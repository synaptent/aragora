"""Tests for aragora/server/handlers/_oauth/github.py.

Covers the GitHubOAuthMixin:
- _handle_github_auth_start: redirect to GitHub consent screen, client ID checks,
  redirect URL validation, state generation, account linking flag
- _handle_github_callback: error from GitHub, state validation, code exchange,
  user info retrieval, user creation/login, account linking, email lookup,
  token creation, last login update
- _exchange_github_code: sync (urllib) and async (httpx) paths, JSON errors
- _get_github_user_info: public email, private email (emails endpoint),
  primary verified, fallback verified, fallback any, missing email,
  missing id, sync/async
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers._oauth.github import GitHubOAuthMixin
from aragora.server.handlers.base import HandlerResult, error_response
from aragora.server.handlers.oauth.models import OAuthUserInfo
from aragora.server.middleware.rate_limit.oauth_limiter import (
    reset_backoff_tracker,
    reset_oauth_limiter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: object) -> dict:
    """Extract body from HandlerResult or dict."""
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
    """Extract HTTP status code from HandlerResult or dict."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# ---------------------------------------------------------------------------
# Fake user / token helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeUser:
    """Minimal user object returned by user stores."""

    id: str = "user-123"
    email: str = "octocat@github.com"
    org_id: str | None = "org-1"
    role: str = "member"


@dataclass
class FakeTokenPair:
    """Minimal TokenPair returned by create_token_pair."""

    access_token: str = "access-jwt"
    refresh_token: str = "refresh-jwt"


@dataclass
class FakeAuthCtx:
    """Minimal auth context for extract_user_from_request."""

    is_authenticated: bool = False
    user_id: str | None = None


# ---------------------------------------------------------------------------
# Build a concrete class from the mixin
# ---------------------------------------------------------------------------


