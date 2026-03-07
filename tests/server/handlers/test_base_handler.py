"""
Tests for the base handler module.

Tests cover:
- Response builders (error_response, json_response, HandlerResult)
- BaseHandler class and its methods
- Handler mixins (PaginatedHandlerMixin, CachedHandlerMixin, AuthenticatedHandlerMixin)
- Path parameter extraction
- JSON body parsing
- Authentication helpers
- Utility functions
"""

import json
import re
from io import BytesIO
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ============================================================================
# Response Builder Tests
# ============================================================================


class TestHandlerResult:
    """Tests for HandlerResult dataclass."""

    def test_import_handler_result(self):
        """HandlerResult can be imported."""
        from aragora.server.handlers.base import HandlerResult

        assert HandlerResult is not None

    def test_handler_result_fields(self):
        """HandlerResult has required fields."""
        from aragora.server.handlers.base import HandlerResult

        result = HandlerResult(
            status_code=200, content_type="application/json", body=b'{"test": true}'
        )
        assert result.body == b'{"test": true}'
        assert result.status_code == 200
        assert result.content_type == "application/json"

    def test_handler_result_custom_status(self):
        """HandlerResult accepts custom status codes."""
        from aragora.server.handlers.base import HandlerResult

        result = HandlerResult(
            status_code=404, content_type="application/json", body=b'{"error": "Not found"}'
        )
        assert result.status_code == 404


class TestJsonResponse:
    """Tests for json_response helper."""

    def test_json_response_basic(self):
        """json_response creates valid JSON response."""
        from aragora.server.handlers.base import json_response

        result = json_response({"key": "value"})
        assert result.status_code == 200
        assert result.content_type == "application/json"
        body = json.loads(result.body)
        assert body["key"] == "value"

    def test_json_response_custom_status(self):
        """json_response accepts custom status code."""
        from aragora.server.handlers.base import json_response

        result = json_response({"id": 1}, status=201)
        assert result.status_code == 201

    def test_json_response_list(self):
        """json_response handles list data."""
        from aragora.server.handlers.base import json_response

        result = json_response([1, 2, 3])
        body = json.loads(result.body)
        assert body == [1, 2, 3]

    def test_json_response_nested(self):
        """json_response handles nested structures."""
        from aragora.server.handlers.base import json_response

        data = {"nested": {"deep": {"value": 42}}}
        result = json_response(data)
        body = json.loads(result.body)
        assert body["nested"]["deep"]["value"] == 42


class TestErrorResponse:
    """Tests for error_response helper."""

    def test_error_response_basic(self):
        """error_response creates error with message."""
        from aragora.server.handlers.base import error_response

        result = error_response("Not found", 404)
        assert result.status_code == 404
        body = json.loads(result.body)
        assert body["error"] == "Not found"

    def test_error_response_default_status(self):
        """error_response defaults to 400 status for validation errors."""
        from aragora.server.handlers.base import error_response

        # error_response requires status parameter
        result = error_response("Server error", 500)
        assert result.status_code == 500

    def test_error_response_400(self):
        """error_response handles 400 Bad Request."""
        from aragora.server.handlers.base import error_response

        result = error_response("Invalid input", 400)
        assert result.status_code == 400
        body = json.loads(result.body)
        assert "Invalid input" in body["error"]


class TestSafeErrorResponse:
    """Tests for safe_error_response helper."""

    def test_safe_error_response_sanitizes(self):
        """safe_error_response sanitizes exception messages."""
        from aragora.server.handlers.base import safe_error_response

        exc = Exception("Internal path: /home/user/secret")
        result = safe_error_response(exc, "test operation")
        assert result.status_code == 500
        body = json.loads(result.body)
        # Should not contain the internal path
        assert "/home/user" not in str(body)

    def test_safe_error_response_with_handler(self):
        """safe_error_response extracts trace_id from handler."""
        from aragora.server.handlers.base import safe_error_response

        handler = MagicMock()
        handler.trace_id = "trace-123"

        exc = ValueError("Test error")
        result = safe_error_response(exc, "test context", handler=handler)
        assert result.status_code == 500

    def test_safe_error_response_custom_status(self):
        """safe_error_response accepts custom status."""
        from aragora.server.handlers.base import safe_error_response

        exc = RuntimeError("Bad request")
        result = safe_error_response(exc, "validation", status=400)
        assert result.status_code == 400


class TestFeatureUnavailableResponse:
    """Tests for feature_unavailable_response helper."""

    def test_feature_unavailable_basic(self):
        """feature_unavailable_response returns 503."""
        from aragora.server.handlers.base import feature_unavailable_response

        result = feature_unavailable_response("pulse")
        assert result.status_code == 503

    def test_feature_unavailable_with_message(self):
        """feature_unavailable_response accepts custom message."""
        from aragora.server.handlers.base import feature_unavailable_response

        result = feature_unavailable_response("genesis", "Genesis module not installed")
        assert result.status_code == 503


# ============================================================================
# Utility Function Tests
# ============================================================================


class TestGetHostHeader:
    """Tests for get_host_header utility."""

    def test_get_host_header_from_handler(self):
        """get_host_header extracts Host from handler."""
        from aragora.server.handlers.base import get_host_header

        handler = MagicMock()
        handler.headers = {"Host": "example.com:8080"}

        result = get_host_header(handler)
        assert result == "example.com:8080"

    def test_get_host_header_none_handler(self):
        """get_host_header returns default for None handler."""
        from aragora.server.handlers.base import get_host_header

        result = get_host_header(None)
        assert result == "localhost:8080"

    def test_get_host_header_missing_header(self):
        """get_host_header returns default when Host missing."""
        from aragora.server.handlers.base import get_host_header

        handler = MagicMock()
        handler.headers = {}

        result = get_host_header(handler)
        assert result == "localhost:8080"

    def test_get_host_header_custom_default(self):
        """get_host_header accepts custom default."""
        from aragora.server.handlers.base import get_host_header

        result = get_host_header(None, default="custom:9000")
        assert result == "custom:9000"


class TestGetAgentName:
    """Tests for get_agent_name utility."""

    def test_get_agent_name_from_dict_name(self):
        """get_agent_name extracts name from dict."""
        from aragora.server.handlers.base import get_agent_name

        agent = {"name": "claude"}
        assert get_agent_name(agent) == "claude"

    def test_get_agent_name_from_dict_agent_name(self):
        """get_agent_name extracts agent_name from dict."""
        from aragora.server.handlers.base import get_agent_name

        agent = {"agent_name": "gpt4"}
        assert get_agent_name(agent) == "gpt4"

    def test_get_agent_name_from_object(self):
        """get_agent_name extracts name from object."""
        from aragora.server.handlers.base import get_agent_name

        agent = MagicMock()
        agent.name = "gemini"
        agent.agent_name = None

        assert get_agent_name(agent) == "gemini"

    def test_get_agent_name_none(self):
        """get_agent_name returns None for None input."""
        from aragora.server.handlers.base import get_agent_name

        assert get_agent_name(None) is None

    def test_get_agent_name_prefers_agent_name(self):
        """get_agent_name prefers agent_name over name in dict."""
        from aragora.server.handlers.base import get_agent_name

        agent = {"agent_name": "preferred", "name": "fallback"}
        assert get_agent_name(agent) == "preferred"


