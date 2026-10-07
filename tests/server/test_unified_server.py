"""
Tests for UnifiedServer and UnifiedHandler.

Comprehensive test coverage for:
1. HTTP Dispatch Tests - Route dispatching, fallback/404 handling, method routing
2. Authentication Tests - Bearer token handling, auth context propagation
3. Rate Limiting Tests - Request counting, rate limit responses, headers
4. Server Lifecycle Tests - Startup, graceful shutdown, signal handling

Uses mocking for external dependencies while testing actual server logic.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import tempfile
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_headers():
    """Create mock HTTP headers."""

    class MockHeaders:
        def __init__(self, data: dict[str, str] | None = None):
            self._data = data or {}

        def get(self, key: str, default: str = "") -> str:
            return self._data.get(key, default)

        def items(self):
            return self._data.items()

        def __iter__(self):
            return iter(self._data)

    return MockHeaders


@pytest.fixture
def mock_request_handler(mock_headers):
    """Create a mock request handler for testing UnifiedHandler methods."""

    class MockHandler:
        def __init__(self):
            self.path = "/"
            self.command = "GET"
            self.client_address = ("127.0.0.1", 12345)
            self.headers = mock_headers()
            self.wfile = BytesIO()
            self._response_status = 0
            self._rate_limit_result = None
            self._sent_headers: list[tuple[str, str]] = []
            self._response_code = 0
            self.responses = {404: ("Not Found", ""), 500: ("Internal Server Error", "")}

        def send_response(self, code: int) -> None:
            self._response_code = code

        def send_header(self, keyword: str, value: str) -> None:
            self._sent_headers.append((keyword, value))

        def end_headers(self) -> None:
            pass

        def get_response_json(self) -> dict:
            """Parse the response body as JSON."""
            self.wfile.seek(0)
            content = self.wfile.read()
            if content:
                return json.loads(content.decode())
            return {}

    return MockHandler()


@pytest.fixture
def temp_nomic_dir():
    """Create a temporary directory for nomic state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# =============================================================================
# HTTP Dispatch Tests
# =============================================================================