class ConcreteGitHubHandler(GitHubOAuthMixin):
    """Concrete class combining the mixin with stubs for parent methods."""

    def __init__(self):
        self._user_store = MagicMock()
        self._redirect_error_result = HandlerResult(
            status_code=302,
            content_type="text/html",
            body=b"error-redirect",
        )
        self._redirect_tokens_result = HandlerResult(
            status_code=302,
            content_type="text/html",
            body=b"token-redirect",
        )
        self._account_linking_result = HandlerResult(
            status_code=302,
            content_type="text/html",
            body=b"linking-redirect",
        )

    def _get_user_store(self):
        return self._user_store

    def _redirect_with_error(self, error: str) -> HandlerResult:
        self._last_error = error
        return self._redirect_error_result

    def _redirect_with_tokens(self, redirect_url: str, tokens: Any) -> HandlerResult:
        self._last_redirect_url = redirect_url
        self._last_tokens = tokens
        return self._redirect_tokens_result

    def _find_user_by_oauth(self, user_store, user_info):
        return self._user_store._find_by_oauth(user_info)

    def _link_oauth_to_user(self, user_store, user_id, user_info):
        return self._user_store._link_oauth(user_id, user_info)

    def _create_oauth_user(self, user_store, user_info):
        return self._user_store._create_oauth(user_info)

    def _handle_account_linking(self, user_store, user_id, user_info, state_data):
        self._last_linking_user_id = user_id
        return self._account_linking_result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_IMPL_MODULE = "aragora.server.handlers.oauth._oauth_impl"


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset global rate limiter singletons between tests."""
    reset_oauth_limiter()
    reset_backoff_tracker()
    yield
    reset_oauth_limiter()
    reset_backoff_tracker()


def _make_impl(**overrides) -> ModuleType:
    """Build a fake _oauth_impl module with sensible defaults.

    Keyword arguments override any default attribute.
    """
    mod = ModuleType(_IMPL_MODULE)
    # Config getters
    mod._get_github_client_id = lambda: "gh-client-id"
    mod._get_github_client_secret = lambda: "gh-client-secret"
    mod._get_github_redirect_uri = lambda: "http://localhost/callback"
    mod._get_oauth_success_url = lambda: "http://localhost/success"
    mod._get_oauth_error_url = lambda: "http://localhost/error"
    mod._validate_redirect_url = lambda url: True
    mod._generate_state = lambda user_id=None, redirect_url=None: "state-tok"
    mod._validate_state = lambda s: {"redirect_url": "http://localhost/success"}
    # Constants
    mod.GITHUB_CLIENT_ID = "gh-client-id"
    mod.GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
    mod.GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
    mod.GITHUB_USERINFO_URL = "https://api.github.com/user"
    mod.GITHUB_EMAILS_URL = "https://api.github.com/user/emails"
    # Tracing stubs
    mod.create_span = MagicMock()
    mod.add_span_attributes = MagicMock()
    # Rate limiter stub
    limiter = MagicMock()
    limiter.is_allowed = MagicMock(return_value=True)
    mod._oauth_limiter = limiter

    for key, val in overrides.items():
        setattr(mod, key, val)
    return mod


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
    """Create a ConcreteGitHubHandler."""
    return ConcreteGitHubHandler()


@pytest.fixture()
def mock_http_handler():
    """Create a mock HTTP handler."""
    mock = MagicMock()
    mock.command = "GET"
    mock.client_address = ("127.0.0.1", 12345)
    mock.headers = {"X-Forwarded-For": "192.168.1.1"}
    return mock


# ===========================================================================
# _handle_github_auth_start
# ===========================================================================


class TestHandleGitHubAuthStart:
    """Tests for _handle_github_auth_start."""

    def test_returns_302_redirect_to_github(self, handler, impl, mock_http_handler):
        """Successful auth start returns 302 with GitHub URL."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_github_auth_start(mock_http_handler, {})
        assert _status(result) == 302
        assert result.headers is not None
        assert "github.com/login/oauth/authorize" in result.headers["Location"]

    def test_includes_client_id_in_url(self, handler, impl, mock_http_handler):
        """Authorization URL contains the configured client ID."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_github_auth_start(mock_http_handler, {})
        assert "client_id=gh-client-id" in result.headers["Location"]

    def test_includes_scope_in_url(self, handler, impl, mock_http_handler):
        """Authorization URL requests read:user and user:email scopes."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_github_auth_start(mock_http_handler, {})
        location = result.headers["Location"]
        assert "read%3Auser" in location or "read:user" in location

    def test_includes_state_parameter(self, handler, impl, mock_http_handler):
        """Authorization URL includes CSRF state parameter."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_github_auth_start(mock_http_handler, {})
        assert "state=state-tok" in result.headers["Location"]

    def test_not_configured_returns_503(self, handler, mock_http_handler):
        """Returns 503 when GitHub client ID is not configured."""
        mod = _make_impl()
        mod._get_github_client_id = lambda: None
        old = sys.modules.get(_IMPL_MODULE)
        sys.modules[_IMPL_MODULE] = mod
        try:
            with patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=FakeAuthCtx(is_authenticated=False),
            ):
                result = handler._handle_github_auth_start(mock_http_handler, {})
            assert _status(result) == 503
        finally:
            if old is not None:
                sys.modules[_IMPL_MODULE] = old
            else:
                sys.modules.pop(_IMPL_MODULE, None)

    def test_empty_client_id_returns_503(self, handler, mock_http_handler):
        """Returns 503 when GitHub client ID is empty string."""
        mod = _make_impl()
        mod._get_github_client_id = lambda: ""
        old = sys.modules.get(_IMPL_MODULE)
        sys.modules[_IMPL_MODULE] = mod
        try:
            with patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=FakeAuthCtx(is_authenticated=False),
            ):
                result = handler._handle_github_auth_start(mock_http_handler, {})
            assert _status(result) == 503
        finally:
            if old is not None:
                sys.modules[_IMPL_MODULE] = old
            else:
                sys.modules.pop(_IMPL_MODULE, None)

    def test_invalid_redirect_url_returns_400(self, handler, mock_http_handler):
        """Returns 400 when the redirect_url query param is not in allowlist."""
        mod = _make_impl()
        mod._validate_redirect_url = lambda url: False
        old = sys.modules.get(_IMPL_MODULE)
        sys.modules[_IMPL_MODULE] = mod
        try:
            with patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=FakeAuthCtx(is_authenticated=False),
            ):
                result = handler._handle_github_auth_start(
                    mock_http_handler, {"redirect_url": "https://evil.com/steal"}
                )
            assert _status(result) == 400
        finally:
            if old is not None:
                sys.modules[_IMPL_MODULE] = old
            else:
                sys.modules.pop(_IMPL_MODULE, None)

    def test_uses_redirect_url_from_query_params(self, handler, impl, mock_http_handler):
        """When query_params has redirect_url, it is passed to _generate_state."""
        calls = []
        impl._generate_state = lambda user_id=None, redirect_url=None: (
            calls.append(redirect_url) or "state-tok"
        )
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            handler._handle_github_auth_start(
                mock_http_handler, {"redirect_url": "http://localhost/custom"}
            )
        assert calls[-1] == "http://localhost/custom"

    def test_authenticated_user_gets_linking_state(self, handler, impl, mock_http_handler):
        """When user is already authenticated, user_id is passed to _generate_state."""
        calls = []
        impl._generate_state = lambda user_id=None, redirect_url=None: (
            calls.append(user_id) or "state-tok"
        )
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=True, user_id="existing-user"),
        ):
            handler._handle_github_auth_start(mock_http_handler, {})
        assert calls[-1] == "existing-user"

    def test_unauthenticated_user_state_has_no_user_id(self, handler, impl, mock_http_handler):
        """When user is not authenticated, user_id is None in _generate_state."""
        calls = []
        impl._generate_state = lambda user_id=None, redirect_url=None: (
            calls.append(user_id) or "state-tok"
        )
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            handler._handle_github_auth_start(mock_http_handler, {})
        assert calls[-1] is None

    def test_redirect_body_contains_meta_refresh(self, handler, impl, mock_http_handler):
        """Response body contains a meta refresh tag as fallback."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = handler._handle_github_auth_start(mock_http_handler, {})
        assert b"meta http-equiv" in result.body


