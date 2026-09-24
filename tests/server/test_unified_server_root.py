"""
Tests for unified_server.py - the main HTTP/WebSocket server.

Tests cover:
- Input validation (safe_int, safe_float, safe_string)
- Path segment extraction
- Content length validation
- Client IP extraction
- Rate limiting
- CORS headers
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from io import BytesIO


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_handler():
    """Create a mock UnifiedHandler with necessary attributes."""
    handler = Mock()
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.path = "/api/test"
    handler.wfile = BytesIO()
    handler.requestline = "GET /api/test HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.command = "GET"

    # Mock _send_json to track calls
    handler._send_json = Mock()

    return handler


@pytest.fixture
def handler_class():
    """Import and return the UnifiedHandler class."""
    from aragora.server.unified_server import UnifiedHandler

    return UnifiedHandler


# =============================================================================
# _safe_int Tests
# =============================================================================


class TestSafeInt:
    """Tests for _safe_int method."""

    def test_valid_integer(self, handler_class, mock_handler):
        """Should parse valid integer from query."""
        # Bind method to mock
        method = handler_class._safe_int.__get__(mock_handler, type(mock_handler))

        result = method({"limit": ["10"]}, "limit", 20)
        assert result == 10

    def test_default_when_missing(self, handler_class, mock_handler):
        """Should return default when key is missing."""
        method = handler_class._safe_int.__get__(mock_handler, type(mock_handler))

        result = method({}, "limit", 20)
        assert result == 20

    def test_clamps_to_max(self, handler_class, mock_handler):
        """Should clamp value to max_val."""
        method = handler_class._safe_int.__get__(mock_handler, type(mock_handler))

        result = method({"limit": ["500"]}, "limit", 20, max_val=100)
        assert result == 100

    def test_clamps_to_min_one(self, handler_class, mock_handler):
        """Should clamp value to minimum of 1."""
        method = handler_class._safe_int.__get__(mock_handler, type(mock_handler))

        result = method({"limit": ["-5"]}, "limit", 20)
        assert result == 1

    def test_invalid_string_returns_default(self, handler_class, mock_handler):
        """Should return default for non-numeric string."""
        method = handler_class._safe_int.__get__(mock_handler, type(mock_handler))

        result = method({"limit": ["abc"]}, "limit", 20)
        assert result == 20

    def test_empty_list_returns_default(self, handler_class, mock_handler):
        """Should return default for empty list."""
        method = handler_class._safe_int.__get__(mock_handler, type(mock_handler))

        result = method({"limit": []}, "limit", 20)
        assert result == 20


# =============================================================================
# _safe_float Tests
# =============================================================================


class TestSafeFloat:
    """Tests for _safe_float method."""

    def test_valid_float(self, handler_class, mock_handler):
        """Should parse valid float from query."""
        method = handler_class._safe_float.__get__(mock_handler, type(mock_handler))

        result = method({"threshold": ["0.75"]}, "threshold", 0.5)
        assert result == 0.75

    def test_default_when_missing(self, handler_class, mock_handler):
        """Should return default when key is missing."""
        method = handler_class._safe_float.__get__(mock_handler, type(mock_handler))

        result = method({}, "threshold", 0.5)
        assert result == 0.5

    def test_clamps_to_max(self, handler_class, mock_handler):
        """Should clamp value to max_val."""
        method = handler_class._safe_float.__get__(mock_handler, type(mock_handler))

        result = method({"threshold": ["1.5"]}, "threshold", 0.5, max_val=1.0)
        assert result == 1.0

    def test_clamps_to_min(self, handler_class, mock_handler):
        """Should clamp value to min_val."""
        method = handler_class._safe_float.__get__(mock_handler, type(mock_handler))

        result = method({"threshold": ["-0.5"]}, "threshold", 0.5, min_val=0.0)
        assert result == 0.0

    def test_invalid_string_returns_default(self, handler_class, mock_handler):
        """Should return default for non-numeric string."""
        method = handler_class._safe_float.__get__(mock_handler, type(mock_handler))

        result = method({"threshold": ["abc"]}, "threshold", 0.5)
        assert result == 0.5


# =============================================================================
# _safe_string Tests
# =============================================================================


class TestSafeString:
    """Tests for _safe_string method."""

    def test_valid_string(self, handler_class, mock_handler):
        """Should return valid string unchanged."""
        method = handler_class._safe_string.__get__(mock_handler, type(mock_handler))

        result = method("hello")
        assert result == "hello"

    def test_truncates_long_string(self, handler_class, mock_handler):
        """Should truncate string to max_len."""
        method = handler_class._safe_string.__get__(mock_handler, type(mock_handler))

        result = method("a" * 1000, max_len=100)
        assert len(result) == 100

    def test_empty_string_returns_none(self, handler_class, mock_handler):
        """Should return None for empty string."""
        method = handler_class._safe_string.__get__(mock_handler, type(mock_handler))

        result = method("")
        assert result is None

    def test_none_returns_none(self, handler_class, mock_handler):
        """Should return None for None input."""
        method = handler_class._safe_string.__get__(mock_handler, type(mock_handler))

        result = method(None)
        assert result is None

    def test_pattern_match_valid(self, handler_class, mock_handler):
        """Should return string if pattern matches."""
        method = handler_class._safe_string.__get__(mock_handler, type(mock_handler))

        result = method("abc123", pattern=r"^[a-z0-9]+$")
        assert result == "abc123"

    def test_pattern_match_invalid(self, handler_class, mock_handler):
        """Should return None if pattern doesn't match."""
        method = handler_class._safe_string.__get__(mock_handler, type(mock_handler))

        result = method("abc-123", pattern=r"^[a-z0-9]+$")
        assert result is None

    def test_non_string_returns_none(self, handler_class, mock_handler):
        """Should return None for non-string input."""
        method = handler_class._safe_string.__get__(mock_handler, type(mock_handler))

        result = method(123)
        assert result is None


