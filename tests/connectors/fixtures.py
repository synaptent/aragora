"""
Shared fixtures for connector tests.

Provides:
- Mock HTTP sessions and responses
- OAuth credential factories
- Rate limit simulation
- Retry behavior testing

Usage:
    # In conftest.py
    from tests.connectors.fixtures import *

    # Or import specific fixtures
    from tests.connectors.fixtures import mock_aiohttp_session
"""

from __future__ import annotations

import asyncio
import pytest
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# HTTP Response Factories
# =============================================================================


@dataclass
class MockResponse:
    """Factory for creating mock HTTP responses."""

    status: int = 200
    data: dict[str, Any] | list[Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    reason: str = "OK"

    async def json(self):
        return self.data

    async def text(self):
        import json

        return json.dumps(self.data) if self.data else ""

    @property
    def content_type(self):
        return self.headers.get("Content-Type", "application/json")


def create_success_response(data: dict[str, Any] | list[Any]) -> MockResponse:
    """Create a successful (200) response."""
    return MockResponse(status=200, data=data)


def create_error_response(status: int, error: str, message: str = "") -> MockResponse:
    """Create an error response."""
    return MockResponse(
        status=status,
        data={"error": error, "message": message},
        reason=error,
    )


def create_rate_limit_response(retry_after: int = 60) -> MockResponse:
    """Create a rate limit (429) response."""
    return MockResponse(
        status=429,
        data={"error": "rate_limit_exceeded", "message": "Too many requests"},
        headers={"Retry-After": str(retry_after)},
        reason="Too Many Requests",
    )


def create_auth_error_response() -> MockResponse:
    """Create an authentication error (401) response."""
    return MockResponse(
        status=401,
        data={"error": "unauthorized", "message": "Invalid or expired token"},
        reason="Unauthorized",
    )


def create_server_error_response() -> MockResponse:
    """Create a server error (500) response."""
    return MockResponse(
        status=500,
        data={"error": "internal_server_error", "message": "Something went wrong"},
        reason="Internal Server Error",
    )


# =============================================================================
# OAuth Fixtures
# =============================================================================


@dataclass
class OAuthTokenSet:
    """Standard OAuth token set for testing."""

    access_token: str = "test_access_token"
    refresh_token: str = "test_refresh_token"
    token_type: str = "Bearer"
    expires_in: int = 3600
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=1)
    )
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

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at


@pytest.fixture
def valid_oauth_tokens():
    """Create valid (non-expired) OAuth tokens."""
    return OAuthTokenSet()


@pytest.fixture
def expired_oauth_tokens():
    """Create expired OAuth tokens."""
    return OAuthTokenSet(
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        expires_in=-3600,
    )


@pytest.fixture
def oauth_token_response():
    """Create a mock OAuth token exchange response."""
    tokens = OAuthTokenSet()
    return create_success_response(tokens.to_dict())


# =============================================================================
# HTTP Session Fixtures
# =============================================================================


class MockHTTPSession:
    """Mock aiohttp session with configurable responses."""

    def __init__(self):
        self.get_responses: list[MockResponse] = []
        self.post_responses: list[MockResponse] = []
        self.put_responses: list[MockResponse] = []
        self.delete_responses: list[MockResponse] = []
        self.patch_responses: list[MockResponse] = []

        self.get_calls: list[tuple[str, dict]] = []
        self.post_calls: list[tuple[str, dict]] = []
        self.put_calls: list[tuple[str, dict]] = []
        self.delete_calls: list[tuple[str, dict]] = []
        self.patch_calls: list[tuple[str, dict]] = []

        self._get_index = 0
        self._post_index = 0
        self._put_index = 0
        self._delete_index = 0
        self._patch_index = 0

    def queue_get_response(self, response: MockResponse):
        """Queue a response for the next GET request."""
        self.get_responses.append(response)

    def queue_post_response(self, response: MockResponse):
        """Queue a response for the next POST request."""
        self.post_responses.append(response)

    def queue_put_response(self, response: MockResponse):
        """Queue a response for the next PUT request."""
        self.put_responses.append(response)

    def queue_delete_response(self, response: MockResponse):
        """Queue a response for the next DELETE request."""
        self.delete_responses.append(response)

    def queue_patch_response(self, response: MockResponse):
        """Queue a response for the next PATCH request."""
        self.patch_responses.append(response)

    def _create_response_context(
        self, responses: list, index_attr: str, calls: list, url: str, **kwargs
    ):
        """Create a context manager that returns the next queued response."""
        calls.append((url, kwargs))
        index = getattr(self, index_attr)

        if index < len(responses):
            response = responses[index]
            setattr(self, index_attr, index + 1)
        else:
            # Default response if no more queued
            response = create_success_response({})

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=response)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    def get(self, url: str, **kwargs):
        return self._create_response_context(
            self.get_responses, "_get_index", self.get_calls, url, **kwargs
        )

    def post(self, url: str, **kwargs):
        return self._create_response_context(
            self.post_responses, "_post_index", self.post_calls, url, **kwargs
        )

    def put(self, url: str, **kwargs):
        return self._create_response_context(
            self.put_responses, "_put_index", self.put_calls, url, **kwargs
        )

    def delete(self, url: str, **kwargs):
        return self._create_response_context(
            self.delete_responses, "_delete_index", self.delete_calls, url, **kwargs
        )

    def patch(self, url: str, **kwargs):
        return self._create_response_context(
            self.patch_responses, "_patch_index", self.patch_calls, url, **kwargs
        )