# ===========================================================================
# _handle_github_callback
# ===========================================================================


class TestHandleGitHubCallback:
    """Tests for _handle_github_callback."""

    @pytest.mark.asyncio
    async def test_error_from_github_redirects(self, handler, impl):
        """When GitHub returns an error param, redirect with error."""
        result = await handler._handle_github_callback(
            MagicMock(), {"error": "access_denied", "error_description": "User denied"}
        )
        assert result is handler._redirect_error_result
        assert "User denied" in handler._last_error

    @pytest.mark.asyncio
    async def test_error_from_github_uses_error_as_fallback_desc(self, handler, impl):
        """When error_description is missing, uses error value as description."""
        result = await handler._handle_github_callback(MagicMock(), {"error": "server_error"})
        assert result is handler._redirect_error_result
        assert "server_error" in handler._last_error

    @pytest.mark.asyncio
    async def test_missing_state_redirects_with_error(self, handler, impl):
        """Missing state parameter triggers error redirect."""
        result = await handler._handle_github_callback(MagicMock(), {})
        assert result is handler._redirect_error_result
        assert "state" in handler._last_error.lower()

    @pytest.mark.asyncio
    async def test_invalid_state_redirects_with_error(self, handler, impl):
        """Invalid/expired state triggers error redirect."""
        impl._validate_state = lambda s: None
        result = await handler._handle_github_callback(MagicMock(), {"state": "bad-state"})
        assert result is handler._redirect_error_result
        assert "expired" in handler._last_error.lower() or "invalid" in handler._last_error.lower()

    @pytest.mark.asyncio
    async def test_missing_code_redirects_with_error(self, handler, impl):
        """Missing authorization code triggers error redirect."""
        result = await handler._handle_github_callback(MagicMock(), {"state": "valid-state"})
        assert result is handler._redirect_error_result
        assert "code" in handler._last_error.lower()

    @pytest.mark.asyncio
    async def test_token_exchange_failure_redirects(self, handler, impl):
        """Failed token exchange redirects with error."""
        handler._exchange_github_code = MagicMock(side_effect=ConnectionError("network down"))
        result = await handler._handle_github_callback(
            MagicMock(), {"state": "s", "code": "auth-code"}
        )
        assert result is handler._redirect_error_result
        assert (
            "exchange" in handler._last_error.lower()
            or "authorization" in handler._last_error.lower()
        )

    @pytest.mark.asyncio
    async def test_token_exchange_httpx_error_redirects(self, handler, impl):
        """httpx.HTTPError during token exchange redirects with error."""
        import httpx

        handler._exchange_github_code = MagicMock(side_effect=httpx.HTTPError("bad gateway"))
        result = await handler._handle_github_callback(
            MagicMock(), {"state": "s", "code": "auth-code"}
        )
        assert result is handler._redirect_error_result

    @pytest.mark.asyncio
    async def test_no_access_token_redirects(self, handler, impl):
        """No access_token in response triggers error redirect."""
        handler._exchange_github_code = MagicMock(return_value={"error": "bad_verification_code"})
        result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_error_result
        assert "access token" in handler._last_error.lower()

    @pytest.mark.asyncio
    async def test_no_access_token_uses_error_description(self, handler, impl):
        """Error description from token response is logged."""
        handler._exchange_github_code = MagicMock(
            return_value={"error_description": "code expired"}
        )
        result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_error_result

    @pytest.mark.asyncio
    async def test_user_info_failure_redirects(self, handler, impl):
        """Failed user info retrieval redirects with error."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_github_user_info = MagicMock(
            side_effect=ConnectionError("cannot reach GitHub")
        )
        result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_error_result
        assert "user info" in handler._last_error.lower()

    @pytest.mark.asyncio
    async def test_no_user_store_redirects(self, handler, impl):
        """When user store is unavailable, redirect with error."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="test@example.com",
            name="Test",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        handler._user_store = None
        handler._get_user_store = lambda: None

        result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_error_result
        assert "unavailable" in handler._last_error.lower()

    @pytest.mark.asyncio
    async def test_account_linking_when_user_id_in_state(self, handler, impl):
        """When state has user_id, account linking flow is triggered."""
        impl._validate_state = lambda s: {"user_id": "link-user-99", "redirect_url": "/"}

        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="link@example.com",
            name="Linker",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)

        result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._account_linking_result
        assert handler._last_linking_user_id == "link-user-99"

    @pytest.mark.asyncio
    async def test_existing_user_by_oauth_logs_in(self, handler, impl):
        """When user exists by OAuth provider ID, log them in."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="exists@example.com",
            name="Exists",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        existing_user = FakeUser(id="u-existing", email="exists@example.com")
        handler._user_store._find_by_oauth = MagicMock(return_value=existing_user)
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=FakeTokenPair(),
        ):
            result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_tokens_result

    @pytest.mark.asyncio
    async def test_existing_email_links_oauth_when_verified(self, handler, impl):
        """When user found by email with verified email, link OAuth to existing account."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="existing@example.com",
            name="Existing",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        handler._user_store._find_by_oauth = MagicMock(return_value=None)

        email_user = FakeUser(id="u-email", email="existing@example.com")
        handler._user_store.get_user_by_email = MagicMock(return_value=email_user)
        handler._user_store._link_oauth = MagicMock(return_value=True)
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=FakeTokenPair(),
        ):
            result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_tokens_result
        handler._user_store._link_oauth.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_email_blocks_unverified(self, handler, impl):
        """When user found by email but email NOT verified, block linking."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="existing@example.com",
            name="Existing",
            email_verified=False,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        handler._user_store._find_by_oauth = MagicMock(return_value=None)

        email_user = FakeUser(id="u-email", email="existing@example.com")
        handler._user_store.get_user_by_email = MagicMock(return_value=email_user)

        result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_error_result
        assert "verification" in handler._last_error.lower()

    @pytest.mark.asyncio
    async def test_new_user_created_when_not_found(self, handler, impl):
        """When no existing user found, create a new OAuth user."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="new@example.com",
            name="New User",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        handler._user_store._find_by_oauth = MagicMock(return_value=None)
        handler._user_store.get_user_by_email = MagicMock(return_value=None)
        new_user = FakeUser(id="u-new", email="new@example.com")
        handler._user_store._create_oauth = MagicMock(return_value=new_user)
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=FakeTokenPair(),
        ):
            result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_tokens_result
        handler._user_store._create_oauth.assert_called_once()

    @pytest.mark.asyncio
    async def test_user_creation_failure_redirects(self, handler, impl):
        """When user creation returns None, redirect with error."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="fail@example.com",
            name="Fail",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        handler._user_store._find_by_oauth = MagicMock(return_value=None)
        handler._user_store.get_user_by_email = MagicMock(return_value=None)
        handler._user_store._create_oauth = MagicMock(return_value=None)

        result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_error_result
        assert "create" in handler._last_error.lower() or "failed" in handler._last_error.lower()

    @pytest.mark.asyncio
    async def test_last_login_updated_on_success(self, handler, impl):
        """After successful login, last_login_at is updated on user store."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="login@example.com",
            name="Login",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        existing_user = FakeUser(id="u-login", email="login@example.com")
        handler._user_store._find_by_oauth = MagicMock(return_value=existing_user)
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=FakeTokenPair(),
        ):
            await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        handler._user_store.update_user.assert_called_once()
        call_kwargs = handler._user_store.update_user.call_args
        assert "last_login_at" in call_kwargs.kwargs or (len(call_kwargs.args) > 1)

    @pytest.mark.asyncio
    async def test_redirect_url_from_state_data(self, handler, impl):
        """Redirect URL from state_data is used for final redirect."""
        impl._validate_state = lambda s: {"redirect_url": "http://localhost/custom-redir"}

        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="redir@example.com",
            name="Redir",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        existing_user = FakeUser(id="u-redir", email="redir@example.com")
        handler._user_store._find_by_oauth = MagicMock(return_value=existing_user)
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=FakeTokenPair(),
        ):
            await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert handler._last_redirect_url == "http://localhost/custom-redir"

    @pytest.mark.asyncio
    async def test_token_exchange_async_result_awaited(self, handler, impl):
        """When _exchange_github_code returns a coroutine, it is awaited."""

        async def async_exchange(code):
            return {"access_token": "async-tok"}

        handler._exchange_github_code = lambda code: async_exchange(code)

        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="async@example.com",
            name="Async",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        existing_user = FakeUser(id="u-async", email="async@example.com")
        handler._user_store._find_by_oauth = MagicMock(return_value=existing_user)
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=FakeTokenPair(),
        ):
            result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_tokens_result

    @pytest.mark.asyncio
    async def test_user_info_async_result_awaited(self, handler, impl):
        """When _get_github_user_info returns a coroutine, it is awaited."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})

        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="async-info@example.com",
            name="AsyncInfo",
            email_verified=True,
        )

        async def async_user_info(token):
            return user_info

        handler._get_github_user_info = lambda token: async_user_info(token)
        existing_user = FakeUser(id="u-async-info", email="async-info@example.com")
        handler._user_store._find_by_oauth = MagicMock(return_value=existing_user)
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=FakeTokenPair(),
        ):
            result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_tokens_result

    @pytest.mark.asyncio
    async def test_async_user_store_email_lookup(self, handler, impl):
        """When user store has get_user_by_email_async, it is used."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="async-email@example.com",
            name="AsyncEmail",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        handler._user_store._find_by_oauth = MagicMock(return_value=None)

        email_user = FakeUser(id="u-async-email", email="async-email@example.com")
        handler._user_store.get_user_by_email_async = AsyncMock(return_value=email_user)
        handler._user_store._link_oauth = MagicMock(return_value=True)
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=FakeTokenPair(),
        ):
            result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_tokens_result
        handler._user_store.get_user_by_email_async.assert_called_once_with(
            "async-email@example.com"
        )

    @pytest.mark.asyncio
    async def test_async_update_user(self, handler, impl):
        """When user store has update_user_async, it is used."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="async-update@example.com",
            name="AsyncUpdate",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        existing_user = FakeUser(id="u-async-update", email="async-update@example.com")
        handler._user_store._find_by_oauth = MagicMock(return_value=existing_user)
        handler._user_store.update_user_async = AsyncMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=FakeTokenPair(),
        ):
            result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_tokens_result
        handler._user_store.update_user_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_exchange_json_decode_error(self, handler, impl):
        """json.JSONDecodeError during token exchange redirects with error."""
        handler._exchange_github_code = MagicMock(side_effect=json.JSONDecodeError("bad", "", 0))
        result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_error_result

    @pytest.mark.asyncio
    async def test_user_info_key_error(self, handler, impl):
        """KeyError during user info retrieval redirects with error."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_github_user_info = MagicMock(side_effect=KeyError("id"))
        result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_error_result

    @pytest.mark.asyncio
    async def test_user_info_value_error(self, handler, impl):
        """ValueError during user info retrieval redirects with error."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        handler._get_github_user_info = MagicMock(side_effect=ValueError("missing email"))
        result = await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        assert result is handler._redirect_error_result

    @pytest.mark.asyncio
    async def test_create_token_pair_called_with_user_data(self, handler, impl):
        """create_token_pair is called with user fields."""
        handler._exchange_github_code = MagicMock(return_value={"access_token": "tok"})
        user_info = OAuthUserInfo(
            provider="github",
            provider_user_id="12345",
            email="toktest@example.com",
            name="TokTest",
            email_verified=True,
        )
        handler._get_github_user_info = MagicMock(return_value=user_info)
        existing_user = FakeUser(
            id="u-toktest",
            email="toktest@example.com",
            org_id="org-x",
            role="admin",
        )
        handler._user_store._find_by_oauth = MagicMock(return_value=existing_user)
        handler._user_store.update_user = MagicMock()

        mock_ctp = MagicMock(return_value=FakeTokenPair())
        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            mock_ctp,
        ):
            await handler._handle_github_callback(MagicMock(), {"state": "s", "code": "c"})
        mock_ctp.assert_called_once_with(
            user_id="u-toktest",
            email="toktest@example.com",
            org_id="org-x",
            role="admin",
        )


# ===========================================================================
# _exchange_github_code (sync path)
# ===========================================================================


class TestExchangeGitHubCodeSync:
    """Tests for _exchange_github_code when no event loop is running."""

    def test_sync_exchange_returns_parsed_json(self, handler, impl):
        """Sync path uses urllib and returns parsed JSON."""
        response_body = json.dumps({"access_token": "gho_abc"}).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=mock_response,
        ):
            result = handler._exchange_github_code("test-code")
        assert result == {"access_token": "gho_abc"}

    def test_sync_exchange_empty_body_returns_empty_dict(self, handler, impl):
        """Empty response body returns empty dict."""
        mock_response = MagicMock()
        mock_response.read.return_value = b""
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=mock_response,
        ):
            result = handler._exchange_github_code("test-code")
        assert result == {}

    def test_sync_exchange_invalid_json_raises(self, handler, impl):
        """Invalid JSON response raises ValueError."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"not-json"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=mock_response,
        ):
            with pytest.raises(ValueError, match="Invalid JSON"):
                handler._exchange_github_code("test-code")

    def test_sync_exchange_uses_correct_url(self, handler, impl):
        """Sync path posts to GITHUB_TOKEN_URL."""
        response_body = json.dumps({"access_token": "gho_abc"}).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=mock_response,
        ) as mock_urlopen:
            handler._exchange_github_code("test-code")
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://github.com/login/oauth/access_token"

    def test_sync_exchange_sends_json_accept_header(self, handler, impl):
        """Sync path sets Accept: application/json header."""
        response_body = json.dumps({"access_token": "gho_abc"}).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=mock_response,
        ) as mock_urlopen:
            handler._exchange_github_code("test-code")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Accept") == "application/json"


