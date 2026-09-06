"""Tests for aragora/server/handlers/_oauth/apple.py.

Covers the AppleOAuthMixin:
- _handle_apple_auth_start: redirect to Apple consent screen, client ID checks,
  redirect URL validation, state generation, authenticated user inclusion
- _handle_apple_callback: error from Apple, state validation, missing code/id_token,
  form_post body parsing, code exchange, id_token parsing, user data extraction,
  _complete_oauth_flow invocation
- _exchange_apple_code: urllib token exchange, client secret generation
- _generate_apple_client_secret: PyJWT usage, missing config errors
- _parse_apple_id_token: JWT payload decoding, user data parsing, email extraction,
  name extraction with fallback
"""

from __future__ import annotations

import base64
import json
import sys
import time
from dataclasses import dataclass
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers._oauth.apple import AppleOAuthMixin
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


def _make_apple_id_token(
    email: str = "alice@example.com",
    sub: str = "apple-user-001",
    email_verified: bool | str = True,
) -> str:
    """Build a fake 3-part Apple ID token (header.payload.signature)."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=").decode()
    payload_data = {
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
    }
    payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(b"fake-signature").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


# ---------------------------------------------------------------------------
# Mock _oauth_impl module
# ---------------------------------------------------------------------------


_IMPL_MODULE = "aragora.server.handlers.oauth._oauth_impl"


def _make_impl(**overrides: Any) -> ModuleType:
    """Build a fake _oauth_impl module with sensible defaults."""
    mod = ModuleType(_IMPL_MODULE)
    mod.APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"
    mod.APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
    mod._get_apple_client_id = lambda: "com.example.app"
    mod._get_apple_redirect_uri = lambda: "http://localhost:8080/callback/apple"
    mod._get_apple_team_id = lambda: "TEAM123"
    mod._get_apple_key_id = lambda: "KEY456"
    mod._get_apple_private_key = (
        lambda: "-----BEGIN EC PRIVATE KEY-----\nfake\n-----END EC PRIVATE KEY-----"
    )
    mod._get_oauth_success_url = lambda: "http://localhost:3000/auth/success"
    mod._get_oauth_error_url = lambda: "http://localhost:3000/auth/error"
    mod._validate_redirect_url = lambda url: True
    mod._generate_state = lambda user_id=None, redirect_url=None: "mock-state-token"
    mod._validate_state = lambda state: {"redirect_url": "http://localhost:3000/auth/success"}
    for k, v in overrides.items():
        setattr(mod, k, v)
    return mod


# ---------------------------------------------------------------------------
# Concrete test class mixing in AppleOAuthMixin
# ---------------------------------------------------------------------------


class _TestAppleHandler(AppleOAuthMixin):
    """Concrete class that mixes in AppleOAuthMixin for testing."""

    def __init__(self) -> None:
        self._user_store = MagicMock()
        self._error_messages: list[str] = []
        self._complete_oauth_flow_calls: list[tuple] = []

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

    def _complete_oauth_flow(self, user_info: OAuthUserInfo, state_data: dict) -> HandlerResult:
        self._complete_oauth_flow_calls.append((user_info, state_data))
        return HandlerResult(
            status_code=302,
            content_type="text/html",
            body=b"oauth-flow-complete",
            headers={"Location": "http://localhost:3000/auth/success"},
        )

    def _maybe_await(self, value: Any) -> Any:
        return value


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    return _TestAppleHandler()


@pytest.fixture()
def mock_http_handler():
    h = MagicMock()
    h.command = "GET"
    h.headers = {}
    # Apple callback reads from handler.request.body for form_post
    h.request = MagicMock()
    h.request.body = None
    return h


# ===========================================================================
# _handle_apple_auth_start
# ===========================================================================


class TestAppleAuthStart:
    """Tests for _handle_apple_auth_start."""

    def test_returns_redirect_to_apple(self, handler, impl, mock_http_handler):
        """Auth start returns a 302 with Location to Apple auth URL."""
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = handler._handle_apple_auth_start(mock_http_handler, {})

        assert _status(result) == 302
        loc = result.headers["Location"]
        assert loc.startswith("https://appleid.apple.com/auth/authorize?")
        assert "client_id=com.example.app" in loc
        assert "response_type=code+id_token" in loc or "response_type=code%20id_token" in loc
        assert "scope=name+email" in loc or "scope=name%20email" in loc
        assert "state=mock-state-token" in loc
        assert "response_mode=form_post" in loc

    def test_apple_not_configured_returns_503(self, handler, mock_http_handler):
        """Returns 503 when Apple client ID is not configured."""
        mod = _make_impl(**{"_get_apple_client_id": lambda: None})
        sys.modules[_IMPL_MODULE] = mod
        try:
            result = handler._handle_apple_auth_start(mock_http_handler, {})
            assert _status(result) == 503
            body = _body(result)
            assert "not configured" in body.get("error", body.get("raw", "")).lower()
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    def test_empty_client_id_returns_503(self, handler, mock_http_handler):
        """Returns 503 when Apple client ID is empty string."""
        mod = _make_impl(**{"_get_apple_client_id": lambda: ""})
        sys.modules[_IMPL_MODULE] = mod
        try:
            result = handler._handle_apple_auth_start(mock_http_handler, {})
            assert _status(result) == 503
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    def test_invalid_redirect_url_returns_400(self, handler, impl, mock_http_handler):
        """Returns 400 when redirect_url fails validation."""
        impl._validate_redirect_url = lambda url: False
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = handler._handle_apple_auth_start(
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
            handler._handle_apple_auth_start(
                mock_http_handler, {"redirect_url": "https://app.example.com/done"}
            )

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
            handler._handle_apple_auth_start(mock_http_handler, {})

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
            handler._handle_apple_auth_start(mock_http_handler, {})

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
            handler._handle_apple_auth_start(mock_http_handler, {})

        assert captured["redirect_url"] == "http://localhost:3000/auth/success"

    def test_redirect_body_contains_meta_refresh(self, handler, impl, mock_http_handler):
        """Response body contains a meta refresh tag as fallback."""
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = handler._handle_apple_auth_start(mock_http_handler, {})

        assert b"meta http-equiv" in result.body

    def test_redirect_uri_included_in_params(self, handler, impl, mock_http_handler):
        """Authorization URL includes the configured redirect URI."""
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = handler._handle_apple_auth_start(mock_http_handler, {})

        loc = result.headers["Location"]
        assert "redirect_uri=" in loc
        assert "localhost" in loc

    def test_query_param_as_list(self, handler, impl, mock_http_handler):
        """Query parameters provided as lists are handled correctly."""
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = MagicMock(is_authenticated=False)
            result = handler._handle_apple_auth_start(
                mock_http_handler,
                {"redirect_url": ["https://app.example.com/done"]},
            )

        assert _status(result) == 302


# ===========================================================================
# _handle_apple_callback
# ===========================================================================


class TestAppleCallback:
    """Tests for _handle_apple_callback."""

    def test_error_from_apple_redirects_with_error(self, handler, impl, mock_http_handler):
        """Apple error parameter triggers redirect with error."""
        result = handler._handle_apple_callback(mock_http_handler, {"error": "access_denied"})
        assert _status(result) == 302
        assert len(handler._error_messages) == 1
        assert "access_denied" in handler._error_messages[0]

    def test_missing_state_returns_error(self, handler, impl, mock_http_handler):
        """Missing state parameter triggers redirect with error."""
        result = handler._handle_apple_callback(mock_http_handler, {"code": "auth-code"})
        assert _status(result) == 302
        assert "Missing state" in handler._error_messages[0]

    def test_invalid_state_returns_error(self, handler, impl, mock_http_handler):
        """Invalid/expired state triggers redirect with error."""
        impl._validate_state = lambda state: None
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "bad-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Invalid or expired" in handler._error_messages[0]

    def test_missing_code_and_id_token_returns_error(self, handler, impl, mock_http_handler):
        """Missing both authorization code and id_token triggers redirect with error."""
        result = handler._handle_apple_callback(mock_http_handler, {"state": "valid-state"})
        assert _status(result) == 302
        assert (
            "Missing authorization code" in handler._error_messages[0]
            or "id_token" in handler._error_messages[0]
        )

    def test_successful_callback_with_code(self, handler, impl, mock_http_handler):
        """Successful callback with authorization code exchanges and completes flow."""
        id_token = _make_apple_id_token()
        handler._exchange_apple_code = MagicMock(return_value={"id_token": id_token})
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert len(handler._complete_oauth_flow_calls) == 1
        user_info, state_data = handler._complete_oauth_flow_calls[0]
        assert user_info.provider == "apple"
        assert user_info.email == "alice@example.com"

    def test_successful_callback_with_id_token_only(self, handler, impl, mock_http_handler):
        """Successful callback with only id_token (no code) still completes flow."""
        id_token = _make_apple_id_token(email="bob@example.com", sub="apple-bob")
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "id_token": id_token}
        )
        assert _status(result) == 302
        assert len(handler._complete_oauth_flow_calls) == 1
        user_info, _ = handler._complete_oauth_flow_calls[0]
        assert user_info.email == "bob@example.com"
        assert user_info.provider_user_id == "apple-bob"

    def test_code_exchange_failure_returns_error(self, handler, impl, mock_http_handler):
        """ConnectionError during code exchange triggers redirect with error."""
        handler._exchange_apple_code = MagicMock(side_effect=ConnectionError("network down"))
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to process" in handler._error_messages[0]

    def test_code_exchange_timeout_returns_error(self, handler, impl, mock_http_handler):
        """TimeoutError during code exchange triggers redirect with error."""
        handler._exchange_apple_code = MagicMock(side_effect=TimeoutError("timed out"))
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to process" in handler._error_messages[0]

    def test_code_exchange_os_error_returns_error(self, handler, impl, mock_http_handler):
        """OSError during code exchange triggers redirect with error."""
        handler._exchange_apple_code = MagicMock(side_effect=OSError("network unreachable"))
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to process" in handler._error_messages[0]

    def test_code_exchange_value_error_returns_error(self, handler, impl, mock_http_handler):
        """ValueError during code exchange triggers redirect with error."""
        handler._exchange_apple_code = MagicMock(side_effect=ValueError("bad config"))
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to process" in handler._error_messages[0]

    def test_code_exchange_key_error_returns_error(self, handler, impl, mock_http_handler):
        """KeyError during code exchange triggers redirect with error."""
        handler._exchange_apple_code = MagicMock(side_effect=KeyError("missing key"))
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to process" in handler._error_messages[0]

    def test_code_exchange_json_decode_error_returns_error(self, handler, impl, mock_http_handler):
        """json.JSONDecodeError during code exchange triggers redirect with error."""
        handler._exchange_apple_code = MagicMock(side_effect=json.JSONDecodeError("bad", "", 0))
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to process" in handler._error_messages[0]

    def test_code_exchange_import_error_returns_error(self, handler, impl, mock_http_handler):
        """ImportError during code exchange (missing PyJWT) triggers redirect with error."""
        handler._exchange_apple_code = MagicMock(side_effect=ImportError("No module named 'jwt'"))
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        assert "Failed to process" in handler._error_messages[0]

    def test_id_token_parse_failure_returns_error(self, handler, impl, mock_http_handler):
        """ValueError from _parse_apple_id_token triggers redirect with error."""
        # Provide an invalid id_token (not 3 parts)
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "id_token": "invalid-token"}
        )
        assert _status(result) == 302
        assert "Failed to process" in handler._error_messages[0]

    def test_form_post_body_parsing(self, handler, impl, mock_http_handler):
        """Apple form_post body data is parsed and merged with query params."""
        id_token = _make_apple_id_token()
        # Set up form body with code and state
        form_data = f"code=form-auth-code&state=form-state&id_token={id_token}"
        mock_http_handler.request.body = form_data.encode()

        handler._exchange_apple_code = MagicMock(return_value={"id_token": id_token})

        result = handler._handle_apple_callback(mock_http_handler, {})
        assert _status(result) == 302
        assert len(handler._complete_oauth_flow_calls) == 1

    def test_form_body_overrides_query_params(self, handler, impl, mock_http_handler):
        """POST body parameters override query parameters."""
        id_token = _make_apple_id_token(email="form@example.com")
        form_data = f"state=form-state&id_token={id_token}"
        mock_http_handler.request.body = form_data.encode()

        result = handler._handle_apple_callback(mock_http_handler, {"state": "query-state"})
        assert _status(result) == 302
        assert len(handler._complete_oauth_flow_calls) == 1
        user_info, _ = handler._complete_oauth_flow_calls[0]
        assert user_info.email == "form@example.com"

    def test_no_request_body_graceful(self, handler, impl, mock_http_handler):
        """When handler.request.body is None, only query params are used."""
        mock_http_handler.request.body = None
        id_token = _make_apple_id_token()
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "id_token": id_token}
        )
        assert _status(result) == 302
        assert len(handler._complete_oauth_flow_calls) == 1

    def test_no_request_attr_graceful(self, handler, impl, mock_http_handler):
        """When handler has no request attribute, only query params are used."""
        del mock_http_handler.request
        id_token = _make_apple_id_token()
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "id_token": id_token}
        )
        assert _status(result) == 302
        assert len(handler._complete_oauth_flow_calls) == 1

    def test_user_data_json_parsed(self, handler, impl, mock_http_handler):
        """Apple user data JSON is parsed and passed to _parse_apple_id_token."""
        id_token = _make_apple_id_token()
        user_data = json.dumps({"name": {"firstName": "Jane", "lastName": "Doe"}})
        mock_http_handler.request.body = (
            f"state=valid&id_token={id_token}&user={user_data}".encode()
        )

        result = handler._handle_apple_callback(mock_http_handler, {})
        assert _status(result) == 302
        assert len(handler._complete_oauth_flow_calls) == 1
        user_info, _ = handler._complete_oauth_flow_calls[0]
        assert user_info.name == "Jane Doe"

    def test_invalid_user_data_json_handled_gracefully(self, handler, impl, mock_http_handler):
        """Invalid JSON in user data field doesn't crash, defaults to empty dict."""
        id_token = _make_apple_id_token()
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid", "id_token": id_token, "user": "not-valid-json{"}
        )
        assert _status(result) == 302
        assert len(handler._complete_oauth_flow_calls) == 1
        # Name should fallback to email prefix since user_data is empty
        user_info, _ = handler._complete_oauth_flow_calls[0]
        assert user_info.name == "alice"

    def test_empty_user_data_handled(self, handler, impl, mock_http_handler):
        """Empty string user data defaults to empty dict."""
        id_token = _make_apple_id_token()
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid", "id_token": id_token, "user": ""}
        )
        assert _status(result) == 302
        assert len(handler._complete_oauth_flow_calls) == 1

    def test_code_exchange_provides_id_token_to_parser(self, handler, impl, mock_http_handler):
        """When code is present, exchanged id_token is used for parsing."""
        exchanged_token = _make_apple_id_token(email="exchanged@example.com")
        handler._exchange_apple_code = MagicMock(return_value={"id_token": exchanged_token})
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid-state", "code": "auth-code"}
        )
        assert _status(result) == 302
        user_info, _ = handler._complete_oauth_flow_calls[0]
        assert user_info.email == "exchanged@example.com"

    def test_code_exchange_no_id_token_uses_original(self, handler, impl, mock_http_handler):
        """When code exchange returns no id_token, the original id_token from params is used."""
        original_token = _make_apple_id_token(email="original@example.com")
        handler._exchange_apple_code = MagicMock(
            return_value={"access_token": "some-token"}  # No id_token key
        )
        result = handler._handle_apple_callback(
            mock_http_handler,
            {"state": "valid-state", "code": "auth-code", "id_token": original_token},
        )
        assert _status(result) == 302
        user_info, _ = handler._complete_oauth_flow_calls[0]
        assert user_info.email == "original@example.com"

    def test_state_data_passed_to_complete_flow(self, handler, impl, mock_http_handler):
        """State data from validation is passed to _complete_oauth_flow."""
        impl._validate_state = lambda state: {
            "redirect_url": "https://custom.example.com/done",
            "user_id": "existing-user-123",
        }
        id_token = _make_apple_id_token()
        result = handler._handle_apple_callback(
            mock_http_handler, {"state": "valid", "id_token": id_token}
        )
        assert _status(result) == 302
        _, state_data = handler._complete_oauth_flow_calls[0]
        assert state_data["redirect_url"] == "https://custom.example.com/done"
        assert state_data["user_id"] == "existing-user-123"