@pytest.fixture
def mock_http_session():
    """Create a mock HTTP session with queued responses."""
    return MockHTTPSession()


@pytest.fixture
def mock_aiohttp_session(mock_http_session):
    """Patch aiohttp.ClientSession to use mock session."""
    with patch("aiohttp.ClientSession") as mock:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_http_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock.return_value = ctx
        yield mock_http_session


@pytest.fixture
def mock_httpx_client(mock_http_session):
    """Patch httpx.AsyncClient to use mock session."""
    with patch("httpx.AsyncClient") as mock:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_http_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock.return_value = ctx
        yield mock_http_session


# =============================================================================
# Rate Limit Testing
# =============================================================================


@pytest.fixture
def rate_limit_sequence():
    """Create a sequence of responses simulating rate limit then success.

    Returns 429 twice, then success.
    """
    return [
        create_rate_limit_response(retry_after=1),
        create_rate_limit_response(retry_after=1),
        create_success_response({"data": "success"}),
    ]


@pytest.fixture
def retry_sequence():
    """Create a sequence of responses for testing retry behavior.

    Returns 500 twice, then success.
    """
    return [
        create_server_error_response(),
        create_server_error_response(),
        create_success_response({"data": "success"}),
    ]


# =============================================================================
# Credential Fixtures
# =============================================================================


@pytest.fixture
def test_api_key():
    """Generate a test API key."""
    return "test_api_key_" + "x" * 32


@pytest.fixture
def test_client_credentials():
    """Generate test OAuth client credentials."""
    return {
        "client_id": "test_client_id_12345",
        "client_secret": "test_client_secret_67890",
        "redirect_uri": "http://localhost:8080/callback",
    }


@pytest.fixture
def test_bearer_token():
    """Generate a test Bearer token."""
    return "Bearer test_access_token_abcdef123456"


# =============================================================================
# Connector-Specific Fixtures
# =============================================================================


@pytest.fixture
def quickbooks_credentials(test_client_credentials):
    """QuickBooks-specific credentials."""
    return {
        **test_client_credentials,
        "realm_id": "123456789",
        "environment": "sandbox",
    }


@pytest.fixture
def stripe_credentials():
    """Stripe-specific credentials."""
    return {
        "api_key": "sk_test_" + "x" * 24,
        "webhook_secret": "whsec_" + "x" * 32,
    }


@pytest.fixture
def salesforce_credentials(test_client_credentials):
    """Salesforce-specific credentials."""
    return {
        **test_client_credentials,
        "instance_url": "https://test.salesforce.com",
    }


@pytest.fixture
def github_credentials():
    """GitHub-specific credentials."""
    return {
        "token": "ghp_" + "x" * 36,
        "app_id": "12345",
        "installation_id": "67890",
    }


# =============================================================================
# Database Connector Fixtures
# =============================================================================


@pytest.fixture
def postgres_credentials():
    """PostgreSQL connection credentials."""
    return {
        "host": "localhost",
        "port": 5432,
        "database": "test_db",
        "user": "test_user",
        "password": "test_password",
    }


@pytest.fixture
def mysql_credentials():
    """MySQL connection credentials."""
    return {
        "host": "localhost",
        "port": 3306,
        "database": "test_db",
        "user": "test_user",
        "password": "test_password",
    }


@pytest.fixture
def mongodb_credentials():
    """MongoDB connection credentials."""
    return {
        "connection_string": "mongodb://localhost:27017/test_db",
        "database": "test_db",
    }


# =============================================================================
# Utilities
# =============================================================================


def assert_request_made(
    session: MockHTTPSession,
    method: str,
    url_contains: str | None = None,
    data_contains: dict | None = None,
):
    """Assert that a specific request was made."""
    calls = getattr(session, f"{method.lower()}_calls")
    assert len(calls) > 0, f"No {method.upper()} requests were made"

    if url_contains:
        found = any(url_contains in call[0] for call in calls)
        assert found, f"No {method.upper()} request to URL containing '{url_contains}'"

    if data_contains:
        for _, kwargs in calls:
            if "json" in kwargs or "data" in kwargs:
                request_data = kwargs.get("json") or kwargs.get("data", {})
                for key, value in data_contains.items():
                    if key in request_data and request_data[key] == value:
                        return
        assert False, f"No {method.upper()} request with data containing {data_contains}"