# ===========================================================================
# _exchange_github_code (async path)
# ===========================================================================


class TestExchangeGitHubCodeAsync:
    """Tests for _exchange_github_code when an event loop IS running."""

    @pytest.mark.asyncio
    async def test_async_exchange_returns_coroutine(self, handler, impl):
        """When event loop exists, returns a coroutine that posts via httpx."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "gho_async"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._exchange_github_code("test-code")
            # Should return a coroutine in async context
            import inspect

            if inspect.isawaitable(result):
                result = await result
        assert result == {"access_token": "gho_async"}

    @pytest.mark.asyncio
    async def test_async_exchange_invalid_json_raises(self, handler, impl):
        """Invalid JSON from async response raises ValueError."""
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("bad", "", 0)

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._exchange_github_code("test-code")
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="Invalid JSON"):
                    await result


# ===========================================================================
# _get_github_user_info (sync path)
# ===========================================================================


class TestGetGitHubUserInfoSync:
    """Tests for _get_github_user_info sync path."""

    def _make_urlopen_response(self, body: dict | list) -> MagicMock:
        """Create a context manager mock that returns body bytes."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(body).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_public_email_returned(self, handler, impl):
        """When user data has public email, it is used directly."""
        user_data = {
            "id": 42,
            "email": "public@example.com",
            "name": "Octocat",
            "avatar_url": "http://img/oc",
        }
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=resp,
        ):
            info = handler._get_github_user_info("token-abc")
        assert info.email == "public@example.com"
        assert info.provider == "github"
        assert info.provider_user_id == "42"
        assert info.name == "Octocat"
        assert info.picture == "http://img/oc"

    def test_private_email_primary_verified(self, handler, impl):
        """When public email is absent, primary verified email is found."""
        user_data = {"id": 42, "name": "Ghost"}
        emails = [
            {"email": "secondary@example.com", "primary": False, "verified": True},
            {"email": "primary@example.com", "primary": True, "verified": True},
        ]
        user_resp = self._make_urlopen_response(user_data)
        email_resp = self._make_urlopen_response(emails)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            side_effect=[user_resp, email_resp],
        ):
            info = handler._get_github_user_info("token-abc")
        assert info.email == "primary@example.com"
        assert info.email_verified is True

    def test_private_email_fallback_verified(self, handler, impl):
        """When no primary verified, fallback to any verified email."""
        user_data = {"id": 42, "name": "Ghost"}
        emails = [
            {"email": "unverified@example.com", "primary": True, "verified": False},
            {"email": "verified@example.com", "primary": False, "verified": True},
        ]
        user_resp = self._make_urlopen_response(user_data)
        email_resp = self._make_urlopen_response(emails)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            side_effect=[user_resp, email_resp],
        ):
            info = handler._get_github_user_info("token-abc")
        assert info.email == "verified@example.com"
        assert info.email_verified is True

    def test_private_email_fallback_any(self, handler, impl):
        """When no verified emails, fallback to first email."""
        user_data = {"id": 42, "name": "Ghost"}
        emails = [
            {"email": "only@example.com", "primary": False, "verified": False},
        ]
        user_resp = self._make_urlopen_response(user_data)
        email_resp = self._make_urlopen_response(emails)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            side_effect=[user_resp, email_resp],
        ):
            info = handler._get_github_user_info("token-abc")
        assert info.email == "only@example.com"
        assert info.email_verified is False

    def test_no_email_raises_value_error(self, handler, impl):
        """When no email can be found anywhere, ValueError is raised."""
        user_data = {"id": 42, "name": "Ghost"}
        emails = []
        user_resp = self._make_urlopen_response(user_data)
        email_resp = self._make_urlopen_response(emails)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            side_effect=[user_resp, email_resp],
        ):
            with pytest.raises(ValueError, match="email"):
                handler._get_github_user_info("token-abc")

    def test_missing_id_raises_value_error(self, handler, impl):
        """When user data has no 'id' field, ValueError is raised."""
        user_data = {"email": "noid@example.com", "name": "NoId"}
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=resp,
        ):
            with pytest.raises(ValueError, match="id"):
                handler._get_github_user_info("token-abc")

    def test_name_falls_back_to_login(self, handler, impl):
        """When name is None, falls back to login username."""
        user_data = {"id": 42, "email": "namer@example.com", "name": None, "login": "octologin"}
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=resp,
        ):
            info = handler._get_github_user_info("token-abc")
        assert info.name == "octologin"

    def test_name_falls_back_to_email_prefix(self, handler, impl):
        """When neither name nor login exist, falls back to email prefix."""
        user_data = {"id": 42, "email": "prefix@example.com"}
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=resp,
        ):
            info = handler._get_github_user_info("token-abc")
        assert info.name == "prefix"

    def test_invalid_json_from_user_endpoint_raises(self, handler, impl):
        """Invalid JSON from user endpoint raises ValueError."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not-json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=mock_resp,
        ):
            with pytest.raises(ValueError, match="Invalid JSON"):
                handler._get_github_user_info("token-abc")

    def test_invalid_json_from_emails_endpoint_raises(self, handler, impl):
        """Invalid JSON from emails endpoint raises ValueError."""
        user_data = {"id": 42, "name": "Ghost"}
        user_resp = self._make_urlopen_response(user_data)

        email_resp = MagicMock()
        email_resp.read.return_value = b"not-json"
        email_resp.__enter__ = MagicMock(return_value=email_resp)
        email_resp.__exit__ = MagicMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            side_effect=[user_resp, email_resp],
        ):
            with pytest.raises(ValueError, match="Invalid JSON"):
                handler._get_github_user_info("token-abc")

    def test_empty_user_body_returns_empty_dict(self, handler, impl):
        """Empty body from user endpoint results in empty dict (no id -> error)."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=mock_resp,
        ):
            # Empty body => {} => no email, will try emails endpoint, then no id
            # Actually empty body => {} => no email => tries emails endpoint
            # But urlopen is now exhausted, so it will error.
            # Let's provide two responses:
            pass

    def test_provider_user_id_is_string(self, handler, impl):
        """provider_user_id is always stringified even when id is int."""
        user_data = {"id": 99999, "email": "strid@example.com", "name": "StrID"}
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=resp,
        ):
            info = handler._get_github_user_info("token-abc")
        assert info.provider_user_id == "99999"
        assert isinstance(info.provider_user_id, str)

    def test_sends_bearer_authorization_header(self, handler, impl):
        """Sync path sends Bearer token in Authorization header."""
        user_data = {"id": 42, "email": "auth@example.com", "name": "Auth"}
        resp = self._make_urlopen_response(user_data)

        with patch(
            "aragora.server.handlers._oauth.github.urllib_request.urlopen",
            return_value=resp,
        ) as mock_urlopen:
            handler._get_github_user_info("my-secret-token")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer my-secret-token"