# ===========================================================================
# _exchange_apple_code
# ===========================================================================


class TestExchangeAppleCode:
    """Tests for _exchange_apple_code."""

    def test_exchange_sends_correct_data(self, handler, impl):
        """_exchange_apple_code sends correct form data to Apple."""
        handler._generate_apple_client_secret = MagicMock(return_value="client-secret-jwt")

        captured_req = {}
        token_response = json.dumps({"id_token": "tok.abc.def"}).encode()
        mock_response = MagicMock()
        mock_response.read.return_value = token_response
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        def mock_urlopen(req):
            captured_req["url"] = req.full_url
            captured_req["data"] = req.data
            captured_req["headers"] = dict(req.headers)
            return mock_response

        with patch(
            "aragora.server.handlers._oauth.apple.urlopen",
            side_effect=mock_urlopen,
        ):
            result = handler._exchange_apple_code("my-auth-code")

        assert captured_req["url"] == "https://appleid.apple.com/auth/token"
        data_str = captured_req["data"].decode("utf-8")
        assert "code=my-auth-code" in data_str
        assert "client_id=com.example.app" in data_str
        assert "client_secret=client-secret-jwt" in data_str
        assert "grant_type=authorization_code" in data_str
        assert captured_req["headers"]["Content-type"] == "application/x-www-form-urlencoded"
        assert result == {"id_token": "tok.abc.def"}

    def test_exchange_empty_response_returns_empty_dict(self, handler, impl):
        """Empty response body returns empty dict."""
        handler._generate_apple_client_secret = MagicMock(return_value="secret")
        mock_response = MagicMock()
        mock_response.read.return_value = b""
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "aragora.server.handlers._oauth.apple.urlopen",
            return_value=mock_response,
        ):
            result = handler._exchange_apple_code("code")
        assert result == {}

    def test_exchange_includes_redirect_uri(self, handler, impl):
        """Exchange sends configured redirect_uri."""
        handler._generate_apple_client_secret = MagicMock(return_value="secret")

        captured_data = {}
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"id_token": "t"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        def mock_urlopen(req):
            captured_data["data"] = req.data.decode("utf-8")
            return mock_response

        with patch(
            "aragora.server.handlers._oauth.apple.urlopen",
            side_effect=mock_urlopen,
        ):
            handler._exchange_apple_code("code")

        assert "redirect_uri=" in captured_data["data"]
        assert "localhost" in captured_data["data"]


