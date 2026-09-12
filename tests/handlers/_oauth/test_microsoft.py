"""Tests for aragora/server/handlers/_oauth/microsoft.py.

Covers the MicrosoftOAuthMixin:
- _handle_microsoft_auth_start: redirect to Microsoft consent screen, client ID checks,
  redirect URL validation, state generation, tenant configuration
- _handle_microsoft_callback: error from Microsoft, state validation, code exchange,
  user info retrieval, complete OAuth flow, error paths
- _exchange_microsoft_code: sync (urllib) and async (httpx) code exchange
- _get_microsoft_user_info: sync (urllib) and async (httpx) user info fetch,
  email fallback to userPrincipalName, missing email, missing id, displayName fallback
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers._oauth.microsoft import MicrosoftOAuthMixin
from aragora.server.handlers.base import HandlerResult
from aragora.server.handlers.oauth.models import OAuthUserInfo
from aragora.server.middleware.rate_limit.oauth_limiter import (
    reset_backoff_tracker,
    reset_oauth_limiter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: object) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    raw = result.body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw}


def _status(result: object) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# ---------------------------------------------------------------------------
# Fake user / token / auth context helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeUser:
    """Minimal user object returned by user stores."""

    id: str = "user-123"
    email: str = "user@example.com"
    org_id: str | None = "org-1"
    role: str = "member"


@dataclass
class FakeTokenPair:
    """Minimal TokenPair returned by create_token_pair."""

    access_token: str = "access-jwt"
    refresh_token: str = "refresh-jwt"
    expires_in: int = 3600


@dataclass
class FakeAuthCtx:
    """Minimal auth context for extract_user_from_request."""

    is_authenticated: bool = False
    user_id: str | None = None


# ---------------------------------------------------------------------------
# Concrete test class mixing in MicrosoftOAuthMixin
# ---------------------------------------------------------------------------


OAUTH_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


class ConcreteMicrosoftHandler(MicrosoftOAuthMixin):
    """Concrete class combining the mixin with stubs for parent methods."""

    OAUTH_NO_CACHE_HEADERS = OAUTH_NO_CACHE_HEADERS

    def __init__(self) -> None:
        self._user_store = MagicMock()
        self._error_messages: list[str] = []
        self._complete_flow_calls: list[tuple] = []

    def _get_user_store(self) -> Any:
        return self._user_store

    def _redirect_with_error(self, error: str) -> HandlerResult:
        self._error_messages.append(error)
        return HandlerResult(
            status_code=302,
            content_type="text/html",
            body=json.dumps({"error": error}).encode(),
            headers={"Location": f"http://localhost:3000/auth/error?error={error}"},
        )

    def _complete_oauth_flow(
        self, user_info: OAuthUserInfo, state_data: dict[str, Any]
    ) -> HandlerResult:
        self._complete_flow_calls.append((user_info, state_data))
        return HandlerResult(
            status_code=302,
            content_type="text/html",
            body=b"oauth-flow-complete",
            headers={"Location": "http://localhost:3000/auth/success"},
        )


# ---------------------------------------------------------------------------
# Mock _oauth_impl module
# ---------------------------------------------------------------------------


_IMPL_MODULE = "aragora.server.handlers.oauth._oauth_impl"


def _make_impl(**overrides: Any) -> ModuleType:
    """Build a fake _oauth_impl module with sensible defaults."""
    mod = ModuleType(_IMPL_MODULE)
    # Config getters
    mod._get_microsoft_client_id = lambda: "ms-client-id"
    mod._get_microsoft_client_secret = lambda: "ms-client-secret"
    mod._get_microsoft_redirect_uri = lambda: "http://localhost:8080/callback"
    mod._get_microsoft_tenant = lambda: "common"
    mod._get_oauth_success_url = lambda: "http://localhost:3000/auth/success"
    mod._get_oauth_error_url = lambda: "http://localhost:3000/auth/error"
    mod._validate_redirect_url = lambda url: True
    mod._generate_state = lambda user_id=None, redirect_url=None: "mock-state-token"
    mod._validate_state = lambda state: {"redirect_url": "http://localhost:3000/auth/success"}
    # Constants
    mod.MICROSOFT_AUTH_URL_TEMPLATE = (
        "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
    )
    mod.MICROSOFT_TOKEN_URL_TEMPLATE = (
        "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    )
    mod.MICROSOFT_USERINFO_URL = "https://graph.microsoft.com/v1.0/me"
    # Tracing stubs
    mod.create_span = MagicMock()
    mod.add_span_attributes = MagicMock()
    # Rate limiter stub
    limiter = MagicMock()
    limiter.is_allowed = MagicMock(return_value=True)
    mod._oauth_limiter = limiter

    for k, v in overrides.items():
        setattr(mod, k, v)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset global rate limiter singletons between tests."""
    reset_oauth_limiter()
    reset_backoff_tracker()
    yield
    reset_oauth_limiter()
    reset_backoff_tracker()


