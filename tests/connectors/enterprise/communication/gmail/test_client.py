"""
Tests for Gmail Client Mixin.

Comprehensive tests for GmailClientMixin covering:
- OAuth URL generation
- Authentication with code and refresh token
- Token management and refresh
- Access token retrieval with auto-refresh
- API request handling with circuit breaker
- Client configuration properties
- User info retrieval
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from aragora.reasoning.provenance import SourceType


# =============================================================================
# Test Fixtures
# =============================================================================


class MockEnterpriseConnector:
    """Mock enterprise connector that implements EnterpriseConnectorMethods protocol."""

    def __init__(self):
        self._circuit_open = False
        self._failure_count = 0
        self._success_count = 0

    def check_circuit_breaker(self) -> bool:
        return not self._circuit_open

    def get_circuit_breaker_status(self) -> dict:
        return {"cooldown_seconds": 60, "failure_count": self._failure_count}

    def record_success(self) -> None:
        self._success_count += 1

    def record_failure(self) -> None:
        self._failure_count += 1


@pytest.fixture
def mock_httpx_response():
    """Factory for creating mock httpx responses."""

    def _create(status_code: int = 200, json_data: dict = None, content: bytes = b""):
        response = Mock()
        response.status_code = status_code
        response.json = Mock(return_value=json_data or {})
        response.content = content or json.dumps(json_data or {}).encode()
        response.text = (json_data and str(json_data)) or "{}"
        response.raise_for_status = Mock()
        if status_code >= 400:
            import httpx

            request = httpx.Request("GET", "https://gmail.googleapis.com/test")
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Error", request=request, response=response
            )
        return response

    return _create


@pytest.fixture
def client_mixin():
    """Create a client mixin instance with mock base."""
    from aragora.connectors.enterprise.communication.gmail.client import GmailClientMixin

    class TestMixin(GmailClientMixin, MockEnterpriseConnector):
        def __init__(self):
            super().__init__()
            self._access_token = None
            self._refresh_token = None
            self._token_expiry = None
            self._token_lock = asyncio.Lock()
            self.user_id = "me"

    return TestMixin()


@pytest.fixture(autouse=True)
def reset_refresh_token_fallback():
    """Prevent live saved Gmail tokens from leaking into unit tests."""
    with patch(
        "aragora.connectors.enterprise.communication.gmail.client._load_refresh_token_fallback",
        return_value=None,
    ):
        yield


@pytest.fixture
def authenticated_mixin(client_mixin):
    """Create an authenticated client mixin."""
    client_mixin._access_token = "test_access_token"
    client_mixin._refresh_token = "test_refresh_token"
    client_mixin._token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    return client_mixin


# =============================================================================
# Import JSON for Tests
# =============================================================================

import json


# =============================================================================
# Properties Tests
# =============================================================================


class TestClientProperties:
    """Tests for client property accessors."""

    def test_source_type(self, client_mixin):
        """Test source_type returns DOCUMENT."""
        assert client_mixin.source_type == SourceType.DOCUMENT

    def test_name(self, client_mixin):
        """Test name returns 'Gmail'."""
        assert client_mixin.name == "Gmail"

    def test_access_token_none_when_not_set(self, client_mixin):
        """Test access_token returns None when not set."""
        assert client_mixin.access_token is None

    def test_access_token_when_set(self, authenticated_mixin):
        """Test access_token returns value when set."""
        assert authenticated_mixin.access_token == "test_access_token"

    def test_refresh_token_none_when_not_set(self, client_mixin):
        """Test refresh_token returns None when not set."""
        assert client_mixin.refresh_token is None

    def test_refresh_token_when_set(self, authenticated_mixin):
        """Test refresh_token returns value when set."""
        assert authenticated_mixin.refresh_token == "test_refresh_token"

    def test_token_expiry_none_when_not_set(self, client_mixin):
        """Test token_expiry returns None when not set."""
        assert client_mixin.token_expiry is None

    def test_token_expiry_when_set(self, authenticated_mixin):
        """Test token_expiry returns value when set."""
        assert authenticated_mixin.token_expiry is not None

    def test_is_configured_without_env(self, client_mixin):
        """Test is_configured returns False without credentials."""
        with patch.dict("os.environ", {}, clear=True):
            assert client_mixin.is_configured is False

    def test_is_configured_with_gmail_client_id(self, client_mixin):
        """Test is_configured returns True with GMAIL_CLIENT_ID."""
        with patch.dict("os.environ", {"GMAIL_CLIENT_ID": "test_id"}):
            assert client_mixin.is_configured is True

    def test_is_configured_with_google_gmail_client_id(self, client_mixin):
        """Test is_configured returns True with GOOGLE_GMAIL_CLIENT_ID."""
        with patch.dict("os.environ", {"GOOGLE_GMAIL_CLIENT_ID": "test_id"}):
            assert client_mixin.is_configured is True

    def test_is_configured_with_google_client_id(self, client_mixin):
        """Test is_configured returns True with GOOGLE_CLIENT_ID."""
        with patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "test_id"}):
            assert client_mixin.is_configured is True


# =============================================================================
# OAuth URL Generation Tests
# =============================================================================


class TestOAuthUrlGeneration:
    """Tests for OAuth URL generation."""

    def test_get_oauth_url_basic(self, client_mixin):
        """Test OAuth URL generation with basic parameters."""
        with patch.dict("os.environ", {"GMAIL_CLIENT_ID": "test_client_id"}):
            url = client_mixin.get_oauth_url(
                redirect_uri="https://example.com/callback",
            )

            assert "accounts.google.com" in url
            assert "client_id=test_client_id" in url
            assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in url
            assert "response_type=code" in url
            assert "access_type=offline" in url
            assert "prompt=consent" in url

    def test_get_oauth_url_with_state(self, client_mixin):
        """Test OAuth URL generation with state parameter."""
        with patch.dict("os.environ", {"GMAIL_CLIENT_ID": "test_client_id"}):
            url = client_mixin.get_oauth_url(
                redirect_uri="https://example.com/callback",
                state="csrf_token_123",
            )

            assert "state=csrf_token_123" in url

    def test_get_oauth_url_without_state(self, client_mixin):
        """Test OAuth URL generation without state parameter."""
        with patch.dict("os.environ", {"GMAIL_CLIENT_ID": "test_client_id"}):
            url = client_mixin.get_oauth_url(
                redirect_uri="https://example.com/callback",
            )

            assert "state=" not in url

    def test_get_oauth_url_includes_scopes(self, client_mixin):
        """Test OAuth URL includes Gmail scopes."""
        with patch.dict("os.environ", {"GMAIL_CLIENT_ID": "test_client_id"}):
            url = client_mixin.get_oauth_url(
                redirect_uri="https://example.com/callback",
            )

            assert "gmail.readonly" in url

    def test_get_oauth_url_uses_env_fallbacks(self, client_mixin):
        """Test OAuth URL uses credential environment variable fallbacks."""
        with patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "fallback_id"}, clear=True):
            url = client_mixin.get_oauth_url(
                redirect_uri="https://example.com/callback",
            )

            assert "client_id=fallback_id" in url


# =============================================================================
# Authentication Tests
# =============================================================================


class MockHttpPoolSession:
    """Mock HTTP pool session context manager."""

    def __init__(self, mock_client):
        self.mock_client = mock_client

    async def __aenter__(self):
        return self.mock_client

    async def __aexit__(self, *args):
        pass


class MockHttpPool:
    """Mock HTTP client pool."""

    def __init__(self, mock_client):
        self.mock_client = mock_client

    def get_session(self, name: str):
        return MockHttpPoolSession(self.mock_client)


class TestAuthentication:
    """Tests for authentication methods."""

    @pytest.mark.asyncio
    async def test_authenticate_with_code_success(self, client_mixin, mock_httpx_response):
        """Test successful authentication with authorization code."""
        token_response = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, token_response))
        mock_pool = MockHttpPool(mock_client)

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch(
                "aragora.server.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                result = await client_mixin.authenticate(
                    code="auth_code_123",
                    redirect_uri="https://example.com/callback",
                )

                assert result is True
                assert client_mixin._access_token == "new_access_token"
                assert client_mixin._refresh_token == "new_refresh_token"
                assert client_mixin._token_expiry is not None

    @pytest.mark.asyncio
    async def test_authenticate_with_refresh_token_success(self, client_mixin, mock_httpx_response):
        """Test successful authentication with refresh token."""
        token_response = {
            "access_token": "refreshed_access_token",
            "expires_in": 3600,
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, token_response))
        mock_pool = MockHttpPool(mock_client)

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch(
                "aragora.server.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                result = await client_mixin.authenticate(
                    refresh_token="existing_refresh_token",
                )

                assert result is True
                assert client_mixin._access_token == "refreshed_access_token"
                assert client_mixin._refresh_token == "existing_refresh_token"

    @pytest.mark.asyncio
    async def test_authenticate_missing_credentials(self, client_mixin):
        """Test authentication fails without credentials."""
        with patch.dict("os.environ", {}, clear=True):
            result = await client_mixin.authenticate(
                code="auth_code",
                redirect_uri="https://example.com/callback",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_no_code_or_token(self, client_mixin):
        """Test authentication fails without code or refresh token."""
        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            result = await client_mixin.authenticate()

            assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_api_error(self, client_mixin, mock_httpx_response):
        """Test authentication handles API errors."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value=mock_httpx_response(401, {"error": "invalid_grant"})
        )
        mock_pool = MockHttpPool(mock_client)

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch(
                "aragora.server.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                result = await client_mixin.authenticate(
                    code="invalid_code",
                    redirect_uri="https://example.com/callback",
                )

                assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_preserves_refresh_token_on_refresh(
        self, client_mixin, mock_httpx_response
    ):
        """Test refresh authentication preserves existing refresh token if not returned."""
        token_response = {
            "access_token": "new_access_token",
            "expires_in": 3600,
            # No refresh_token in response
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, token_response))
        mock_pool = MockHttpPool(mock_client)

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch(
                "aragora.server.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                await client_mixin.authenticate(refresh_token="original_refresh_token")

                assert client_mixin._refresh_token == "original_refresh_token"


# =============================================================================
# Token Management Tests
# =============================================================================


class TestTokenManagement:
    """Tests for token management."""

    @pytest.mark.asyncio
    async def test_get_access_token_valid(self, authenticated_mixin):
        """Test getting valid access token."""
        token = await authenticated_mixin._get_access_token()
        assert token == "test_access_token"

    @pytest.mark.asyncio
    async def test_get_access_token_expired_refreshes(
        self, authenticated_mixin, mock_httpx_response
    ):
        """Test that expired token triggers refresh."""
        # Set token to expired
        authenticated_mixin._token_expiry = datetime.now(timezone.utc) - timedelta(hours=1)

        token_response = {
            "access_token": "new_access_token",
            "expires_in": 3600,
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, token_response))
        mock_pool = MockHttpPool(mock_client)

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch(
                "aragora.server.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                token = await authenticated_mixin._get_access_token()

                assert token == "new_access_token"

    @pytest.mark.asyncio
    async def test_get_access_token_no_token_no_refresh(self, client_mixin):
        """Test error when no token and no refresh token."""
        with pytest.raises(ValueError, match="No valid access token"):
            await client_mixin._get_access_token()

    @pytest.mark.asyncio
    async def test_get_access_token_uses_saved_refresh_token_fallback(self, client_mixin):
        """Test access token lookup loads a saved refresh token fallback."""
        client_mixin._access_token = None
        client_mixin._refresh_token = None

        with (
            patch(
                "aragora.connectors.enterprise.communication.gmail.client._load_refresh_token_fallback",
                return_value="saved-refresh-token",
            ),
            patch.object(
                client_mixin,
                "_refresh_access_token",
                AsyncMock(return_value="new_access_token"),
            ) as mock_refresh,
        ):
            token = await client_mixin._get_access_token()

        assert token == "new_access_token"
        assert client_mixin._refresh_token == "saved-refresh-token"
        mock_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_access_token_thread_safe(self, authenticated_mixin, mock_httpx_response):
        """Test token refresh is thread-safe with lock."""
        # Set token to expired
        authenticated_mixin._token_expiry = datetime.now(timezone.utc) - timedelta(hours=1)

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # Simulate network delay
            return mock_httpx_response(
                200,
                {
                    "access_token": f"token_{call_count}",
                    "expires_in": 3600,
                },
            )

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_pool = MockHttpPool(mock_client)

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch(
                "aragora.server.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                # Simulate concurrent token requests
                results = await asyncio.gather(
                    authenticated_mixin._get_access_token(),
                    authenticated_mixin._get_access_token(),
                    authenticated_mixin._get_access_token(),
                )

                # All should get the same token due to lock
                assert all(r == results[0] for r in results)

    @pytest.mark.asyncio
    async def test_refresh_access_token(self, authenticated_mixin, mock_httpx_response):
        """Test refresh_access_token method."""
        token_response = {
            "access_token": "refreshed_token",
            "expires_in": 3600,
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, token_response))
        mock_pool = MockHttpPool(mock_client)

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch(
                "aragora.server.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ):
                token = await authenticated_mixin._refresh_access_token()

                assert token == "refreshed_token"
                assert authenticated_mixin._access_token == "refreshed_token"

    @pytest.mark.asyncio
    async def test_refresh_access_token_no_refresh_token(self, client_mixin):
        """Test refresh fails without refresh token."""
        with pytest.raises(ValueError, match="No refresh token"):
            await client_mixin._refresh_access_token()


# =============================================================================
# API Request Tests
# =============================================================================


class TestApiRequests:
    """Tests for API request handling."""

    @pytest.mark.asyncio
    async def test_api_request_success(self, authenticated_mixin, mock_httpx_response):
        """Test successful API request."""
        response_data = {"messages": [{"id": "msg_1"}]}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_httpx_response(200, response_data))
        mock_pool = MockHttpPool(mock_client)

        with patch(
            "aragora.server.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await authenticated_mixin._api_request("/messages")

            assert result == response_data

    @pytest.mark.asyncio
    async def test_api_request_builds_correct_url(self, authenticated_mixin, mock_httpx_response):
        """Test API request builds correct URL."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_httpx_response(200, {}))
        mock_pool = MockHttpPool(mock_client)

        with patch(
            "aragora.server.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            await authenticated_mixin._api_request("/messages")

            call_args = mock_client.request.call_args
            # The URL is the second positional argument
            url = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("url", "")
            assert "gmail.googleapis.com" in url
            assert "/users/me/messages" in url

    @pytest.mark.asyncio
    async def test_api_request_includes_auth_header(self, authenticated_mixin, mock_httpx_response):
        """Test API request includes authorization header."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_httpx_response(200, {}))
        mock_pool = MockHttpPool(mock_client)

        with patch(
            "aragora.server.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            await authenticated_mixin._api_request("/messages")

            call_args = mock_client.request.call_args
            headers = call_args.kwargs.get("headers", {})
            assert "Authorization" in headers
            assert "Bearer test_access_token" in headers["Authorization"]

    @pytest.mark.asyncio
    async def test_api_request_circuit_breaker_open(self, authenticated_mixin):
        """Test API request fails when circuit breaker is open."""
        authenticated_mixin._circuit_open = True

        with pytest.raises(ConnectionError, match="Circuit breaker open"):
            await authenticated_mixin._api_request("/messages")

    @pytest.mark.asyncio
    async def test_api_request_records_failure_on_5xx(
        self, authenticated_mixin, mock_httpx_response
    ):
        """Test 5xx errors record failures for circuit breaker."""
        error_response = mock_httpx_response(500, {"error": "Server error"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=error_response)
        mock_pool = MockHttpPool(mock_client)

        with patch(
            "aragora.server.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            with pytest.raises(Exception):
                await authenticated_mixin._api_request("/messages")

            assert authenticated_mixin._failure_count == 1

    @pytest.mark.asyncio
    async def test_api_request_records_failure_on_429(
        self, authenticated_mixin, mock_httpx_response
    ):
        """Test rate limit errors record failures."""
        error_response = mock_httpx_response(429, {"error": "Rate limit"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=error_response)
        mock_pool = MockHttpPool(mock_client)

        with patch(
            "aragora.server.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            with pytest.raises(Exception):
                await authenticated_mixin._api_request("/messages")

            assert authenticated_mixin._failure_count == 1

    @pytest.mark.asyncio
    async def test_api_request_records_success(self, authenticated_mixin, mock_httpx_response):
        """Test successful requests record success."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_httpx_response(200, {}))
        mock_pool = MockHttpPool(mock_client)

        with patch(
            "aragora.server.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            await authenticated_mixin._api_request("/messages")

            assert authenticated_mixin._success_count == 1

    @pytest.mark.asyncio
    async def test_api_request_with_params(self, authenticated_mixin, mock_httpx_response):
        """Test API request passes query parameters."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_httpx_response(200, {}))
        mock_pool = MockHttpPool(mock_client)

        with patch(
            "aragora.server.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            await authenticated_mixin._api_request(
                "/messages",
                params={"maxResults": 10, "q": "from:test@example.com"},
            )

            call_args = mock_client.request.call_args
            params = call_args.kwargs.get("params", {})
            assert params["maxResults"] == 10
            assert params["q"] == "from:test@example.com"

    @pytest.mark.asyncio
    async def test_api_request_with_json_data(self, authenticated_mixin, mock_httpx_response):
        """Test API request passes JSON data."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_httpx_response(200, {}))
        mock_pool = MockHttpPool(mock_client)

        with patch(
            "aragora.server.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            await authenticated_mixin._api_request(
                "/messages/msg_1/modify",
                method="POST",
                json_data={"addLabelIds": ["STARRED"]},
            )

            call_args = mock_client.request.call_args
            json_data = call_args.kwargs.get("json", {})
            assert json_data["addLabelIds"] == ["STARRED"]

    @pytest.mark.asyncio
    async def test_api_request_timeout_records_failure(self, authenticated_mixin):
        """Test timeout errors record failures."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=TimeoutError("Timeout"))
        mock_pool = MockHttpPool(mock_client)

        with patch(
            "aragora.server.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            with pytest.raises(TimeoutError):
                await authenticated_mixin._api_request("/messages")

            assert authenticated_mixin._failure_count == 1

    @pytest.mark.asyncio
    async def test_api_request_connection_error_records_failure(self, authenticated_mixin):
        """Test connection errors record failures."""
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=ConnectionError("Network error"))
        mock_pool = MockHttpPool(mock_client)

        with patch(
            "aragora.server.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            with pytest.raises(ConnectionError):
                await authenticated_mixin._api_request("/messages")

            assert authenticated_mixin._failure_count == 1


# =============================================================================
# HTTP Client Tests
# =============================================================================


class TestHttpClient:
    """Tests for HTTP client management."""

    def test_get_client_returns_context_manager(self, client_mixin):
        """Test _get_client returns an httpx client context manager."""
        client = client_mixin._get_client()
        assert client is not None


# =============================================================================
# User Info Tests
# =============================================================================


class TestUserInfo:
    """Tests for user info retrieval."""

    @pytest.mark.asyncio
    async def test_get_user_info(self, authenticated_mixin):
        """Test getting user profile information."""
        profile_data = {
            "emailAddress": "user@example.com",
            "messagesTotal": 1000,
            "threadsTotal": 500,
            "historyId": "12345",
        }

        with patch.object(authenticated_mixin, "_api_request", return_value=profile_data):
            result = await authenticated_mixin.get_user_info()

            assert result["emailAddress"] == "user@example.com"
            assert result["messagesTotal"] == 1000
            assert result["historyId"] == "12345"

    @pytest.mark.asyncio
    async def test_get_user_info_calls_profile_endpoint(self, authenticated_mixin):
        """Test get_user_info calls the correct endpoint."""
        with patch.object(authenticated_mixin, "_api_request") as mock_request:
            mock_request.return_value = {}

            await authenticated_mixin.get_user_info()

            mock_request.assert_called_once_with("/profile")


# =============================================================================
# Scope Constants Tests
# =============================================================================


class TestScopeConstants:
    """Tests for Gmail scope constants."""

    def test_readonly_scopes(self):
        """Test readonly scopes."""
        from aragora.connectors.enterprise.communication.gmail.client import (
            GMAIL_SCOPES_READONLY,
        )

        assert "gmail.readonly" in GMAIL_SCOPES_READONLY[0]
        assert len(GMAIL_SCOPES_READONLY) == 1

    def test_full_scopes(self):
        """Test full scopes include send and modify."""
        from aragora.connectors.enterprise.communication.gmail.client import (
            GMAIL_SCOPES_FULL,
        )

        scope_str = " ".join(GMAIL_SCOPES_FULL)
        assert "gmail.readonly" in scope_str
        assert "gmail.send" in scope_str
        assert "gmail.modify" in scope_str

    def test_default_scopes_are_readonly(self):
        """Test default scopes are readonly."""
        from aragora.connectors.enterprise.communication.gmail.client import (
            GMAIL_SCOPES,
            GMAIL_SCOPES_READONLY,
        )

        assert GMAIL_SCOPES == GMAIL_SCOPES_READONLY


# =============================================================================
# Credential Helper Tests
# =============================================================================


class TestCredentialHelpers:
    """Tests for credential helper functions."""

    def test_get_client_credentials_gmail_prefix(self):
        """Test credential lookup with GMAIL_ prefix."""
        from aragora.connectors.enterprise.communication.gmail.client import (
            _get_client_credentials,
        )

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "gmail_id",
                "GMAIL_CLIENT_SECRET": "gmail_secret",
            },
            clear=True,
        ):
            client_id, client_secret = _get_client_credentials()

            assert client_id == "gmail_id"
            assert client_secret == "gmail_secret"

    def test_get_client_credentials_google_gmail_prefix(self):
        """Test credential lookup with GOOGLE_GMAIL_ prefix."""
        from aragora.connectors.enterprise.communication.gmail.client import (
            _get_client_credentials,
        )

        with patch.dict(
            "os.environ",
            {
                "GOOGLE_GMAIL_CLIENT_ID": "google_gmail_id",
                "GOOGLE_GMAIL_CLIENT_SECRET": "google_gmail_secret",
            },
            clear=True,
        ):
            client_id, client_secret = _get_client_credentials()

            assert client_id == "google_gmail_id"
            assert client_secret == "google_gmail_secret"

    def test_get_client_credentials_google_prefix_fallback(self):
        """Test credential lookup with GOOGLE_ prefix fallback."""
        from aragora.connectors.enterprise.communication.gmail.client import (
            _get_client_credentials,
        )

        with patch.dict(
            "os.environ",
            {
                "GOOGLE_CLIENT_ID": "google_id",
                "GOOGLE_CLIENT_SECRET": "google_secret",
            },
            clear=True,
        ):
            client_id, client_secret = _get_client_credentials()

            assert client_id == "google_id"
            assert client_secret == "google_secret"

    def test_get_client_credentials_priority(self):
        """Test credential priority: GMAIL_ > GOOGLE_GMAIL_ > GOOGLE_."""
        from aragora.connectors.enterprise.communication.gmail.client import (
            _get_client_credentials,
        )

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "gmail_id",
                "GOOGLE_GMAIL_CLIENT_ID": "google_gmail_id",
                "GOOGLE_CLIENT_ID": "google_id",
                "GMAIL_CLIENT_SECRET": "gmail_secret",
            },
        ):
            client_id, client_secret = _get_client_credentials()

            assert client_id == "gmail_id"
            assert client_secret == "gmail_secret"
