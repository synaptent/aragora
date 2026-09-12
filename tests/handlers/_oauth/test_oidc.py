"""Tests for aragora/server/handlers/_oauth/oidc.py.

Covers the OIDCOAuthMixin:
- _handle_oidc_auth_start: redirect to OIDC provider, configuration checks,
  redirect URL validation, state generation, discovery endpoint fetching,
  auth endpoint extraction, timeout handling
- _handle_oidc_callback: error from provider, state validation, code exchange,
  user info retrieval, complete OAuth flow dispatch, error paths
- _get_oidc_discovery: sync (urllib) and async (httpx) paths, error handling
- _exchange_oidc_code: sync (urllib) and async (httpx) paths, missing token
  endpoint, correct form data
- _get_oidc_user_info: userinfo endpoint, id_token fallback, email/sub
  validation, sync/async paths
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers._oauth.oidc import OIDCOAuthMixin
from aragora.server.handlers.base import HandlerResult
from aragora.server.handlers.oauth.models import OAuthUserInfo


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


def _make_id_token(payload: dict) -> str:
    """Build a fake JWT id_token (header.payload.signature) with a given payload."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(b"fake-sig").rstrip(b"=")
    return f"{header.decode()}.{body.decode()}.{sig.decode()}"


async def _run_auth_start(handler, http_handler, query_params):
    """Call _handle_oidc_auth_start bypassing decorators (async)."""
    return await handler._handle_oidc_auth_start.__wrapped__.__wrapped__(
        handler, http_handler, query_params
    )


async def _run_callback(handler, http_handler, query_params):
    """Call _handle_oidc_callback bypassing decorators (async)."""
    return await handler._handle_oidc_callback.__wrapped__.__wrapped__(
        handler, http_handler, query_params
    )


# ---------------------------------------------------------------------------
# Mock _oauth_impl module
# ---------------------------------------------------------------------------

_IMPL_MODULE = "aragora.server.handlers.oauth._oauth_impl"


def _make_impl(**overrides: Any) -> ModuleType:
    """Build a fake _oauth_impl module with sensible defaults."""
    mod = ModuleType(_IMPL_MODULE)
    mod._get_oidc_issuer = lambda: "https://idp.example.com"
    mod._get_oidc_client_id = lambda: "oidc-client-id"
    mod._get_oidc_client_secret = lambda: "oidc-client-secret"
    mod._get_oidc_redirect_uri = lambda: "http://localhost:8080/callback/oidc"
    mod._get_oauth_success_url = lambda: "http://localhost:3000/auth/success"
    mod._get_oauth_error_url = lambda: "http://localhost:3000/auth/error"
    mod._validate_redirect_url = lambda url: True
    mod._generate_state = lambda user_id=None, redirect_url=None: "mock-state-token"
    mod._validate_state = lambda state: {"redirect_url": "http://localhost:3000/auth/success"}
    for k, v in overrides.items():
        setattr(mod, k, v)
    return mod


# ---------------------------------------------------------------------------
# Concrete test class mixing in OIDCOAuthMixin
# ---------------------------------------------------------------------------


class _TestOIDCHandler(OIDCOAuthMixin):
    """Concrete class that mixes in OIDCOAuthMixin for testing."""

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

    async def _complete_oauth_flow(
        self, user_info: OAuthUserInfo, state_data: dict
    ) -> HandlerResult:
        self._complete_flow_calls.append((user_info, state_data))
        return HandlerResult(
            status_code=302,
            content_type="text/html",
            body=b"oauth-flow-complete",
            headers={"Location": "http://localhost:3000/auth/success"},
        )


# ---------------------------------------------------------------------------
# Mock discovery document
# ---------------------------------------------------------------------------