# ===========================================================================
# _generate_apple_client_secret
# ===========================================================================


class TestGenerateAppleClientSecret:
    """Tests for _generate_apple_client_secret."""

    def test_generates_jwt_with_correct_claims(self, handler, impl):
        """Generated JWT has correct claims."""
        mock_jwt = MagicMock()
        mock_jwt.encode.return_value = "encoded-jwt-token"

        with patch.dict(sys.modules, {"jwt": mock_jwt}):
            result = handler._generate_apple_client_secret()

        assert result == "encoded-jwt-token"
        call_args = mock_jwt.encode.call_args
        payload = call_args[0][0]
        private_key = call_args[0][1]
        algorithm = call_args[1]["algorithm"] if "algorithm" in call_args[1] else call_args[0][2]
        headers = call_args[1]["headers"]

        assert payload["iss"] == "TEAM123"
        assert payload["aud"] == "https://appleid.apple.com"
        assert payload["sub"] == "com.example.app"
        assert "iat" in payload
        assert "exp" in payload
        # Expiry should be ~180 days
        assert payload["exp"] - payload["iat"] == 86400 * 180
        assert algorithm == "ES256"
        assert headers["kid"] == "KEY456"
        assert "BEGIN EC PRIVATE KEY" in private_key

    def test_missing_pyjwt_raises_value_error(self, handler, impl):
        """Missing PyJWT module raises ValueError with install instructions."""
        with patch.dict(sys.modules, {"jwt": None}):
            # Force re-import to trigger ImportError
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError())
                if name == "jwt"
                else __import__(name, *args, **kwargs),
            ):
                with pytest.raises(ValueError, match="PyJWT"):
                    handler._generate_apple_client_secret()

    def test_missing_team_id_raises_value_error(self, handler, mock_http_handler):
        """Missing team_id raises ValueError."""
        mod = _make_impl(**{"_get_apple_team_id": lambda: None})
        sys.modules[_IMPL_MODULE] = mod
        try:
            mock_jwt = MagicMock()
            with patch.dict(sys.modules, {"jwt": mock_jwt}):
                with pytest.raises(ValueError, match="not fully configured"):
                    handler._generate_apple_client_secret()
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    def test_missing_key_id_raises_value_error(self, handler, mock_http_handler):
        """Missing key_id raises ValueError."""
        mod = _make_impl(**{"_get_apple_key_id": lambda: None})
        sys.modules[_IMPL_MODULE] = mod
        try:
            mock_jwt = MagicMock()
            with patch.dict(sys.modules, {"jwt": mock_jwt}):
                with pytest.raises(ValueError, match="not fully configured"):
                    handler._generate_apple_client_secret()
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    def test_missing_private_key_raises_value_error(self, handler, mock_http_handler):
        """Missing private_key raises ValueError."""
        mod = _make_impl(**{"_get_apple_private_key": lambda: None})
        sys.modules[_IMPL_MODULE] = mod
        try:
            mock_jwt = MagicMock()
            with patch.dict(sys.modules, {"jwt": mock_jwt}):
                with pytest.raises(ValueError, match="not fully configured"):
                    handler._generate_apple_client_secret()
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    def test_missing_client_id_raises_value_error(self, handler, mock_http_handler):
        """Missing client_id raises ValueError."""
        mod = _make_impl(**{"_get_apple_client_id": lambda: None})
        sys.modules[_IMPL_MODULE] = mod
        try:
            mock_jwt = MagicMock()
            with patch.dict(sys.modules, {"jwt": mock_jwt}):
                with pytest.raises(ValueError, match="not fully configured"):
                    handler._generate_apple_client_secret()
        finally:
            sys.modules.pop(_IMPL_MODULE, None)

    def test_iat_is_current_time(self, handler, impl):
        """iat claim is set to current time."""
        mock_jwt = MagicMock()
        mock_jwt.encode.return_value = "jwt"
        now = int(time.time())

        with patch.dict(sys.modules, {"jwt": mock_jwt}):
            handler._generate_apple_client_secret()

        payload = mock_jwt.encode.call_args[0][0]
        # Allow 5 seconds tolerance
        assert abs(payload["iat"] - now) < 5