@pytest.fixture()
def impl():
    """Install a fake _oauth_impl in sys.modules for the duration of the test."""
    mod = _make_impl()
    old = sys.modules.get(_IMPL_MODULE)
    sys.modules[_IMPL_MODULE] = mod
    yield mod
    if old is not None:
        sys.modules[_IMPL_MODULE] = old
    else:
        sys.modules.pop(_IMPL_MODULE, None)


@pytest.fixture()
def handler():
    """Create a ConcreteMicrosoftHandler."""
    return ConcreteMicrosoftHandler()


@pytest.fixture()
def mock_http_handler():
    """Create a mock HTTP handler."""
    mock = MagicMock()
    mock.command = "GET"
    mock.client_address = ("127.0.0.1", 12345)
    mock.headers = {"X-Forwarded-For": "192.168.1.1"}
    return mock


@pytest.fixture()
def sample_user_info():
    return OAuthUserInfo(
        provider="microsoft",
        provider_user_id="ms-12345",
        email="alice@example.com",
        name="Alice",
        picture=None,
        email_verified=True,
    )


# ===========================================================================
# _handle_microsoft_auth_start
# ===========================================================================


class TestMicrosoftAuthStart:
    """Tests for _handle_microsoft_auth_start."""

    def test_returns_302_redirect_to_microsoft(self, handler, impl, mock_http_handler):
        """Successful auth start returns 302 with Microsoft URL."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
        assert _status(result) == 302
        loc = result.headers["Location"]
        assert "login.microsoftonline.com/common/oauth2/v2.0/authorize" in loc

    def test_includes_client_id_in_url(self, handler, impl, mock_http_handler):
        """Authorization URL contains the configured client ID."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
        assert "client_id=ms-client-id" in result.headers["Location"]

    def test_includes_response_type_code(self, handler, impl, mock_http_handler):
        """Authorization URL includes response_type=code."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
        assert "response_type=code" in result.headers["Location"]

    def test_includes_scope(self, handler, impl, mock_http_handler):
        """Authorization URL includes openid email profile User.Read scopes."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
        location = result.headers["Location"]
        assert "openid" in location
        assert "User.Read" in location

    def test_includes_state_parameter(self, handler, impl, mock_http_handler):
        """Authorization URL includes CSRF state parameter."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
        assert "state=mock-state-token" in result.headers["Location"]

    def test_includes_response_mode_query(self, handler, impl, mock_http_handler):
        """Authorization URL includes response_mode=query."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
        assert "response_mode=query" in result.headers["Location"]

    def test_not_configured_returns_503(self, handler, mock_http_handler):
        """Returns 503 when Microsoft client ID is not configured."""
        mod = _make_impl(**{"_get_microsoft_client_id": lambda: None})
        old = sys.modules.get(_IMPL_MODULE)
        sys.modules[_IMPL_MODULE] = mod
        try:
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
            assert _status(result) == 503
            body = _body(result)
            assert "not configured" in body.get("error", body.get("raw", "")).lower()
        finally:
            if old is not None:
                sys.modules[_IMPL_MODULE] = old
            else:
                sys.modules.pop(_IMPL_MODULE, None)

    def test_empty_client_id_returns_503(self, handler, mock_http_handler):
        """Returns 503 when Microsoft client ID is empty string."""
        mod = _make_impl(**{"_get_microsoft_client_id": lambda: ""})
        old = sys.modules.get(_IMPL_MODULE)
        sys.modules[_IMPL_MODULE] = mod
        try:
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
            assert _status(result) == 503
        finally:
            if old is not None:
                sys.modules[_IMPL_MODULE] = old
            else:
                sys.modules.pop(_IMPL_MODULE, None)

    def test_invalid_redirect_url_returns_400(self, handler, mock_http_handler):
        """Returns 400 when the redirect_url query param is not in allowlist."""
        mod = _make_impl(**{"_validate_redirect_url": lambda url: False})
        old = sys.modules.get(_IMPL_MODULE)
        sys.modules[_IMPL_MODULE] = mod
        try:
            with patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=FakeAuthCtx(is_authenticated=False),
            ):
                result = handler._handle_microsoft_auth_start(
                    mock_http_handler, {"redirect_url": "https://evil.com/steal"}
                )
            assert _status(result) == 400
            body = _body(result)
            assert "redirect" in body.get("error", body.get("raw", "")).lower()
        finally:
            if old is not None:
                sys.modules[_IMPL_MODULE] = old
            else:
                sys.modules.pop(_IMPL_MODULE, None)

    def test_uses_redirect_url_from_query_params(self, handler, impl, mock_http_handler):
        """When query_params has redirect_url, it is passed to _generate_state."""
        calls: list[str | None] = []
        impl._generate_state = lambda user_id=None, redirect_url=None: (
            calls.append(redirect_url) or "state-tok"
        )
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            handler._handle_microsoft_auth_start(
                mock_http_handler, {"redirect_url": "http://localhost/custom"}
            )
        assert calls[-1] == "http://localhost/custom"

    def test_default_redirect_url_when_not_in_params(self, handler, impl, mock_http_handler):
        """Uses OAuth success URL as default redirect when not specified in query."""
        calls: list[str | None] = []
        impl._generate_state = lambda user_id=None, redirect_url=None: (
            calls.append(redirect_url) or "state-tok"
        )
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            handler._handle_microsoft_auth_start(mock_http_handler, {})
        assert calls[-1] == "http://localhost:3000/auth/success"

    def test_authenticated_user_passes_user_id_to_state(self, handler, impl, mock_http_handler):
        """When user is already authenticated, user_id is included in state."""
        calls: list[str | None] = []
        impl._generate_state = lambda user_id=None, redirect_url=None: (
            calls.append(user_id) or "state-tok"
        )
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=True, user_id="existing-user"),
        ):
            handler._handle_microsoft_auth_start(mock_http_handler, {})
        assert calls[-1] == "existing-user"

    def test_unauthenticated_user_passes_none_user_id(self, handler, impl, mock_http_handler):
        """When user is not authenticated, user_id is None in state."""
        calls: list[str | None] = []
        impl._generate_state = lambda user_id=None, redirect_url=None: (
            calls.append(user_id) or "state-tok"
        )
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            handler._handle_microsoft_auth_start(mock_http_handler, {})
        assert calls[-1] is None

    def test_custom_tenant_in_url(self, handler, impl, mock_http_handler):
        """Custom tenant is used in the authorization URL."""
        impl._get_microsoft_tenant = lambda: "my-tenant-id"
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
        loc = result.headers["Location"]
        assert "my-tenant-id" in loc
        assert "login.microsoftonline.com/my-tenant-id/" in loc

    def test_redirect_body_contains_meta_refresh(self, handler, impl, mock_http_handler):
        """Response body contains a meta refresh tag as fallback."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
        assert b"meta http-equiv" in result.body

    def test_redirect_uri_in_url(self, handler, impl, mock_http_handler):
        """Authorization URL includes the configured redirect URI."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_microsoft_auth_start(mock_http_handler, {})
        loc = result.headers["Location"]
        # URL-encoded form of http://localhost:8080/callback
        assert "redirect_uri=" in loc

    def test_query_param_as_list(self, handler, impl, mock_http_handler):
        """Query parameters provided as lists are handled correctly."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_microsoft_auth_start(
                mock_http_handler,
                {"redirect_url": ["https://app.example.com/done"]},
            )
        assert _status(result) == 302


# ===========================================================================
# _handle_microsoft_callback
# ===========================================================================


class TestMicrosoftCallback:
    """Tests for _handle_microsoft_callback."""

    def _run_callback(self, handler, mock_http_handler, query_params):
        """Run the async callback via the event loop, unwrapping decorators."""
        return asyncio.run(
            handler._handle_microsoft_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, query_params
            )
        )

    def test_error_from_microsoft_redirects_with_error(self, handler, impl, mock_http_handler):
        """Microsoft error parameter triggers redirect with error."""
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"error": "access_denied", "error_description": "User denied"},
        )
        assert _status(result) == 302
        assert "User denied" in handler._error_messages[0]

    def test_error_without_description_uses_error_code(self, handler, impl, mock_http_handler):
        """When error_description is missing, error code itself is used."""
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"error": "server_error"},
        )
        assert _status(result) == 302
        assert "server_error" in handler._error_messages[0]

    def test_missing_state_redirects_with_error(self, handler, impl, mock_http_handler):
        """Missing state parameter triggers error redirect."""
        result = self._run_callback(handler, mock_http_handler, {"code": "auth-code"})
        assert _status(result) == 302
        assert "Missing state" in handler._error_messages[0]

    def test_invalid_state_redirects_with_error(self, handler, impl, mock_http_handler):
        """Invalid/expired state triggers error redirect."""
        impl._validate_state = lambda state: None
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "bad-state", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert "Invalid or expired" in handler._error_messages[0]

    def test_missing_code_redirects_with_error(self, handler, impl, mock_http_handler):
        """Missing authorization code triggers error redirect."""
        result = self._run_callback(handler, mock_http_handler, {"state": "valid-state"})
        assert _status(result) == 302
        assert "Missing authorization code" in handler._error_messages[0]

    def test_token_exchange_connection_error_redirects(self, handler, impl, mock_http_handler):
        """ConnectionError during token exchange redirects with error."""
        handler._exchange_microsoft_code = MagicMock(side_effect=ConnectionError("network down"))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    def test_token_exchange_httpx_error_redirects(self, handler, impl, mock_http_handler):
        """httpx.HTTPError during token exchange redirects with error."""
        import httpx

        handler._exchange_microsoft_code = MagicMock(side_effect=httpx.HTTPError("bad gateway"))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    def test_token_exchange_timeout_error_redirects(self, handler, impl, mock_http_handler):
        """TimeoutError during token exchange redirects with error."""
        handler._exchange_microsoft_code = MagicMock(side_effect=TimeoutError("request timed out"))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    def test_token_exchange_os_error_redirects(self, handler, impl, mock_http_handler):
        """OSError during token exchange redirects with error."""
        handler._exchange_microsoft_code = MagicMock(side_effect=OSError("network unreachable"))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    def test_token_exchange_value_error_redirects(self, handler, impl, mock_http_handler):
        """ValueError during token exchange redirects with error."""
        handler._exchange_microsoft_code = MagicMock(side_effect=ValueError("bad response"))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    def test_token_exchange_json_decode_error_redirects(self, handler, impl, mock_http_handler):
        """json.JSONDecodeError during token exchange redirects with error."""
        handler._exchange_microsoft_code = MagicMock(side_effect=json.JSONDecodeError("bad", "", 0))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    def test_no_access_token_redirects(self, handler, impl, mock_http_handler):
        """Token response without access_token triggers error redirect."""
        handler._exchange_microsoft_code = MagicMock(return_value={"token_type": "Bearer"})
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "c"},
        )
        assert _status(result) == 302
        assert "No access token" in handler._error_messages[0]

    def test_user_info_failure_redirects(self, handler, impl, mock_http_handler):
        """Failed user info retrieval redirects with error."""
        handler._exchange_microsoft_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_microsoft_user_info = MagicMock(
            side_effect=ConnectionError("cannot reach Microsoft Graph")
        )
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "c"},
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    def test_user_info_httpx_error_redirects(self, handler, impl, mock_http_handler):
        """httpx.HTTPError during user info retrieval redirects with error."""
        import httpx

        handler._exchange_microsoft_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_microsoft_user_info = MagicMock(side_effect=httpx.HTTPError("graph api error"))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "c"},
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    def test_user_info_timeout_error_redirects(self, handler, impl, mock_http_handler):
        """TimeoutError during user info retrieval redirects with error."""
        handler._exchange_microsoft_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_microsoft_user_info = MagicMock(side_effect=TimeoutError("timeout"))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "c"},
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    def test_user_info_value_error_redirects(self, handler, impl, mock_http_handler):
        """ValueError during user info retrieval redirects with error."""
        handler._exchange_microsoft_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_microsoft_user_info = MagicMock(side_effect=ValueError("bad data"))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "c"},
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    def test_user_info_key_error_redirects(self, handler, impl, mock_http_handler):
        """KeyError during user info retrieval redirects with error."""
        handler._exchange_microsoft_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_microsoft_user_info = MagicMock(side_effect=KeyError("id"))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "c"},
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    def test_user_info_json_decode_error_redirects(self, handler, impl, mock_http_handler):
        """json.JSONDecodeError during user info retrieval redirects with error."""
        handler._exchange_microsoft_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_microsoft_user_info = MagicMock(side_effect=json.JSONDecodeError("bad", "", 0))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "c"},
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    def test_successful_flow_calls_complete_oauth(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """Successful callback invokes _complete_oauth_flow."""
        handler._exchange_microsoft_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_microsoft_user_info = MagicMock(return_value=sample_user_info)
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "valid", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert len(handler._complete_flow_calls) == 1
        user_info, state_data = handler._complete_flow_calls[0]
        assert user_info.provider == "microsoft"
        assert user_info.email == "alice@example.com"
        assert state_data["redirect_url"] == "http://localhost:3000/auth/success"

    def test_awaitable_token_exchange_result(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """When _exchange_microsoft_code returns a coroutine, it is awaited."""

        async def async_exchange(code):
            return {"access_token": "async-tok"}

        handler._exchange_microsoft_code = lambda code: async_exchange(code)
        handler._get_microsoft_user_info = MagicMock(return_value=sample_user_info)
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "valid", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert len(handler._complete_flow_calls) == 1

    def test_awaitable_user_info_result(self, handler, impl, mock_http_handler, sample_user_info):
        """When _get_microsoft_user_info returns a coroutine, it is awaited."""
        handler._exchange_microsoft_code = MagicMock(return_value={"access_token": "tok"})

        async def async_user_info(token):
            return sample_user_info

        handler._get_microsoft_user_info = lambda token: async_user_info(token)
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "valid", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert len(handler._complete_flow_calls) == 1

    def test_state_data_passed_to_complete_flow(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """state_data from _validate_state is passed to _complete_oauth_flow."""
        impl._validate_state = lambda state: {
            "redirect_url": "https://custom.example.com/done",
            "user_id": "linking-user",
        }
        handler._exchange_microsoft_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_microsoft_user_info = MagicMock(return_value=sample_user_info)
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "valid", "code": "auth-code"},
        )
        assert _status(result) == 302
        _, state_data = handler._complete_flow_calls[0]
        assert state_data["redirect_url"] == "https://custom.example.com/done"
        assert state_data["user_id"] == "linking-user"

    def test_empty_token_response_no_access_token(self, handler, impl, mock_http_handler):
        """Empty token response (empty dict) triggers no access token error."""
        handler._exchange_microsoft_code = MagicMock(return_value={})
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "c"},
        )
        assert _status(result) == 302
        assert "No access token" in handler._error_messages[0]

    def test_user_info_os_error_redirects(self, handler, impl, mock_http_handler):
        """OSError during user info retrieval redirects with error."""
        handler._exchange_microsoft_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_microsoft_user_info = MagicMock(side_effect=OSError("network error"))
        result = self._run_callback(
            handler,
            mock_http_handler,
            {"state": "s", "code": "c"},
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]


# ===========================================================================
# _exchange_microsoft_code (sync path)
# ===========================================================================


class TestExchangeMicrosoftCodeSync:
    """Tests for _exchange_microsoft_code when no event loop is running."""

    @pytest.fixture(autouse=True)
    def _force_sync(self):
        """Force sync path by hiding the running event loop."""
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            yield

    def _make_urlopen_response(self, body: bytes) -> MagicMock:
        """Create a context manager mock that returns body bytes."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_sync_exchange_returns_parsed_json(self, handler, impl):
        """Sync path uses urllib and returns parsed JSON."""
        response_body = json.dumps({"access_token": "ms-tok-123"}).encode("utf-8")
        resp = self._make_urlopen_response(response_body)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ):
            result = handler._exchange_microsoft_code("test-code")
        assert result["access_token"] == "ms-tok-123"

    def test_sync_exchange_empty_body_returns_empty_dict(self, handler, impl):
        """Empty response body returns empty dict."""
        resp = self._make_urlopen_response(b"")

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ):
            result = handler._exchange_microsoft_code("test-code")
        assert result == {}

    def test_sync_exchange_uses_correct_url(self, handler, impl):
        """Sync path posts to the correct Microsoft token URL."""
        response_body = json.dumps({"access_token": "tok"}).encode("utf-8")
        resp = self._make_urlopen_response(response_body)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ) as mock_urlopen:
            result = handler._exchange_microsoft_code("test-code")
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    def test_sync_exchange_sends_form_encoded_data(self, handler, impl):
        """Sync path sends correct form-encoded data."""
        response_body = json.dumps({"access_token": "tok"}).encode("utf-8")
        resp = self._make_urlopen_response(response_body)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ) as mock_urlopen:
            result = handler._exchange_microsoft_code("my-auth-code")
        req = mock_urlopen.call_args[0][0]
        data_str = req.data.decode("utf-8")
        assert "code=my-auth-code" in data_str
        assert "client_id=ms-client-id" in data_str
        assert "client_secret=ms-client-secret" in data_str
        assert "grant_type=authorization_code" in data_str

    def test_sync_exchange_sends_content_type_header(self, handler, impl):
        """Sync path sets Content-Type: application/x-www-form-urlencoded."""
        response_body = json.dumps({"access_token": "tok"}).encode("utf-8")
        resp = self._make_urlopen_response(response_body)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ) as mock_urlopen:
            result = handler._exchange_microsoft_code("test-code")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Content-type") == "application/x-www-form-urlencoded"

    def test_sync_exchange_custom_tenant(self, handler, impl):
        """Sync path uses custom tenant in token URL."""
        impl._get_microsoft_tenant = lambda: "my-org-tenant"
        response_body = json.dumps({"access_token": "tok"}).encode("utf-8")
        resp = self._make_urlopen_response(response_body)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ) as mock_urlopen:
            result = handler._exchange_microsoft_code("test-code")
        req = mock_urlopen.call_args[0][0]
        assert "my-org-tenant" in req.full_url


