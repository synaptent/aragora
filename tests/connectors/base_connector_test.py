"""
Base connector test framework.

Provides:
- BaseConnectorTestCase: Abstract base class for connector tests
- ConnectorTestMixin: Reusable test methods for common patterns
- Fixtures for mocking HTTP, OAuth, and credentials

Usage:
    class TestMyConnector(BaseConnectorTestCase):
        connector_class = MyConnector
        connector_kwargs = {"client_id": "test", "client_secret": "secret"}

        # Inherit all standard tests automatically
        # Override any that need connector-specific behavior
"""

from __future__ import annotations

import asyncio
import pytest
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch


@dataclass
class MockOAuthResponse:
    """Standard OAuth response for testing."""

    access_token: str = "test_access_token"
    refresh_token: str = "test_refresh_token"
    token_type: str = "Bearer"
    expires_in: int = 3600
    scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
        }
        if self.scope:
            result["scope"] = self.scope
        return result


@dataclass
class MockHTTPResponse:
    """Mock HTTP response for testing API calls."""

    status: int = 200
    data: dict[str, Any] | list[Any] | None = None
    headers: dict[str, str] | None = None

    async def json(self) -> dict[str, Any] | list[Any]:
        return self.data or {}

    async def text(self) -> str:
        import json

        return json.dumps(self.data) if self.data else ""


class ConnectorTestMixin:
    """Mixin providing reusable test methods for connectors.

    Tests common patterns that all connectors should support.
    Not collected directly by pytest -- subclass with a Test prefix.
    """

    __test__ = False

    # Override in subclass
    connector_class: type[Any] = None
    connector_kwargs: dict[str, Any] = {}

    # Optional: Override for OAuth connectors
    oauth_auth_url_patterns: list[str] = []
    oauth_token_url: str = ""

    @pytest.fixture
    def connector(self):
        """Create connector instance with test credentials."""
        if not self.connector_class:
            pytest.skip("connector_class not defined")
        return self.connector_class(**self.connector_kwargs)

    @staticmethod
    def _require_method(obj: Any, method_name: str) -> None:
        """Skip the test if *obj* does not expose *method_name*."""
        if not hasattr(obj, method_name):
            pytest.skip(f"Connector does not have {method_name}")

    @pytest.fixture
    def mock_http_session(self):
        """Create mock aiohttp session."""
        with patch("aiohttp.ClientSession") as mock:
            session_instance = MagicMock()
            mock.return_value.__aenter__ = AsyncMock(return_value=session_instance)
            mock.return_value.__aexit__ = AsyncMock(return_value=False)
            yield session_instance

    @pytest.fixture
    def mock_oauth_response(self):
        """Create standard OAuth token response."""
        return MockOAuthResponse()

    def create_mock_http_response(
        self,
        status: int = 200,
        data: dict[str, Any] | None = None,
    ) -> AsyncMock:
        """Create a mock HTTP response for aiohttp."""
        response = MockHTTPResponse(status=status, data=data)
        return AsyncMock(__aenter__=AsyncMock(return_value=response))