# =============================================================================
# _extract_path_segment Tests
# =============================================================================


class TestExtractPathSegment:
    """Tests for _extract_path_segment method."""

    def test_extract_valid_segment(self, handler_class, mock_handler):
        """Should extract segment at given index."""
        method = handler_class._extract_path_segment.__get__(mock_handler, type(mock_handler))

        result = method("/api/debates/abc123/messages", 3)
        assert result == "abc123"

    def test_missing_segment_returns_none(self, handler_class, mock_handler):
        """Should return None and send error for missing segment."""
        method = handler_class._extract_path_segment.__get__(mock_handler, type(mock_handler))

        result = method("/api/debates", 3)
        assert result is None
        mock_handler._send_json.assert_called_once()
        call_args = mock_handler._send_json.call_args
        assert call_args[0][0]["error"] == "Missing id in path"
        assert call_args[1]["status"] == 400

    def test_empty_segment_returns_none(self, handler_class, mock_handler):
        """Should return None for empty segment."""
        method = handler_class._extract_path_segment.__get__(mock_handler, type(mock_handler))

        result = method("/api/debates//messages", 3)
        assert result is None

    def test_custom_segment_name(self, handler_class, mock_handler):
        """Should use custom segment name in error."""
        method = handler_class._extract_path_segment.__get__(mock_handler, type(mock_handler))

        result = method("/api/agent", 3, segment_name="agent_name")
        assert result is None
        call_args = mock_handler._send_json.call_args
        assert "agent_name" in call_args[0][0]["error"]


# =============================================================================
# _validate_content_length Tests
# =============================================================================


class TestValidateContentLength:
    """Tests for _validate_content_length method."""

    def test_valid_content_length(self, handler_class, mock_handler):
        """Should return content length for valid header."""
        mock_handler.headers = {"Content-Length": "1000"}
        method = handler_class._validate_content_length.__get__(mock_handler, type(mock_handler))

        result = method()
        assert result == 1000

    def test_missing_content_length_returns_zero(self, handler_class, mock_handler):
        """Should return 0 for missing Content-Length."""
        mock_handler.headers = {}
        method = handler_class._validate_content_length.__get__(mock_handler, type(mock_handler))

        result = method()
        assert result == 0

    def test_invalid_content_length_returns_none(self, handler_class, mock_handler):
        """Should return None and send error for invalid Content-Length."""
        mock_handler.headers = {"Content-Length": "abc"}
        method = handler_class._validate_content_length.__get__(mock_handler, type(mock_handler))

        result = method()
        assert result is None
        mock_handler._send_json.assert_called_once()

    def test_negative_content_length_returns_none(self, handler_class, mock_handler):
        """Should return None and send error for negative Content-Length."""
        mock_handler.headers = {"Content-Length": "-100"}
        method = handler_class._validate_content_length.__get__(mock_handler, type(mock_handler))

        result = method()
        assert result is None
        call_args = mock_handler._send_json.call_args
        assert "negative" in call_args[0][0]["error"]

    def test_exceeds_max_size_returns_none(self, handler_class, mock_handler):
        """Should return None and send 413 for content exceeding max."""
        mock_handler.headers = {"Content-Length": "20000000"}  # 20MB
        method = handler_class._validate_content_length.__get__(mock_handler, type(mock_handler))

        result = method(max_size=10 * 1024 * 1024)  # 10MB max
        assert result is None
        call_args = mock_handler._send_json.call_args
        assert call_args[1]["status"] == 413

    def test_custom_max_size(self, handler_class, mock_handler):
        """Should respect custom max_size."""
        mock_handler.headers = {"Content-Length": "500"}
        method = handler_class._validate_content_length.__get__(mock_handler, type(mock_handler))

        result = method(max_size=1000)
        assert result == 500