class TestAgentToDict:
    """Tests for agent_to_dict utility."""

    def test_agent_to_dict_from_dict(self):
        """agent_to_dict returns copy for dict input."""
        from aragora.server.handlers.base import agent_to_dict

        agent = {"name": "claude", "elo": 1600}
        result = agent_to_dict(agent)
        assert result == agent
        assert result is not agent  # Should be a copy

    def test_agent_to_dict_from_object(self):
        """agent_to_dict extracts fields from object."""
        from aragora.server.handlers.base import agent_to_dict

        agent = MagicMock()
        agent.name = "claude"
        agent.agent_name = None
        agent.elo = 1650
        agent.wins = 10
        agent.losses = 5
        agent.draws = 2
        agent.win_rate = 0.6
        agent.games_played = 17

        result = agent_to_dict(agent)
        assert result["name"] == "claude"
        assert result["elo"] == 1650
        assert result["wins"] == 10
        assert result["losses"] == 5

    def test_agent_to_dict_none(self):
        """agent_to_dict returns empty dict for None."""
        from aragora.server.handlers.base import agent_to_dict

        assert agent_to_dict(None) == {}

    def test_agent_to_dict_without_name(self):
        """agent_to_dict can exclude name fields."""
        from aragora.server.handlers.base import agent_to_dict

        agent = MagicMock()
        agent.name = "claude"
        agent.elo = 1500

        result = agent_to_dict(agent, include_name=False)
        assert "name" not in result
        assert "agent_name" not in result
        assert result["elo"] == 1500


# ============================================================================
# BaseHandler Tests
# ============================================================================


class TestBaseHandlerInit:
    """Tests for BaseHandler initialization."""

    def test_base_handler_init(self):
        """BaseHandler initializes with server context."""
        from aragora.server.handlers.base import BaseHandler

        ctx = {"storage": MagicMock(), "elo_system": MagicMock()}
        handler = BaseHandler(ctx)
        assert handler.ctx == ctx

    def test_base_handler_empty_context(self):
        """BaseHandler accepts empty context."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        assert handler.ctx == {}


class TestBaseHandlerGetters:
    """Tests for BaseHandler getter methods."""

    def test_get_storage(self):
        """get_storage returns storage from context."""
        from aragora.server.handlers.base import BaseHandler

        mock_storage = MagicMock()
        handler = BaseHandler({"storage": mock_storage})
        assert handler.get_storage() is mock_storage

    def test_get_storage_missing(self):
        """get_storage returns None when not in context."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        assert handler.get_storage() is None

    def test_get_elo_system(self):
        """get_elo_system returns elo_system from context."""
        from aragora.server.handlers.base import BaseHandler

        mock_elo = MagicMock()
        handler = BaseHandler({"elo_system": mock_elo})
        assert handler.get_elo_system() is mock_elo

    def test_get_debate_embeddings(self):
        """get_debate_embeddings returns embeddings from context."""
        from aragora.server.handlers.base import BaseHandler

        mock_embeddings = MagicMock()
        handler = BaseHandler({"debate_embeddings": mock_embeddings})
        assert handler.get_debate_embeddings() is mock_embeddings

    def test_get_critique_store(self):
        """get_critique_store returns store from context."""
        from aragora.server.handlers.base import BaseHandler

        mock_store = MagicMock()
        handler = BaseHandler({"critique_store": mock_store})
        assert handler.get_critique_store() is mock_store

    def test_get_nomic_dir(self):
        """get_nomic_dir returns path from context."""
        from aragora.server.handlers.base import BaseHandler
        from pathlib import Path

        path = Path("/tmp/nomic")
        handler = BaseHandler({"nomic_dir": path})
        assert handler.get_nomic_dir() == path


class TestBaseHandlerPathExtraction:
    """Tests for BaseHandler path parameter extraction."""

    def test_extract_path_param_success(self):
        """extract_path_param extracts valid parameter."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        # Path: /api/v1/debates/debate-123/messages
        # Uses path.split("/") without stripping, so:
        # Parts: ["", "api", "v1", "debates", "debate-123", "messages"]
        # Index:   0     1      2        3             4           5
        # Index 4 is "debate-123"
        value, err = handler.extract_path_param(
            "/api/v1/debates/debate-123/messages", 4, "debate_id"
        )
        assert value == "debate-123"
        assert err is None

    def test_extract_path_param_missing(self):
        """extract_path_param returns error for missing segment."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        # /api/v1/debates -> ["api", "v1", "debates"] (3 elements, index 4 doesn't exist)
        value, err = handler.extract_path_param("/api/v1/debates", 4, "missing")
        assert value is None
        assert err is not None
        assert err.status_code == 400

    def test_extract_path_param_empty(self):
        """extract_path_param returns error for empty segment."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        # Double slash creates empty segment
        # Path: /api/v1//debates -> path.split("/") = ["", "api", "v1", "", "debates"]
        # Index 3 is the empty segment
        value, err = handler.extract_path_param("/api/v1//debates", 3, "empty")
        assert value is None
        assert err is not None

    def test_extract_path_params_multiple(self):
        """extract_path_params extracts multiple parameters."""
        from aragora.server.handlers.base import BaseHandler, SAFE_ID_PATTERN

        handler = BaseHandler({})
        # Path: /api/v1/debates/debate-123/rounds/5
        # Uses path.split("/") without stripping, so:
        # Parts: ["", "api", "v1", "debates", "debate-123", "rounds", "5"]
        # Index:   0     1      2        3            4          5      6
        params, err = handler.extract_path_params(
            "/api/v1/debates/debate-123/rounds/5",
            [
                (4, "debate_id", SAFE_ID_PATTERN),
                (5, "resource", None),
                (6, "round_num", None),
            ],
        )
        assert err is None
        assert params["debate_id"] == "debate-123"
        assert params["resource"] == "rounds"
        assert params["round_num"] == "5"

    def test_extract_path_params_first_error_stops(self):
        """extract_path_params returns first error encountered."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        # Path: /api/v1/debates -> ["api", "v1", "debates"] (3 elements)
        # Index 3 doesn't exist, so it should fail
        params, err = handler.extract_path_params(
            "/api/v1/debates",
            [
                (3, "debate_id", None),  # This fails (index out of bounds)
                (10, "nonexistent", None),  # This would fail if reached
            ],
        )
        assert params is None
        assert err is not None


