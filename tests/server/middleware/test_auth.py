"""
Tests for aragora.server.middleware.auth - Authentication middleware.

Tests cover:
- AuthContext dataclass
- Token extraction from headers
- Client IP extraction
- Token validation
- require_auth decorator
- optional_auth decorator
- require_auth_or_localhost decorator
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Test Fixtures
# ===========================================================================


@dataclass
class MockHandler:
    """Mock HTTP handler for testing."""

    headers: dict[str, str]
    client_address: tuple[str, int] = ("127.0.0.1", 12345)


@pytest.fixture
def mock_handler():
    """Create a mock handler with no auth."""
    return MockHandler(headers={})


@pytest.fixture
def mock_handler_with_token():
    """Create a mock handler with valid token."""
    return MockHandler(headers={"Authorization": "Bearer valid-token-123"})


@pytest.fixture
def mock_handler_with_xff():
    """Create a mock handler with X-Forwarded-For header."""
    return MockHandler(
        headers={"X-Forwarded-For": "192.168.1.100, 10.0.0.1"},
        client_address=("127.0.0.1", 12345),
    )


# ===========================================================================
# Test AuthContext
# ===========================================================================


class TestAuthContext:
    """Tests for AuthContext dataclass."""

    def test_default_not_authenticated(self):
        """AuthContext should default to not authenticated."""
        from aragora.server.middleware.auth import AuthContext

        ctx = AuthContext()

        assert ctx.authenticated is False
        assert ctx.token is None
        assert ctx.client_ip is None
        assert ctx.user_id is None

    def test_is_authenticated_alias(self):
        """is_authenticated should be an alias for authenticated."""
        from aragora.server.middleware.auth import AuthContext

        ctx = AuthContext(authenticated=True)
        assert ctx.is_authenticated is True

        ctx2 = AuthContext(authenticated=False)
        assert ctx2.is_authenticated is False

    def test_full_context(self):
        """AuthContext should store all provided values."""
        from aragora.server.middleware.auth import AuthContext

        ctx = AuthContext(
            authenticated=True,
            token="test-token",
            client_ip="192.168.1.1",
            user_id="user-123",
        )

        assert ctx.authenticated is True
        assert ctx.token == "test-token"
        assert ctx.client_ip == "192.168.1.1"
        assert ctx.user_id == "user-123"


# ===========================================================================
# Test Token Extraction
# ===========================================================================


class TestExtractToken:
    """Tests for extract_token function."""

    def test_extract_bearer_token(self, mock_handler_with_token):
        """Should extract token from Bearer auth header."""
        from aragora.server.middleware.auth import extract_token

        token = extract_token(mock_handler_with_token)
        assert token == "valid-token-123"

    def test_extract_no_header(self, mock_handler):
        """Should return None when no Authorization header."""
        from aragora.server.middleware.auth import extract_token

        token = extract_token(mock_handler)
        assert token is None

    def test_extract_non_bearer(self):
        """Should return None for non-Bearer auth."""
        from aragora.server.middleware.auth import extract_token

        handler = MockHandler(headers={"Authorization": "Basic dXNlcjpwYXNz"})
        token = extract_token(handler)
        assert token is None

    def test_extract_empty_bearer(self):
        """Should return empty string for empty Bearer value."""
        from aragora.server.middleware.auth import extract_token

        handler = MockHandler(headers={"Authorization": "Bearer "})
        token = extract_token(handler)
        assert token == ""

    def test_extract_none_handler(self):
        """Should return None for None handler."""
        from aragora.server.middleware.auth import extract_token

        token = extract_token(None)
        assert token is None

    def test_extract_handler_without_headers(self):
        """Should return None for handler without headers."""
        from aragora.server.middleware.auth import extract_token

        handler = MagicMock(spec=[])  # No headers attribute
        token = extract_token(handler)
        assert token is None


# ===========================================================================
# Test Client IP Extraction
# ===========================================================================


class TestExtractClientIP:
    """Tests for extract_client_ip function."""

    def test_extract_from_client_address(self, mock_handler):
        """Should extract IP from client_address."""
        from aragora.server.middleware.auth import extract_client_ip

        ip = extract_client_ip(mock_handler)
        assert ip == "127.0.0.1"

    def test_extract_from_xff(self, mock_handler_with_xff):
        """Should prefer X-Forwarded-For over client_address."""
        from aragora.server.middleware.auth import extract_client_ip

        ip = extract_client_ip(mock_handler_with_xff)
        # XFF ignored without TRUSTED_PROXY_CIDRS (security hardening)
        assert ip == "127.0.0.1"

    def test_extract_none_handler(self):
        """Should return None for None handler."""
        from aragora.server.middleware.auth import extract_client_ip

        ip = extract_client_ip(None)
        assert ip is None

    def test_extract_ipv6(self):
        """Should handle IPv6 addresses."""
        from aragora.server.middleware.auth import extract_client_ip

        handler = MockHandler(
            headers={},
            client_address=("::1", 12345),
        )
        ip = extract_client_ip(handler)
        assert ip == "::1"

    def test_auth_legacy_path_warns(self, mock_handler):
        """The old auth symbol remains a warning compatibility shim."""
        from aragora.server.middleware.auth import extract_client_ip

        with pytest.warns(
            DeprecationWarning, match="aragora.server.middleware.auth.extract_client_ip"
        ):
            assert extract_client_ip(mock_handler) == "127.0.0.1"

    def test_user_auth_legacy_path_warns(self, mock_handler):
        """The old user_auth symbol remains a warning compatibility shim."""
        from aragora.server.middleware.user_auth import extract_client_ip

        with pytest.warns(
            DeprecationWarning,
            match="aragora.server.middleware.user_auth.extract_client_ip",
        ):
            assert extract_client_ip(mock_handler) == "127.0.0.1"


# ===========================================================================
# Test Token Validation
# ===========================================================================


class TestValidateToken:
    """Tests for validate_token function."""

    def test_validate_empty_token(self):
        """Should reject empty token."""
        from aragora.server.middleware.auth import validate_token

        assert validate_token("") is False
        assert validate_token(None) is False  # type: ignore[arg-type]

    def test_validate_valid_token(self):
        """Should accept valid token."""
        from aragora.server.middleware.auth import validate_token

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.validate_token.return_value = True
            with patch(
                "aragora.server.middleware.token_revocation.is_token_revoked", return_value=False
            ):
                result = validate_token("valid-token")
                assert result is True

    def test_validate_invalid_token(self):
        """Should reject invalid token."""
        from aragora.server.middleware.auth import validate_token

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.validate_token.return_value = False
            result = validate_token("invalid-token")
            assert result is False

    def test_validate_revoked_token(self):
        """Should reject revoked token."""
        from aragora.server.middleware.auth import validate_token

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.validate_token.return_value = True
            with patch(
                "aragora.server.middleware.token_revocation.is_token_revoked", return_value=True
            ):
                result = validate_token("revoked-token")
                assert result is False


# ===========================================================================
# Test require_auth Decorator
# ===========================================================================


class TestRequireAuth:
    """Tests for require_auth decorator."""

    def test_require_auth_no_handler(self):
        """Should return 401 when no handler provided."""
        from aragora.server.middleware.auth import require_auth

        @require_auth
        def protected_func():
            return "success"

        result = protected_func()
        assert result.status_code == 401
        assert "Authentication required" in result.body.decode()

    def test_require_auth_no_api_token_configured(self, mock_handler):
        """Should return 401 when no API token is configured."""
        from aragora.server.middleware.auth import require_auth

        @require_auth
        def protected_func(handler):
            return "success"

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.api_token = None
            result = protected_func(handler=mock_handler)
            assert result.status_code == 401
            assert "ARAGORA_API_TOKEN" in result.body.decode()

    def test_require_auth_missing_token(self, mock_handler):
        """Should return 401 when token is missing."""
        from aragora.server.middleware.auth import require_auth

        @require_auth
        def protected_func(handler):
            return "success"

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.api_token = "configured-token"
            result = protected_func(handler=mock_handler)
            assert result.status_code == 401

    def test_require_auth_invalid_token(self, mock_handler_with_token):
        """Should return 401 when token is invalid."""
        from aragora.server.middleware.auth import require_auth

        @require_auth
        def protected_func(handler):
            return "success"

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.api_token = "configured-token"
            mock_config.validate_token.return_value = False
            result = protected_func(handler=mock_handler_with_token)
            assert result.status_code == 401

    def test_require_auth_valid_token(self, mock_handler_with_token):
        """Should allow access with valid token."""
        from aragora.server.middleware.auth import require_auth

        @require_auth
        def protected_func(handler):
            return "success"

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.api_token = "configured-token"
            mock_config.validate_token.return_value = True
            with patch(
                "aragora.server.middleware.token_revocation.is_token_revoked", return_value=False
            ):
                result = protected_func(handler=mock_handler_with_token)
                assert result == "success"


# ===========================================================================
# Test optional_auth Decorator
# ===========================================================================


class TestOptionalAuth:
    """Tests for optional_auth decorator."""

    def test_optional_auth_no_token(self, mock_handler):
        """Should provide unauthenticated context when no token."""
        from aragora.server.middleware.auth import optional_auth

        @optional_auth
        def public_func(handler, auth_context):
            return auth_context

        result = public_func(handler=mock_handler)
        assert result.authenticated is False
        assert result.token is None

    def test_optional_auth_valid_token(self, mock_handler_with_token):
        """Should provide authenticated context with valid token."""
        from aragora.server.middleware.auth import optional_auth

        @optional_auth
        def public_func(handler, auth_context):
            return auth_context

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.validate_token.return_value = True
            with patch(
                "aragora.server.middleware.token_revocation.is_token_revoked", return_value=False
            ):
                result = public_func(handler=mock_handler_with_token)
                assert result.authenticated is True
                assert result.token == "valid-token-123"

    def test_optional_auth_invalid_token(self, mock_handler_with_token):
        """Should provide unauthenticated context with invalid token."""
        from aragora.server.middleware.auth import optional_auth

        @optional_auth
        def public_func(handler, auth_context):
            return auth_context

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.validate_token.return_value = False
            result = public_func(handler=mock_handler_with_token)
            assert result.authenticated is False
            assert result.token is None

    def test_optional_auth_includes_client_ip(self, mock_handler_with_xff):
        """Should include client IP in context."""
        from aragora.server.middleware.auth import optional_auth

        @optional_auth
        def public_func(handler, auth_context):
            return auth_context

        result = public_func(handler=mock_handler_with_xff)
        # XFF ignored without TRUSTED_PROXY_CIDRS (security hardening)
        assert result.client_ip == "127.0.0.1"


# ===========================================================================
# Test require_auth_or_localhost Decorator
# ===========================================================================


class TestRequireAuthOrLocalhost:
    """Tests for require_auth_or_localhost decorator."""

    def test_allows_localhost_ipv4(self):
        """Should allow requests from 127.0.0.1 without token."""
        from aragora.server.middleware.auth import require_auth_or_localhost

        @require_auth_or_localhost
        def protected_func(handler):
            return "success"

        handler = MockHandler(
            headers={},
            client_address=("127.0.0.1", 12345),
        )

        # Localhost requests don't need auth_config patch - they bypass auth
        result = protected_func(handler=handler)
        assert result == "success"

    def test_allows_localhost_ipv6(self):
        """Should allow requests from ::1 without token."""
        from aragora.server.middleware.auth import require_auth_or_localhost

        @require_auth_or_localhost
        def protected_func(handler):
            return "success"

        handler = MockHandler(
            headers={},
            client_address=("::1", 12345),
        )

        # Localhost requests don't need auth_config patch - they bypass auth
        result = protected_func(handler=handler)
        assert result == "success"

    def test_requires_auth_for_remote(self):
        """Should require auth for non-localhost requests."""
        from aragora.server.middleware.auth import require_auth_or_localhost

        @require_auth_or_localhost
        def protected_func(handler):
            return "success"

        handler = MockHandler(
            headers={},
            client_address=("192.168.1.100", 12345),
        )

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.api_token = "configured-token"
            result = protected_func(handler=handler)
            assert result.status_code == 401

    def test_allows_remote_with_valid_token(self):
        """Should allow remote requests with valid token."""
        from aragora.server.middleware.auth import require_auth_or_localhost

        @require_auth_or_localhost
        def protected_func(handler):
            return "success"

        handler = MockHandler(
            headers={"Authorization": "Bearer valid-token"},
            client_address=("192.168.1.100", 12345),
        )

        with patch("aragora.server.auth.auth_config") as mock_config:
            mock_config.api_token = "configured-token"
            mock_config.validate_token.return_value = True
            with patch(
                "aragora.server.middleware.token_revocation.is_token_revoked", return_value=False
            ):
                result = protected_func(handler=handler)
                assert result == "success"


# ===========================================================================
# Test Edge Cases
# ===========================================================================


class TestAuthEdgeCases:
    """Edge case tests for auth middleware."""

    def test_handler_extraction_from_args(self):
        """Should extract handler from positional args."""
        from aragora.server.middleware.auth import optional_auth

        @optional_auth
        def func(self_arg, handler, auth_context):
            return auth_context

        handler = MockHandler(headers={})
        result = func("self", handler)
        assert result.client_ip == "127.0.0.1"

    def test_token_with_extra_spaces(self):
        """Should handle token with extra whitespace."""
        from aragora.server.middleware.auth import extract_token

        handler = MockHandler(headers={"Authorization": "Bearer   token-with-spaces  "})
        token = extract_token(handler)
        # Token includes the extra spaces after "Bearer "
        assert token == "  token-with-spaces  "

    def test_multiple_xff_ips(self):
        """XFF is ignored without TRUSTED_PROXY_CIDRS (security hardening)."""
        from aragora.server.middleware.auth import extract_client_ip

        handler = MockHandler(
            headers={"X-Forwarded-For": "  10.0.0.1  , 192.168.1.1, 172.16.0.1"},
            client_address=("127.0.0.1", 12345),
        )
        ip = extract_client_ip(handler)
        assert ip == "127.0.0.1"