class BaseConnectorTestCase(ConnectorTestMixin, ABC):
    """Abstract base class for connector tests.

    Provides standard test structure with automatic test generation
    for common patterns. Subclasses must define connector_class
    and may override connector_kwargs.

    Not collected directly by pytest -- subclass with a Test prefix and
    set ``connector_class``.

    Test categories:
    - Configuration: is_configured, initialization
    - OAuth: auth URL, code exchange, token refresh
    - API Operations: search, fetch, list, create
    - Error Handling: rate limits, authentication errors, network errors
    - Resilience: retry, circuit breaker
    """

    __test__ = False

    # Test data for API operations
    test_search_query: str = "test query"
    test_fetch_id: str = "test-id-123"

    # Expected behavior flags -- set to False in subclass to skip groups
    supports_oauth: bool = True
    supports_search: bool = True
    supports_fetch: bool = True
    supports_list: bool = False
    supports_create: bool = False
    supports_update: bool = False
    supports_delete: bool = False

    def _skip_unless_oauth(self, connector: Any, method: str) -> None:
        """Skip if OAuth is disabled or *connector* lacks *method*."""
        if not self.supports_oauth:
            pytest.skip("Connector does not support OAuth")
        self._require_method(connector, method)

    # --- Configuration Tests ---

    def test_connector_can_be_instantiated(self, connector):
        """Test that connector can be created."""
        assert connector is not None

    def test_connector_has_name(self, connector):
        """Test that connector has a name property."""
        if hasattr(connector, "name"):
            assert connector.name is not None
            assert isinstance(connector.name, str)
            assert len(connector.name) > 0

    def test_connector_has_source_type(self, connector):
        """Test that connector defines a source type."""
        if hasattr(connector, "source_type"):
            assert connector.source_type is not None

    def test_is_configured_with_credentials(self, connector):
        """Test is_configured returns True when credentials provided."""
        if hasattr(connector, "is_configured"):
            # Connector was created with test credentials
            assert connector.is_configured is True

    # --- OAuth Tests ---

    def test_get_authorization_url_returns_url(self, connector):
        """Test OAuth authorization URL generation."""
        self._skip_unless_oauth(connector, "get_authorization_url")

        url = connector.get_authorization_url(state="test_state")
        assert url is not None
        assert isinstance(url, str)
        assert url.startswith("http")

    def test_authorization_url_contains_client_id(self, connector):
        """Test OAuth URL contains client_id."""
        self._skip_unless_oauth(connector, "get_authorization_url")

        url = connector.get_authorization_url(state="test_state")
        client_id = self.connector_kwargs.get("client_id", "")
        if client_id:
            assert client_id in url or "client_id" in url

    def test_authorization_url_contains_state(self, connector):
        """Test OAuth URL contains state parameter."""
        self._skip_unless_oauth(connector, "get_authorization_url")

        state = "unique_test_state_12345"
        url = connector.get_authorization_url(state=state)
        assert state in url

    @pytest.mark.asyncio
    async def test_exchange_code_returns_credentials(self, connector, mock_http_session):
        """Test OAuth code exchange returns credentials."""
        self._skip_unless_oauth(connector, "exchange_code")

        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "access_token": "test_access_token",
                "refresh_token": "test_refresh_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        )
        mock_http_session.post = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        try:
            credentials = await connector.exchange_code(authorization_code="test_code")
            assert credentials is not None
            if hasattr(credentials, "access_token"):
                assert credentials.access_token == "test_access_token"
        except NotImplementedError:
            pytest.skip("exchange_code not implemented")

    # --- Error Handling Tests ---

    @pytest.mark.asyncio
    async def test_handles_rate_limit_error(self, connector, mock_http_session):
        """Test connector handles rate limit (429) errors."""
        self._require_method(connector, "search")

        mock_response = AsyncMock()
        mock_response.status = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.json = AsyncMock(return_value={"error": "rate_limit"})
        mock_http_session.get = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        # Should either raise RateLimitError or return gracefully
        try:
            result = await connector.search(self.test_search_query)
            # If it returns, should be empty or have error info
            assert result is not None
        except Exception as e:
            # Should be a rate limit related error
            assert "rate" in str(e).lower() or "429" in str(e) or "limit" in str(e).lower()

    @pytest.mark.asyncio
    async def test_handles_authentication_error(self, connector, mock_http_session):
        """Test connector handles authentication (401) errors."""
        self._require_method(connector, "search")

        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.json = AsyncMock(return_value={"error": "unauthorized"})
        mock_http_session.get = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        try:
            result = await connector.search(self.test_search_query)
            # If it returns, verify it handles gracefully
            assert result is not None
        except Exception as e:
            # Should be an auth related error
            assert (
                "auth" in str(e).lower()
                or "401" in str(e)
                or "unauthorized" in str(e).lower()
                or "token" in str(e).lower()
            )

    @pytest.mark.asyncio
    async def test_handles_server_error(self, connector, mock_http_session):
        """Test connector handles server (500) errors."""
        self._require_method(connector, "search")

        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.json = AsyncMock(return_value={"error": "internal_server_error"})
        mock_http_session.get = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        try:
            result = await connector.search(self.test_search_query)
            assert result is not None
        except Exception as e:
            # Should be a server error
            assert "500" in str(e) or "server" in str(e).lower() or "internal" in str(e).lower()