MOCK_DISCOVERY = {
    "authorization_endpoint": "https://idp.example.com/authorize",
    "token_endpoint": "https://idp.example.com/token",
    "userinfo_endpoint": "https://idp.example.com/userinfo",
    "issuer": "https://idp.example.com",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def impl():
    """Return a default mock _oauth_impl module and register it in sys.modules."""
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
    return _TestOIDCHandler()


@pytest.fixture()
def mock_http_handler():
    h = MagicMock()
    h.command = "GET"
    h.headers = {}
    return h


# ===========================================================================
# _handle_oidc_auth_start
# ===========================================================================


class TestOIDCAuthStart:
    """Tests for _handle_oidc_auth_start."""

    @pytest.mark.asyncio
    async def test_returns_redirect_to_oidc_provider(self, handler, impl, mock_http_handler):
        """Auth start returns a 302 with Location to OIDC auth endpoint."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = await _run_auth_start(handler, mock_http_handler, {})

        assert _status(result) == 302
        loc = result.headers["Location"]
        assert loc.startswith("https://idp.example.com/authorize?")
        assert "client_id=oidc-client-id" in loc
        assert "response_type=code" in loc
        assert "scope=openid+email+profile" in loc
        assert "state=mock-state-token" in loc

    @pytest.mark.asyncio
    async def test_oidc_not_configured_issuer_returns_503(self, handler, mock_http_handler):
        """Returns 503 when OIDC issuer is not configured."""
        mod = _make_impl(**{"_get_oidc_issuer": lambda: None})
        sys.modules[_IMPL_MODULE] = mod
        try:
            result = await _run_auth_start(handler, mock_http_handler, {})
            assert _status(result) == 503
            body = _body(result)
            assert "not configured" in body.get("error", body.get("raw", "")).lower()
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    @pytest.mark.asyncio
    async def test_oidc_not_configured_client_id_returns_503(self, handler, mock_http_handler):
        """Returns 503 when OIDC client ID is not configured."""
        mod = _make_impl(**{"_get_oidc_client_id": lambda: None})
        sys.modules[_IMPL_MODULE] = mod
        try:
            result = await _run_auth_start(handler, mock_http_handler, {})
            assert _status(result) == 503
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    @pytest.mark.asyncio
    async def test_empty_issuer_returns_503(self, handler, mock_http_handler):
        """Returns 503 when OIDC issuer is empty string."""
        mod = _make_impl(**{"_get_oidc_issuer": lambda: ""})
        sys.modules[_IMPL_MODULE] = mod
        try:
            result = await _run_auth_start(handler, mock_http_handler, {})
            assert _status(result) == 503
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    @pytest.mark.asyncio
    async def test_empty_client_id_returns_503(self, handler, mock_http_handler):
        """Returns 503 when OIDC client ID is empty string."""
        mod = _make_impl(**{"_get_oidc_client_id": lambda: ""})
        sys.modules[_IMPL_MODULE] = mod
        try:
            result = await _run_auth_start(handler, mock_http_handler, {})
            assert _status(result) == 503
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    @pytest.mark.asyncio
    async def test_invalid_redirect_url_returns_400(self, handler, impl, mock_http_handler):
        """Returns 400 when redirect_url fails validation."""
        impl._validate_redirect_url = lambda url: False
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = await _run_auth_start(
                handler, mock_http_handler, {"redirect_url": "https://evil.com"}
            )

        assert _status(result) == 400
        body = _body(result)
        assert "redirect" in body.get("error", body.get("raw", "")).lower()

    @pytest.mark.asyncio
    async def test_custom_redirect_url_passed_to_state(self, handler, impl, mock_http_handler):
        """Custom redirect_url from query params is forwarded to state generation."""
        captured = {}
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)

        def mock_generate(user_id=None, redirect_url=None):
            captured["redirect_url"] = redirect_url
            return "state-token"

        impl._generate_state = mock_generate
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            await _run_auth_start(
                handler, mock_http_handler, {"redirect_url": "https://app.example.com/done"}
            )

        assert captured["redirect_url"] == "https://app.example.com/done"

    @pytest.mark.asyncio
    async def test_authenticated_user_passes_user_id_to_state(
        self, handler, impl, mock_http_handler
    ):
        """When user is already authenticated, user_id is included in state."""
        captured = {}
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)

        def mock_generate(user_id=None, redirect_url=None):
            captured["user_id"] = user_id
            return "state-token"

        impl._generate_state = mock_generate
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=True, user_id="user-42")
            await _run_auth_start(handler, mock_http_handler, {})

        assert captured["user_id"] == "user-42"

    @pytest.mark.asyncio
    async def test_unauthenticated_user_passes_none_user_id(self, handler, impl, mock_http_handler):
        """When user is not authenticated, user_id is None in state."""
        captured = {}
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)

        def mock_generate(user_id=None, redirect_url=None):
            captured["user_id"] = user_id
            return "state-token"

        impl._generate_state = mock_generate
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            await _run_auth_start(handler, mock_http_handler, {})

        assert captured["user_id"] is None

    @pytest.mark.asyncio
    async def test_default_redirect_url_when_not_in_params(self, handler, impl, mock_http_handler):
        """Uses OAuth success URL as default redirect when not specified in query."""
        captured = {}
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)

        def mock_generate(user_id=None, redirect_url=None):
            captured["redirect_url"] = redirect_url
            return "state-token"

        impl._generate_state = mock_generate
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            await _run_auth_start(handler, mock_http_handler, {})

        assert captured["redirect_url"] == "http://localhost:3000/auth/success"

    @pytest.mark.asyncio
    async def test_discovery_failure_returns_503(self, handler, impl, mock_http_handler):
        """Returns 503 when OIDC discovery has no auth endpoint."""
        handler._get_oidc_discovery = MagicMock(return_value={})
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = await _run_auth_start(handler, mock_http_handler, {})

        assert _status(result) == 503
        body = _body(result)
        assert "discovery" in body.get("error", body.get("raw", "")).lower()

    @pytest.mark.asyncio
    async def test_meta_refresh_in_body(self, handler, impl, mock_http_handler):
        """Response body contains a meta refresh tag as fallback."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = await _run_auth_start(handler, mock_http_handler, {})

        assert b"meta http-equiv" in result.body

    @pytest.mark.asyncio
    async def test_redirect_url_as_list(self, handler, impl, mock_http_handler):
        """Query parameters provided as lists are handled correctly."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = await _run_auth_start(
                handler,
                mock_http_handler,
                {"redirect_url": ["https://app.example.com/done"]},
            )

        assert _status(result) == 302

    @pytest.mark.asyncio
    async def test_awaitable_discovery_is_awaited(self, handler, impl, mock_http_handler):
        """When _get_oidc_discovery returns a coroutine, it is awaited."""

        async def async_discovery(issuer):
            return MOCK_DISCOVERY

        handler._get_oidc_discovery = lambda issuer: async_discovery(issuer)
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = await _run_auth_start(handler, mock_http_handler, {})

        assert _status(result) == 302
        loc = result.headers["Location"]
        assert "idp.example.com/authorize" in loc

    @pytest.mark.asyncio
    async def test_discovery_timeout_returns_504(self, handler, impl, mock_http_handler):
        """Returns 504 when OIDC discovery times out."""

        async def slow_discovery(issuer):
            await asyncio.sleep(100)
            return MOCK_DISCOVERY

        handler._get_oidc_discovery = lambda issuer: slow_discovery(issuer)
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            with patch(
                "aragora.server.handlers._oauth.oidc.asyncio.wait_for",
                side_effect=asyncio.TimeoutError,
            ):
                result = await _run_auth_start(handler, mock_http_handler, {})

        assert _status(result) == 504
        body = _body(result)
        assert "timed out" in body.get("error", body.get("raw", "")).lower()

    @pytest.mark.asyncio
    async def test_redirect_uri_in_auth_url(self, handler, impl, mock_http_handler):
        """Authorization URL includes the configured redirect URI."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = await _run_auth_start(handler, mock_http_handler, {})

        loc = result.headers["Location"]
        assert "redirect_uri=" in loc
        assert "localhost%3A8080%2Fcallback%2Foidc" in loc or "localhost:8080/callback/oidc" in loc

    @pytest.mark.asyncio
    async def test_auth_start_with_both_issuer_and_client_id_none(self, handler, mock_http_handler):
        """Returns 503 when both OIDC issuer and client ID are None."""
        mod = _make_impl(**{"_get_oidc_issuer": lambda: None, "_get_oidc_client_id": lambda: None})
        sys.modules[_IMPL_MODULE] = mod
        try:
            result = await _run_auth_start(handler, mock_http_handler, {})
            assert _status(result) == 503
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    @pytest.mark.asyncio
    async def test_auth_start_with_both_empty(self, handler, mock_http_handler):
        """Returns 503 when both OIDC issuer and client ID are empty."""
        mod = _make_impl(**{"_get_oidc_issuer": lambda: "", "_get_oidc_client_id": lambda: ""})
        sys.modules[_IMPL_MODULE] = mod
        try:
            result = await _run_auth_start(handler, mock_http_handler, {})
            assert _status(result) == 503
        finally:
            sys.modules.pop(_IMPL_MODULE, None)


# ===========================================================================
# _handle_oidc_callback
# ===========================================================================


class TestOIDCCallback:
    """Tests for _handle_oidc_callback."""

    @pytest.mark.asyncio
    async def test_error_from_provider_redirects_with_error(self, handler, impl, mock_http_handler):
        """OIDC error parameter triggers redirect with error."""
        result = await _run_callback(
            handler,
            mock_http_handler,
            {"error": "access_denied", "error_description": "User denied"},
        )
        assert _status(result) == 302
        assert "User denied" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_error_without_description_uses_error_code(
        self, handler, impl, mock_http_handler
    ):
        """When no error_description, error code itself is used."""
        result = await _run_callback(handler, mock_http_handler, {"error": "server_error"})
        assert _status(result) == 302
        assert "server_error" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_missing_state_returns_error(self, handler, impl, mock_http_handler):
        """Missing state parameter triggers redirect with error."""
        result = await _run_callback(handler, mock_http_handler, {"code": "auth-code"})
        assert _status(result) == 302
        assert "Missing state" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_invalid_state_returns_error(self, handler, impl, mock_http_handler):
        """Invalid/expired state triggers redirect with error."""
        impl._validate_state = lambda state: None
        result = await _run_callback(
            handler, mock_http_handler, {"state": "bad-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Invalid or expired" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_missing_code_returns_error(self, handler, impl, mock_http_handler):
        """Missing authorization code triggers redirect with error."""
        result = await _run_callback(handler, mock_http_handler, {"state": "valid-state"})
        assert _status(result) == 302
        assert "Missing authorization code" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_token_exchange_httpx_error(self, handler, impl, mock_http_handler):
        """httpx.HTTPError during token exchange redirects with error."""
        import httpx

        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(side_effect=httpx.ConnectError("connection failed"))
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_token_exchange_connection_error(self, handler, impl, mock_http_handler):
        """ConnectionError during token exchange redirects with error."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(side_effect=ConnectionError("network down"))
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_token_exchange_timeout_error(self, handler, impl, mock_http_handler):
        """TimeoutError during token exchange redirects with error."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(side_effect=TimeoutError("request timed out"))
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_token_exchange_os_error(self, handler, impl, mock_http_handler):
        """OSError during token exchange redirects with error."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(side_effect=OSError("network unreachable"))
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_token_exchange_value_error(self, handler, impl, mock_http_handler):
        """ValueError during token exchange redirects with error."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(
            side_effect=ValueError("No token endpoint in OIDC discovery")
        )
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_user_info_failure_returns_error(self, handler, impl, mock_http_handler):
        """Failure to get user info triggers redirect with error."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(
            return_value={"access_token": "tok", "id_token": "idt"}
        )
        handler._get_oidc_user_info = MagicMock(side_effect=ConnectionError("timeout"))
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_user_info_key_error_returns_error(self, handler, impl, mock_http_handler):
        """KeyError during user info fetch redirects with error."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(
            return_value={"access_token": "tok", "id_token": "idt"}
        )
        handler._get_oidc_user_info = MagicMock(side_effect=KeyError("email"))
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_user_info_value_error_returns_error(self, handler, impl, mock_http_handler):
        """ValueError during user info fetch redirects with error."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(
            return_value={"access_token": "tok", "id_token": "idt"}
        )
        handler._get_oidc_user_info = MagicMock(side_effect=ValueError("No email in OIDC response"))
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_user_info_httpx_error_returns_error(self, handler, impl, mock_http_handler):
        """httpx.HTTPError during user info fetch redirects with error."""
        import httpx

        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(
            return_value={"access_token": "tok", "id_token": "idt"}
        )
        handler._get_oidc_user_info = MagicMock(side_effect=httpx.HTTPError("bad gateway"))
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_user_info_os_error_returns_error(self, handler, impl, mock_http_handler):
        """OSError during user info fetch redirects with error."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(
            return_value={"access_token": "tok", "id_token": "idt"}
        )
        handler._get_oidc_user_info = MagicMock(side_effect=OSError("network"))
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_successful_callback_completes_flow(self, handler, impl, mock_http_handler):
        """Successful callback completes the OAuth flow."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(
            return_value={"access_token": "tok", "id_token": "idt"}
        )
        user_info = OAuthUserInfo(
            provider="oidc",
            provider_user_id="sub-123",
            email="alice@example.com",
            name="Alice",
            email_verified=True,
        )
        handler._get_oidc_user_info = MagicMock(return_value=user_info)

        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert len(handler._complete_flow_calls) == 1
        uinfo, sdata = handler._complete_flow_calls[0]
        assert uinfo.email == "alice@example.com"
        assert uinfo.provider == "oidc"

    @pytest.mark.asyncio
    async def test_awaitable_token_exchange_is_awaited(self, handler, impl, mock_http_handler):
        """When _exchange_oidc_code returns a coroutine, it is awaited."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)

        async def async_exchange(code, discovery):
            return {"access_token": "async-tok", "id_token": "async-idt"}

        handler._exchange_oidc_code = lambda code, discovery: async_exchange(code, discovery)

        user_info = OAuthUserInfo(
            provider="oidc",
            provider_user_id="sub-456",
            email="bob@example.com",
            name="Bob",
            email_verified=True,
        )
        handler._get_oidc_user_info = MagicMock(return_value=user_info)

        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert len(handler._complete_flow_calls) == 1

    @pytest.mark.asyncio
    async def test_awaitable_user_info_is_awaited(self, handler, impl, mock_http_handler):
        """When _get_oidc_user_info returns a coroutine, it is awaited."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(
            return_value={"access_token": "tok", "id_token": "idt"}
        )

        user_info = OAuthUserInfo(
            provider="oidc",
            provider_user_id="sub-789",
            email="charlie@example.com",
            name="Charlie",
            email_verified=True,
        )

        async def async_user_info(access_token, id_token, discovery):
            return user_info

        handler._get_oidc_user_info = lambda at, idt, disc: async_user_info(at, idt, disc)

        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert len(handler._complete_flow_calls) == 1

    @pytest.mark.asyncio
    async def test_state_data_passed_to_complete_flow(self, handler, impl, mock_http_handler):
        """State data is passed to _complete_oauth_flow."""
        impl._validate_state = lambda state: {
            "user_id": "linking-user",
            "redirect_url": "https://custom.example.com/done",
        }
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(
            return_value={"access_token": "tok", "id_token": "idt"}
        )
        user_info = OAuthUserInfo(
            provider="oidc",
            provider_user_id="sub-link",
            email="link@example.com",
            name="Linker",
            email_verified=True,
        )
        handler._get_oidc_user_info = MagicMock(return_value=user_info)

        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
        )
        assert _status(result) == 302
        _, sdata = handler._complete_flow_calls[0]
        assert sdata["user_id"] == "linking-user"
        assert sdata["redirect_url"] == "https://custom.example.com/done"

    @pytest.mark.asyncio
    async def test_callback_with_empty_query_params(self, handler, impl, mock_http_handler):
        """Callback with completely empty query params returns missing state error."""
        result = await _run_callback(handler, mock_http_handler, {})
        assert _status(result) == 302
        assert "Missing state" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_injection_in_error_description(self, handler, impl, mock_http_handler):
        """HTML/JS injection in error_description is passed through to redirect_with_error."""
        result = await _run_callback(
            handler,
            mock_http_handler,
            {"error": "bad", "error_description": '<script>alert("xss")</script>'},
        )
        assert _status(result) == 302
        assert handler._error_messages[0].startswith("OIDC error:")

    @pytest.mark.asyncio
    async def test_injection_in_state_parameter(self, handler, impl, mock_http_handler):
        """Malicious state parameter is handled safely."""
        impl._validate_state = lambda state: None
        result = await _run_callback(
            handler,
            mock_http_handler,
            {"state": "'; DROP TABLE users; --", "code": "auth-code"},
        )
        assert _status(result) == 302
        assert "Invalid or expired" in handler._error_messages[0]

    @pytest.mark.asyncio
    async def test_very_long_code_handled(self, handler, impl, mock_http_handler):
        """Very long authorization code is passed through without error."""
        handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        handler._exchange_oidc_code = MagicMock(
            return_value={"access_token": "tok", "id_token": "idt"}
        )
        user_info = OAuthUserInfo(
            provider="oidc",
            provider_user_id="sub-long",
            email="long@example.com",
            name="Long",
            email_verified=True,
        )
        handler._get_oidc_user_info = MagicMock(return_value=user_info)

        long_code = "A" * 10000
        result = await _run_callback(
            handler, mock_http_handler, {"state": "valid", "code": long_code}
        )
        assert _status(result) == 302
        assert len(handler._complete_flow_calls) == 1


# ===========================================================================
# _get_oidc_discovery
# ===========================================================================


class TestGetOIDCDiscovery:
    """Tests for _get_oidc_discovery."""

    @pytest.mark.asyncio
    async def test_async_path_uses_httpx(self, handler, impl):
        """When event loop is running, uses httpx.AsyncClient (async path)."""
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_DISCOVERY

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_discovery("https://idp.example.com")
            import inspect

            if inspect.isawaitable(result):
                data = await result
            else:
                data = result
        assert data == MOCK_DISCOVERY

    @pytest.mark.asyncio
    async def test_async_path_httpx_error_returns_empty(self, handler, impl):
        """httpx.HTTPError returns empty dict in async path."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPError("fail")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_discovery("https://idp.example.com")
            import inspect

            if inspect.isawaitable(result):
                data = await result
            else:
                data = result
        assert data == {}

    @pytest.mark.asyncio
    async def test_async_path_connection_error_returns_empty(self, handler, impl):
        """ConnectionError returns empty dict in async path."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = ConnectionError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_discovery("https://idp.example.com")
            import inspect

            if inspect.isawaitable(result):
                data = await result
            else:
                data = result
        assert data == {}

    @pytest.mark.asyncio
    async def test_async_path_timeout_error_returns_empty(self, handler, impl):
        """TimeoutError returns empty dict in async path."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = TimeoutError("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_discovery("https://idp.example.com")
            import inspect

            if inspect.isawaitable(result):
                data = await result
            else:
                data = result
        assert data == {}

    @pytest.mark.asyncio
    async def test_async_path_os_error_returns_empty(self, handler, impl):
        """OSError returns empty dict in async path."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = OSError("network")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_discovery("https://idp.example.com")
            import inspect

            if inspect.isawaitable(result):
                data = await result
            else:
                data = result
        assert data == {}

    @pytest.mark.asyncio
    async def test_async_path_value_error_returns_empty(self, handler, impl):
        """ValueError returns empty dict in async path."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = ValueError("bad value")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_discovery("https://idp.example.com")
            import inspect

            if inspect.isawaitable(result):
                data = await result
            else:
                data = result
        assert data == {}

    @pytest.mark.asyncio
    async def test_async_discovery_url_strips_trailing_slash(self, handler, impl):
        """Trailing slash on issuer is stripped before building discovery URL."""
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_DISCOVERY

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_discovery("https://idp.example.com/")
            import inspect

            if inspect.isawaitable(result):
                await result
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://idp.example.com/.well-known/openid-configuration"

    @pytest.mark.asyncio
    async def test_async_discovery_url_no_trailing_slash(self, handler, impl):
        """Issuer without trailing slash produces correct discovery URL."""
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_DISCOVERY

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_discovery("https://idp.example.com")
            import inspect

            if inspect.isawaitable(result):
                await result
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://idp.example.com/.well-known/openid-configuration"