# ===========================================================================
# _parse_apple_id_token
# ===========================================================================


class TestParseAppleIdToken:
    """Tests for _parse_apple_id_token."""

    def test_parses_valid_token(self, handler, impl):
        """Parses a valid 3-part Apple ID token."""
        token = _make_apple_id_token(
            email="alice@example.com",
            sub="apple-123",
            email_verified=True,
        )
        result = handler._parse_apple_id_token(token, {})
        assert isinstance(result, OAuthUserInfo)
        assert result.provider == "apple"
        assert result.provider_user_id == "apple-123"
        assert result.email == "alice@example.com"
        assert result.email_verified is True
        assert result.picture is None

    def test_invalid_token_format_raises(self, handler, impl):
        """Token with wrong number of parts raises ValueError."""
        with pytest.raises(ValueError, match="Invalid Apple ID token"):
            handler._parse_apple_id_token("only-one-part", {})

    def test_two_part_token_raises(self, handler, impl):
        """Token with only 2 parts raises ValueError."""
        with pytest.raises(ValueError, match="Invalid Apple ID token"):
            handler._parse_apple_id_token("part1.part2", {})

    def test_four_part_token_raises(self, handler, impl):
        """Token with 4 parts raises ValueError."""
        with pytest.raises(ValueError, match="Invalid Apple ID token"):
            handler._parse_apple_id_token("a.b.c.d", {})

    def test_missing_email_raises(self, handler, impl):
        """Token without email raises ValueError."""
        token = _make_apple_id_token(email="")
        # The token has email="" which is falsy
        with pytest.raises(ValueError, match="No email"):
            handler._parse_apple_id_token(token, {})

    def test_name_from_user_data(self, handler, impl):
        """Name is extracted from Apple user data (first auth only)."""
        token = _make_apple_id_token()
        user_data = {"name": {"firstName": "Jane", "lastName": "Doe"}}
        result = handler._parse_apple_id_token(token, user_data)
        assert result.name == "Jane Doe"

    def test_name_first_only(self, handler, impl):
        """Name with only firstName is properly handled."""
        token = _make_apple_id_token()
        user_data = {"name": {"firstName": "Jane"}}
        result = handler._parse_apple_id_token(token, user_data)
        assert result.name == "Jane"

    def test_name_last_only(self, handler, impl):
        """Name with only lastName is properly handled."""
        token = _make_apple_id_token()
        user_data = {"name": {"lastName": "Doe"}}
        result = handler._parse_apple_id_token(token, user_data)
        assert result.name == "Doe"

    def test_name_fallback_to_email_prefix(self, handler, impl):
        """When no name data, falls back to email prefix."""
        token = _make_apple_id_token(email="charlie@example.com")
        result = handler._parse_apple_id_token(token, {})
        assert result.name == "charlie"

    def test_name_empty_user_data(self, handler, impl):
        """Empty user_data name object falls back to email prefix."""
        token = _make_apple_id_token(email="delta@example.com")
        result = handler._parse_apple_id_token(token, {"name": {}})
        assert result.name == "delta"

    def test_email_verified_as_string_true(self, handler, impl):
        """email_verified as string 'true' is parsed correctly."""
        token = _make_apple_id_token(email_verified="true")
        result = handler._parse_apple_id_token(token, {})
        assert result.email_verified is True

    def test_email_verified_as_string_false(self, handler, impl):
        """email_verified as string 'false' is parsed correctly."""
        token = _make_apple_id_token(email_verified="false")
        result = handler._parse_apple_id_token(token, {})
        assert result.email_verified is False

    def test_email_verified_as_bool_true(self, handler, impl):
        """email_verified as boolean True is parsed correctly."""
        token = _make_apple_id_token(email_verified=True)
        result = handler._parse_apple_id_token(token, {})
        assert result.email_verified is True

    def test_email_verified_as_bool_false(self, handler, impl):
        """email_verified as boolean False is parsed correctly."""
        token = _make_apple_id_token(email_verified=False)
        result = handler._parse_apple_id_token(token, {})
        assert result.email_verified is False

    def test_sub_used_as_provider_user_id(self, handler, impl):
        """sub claim from token is used as provider_user_id."""
        token = _make_apple_id_token(sub="unique-apple-sub-789")
        result = handler._parse_apple_id_token(token, {})
        assert result.provider_user_id == "unique-apple-sub-789"

    def test_base64_padding_handled(self, handler, impl):
        """Base64 payload with non-standard padding is decoded correctly."""
        # Create a payload that requires padding
        token = _make_apple_id_token(
            email="padtest@example.com",
            sub="pad-sub",
        )
        result = handler._parse_apple_id_token(token, {})
        assert result.email == "padtest@example.com"

    def test_no_name_in_user_data_key(self, handler, impl):
        """User data without 'name' key at all falls back to email prefix."""
        token = _make_apple_id_token(email="nokey@example.com")
        result = handler._parse_apple_id_token(token, {"other": "data"})
        assert result.name == "nokey"

    def test_provider_always_apple(self, handler, impl):
        """Provider is always set to 'apple'."""
        token = _make_apple_id_token()
        result = handler._parse_apple_id_token(token, {})
        assert result.provider == "apple"

    def test_picture_always_none(self, handler, impl):
        """Picture is always None (Apple doesn't provide profile pictures)."""
        token = _make_apple_id_token()
        result = handler._parse_apple_id_token(token, {})
        assert result.picture is None

    def test_missing_sub_defaults_to_empty(self, handler, impl):
        """Missing sub claim defaults to empty string."""
        header = (
            base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=").decode()
        )
        payload_data = {"email": "nosub@example.com", "email_verified": True}
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        sig = base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode()
        token = f"{header}.{payload}.{sig}"

        result = handler._parse_apple_id_token(token, {})
        assert result.provider_user_id == ""