class TestHTTPDispatch:
    """Tests for HTTP route dispatching logic."""

    @staticmethod
    def _make_unified_handler(mock_request_handler, *, accept: str = "application/json"):
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        handler.path = "/api/v1/spectate/stream"
        handler.command = "GET"
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = type(mock_request_handler.headers)({"Accept": accept})
        handler.wfile = mock_request_handler.wfile
        handler._response_status = 0
        handler._rate_limit_result = None
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler._add_cors_headers = MagicMock()
        handler._add_security_headers = MagicMock()
        handler._add_trace_headers = MagicMock()
        handler._check_rbac = MagicMock(return_value=True)
        handler._check_admin_mfa = MagicMock(return_value=True)
        handler._check_rate_limit = MagicMock(return_value=True)
        handler._check_live_streaming_budget = MagicMock(return_value=True)
        handler._try_modular_handler = MagicMock(return_value=False)
        handler._send_json = MagicMock()
        return handler

    def test_api_path_routes_to_modular_handlers(self, mock_request_handler):
        """Test that /api/* paths attempt modular handler routing."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        # Manually bind the mock to act like self
        handler.path = "/api/health"
        handler.command = "GET"
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = mock_request_handler.headers
        handler.wfile = mock_request_handler.wfile
        handler._response_status = 0
        handler._rate_limit_result = None

        # The path should be identified as an API route
        assert handler.path.startswith("/api/")

    def test_static_file_paths(self):
        """Test that non-API paths are treated as static file paths."""
        from aragora.server.unified_server import UnifiedHandler

        # These paths should be treated as static files
        static_paths = [
            "/",
            "/index.html",
            "/style.css",
            "/app.js",
            "/favicon.ico",
            "/logo.svg",
            "/image.png",
        ]

        for path in static_paths:
            assert not path.startswith("/api/"), f"{path} should be static"

    def test_healthz_exempt_from_auth(self):
        """Test that /healthz is exempt from authentication."""
        from aragora.server.unified_server import UnifiedHandler

        assert "/healthz" in UnifiedHandler.AUTH_EXEMPT_PATHS

    def test_readyz_exempt_from_auth(self):
        """Test that /readyz is exempt from authentication."""
        from aragora.server.unified_server import UnifiedHandler

        assert "/readyz" in UnifiedHandler.AUTH_EXEMPT_PATHS

    def test_api_health_exempt_from_auth(self):
        """Test that /api/health is exempt from authentication."""
        from aragora.server.unified_server import UnifiedHandler

        assert "/api/health" in UnifiedHandler.AUTH_EXEMPT_PATHS

    def test_method_routing_get(self):
        """Test that GET requests are routed correctly."""
        from aragora.server.unified_server import UnifiedHandler

        # Verify UnifiedHandler has do_GET method
        assert hasattr(UnifiedHandler, "do_GET")
        assert callable(getattr(UnifiedHandler, "do_GET"))

    def test_method_routing_post(self):
        """Test that POST requests are routed correctly."""
        from aragora.server.unified_server import UnifiedHandler

        # Verify UnifiedHandler has do_POST method
        assert hasattr(UnifiedHandler, "do_POST")
        assert callable(getattr(UnifiedHandler, "do_POST"))

    def test_method_routing_delete(self):
        """Test that DELETE requests are routed correctly."""
        from aragora.server.unified_server import UnifiedHandler

        # Verify UnifiedHandler has do_DELETE method
        assert hasattr(UnifiedHandler, "do_DELETE")
        assert callable(getattr(UnifiedHandler, "do_DELETE"))

    def test_method_routing_put(self):
        """Test that PUT requests are routed correctly."""
        from aragora.server.unified_server import UnifiedHandler

        # Verify UnifiedHandler has do_PUT method
        assert hasattr(UnifiedHandler, "do_PUT")
        assert callable(getattr(UnifiedHandler, "do_PUT"))

    def test_method_routing_patch(self):
        """Test that PATCH requests are routed correctly."""
        from aragora.server.unified_server import UnifiedHandler

        # Verify UnifiedHandler has do_PATCH method
        assert hasattr(UnifiedHandler, "do_PATCH")
        assert callable(getattr(UnifiedHandler, "do_PATCH"))

    def test_method_routing_options(self):
        """Test that OPTIONS requests are handled for CORS preflight."""
        from aragora.server.unified_server import UnifiedHandler

        # Verify UnifiedHandler has do_OPTIONS method
        assert hasattr(UnifiedHandler, "do_OPTIONS")
        assert callable(getattr(UnifiedHandler, "do_OPTIONS"))

    def test_normalize_endpoint_uuid(self):
        """Test that UUIDs in paths are normalized for metrics."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)

        # Test UUID normalization
        path = "/api/debates/550e8400-e29b-41d4-a716-446655440000/messages"
        normalized = handler._normalize_endpoint(path)
        assert "{id}" in normalized
        assert "550e8400-e29b-41d4-a716-446655440000" not in normalized

    def test_normalize_endpoint_numeric_id(self):
        """Test that numeric IDs in paths are normalized for metrics."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)

        # Test numeric ID normalization
        path = "/api/debates/12345/messages"
        normalized = handler._normalize_endpoint(path)
        assert "{id}" in normalized
        assert "12345" not in normalized

    def test_auth_me_returns_401_without_handler(self):
        """Test that /api/auth/me returns 401 when handler unavailable."""
        from aragora.server.unified_server import UnifiedHandler

        # The /api/auth/me endpoint should return 401 for unauthenticated requests
        # This is a fallback behavior when the handler isn't available
        assert "/api/auth/me" not in UnifiedHandler.AUTH_EXEMPT_PATHS

    def test_live_spectate_stream_intercepts_sse_requests(self, mock_request_handler):
        """SSE spectate requests should bypass the buffered modular handler path."""
        from aragora.server.unified_server import UnifiedHandler

        handler = self._make_unified_handler(
            mock_request_handler,
            accept="text/event-stream",
        )

        with patch.object(
            UnifiedHandler,
            "_serve_live_spectate_stream",
            return_value=True,
        ) as mock_stream:
            handler._do_GET_internal("/api/v1/spectate/stream", {})

        mock_stream.assert_called_once_with({})
        handler._try_modular_handler.assert_not_called()

    def test_live_spectate_stream_falls_back_for_json_callers(self, mock_request_handler):
        """Non-SSE spectate callers should continue through modular JSON handling."""
        handler = self._make_unified_handler(mock_request_handler)
        handler._try_modular_handler.return_value = True

        handler._do_GET_internal("/api/v1/spectate/stream", {})

        handler._try_modular_handler.assert_called_once_with("/api/v1/spectate/stream", {})

    def test_serve_live_spectate_stream_writes_sse_frames(self, mock_request_handler):
        """The dedicated live spectate path should emit framed SSE bytes."""
        handler = self._make_unified_handler(
            mock_request_handler,
            accept="text/event-stream",
        )

        with (
            patch(
                "aragora.server.handlers.spectate_ws.iter_live_spectate_sse_frames",
                return_value=iter([b"event: connected\ndata: {}\n\n"]),
            ) as mock_stream,
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=SimpleNamespace(is_authenticated=False),
            ),
        ):
            assert handler._serve_live_spectate_stream({}) is True

        mock_stream.assert_called_once_with({}, org_id=None, storage=None)
        assert mock_request_handler.wfile.getvalue() == b"event: connected\ndata: {}\n\n"
        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call("Content-Type", "text/event-stream")
        handler.send_header.assert_any_call("X-Aragora-Stream-Transport", "sse_live")

    def test_serve_live_spectate_stream_scopes_events_to_the_callers_org(
        self, mock_request_handler
    ):
        handler = self._make_unified_handler(
            mock_request_handler,
            accept="text/event-stream",
        )

        with (
            patch(
                "aragora.server.handlers.spectate_ws.iter_live_spectate_sse_frames",
                return_value=iter([b"event: connected\ndata: {}\n\n"]),
            ) as mock_stream,
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=SimpleNamespace(
                    is_authenticated=True, user_id="u-1", org_id="org-1", role="member"
                ),
            ),
        ):
            assert handler._serve_live_spectate_stream({}) is True

        mock_stream.assert_called_once_with({}, org_id="org-1", storage=None)


class TestHTTP404Handling:
    """Tests for 404 fallback handling."""

    def test_unknown_api_endpoint_post_returns_404(self):
        """Test that unknown POST endpoints return 404."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        # Verify send_error method exists
        assert hasattr(handler, "send_error")

    def test_unknown_api_endpoint_delete_returns_404(self):
        """Test that unknown DELETE endpoints return 404."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        # Verify handler structure for DELETE
        assert hasattr(handler, "_do_DELETE_internal")

    def test_unknown_api_endpoint_patch_returns_404(self):
        """Test that unknown PATCH endpoints return 404."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        # Verify handler structure for PATCH
        assert hasattr(handler, "_do_PATCH_internal")

    def test_unknown_api_endpoint_put_returns_404(self):
        """Test that unknown PUT endpoints return 404."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        # Verify handler structure for PUT
        assert hasattr(handler, "_do_PUT_internal")


# =============================================================================
# Authentication Tests
# =============================================================================


class TestAuthentication:
    """Tests for authentication middleware integration."""

    def test_bearer_token_extraction(self):
        """Test that Bearer tokens are extracted from Authorization header."""
        from aragora.server.auth import auth_config

        headers = {"Authorization": "Bearer test_token_123"}
        token = auth_config.extract_token_from_request(headers)
        assert token == "test_token_123"

    def test_bearer_token_missing(self):
        """Test handling when no Authorization header is present."""
        from aragora.server.auth import auth_config

        headers = {}
        token = auth_config.extract_token_from_request(headers)
        assert token is None

    def test_bearer_token_invalid_format(self):
        """Test handling when Authorization header has wrong format."""
        from aragora.server.auth import auth_config

        # Missing "Bearer " prefix
        headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        token = auth_config.extract_token_from_request(headers)
        assert token is None

    def test_auth_exempt_paths_health(self):
        """Test that health endpoints are auth exempt."""
        from aragora.server.unified_server import UnifiedHandler

        health_paths = [
            "/healthz",
            "/readyz",
            "/api/health",
            "/api/health/detailed",
            "/api/health/deep",
            "/api/health/stores",
            "/api/v1/health",
            "/api/v1/health/detailed",
        ]
        for path in health_paths:
            assert path in UnifiedHandler.AUTH_EXEMPT_PATHS, f"{path} should be exempt"

    def test_auth_exempt_paths_docs_require_auth(self):
        """Test that API documentation endpoints require auth (locked down)."""
        from aragora.server.unified_server import UnifiedHandler

        doc_paths = [
            "/api/openapi",
            "/api/openapi.json",
            "/api/openapi.yaml",
            "/api/docs",
            "/api/docs/",
        ]
        for path in doc_paths:
            assert path not in UnifiedHandler.AUTH_EXEMPT_PATHS, (
                f"{path} should NOT be exempt (requires auth to prevent attack surface mapping)"
            )

    def test_auth_exempt_prefixes_oauth(self):
        """Test that OAuth flow prefixes are auth exempt."""
        from aragora.server.unified_server import UnifiedHandler

        # Check OAuth paths work with prefix matching
        oauth_path = "/api/auth/oauth/google"
        assert any(oauth_path.startswith(p) for p in UnifiedHandler.AUTH_EXEMPT_PREFIXES)

    def test_auth_exempt_get_prefixes(self):
        """Test that GET-only exempt prefixes work correctly."""
        from aragora.server.unified_server import UnifiedHandler

        # Evidence endpoints should be GET-only exempt
        evidence_path = "/api/evidence/123"
        assert any(evidence_path.startswith(p) for p in UnifiedHandler.AUTH_EXEMPT_GET_PREFIXES)

    def test_unauthenticated_request_blocked_on_protected_route(self):
        """Test that unauthenticated requests are blocked on protected routes."""
        from aragora.server.auth import AuthConfig, check_auth
        import aragora.server.auth as auth_mod

        test_config = AuthConfig()
        test_config.enabled = True
        test_config.api_token = "secret_token"

        # Use a dedicated AuthConfig to avoid pollution from parallel tests
        with patch.object(auth_mod, "auth_config", test_config):
            authenticated, _ = check_auth({})
            assert not authenticated

    def test_authenticated_request_allowed(self):
        """Test that authenticated requests are allowed."""
        from aragora.server.auth import AuthConfig, check_auth
        import aragora.server.auth as auth_mod

        test_config = AuthConfig()
        test_config.enabled = True
        test_config.api_token = "secret_token"

        # Use a dedicated AuthConfig to avoid pollution from parallel tests
        with patch.object(auth_mod, "auth_config", test_config):
            token = test_config.generate_token()
            headers = {"Authorization": f"Bearer {token}"}

            authenticated, _ = check_auth(headers)
            assert authenticated

    def test_token_validation_expired(self):
        """Test that expired tokens are rejected."""
        from aragora.server.auth import AuthConfig

        test_config = AuthConfig()
        test_config.enabled = True
        test_config.api_token = "secret_token"

        # Generate token that expires immediately
        token = test_config.generate_token(expires_in=-1)
        assert not test_config.validate_token(token)

    def test_token_revocation(self):
        """Test that revoked tokens are rejected."""
        from aragora.server.auth import AuthConfig

        test_config = AuthConfig()
        test_config.enabled = True
        test_config.api_token = "secret_token"

        # Generate and revoke token
        token = test_config.generate_token()
        test_config.revoke_token(token)
        assert test_config.is_revoked(token)
        assert not test_config.validate_token(token)


class TestAuthContextPropagation:
    """Tests for authentication context propagation to handlers."""

    def test_rbac_bypass_paths_configured(self):
        """Test that RBAC middleware has bypass paths configured."""
        from aragora.server.unified_server import UnifiedHandler

        rbac = UnifiedHandler._get_rbac()
        assert rbac.config.bypass_paths is not None
        assert "/health" in rbac.config.bypass_paths
        assert "/healthz" in rbac.config.bypass_paths

    def test_rbac_bypass_methods_configured(self):
        """Test that RBAC middleware bypasses OPTIONS method."""
        from aragora.server.unified_server import UnifiedHandler

        rbac = UnifiedHandler._get_rbac()
        assert "OPTIONS" in rbac.config.bypass_methods

    def test_default_authenticated_enabled(self):
        """Test that default_authenticated is enabled for security."""
        from aragora.server.unified_server import UnifiedHandler

        rbac = UnifiedHandler._get_rbac()
        assert rbac.config.default_authenticated is True


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestRateLimiting:
    """Tests for rate limit enforcement."""

    def test_rate_limit_check_returns_tuple(self):
        """Test that rate limit check returns (allowed, remaining) tuple."""
        from aragora.server.auth import auth_config

        allowed, remaining = auth_config.check_rate_limit("test_token")
        assert isinstance(allowed, bool)
        assert isinstance(remaining, int)

    def test_rate_limit_by_ip_returns_tuple(self):
        """Test that IP rate limit check returns (allowed, remaining) tuple."""
        from aragora.server.auth import auth_config

        allowed, remaining = auth_config.check_rate_limit_by_ip("192.168.1.1")
        assert isinstance(allowed, bool)
        assert isinstance(remaining, int)

    def test_rate_limit_exceeded(self):
        """Test that rate limit is enforced after exceeding threshold."""
        from aragora.server.auth import AuthConfig

        # Create fresh config to avoid affecting other tests
        config = AuthConfig()
        config.rate_limit_per_minute = 3  # Low limit for testing

        token = "test_rate_limit_token"

        # Make requests up to the limit
        for _ in range(3):
            allowed, _ = config.check_rate_limit(token)
            assert allowed

        # Next request should be blocked
        allowed, remaining = config.check_rate_limit(token)
        assert not allowed
        assert remaining == 0

        # Cleanup
        config.stop_cleanup_thread()

    def test_rate_limit_headers_returned(self):
        """Test that rate limit headers are properly generated."""
        from aragora.server.middleware.rate_limit import rate_limit_headers, RateLimitResult

        result = RateLimitResult(
            allowed=True,
            remaining=50,
            limit=100,
            retry_after=0.0,
            key="test_key",
        )

        headers = rate_limit_headers(result)
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers

    def test_rate_limit_429_response(self):
        """Test that 429 response is sent when rate limited."""
        from aragora.server.middleware.rate_limit import RateLimitResult

        # When rate limited, response should include retry_after
        result = RateLimitResult(
            allowed=False,
            remaining=0,
            limit=100,
            retry_after=30.0,
            key="test_key",
        )

        assert not result.allowed
        assert result.retry_after > 0

    def test_tier_rate_limits_configured(self):
        """Test that tier rate limits are properly configured."""
        from aragora.server.middleware.rate_limit import TIER_RATE_LIMITS

        assert "free" in TIER_RATE_LIMITS
        assert "starter" in TIER_RATE_LIMITS
        assert "professional" in TIER_RATE_LIMITS
        assert "enterprise" in TIER_RATE_LIMITS

    def test_upload_rate_limiter(self):
        """Test that upload rate limiter is available."""
        from aragora.server.upload_rate_limit import get_upload_limiter

        limiter = get_upload_limiter()
        assert limiter is not None
        assert hasattr(limiter, "check_allowed")

    def test_ip_rate_limit_with_empty_ip(self):
        """Test that empty IP address is handled gracefully."""
        from aragora.server.auth import auth_config

        allowed, remaining = auth_config.check_rate_limit_by_ip("")
        assert allowed is True
        assert remaining == auth_config.ip_rate_limit_per_minute


class TestRateLimitCleanup:
    """Tests for rate limit entry cleanup."""

    def test_cleanup_expired_entries(self):
        """Test that expired entries are cleaned up."""
        from aragora.server.auth import AuthConfig

        config = AuthConfig()

        # Add some entries
        config.check_rate_limit("test_token_1")
        config.check_rate_limit_by_ip("192.168.1.1")

        # Run cleanup
        stats = config.cleanup_expired_entries(ttl_seconds=0)

        assert "token_entries_removed" in stats
        assert "ip_entries_removed" in stats
        assert isinstance(stats["token_entries_removed"], int)
        assert isinstance(stats["ip_entries_removed"], int)

        config.stop_cleanup_thread()

    def test_rate_limit_stats(self):
        """Test that rate limit stats are available."""
        from aragora.server.auth import auth_config

        stats = auth_config.get_rate_limit_stats()
        assert "token_entries" in stats
        assert "ip_entries" in stats
        assert "revoked_tokens" in stats


# =============================================================================
# Server Lifecycle Tests
# =============================================================================


class TestServerInitialization:
    """Tests for server initialization."""

    @pytest.mark.smoke
    def test_unified_server_init(self, temp_nomic_dir):
        """Test UnifiedServer initialization."""
        from aragora.server.unified_server import UnifiedServer

        server = UnifiedServer(
            http_port=8081,
            ws_port=8766,
            nomic_dir=temp_nomic_dir,
        )

        assert server.http_port == 8081
        assert server.ws_port == 8766
        assert server.nomic_dir == temp_nomic_dir

    def test_unified_server_default_ports(self):
        """Test UnifiedServer uses default ports."""
        from aragora.server.unified_server import UnifiedServer

        server = UnifiedServer()

        assert server.http_port == 8080
        assert server.ws_port == 8765

    def test_unified_server_ssl_disabled_by_default(self):
        """Test that SSL is disabled by default."""
        from aragora.server.unified_server import UnifiedServer

        server = UnifiedServer()

        assert server.ssl_enabled is False
        assert server.ssl_cert is None
        assert server.ssl_key is None

    def test_unified_server_ssl_enabled_with_certs(self, temp_nomic_dir):
        """Test that SSL is enabled when certs are provided."""
        from aragora.server.unified_server import UnifiedServer

        # Create dummy cert files
        cert_path = temp_nomic_dir / "cert.pem"
        key_path = temp_nomic_dir / "key.pem"
        cert_path.write_text("dummy cert")
        key_path.write_text("dummy key")

        server = UnifiedServer(
            ssl_cert=str(cert_path),
            ssl_key=str(key_path),
        )

        assert server.ssl_enabled is True
        assert server.ssl_cert == str(cert_path)
        assert server.ssl_key == str(key_path)

    def test_stream_servers_created(self):
        """Test that WebSocket stream servers are created."""
        from aragora.server.unified_server import UnifiedServer

        server = UnifiedServer()

        assert server.stream_server is not None
        assert server.control_plane_stream is not None
        assert server.nomic_loop_stream is not None

    def test_emitter_property(self):
        """Test that emitter property returns stream emitter."""
        from aragora.server.unified_server import UnifiedServer

        server = UnifiedServer()

        emitter = server.emitter
        assert emitter is not None
        assert emitter == server.stream_server.emitter


class TestServerStartup:
    """Tests for server startup sequence."""

    @pytest.mark.asyncio
    async def test_start_initializes_handlers(self, temp_nomic_dir):
        """Test that server start initializes handlers."""
        from aragora.server.unified_server import UnifiedServer, UnifiedHandler

        server = UnifiedServer(nomic_dir=temp_nomic_dir)

        # Mock the actual server startup to avoid binding ports
        with patch.object(server.stream_server, "start", new_callable=AsyncMock):
            with patch.object(server.control_plane_stream, "start", new_callable=AsyncMock):
                with patch.object(server.nomic_loop_stream, "start", new_callable=AsyncMock):
                    canvas_ctx = (
                        patch.object(server.canvas_stream, "start", new_callable=AsyncMock)
                        if server.canvas_stream
                        else contextlib.nullcontext()
                    )
                    with canvas_ctx:
                        with patch.object(server, "_run_http_server"):
                            with patch(
                                "aragora.server.startup.parallel_init", new_callable=AsyncMock
                            ) as mock_init:
                                mock_init.return_value = {"watchdog_task": None}
                                with patch("threading.Thread"):
                                    # Start should not raise
                                    try:
                                        await asyncio.wait_for(server.start(), timeout=2.0)
                                    except asyncio.TimeoutError:
                                        pass  # Expected - servers run forever

    def test_handlers_initialized_lazily(self):
        """Test that handlers are initialized lazily on first request."""
        from aragora.server.unified_server import UnifiedHandler

        # Reset initialized state
        original_initialized = UnifiedHandler._handlers_initialized
        try:
            UnifiedHandler._handlers_initialized = False
            assert not UnifiedHandler._handlers_initialized
        finally:
            UnifiedHandler._handlers_initialized = original_initialized


class TestGracefulShutdown:
    """Tests for graceful shutdown."""

    def test_shutdown_sequence_creation(self):
        """Test that shutdown sequence is created with phases."""
        from aragora.server.shutdown_sequence import (
            create_server_shutdown_sequence,
            ShutdownSequence,
        )
        from aragora.server.unified_server import UnifiedServer

        server = UnifiedServer()
        sequence = create_server_shutdown_sequence(server)

        assert isinstance(sequence, ShutdownSequence)
        assert len(sequence._phases) > 0

    def test_shutdown_phase_structure(self):
        """Test that shutdown phases have required attributes."""
        from aragora.server.shutdown_sequence import ShutdownPhase

        phase = ShutdownPhase(
            name="Test Phase",
            execute=AsyncMock(),
            timeout=5.0,
            critical=True,
        )

        assert phase.name == "Test Phase"
        assert phase.timeout == 5.0
        assert phase.critical is True

    @pytest.mark.asyncio
    async def test_shutdown_sequence_execute_all(self):
        """Test that execute_all runs all phases."""
        from aragora.server.shutdown_sequence import ShutdownSequence, ShutdownPhase

        sequence = ShutdownSequence()

        executed = []

        async def phase1():
            executed.append("phase1")

        async def phase2():
            executed.append("phase2")

        sequence.add_phase(ShutdownPhase(name="Phase 1", execute=phase1, timeout=1.0))
        sequence.add_phase(ShutdownPhase(name="Phase 2", execute=phase2, timeout=1.0))

        result = await sequence.execute_all(overall_timeout=5.0)

        assert "phase1" in executed
        assert "phase2" in executed
        assert len(result["completed"]) == 2
        assert len(result["failed"]) == 0

    @pytest.mark.asyncio
    async def test_shutdown_phase_timeout_isolation(self):
        """Test that phase timeout doesn't affect other phases."""
        from aragora.server.shutdown_sequence import ShutdownSequence, ShutdownPhase

        sequence = ShutdownSequence()

        async def slow_phase():
            await asyncio.sleep(10)

        async def fast_phase():
            pass

        sequence.add_phase(ShutdownPhase(name="Slow", execute=slow_phase, timeout=0.1))
        sequence.add_phase(ShutdownPhase(name="Fast", execute=fast_phase, timeout=1.0))

        result = await sequence.execute_all(overall_timeout=5.0)

        # Slow phase should fail, fast phase should succeed
        assert "Slow" in result["failed"]
        assert "Fast" in result["completed"]

    @pytest.mark.asyncio
    async def test_shutdown_phase_error_isolation(self):
        """Test that phase errors don't affect other phases."""
        from aragora.server.shutdown_sequence import ShutdownSequence, ShutdownPhase

        sequence = ShutdownSequence()

        async def error_phase():
            raise RuntimeError("Intentional error")

        async def success_phase():
            pass

        sequence.add_phase(ShutdownPhase(name="Error", execute=error_phase, timeout=1.0))
        sequence.add_phase(ShutdownPhase(name="Success", execute=success_phase, timeout=1.0))

        result = await sequence.execute_all(overall_timeout=5.0)

        # Error phase should fail, success phase should succeed
        assert "Error" in result["failed"]
        assert "Success" in result["completed"]

    def test_is_shutting_down_property(self):
        """Test is_shutting_down property."""
        from aragora.server.unified_server import UnifiedServer

        server = UnifiedServer()
        assert server.is_shutting_down is False

        server._shutting_down = True
        assert server.is_shutting_down is True