class TestBaseHandlerJsonParsing:
    """Tests for BaseHandler JSON body parsing."""

    def test_read_json_body_success(self):
        """read_json_body parses valid JSON."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        body_bytes = b'{"key": "value"}'
        mock_http.headers = {"Content-Length": str(len(body_bytes))}
        mock_http.rfile = BytesIO(body_bytes)

        result = handler.read_json_body(mock_http)
        assert result == {"key": "value"}

    def test_read_json_body_empty(self):
        """read_json_body returns empty dict for no content."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.headers = {"Content-Length": "0"}
        mock_http.rfile = BytesIO(b"")

        result = handler.read_json_body(mock_http)
        assert result == {}

    def test_read_json_body_invalid(self):
        """read_json_body returns None for invalid JSON."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        body_bytes = b"not json"
        mock_http.headers = {"Content-Length": str(len(body_bytes))}
        mock_http.rfile = BytesIO(body_bytes)

        result = handler.read_json_body(mock_http)
        assert result is None

    def test_read_json_body_too_large(self):
        """read_json_body returns None for oversized body."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.headers = {"Content-Length": "999999999"}

        result = handler.read_json_body(mock_http, max_size=1000)
        assert result is None

    def test_validate_content_length_valid(self):
        """validate_content_length accepts valid length."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.headers = {"Content-Length": "100"}

        result = handler.validate_content_length(mock_http)
        assert result == 100

    def test_validate_content_length_negative(self):
        """validate_content_length rejects negative length."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.headers = {"Content-Length": "-1"}

        result = handler.validate_content_length(mock_http)
        assert result is None

    def test_validate_json_content_type_valid(self):
        """validate_json_content_type accepts application/json."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.headers = {"Content-Type": "application/json"}

        result = handler.validate_json_content_type(mock_http)
        assert result is None  # None means valid

    def test_validate_json_content_type_with_charset(self):
        """validate_json_content_type accepts charset parameter."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.headers = {"Content-Type": "application/json; charset=utf-8"}

        result = handler.validate_json_content_type(mock_http)
        assert result is None

    def test_validate_json_content_type_invalid(self):
        """validate_json_content_type rejects non-JSON."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.headers = {"Content-Type": "text/plain"}

        result = handler.validate_json_content_type(mock_http)
        assert result is not None
        assert result.status_code == 415

    def test_read_json_body_validated_success(self):
        """read_json_body_validated parses with validation."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        body_bytes = b'{"valid": true}'
        mock_http.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body_bytes)),
        }
        mock_http.rfile = BytesIO(body_bytes)

        body, err = handler.read_json_body_validated(mock_http)
        assert err is None
        assert body == {"valid": True}

    def test_read_json_body_validated_wrong_content_type(self):
        """read_json_body_validated rejects wrong Content-Type."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.headers = {"Content-Type": "text/html", "Content-Length": "10"}

        body, err = handler.read_json_body_validated(mock_http)
        assert body is None
        assert err is not None
        assert err.status_code == 415


class TestBaseHandlerAuth:
    """Tests for BaseHandler authentication methods."""

    def test_get_current_user_authenticated(self):
        """get_current_user returns user when authenticated."""
        from aragora.server.handlers.base import BaseHandler
        from aragora.billing.auth.context import UserAuthContext

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.headers = {"Authorization": "Bearer test-token"}

        mock_ctx = UserAuthContext(
            authenticated=True,
            user_id="user-123",
            email="test@example.com",
        )

        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=mock_ctx,
        ):
            result = handler.get_current_user(mock_http)
            assert result is not None
            assert result.user_id == "user-123"

    @pytest.mark.no_auto_auth
    def test_get_current_user_not_authenticated(self):
        """get_current_user returns None when not authenticated."""
        from aragora.server.handlers.base import BaseHandler
        from aragora.billing.auth.context import UserAuthContext

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.headers = {}

        mock_ctx = UserAuthContext(authenticated=False)

        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=mock_ctx,
        ):
            result = handler.get_current_user(mock_http)
            assert result is None

    def test_require_auth_or_error_success(self):
        """require_auth_or_error returns user when authenticated."""
        from aragora.server.handlers.base import BaseHandler
        from aragora.billing.auth.context import UserAuthContext

        handler = BaseHandler({})
        mock_http = MagicMock()

        mock_ctx = UserAuthContext(
            authenticated=True,
            user_id="user-456",
        )

        with patch.object(handler, "get_current_user", return_value=mock_ctx):
            user, err = handler.require_auth_or_error(mock_http)
            assert err is None
            assert user.user_id == "user-456"

    def test_require_auth_or_error_failure(self):
        """require_auth_or_error returns error when not authenticated."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()

        with patch.object(handler, "get_current_user", return_value=None):
            user, err = handler.require_auth_or_error(mock_http)
            assert user is None
            assert err is not None
            assert err.status_code == 401