# ===========================================================================
# Integration-style tests via OAuthHandler.handle()
# ===========================================================================


class TestHandleRouting:
    """Tests that the Apple endpoints are routed through OAuthHandler.handle()."""

    @pytest.fixture()
    def oauth_handler(self, impl):
        """Create an OAuthHandler with mock context."""
        # Add rate limiter and tracing stubs
        limiter = MagicMock()
        limiter.is_allowed = MagicMock(return_value=True)
        impl._oauth_limiter = limiter
        impl.create_span = MagicMock()
        impl.add_span_attributes = MagicMock()
        # Create a context manager for create_span
        span_mock = MagicMock()
        impl.create_span.return_value.__enter__ = MagicMock(return_value=span_mock)
        impl.create_span.return_value.__exit__ = MagicMock(return_value=False)

        from aragora.server.handlers._oauth.base import OAuthHandler

        ctx = {"user_store": MagicMock()}
        h = OAuthHandler(ctx)
        return h

    @pytest.fixture()
    def mock_http_handler_for_routing(self):
        h = MagicMock()
        h.command = "GET"
        h.headers = {}
        h.client_address = ("127.0.0.1", 12345)
        h.request = MagicMock()
        h.request.body = None
        return h

    def test_apple_auth_start_routed_v1(self, oauth_handler, impl, mock_http_handler_for_routing):
        """GET /api/v1/auth/oauth/apple routes to Apple auth start."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=MagicMock(is_authenticated=False),
        ):
            result = oauth_handler.handle(
                "/api/v1/auth/oauth/apple", {}, mock_http_handler_for_routing, "GET"
            )
        assert _status(result) == 302

    def test_apple_auth_start_routed_non_v1(
        self, oauth_handler, impl, mock_http_handler_for_routing
    ):
        """GET /api/auth/oauth/apple routes to Apple auth start."""
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=MagicMock(is_authenticated=False),
        ):
            result = oauth_handler.handle(
                "/api/auth/oauth/apple", {}, mock_http_handler_for_routing, "GET"
            )
        assert _status(result) == 302

    def test_apple_callback_routed_v1_get(self, oauth_handler, impl, mock_http_handler_for_routing):
        """GET /api/v1/auth/oauth/apple/callback routes to callback handler."""
        result = oauth_handler.handle(
            "/api/v1/auth/oauth/apple/callback",
            {"error": "access_denied"},
            mock_http_handler_for_routing,
            "GET",
        )
        assert _status(result) == 302

    def test_apple_callback_routed_v1_post(
        self, oauth_handler, impl, mock_http_handler_for_routing
    ):
        """POST /api/v1/auth/oauth/apple/callback routes to callback handler (form_post)."""
        mock_http_handler_for_routing.command = "POST"
        result = oauth_handler.handle(
            "/api/v1/auth/oauth/apple/callback",
            {"error": "access_denied"},
            mock_http_handler_for_routing,
            "POST",
        )
        assert _status(result) == 302

    def test_apple_callback_routed_non_v1(self, oauth_handler, impl, mock_http_handler_for_routing):
        """GET /api/auth/oauth/apple/callback also routes correctly."""
        result = oauth_handler.handle(
            "/api/auth/oauth/apple/callback",
            {"error": "server_error"},
            mock_http_handler_for_routing,
            "GET",
        )
        assert _status(result) == 302

    def test_rate_limited_returns_429(self, oauth_handler, impl, mock_http_handler_for_routing):
        """When rate limiter denies request, returns 429."""
        impl._oauth_limiter.is_allowed = MagicMock(return_value=False)
        result = oauth_handler.handle(
            "/api/v1/auth/oauth/apple", {}, mock_http_handler_for_routing, "GET"
        )
        assert _status(result) == 429