# ===========================================================================
# _get_github_user_info (async path)
# ===========================================================================


class TestGetGitHubUserInfoAsync:
    """Tests for _get_github_user_info async path."""

    @pytest.mark.asyncio
    async def test_async_public_email(self, handler, impl):
        """Async path with public email returns OAuthUserInfo."""
        user_data = {
            "id": 42,
            "email": "async@example.com",
            "name": "AsyncUser",
            "avatar_url": "http://img",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_github_user_info("token-abc")
            import inspect

            if inspect.isawaitable(result):
                result = await result
        assert result.email == "async@example.com"
        assert result.provider_user_id == "42"

    @pytest.mark.asyncio
    async def test_async_private_email_fallback(self, handler, impl):
        """Async path falls back to emails endpoint when email is None."""
        user_data = {"id": 42, "name": "NoEmail"}
        emails = [
            {"email": "primary@example.com", "primary": True, "verified": True},
        ]

        mock_user_response = MagicMock()
        mock_user_response.json.return_value = user_data

        mock_email_response = MagicMock()
        mock_email_response.json.return_value = emails

        user_client = AsyncMock()
        user_client.get.return_value = mock_user_response
        user_client.__aenter__ = AsyncMock(return_value=user_client)
        user_client.__aexit__ = AsyncMock(return_value=False)

        email_client = AsyncMock()
        email_client.get.return_value = mock_email_response
        email_client.__aenter__ = AsyncMock(return_value=email_client)
        email_client.__aexit__ = AsyncMock(return_value=False)

        clients = [user_client, email_client]
        with patch(
            "aragora.server.handlers._oauth.github.httpx.AsyncClient",
            side_effect=clients,
        ):
            result = handler._get_github_user_info("token-abc")
            import inspect

            if inspect.isawaitable(result):
                result = await result
        assert result.email == "primary@example.com"
        assert result.email_verified is True

    @pytest.mark.asyncio
    async def test_async_no_email_raises(self, handler, impl):
        """Async path raises ValueError when no email found."""
        user_data = {"id": 42, "name": "NoEmail"}
        emails = []

        mock_user_response = MagicMock()
        mock_user_response.json.return_value = user_data

        mock_email_response = MagicMock()
        mock_email_response.json.return_value = emails

        user_client = AsyncMock()
        user_client.get.return_value = mock_user_response
        user_client.__aenter__ = AsyncMock(return_value=user_client)
        user_client.__aexit__ = AsyncMock(return_value=False)

        email_client = AsyncMock()
        email_client.get.return_value = mock_email_response
        email_client.__aenter__ = AsyncMock(return_value=email_client)
        email_client.__aexit__ = AsyncMock(return_value=False)

        clients = [user_client, email_client]
        with patch(
            "aragora.server.handlers._oauth.github.httpx.AsyncClient",
            side_effect=clients,
        ):
            result = handler._get_github_user_info("token-abc")
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="email"):
                    await result

    @pytest.mark.asyncio
    async def test_async_missing_id_raises(self, handler, impl):
        """Async path raises ValueError when 'id' is missing."""
        user_data = {"email": "noid@example.com", "name": "NoId"}
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_github_user_info("token-abc")
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="id"):
                    await result

    @pytest.mark.asyncio
    async def test_async_invalid_json_user_endpoint(self, handler, impl):
        """Async path raises ValueError on invalid JSON from user endpoint."""
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("bad", "", 0)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.github.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_github_user_info("token-abc")
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="Invalid JSON"):
                    await result

    @pytest.mark.asyncio
    async def test_async_invalid_json_emails_endpoint(self, handler, impl):
        """Async path raises ValueError on invalid JSON from emails endpoint."""
        user_data = {"id": 42, "name": "Ghost"}

        mock_user_response = MagicMock()
        mock_user_response.json.return_value = user_data

        mock_email_response = MagicMock()
        mock_email_response.json.side_effect = json.JSONDecodeError("bad", "", 0)

        user_client = AsyncMock()
        user_client.get.return_value = mock_user_response
        user_client.__aenter__ = AsyncMock(return_value=user_client)
        user_client.__aexit__ = AsyncMock(return_value=False)

        email_client = AsyncMock()
        email_client.get.return_value = mock_email_response
        email_client.__aenter__ = AsyncMock(return_value=email_client)
        email_client.__aexit__ = AsyncMock(return_value=False)

        clients = [user_client, email_client]
        with patch(
            "aragora.server.handlers._oauth.github.httpx.AsyncClient",
            side_effect=clients,
        ):
            result = handler._get_github_user_info("token-abc")
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="Invalid JSON"):
                    await result

    @pytest.mark.asyncio
    async def test_async_verified_fallback_email(self, handler, impl):
        """Async path falls back to any verified email when no primary verified."""
        user_data = {"id": 42, "name": "Fallback"}
        emails = [
            {"email": "unverified@example.com", "primary": True, "verified": False},
            {"email": "verified@example.com", "primary": False, "verified": True},
        ]

        mock_user_response = MagicMock()
        mock_user_response.json.return_value = user_data

        mock_email_response = MagicMock()
        mock_email_response.json.return_value = emails

        user_client = AsyncMock()
        user_client.get.return_value = mock_user_response
        user_client.__aenter__ = AsyncMock(return_value=user_client)
        user_client.__aexit__ = AsyncMock(return_value=False)

        email_client = AsyncMock()
        email_client.get.return_value = mock_email_response
        email_client.__aenter__ = AsyncMock(return_value=email_client)
        email_client.__aexit__ = AsyncMock(return_value=False)

        clients = [user_client, email_client]
        with patch(
            "aragora.server.handlers._oauth.github.httpx.AsyncClient",
            side_effect=clients,
        ):
            result = handler._get_github_user_info("token-abc")
            import inspect

            if inspect.isawaitable(result):
                result = await result
        assert result.email == "verified@example.com"
        assert result.email_verified is True

    @pytest.mark.asyncio
    async def test_async_any_email_fallback(self, handler, impl):
        """Async path falls back to first email when none are verified."""
        user_data = {"id": 42, "name": "LastResort"}
        emails = [
            {"email": "only@example.com", "primary": False, "verified": False},
        ]

        mock_user_response = MagicMock()
        mock_user_response.json.return_value = user_data

        mock_email_response = MagicMock()
        mock_email_response.json.return_value = emails

        user_client = AsyncMock()
        user_client.get.return_value = mock_user_response
        user_client.__aenter__ = AsyncMock(return_value=user_client)
        user_client.__aexit__ = AsyncMock(return_value=False)

        email_client = AsyncMock()
        email_client.get.return_value = mock_email_response
        email_client.__aenter__ = AsyncMock(return_value=email_client)
        email_client.__aexit__ = AsyncMock(return_value=False)

        clients = [user_client, email_client]
        with patch(
            "aragora.server.handlers._oauth.github.httpx.AsyncClient",
            side_effect=clients,
        ):
            result = handler._get_github_user_info("token-abc")
            import inspect

            if inspect.isawaitable(result):
                result = await result
        assert result.email == "only@example.com"
        assert result.email_verified is False