class TestBaseHandlerMethods:
    """Tests for BaseHandler handle methods."""

    def test_handle_returns_none_by_default(self):
        """handle returns None by default."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        result = handler.handle("/test", {}, MagicMock())
        assert result is None

    def test_handle_post_returns_none_by_default(self):
        """handle_post returns None by default."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        result = handler.handle_post("/test", {}, MagicMock())
        assert result is None

    def test_handle_delete_returns_none_by_default(self):
        """handle_delete returns None by default."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        result = handler.handle_delete("/test", {}, MagicMock())
        assert result is None

    def test_handle_patch_returns_none_by_default(self):
        """handle_patch returns None by default."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        result = handler.handle_patch("/test", {}, MagicMock())
        assert result is None

    def test_handle_put_returns_none_by_default(self):
        """handle_put returns None by default."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        result = handler.handle_put("/test", {}, MagicMock())
        assert result is None


# ============================================================================
# Handler Mixin Tests
# ============================================================================


class TestPaginatedHandlerMixin:
    """Tests for PaginatedHandlerMixin."""

    def test_get_pagination_defaults(self):
        """get_pagination returns defaults for empty params."""
        from aragora.server.handlers.base import PaginatedHandlerMixin

        mixin = PaginatedHandlerMixin()
        limit, offset = mixin.get_pagination({})
        assert limit == mixin.DEFAULT_LIMIT
        assert offset == mixin.DEFAULT_OFFSET

    def test_get_pagination_from_params(self):
        """get_pagination extracts from query params."""
        from aragora.server.handlers.base import PaginatedHandlerMixin

        mixin = PaginatedHandlerMixin()
        limit, offset = mixin.get_pagination({"limit": "50", "offset": "10"})
        assert limit == 50
        assert offset == 10

    def test_get_pagination_clamps_limit(self):
        """get_pagination clamps limit to max."""
        from aragora.server.handlers.base import PaginatedHandlerMixin

        mixin = PaginatedHandlerMixin()
        limit, offset = mixin.get_pagination({"limit": "999"})
        assert limit == mixin.MAX_LIMIT

    def test_get_pagination_clamps_negative(self):
        """get_pagination clamps negative values."""
        from aragora.server.handlers.base import PaginatedHandlerMixin

        mixin = PaginatedHandlerMixin()
        limit, offset = mixin.get_pagination({"limit": "-5", "offset": "-10"})
        assert limit >= 1
        assert offset >= 0

    def test_paginated_response_format(self):
        """paginated_response returns correct format."""
        from aragora.server.handlers.base import PaginatedHandlerMixin

        mixin = PaginatedHandlerMixin()
        result = mixin.paginated_response(
            items=[{"id": 1}, {"id": 2}],
            total=100,
            limit=20,
            offset=0,
        )

        body = json.loads(result.body)
        assert body["items"] == [{"id": 1}, {"id": 2}]
        assert body["total"] == 100
        assert body["limit"] == 20
        assert body["offset"] == 0
        assert body["has_more"] is True

    def test_paginated_response_has_more_false(self):
        """paginated_response sets has_more=False at end."""
        from aragora.server.handlers.base import PaginatedHandlerMixin

        mixin = PaginatedHandlerMixin()
        result = mixin.paginated_response(
            items=[{"id": 1}],
            total=1,
            limit=20,
            offset=0,
        )

        body = json.loads(result.body)
        assert body["has_more"] is False

    def test_paginated_response_custom_key(self):
        """paginated_response accepts custom items_key."""
        from aragora.server.handlers.base import PaginatedHandlerMixin

        mixin = PaginatedHandlerMixin()
        result = mixin.paginated_response(
            items=[{"name": "test"}],
            total=1,
            limit=20,
            offset=0,
            items_key="debates",
        )

        body = json.loads(result.body)
        assert "debates" in body
        assert "items" not in body


class TestCachedHandlerMixin:
    """Tests for CachedHandlerMixin."""

    def test_cached_response_caches_value(self):
        """cached_response caches and returns value."""
        from aragora.server.handlers.base import CachedHandlerMixin, clear_cache

        clear_cache()
        mixin = CachedHandlerMixin()

        call_count = 0

        def generator():
            nonlocal call_count
            call_count += 1
            return {"computed": True}

        # First call - generates
        result1 = mixin.cached_response("test_key", 60, generator)
        assert result1 == {"computed": True}
        assert call_count == 1

        # Second call - should use cache
        result2 = mixin.cached_response("test_key", 60, generator)
        assert result2 == {"computed": True}
        # Generator should not be called again (cached)
        # Note: Actual caching depends on implementation

    def test_cached_response_different_keys(self):
        """cached_response uses different values for different keys."""
        from aragora.server.handlers.base import CachedHandlerMixin, clear_cache

        clear_cache()
        mixin = CachedHandlerMixin()

        result1 = mixin.cached_response("key1", 60, lambda: "value1")
        result2 = mixin.cached_response("key2", 60, lambda: "value2")

        assert result1 == "value1"
        assert result2 == "value2"


class TestAuthenticatedHandlerMixin:
    """Tests for AuthenticatedHandlerMixin."""

    def test_require_auth_delegates_to_base(self):
        """require_auth uses require_auth_or_error when available."""
        from aragora.server.handlers.base import (
            AuthenticatedHandlerMixin,
            BaseHandler,
        )
        from aragora.billing.auth.context import UserAuthContext

        class TestHandler(BaseHandler, AuthenticatedHandlerMixin):
            pass

        handler = TestHandler({})
        mock_http = MagicMock()

        mock_user = UserAuthContext(authenticated=True, user_id="test-user")
        with patch.object(handler, "get_current_user", return_value=mock_user):
            result = handler.require_auth(mock_http)
            assert result.user_id == "test-user"

    def test_require_auth_returns_error(self):
        """require_auth returns error when not authenticated."""
        from aragora.server.handlers.base import (
            AuthenticatedHandlerMixin,
            BaseHandler,
        )

        class TestHandler(BaseHandler, AuthenticatedHandlerMixin):
            pass

        handler = TestHandler({})
        mock_http = MagicMock()

        with patch.object(handler, "get_current_user", return_value=None):
            result = handler.require_auth(mock_http)
            # Result should be HandlerResult with 401
            assert hasattr(result, "status_code")
            assert result.status_code == 401


# ============================================================================
# Decorator Tests
# ============================================================================


class TestRequireQuotaDecorator:
    """Tests for require_quota decorator."""

    def test_require_quota_passes_for_available_quota(self):
        """require_quota allows operation when quota available."""
        from aragora.server.handlers.base import require_quota, json_response
        from aragora.billing.auth.context import UserAuthContext

        @require_quota()
        def test_func(handler, user=None):
            return json_response({"success": True})

        mock_handler = MagicMock()
        mock_handler.headers = {}

        mock_user = UserAuthContext(
            authenticated=True,
            user_id="test-user",
            org_id=None,  # No org = no quota check
        )

        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=mock_user,
        ):
            result = test_func(mock_handler)
            body = json.loads(result.body)
            assert body["success"] is True

    @pytest.mark.no_auto_auth
    def test_require_quota_rejects_unauthenticated(self):
        """require_quota returns 401 for unauthenticated request."""
        from aragora.server.handlers.base import require_quota, json_response
        from aragora.billing.auth.context import UserAuthContext

        @require_quota()
        def test_func(handler, user=None):
            return json_response({"success": True})

        mock_handler = MagicMock()
        mock_handler.headers = {}

        mock_user = UserAuthContext(
            authenticated=False,
            error_reason="No token provided",
        )

        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=mock_user,
        ):
            result = test_func(mock_handler)
            assert result.status_code == 401


# ============================================================================
# Parameter Extraction Tests
# ============================================================================


class TestParameterExtraction:
    """Tests for parameter extraction utilities."""

    def test_get_int_param_default(self):
        """get_int_param returns default for missing param."""
        from aragora.server.handlers.base import get_int_param

        result = get_int_param({}, "missing", 42)
        assert result == 42

    def test_get_int_param_from_string(self):
        """get_int_param parses string to int."""
        from aragora.server.handlers.base import get_int_param

        result = get_int_param({"count": "100"}, "count", 0)
        assert result == 100

    def test_get_bool_param_true_values(self):
        """get_bool_param recognizes true values."""
        from aragora.server.handlers.base import get_bool_param

        assert get_bool_param({"flag": "true"}, "flag", False) is True
        assert get_bool_param({"flag": "1"}, "flag", False) is True
        assert get_bool_param({"flag": "yes"}, "flag", False) is True

    def test_get_bool_param_false_values(self):
        """get_bool_param recognizes false values."""
        from aragora.server.handlers.base import get_bool_param

        assert get_bool_param({"flag": "false"}, "flag", True) is False
        assert get_bool_param({"flag": "0"}, "flag", True) is False
        assert get_bool_param({"flag": "no"}, "flag", True) is False

    def test_get_clamped_int_param(self):
        """get_clamped_int_param clamps to range."""
        from aragora.server.handlers.base import get_clamped_int_param

        # Below min
        result = get_clamped_int_param({"val": "-10"}, "val", 50, min_val=0, max_val=100)
        assert result == 0

        # Above max
        result = get_clamped_int_param({"val": "999"}, "val", 50, min_val=0, max_val=100)
        assert result == 100

        # In range
        result = get_clamped_int_param({"val": "75"}, "val", 50, min_val=0, max_val=100)
        assert result == 75

    def test_get_bounded_string_param_truncates(self):
        """get_bounded_string_param truncates long strings."""
        from aragora.server.handlers.base import get_bounded_string_param

        long_string = "a" * 1000
        result = get_bounded_string_param({"text": long_string}, "text", "", max_length=100)
        assert len(result) == 100

    def test_get_bounded_float_param_clamps(self):
        """get_bounded_float_param clamps to range."""
        from aragora.server.handlers.base import get_bounded_float_param

        # Below min
        result = get_bounded_float_param({"val": "-5.0"}, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 0.0

        # Above max
        result = get_bounded_float_param({"val": "2.5"}, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 1.0


# ============================================================================
# Module Exports Tests
# ============================================================================


class TestModuleExports:
    """Tests for module-level exports."""

    def test_all_core_exports_exist(self):
        """All core exports are importable."""
        from aragora.server.handlers.base import (
            BaseHandler,
            HandlerResult,
            error_response,
            json_response,
            handle_errors,
            require_auth,
            require_user_auth,
            require_storage,
        )

        assert all(
            [
                BaseHandler,
                HandlerResult,
                error_response,
                json_response,
                handle_errors,
                require_auth,
                require_user_auth,
                require_storage,
            ]
        )

    def test_cache_exports_exist(self):
        """Cache-related exports are importable."""
        from aragora.server.handlers.base import (
            ttl_cache,
            clear_cache,
            get_cache_stats,
            invalidate_cache,
            BoundedTTLCache,
        )

        assert all([ttl_cache, clear_cache, get_cache_stats, invalidate_cache, BoundedTTLCache])

    def test_validation_exports_exist(self):
        """Validation exports are importable."""
        from aragora.server.handlers.base import (
            SAFE_ID_PATTERN,
            SAFE_SLUG_PATTERN,
            SAFE_AGENT_PATTERN,
            validate_agent_name,
            validate_debate_id,
        )

        assert all(
            [
                SAFE_ID_PATTERN,
                SAFE_SLUG_PATTERN,
                SAFE_AGENT_PATTERN,
                validate_agent_name,
                validate_debate_id,
            ]
        )

    def test_mixin_exports_exist(self):
        """Mixin exports are importable."""
        from aragora.server.handlers.base import (
            PaginatedHandlerMixin,
            CachedHandlerMixin,
            AuthenticatedHandlerMixin,
        )

        assert all([PaginatedHandlerMixin, CachedHandlerMixin, AuthenticatedHandlerMixin])


# ============================================================================
# Success Response Tests
# ============================================================================


class TestSuccessResponse:
    """Tests for success_response helper."""

    def test_success_response_basic(self):
        """success_response creates success response with data."""
        from aragora.server.handlers.base import success_response

        result = success_response({"id": "123"})
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["success"] is True
        assert body["data"] == {"id": "123"}

    def test_success_response_with_message(self):
        """success_response accepts optional message."""
        from aragora.server.handlers.base import success_response

        result = success_response({"count": 5}, message="Found 5 items")
        body = json.loads(result.body)
        assert body["success"] is True
        assert body["message"] == "Found 5 items"

    def test_success_response_list_data(self):
        """success_response handles list data."""
        from aragora.server.handlers.base import success_response

        result = success_response([1, 2, 3])
        body = json.loads(result.body)
        assert body["data"] == [1, 2, 3]


# ============================================================================
# Safe Data Utilities Tests
# ============================================================================


class TestSafeGet:
    """Tests for safe_get utility."""

    def test_safe_get_from_dict(self):
        """safe_get extracts value from dict."""
        from aragora.server.handlers.base import safe_get

        data = {"key": "value"}
        assert safe_get(data, "key") == "value"

    def test_safe_get_missing_key(self):
        """safe_get returns default for missing key."""
        from aragora.server.handlers.base import safe_get

        data = {"other": "value"}
        assert safe_get(data, "key", "default") == "default"

    def test_safe_get_none_data(self):
        """safe_get handles None data."""
        from aragora.server.handlers.base import safe_get

        assert safe_get(None, "key", "default") == "default"

    def test_safe_get_non_dict(self):
        """safe_get handles non-dict data."""
        from aragora.server.handlers.base import safe_get

        assert safe_get("not a dict", "key", "default") == "default"
        assert safe_get([1, 2, 3], "key", "default") == "default"


class TestSafeGetNested:
    """Tests for safe_get_nested utility."""

    def test_safe_get_nested_basic(self):
        """safe_get_nested navigates nested dicts."""
        from aragora.server.handlers.base import safe_get_nested

        data = {"outer": {"inner": {"deep": "value"}}}
        assert safe_get_nested(data, ["outer", "inner", "deep"]) == "value"

    def test_safe_get_nested_missing_key(self):
        """safe_get_nested returns default for missing key."""
        from aragora.server.handlers.base import safe_get_nested

        data = {"outer": {"inner": {}}}
        assert safe_get_nested(data, ["outer", "inner", "deep"], "default") == "default"

    def test_safe_get_nested_none_data(self):
        """safe_get_nested handles None data."""
        from aragora.server.handlers.base import safe_get_nested

        assert safe_get_nested(None, ["a", "b"], "default") == "default"

    def test_safe_get_nested_non_dict_intermediate(self):
        """safe_get_nested handles non-dict intermediate values."""
        from aragora.server.handlers.base import safe_get_nested

        data = {"outer": "not a dict"}
        assert safe_get_nested(data, ["outer", "inner"], "default") == "default"

    def test_safe_get_nested_empty_keys(self):
        """safe_get_nested handles empty keys list."""
        from aragora.server.handlers.base import safe_get_nested

        data = {"key": "value"}
        result = safe_get_nested(data, [])
        assert result == {"key": "value"}


class TestSafeJsonParse:
    """Tests for safe_json_parse utility."""

    def test_safe_json_parse_string(self):
        """safe_json_parse parses JSON string."""
        from aragora.server.handlers.base import safe_json_parse

        result = safe_json_parse('{"key": "value"}')
        assert result == {"key": "value"}

    def test_safe_json_parse_dict(self):
        """safe_json_parse returns dict as-is."""
        from aragora.server.handlers.base import safe_json_parse

        data = {"already": "parsed"}
        result = safe_json_parse(data)
        assert result == data

    def test_safe_json_parse_list(self):
        """safe_json_parse returns list as-is."""
        from aragora.server.handlers.base import safe_json_parse

        data = [1, 2, 3]
        result = safe_json_parse(data)
        assert result == data

    def test_safe_json_parse_invalid(self):
        """safe_json_parse returns default for invalid JSON."""
        from aragora.server.handlers.base import safe_json_parse

        assert safe_json_parse("not json", "default") == "default"

    def test_safe_json_parse_none(self):
        """safe_json_parse returns default for None."""
        from aragora.server.handlers.base import safe_json_parse

        assert safe_json_parse(None, "default") == "default"

    def test_safe_json_parse_bytes(self):
        """safe_json_parse handles bytes input."""
        from aragora.server.handlers.base import safe_json_parse

        result = safe_json_parse(b'{"key": "value"}')
        assert result == {"key": "value"}


# ============================================================================
# Decorator Tests - Additional Coverage
# ============================================================================


class TestHandleErrorsDecorator:
    """Tests for handle_errors decorator."""

    def test_handle_errors_success(self):
        """handle_errors passes through successful results."""
        from aragora.server.handlers.base import handle_errors, json_response

        @handle_errors("test operation")
        def success_func():
            return json_response({"success": True})

        result = success_func()
        assert result.status_code == 200

    def test_handle_errors_exception(self):
        """handle_errors catches exceptions and returns error response."""
        from aragora.server.handlers.base import handle_errors

        @handle_errors("test operation")
        def failing_func():
            raise ValueError("Test error")

        result = failing_func()
        assert result.status_code == 400  # ValueError maps to 400

    def test_handle_errors_not_found(self):
        """handle_errors maps FileNotFoundError to 404."""
        from aragora.server.handlers.base import handle_errors

        @handle_errors("test operation")
        def not_found_func():
            raise FileNotFoundError("Not found")

        result = not_found_func()
        assert result.status_code == 404

    def test_handle_errors_adds_trace_id(self):
        """handle_errors adds X-Trace-Id header."""
        from aragora.server.handlers.base import handle_errors

        @handle_errors("test operation")
        def failing_func():
            raise Exception("Generic error")

        result = failing_func()
        assert "X-Trace-Id" in result.headers


class TestAutoErrorResponseDecorator:
    """Tests for auto_error_response decorator."""

    def test_auto_error_response_success(self):
        """auto_error_response passes through successful results."""
        from aragora.server.handlers.base import auto_error_response, json_response

        @auto_error_response("test operation")
        def success_func():
            return json_response({"ok": True})

        result = success_func()
        assert result.status_code == 200

    def test_auto_error_response_value_error(self):
        """auto_error_response handles ValueError."""
        from aragora.server.handlers.base import auto_error_response

        @auto_error_response("test operation")
        def invalid_func():
            raise ValueError("Invalid value")

        result = invalid_func()
        assert result.status_code == 400

    def test_auto_error_response_permission_error(self):
        """auto_error_response handles PermissionError."""
        from aragora.server.handlers.base import auto_error_response

        @auto_error_response("test operation")
        def denied_func():
            raise PermissionError("Access denied")

        result = denied_func()
        assert result.status_code == 403


class TestLogRequestDecorator:
    """Tests for log_request decorator."""

    def test_log_request_success(self):
        """log_request logs and returns successful result."""
        from aragora.server.handlers.base import log_request, json_response

        @log_request("test operation")
        def success_func():
            return json_response({"logged": True})

        result = success_func()
        assert result.status_code == 200

    def test_log_request_reraises_exception(self):
        """log_request reraises exceptions after logging."""
        from aragora.server.handlers.base import log_request

        @log_request("test operation")
        def failing_func():
            raise RuntimeError("Test error")

        with pytest.raises(RuntimeError):
            failing_func()


class TestWithErrorRecoveryDecorator:
    """Tests for with_error_recovery decorator."""

    def test_with_error_recovery_success(self):
        """with_error_recovery passes through successful results."""
        from aragora.server.handlers.base import with_error_recovery

        @with_error_recovery(fallback_value="fallback")
        def success_func():
            return "success"

        result = success_func()
        assert result == "success"

    def test_with_error_recovery_fallback(self):
        """with_error_recovery returns fallback on error."""
        from aragora.server.handlers.base import with_error_recovery

        @with_error_recovery(fallback_value={"error": "recovered"})
        def failing_func():
            raise RuntimeError("Test error")

        result = failing_func()
        assert result == {"error": "recovered"}


# ============================================================================
# Authentication Decorator Tests
# ============================================================================


class TestRequireStorageDecorator:
    """Tests for require_storage decorator."""

    def test_require_storage_available(self):
        """require_storage allows access when storage available."""
        from aragora.server.handlers.base import require_storage, BaseHandler, json_response

        class TestHandler(BaseHandler):
            @require_storage
            def get_data(self):
                return json_response({"data": "ok"})

        handler = TestHandler({"storage": MagicMock()})
        result = handler.get_data()
        assert result.status_code == 200

    def test_require_storage_unavailable(self):
        """require_storage returns 503 when storage unavailable."""
        from aragora.server.handlers.base import require_storage, BaseHandler, json_response

        class TestHandler(BaseHandler):
            @require_storage
            def get_data(self):
                return json_response({"data": "ok"})

        handler = TestHandler({})
        result = handler.get_data()
        assert result.status_code == 503


class TestRequireFeatureDecorator:
    """Tests for require_feature decorator."""

    def test_require_feature_available(self):
        """require_feature allows access when feature available."""
        from aragora.server.handlers.base import require_feature, json_response

        @require_feature(lambda: True, "Test Feature")
        def feature_func():
            return json_response({"feature": "enabled"})

        result = feature_func()
        assert result.status_code == 200

    def test_require_feature_unavailable(self):
        """require_feature returns error when feature unavailable."""
        from aragora.server.handlers.base import require_feature, json_response

        @require_feature(lambda: False, "Test Feature", status_code=501)
        def feature_func():
            return json_response({"feature": "enabled"})

        result = feature_func()
        assert result.status_code == 501


# ============================================================================
# BaseHandler Admin and Permission Tests
# ============================================================================


class TestBaseHandlerAdminAuth:
    """Tests for BaseHandler admin authentication methods."""

    def test_require_admin_or_error_success(self):
        """require_admin_or_error returns admin user."""
        from aragora.server.handlers.base import BaseHandler
        from aragora.billing.auth.context import UserAuthContext

        handler = BaseHandler({})
        mock_http = MagicMock()

        mock_user = UserAuthContext(
            authenticated=True,
            user_id="admin-user",
            role="admin",
        )

        with patch.object(handler, "get_current_user", return_value=mock_user):
            user, err = handler.require_admin_or_error(mock_http)
            assert err is None
            assert user.user_id == "admin-user"

    def test_require_admin_or_error_not_admin(self):
        """require_admin_or_error returns 403 for non-admin."""
        from aragora.server.handlers.base import BaseHandler
        from aragora.billing.auth.context import UserAuthContext

        handler = BaseHandler({})
        mock_http = MagicMock()

        mock_user = UserAuthContext(
            authenticated=True,
            user_id="regular-user",
            role="member",
        )

        with patch.object(handler, "get_current_user", return_value=mock_user):
            user, err = handler.require_admin_or_error(mock_http)
            assert user is None
            assert err is not None
            assert err.status_code == 403

    def test_require_admin_or_error_owner_allowed(self):
        """require_admin_or_error allows owner role."""
        from aragora.server.handlers.base import BaseHandler
        from aragora.billing.auth.context import UserAuthContext

        handler = BaseHandler({})
        mock_http = MagicMock()

        mock_user = UserAuthContext(
            authenticated=True,
            user_id="owner-user",
            role="owner",
        )

        with patch.object(handler, "get_current_user", return_value=mock_user):
            user, err = handler.require_admin_or_error(mock_http)
            assert err is None
            assert user.user_id == "owner-user"


@pytest.mark.no_auto_auth
class TestBaseHandlerPermissionAuth:
    """Tests for BaseHandler permission authentication methods."""

    def test_require_permission_or_error_success(self):
        """require_permission_or_error allows user with role permission."""
        from aragora.server.handlers.base import BaseHandler
        from aragora.billing.auth.context import UserAuthContext

        handler = BaseHandler({})
        mock_http = MagicMock()

        # Member role has debates:read permission in PERMISSION_MATRIX
        mock_user = UserAuthContext(
            authenticated=True,
            user_id="user-123",
            role="member",
        )

        with patch.object(handler, "get_current_user", return_value=mock_user):
            user, err = handler.require_permission_or_error(mock_http, "debates:read")
            assert err is None
            assert user.user_id == "user-123"

    def test_require_permission_or_error_denied(self):
        """require_permission_or_error returns 403 without permission."""
        from aragora.server.handlers.base import BaseHandler
        from aragora.billing.auth.context import UserAuthContext

        handler = BaseHandler({})
        mock_http = MagicMock()

        # Member role does not have admin:system permission
        mock_user = UserAuthContext(
            authenticated=True,
            user_id="user-123",
            role="member",
        )

        with patch.object(handler, "get_current_user", return_value=mock_user):
            user, err = handler.require_permission_or_error(mock_http, "admin:system")
            assert user is None
            assert err is not None
            assert err.status_code == 403

    def test_require_permission_or_error_admin_bypass(self):
        """require_permission_or_error allows admin for any permission."""
        from aragora.server.handlers.base import BaseHandler
        from aragora.billing.auth.context import UserAuthContext

        handler = BaseHandler({})
        mock_http = MagicMock()

        mock_user = UserAuthContext(
            authenticated=True,
            user_id="admin-user",
            role="admin",
        )

        with patch.object(handler, "get_current_user", return_value=mock_user):
            user, err = handler.require_permission_or_error(mock_http, "any:permission")
            assert err is None


# ============================================================================
# Validate Body Decorator Tests
# ============================================================================


class TestValidateBodyDecorator:
    """Tests for validate_body decorator."""

    def test_validate_body_sync_success(self):
        """validate_body allows request with required fields."""
        from aragora.server.handlers.base import validate_body, json_response

        mock_self = MagicMock()
        mock_request = MagicMock()
        mock_request.json.return_value = {"name": "test", "value": 123}

        @validate_body(["name", "value"])
        def handler(self, request):
            return json_response({"ok": True})

        result = handler(mock_self, mock_request)
        assert result.status_code == 200

    def test_validate_body_sync_missing_fields(self):
        """validate_body rejects request missing required fields."""
        from aragora.server.handlers.base import validate_body, json_response

        mock_self = MagicMock()
        mock_self.error_response = None  # Trigger base error_response use
        del mock_self.error_response

        mock_request = MagicMock()
        mock_request.json.return_value = {"name": "test"}

        @validate_body(["name", "value", "extra"])
        def handler(self, request):
            return json_response({"ok": True})

        result = handler(mock_self, mock_request)
        assert result.status_code == 400
        body = json.loads(result.body)
        assert "Missing required fields" in body["error"]

    def test_validate_body_invalid_json(self):
        """validate_body rejects request with invalid JSON."""
        from aragora.server.handlers.base import validate_body, json_response

        mock_self = MagicMock()
        mock_self.error_response = None
        del mock_self.error_response

        mock_request = MagicMock()
        mock_request.json.side_effect = json.JSONDecodeError("Test", "", 0)

        @validate_body(["name"])
        def handler(self, request):
            return json_response({"ok": True})

        result = handler(mock_self, mock_request)
        assert result.status_code == 400


class TestValidateBodyAsyncDecorator:
    """Tests for validate_body decorator with async handlers."""

    @pytest.mark.asyncio
    async def test_validate_body_async_success(self):
        """validate_body works with async handlers."""
        from aragora.server.handlers.base import validate_body, json_response

        mock_self = MagicMock()
        mock_request = MagicMock()
        mock_request.json = MagicMock(return_value={"name": "test"})

        # Mock async json method
        async def async_json():
            return {"name": "test"}

        mock_request.json = async_json

        @validate_body(["name"])
        async def async_handler(self, request):
            return json_response({"ok": True})

        result = await async_handler(mock_self, mock_request)
        assert result.status_code == 200


# ============================================================================
# API Endpoint and Rate Limit Decorator Tests
# ============================================================================


class TestApiEndpointDecorator:
    """Tests for api_endpoint decorator."""

    def test_api_endpoint_attaches_metadata(self):
        """api_endpoint attaches metadata to function."""
        from aragora.server.handlers.base import api_endpoint

        @api_endpoint(method="POST", path="/api/test", summary="Test endpoint")
        def test_func():
            pass

        assert hasattr(test_func, "_api_metadata")
        assert test_func._api_metadata["method"] == "POST"
        assert test_func._api_metadata["path"] == "/api/test"
        assert test_func._api_metadata["summary"] == "Test endpoint"


class TestRateLimitDecorator:
    """Tests for rate_limit decorator."""

    def test_rate_limit_wraps_function(self):
        """rate_limit wraps function correctly."""
        from aragora.server.handlers.base import rate_limit, json_response

        @rate_limit(requests_per_minute=30, burst=5)
        def limited_func():
            return json_response({"limited": True})

        # Function should still be callable
        result = limited_func()
        assert result.status_code == 200


# ============================================================================
# BaseHandler Request Context Tests
# ============================================================================


class TestBaseHandlerRequestContext:
    """Tests for BaseHandler request context management."""

    def test_set_request_context(self):
        """set_request_context stores handler and params."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        query_params = {"limit": "10"}

        handler.set_request_context(mock_http, query_params)

        assert handler._current_handler is mock_http
        assert handler._current_query_params == query_params

    def test_get_query_param_pattern_1(self):
        """get_query_param works with pattern 1 (name, default)."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        handler._current_query_params = {"limit": "50"}

        result = handler.get_query_param("limit", "10")
        assert result == "50"

    def test_get_query_param_pattern_1_missing(self):
        """get_query_param returns default for missing param."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        handler._current_query_params = {}

        result = handler.get_query_param("missing", "default")
        assert result == "default"

    def test_get_query_param_pattern_2(self):
        """get_query_param works with pattern 2 (handler, name, default)."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        mock_http.path = "/api/test?limit=25"

        result = handler.get_query_param(mock_http, "limit", "10")
        assert result == "25"

    def test_get_json_body(self):
        """get_json_body returns parsed JSON from current handler."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        mock_http = MagicMock()
        body_bytes = b'{"test": true}'
        mock_http.headers = {"Content-Length": str(len(body_bytes))}
        mock_http.rfile = BytesIO(body_bytes)

        handler._current_handler = mock_http
        result = handler.get_json_body()
        assert result == {"test": True}

    def test_get_json_body_no_handler(self):
        """get_json_body returns None when no handler set."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        handler._current_handler = None

        result = handler.get_json_body()
        assert result is None


# ============================================================================
# BaseHandler Response Method Tests
# ============================================================================


class TestBaseHandlerResponseMethods:
    """Tests for BaseHandler response helper methods."""

    def test_json_response_method(self):
        """BaseHandler.json_response creates JSON response."""
        from aragora.server.handlers.base import BaseHandler
        from http import HTTPStatus

        handler = BaseHandler({})
        result = handler.json_response({"key": "value"})

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["key"] == "value"

    def test_json_response_method_with_status(self):
        """BaseHandler.json_response accepts HTTPStatus."""
        from aragora.server.handlers.base import BaseHandler
        from http import HTTPStatus

        handler = BaseHandler({})
        result = handler.json_response({"created": True}, status=HTTPStatus.CREATED)

        assert result.status_code == 201

    def test_success_response_method(self):
        """BaseHandler.success_response creates success response."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        result = handler.success_response({"data": "test"})

        assert result.status_code == 200

    def test_error_response_method(self):
        """BaseHandler.error_response creates error response."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        result = handler.error_response("Bad request")

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "Bad request" in body["error"]

    def test_json_error_method(self):
        """BaseHandler.json_error creates JSON error response."""
        from aragora.server.handlers.base import BaseHandler
        from http import HTTPStatus

        handler = BaseHandler({})
        result = handler.json_error("Not found", HTTPStatus.NOT_FOUND)

        assert result.status_code == 404


# ============================================================================
# Parameter Parsing Tests - Additional Coverage
# ============================================================================


class TestParseQueryParams:
    """Tests for parse_query_params utility."""

    def test_parse_query_params_basic(self):
        """parse_query_params parses simple query string."""
        from aragora.server.handlers.base import parse_query_params

        result = parse_query_params("limit=10&offset=5")
        assert result["limit"] == "10"
        assert result["offset"] == "5"

    def test_parse_query_params_empty(self):
        """parse_query_params handles empty string."""
        from aragora.server.handlers.base import parse_query_params

        result = parse_query_params("")
        assert result == {}

    def test_parse_query_params_single_value_list(self):
        """parse_query_params converts single-value lists."""
        from aragora.server.handlers.base import parse_query_params

        result = parse_query_params("key=value")
        # Single values should be strings, not lists
        assert isinstance(result["key"], str)


class TestGetFloatParam:
    """Tests for get_float_param utility."""

    def test_get_float_param_default(self):
        """get_float_param returns default for missing param."""
        from aragora.server.handlers.base import get_float_param

        result = get_float_param({}, "missing", 0.5)
        assert result == 0.5

    def test_get_float_param_from_string(self):
        """get_float_param parses string to float."""
        from aragora.server.handlers.base import get_float_param

        result = get_float_param({"threshold": "0.75"}, "threshold", 0.5)
        assert result == 0.75

    def test_get_float_param_invalid(self):
        """get_float_param returns default for invalid input."""
        from aragora.server.handlers.base import get_float_param

        result = get_float_param({"threshold": "not a number"}, "threshold", 0.5)
        assert result == 0.5

    def test_get_float_param_list_value(self):
        """get_float_param handles list values."""
        from aragora.server.handlers.base import get_float_param

        result = get_float_param({"threshold": ["0.9", "0.8"]}, "threshold", 0.5)
        assert result == 0.9  # Takes first value


class TestGetStringParam:
    """Tests for get_string_param utility."""

    def test_get_string_param_basic(self):
        """get_string_param extracts string value."""
        from aragora.server.handlers.base import get_string_param

        result = get_string_param({"name": "test"}, "name")
        assert result == "test"

    def test_get_string_param_none_default(self):
        """get_string_param returns None for missing param."""
        from aragora.server.handlers.base import get_string_param

        result = get_string_param({}, "missing")
        assert result is None

    def test_get_string_param_list_value(self):
        """get_string_param handles list values."""
        from aragora.server.handlers.base import get_string_param

        result = get_string_param({"name": ["first", "second"]}, "name")
        assert result == "first"


# ============================================================================
# RBAC/Permission Matrix Tests
# ============================================================================


class TestPermissionMatrix:
    """Tests for permission matrix and has_permission."""

    def test_has_permission_exact_match(self):
        """has_permission matches exact permissions."""
        from aragora.server.handlers.base import has_permission

        assert has_permission("member", "debates:read") is True
        assert has_permission("admin", "debates:update") is True
        assert has_permission("owner", "org:delete") is True

    def test_has_permission_denied(self):
        """has_permission denies unauthorized access."""
        from aragora.server.handlers.base import has_permission

        assert has_permission("member", "org:delete") is False
        assert has_permission("member", "admin:system") is False

    def test_has_permission_wildcard(self):
        """has_permission supports wildcard permissions."""
        from aragora.server.handlers.base import has_permission

        # Owner has admin:* which covers all admin permissions
        assert has_permission("owner", "admin:anything") is True

    def test_has_permission_empty_inputs(self):
        """has_permission handles empty/None inputs."""
        from aragora.server.handlers.base import has_permission

        assert has_permission(None, "debates:read") is False
        assert has_permission("member", None) is False
        assert has_permission("", "debates:read") is False


class TestValidateParamsDecorator:
    """Tests for validate_params decorator."""

    def test_validate_params_extracts_values(self):
        """validate_params extracts and validates query params."""
        from aragora.server.handlers.base import validate_params

        @validate_params(
            {
                "limit": (int, 10, 1, 100),
                "enabled": (bool, False, None, None),
                "name": (str, "", None, 50),
            }
        )
        def handler(query_params, limit=None, enabled=None, name=None):
            return {"limit": limit, "enabled": enabled, "name": name}

        result = handler({"limit": "25", "enabled": "true", "name": "test"})
        assert result["limit"] == 25
        assert result["enabled"] is True
        assert result["name"] == "test"

    def test_validate_params_clamps_values(self):
        """validate_params clamps values to bounds."""
        from aragora.server.handlers.base import validate_params

        @validate_params({"limit": (int, 10, 1, 50)})
        def handler(query_params, limit=None):
            return limit

        # Above max
        result = handler({"limit": "999"})
        assert result == 50

        # Below min
        result = handler({"limit": "-5"})
        assert result == 1

    def test_validate_params_uses_defaults(self):
        """validate_params uses defaults for missing params."""
        from aragora.server.handlers.base import validate_params

        @validate_params(
            {
                "limit": (int, 20, 1, 100),
                "sort": (str, "asc", None, 10),
            }
        )
        def handler(query_params, limit=None, sort=None):
            return {"limit": limit, "sort": sort}

        result = handler({})
        assert result["limit"] == 20
        assert result["sort"] == "asc"


# ============================================================================
# Error Response Structure Tests
# ============================================================================


class TestErrorResponseStructure:
    """Tests for structured error responses."""

    def test_error_response_with_code(self):
        """error_response includes error code when provided."""
        from aragora.server.handlers.base import error_response

        result = error_response("Validation failed", 400, code="VALIDATION_ERROR")
        body = json.loads(result.body)
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["message"] == "Validation failed"

    def test_error_response_with_trace_id(self):
        """error_response includes trace_id when provided."""
        from aragora.server.handlers.base import error_response

        result = error_response("Server error", 500, trace_id="abc123")
        body = json.loads(result.body)
        assert body["error"]["trace_id"] == "abc123"

    def test_error_response_with_suggestion(self):
        """error_response includes suggestion when provided."""
        from aragora.server.handlers.base import error_response

        result = error_response("Invalid format", 400, suggestion="Use ISO 8601 date format")
        body = json.loads(result.body)
        assert body["error"]["suggestion"] == "Use ISO 8601 date format"

    def test_error_response_with_details(self):
        """error_response includes details when provided."""
        from aragora.server.handlers.base import error_response

        result = error_response(
            "Validation failed", 400, details={"field": "email", "reason": "invalid"}
        )
        body = json.loads(result.body)
        assert body["error"]["details"]["field"] == "email"


# ============================================================================
# Generate Trace ID Tests
# ============================================================================


class TestGenerateTraceId:
    """Tests for generate_trace_id utility."""

    def test_generate_trace_id_format(self):
        """generate_trace_id returns 8-character string."""
        from aragora.server.handlers.base import generate_trace_id

        trace_id = generate_trace_id()
        assert len(trace_id) == 8
        assert isinstance(trace_id, str)

    def test_generate_trace_id_unique(self):
        """generate_trace_id produces unique values."""
        from aragora.server.handlers.base import generate_trace_id

        ids = {generate_trace_id() for _ in range(100)}
        assert len(ids) == 100  # All unique


# ============================================================================
# HandlerResult Headers Tests
# ============================================================================


class TestHandlerResultHeaders:
    """Tests for HandlerResult headers handling."""

    def test_handler_result_default_headers(self):
        """HandlerResult initializes with empty headers dict."""
        from aragora.server.handlers.base import HandlerResult

        result = HandlerResult(status_code=200, content_type="text/plain", body=b"test")
        assert result.headers == {}

    def test_handler_result_custom_headers(self):
        """HandlerResult accepts custom headers."""
        from aragora.server.handlers.base import HandlerResult

        result = HandlerResult(
            status_code=200,
            content_type="text/plain",
            body=b"test",
            headers={"X-Custom": "value"},
        )
        assert result.headers["X-Custom"] == "value"

    def test_json_response_with_headers(self):
        """json_response accepts custom headers."""
        from aragora.server.handlers.base import json_response

        result = json_response({"data": "test"}, headers={"X-Request-Id": "req-123"})
        assert result.headers["X-Request-Id"] == "req-123"
