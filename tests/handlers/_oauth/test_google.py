"""Tests for aragora/server/handlers/_oauth/google.py.

Covers the GoogleOAuthMixin:
- _handle_google_auth_start: redirect to Google consent screen
- _handle_google_callback: full OAuth callback flow (token exchange, user info,
  user creation/linking, account linking, error paths)
- _exchange_code_for_tokens: sync (urllib) and async (httpx) code exchange
- _get_google_user_info: sync (urllib) and async (httpx) user info fetch
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers._oauth.google import GoogleOAuthMixin
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


# ---------------------------------------------------------------------------
# Mock _oauth_impl module
# ---------------------------------------------------------------------------


def _make_impl(**overrides: Any) -> ModuleType:
    """Build a fake _oauth_impl module with sensible defaults."""
    mod = ModuleType("aragora.server.handlers.oauth._oauth_impl")
    mod.GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    mod.GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    mod.GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    mod.GOOGLE_CLIENT_ID = "test-client-id"
    mod._get_google_client_id = lambda: "test-client-id"
    mod._get_google_client_secret = lambda: "test-client-secret"
    mod._get_google_redirect_uri = lambda: "http://localhost:8080/callback"
    mod._get_oauth_success_url = lambda: "http://localhost:3000/auth/success"
    mod._get_oauth_error_url = lambda: "http://localhost:3000/auth/error"
    mod._validate_redirect_url = lambda url: True
    mod._generate_state = lambda user_id=None, redirect_url=None: "mock-state-token"
    mod._validate_state = lambda state: {"redirect_url": "http://localhost:3000/auth/success"}
    for k, v in overrides.items():
        setattr(mod, k, v)
    return mod


# ---------------------------------------------------------------------------
# Concrete test class mixing in GoogleOAuthMixin
# ---------------------------------------------------------------------------

OAUTH_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


class _TestGoogleHandler(GoogleOAuthMixin):
    """Concrete class that mixes in GoogleOAuthMixin for testing."""

    OAUTH_NO_CACHE_HEADERS = OAUTH_NO_CACHE_HEADERS

    def __init__(self) -> None:
        self._user_store = MagicMock()
        self._error_messages: list[str] = []
        self._redirect_tokens_calls: list[tuple] = []
        self._account_linking_calls: list[tuple] = []

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

    def _redirect_with_tokens(self, redirect_url: str, tokens: Any) -> HandlerResult:
        self._redirect_tokens_calls.append((redirect_url, tokens))
        return HandlerResult(
            status_code=302,
            content_type="text/html",
            body=b"redirect-with-tokens",
            headers={"Location": redirect_url},
        )

    def _find_user_by_oauth(self, user_store: Any, user_info: OAuthUserInfo) -> Any:
        return user_store.find_by_oauth(user_info.provider, user_info.provider_user_id)

    def _link_oauth_to_user(self, user_store: Any, user_id: str, user_info: OAuthUserInfo) -> bool:
        return user_store.link_oauth(user_id, user_info)

    def _create_oauth_user(self, user_store: Any, user_info: OAuthUserInfo) -> Any:
        return user_store.create_oauth_user(user_info)

    def _handle_account_linking(
        self,
        user_store: Any,
        user_id: str,
        user_info: OAuthUserInfo,
        state_data: dict,
    ) -> HandlerResult:
        self._account_linking_calls.append((user_id, user_info, state_data))
        return HandlerResult(
            status_code=302,
            content_type="text/html",
            body=b"account-linked",
            headers={"Location": "http://localhost:3000/auth/success"},
        )


# ---------------------------------------------------------------------------
# Mock user object
# ---------------------------------------------------------------------------


@dataclass
class _MockUser:
    id: str = "user-123"
    email: str = "alice@example.com"
    org_id: str = "org-1"
    role: str = "user"


@dataclass
class _MockTokenPair:
    access_token: str = "access-tok"
    refresh_token: str = "refresh-tok"
    expires_in: int = 3600


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def impl():
    """Return a default mock _oauth_impl module and register it in sys.modules."""
    mod = _make_impl()
    sys.modules["aragora.server.handlers.oauth._oauth_impl"] = mod
    yield mod
    # Restore original if present, else remove
    sys.modules.pop("aragora.server.handlers.oauth._oauth_impl", None)


@pytest.fixture()
def handler():
    return _TestGoogleHandler()


@pytest.fixture()
def mock_http_handler():
    h = MagicMock()
    h.command = "GET"
    h.headers = {}
    return h


@pytest.fixture()
def sample_user_info():
    return OAuthUserInfo(
        provider="google",
        provider_user_id="goog-12345",
        email="alice@example.com",
        name="Alice",
        picture="https://example.com/pic.jpg",
        email_verified=True,
    )


# ===========================================================================
# _handle_google_auth_start
# ===========================================================================


class TestGoogleAuthStart:
    """Tests for _handle_google_auth_start."""

    def test_returns_redirect_to_google(self, handler, impl, mock_http_handler):
        """Auth start returns a 302 with Location to Google auth URL."""
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = handler._handle_google_auth_start(mock_http_handler, {})

        assert _status(result) == 302
        loc = result.headers["Location"]
        assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=test-client-id" in loc
        assert "response_type=code" in loc
        assert "scope=openid+email+profile" in loc
        assert "state=mock-state-token" in loc
        assert "access_type=offline" in loc

    def test_google_not_configured_returns_503(self, handler, mock_http_handler):
        """Returns 503 when Google client ID is not configured."""
        mod = _make_impl(**{"_get_google_client_id": lambda: None})
        sys.modules["aragora.server.handlers.oauth._oauth_impl"] = mod
        try:
            result = handler._handle_google_auth_start(mock_http_handler, {})
            assert _status(result) == 503
            body = _body(result)
            assert "not configured" in body.get("error", body.get("raw", "")).lower()
        finally:
            sys.modules.pop("aragora.server.handlers.oauth._oauth_impl", None)

    def test_invalid_redirect_url_returns_400(self, handler, impl, mock_http_handler):
        """Returns 400 when redirect_url fails validation."""
        impl._validate_redirect_url = lambda url: False
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = handler._handle_google_auth_start(
                mock_http_handler, {"redirect_url": "https://evil.com"}
            )

        assert _status(result) == 400
        body = _body(result)
        assert "redirect" in body.get("error", body.get("raw", "")).lower()

    def test_custom_redirect_url_passed_to_state(self, handler, impl, mock_http_handler):
        """Custom redirect_url from query params is forwarded to state generation."""
        captured = {}

        def mock_generate(user_id=None, redirect_url=None):
            captured["redirect_url"] = redirect_url
            return "state-token"

        impl._generate_state = mock_generate
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = handler._handle_google_auth_start(
                mock_http_handler, {"redirect_url": "https://app.example.com/done"}
            )

        assert _status(result) == 302
        assert captured["redirect_url"] == "https://app.example.com/done"

    def test_authenticated_user_passes_user_id_to_state(self, handler, impl, mock_http_handler):
        """When user is already authenticated, user_id is included in state."""
        captured = {}

        def mock_generate(user_id=None, redirect_url=None):
            captured["user_id"] = user_id
            return "state-token"

        impl._generate_state = mock_generate
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=True, user_id="user-42")
            result = handler._handle_google_auth_start(mock_http_handler, {})

        assert _status(result) == 302
        assert captured["user_id"] == "user-42"

    def test_unauthenticated_user_passes_none_user_id(self, handler, impl, mock_http_handler):
        """When user is not authenticated, user_id is None in state."""
        captured = {}

        def mock_generate(user_id=None, redirect_url=None):
            captured["user_id"] = user_id
            return "state-token"

        impl._generate_state = mock_generate
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = handler._handle_google_auth_start(mock_http_handler, {})

        assert _status(result) == 302
        assert captured["user_id"] is None

    def test_default_redirect_url_when_not_in_params(self, handler, impl, mock_http_handler):
        """Uses OAuth success URL as default redirect when not specified in query."""
        captured = {}

        def mock_generate(user_id=None, redirect_url=None):
            captured["redirect_url"] = redirect_url
            return "state-token"

        impl._generate_state = mock_generate
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            handler._handle_google_auth_start(mock_http_handler, {})

        assert captured["redirect_url"] == "http://localhost:3000/auth/success"


# ===========================================================================
# _handle_google_callback
# ===========================================================================


class TestGoogleCallback:
    """Tests for _handle_google_callback."""

    @pytest.fixture(autouse=True)
    def _patch_audit(self):
        """Suppress audit calls during callback tests."""
        with (
            patch("aragora.server.handlers._oauth.google.audit_action"),
            patch("aragora.server.handlers._oauth.google.audit_security"),
        ):
            yield

    def test_error_from_google_redirects_with_error(self, handler, impl, mock_http_handler):
        """Google error parameter triggers redirect with error."""
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler,
                mock_http_handler,
                {"error": "access_denied", "error_description": "User denied"},
            )
        )
        assert _status(result) == 302
        assert "User denied" in handler._error_messages[0]

    def test_error_without_description_uses_error_code(self, handler, impl, mock_http_handler):
        """When no error_description, error code itself is used."""
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"error": "server_error"}
            )
        )
        assert _status(result) == 302
        assert "server_error" in handler._error_messages[0]

    def test_missing_state_returns_error(self, handler, impl, mock_http_handler):
        """Missing state parameter triggers redirect with error."""
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "Missing state" in handler._error_messages[0]

    def test_invalid_state_returns_error(self, handler, impl, mock_http_handler):
        """Invalid/expired state triggers redirect with error."""
        impl._validate_state = lambda state: None
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "bad-state", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "Invalid or expired" in handler._error_messages[0]

    def test_missing_code_returns_error(self, handler, impl, mock_http_handler):
        """Missing authorization code triggers redirect with error."""
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid-state"}
            )
        )
        assert _status(result) == 302
        assert "Missing authorization code" in handler._error_messages[0]

    def test_token_exchange_failure_returns_error(self, handler, impl, mock_http_handler):
        """Token exchange HTTP error triggers redirect with error."""
        import httpx

        handler._exchange_code_for_tokens = MagicMock(
            side_effect=httpx.ConnectError("connection failed")
        )
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    def test_no_access_token_returns_error(self, handler, impl, mock_http_handler):
        """Token response without access_token triggers redirect with error."""
        handler._exchange_code_for_tokens = MagicMock(return_value={"token_type": "Bearer"})
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "No access token" in handler._error_messages[0]

    def test_user_info_failure_returns_error(self, handler, impl, mock_http_handler):
        """Failure to get user info triggers redirect with error."""
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(side_effect=ConnectionError("timeout"))
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    def test_no_user_store_returns_error(self, handler, impl, mock_http_handler, sample_user_info):
        """None user_store triggers redirect with error."""
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store = None
        handler._get_user_store = lambda: None
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "User service unavailable" in handler._error_messages[0]

    def test_account_linking_when_user_id_in_state(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """When state_data contains user_id, account linking is invoked."""
        impl._validate_state = lambda state: {
            "user_id": "linking-user",
            "redirect_url": "http://localhost:3000/auth/success",
        }
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert len(handler._account_linking_calls) == 1
        uid, uinfo, sdata = handler._account_linking_calls[0]
        assert uid == "linking-user"
        assert uinfo.email == "alice@example.com"

    def test_existing_oauth_user_login(self, handler, impl, mock_http_handler, sample_user_info):
        """Existing user found by OAuth ID proceeds to token creation."""
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = user
        handler._user_store.update_user = MagicMock()

        tokens = _MockTokenPair()
        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=tokens,
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        assert _status(result) == 302
        assert len(handler._redirect_tokens_calls) == 1
        redirect_url, tok = handler._redirect_tokens_calls[0]
        assert redirect_url == "http://localhost:3000/auth/success"
        assert tok.access_token == "access-tok"

    def test_find_user_by_oauth_db_error_redirects(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """Database error during find_user_by_oauth redirects with error."""
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._find_user_by_oauth = MagicMock(side_effect=RuntimeError("DB connection lost"))
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "database error" in handler._error_messages[0].lower()

    def test_find_user_by_oauth_interface_error_gives_temp_message(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """InterfaceError during find_user_by_oauth gives temporary connection message."""
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)

        class InterfaceError(Exception):
            pass

        handler._find_user_by_oauth = MagicMock(side_effect=InterfaceError("pool closed"))
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "temporary connection" in handler._error_messages[0].lower()

    def test_email_lookup_links_existing_account(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """When no OAuth user but email matches, link OAuth to existing account."""
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = None
        handler._user_store.get_user_by_email.return_value = user
        handler._user_store.update_user = MagicMock()

        tokens = _MockTokenPair()
        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=tokens,
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        assert _status(result) == 302
        handler._user_store.link_oauth.assert_called_once_with(user.id, sample_user_info)

    def test_unverified_email_blocks_linking(self, handler, impl, mock_http_handler):
        """Unverified email from Google blocks linking to existing account."""
        unverified_info = OAuthUserInfo(
            provider="google",
            provider_user_id="goog-99",
            email="alice@example.com",
            name="Alice",
            email_verified=False,
        )
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=unverified_info)
        handler._user_store.find_by_oauth.return_value = None
        handler._user_store.get_user_by_email.return_value = user

        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "verification required" in handler._error_messages[0].lower()

    def test_new_user_creation(self, handler, impl, mock_http_handler, sample_user_info):
        """When no existing user, create new OAuth user."""
        new_user = _MockUser(id="new-user-1")
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = None
        handler._user_store.get_user_by_email.return_value = None
        handler._user_store.create_oauth_user.return_value = new_user
        handler._user_store.update_user = MagicMock()

        tokens = _MockTokenPair()
        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=tokens,
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        assert _status(result) == 302
        handler._user_store.create_oauth_user.assert_called_once_with(sample_user_info)
        assert len(handler._redirect_tokens_calls) == 1

    def test_create_user_failure_returns_error(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """Failure to create user returns error redirect."""
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = None
        handler._user_store.get_user_by_email.return_value = None
        handler._create_oauth_user = MagicMock(side_effect=RuntimeError("DB write failed"))

        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "Failed to create" in handler._error_messages[0]

    def test_create_user_returns_none_gives_error(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """When create_oauth_user returns None, error redirect occurs."""
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = None
        handler._user_store.get_user_by_email.return_value = None
        handler._user_store.create_oauth_user.return_value = None

        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "Failed to create user" in handler._error_messages[0]

    def test_update_last_login_failure_is_nonfatal(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """Failure to update last_login is non-fatal; tokens are still created."""
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = user
        handler._user_store.update_user.side_effect = RuntimeError("DB error")

        tokens = _MockTokenPair()
        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=tokens,
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        # Should still succeed despite update_user failure
        assert _status(result) == 302
        assert len(handler._redirect_tokens_calls) == 1

    def test_jwt_configuration_error_returns_error(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """ConfigurationError during token creation returns specific error."""
        from aragora.exceptions import ConfigurationError

        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = user
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            side_effect=ConfigurationError("jwt_auth", "JWT secret not set"),
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        assert _status(result) == 302
        assert "JWT" in handler._error_messages[0]

    def test_token_creation_value_error_returns_error(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """ValueError during token creation returns error with type name."""
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = user
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            side_effect=ValueError("bad value"),
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        assert _status(result) == 302
        assert "ValueError" in handler._error_messages[0]

    def test_redirect_url_from_state_data(self, handler, impl, mock_http_handler, sample_user_info):
        """Redirect URL is taken from state_data when present."""
        impl._validate_state = lambda state: {
            "redirect_url": "https://custom.example.com/done",
        }
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = user
        handler._user_store.update_user = MagicMock()

        tokens = _MockTokenPair()
        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=tokens,
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        redirect_url, _ = handler._redirect_tokens_calls[0]
        assert redirect_url == "https://custom.example.com/done"

    def test_redirect_url_falls_back_to_oauth_success_url(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """When state_data has no redirect_url, falls back to OAuth success URL."""
        impl._validate_state = lambda state: {}
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = user
        handler._user_store.update_user = MagicMock()

        tokens = _MockTokenPair()
        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=tokens,
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        redirect_url, _ = handler._redirect_tokens_calls[0]
        assert redirect_url == "http://localhost:3000/auth/success"

    def test_async_user_store_methods_used_when_available(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """When user_store has async methods, they are preferred."""
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = None

        # Set up async get_user_by_email_async
        async def async_get_by_email(email):
            return user

        handler._user_store.get_user_by_email_async = async_get_by_email

        # Set up async update_user_async
        async def async_update_user(user_id, **kwargs):
            pass

        handler._user_store.update_user_async = async_update_user
        handler._user_store.link_oauth = MagicMock(return_value=True)

        tokens = _MockTokenPair()
        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=tokens,
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        assert _status(result) == 302
        assert len(handler._redirect_tokens_calls) == 1

    def test_get_user_by_email_db_error_returns_error(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """Database error during email lookup redirects with error."""
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = None
        handler._user_store.get_user_by_email.side_effect = RuntimeError("DB error")
        # Ensure no async variant
        handler._user_store.get_user_by_email_async = None

        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "database error" in handler._error_messages[0].lower()

    def test_token_exchange_timeout_error(self, handler, impl, mock_http_handler):
        """TimeoutError during token exchange redirects with error."""
        handler._exchange_code_for_tokens = MagicMock(side_effect=TimeoutError("request timed out"))
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    def test_token_exchange_os_error(self, handler, impl, mock_http_handler):
        """OSError during token exchange redirects with error."""
        handler._exchange_code_for_tokens = MagicMock(side_effect=OSError("network unreachable"))
        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "Failed to exchange" in handler._error_messages[0]

    def test_awaitable_token_exchange_result(
        self, handler, impl, mock_http_handler, sample_user_info
    ):
        """When _exchange_code_for_tokens returns a coroutine, it is awaited."""
        user = _MockUser()

        async def async_exchange(code):
            return {"access_token": "async-tok"}

        handler._exchange_code_for_tokens = lambda code: async_exchange(code)
        handler._get_google_user_info = MagicMock(return_value=sample_user_info)
        handler._user_store.find_by_oauth.return_value = user
        handler._user_store.update_user = MagicMock()

        tokens = _MockTokenPair()
        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=tokens,
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        assert _status(result) == 302
        assert len(handler._redirect_tokens_calls) == 1

    def test_awaitable_user_info_result(self, handler, impl, mock_http_handler, sample_user_info):
        """When _get_google_user_info returns a coroutine, it is awaited."""
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})

        async def async_user_info(token):
            return sample_user_info

        handler._get_google_user_info = lambda token: async_user_info(token)
        handler._user_store.find_by_oauth.return_value = user
        handler._user_store.update_user = MagicMock()

        tokens = _MockTokenPair()
        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            return_value=tokens,
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        assert _status(result) == 302
        assert len(handler._redirect_tokens_calls) == 1


# ===========================================================================
# _exchange_code_for_tokens
# ===========================================================================


class TestExchangeCodeForTokens:
    """Tests for _exchange_code_for_tokens."""

    def test_sync_path_uses_urllib(self, handler, impl):
        """When no event loop, uses urllib.request.urlopen (sync path)."""
        token_response = json.dumps({"access_token": "tok-123", "token_type": "Bearer"}).encode()
        mock_response = MagicMock()
        mock_response.read.return_value = token_response
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            patch(
                "aragora.server.handlers._oauth.google.urllib_request.urlopen",
                return_value=mock_response,
            ),
        ):
            result = handler._exchange_code_for_tokens("auth-code-123")

        assert result["access_token"] == "tok-123"

    def test_sync_path_empty_response_raises(self, handler, impl):
        """Empty response from Google token endpoint raises ValueError."""
        mock_response = MagicMock()
        mock_response.read.return_value = b""
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            patch(
                "aragora.server.handlers._oauth.google.urllib_request.urlopen",
                return_value=mock_response,
            ),
        ):
            with pytest.raises(ValueError, match="Empty response"):
                handler._exchange_code_for_tokens("auth-code")

    def test_sync_path_invalid_json_raises(self, handler, impl):
        """Invalid JSON from Google token endpoint raises ValueError."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"not-json"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            patch(
                "aragora.server.handlers._oauth.google.urllib_request.urlopen",
                return_value=mock_response,
            ),
        ):
            with pytest.raises(ValueError, match="Invalid JSON"):
                handler._exchange_code_for_tokens("auth-code")

    @pytest.mark.asyncio
    async def test_async_path_uses_httpx(self, handler, impl):
        """When event loop is running, uses httpx.AsyncClient (async path)."""
        mock_response = MagicMock()
        mock_response.content = b'{"access_token": "async-tok"}'
        mock_response.json.return_value = {"access_token": "async-tok"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.google.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._exchange_code_for_tokens("auth-code")
            # In async context it returns a coroutine
            if asyncio.iscoroutine(result):
                data = await result
                assert data["access_token"] == "async-tok"
            else:
                assert result["access_token"] == "async-tok"

    @pytest.mark.asyncio
    async def test_async_path_empty_response_raises(self, handler, impl):
        """Empty response from Google in async path raises ValueError."""
        mock_response = MagicMock()
        mock_response.content = b""

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.google.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._exchange_code_for_tokens("auth-code")
            if asyncio.iscoroutine(result):
                with pytest.raises(ValueError, match="Empty response"):
                    await result

    @pytest.mark.asyncio
    async def test_async_path_invalid_json_raises(self, handler, impl):
        """Invalid JSON response from Google in async path raises ValueError."""
        mock_response = MagicMock()
        mock_response.content = b"not-json"
        mock_response.json.side_effect = json.JSONDecodeError("err", "doc", 0)

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.google.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._exchange_code_for_tokens("auth-code")
            if asyncio.iscoroutine(result):
                with pytest.raises(ValueError, match="Invalid JSON"):
                    await result


# ===========================================================================
# _get_google_user_info
# ===========================================================================


class TestGetGoogleUserInfo:
    """Tests for _get_google_user_info."""

    def test_sync_path_returns_user_info(self, handler, impl):
        """Sync path returns OAuthUserInfo from Google response."""
        user_data = json.dumps(
            {
                "id": "goog-42",
                "email": "bob@example.com",
                "name": "Bob",
                "picture": "https://example.com/bob.jpg",
                "verified_email": True,
            }
        ).encode()
        mock_response = MagicMock()
        mock_response.read.return_value = user_data
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            patch(
                "aragora.server.handlers._oauth.google.urllib_request.urlopen",
                return_value=mock_response,
            ),
        ):
            result = handler._get_google_user_info("access-token")

        assert isinstance(result, OAuthUserInfo)
        assert result.provider == "google"
        assert result.provider_user_id == "goog-42"
        assert result.email == "bob@example.com"
        assert result.name == "Bob"
        assert result.picture == "https://example.com/bob.jpg"
        assert result.email_verified is True

    def test_sync_path_name_fallback_to_email_prefix(self, handler, impl):
        """When name is missing, falls back to email prefix."""
        user_data = json.dumps(
            {
                "id": "goog-42",
                "email": "charlie@example.com",
                "verified_email": False,
            }
        ).encode()
        mock_response = MagicMock()
        mock_response.read.return_value = user_data
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            patch(
                "aragora.server.handlers._oauth.google.urllib_request.urlopen",
                return_value=mock_response,
            ),
        ):
            result = handler._get_google_user_info("access-token")

        assert result.name == "charlie"
        assert result.email_verified is False

    def test_sync_path_invalid_json_raises(self, handler, impl):
        """Invalid JSON from userinfo endpoint raises ValueError."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"<html>error</html>"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            patch(
                "aragora.server.handlers._oauth.google.urllib_request.urlopen",
                return_value=mock_response,
            ),
        ):
            with pytest.raises(ValueError, match="Invalid JSON"):
                handler._get_google_user_info("access-token")

    @pytest.mark.asyncio
    async def test_async_path_returns_user_info(self, handler, impl):
        """Async path returns OAuthUserInfo from Google response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "goog-77",
            "email": "dana@example.com",
            "name": "Dana",
            "picture": "https://example.com/dana.jpg",
            "verified_email": True,
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.google.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_google_user_info("access-token")
            if asyncio.iscoroutine(result):
                info = await result
            else:
                info = result

        assert isinstance(info, OAuthUserInfo)
        assert info.provider == "google"
        assert info.provider_user_id == "goog-77"
        assert info.email == "dana@example.com"
        assert info.name == "Dana"

    @pytest.mark.asyncio
    async def test_async_path_name_fallback(self, handler, impl):
        """Async path falls back name to email prefix when not provided."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "goog-88",
            "email": "eve@example.com",
            "verified_email": False,
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.google.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_google_user_info("access-token")
            if asyncio.iscoroutine(result):
                info = await result
            else:
                info = result

        assert info.name == "eve"

    @pytest.mark.asyncio
    async def test_async_path_invalid_json_raises(self, handler, impl):
        """Invalid JSON from Google userinfo in async path raises ValueError."""
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("err", "doc", 0)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.google.httpx.AsyncClient", return_value=mock_client
        ):
            result = handler._get_google_user_info("access-token")
            if asyncio.iscoroutine(result):
                with pytest.raises(ValueError, match="Invalid JSON"):
                    await result


# ===========================================================================
# Edge cases and integration
# ===========================================================================


class TestEdgeCases:
    """Additional edge-case and integration tests."""

    @pytest.fixture(autouse=True)
    def _patch_audit(self):
        with (
            patch("aragora.server.handlers._oauth.google.audit_action"),
            patch("aragora.server.handlers._oauth.google.audit_security"),
        ):
            yield

    def test_query_param_as_list(self, handler, impl, mock_http_handler):
        """Query parameters provided as lists are handled correctly."""
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = handler._handle_google_auth_start(
                mock_http_handler,
                {"redirect_url": ["https://app.example.com/done"]},
            )

        assert _status(result) == 302

    def test_token_key_error_returns_error(self, handler, impl, mock_http_handler):
        """KeyError during token creation returns error with type name."""
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        info = OAuthUserInfo(
            provider="google",
            provider_user_id="goog-1",
            email="a@b.com",
            name="A",
            email_verified=True,
        )
        handler._get_google_user_info = MagicMock(return_value=info)
        handler._user_store.find_by_oauth.return_value = user
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            side_effect=KeyError("missing"),
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        assert _status(result) == 302
        assert "KeyError" in handler._error_messages[0]

    def test_token_type_error_returns_error(self, handler, impl, mock_http_handler):
        """TypeError during token creation returns error with type name."""
        user = _MockUser()
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        info = OAuthUserInfo(
            provider="google",
            provider_user_id="goog-1",
            email="a@b.com",
            name="A",
            email_verified=True,
        )
        handler._get_google_user_info = MagicMock(return_value=info)
        handler._user_store.find_by_oauth.return_value = user
        handler._user_store.update_user = MagicMock()

        with patch(
            "aragora.billing.jwt_auth.create_token_pair",
            side_effect=TypeError("wrong type"),
        ):
            result = asyncio.run(
                handler._handle_google_callback.__wrapped__.__wrapped__(
                    handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
                )
            )

        assert _status(result) == 302
        assert "TypeError" in handler._error_messages[0]

    def test_user_info_key_error_returns_error(self, handler, impl, mock_http_handler):
        """KeyError during user info fetch redirects with error."""
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(side_effect=KeyError("id"))

        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    def test_user_info_value_error_returns_error(self, handler, impl, mock_http_handler):
        """ValueError during user info fetch redirects with error."""
        handler._exchange_code_for_tokens = MagicMock(return_value={"access_token": "tok"})
        handler._get_google_user_info = MagicMock(side_effect=ValueError("bad data"))

        result = asyncio.run(
            handler._handle_google_callback.__wrapped__.__wrapped__(
                handler, mock_http_handler, {"state": "valid", "code": "auth-code"}
            )
        )
        assert _status(result) == 302
        assert "Failed to get user info" in handler._error_messages[0]

    def test_exchange_code_sends_correct_data(self, handler, impl):
        """_exchange_code_for_tokens sends correct form data to Google."""
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
                "aragora.server.handlers._oauth.google.urllib_request.urlopen",
                side_effect=mock_urlopen,
            ),
        ):
            result = handler._exchange_code_for_tokens("my-auth-code")

        assert captured_req["url"] == "https://oauth2.googleapis.com/token"
        data_str = captured_req["data"].decode("utf-8")
        assert "code=my-auth-code" in data_str
        assert "client_id=test-client-id" in data_str
        assert "grant_type=authorization_code" in data_str
        assert captured_req["headers"]["Content-type"] == "application/x-www-form-urlencoded"

    def test_get_user_info_sends_bearer_token(self, handler, impl):
        """_get_google_user_info sends correct Authorization header."""
        captured_req = {}

        def mock_urlopen(req):
            captured_req["url"] = req.full_url
            captured_req["headers"] = dict(req.headers)
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(
                {
                    "id": "goog-1",
                    "email": "x@y.com",
                }
            ).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with (
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            patch(
                "aragora.server.handlers._oauth.google.urllib_request.urlopen",
                side_effect=mock_urlopen,
            ),
        ):
            result = handler._get_google_user_info("my-bearer-token")

        assert captured_req["url"] == "https://www.googleapis.com/oauth2/v2/userinfo"
        assert captured_req["headers"]["Authorization"] == "Bearer my-bearer-token"