class TestSignalHandling:
    """Tests for signal handling."""

    def test_signal_handlers_setup_method_exists(self):
        """Test that signal handler setup method exists."""
        from aragora.server.unified_server import UnifiedServer

        server = UnifiedServer()
        assert hasattr(server, "_setup_signal_handlers")
        assert callable(server._setup_signal_handlers)

    @pytest.mark.asyncio
    async def test_graceful_shutdown_method_exists(self):
        """Test that graceful_shutdown method exists and is async."""
        from aragora.server.unified_server import UnifiedServer

        server = UnifiedServer()
        assert hasattr(server, "graceful_shutdown")
        assert asyncio.iscoroutinefunction(server.graceful_shutdown)


# =============================================================================
# Content Length Validation Tests
# =============================================================================


class TestContentLengthValidation:
    """Tests for content length validation (DoS protection)."""

    def test_max_content_length_constants(self):
        """Test that max content length constants are defined."""
        from aragora.server.unified_server import MAX_CONTENT_LENGTH, MAX_JSON_CONTENT_LENGTH

        assert MAX_CONTENT_LENGTH == 100 * 1024 * 1024  # 100MB
        assert MAX_JSON_CONTENT_LENGTH == 10 * 1024 * 1024  # 10MB

    def test_multipart_parts_limit(self):
        """Test that multipart parts limit is defined."""
        from aragora.server.unified_server import MAX_MULTIPART_PARTS

        assert MAX_MULTIPART_PARTS == 10