# =============================================================================
# _get_client_ip Tests
# =============================================================================


class TestGetClientIp:
    """Tests for _get_client_ip method."""

    def test_returns_remote_ip(self, handler_class, mock_handler):
        """Should return remote IP when not from trusted proxy."""
        mock_handler.client_address = ("192.168.1.100", 12345)
        mock_handler.headers = {}
        method = handler_class._get_client_ip.__get__(mock_handler, type(mock_handler))

        result = method()
        assert result == "192.168.1.100"

    def test_uses_forwarded_for_from_trusted_proxy(self, handler_class, mock_handler):
        """Should use X-Forwarded-For when request from trusted proxy."""
        mock_handler.client_address = ("127.0.0.1", 12345)
        mock_handler.headers = {"X-Forwarded-For": "203.0.113.50, 70.41.3.18"}
        method = handler_class._get_client_ip.__get__(mock_handler, type(mock_handler))

        result = method()
        assert result == "203.0.113.50"

    def test_ignores_forwarded_for_from_untrusted(self, handler_class, mock_handler):
        """Should ignore X-Forwarded-For from untrusted source."""
        mock_handler.client_address = ("192.168.1.100", 12345)
        mock_handler.headers = {"X-Forwarded-For": "10.0.0.1"}
        method = handler_class._get_client_ip.__get__(mock_handler, type(mock_handler))

        result = method()
        assert result == "192.168.1.100"

    def test_handles_missing_client_address(self, handler_class, mock_handler):
        """Should return 'unknown' when client_address is missing."""
        del mock_handler.client_address
        mock_handler.headers = {}
        method = handler_class._get_client_ip.__get__(mock_handler, type(mock_handler))

        result = method()
        assert result == "unknown"


# =============================================================================
# UnifiedServer Tests
# =============================================================================


class TestUnifiedServerInit:
    """Tests for UnifiedServer initialization."""

    def test_default_initialization(self):
        """Should initialize with default values."""
        from aragora.server.unified_server import UnifiedServer

        with patch("aragora.server.unified_server.DebateStreamServer"):
            server = UnifiedServer(http_host="localhost", http_port=8080, ws_port=8081)

            assert server.http_host == "localhost"
            assert server.http_port == 8080
            assert server.ws_port == 8081

    def test_with_storage(self, tmp_path):
        """Should initialize with storage."""
        from aragora.server.unified_server import UnifiedServer
        from aragora.storage.debate_storage import DebateStorage

        db_path = tmp_path / "test.db"
        storage = DebateStorage(str(db_path))

        with patch("aragora.server.unified_server.DebateStreamServer"):
            server = UnifiedServer(
                http_host="localhost",
                http_port=8080,
                ws_port=8081,
                storage=storage,
            )

            assert server.storage is not None


# =============================================================================
# Security Tests
# =============================================================================


class TestSecurityHeaders:
    """Tests for security header handling."""

    def test_cors_headers_added(self, handler_class, mock_handler):
        """Should add CORS headers to response."""
        # Setup mock for send_header
        mock_handler.send_header = Mock()
        method = handler_class._add_cors_headers.__get__(mock_handler, type(mock_handler))

        # cors_config is imported inside the method from aragora.server.cors_config
        with patch("aragora.server.cors_config.cors_config") as mock_cors:
            mock_cors.is_origin_allowed.return_value = True
            mock_handler.headers = {"Origin": "https://example.com"}

            method()

            # Verify headers were added
            assert mock_handler.send_header.called


# =============================================================================
# Integration Tests
# =============================================================================


class TestHandlerIntegration:
    """Integration tests for handler routing."""

    def test_handler_routes_to_modular_handlers(self):
        """Verify handler delegates to modular handlers."""
        # This tests the handler registry integration
        from aragora.server.unified_server import UnifiedHandler

        # UnifiedHandler should have _init_handlers from mixin
        assert hasattr(UnifiedHandler, "_init_handlers")
        assert hasattr(UnifiedHandler, "_try_modular_handler")