# ===========================================================================
# _exchange_microsoft_code (async path)
# ===========================================================================


class TestExchangeMicrosoftCodeAsync:
    """Tests for _exchange_microsoft_code when an event loop IS running."""

    @pytest.mark.asyncio
    async def test_async_exchange_returns_coroutine(self, handler, impl):
        """When event loop exists, returns a coroutine that posts via httpx."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "ms-async-tok"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._exchange_microsoft_code("test-code")
            import inspect

            if inspect.isawaitable(result):
                result = await result
        assert result == {"access_token": "ms-async-tok"}

    @pytest.mark.asyncio
    async def test_async_exchange_sends_correct_data(self, handler, impl):
        """Async path sends correct form data via httpx."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._exchange_microsoft_code("test-code")
            import inspect

            if inspect.isawaitable(result):
                await result

        # Verify the POST call
        call_kwargs = mock_client.post.call_args
        assert "login.microsoftonline.com/common/oauth2/v2.0/token" in call_kwargs.args[0]
        data = call_kwargs.kwargs["data"]
        assert data["code"] == "test-code"
        assert data["client_id"] == "ms-client-id"
        assert data["grant_type"] == "authorization_code"

    @pytest.mark.asyncio
    async def test_async_exchange_uses_10s_timeout(self, handler, impl):
        """Async path creates AsyncClient with 10s timeout."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ) as mock_constructor:
            result = handler._exchange_microsoft_code("test-code")
            import inspect

            if inspect.isawaitable(result):
                await result
        mock_constructor.assert_called_once_with(timeout=10.0)


# ===========================================================================
# _get_microsoft_user_info (sync path)
# ===========================================================================


class TestGetMicrosoftUserInfoSync:
    """Tests for _get_microsoft_user_info sync path."""

    @pytest.fixture(autouse=True)
    def _force_sync(self):
        """Force sync path by hiding the running event loop."""
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            yield

    def _make_urlopen_response(self, body: dict) -> MagicMock:
        """Create a context manager mock that returns JSON body bytes."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(body).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_returns_user_info_with_mail(self, handler, impl):
        """Sync path returns OAuthUserInfo when 'mail' field is present."""
        user_data = {
            "id": "ms-user-42",
            "mail": "bob@example.com",
            "displayName": "Bob Smith",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ):
            result = handler._get_microsoft_user_info("access-token")
            assert not asyncio.iscoroutine(result), "Expected sync path"

        assert isinstance(result, OAuthUserInfo)
        assert result.provider == "microsoft"
        assert result.provider_user_id == "ms-user-42"
        assert result.email == "bob@example.com"
        assert result.name == "Bob Smith"
        assert result.picture is None
        assert result.email_verified is True

    def test_falls_back_to_user_principal_name(self, handler, impl):
        """When 'mail' is None, falls back to userPrincipalName."""
        user_data = {
            "id": "ms-user-43",
            "mail": None,
            "userPrincipalName": "charlie@contoso.com",
            "displayName": "Charlie",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ):
            result = handler._get_microsoft_user_info("access-token")
            assert not asyncio.iscoroutine(result), "Expected sync path"

        assert result.email == "charlie@contoso.com"

    def test_name_falls_back_to_email_prefix(self, handler, impl):
        """When displayName is missing, falls back to email prefix."""
        user_data = {
            "id": "ms-user-44",
            "mail": "dana@example.com",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ):
            result = handler._get_microsoft_user_info("access-token")
            assert not asyncio.iscoroutine(result), "Expected sync path"

        assert result.name == "dana"

    def test_missing_email_raises_value_error(self, handler, impl):
        """When no email can be found, ValueError is raised."""
        user_data = {
            "id": "ms-user-45",
            "displayName": "NoEmail",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ):
            with pytest.raises(ValueError, match="(?i)email"):
                handler._get_microsoft_user_info("access-token")

    def test_email_without_at_raises_value_error(self, handler, impl):
        """When email does not contain '@', ValueError is raised."""
        user_data = {
            "id": "ms-user-46",
            "mail": "noemail",
            "displayName": "NoAtSign",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ):
            with pytest.raises(ValueError, match="(?i)email"):
                handler._get_microsoft_user_info("access-token")

    def test_missing_id_raises_value_error(self, handler, impl):
        """When user data has no 'id' field, ValueError is raised."""
        user_data = {
            "mail": "noid@example.com",
            "displayName": "NoId",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ):
            with pytest.raises(ValueError, match="(?i)id"):
                handler._get_microsoft_user_info("access-token")

    def test_sends_bearer_authorization_header(self, handler, impl):
        """Sync path sends Bearer token in Authorization header."""
        user_data = {
            "id": "ms-user-47",
            "mail": "auth@example.com",
            "displayName": "Auth",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ) as mock_urlopen:
            result = handler._get_microsoft_user_info("my-secret-token")
            assert not asyncio.iscoroutine(result), "Expected sync path"
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer my-secret-token"

    def test_uses_correct_userinfo_url(self, handler, impl):
        """Sync path requests from MICROSOFT_USERINFO_URL."""
        user_data = {
            "id": "ms-user-48",
            "mail": "url@example.com",
            "displayName": "URLTest",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ) as mock_urlopen:
            result = handler._get_microsoft_user_info("access-token")
            assert not asyncio.iscoroutine(result), "Expected sync path"
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://graph.microsoft.com/v1.0/me"

    def test_empty_mail_falls_back_to_upn(self, handler, impl):
        """When 'mail' is empty string, falls back to userPrincipalName."""
        user_data = {
            "id": "ms-user-49",
            "mail": "",
            "userPrincipalName": "eve@contoso.com",
            "displayName": "Eve",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ):
            result = handler._get_microsoft_user_info("access-token")
            assert not asyncio.iscoroutine(result), "Expected sync path"

        assert result.email == "eve@contoso.com"

    def test_email_verified_always_true(self, handler, impl):
        """Microsoft validates emails, so email_verified is always True."""
        user_data = {
            "id": "ms-user-50",
            "mail": "verified@example.com",
            "displayName": "Verified",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.microsoft.urlopen",
            return_value=resp,
        ):
            result = handler._get_microsoft_user_info("access-token")
            assert not asyncio.iscoroutine(result), "Expected sync path"

        assert result.email_verified is True