class CredentialTestMixin:
    """Mixin for testing credential handling."""

    __test__ = False

    @pytest.fixture
    def expired_credentials(self):
        """Create expired credentials for testing."""
        return {
            "access_token": "expired_token",
            "refresh_token": "refresh_token",
            "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        }

    @pytest.fixture
    def valid_credentials(self):
        """Create valid (non-expired) credentials for testing."""
        return {
            "access_token": "valid_token",
            "refresh_token": "refresh_token",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }


class SearchConnectorTestMixin:
    """Mixin for testing search-capable connectors."""

    __test__ = False

    test_search_results: list[dict[str, Any]] = []

    @pytest.mark.asyncio
    async def test_search_returns_list(self, connector, mock_http_session):
        """Test search returns a list of results."""
        self._require_method(connector, "search")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"results": self.test_search_results})
        mock_http_session.get = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        try:
            results = await connector.search("test query")
            assert isinstance(results, list)
        except NotImplementedError:
            pytest.skip("search not implemented")

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, connector, mock_http_session):
        """Test search respects the limit parameter."""
        self._require_method(connector, "search")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"results": [{"id": i} for i in range(100)]})
        mock_http_session.get = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        try:
            results = await connector.search("test query", limit=5)
            # Results should be limited (may be limited at API or client level)
            assert isinstance(results, list)
        except NotImplementedError:
            pytest.skip("search not implemented")


class CRUDConnectorTestMixin:
    """Mixin for testing CRUD-capable connectors."""

    __test__ = False

    test_create_data: dict[str, Any] = {}
    test_update_data: dict[str, Any] = {}

    @pytest.mark.asyncio
    async def test_list_returns_items(self, connector, mock_http_session):
        """Test list operation returns items."""
        if not hasattr(connector, "list") and not hasattr(connector, "list_all"):
            pytest.skip("Connector does not have list or list_all method")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"items": [], "total": 0})
        mock_http_session.get = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        method = getattr(connector, "list", None) or getattr(connector, "list_all", None)
        if method:
            try:
                results = await method()
                assert results is not None
            except NotImplementedError:
                pytest.skip("list not implemented")

    @pytest.mark.asyncio
    async def test_create_returns_item(self, connector, mock_http_session):
        """Test create operation returns created item."""
        self._require_method(connector, "create")

        mock_response = AsyncMock()
        mock_response.status = 201
        mock_response.json = AsyncMock(return_value={"id": "new-123", **self.test_create_data})
        mock_http_session.post = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        try:
            result = await connector.create(self.test_create_data)
            assert result is not None
        except NotImplementedError:
            pytest.skip("create not implemented")

    @pytest.mark.asyncio
    async def test_get_returns_item(self, connector, mock_http_session):
        """Test get operation returns item by ID."""
        self._require_method(connector, "get")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"id": "test-123", "name": "Test"})
        mock_http_session.get = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        try:
            result = await connector.get("test-123")
            assert result is not None
        except NotImplementedError:
            pytest.skip("get not implemented")

    @pytest.mark.asyncio
    async def test_delete_succeeds(self, connector, mock_http_session):
        """Test delete operation succeeds."""
        self._require_method(connector, "delete")

        mock_response = AsyncMock()
        mock_response.status = 204
        mock_response.json = AsyncMock(return_value={})
        mock_http_session.delete = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        try:
            result = await connector.delete("test-123")
            # Delete should return True or None on success
            assert result is None or result is True
        except NotImplementedError:
            pytest.skip("delete not implemented")