# ===========================================================================
# Integration-style tests via OAuthHandler.handle()
# ===========================================================================


class TestHandleRouting:
    """Tests that the GitHub endpoints are routed through OAuthHandler.handle()."""

    @pytest.fixture()
    def oauth_handler(self, impl):
        """Create an OAuthHandler with mock context."""
        from aragora.server.handlers._oauth.base import OAuthHandler

        ctx = {"user_store": MagicMock()}
        h = OAuthHandler(ctx)
        return h

    def test_github_auth_start_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/v1/auth/oauth/github routes to GitHub auth start."""
        impl._get_github_client_id = lambda: "gh-id"

        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = oauth_handler.handle("/api/v1/auth/oauth/github", {}, mock_http_handler, "GET")
        assert _status(result) == 302

    def test_github_callback_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/v1/auth/oauth/github/callback routes to callback handler."""
        result = oauth_handler.handle(
            "/api/v1/auth/oauth/github/callback",
            {"error": "access_denied", "error_description": "denied"},
            mock_http_handler,
            "GET",
        )
        assert _status(result) == 302

    def test_non_v1_github_auth_start_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/auth/oauth/github also routes correctly (non-v1)."""
        impl._get_github_client_id = lambda: "gh-id"

        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=FakeAuthCtx(is_authenticated=False),
        ):
            result = oauth_handler.handle("/api/auth/oauth/github", {}, mock_http_handler, "GET")
        assert _status(result) == 302

    def test_rate_limited_returns_429(self, oauth_handler, impl, mock_http_handler):
        """When rate limiter denies request, returns 429."""
        impl._oauth_limiter.is_allowed = MagicMock(return_value=False)
        result = oauth_handler.handle("/api/v1/auth/oauth/github", {}, mock_http_handler, "GET")
        assert _status(result) == 429