# ===========================================================================
# _get_microsoft_user_info (async path)
# ===========================================================================


class TestGetMicrosoftUserInfoAsync:
    """Tests for _get_microsoft_user_info async path."""

    @pytest.mark.asyncio
    async def test_async_returns_user_info_with_mail(self, handler, impl):
        """Async path returns OAuthUserInfo when 'mail' field is present."""
        user_data = {
            "id": "ms-async-42",
            "mail": "async@example.com",
            "displayName": "AsyncUser",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._get_microsoft_user_info("access-token")
            import inspect

            if inspect.isawaitable(result):
                result = await result

        assert isinstance(result, OAuthUserInfo)
        assert result.provider == "microsoft"
        assert result.provider_user_id == "ms-async-42"
        assert result.email == "async@example.com"
        assert result.name == "AsyncUser"
        assert result.picture is None
        assert result.email_verified is True

    @pytest.mark.asyncio
    async def test_async_falls_back_to_upn(self, handler, impl):
        """Async path falls back to userPrincipalName when mail is None."""
        user_data = {
            "id": "ms-async-43",
            "mail": None,
            "userPrincipalName": "upn@contoso.com",
            "displayName": "UPNUser",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._get_microsoft_user_info("access-token")
            import inspect

            if inspect.isawaitable(result):
                result = await result

        assert result.email == "upn@contoso.com"

    @pytest.mark.asyncio
    async def test_async_name_fallback_to_email_prefix(self, handler, impl):
        """Async path falls back name to email prefix when displayName is missing."""
        user_data = {
            "id": "ms-async-44",
            "mail": "noname@example.com",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._get_microsoft_user_info("access-token")
            import inspect

            if inspect.isawaitable(result):
                result = await result

        assert result.name == "noname"

    @pytest.mark.asyncio
    async def test_async_missing_email_raises(self, handler, impl):
        """Async path raises ValueError when no email found."""
        user_data = {
            "id": "ms-async-45",
            "displayName": "NoEmail",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._get_microsoft_user_info("access-token")
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="email"):
                    await result

    @pytest.mark.asyncio
    async def test_async_email_without_at_raises(self, handler, impl):
        """Async path raises ValueError when email has no '@'."""
        user_data = {
            "id": "ms-async-46",
            "mail": "noemail",
            "displayName": "NoAtSign",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._get_microsoft_user_info("access-token")
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="email"):
                    await result

    @pytest.mark.asyncio
    async def test_async_missing_id_raises(self, handler, impl):
        """Async path raises ValueError when 'id' is missing."""
        user_data = {
            "mail": "noid@example.com",
            "displayName": "NoId",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._get_microsoft_user_info("access-token")
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="id"):
                    await result

    @pytest.mark.asyncio
    async def test_async_uses_correct_url(self, handler, impl):
        """Async path requests from MICROSOFT_USERINFO_URL."""
        user_data = {
            "id": "ms-async-47",
            "mail": "url@example.com",
            "displayName": "URLTest",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._get_microsoft_user_info("access-token")
            import inspect

            if inspect.isawaitable(result):
                await result

        mock_client.get.assert_called_once_with(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": "Bearer access-token"},
        )

    @pytest.mark.asyncio
    async def test_async_sends_bearer_token(self, handler, impl):
        """Async path sends Bearer token in Authorization header."""
        user_data = {
            "id": "ms-async-48",
            "mail": "bearer@example.com",
            "displayName": "Bearer",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._get_microsoft_user_info("my-bearer-token")
            import inspect

            if inspect.isawaitable(result):
                await result

        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer my-bearer-token"

    @pytest.mark.asyncio
    async def test_async_uses_10s_timeout(self, handler, impl):
        """Async path creates AsyncClient with 10s timeout."""
        user_data = {
            "id": "ms-async-49",
            "mail": "timeout@example.com",
            "displayName": "Timeout",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ) as mock_constructor:
            result = handler._get_microsoft_user_info("access-token")
            import inspect

            if inspect.isawaitable(result):
                await result
        mock_constructor.assert_called_once_with(timeout=10.0)

    @pytest.mark.asyncio
    async def test_async_empty_mail_falls_back_to_upn(self, handler, impl):
        """Async path: empty string mail falls back to userPrincipalName."""
        user_data = {
            "id": "ms-async-50",
            "mail": "",
            "userPrincipalName": "fallback@contoso.com",
            "displayName": "Fallback",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._get_microsoft_user_info("access-token")
            import inspect

            if inspect.isawaitable(result):
                result = await result

        assert result.email == "fallback@contoso.com"

    @pytest.mark.asyncio
    async def test_async_email_verified_always_true(self, handler, impl):
        """Async path: email_verified is always True for Microsoft."""
        user_data = {
            "id": "ms-async-51",
            "mail": "verified@example.com",
            "displayName": "Verified",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.microsoft.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = handler._get_microsoft_user_info("access-token")
            import inspect

            if inspect.isawaitable(result):
                result = await result

        assert result.email_verified is True


# ===========================================================================
# Integration-style tests via OAuthHandler.handle()
# ===========================================================================


class TestHandleRouting:
    """Tests that the Microsoft endpoints are routed through OAuthHandler.handle()."""

    @pytest.fixture()
    def oauth_handler(self, impl):
        """Create an OAuthHandler with mock context."""
        from aragora.server.handlers._oauth.base import OAuthHandler

        ctx = {"user_store": MagicMock()}
        h = OAuthHandler(ctx)
        return h

    def test_microsoft_auth_start_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/v1/auth/oauth/microsoft routes to Microsoft auth start."""
        impl._get_microsoft_client_id = lambda: "ms-id"

        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = oauth_handler.handle(
                "/api/v1/auth/oauth/microsoft", {}, mock_http_handler, "GET"
            )
        assert _status(result) == 302

    def test_microsoft_callback_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/v1/auth/oauth/microsoft/callback routes to callback handler."""
        result = oauth_handler.handle(
            "/api/v1/auth/oauth/microsoft/callback",
            {"error": "access_denied", "error_description": "denied"},
            mock_http_handler,
            "GET",
        )
        assert _status(result) == 302

    def test_non_v1_microsoft_auth_start_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/auth/oauth/microsoft also routes correctly (non-v1)."""
        impl._get_microsoft_client_id = lambda: "ms-id"

        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = oauth_handler.handle("/api/auth/oauth/microsoft", {}, mock_http_handler, "GET")
        assert _status(result) == 302

    def test_non_v1_microsoft_callback_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/auth/oauth/microsoft/callback also routes correctly (non-v1)."""
        result = oauth_handler.handle(
            "/api/auth/oauth/microsoft/callback",
            {"error": "server_error"},
            mock_http_handler,
            "GET",
        )
        assert _status(result) == 302

    def test_rate_limited_returns_429(self, oauth_handler, impl, mock_http_handler):
        """When rate limiter denies request, returns 429."""
        impl._oauth_limiter.is_allowed = MagicMock(return_value=False)
        result = oauth_handler.handle("/api/v1/auth/oauth/microsoft", {}, mock_http_handler, "GET")
        assert _status(result) == 429