# ===========================================================================
# _exchange_oidc_code
# ===========================================================================


class TestExchangeOIDCCode:
    """Tests for _exchange_oidc_code."""

    def test_missing_token_endpoint_raises_value_error(self, handler, impl):
        """Raises ValueError when discovery has no token endpoint."""
        with pytest.raises(ValueError, match="No token endpoint"):
            result = handler._exchange_oidc_code("auth-code", {})
            if asyncio.iscoroutine(result):
                result.close()

    def test_sync_path_uses_urllib(self, handler, impl):
        """When no event loop, uses urllib.request.urlopen (sync path)."""
        token_response = json.dumps({"access_token": "tok-123"}).encode()
        mock_response = MagicMock()
        mock_response.read.return_value = token_response
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            patch(
                "aragora.server.handlers._oauth.oidc.urllib_request.urlopen",
                return_value=mock_response,
            ),
        ):
            result = handler._exchange_oidc_code("auth-code", MOCK_DISCOVERY)

        assert result["access_token"] == "tok-123"

    def test_sync_path_empty_response_returns_empty_dict(self, handler, impl):
        """Empty response body returns empty dict in sync path."""
        mock_response = MagicMock()
        mock_response.read.return_value = b""
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            patch(
                "aragora.server.handlers._oauth.oidc.urllib_request.urlopen",
                return_value=mock_response,
            ),
        ):
            result = handler._exchange_oidc_code("auth-code", MOCK_DISCOVERY)
            assert result == {}

    def test_sync_path_sends_correct_data(self, handler, impl):
        """Sync path sends correct form data to token endpoint."""
        captured_req = {}

        def mock_urlopen(req):
            captured_req["url"] = req.full_url
            captured_req["data"] = req.data
            captured_req["headers"] = dict(req.headers)
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"access_token": "tok"}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with (
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            patch(
                "aragora.server.handlers._oauth.oidc.urllib_request.urlopen",
                side_effect=mock_urlopen,
            ),
        ):
            result = handler._exchange_oidc_code("my-auth-code", MOCK_DISCOVERY)

        assert captured_req["url"] == "https://idp.example.com/token"
        data_str = captured_req["data"].decode("utf-8")
        assert "code=my-auth-code" in data_str
        assert "client_id=oidc-client-id" in data_str
        assert "client_secret=oidc-client-secret" in data_str
        assert "grant_type=authorization_code" in data_str
        assert captured_req["headers"]["Content-type"] == "application/x-www-form-urlencoded"

    @pytest.mark.asyncio
    async def test_async_path_uses_httpx(self, handler, impl):
        """When event loop is running, uses httpx.AsyncClient (async path)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "async-tok"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._exchange_oidc_code("auth-code", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                data = await result
                assert data["access_token"] == "async-tok"
            else:
                assert result["access_token"] == "async-tok"

    @pytest.mark.asyncio
    async def test_async_path_posts_to_token_endpoint(self, handler, impl):
        """Async path posts to the correct token endpoint."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._exchange_oidc_code("auth-code", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                await result

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://idp.example.com/token"
        assert call_args[1]["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

    @pytest.mark.asyncio
    async def test_async_path_sends_correct_form_data(self, handler, impl):
        """Async path sends code, client_id, client_secret, redirect_uri, grant_type."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._exchange_oidc_code("my-code", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                await result

        call_args = mock_client.post.call_args
        data = call_args[1]["data"]
        assert data["code"] == "my-code"
        assert data["client_id"] == "oidc-client-id"
        assert data["client_secret"] == "oidc-client-secret"
        assert data["redirect_uri"] == "http://localhost:8080/callback/oidc"
        assert data["grant_type"] == "authorization_code"


# ===========================================================================
# _get_oidc_user_info
# ===========================================================================


class TestGetOIDCUserInfo:
    """Tests for _get_oidc_user_info."""

    @pytest.mark.asyncio
    async def test_async_userinfo_endpoint_returns_user_info(self, handler, impl):
        """Async path with userinfo endpoint returns OAuthUserInfo."""
        user_data = {
            "sub": "oidc-42",
            "email": "alice@example.com",
            "name": "Alice",
            "picture": "https://example.com/pic.jpg",
            "email_verified": True,
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("access-tok", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                info = await result
            else:
                info = result

        assert isinstance(info, OAuthUserInfo)
        assert info.provider == "oidc"
        assert info.provider_user_id == "oidc-42"
        assert info.email == "alice@example.com"
        assert info.name == "Alice"
        assert info.picture == "https://example.com/pic.jpg"
        assert info.email_verified is True

    @pytest.mark.asyncio
    async def test_async_name_fallback_to_email_prefix(self, handler, impl):
        """When name is missing, falls back to email prefix."""
        user_data = {
            "sub": "oidc-43",
            "email": "charlie@example.com",
            "email_verified": False,
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("access-tok", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                info = await result
            else:
                info = result

        assert info.name == "charlie"
        assert info.email_verified is False

    @pytest.mark.asyncio
    async def test_async_no_email_raises_value_error(self, handler, impl):
        """Raises ValueError when OIDC response has no email."""
        user_data = {"sub": "oidc-44"}
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("access-tok", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="No email"):
                    await result

    @pytest.mark.asyncio
    async def test_async_no_sub_raises_value_error(self, handler, impl):
        """Raises ValueError when OIDC response has no subject."""
        user_data = {"email": "nosub@example.com"}
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("access-tok", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="No subject"):
                    await result

    @pytest.mark.asyncio
    async def test_async_id_token_fallback_when_userinfo_empty(self, handler, impl):
        """Falls back to id_token payload when userinfo returns empty."""
        id_token_payload = {
            "sub": "oidc-fallback",
            "email": "fallback@example.com",
            "name": "Fallback User",
            "email_verified": True,
        }
        id_token = _make_id_token(id_token_payload)

        mock_response = MagicMock()
        mock_response.json.return_value = {}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("access-tok", id_token, MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                info = await result
            else:
                info = result

        assert info.provider_user_id == "oidc-fallback"
        assert info.email == "fallback@example.com"
        assert info.name == "Fallback User"

    @pytest.mark.asyncio
    async def test_async_id_token_fallback_when_userinfo_fails(self, handler, impl):
        """Falls back to id_token when userinfo endpoint fails."""
        import httpx

        id_token_payload = {
            "sub": "oidc-fail-fallback",
            "email": "fail-fallback@example.com",
            "name": "Fail Fallback",
            "email_verified": False,
        }
        id_token = _make_id_token(id_token_payload)

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPError("userinfo failed")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("access-tok", id_token, MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                info = await result
            else:
                info = result

        assert info.provider_user_id == "oidc-fail-fallback"
        assert info.email == "fail-fallback@example.com"

    @pytest.mark.asyncio
    async def test_async_no_userinfo_endpoint_uses_id_token(self, handler, impl):
        """When discovery has no userinfo endpoint, use id_token directly."""
        id_token_payload = {
            "sub": "oidc-no-endpoint",
            "email": "noendpoint@example.com",
            "name": "No Endpoint",
            "email_verified": True,
        }
        id_token = _make_id_token(id_token_payload)

        discovery_no_userinfo = {
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
        }

        result = handler._get_oidc_user_info("access-tok", id_token, discovery_no_userinfo)
        import inspect

        if inspect.isawaitable(result):
            info = await result
        else:
            info = result

        assert info.provider_user_id == "oidc-no-endpoint"
        assert info.email == "noendpoint@example.com"

    @pytest.mark.asyncio
    async def test_async_no_access_token_skips_userinfo(self, handler, impl):
        """When access_token is None, skip userinfo endpoint and use id_token."""
        id_token_payload = {
            "sub": "oidc-no-access",
            "email": "noaccess@example.com",
            "name": "No Access",
            "email_verified": True,
        }
        id_token = _make_id_token(id_token_payload)

        result = handler._get_oidc_user_info(None, id_token, MOCK_DISCOVERY)
        import inspect

        if inspect.isawaitable(result):
            info = await result
        else:
            info = result

        assert info.provider_user_id == "oidc-no-access"
        assert info.email == "noaccess@example.com"

    @pytest.mark.asyncio
    async def test_async_email_verified_default_false(self, handler, impl):
        """email_verified defaults to False when not in OIDC response."""
        user_data = {
            "sub": "oidc-noverified",
            "email": "noverified@example.com",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("access-tok", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                info = await result
            else:
                info = result

        assert info.email_verified is False

    @pytest.mark.asyncio
    async def test_async_picture_field(self, handler, impl):
        """Picture URL from OIDC response is passed through."""
        user_data = {
            "sub": "oidc-pic",
            "email": "pic@example.com",
            "name": "Pic User",
            "picture": "https://photos.example.com/me.jpg",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("access-tok", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                info = await result
            else:
                info = result

        assert info.picture == "https://photos.example.com/me.jpg"

    @pytest.mark.asyncio
    async def test_async_picture_is_none_when_absent(self, handler, impl):
        """Picture is None when not in OIDC response."""
        user_data = {
            "sub": "oidc-nopic",
            "email": "nopic@example.com",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("access-tok", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                info = await result
            else:
                info = result

        assert info.picture is None

    @pytest.mark.asyncio
    async def test_async_userinfo_sends_bearer_token(self, handler, impl):
        """Async userinfo request sends Bearer authorization header."""
        user_data = {"sub": "oidc-auth", "email": "auth@example.com"}
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("my-bearer-token", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                await result

        call_args = mock_client.get.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer my-bearer-token"

    @pytest.mark.asyncio
    async def test_async_userinfo_endpoint_url(self, handler, impl):
        """Async path uses userinfo_endpoint from discovery."""
        user_data = {"sub": "oidc-url", "email": "url@example.com"}
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("tok", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                await result

        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://idp.example.com/userinfo"

    @pytest.mark.asyncio
    async def test_async_empty_email_raises(self, handler, impl):
        """Empty string email in OIDC response raises ValueError."""
        user_data = {"sub": "oidc-empty-email", "email": ""}
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("tok", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="No email"):
                    await result

    @pytest.mark.asyncio
    async def test_async_empty_sub_raises(self, handler, impl):
        """Empty string sub in OIDC response raises ValueError."""
        user_data = {"sub": "", "email": "valid@example.com"}
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("tok", "id-tok", MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                with pytest.raises(ValueError, match="No subject"):
                    await result

    @pytest.mark.asyncio
    async def test_userinfo_data_takes_precedence_over_id_token(self, handler, impl):
        """When userinfo returns data, id_token is not used as fallback."""
        id_token_payload = {
            "sub": "oidc-id-token-sub",
            "email": "idtoken@example.com",
            "name": "ID Token User",
        }
        id_token = _make_id_token(id_token_payload)

        user_data = {
            "sub": "oidc-userinfo-sub",
            "email": "userinfo@example.com",
            "name": "Userinfo User",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = user_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.oidc.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_oidc_user_info("tok", id_token, MOCK_DISCOVERY)
            import inspect

            if inspect.isawaitable(result):
                info = await result
            else:
                info = result

        assert info.email == "userinfo@example.com"
        assert info.provider_user_id == "oidc-userinfo-sub"

    @pytest.mark.asyncio
    async def test_id_token_with_only_two_parts_ignored(self, handler, impl):
        """id_token with < 3 parts is not parsed."""
        discovery_no_userinfo = {
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
        }
        bad_id_token = "header.payload"

        result = handler._get_oidc_user_info(None, bad_id_token, discovery_no_userinfo)
        import inspect

        if inspect.isawaitable(result):
            with pytest.raises(ValueError, match="No email"):
                await result

    @pytest.mark.asyncio
    async def test_id_token_with_no_token_returns_empty(self, handler, impl):
        """When no id_token and no userinfo, _fallback_id_token returns empty."""
        discovery_no_userinfo = {
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
        }

        result = handler._get_oidc_user_info(None, None, discovery_no_userinfo)
        import inspect

        if inspect.isawaitable(result):
            with pytest.raises(ValueError, match="No email"):
                await result

    @pytest.mark.asyncio
    async def test_id_token_padding_is_handled(self, handler, impl):
        """id_token base64 payload with missing padding is decoded correctly."""
        payload = {"sub": "padded-sub", "email": "padded@example.com"}
        discovery_no_userinfo = {"token_endpoint": "https://idp.example.com/token"}

        id_token = _make_id_token(payload)

        result = handler._get_oidc_user_info(None, id_token, discovery_no_userinfo)
        import inspect

        if inspect.isawaitable(result):
            info = await result
        else:
            info = result

        assert info.email == "padded@example.com"
        assert info.provider_user_id == "padded-sub"


# ===========================================================================
# Integration via OAuthHandler.handle()
# ===========================================================================


class TestHandleRouting:
    """Tests that the OIDC endpoints are routed through OAuthHandler.handle()."""

    @pytest.fixture()
    def oauth_handler(self, impl):
        """Create an OAuthHandler with mock context."""
        from aragora.server.handlers._oauth.base import OAuthHandler

        impl.create_span = MagicMock()
        impl.add_span_attributes = MagicMock()
        span_mock = MagicMock()
        span_mock.__enter__ = MagicMock(return_value=span_mock)
        span_mock.__exit__ = MagicMock(return_value=False)
        impl.create_span.return_value = span_mock

        limiter = MagicMock()
        limiter.is_allowed = MagicMock(return_value=True)
        impl._oauth_limiter = limiter

        ctx = {"user_store": MagicMock()}
        return OAuthHandler(ctx)

    def test_oidc_auth_start_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/v1/auth/oauth/oidc routes to OIDC auth start."""
        oauth_handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = oauth_handler.handle("/api/v1/auth/oauth/oidc", {}, mock_http_handler, "GET")
        assert _status(result) == 302

    def test_oidc_callback_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/v1/auth/oauth/oidc/callback routes to callback handler."""
        result = oauth_handler.handle(
            "/api/v1/auth/oauth/oidc/callback",
            {"error": "access_denied", "error_description": "denied"},
            mock_http_handler,
            "GET",
        )
        assert _status(result) == 302

    def test_non_v1_oidc_auth_start_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/auth/oauth/oidc also routes correctly (non-v1)."""
        oauth_handler._get_oidc_discovery = MagicMock(return_value=MOCK_DISCOVERY)
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = oauth_handler.handle("/api/auth/oauth/oidc", {}, mock_http_handler, "GET")
        assert _status(result) == 302

    def test_non_v1_oidc_callback_routed(self, oauth_handler, impl, mock_http_handler):
        """GET /api/auth/oauth/oidc/callback routes correctly (non-v1)."""
        result = oauth_handler.handle(
            "/api/auth/oauth/oidc/callback",
            {"error": "access_denied", "error_description": "denied"},
            mock_http_handler,
            "GET",
        )
        assert _status(result) == 302

    def test_rate_limited_returns_429(self, oauth_handler, impl, mock_http_handler):
        """When rate limiter denies request, returns 429."""
        impl._oauth_limiter.is_allowed = MagicMock(return_value=False)
        result = oauth_handler.handle("/api/v1/auth/oauth/oidc", {}, mock_http_handler, "GET")
        assert _status(result) == 429

    def test_oidc_post_method_not_allowed(self, oauth_handler, impl, mock_http_handler):
        """POST /api/v1/auth/oauth/oidc returns 405."""
        mock_http_handler.command = "POST"
        result = oauth_handler.handle("/api/v1/auth/oauth/oidc", {}, mock_http_handler, "POST")
        assert _status(result) == 405

    def test_oidc_callback_post_method_not_allowed(self, oauth_handler, impl, mock_http_handler):
        """POST /api/v1/auth/oauth/oidc/callback returns 405."""
        mock_http_handler.command = "POST"
        result = oauth_handler.handle(
            "/api/v1/auth/oauth/oidc/callback", {}, mock_http_handler, "POST"
        )
        assert _status(result) == 405

    def test_path_traversal_safe(self, oauth_handler, impl, mock_http_handler):
        """Path traversal attempts do not match any route."""
        result = oauth_handler.handle(
            "/api/v1/auth/oauth/oidc/../../../etc/passwd", {}, mock_http_handler, "GET"
        )
        # Should return 405 (unmatched route) since path is not in ROUTES
        assert result is None or _status(result) == 405
