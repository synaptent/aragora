"""Tests for password handler functions (aragora/server/handlers/auth/password.py).

Covers all three password endpoints:
- POST /api/auth/password/change   -> handle_change_password
- POST /api/auth/password/forgot   -> handle_forgot_password
- POST /api/auth/password/reset    -> handle_reset_password

Tests exercise: success paths, permission checks, validation errors, user-not-found,
missing body fields, service unavailable, audit logging, rate limit token naming,
email sending logic, edge cases (whitespace, empty bodies, etc.).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.auth.password import (
    handle_change_password,
    handle_forgot_password,
    handle_reset_password,
    send_password_reset_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: object) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)  # type: ignore[attr-defined]


def _status(result: object) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code  # type: ignore[attr-defined]


class MockHTTPHandler:
    """Lightweight mock HTTP request handler."""

    def __init__(self, body: dict | None = None, method: str = "POST"):
        self.command = method
        self.client_address = ("127.0.0.1", 12345)
        self.headers: dict[str, str] = {
            "User-Agent": "test-agent",
            "Authorization": "Bearer test-token-abc",
        }
        self.rfile = MagicMock()
        if body is not None:
            body_bytes = json.dumps(body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers["Content-Length"] = str(len(body_bytes))
        else:
            self.rfile.read.return_value = b"{}"
            self.headers["Content-Length"] = "2"


@dataclass
class MockUser:
    """Mock user for user-store interactions."""

    id: str = "user-001"
    email: str = "test@example.com"
    name: str = "Test User"
    org_id: str | None = "org-001"
    role: str = "admin"
    is_active: bool = True
    mfa_enabled: bool = False
    mfa_secret: str | None = None
    mfa_backup_codes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "org_id": self.org_id,
            "role": self.role,
        }

    def verify_password(self, password: str) -> bool:
        return password == "correct-password"


@dataclass
class MockAuthCtx:
    """Mock auth context from extract_user_from_request."""

    is_authenticated: bool = True
    user_id: str = "user-001"
    email: str = "test@example.com"
    org_id: str = "org-001"
    role: str = "admin"
    client_ip: str = "127.0.0.1"


# A valid password that meets all requirements:
# >= 12 chars, uppercase, lowercase, digit, special char, not common
VALID_PASSWORD = "NewP@ssw0rd!2024"
VALID_PASSWORD_ALT = "An0ther$ecure!Pass"


def _make_user_store(user: MockUser | None = None):
    """Create a mock user store with standard methods."""
    store = MagicMock()
    u = user or MockUser()
    store.get_user_by_id.return_value = u
    store.get_user_by_email.return_value = u
    store.update_user.return_value = None
    store.increment_token_version.return_value = 2
    return store


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_password_deps(monkeypatch):
    """Patch dependencies common to all password handler functions."""
    mock_auth_ctx = MockAuthCtx()

    # Patch extract_user_from_request used by the proxy in password.py
    monkeypatch.setattr(
        "aragora.server.handlers.auth.password.extract_user_from_request",
        lambda handler, user_store: mock_auth_ctx,
    )

    # Patch emit_handler_event to no-op
    monkeypatch.setattr(
        "aragora.server.handlers.auth.password.emit_handler_event",
        lambda *args, **kwargs: None,
    )

    # Patch audit_security to no-op and mark available
    monkeypatch.setattr("aragora.server.handlers.auth.password.AUDIT_AVAILABLE", True)
    monkeypatch.setattr(
        "aragora.server.handlers.auth.password.audit_security",
        lambda **kwargs: None,
    )


@pytest.fixture
def handler_instance():
    """Create an AuthHandler-like object with mocked methods."""
    from aragora.server.handlers.auth.handler import AuthHandler

    store = _make_user_store()
    h = AuthHandler(server_context={"user_store": store})
    # Always grant permissions
    h._check_permission = MagicMock(return_value=None)
    return h, store


@pytest.fixture
def http():
    """Factory for creating mock HTTP handlers."""

    def _create(body: dict | None = None, method: str = "POST") -> MockHTTPHandler:
        return MockHTTPHandler(body=body, method=method)

    return _create


# =========================================================================
# handle_change_password
# =========================================================================


class TestChangePassword:
    """POST /api/auth/password/change."""

    @patch("aragora.billing.models.hash_password", return_value=("hashed_pw", "salt_val"))
    def test_success(self, mock_hash, handler_instance, http):
        hi, store = handler_instance
        user = MockUser()
        store.get_user_by_id.return_value = user

        result = handle_change_password(
            hi,
            http(body={"current_password": "correct-password", "new_password": VALID_PASSWORD}),
        )
        assert _status(result) == 200
        body = _body(result)
        assert "changed" in body["message"].lower()
        assert body["sessions_invalidated"] is True

    @patch("aragora.billing.models.hash_password", return_value=("new_hash_123", "new_salt_456"))
    def test_updates_password_hash(self, mock_hash, handler_instance, http):
        hi, store = handler_instance
        user = MockUser()
        store.get_user_by_id.return_value = user

        handle_change_password(
            hi,
            http(body={"current_password": "correct-password", "new_password": VALID_PASSWORD}),
        )
        store.update_user.assert_called_once_with(
            user.id,
            password_hash="new_hash_123",
            password_salt="new_salt_456",
        )

    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    def test_invalidates_sessions(self, mock_hash, handler_instance, http):
        hi, store = handler_instance
        user = MockUser()
        store.get_user_by_id.return_value = user

        handle_change_password(
            hi,
            http(body={"current_password": "correct-password", "new_password": VALID_PASSWORD}),
        )
        store.increment_token_version.assert_called_once_with(user.id)

    def test_permission_denied(self, handler_instance, http):
        from aragora.server.handlers.base import error_response

        hi, store = handler_instance
        hi._check_permission = MagicMock(return_value=error_response("Permission denied", 403))
        result = handle_change_password(
            hi,
            http(body={"current_password": "x", "new_password": VALID_PASSWORD}),
        )
        assert _status(result) == 403

    def test_invalid_json_body(self, handler_instance):
        hi, _ = handler_instance
        h = MockHTTPHandler()
        h.rfile.read.return_value = b"not json"
        h.headers["Content-Length"] = "8"
        result = handle_change_password(hi, h)
        assert _status(result) == 400

    def test_missing_current_password(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_change_password(hi, http(body={"new_password": VALID_PASSWORD}))
        assert _status(result) == 400
        assert "required" in _body(result)["error"].lower()

    def test_missing_new_password(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_change_password(hi, http(body={"current_password": "correct-password"}))
        assert _status(result) == 400
        assert "required" in _body(result)["error"].lower()

    def test_empty_current_password(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_change_password(
            hi, http(body={"current_password": "", "new_password": VALID_PASSWORD})
        )
        assert _status(result) == 400

    def test_empty_new_password(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_change_password(
            hi, http(body={"current_password": "correct-password", "new_password": ""})
        )
        assert _status(result) == 400

    def test_both_passwords_empty(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_change_password(hi, http(body={"current_password": "", "new_password": ""}))
        assert _status(result) == 400

    def test_no_user_store(self, http):
        from aragora.server.handlers.auth.handler import AuthHandler

        hi = AuthHandler(server_context={})
        hi._check_permission = MagicMock(return_value=None)
        result = handle_change_password(
            hi,
            http(body={"current_password": "correct-password", "new_password": VALID_PASSWORD}),
        )
        assert _status(result) == 503
        assert "unavailable" in _body(result)["error"].lower()

    def test_password_validation_too_short(self, handler_instance, http):
        hi, store = handler_instance
        store.get_user_by_id.return_value = MockUser()
        result = handle_change_password(
            hi,
            http(body={"current_password": "correct-password", "new_password": "Short1!"}),
        )
        assert _status(result) == 400
        assert "12" in _body(result)["error"]  # mentions minimum length

    def test_password_validation_no_uppercase(self, handler_instance, http):
        hi, store = handler_instance
        store.get_user_by_id.return_value = MockUser()
        result = handle_change_password(
            hi,
            http(
                body={"current_password": "correct-password", "new_password": "nouppercase123!@#"}
            ),
        )
        assert _status(result) == 400
        assert "uppercase" in _body(result)["error"].lower()

    def test_password_validation_no_digit(self, handler_instance, http):
        hi, store = handler_instance
        store.get_user_by_id.return_value = MockUser()
        result = handle_change_password(
            hi,
            http(body={"current_password": "correct-password", "new_password": "NoDigitsHere!@#a"}),
        )
        assert _status(result) == 400
        assert "digit" in _body(result)["error"].lower()

    def test_password_validation_no_special_char(self, handler_instance, http):
        hi, store = handler_instance
        store.get_user_by_id.return_value = MockUser()
        result = handle_change_password(
            hi,
            http(body={"current_password": "correct-password", "new_password": "NoSpecialChar123"}),
        )
        assert _status(result) == 400
        assert "special" in _body(result)["error"].lower()

    def test_user_not_found(self, handler_instance, http):
        hi, store = handler_instance
        store.get_user_by_id.return_value = None
        result = handle_change_password(
            hi,
            http(body={"current_password": "correct-password", "new_password": VALID_PASSWORD}),
        )
        assert _status(result) == 404

    def test_current_password_incorrect(self, handler_instance, http):
        hi, store = handler_instance
        user = MockUser()
        store.get_user_by_id.return_value = user
        result = handle_change_password(
            hi,
            http(body={"current_password": "wrong-password", "new_password": VALID_PASSWORD}),
        )
        assert _status(result) == 401
        assert "incorrect" in _body(result)["error"].lower()

    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    def test_emit_handler_event_called(self, mock_hash, handler_instance, http, monkeypatch):
        hi, store = handler_instance
        user = MockUser()
        store.get_user_by_id.return_value = user

        events = []
        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.emit_handler_event",
            lambda *args, **kwargs: events.append((args, kwargs)),
        )

        handle_change_password(
            hi,
            http(body={"current_password": "correct-password", "new_password": VALID_PASSWORD}),
        )
        assert len(events) == 1
        assert events[0][0][0] == "auth"
        assert events[0][0][2]["action"] == "password_changed"

    def test_empty_body(self, handler_instance, http):
        """Empty JSON body should fail with missing fields."""
        hi, _ = handler_instance
        result = handle_change_password(hi, http(body={}))
        assert _status(result) == 400


# =========================================================================
# handle_forgot_password
# =========================================================================


class TestForgotPassword:
    """POST /api/auth/password/forgot."""

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_success_user_exists(self, mock_get_store, handler_instance, http, monkeypatch):
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.create_token.return_value = ("reset-token-123", None)
        mock_get_store.return_value = mock_reset_store

        # Patch send_password_reset_email to no-op
        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.send_password_reset_email",
            lambda user, link: None,
        )

        result = handle_forgot_password(hi, http(body={"email": "test@example.com"}))
        assert _status(result) == 200
        body = _body(result)
        assert "if an account exists" in body["message"].lower()
        assert body["email"] == "test@example.com"

    def test_success_user_not_found_no_enumeration(self, handler_instance, http):
        """Should return same success response even if user does not exist."""
        hi, store = handler_instance
        store.get_user_by_email.return_value = None

        result = handle_forgot_password(hi, http(body={"email": "nonexistent@example.com"}))
        assert _status(result) == 200
        body = _body(result)
        assert "if an account exists" in body["message"].lower()
        assert body["email"] == "nonexistent@example.com"

    def test_invalid_json_body(self, handler_instance):
        hi, _ = handler_instance
        h = MockHTTPHandler()
        h.rfile.read.return_value = b"not json"
        h.headers["Content-Length"] = "8"
        result = handle_forgot_password(hi, h)
        assert _status(result) == 400

    def test_missing_email(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_forgot_password(hi, http(body={}))
        assert _status(result) == 400
        assert "required" in _body(result)["error"].lower()

    def test_empty_email(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_forgot_password(hi, http(body={"email": ""}))
        assert _status(result) == 400

    def test_whitespace_email(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_forgot_password(hi, http(body={"email": "   "}))
        assert _status(result) == 400

    def test_invalid_email_format(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_forgot_password(hi, http(body={"email": "not-an-email"}))
        assert _status(result) == 400
        assert "email" in _body(result)["error"].lower()

    def test_no_user_store(self, http):
        from aragora.server.handlers.auth.handler import AuthHandler

        hi = AuthHandler(server_context={})
        hi._check_permission = MagicMock(return_value=None)
        result = handle_forgot_password(hi, http(body={"email": "test@example.com"}))
        assert _status(result) == 503
        assert "unavailable" in _body(result)["error"].lower()

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_inactive_user_no_token(self, mock_get_store, handler_instance, http):
        """Inactive user should not receive a reset token, but response is same."""
        hi, store = handler_instance
        user = MockUser(is_active=False)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_get_store.return_value = mock_reset_store

        result = handle_forgot_password(hi, http(body={"email": "test@example.com"}))
        assert _status(result) == 200
        mock_reset_store.create_token.assert_not_called()

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_rate_limited_token_creation(self, mock_get_store, handler_instance, http):
        """When rate limited, should still return success."""
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.create_token.return_value = (None, "Too many requests")
        mock_get_store.return_value = mock_reset_store

        result = handle_forgot_password(hi, http(body={"email": "test@example.com"}))
        assert _status(result) == 200  # Still success for anti-enumeration

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_audit_logged_on_success(self, mock_get_store, handler_instance, http, monkeypatch):
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.create_token.return_value = ("token-abc", None)
        mock_get_store.return_value = mock_reset_store

        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.send_password_reset_email",
            lambda user, link: None,
        )

        audit_calls = []
        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.audit_security",
            lambda **kwargs: audit_calls.append(kwargs),
        )

        handle_forgot_password(hi, http(body={"email": "test@example.com"}))
        assert len(audit_calls) == 1
        assert audit_calls[0]["reason"] == "password_reset_requested"
        assert audit_calls[0]["event_type"] == "anomaly"

    @patch("aragora.server.handlers.auth.password.send_password_reset_email")
    @patch("aragora.server.handlers.auth.password.audit_security")
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_audit_records_exact_ipv6_client(
        self, mock_get_store, mock_audit, _send, handler_instance, http
    ):
        mock_get_store.return_value.create_token.return_value = ("token-abc", None)
        request = http(body={"email": "test@example.com"})
        request.client_address = ("2001:db8:1:2::a", 52000)
        handle_forgot_password(handler_instance[0], request)
        assert mock_audit.call_args.kwargs["ip_address"] == "2001:db8:1:2::a"

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_audit_not_called_when_unavailable(
        self, mock_get_store, handler_instance, http, monkeypatch
    ):
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.create_token.return_value = ("token-abc", None)
        mock_get_store.return_value = mock_reset_store

        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.send_password_reset_email",
            lambda user, link: None,
        )
        monkeypatch.setattr("aragora.server.handlers.auth.password.AUDIT_AVAILABLE", False)

        audit_calls = []
        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.audit_security",
            lambda **kwargs: audit_calls.append(kwargs),
        )

        handle_forgot_password(hi, http(body={"email": "test@example.com"}))
        assert len(audit_calls) == 0

    def test_email_lowercase_normalized(self, handler_instance, http):
        """Email should be lowercased and stripped."""
        hi, store = handler_instance
        store.get_user_by_email.return_value = None

        result = handle_forgot_password(hi, http(body={"email": "  Test@EXAMPLE.COM  "}))
        assert _status(result) == 200
        body = _body(result)
        assert body["email"] == "test@example.com"

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_reset_link_includes_token(self, mock_get_store, handler_instance, http, monkeypatch):
        """The reset link should contain the generated token."""
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.create_token.return_value = ("my-unique-token", None)
        mock_get_store.return_value = mock_reset_store

        sent_links = []
        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.send_password_reset_email",
            lambda u, link: sent_links.append(link),
        )

        handle_forgot_password(hi, http(body={"email": "test@example.com"}))
        assert len(sent_links) == 1
        assert "my-unique-token" in sent_links[0]

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_reset_link_uses_frontend_url_env(
        self, mock_get_store, handler_instance, http, monkeypatch
    ):
        """Reset link should use ARAGORA_FRONTEND_URL environment variable."""
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.create_token.return_value = ("token-xyz", None)
        mock_get_store.return_value = mock_reset_store

        sent_links = []
        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.send_password_reset_email",
            lambda u, link: sent_links.append(link),
        )
        monkeypatch.setenv("ARAGORA_FRONTEND_URL", "https://myapp.example.com")

        handle_forgot_password(hi, http(body={"email": "test@example.com"}))
        assert len(sent_links) == 1
        assert sent_links[0].startswith("https://myapp.example.com/")


# =========================================================================
# handle_reset_password
# =========================================================================


class TestResetPassword:
    """POST /api/auth/password/reset."""

    @patch("aragora.billing.models.hash_password", return_value=("hashed_new", "salt_new"))
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_success(self, mock_get_store, mock_hash, handler_instance, http):
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        result = handle_reset_password(
            hi, http(body={"token": "valid-token", "password": VALID_PASSWORD})
        )
        assert _status(result) == 200
        body = _body(result)
        assert "reset" in body["message"].lower()
        assert body["sessions_invalidated"] is True

    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_accepts_new_password_field(self, mock_get_store, mock_hash, handler_instance, http):
        """Should accept 'new_password' as an alias for 'password'."""
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        result = handle_reset_password(
            hi, http(body={"token": "valid-token", "new_password": VALID_PASSWORD})
        )
        assert _status(result) == 200

    @patch("aragora.billing.models.hash_password", return_value=("reset_hash", "reset_salt"))
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_updates_password_hash(self, mock_get_store, mock_hash, handler_instance, http):
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        handle_reset_password(hi, http(body={"token": "valid-token", "password": VALID_PASSWORD}))
        store.update_user.assert_called_once_with(
            user.id,
            password_hash="reset_hash",
            password_salt="reset_salt",
        )

    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_invalidates_sessions(self, mock_get_store, mock_hash, handler_instance, http):
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        handle_reset_password(hi, http(body={"token": "valid-token", "password": VALID_PASSWORD}))
        store.increment_token_version.assert_called_once_with(user.id)

    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_consumes_token_and_invalidates_others(
        self, mock_get_store, mock_hash, handler_instance, http
    ):
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        handle_reset_password(hi, http(body={"token": "valid-token", "password": VALID_PASSWORD}))
        mock_reset_store.consume_token.assert_called_once_with("valid-token")
        mock_reset_store.invalidate_tokens_for_email.assert_called_once_with("test@example.com")

    def test_invalid_json_body(self, handler_instance):
        hi, _ = handler_instance
        h = MockHTTPHandler()
        h.rfile.read.return_value = b"not json"
        h.headers["Content-Length"] = "8"
        result = handle_reset_password(hi, h)
        assert _status(result) == 400

    def test_missing_token(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_reset_password(hi, http(body={"password": VALID_PASSWORD}))
        assert _status(result) == 400
        assert "token" in _body(result)["error"].lower()

    def test_empty_token(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_reset_password(hi, http(body={"token": "", "password": VALID_PASSWORD}))
        assert _status(result) == 400

    def test_whitespace_token(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_reset_password(hi, http(body={"token": "   ", "password": VALID_PASSWORD}))
        assert _status(result) == 400

    def test_missing_password(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_reset_password(hi, http(body={"token": "some-token"}))
        assert _status(result) == 400
        assert "password" in _body(result)["error"].lower()

    def test_empty_password(self, handler_instance, http):
        hi, _ = handler_instance
        result = handle_reset_password(hi, http(body={"token": "some-token", "password": ""}))
        assert _status(result) == 400

    def test_password_validation_failure(self, handler_instance, http):
        """New password must meet validation requirements."""
        hi, _ = handler_instance

        result = handle_reset_password(hi, http(body={"token": "some-token", "password": "weak"}))
        assert _status(result) == 400

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_invalid_token(self, mock_get_store, handler_instance, http):
        hi, _ = handler_instance

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = (None, "Token expired or invalid")
        mock_get_store.return_value = mock_reset_store

        result = handle_reset_password(
            hi, http(body={"token": "bad-token", "password": VALID_PASSWORD})
        )
        assert _status(result) == 400
        assert (
            "expired" in _body(result)["error"].lower()
            or "invalid" in _body(result)["error"].lower()
        )

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_no_user_store(self, mock_get_store, http):
        from aragora.server.handlers.auth.handler import AuthHandler

        hi = AuthHandler(server_context={})
        hi._check_permission = MagicMock(return_value=None)

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        result = handle_reset_password(
            hi, http(body={"token": "valid-token", "password": VALID_PASSWORD})
        )
        assert _status(result) == 503
        assert "unavailable" in _body(result)["error"].lower()

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_user_not_found(self, mock_get_store, handler_instance, http):
        hi, store = handler_instance
        store.get_user_by_email.return_value = None

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("gone@example.com", None)
        mock_get_store.return_value = mock_reset_store

        result = handle_reset_password(
            hi, http(body={"token": "valid-token", "password": VALID_PASSWORD})
        )
        assert _status(result) == 404
        # Token should still be consumed
        mock_reset_store.consume_token.assert_called_once_with("valid-token")

    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_user_inactive(self, mock_get_store, handler_instance, http):
        hi, store = handler_instance
        user = MockUser(is_active=False)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        result = handle_reset_password(
            hi, http(body={"token": "valid-token", "password": VALID_PASSWORD})
        )
        assert _status(result) == 401
        assert "disabled" in _body(result)["error"].lower()
        mock_reset_store.consume_token.assert_called_once_with("valid-token")

    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_audit_logged_on_success(
        self, mock_get_store, mock_hash, handler_instance, http, monkeypatch
    ):
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        audit_calls = []
        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.audit_security",
            lambda **kwargs: audit_calls.append(kwargs),
        )

        handle_reset_password(hi, http(body={"token": "valid-token", "password": VALID_PASSWORD}))
        assert len(audit_calls) == 1
        assert audit_calls[0]["reason"] == "password_reset_completed"
        assert audit_calls[0]["event_type"] == "encryption"

    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_audit_not_called_when_unavailable(
        self, mock_get_store, mock_hash, handler_instance, http, monkeypatch
    ):
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        monkeypatch.setattr("aragora.server.handlers.auth.password.AUDIT_AVAILABLE", False)

        audit_calls = []
        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.audit_security",
            lambda **kwargs: audit_calls.append(kwargs),
        )

        handle_reset_password(hi, http(body={"token": "valid-token", "password": VALID_PASSWORD}))
        assert len(audit_calls) == 0

    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    def test_emit_handler_event_called(
        self, mock_get_store, mock_hash, handler_instance, http, monkeypatch
    ):
        hi, store = handler_instance
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        events = []
        monkeypatch.setattr(
            "aragora.server.handlers.auth.password.emit_handler_event",
            lambda *args, **kwargs: events.append((args, kwargs)),
        )

        handle_reset_password(hi, http(body={"token": "valid-token", "password": VALID_PASSWORD}))
        assert len(events) == 1
        assert events[0][0][0] == "auth"
        assert events[0][0][2]["action"] == "password_reset"


# =========================================================================
# AuthHandler routing via handle()
# =========================================================================


class TestAuthHandlerRouting:
    """Test that AuthHandler.handle() dispatches password routes correctly."""

    @pytest.fixture
    def routable_handler(self):
        """Create an AuthHandler with patched password handlers."""
        from aragora.server.handlers.auth.handler import AuthHandler

        store = _make_user_store()
        hi = AuthHandler(server_context={"user_store": store})
        hi._check_permission = MagicMock(return_value=None)
        return hi, store

    @pytest.mark.asyncio
    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    async def test_route_password_change(self, mock_hash, routable_handler, http):
        hi, store = routable_handler
        user = MockUser()
        store.get_user_by_id.return_value = user

        result = await hi.handle(
            "/api/auth/password/change",
            {},
            http(body={"current_password": "correct-password", "new_password": VALID_PASSWORD}),
            method="POST",
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    async def test_route_password_alias(self, mock_hash, routable_handler, http):
        """POST /api/auth/password should also change password."""
        hi, store = routable_handler
        user = MockUser()
        store.get_user_by_id.return_value = user

        result = await hi.handle(
            "/api/auth/password",
            {},
            http(body={"current_password": "correct-password", "new_password": VALID_PASSWORD}),
            method="POST",
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_route_password_forgot(self, routable_handler, http):
        hi, store = routable_handler
        store.get_user_by_email.return_value = None

        result = await hi.handle(
            "/api/auth/password/forgot",
            {},
            http(body={"email": "test@example.com"}),
            method="POST",
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    async def test_route_password_reset(self, mock_get_store, mock_hash, routable_handler, http):
        hi, store = routable_handler
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        result = await hi.handle(
            "/api/auth/password/reset",
            {},
            http(body={"token": "valid-token", "password": VALID_PASSWORD}),
            method="POST",
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_route_forgot_password_legacy(self, routable_handler, http):
        """POST /api/auth/forgot-password (legacy) should work."""
        hi, store = routable_handler
        store.get_user_by_email.return_value = None

        result = await hi.handle(
            "/api/auth/forgot-password",
            {},
            http(body={"email": "test@example.com"}),
            method="POST",
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    @patch("aragora.storage.password_reset_store.get_password_reset_store")
    async def test_route_reset_password_legacy(
        self, mock_get_store, mock_hash, routable_handler, http
    ):
        """POST /api/auth/reset-password (legacy) should work."""
        hi, store = routable_handler
        user = MockUser(is_active=True)
        store.get_user_by_email.return_value = user

        mock_reset_store = MagicMock()
        mock_reset_store.validate_token.return_value = ("test@example.com", None)
        mock_get_store.return_value = mock_reset_store

        result = await hi.handle(
            "/api/auth/reset-password",
            {},
            http(body={"token": "valid-token", "password": VALID_PASSWORD}),
            method="POST",
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    @patch("aragora.billing.models.hash_password", return_value=("h", "s"))
    async def test_route_versioned_path(self, mock_hash, routable_handler, http):
        """Versioned path /api/v1/auth/password/change should be normalized."""
        hi, store = routable_handler
        user = MockUser()
        store.get_user_by_id.return_value = user

        result = await hi.handle(
            "/api/v1/auth/password/change",
            {},
            http(body={"current_password": "correct-password", "new_password": VALID_PASSWORD}),
            method="POST",
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_route_disabled_password_reset(self, http):
        """When enable_password_reset_routes=False, forgot/reset return 501."""
        from aragora.server.handlers.auth.handler import AuthHandler

        hi = AuthHandler(server_context={"enable_password_reset_routes": False})
        hi._check_permission = MagicMock(return_value=None)

        result = await hi.handle(
            "/api/auth/password/forgot",
            {},
            http(body={"email": "test@example.com"}),
            method="POST",
        )
        assert _status(result) == 501
        assert "email provider" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_route_disabled_password_reset_reset_endpoint(self, http):
        """When enable_password_reset_routes=False, reset also returns 501."""
        from aragora.server.handlers.auth.handler import AuthHandler

        hi = AuthHandler(server_context={"enable_password_reset_routes": False})
        hi._check_permission = MagicMock(return_value=None)

        result = await hi.handle(
            "/api/auth/password/reset",
            {},
            http(body={"token": "tok", "password": VALID_PASSWORD}),
            method="POST",
        )
        assert _status(result) == 501

    @pytest.mark.asyncio
    async def test_route_disabled_legacy_forgot(self, http):
        """Legacy forgot-password also disabled when enable_password_reset_routes=False."""
        from aragora.server.handlers.auth.handler import AuthHandler

        hi = AuthHandler(server_context={"enable_password_reset_routes": False})
        hi._check_permission = MagicMock(return_value=None)

        result = await hi.handle(
            "/api/auth/forgot-password",
            {},
            http(body={"email": "test@example.com"}),
            method="POST",
        )
        assert _status(result) == 501

    @pytest.mark.asyncio
    async def test_route_disabled_legacy_reset(self, http):
        """Legacy reset-password also disabled when enable_password_reset_routes=False."""
        from aragora.server.handlers.auth.handler import AuthHandler

        hi = AuthHandler(server_context={"enable_password_reset_routes": False})
        hi._check_permission = MagicMock(return_value=None)

        result = await hi.handle(
            "/api/auth/reset-password",
            {},
            http(body={"token": "tok", "password": VALID_PASSWORD}),
            method="POST",
        )
        assert _status(result) == 501


# =========================================================================
# send_password_reset_email
# =========================================================================


class TestSendPasswordResetEmail:
    """Tests for send_password_reset_email helper."""

    def test_no_email_provider_configured(self, monkeypatch):
        """When no SMTP/SendGrid/SES env vars set, logs warning but does not crash."""
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)

        user = MockUser(name="Alice", email="alice@example.com")
        # Should not raise
        send_password_reset_email(user, "https://aragora.ai/reset-password?token=abc")

    def test_import_error_handled(self, monkeypatch):
        """If email integration is not installed, should handle gracefully."""
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "aragora.integrations.email" in name:
                raise ImportError("No module named 'aragora.integrations.email'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")

        user = MockUser(name="Bob", email="bob@example.com")
        # Should not raise
        send_password_reset_email(user, "https://aragora.ai/reset-password?token=xyz")


# =========================================================================
# Module-level exports
# =========================================================================


class TestModuleExports:
    """Verify __all__ exports."""

    def test_all_exports(self):
        from aragora.server.handlers.auth import password

        assert "handle_change_password" in password.__all__
        assert "handle_forgot_password" in password.__all__
        assert "handle_reset_password" in password.__all__
        assert "send_password_reset_email" in password.__all__

    def test_all_exports_count(self):
        from aragora.server.handlers.auth import password

        assert len(password.__all__) == 4


# =========================================================================
# can_handle
# =========================================================================


class TestCanHandle:
    """Test that AuthHandler.can_handle recognizes password routes."""

    def test_password_change(self):
        from aragora.server.handlers.auth.handler import AuthHandler

        h = AuthHandler()
        assert h.can_handle("/api/auth/password/change") is True

    def test_password_forgot(self):
        from aragora.server.handlers.auth.handler import AuthHandler

        h = AuthHandler()
        assert h.can_handle("/api/auth/password/forgot") is True

    def test_password_reset(self):
        from aragora.server.handlers.auth.handler import AuthHandler

        h = AuthHandler()
        assert h.can_handle("/api/auth/password/reset") is True

    def test_password_base(self):
        from aragora.server.handlers.auth.handler import AuthHandler

        h = AuthHandler()
        assert h.can_handle("/api/auth/password") is True

    def test_forgot_password_legacy(self):
        from aragora.server.handlers.auth.handler import AuthHandler

        h = AuthHandler()
        assert h.can_handle("/api/auth/forgot-password") is True

    def test_reset_password_legacy(self):
        from aragora.server.handlers.auth.handler import AuthHandler

        h = AuthHandler()
        assert h.can_handle("/api/auth/reset-password") is True

    def test_versioned_path(self):
        from aragora.server.handlers.auth.handler import AuthHandler

        h = AuthHandler()
        assert h.can_handle("/api/v1/auth/password/change") is True