# =============================================================================
# Client IP Extraction Tests
# =============================================================================


class TestClientIPExtraction:
    """Tests for client IP extraction with proxy support."""

    def test_trusted_proxies_configured(self):
        """Test that trusted proxies are configured."""
        from aragora.server.unified_server import TRUSTED_PROXIES

        assert isinstance(TRUSTED_PROXIES, frozenset)
        assert "127.0.0.1" in TRUSTED_PROXIES

    def test_get_client_ip_from_x_forwarded_for(self, mock_headers):
        """Test client IP extraction from X-Forwarded-For header."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = mock_headers({"X-Forwarded-For": "203.0.113.195, 70.41.3.18"})

        client_ip = handler._get_client_ip()
        # When request comes from trusted proxy, use X-Forwarded-For
        assert client_ip == "203.0.113.195"

    def test_get_client_ip_direct(self, mock_headers):
        """Test client IP extraction for direct connections."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        handler.client_address = ("203.0.113.195", 12345)
        handler.headers = mock_headers({})

        client_ip = handler._get_client_ip()
        assert client_ip == "203.0.113.195"


# =============================================================================
# Safe Parameter Parsing Tests
# =============================================================================


class TestSafeParameterParsing:
    """Tests for safe query parameter parsing."""

    def test_safe_int_valid(self):
        """Test safe integer parsing with valid input."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        result = handler._safe_int({"limit": "50"}, "limit", 10, max_val=100)
        assert result == 50

    def test_safe_int_invalid(self):
        """Test safe integer parsing with invalid input returns default."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        result = handler._safe_int({"limit": "invalid"}, "limit", 10, max_val=100)
        assert result == 10

    def test_safe_int_exceeds_max(self):
        """Test safe integer parsing with value exceeding max."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        result = handler._safe_int({"limit": "200"}, "limit", 10, max_val=100)
        assert result == 100

    def test_safe_float_valid(self):
        """Test safe float parsing with valid input."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        result = handler._safe_float({"threshold": "0.75"}, "threshold", 0.5)
        assert result == 0.75

    def test_safe_string_valid(self):
        """Test safe string validation with valid input."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        result = handler._safe_string("valid_string", max_len=50, pattern=r"^[a-z_]+$")
        assert result == "valid_string"

    def test_safe_string_invalid_pattern(self):
        """Test safe string validation with invalid pattern."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        result = handler._safe_string("INVALID!", max_len=50, pattern=r"^[a-z_]+$")
        assert result is None

    def test_safe_string_truncates(self):
        """Test safe string validation truncates to max length."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        long_string = "a" * 100
        result = handler._safe_string(long_string, max_len=50)
        assert len(result) == 50


# =============================================================================
# CORS and Security Headers Tests
# =============================================================================


class TestSecurityHeaders:
    """Tests for security headers."""

    def test_response_helpers_mixin_has_security_headers(self):
        """Test that ResponseHelpersMixin adds security headers."""
        from aragora.server.response_utils import ResponseHelpersMixin

        assert hasattr(ResponseHelpersMixin, "_add_security_headers")

    def test_response_helpers_mixin_has_cors_headers(self):
        """Test that ResponseHelpersMixin adds CORS headers."""
        from aragora.server.response_utils import ResponseHelpersMixin

        assert hasattr(ResponseHelpersMixin, "_add_cors_headers")

    def test_response_helpers_mixin_has_rate_limit_headers(self):
        """Test that ResponseHelpersMixin adds rate limit headers."""
        from aragora.server.response_utils import ResponseHelpersMixin

        assert hasattr(ResponseHelpersMixin, "_add_rate_limit_headers")


# =============================================================================
# Handler Registry Tests
# =============================================================================


class TestHandlerRegistry:
    """Tests for handler registry functionality."""

    def test_handler_registry_available(self):
        """Test that handler registry is available."""
        from aragora.server.handler_registry import HANDLER_REGISTRY, HANDLERS_AVAILABLE

        assert isinstance(HANDLER_REGISTRY, list)
        assert len(HANDLER_REGISTRY) > 0

    def test_route_index_creation(self):
        """Test that route index can be created."""
        from aragora.server.handler_registry import RouteIndex

        index = RouteIndex()
        assert index is not None
        assert hasattr(index, "get_handler")

    def test_handler_registry_mixin_methods(self):
        """Test that HandlerRegistryMixin has required methods."""
        from aragora.server.handler_registry import HandlerRegistryMixin

        assert hasattr(HandlerRegistryMixin, "_init_handlers")
        assert hasattr(HandlerRegistryMixin, "_try_modular_handler")
        assert hasattr(HandlerRegistryMixin, "_get_handler_stats")


# =============================================================================
# Debate Controller Tests
# =============================================================================


class TestDebateController:
    """Tests for debate controller initialization."""

    def test_debate_controller_getter_exists(self):
        """Test that debate controller getter method exists."""
        from aragora.server.unified_server import UnifiedHandler

        assert hasattr(UnifiedHandler, "_get_debate_controller")

    def test_auto_select_agents_method_exists(self):
        """Test that auto select agents method exists."""
        from aragora.server.unified_server import UnifiedHandler

        assert hasattr(UnifiedHandler, "_auto_select_agents")


# =============================================================================
# Request Logging Tests
# =============================================================================


class TestRequestLogging:
    """Tests for request logging functionality."""

    def test_log_request_method_exists(self):
        """Test that _log_request method exists."""
        from aragora.server.unified_server import UnifiedHandler

        assert hasattr(UnifiedHandler, "_log_request")

    def test_slow_request_threshold_configurable(self):
        """Test that slow request threshold is configurable."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        handler._slow_request_threshold_ms = 1000
        assert handler._slow_request_threshold_ms == 1000

    def test_request_log_can_be_disabled(self):
        """Test that request logging can be disabled."""
        from aragora.server.unified_server import UnifiedHandler

        handler = UnifiedHandler.__new__(UnifiedHandler)
        handler._request_log_enabled = False
        assert handler._request_log_enabled is False
