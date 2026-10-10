"""Tests for login.py (aragora/server/handlers/auth/login.py).

Covers both handle_register and handle_login with all branches:
- Valid registration / login flows
- Input validation (email, password)
- Missing/invalid JSON body
- User store unavailable (503)
- Email already registered (409)
- User creation failure (ValueError)
- Organization creation and org_data in response
- MFA-enabled login (pending token)
- Lockout tracker (is_locked, record_failure, reset)
- Database-based account lockout (legacy)
- Password verification failure with lockout escalation
- Account disabled
- Audit logging (when available / unavailable)
- Handler event emission
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.auth.handler import AuthHandler


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
            self.rfile.read.return_value = b""
            self.headers["Content-Length"] = "0"


@dataclass
class MockUser:
    """Mock user for user-store interactions."""

    id: str = "user-001"
    email: str = "test@example.com"
    name: str = "Test User"
    org_id: str | None = None
    role: str = "member"
    is_active: bool = True
    mfa_enabled: bool = False
    mfa_secret: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "org_id": self.org_id,
            "role": self.role,
        }

    def verify_password(self, password: str) -> bool:
        return password == "Correct-Password1!"


@dataclass
class MockOrg:
    """Mock organization."""

    id: str = "org-001"
    name: str = "Test Org"

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name}


@dataclass
class MockTokenPair:
    """Mock token pair from create_token_pair."""

    access_token: str = "access-tok"
    refresh_token: str = "refresh-tok"

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": "bearer",
            "expires_in": 3600,
        }


class MockLockoutTracker:
    """Mock lockout tracker with controllable behaviour."""

    def __init__(self, *, locked: bool = False, remaining: int = 0):
        self._locked = locked
        self._remaining = remaining
        self._failures: list[tuple] = []
        self._resets: list[tuple] = []

    def is_locked(self, email: str = "", ip: str = "") -> bool:
        return self._locked

    def get_remaining_time(self, email: str = "", ip: str = "") -> int:
        return self._remaining

    def record_failure(self, email: str = "", ip: str = "") -> tuple[int, int | None]:
        self._failures.append((email, ip))
        return (1, None)

    def reset(self, email: str = "", ip: str = "") -> None:
        self._resets.append((email, ip))


class SimpleUserStore:
    """Simple user store that only has the methods we configure.

    Unlike MagicMock, this does NOT auto-create attributes, so
    ``hasattr(store, "is_account_locked")`` returns False by default,
    avoiding the tuple-unpacking issue on login.py line 286.
    """

    def __init__(
        self,
        user: MockUser | None = None,
        org: MockOrg | None = None,
        *,
        existing_email: bool = False,
    ):
        self._user = user or MockUser()
        self._org = org or MockOrg()
        self._existing_email = existing_email
        self._updated: dict[str, Any] = {}
        self._created_users: list[dict] = []
        self._created_orgs: list[dict] = []

    def get_user_by_id(self, user_id: str) -> MockUser | None:
        return self._user

    def get_user_by_email(self, email: str) -> MockUser | None:
        return self._user if self._existing_email else None

    def create_user(self, **kwargs: Any) -> MockUser:
        self._created_users.append(kwargs)
        return self._user

    def create_organization(self, **kwargs: Any) -> MockOrg:
        self._created_orgs.append(kwargs)
        return self._org

    def get_organization_by_id(self, org_id: str) -> MockOrg | None:
        return self._org

    def update_user(self, user_id: str, **kwargs: Any) -> None:
        self._updated[user_id] = kwargs


# A valid password that passes the validator
VALID_PASSWORD = "SecureP@ssw0rd1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_rate_limits(monkeypatch):
    """Bypass rate limiting decorators so they don't interfere with tests."""
    try:
        from aragora.server.handlers.utils import rate_limit as rl_mod

        rl_mod._limiters.clear()
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def _patch_lockout(monkeypatch):
    """Provide a default non-locked lockout tracker."""
    tracker = MockLockoutTracker()
    monkeypatch.setattr(
        "aragora.server.handlers.auth.login.get_lockout_tracker",
        lambda: tracker,
    )
    return tracker


@pytest.fixture
def handler():
    """Create an AuthHandler with a populated user store."""
    store = SimpleUserStore(existing_email=False)
    return AuthHandler(server_context={"user_store": store})


@pytest.fixture
def handler_no_store():
    """AuthHandler with no user store in context."""
    return AuthHandler(server_context={})


# =========================================================================
# handle_register tests
# =========================================================================


class TestRegisterInvalidBody:
    """Registration with missing or bad request body."""

    def test_no_body_returns_400(self, handler):
        http = MockHTTPHandler(body=None)
        result = handler._handle_register(http)
        assert _status(result) == 400

    def test_empty_body_returns_400(self, handler):
        http = MockHTTPHandler(body={})
        result = handler._handle_register(http)
        assert _status(result) == 400

    def test_invalid_json_returns_400(self, handler):
        http = MockHTTPHandler()
        http.rfile.read.return_value = b"not json"
        http.headers["Content-Length"] = "8"
        result = handler._handle_register(http)
        assert _status(result) == 400


class TestRegisterEmailValidation:
    """Email validation on registration."""

    def test_missing_email_returns_400(self, handler):
        http = MockHTTPHandler(body={"password": VALID_PASSWORD})
        result = handler._handle_register(http)
        assert _status(result) == 400
        assert "email" in _body(result).get("error", "").lower()

    def test_invalid_email_format_returns_400(self, handler):
        http = MockHTTPHandler(body={"email": "not-an-email", "password": VALID_PASSWORD})
        result = handler._handle_register(http)
        assert _status(result) == 400


class TestRegisterPasswordValidation:
    """Password validation on registration."""

    def test_missing_password_returns_400(self, handler):
        http = MockHTTPHandler(body={"email": "user@example.com"})
        result = handler._handle_register(http)
        assert _status(result) == 400

    def test_short_password_returns_400(self, handler):
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "Ab1!"})
        result = handler._handle_register(http)
        assert _status(result) == 400

    def test_no_uppercase_returns_400(self, handler):
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "securep@ssw0rd1"})
        result = handler._handle_register(http)
        assert _status(result) == 400

    def test_no_special_char_returns_400(self, handler):
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "SecurePassw0rd1"})
        result = handler._handle_register(http)
        assert _status(result) == 400


class TestRegisterUserStoreUnavailable:
    """503 when user store is missing."""

    def test_no_user_store_returns_503(self, handler_no_store):
        http = MockHTTPHandler(body={"email": "user@example.com", "password": VALID_PASSWORD})
        result = handler_no_store._handle_register(http)
        assert _status(result) == 503
        assert "unavailable" in _body(result).get("error", "").lower()


class TestRegisterEmailAlreadyExists:
    """409 when email already registered."""

    def test_duplicate_email_returns_409(self):
        store = SimpleUserStore(existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": VALID_PASSWORD})
        result = h._handle_register(http)
        assert _status(result) == 409
        assert "already registered" in _body(result).get("error", "").lower()


class TestRegisterUserCreationFailure:
    """409 when user store raises ValueError."""

    @patch("aragora.billing.models.hash_password", return_value=("hash", "salt"))
    def test_value_error_returns_409(self, _hash):
        store = SimpleUserStore(existing_email=False)
        original_create = store.create_user

        def failing_create(**kwargs: Any) -> MockUser:
            raise ValueError("duplicate")

        store.create_user = failing_create
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": VALID_PASSWORD})
        result = h._handle_register(http)
        assert _status(result) == 409
        assert "failed" in _body(result).get("error", "").lower()


class TestRegisterSuccess:
    """Successful registration returns 201 with user + tokens."""

    @patch("aragora.billing.models.hash_password", return_value=("hash", "salt"))
    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_basic_registration(self, _tok, _hash):
        user = MockUser(email="new@example.com")
        store = SimpleUserStore(user=user, existing_email=False)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "new@example.com", "password": VALID_PASSWORD})
        result = h._handle_register(http)
        assert _status(result) == 201
        body = _body(result)
        assert "user" in body
        assert "tokens" in body
        assert body["tokens"]["access_token"] == "access-tok"
        assert len(store._created_users) == 1

    @patch("aragora.billing.models.hash_password", return_value=("hash", "salt"))
    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_registration_normalizes_email(self, _tok, _hash):
        """Email is lowered and stripped."""
        user = MockUser(email="user@example.com")
        store = SimpleUserStore(user=user, existing_email=False)
        # We need to track the email argument. Use a MagicMock wrapper.
        original_get = store.get_user_by_email
        get_mock = MagicMock(side_effect=original_get)
        store.get_user_by_email = get_mock
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": " USER@Example.COM ", "password": VALID_PASSWORD})
        result = h._handle_register(http)
        assert _status(result) == 201
        get_mock.assert_called_with("user@example.com")

    @patch("aragora.billing.models.hash_password", return_value=("hash", "salt"))
    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_registration_uses_email_prefix_as_name(self, _tok, _hash):
        """When name is empty, use email prefix."""
        user = MockUser(email="alice@example.com", name="alice")
        store = SimpleUserStore(user=user, existing_email=False)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "alice@example.com", "password": VALID_PASSWORD})
        result = h._handle_register(http)
        assert _status(result) == 201
        assert len(store._created_users) == 1
        assert store._created_users[0]["name"] == "alice"

    @patch("aragora.billing.models.hash_password", return_value=("hash", "salt"))
    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_registration_with_explicit_name(self, _tok, _hash):
        """Explicit name is used instead of email prefix."""
        user = MockUser(email="alice@example.com", name="Alice Smith")
        store = SimpleUserStore(user=user, existing_email=False)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(
            body={
                "email": "alice@example.com",
                "password": VALID_PASSWORD,
                "name": "Alice Smith",
            }
        )
        result = h._handle_register(http)
        assert _status(result) == 201
        assert store._created_users[0]["name"] == "Alice Smith"


class TestRegisterWithOrganization:
    """Registration with an organization name creates org."""

    @patch("aragora.billing.models.hash_password", return_value=("hash", "salt"))
    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_org_created_and_included_in_response(self, _tok, _hash):
        org = MockOrg(id="org-001", name="Acme Corp")
        user = MockUser(email="alice@acme.com", org_id="org-001")
        store = SimpleUserStore(user=user, org=org, existing_email=False)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(
            body={
                "email": "alice@acme.com",
                "password": VALID_PASSWORD,
                "organization": "Acme Corp",
            }
        )
        result = h._handle_register(http)
        assert _status(result) == 201
        body = _body(result)
        assert body["organization"] is not None
        assert body["organization"]["name"] == "Acme Corp"
        assert len(body["organizations"]) == 1
        assert body["organizations"][0]["org_id"] == "org-001"
        assert len(store._created_orgs) == 1

    @patch("aragora.billing.models.hash_password", return_value=("hash", "salt"))
    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_no_org_name_skips_org_creation(self, _tok, _hash):
        user = MockUser(email="bob@example.com")
        store = SimpleUserStore(user=user, existing_email=False)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "bob@example.com", "password": VALID_PASSWORD})
        result = h._handle_register(http)
        assert _status(result) == 201
        body = _body(result)
        assert body.get("organization") is None
        assert body.get("organizations") == []
        assert len(store._created_orgs) == 0


class TestRegisterAudit:
    """Audit logging on registration."""

    @patch("aragora.billing.models.hash_password", return_value=("hash", "salt"))
    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    @patch("aragora.server.handlers.auth.login.emit_handler_event")
    def test_emit_handler_event_called(self, mock_emit, _tok, _hash):
        user = MockUser(email="a@b.com")
        store = SimpleUserStore(user=user, existing_email=False)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "a@b.com", "password": VALID_PASSWORD})
        h._handle_register(http)
        mock_emit.assert_called_once()
        args = mock_emit.call_args
        assert args[0][0] == "auth"

    @patch("aragora.billing.models.hash_password", return_value=("hash", "salt"))
    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    @patch("aragora.server.handlers.auth.login.AUDIT_AVAILABLE", True)
    @patch("aragora.server.handlers.auth.login.audit_admin")
    def test_audit_admin_called_on_register(self, mock_audit, _tok, _hash):
        user = MockUser(email="a@b.com")
        store = SimpleUserStore(user=user, existing_email=False)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "a@b.com", "password": VALID_PASSWORD})
        h._handle_register(http)
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args
        assert kwargs[1]["action"] == "user_registered"


# =========================================================================
# handle_login tests
# =========================================================================


class TestLoginInvalidBody:
    """Login with missing or bad request body."""

    def test_no_body_returns_400(self, handler):
        http = MockHTTPHandler(body=None)
        result = handler._handle_login(http)
        assert _status(result) == 400

    def test_non_object_json_returns_400(self, handler):
        http = MockHTTPHandler(body=["oops"])
        result = handler._handle_login(http)
        assert _status(result) == 400
        assert "invalid json body" in _body(result).get("error", "").lower()

    def test_empty_body_returns_400(self, handler):
        http = MockHTTPHandler(body={})
        result = handler._handle_login(http)
        assert _status(result) == 400
        assert "required" in _body(result).get("error", "").lower()

    def test_missing_password_returns_400(self, handler):
        http = MockHTTPHandler(body={"email": "user@example.com"})
        result = handler._handle_login(http)
        assert _status(result) == 400

    def test_missing_email_returns_400(self, handler):
        http = MockHTTPHandler(body={"password": "anything"})
        result = handler._handle_login(http)
        assert _status(result) == 400


class TestLoginUserStoreUnavailable:
    """503 when user store is missing."""

    def test_no_user_store_returns_503(self, handler_no_store, _patch_lockout):
        http = MockHTTPHandler(body={"email": "a@b.com", "password": "pw"})
        result = handler_no_store._handle_login(http)
        assert _status(result) == 503
        assert "unavailable" in _body(result).get("error", "").lower()


class TestLoginLockout:
    """Account lockout prevents login."""

    def test_locked_account_returns_429(self, monkeypatch):
        tracker = MockLockoutTracker(locked=True, remaining=300)
        monkeypatch.setattr(
            "aragora.server.handlers.auth.login.get_lockout_tracker",
            lambda: tracker,
        )
        store = SimpleUserStore(existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "pw"})
        result = h._handle_login(http)
        assert _status(result) == 429
        assert "minute" in _body(result).get("error", "").lower()

    def test_db_lockout_returns_429(self, monkeypatch):
        """Legacy database-based lockout."""
        tracker = MockLockoutTracker(locked=False)
        monkeypatch.setattr(
            "aragora.server.handlers.auth.login.get_lockout_tracker",
            lambda: tracker,
        )
        store = SimpleUserStore(existing_email=True)
        lockout_until = datetime(2099, 1, 1, tzinfo=timezone.utc)
        # Add the is_account_locked method dynamically
        store.is_account_locked = lambda email: (True, lockout_until, 5)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "pw"})
        result = h._handle_login(http)
        assert _status(result) == 429
        assert "locked" in _body(result).get("error", "").lower()

    def test_db_lockout_not_locked_continues(self, monkeypatch):
        """When db lockout returns not locked, login continues."""
        tracker = MockLockoutTracker(locked=False)
        monkeypatch.setattr(
            "aragora.server.handlers.auth.login.get_lockout_tracker",
            lambda: tracker,
        )
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        store.is_account_locked = lambda email: (False, None, 2)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "Correct-Password1!"})
        with patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair()):
            result = h._handle_login(http)
        assert _status(result) == 200


class TestLoginUserNotFound:
    """401 when email is not found (no enumeration leak)."""

    def test_unknown_email_returns_401(self, _patch_lockout):
        store = SimpleUserStore(existing_email=False)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "unknown@example.com", "password": "pw"})
        result = h._handle_login(http)
        assert _status(result) == 401
        assert "invalid email or password" in _body(result).get("error", "").lower()

    def test_failure_recorded_on_unknown_email(self, _patch_lockout):
        store = SimpleUserStore(existing_email=False)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "unknown@example.com", "password": "pw"})
        h._handle_login(http)
        assert len(_patch_lockout._failures) == 1


class TestLoginAccountDisabled:
    """401 when account is not active."""

    def test_disabled_account_returns_401(self, _patch_lockout):
        user = MockUser(is_active=False)
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "pw"})
        result = h._handle_login(http)
        assert _status(result) == 401
        assert "disabled" in _body(result).get("error", "").lower()


class TestLoginWrongPassword:
    """Wrong password returns 401 and records failure."""

    def test_wrong_password_returns_401(self, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "wrong"})
        result = h._handle_login(http)
        assert _status(result) == 401
        assert "invalid email or password" in _body(result).get("error", "").lower()

    def test_failure_recorded_on_wrong_password(self, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "wrong"})
        h._handle_login(http)
        assert len(_patch_lockout._failures) == 1

    def test_lockout_triggered_after_failures(self, monkeypatch):
        """When record_failure returns lockout_seconds, return 429."""

        class LockoutEscalate(MockLockoutTracker):
            def record_failure(self, email="", ip=""):
                return (5, 300)  # 5 attempts, locked for 300s

        tracker = LockoutEscalate()
        monkeypatch.setattr(
            "aragora.server.handlers.auth.login.get_lockout_tracker",
            lambda: tracker,
        )
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "wrong"})
        result = h._handle_login(http)
        assert _status(result) == 429
        assert "locked" in _body(result).get("error", "").lower()

    @patch("aragora.server.handlers.auth.login.emit_handler_event")
    def test_emit_failed_event_on_wrong_password(self, mock_emit, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "wrong"})
        h._handle_login(http)
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args[0]
        assert call_args[0] == "auth"

    def test_db_record_failed_login_called(self, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        record_mock = MagicMock(return_value=(3, None))
        store.record_failed_login = record_mock
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "wrong"})
        h._handle_login(http)
        record_mock.assert_called_once()


class TestLoginSuccess:
    """Successful login returns 200 with user + tokens."""

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_basic_login(self, _tok, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "Correct-Password1!"})
        result = h._handle_login(http)
        assert _status(result) == 200
        body = _body(result)
        assert "user" in body
        assert "tokens" in body
        assert body["tokens"]["access_token"] == "access-tok"

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_lockout_reset_on_success(self, _tok, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "Correct-Password1!"})
        h._handle_login(http)
        assert len(_patch_lockout._resets) == 1

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_last_login_updated(self, _tok, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "Correct-Password1!"})
        h._handle_login(http)
        assert "user-001" in store._updated
        assert "last_login_at" in store._updated["user-001"]

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_db_reset_failed_login_called(self, _tok, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        reset_mock = MagicMock(return_value=None)
        store.reset_failed_login_attempts = reset_mock
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "Correct-Password1!"})
        h._handle_login(http)
        reset_mock.assert_called_once()

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_email_normalized(self, _tok, _patch_lockout):
        user = MockUser(email="user@example.com")
        store = SimpleUserStore(user=user, existing_email=True)
        get_mock = MagicMock(side_effect=store.get_user_by_email)
        store.get_user_by_email = get_mock
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(
            body={"email": " USER@Example.COM ", "password": "Correct-Password1!"}
        )
        result = h._handle_login(http)
        assert _status(result) == 200
        get_mock.assert_called_with("user@example.com")


class TestLoginWithOrganization:
    """Login response includes org data when user belongs to an org."""

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_org_included_in_response(self, _tok, _patch_lockout):
        org = MockOrg(id="org-001", name="Acme")
        user = MockUser(email="alice@acme.com", org_id="org-001")
        store = SimpleUserStore(user=user, org=org, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "alice@acme.com", "password": "Correct-Password1!"})
        result = h._handle_login(http)
        assert _status(result) == 200
        body = _body(result)
        assert body["organization"]["name"] == "Acme"
        assert len(body["organizations"]) == 1
        assert body["organizations"][0]["org_id"] == "org-001"
        assert body["organizations"][0]["is_default"] is True

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_no_org_null_fields(self, _tok, _patch_lockout):
        user = MockUser(email="bob@example.com", org_id=None)
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "bob@example.com", "password": "Correct-Password1!"})
        result = h._handle_login(http)
        assert _status(result) == 200
        body = _body(result)
        assert body.get("organization") is None
        assert body.get("organizations") == []


class TestLoginMFA:
    """MFA-enabled login returns pending token instead of full tokens."""

    @patch(
        "aragora.billing.jwt_auth.create_mfa_pending_token",
        return_value="mfa-pending-token-xyz",
    )
    def test_mfa_required_response(self, _mfa_tok, _patch_lockout):
        user = MockUser(
            email="mfa@example.com",
            mfa_enabled=True,
            mfa_secret="JBSWY3DPEHPK3PXP",
        )
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "mfa@example.com", "password": "Correct-Password1!"})
        result = h._handle_login(http)
        assert _status(result) == 200
        body = _body(result)
        assert body["mfa_required"] is True
        assert body["pending_token"] == "mfa-pending-token-xyz"
        assert "tokens" not in body

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_mfa_enabled_but_no_secret_skips_mfa(self, _tok, _patch_lockout):
        """mfa_enabled=True but mfa_secret=None means MFA not fully set up."""
        user = MockUser(
            email="partial@example.com",
            mfa_enabled=True,
            mfa_secret=None,
        )
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(
            body={"email": "partial@example.com", "password": "Correct-Password1!"}
        )
        result = h._handle_login(http)
        assert _status(result) == 200
        body = _body(result)
        assert "tokens" in body
        assert body.get("mfa_required") is None or body.get("mfa_required") is False


class TestLoginAudit:
    """Audit and event logging on login."""

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    @patch("aragora.server.handlers.auth.login.emit_handler_event")
    def test_emit_completed_event_on_login(self, mock_emit, _tok, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "Correct-Password1!"})
        h._handle_login(http)
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args[0]
        assert call_args[0] == "auth"

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    @patch("aragora.server.handlers.auth.login.AUDIT_AVAILABLE", True)
    @patch("aragora.server.handlers.auth.login.audit_login")
    def test_audit_login_success(self, mock_audit, _tok, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "Correct-Password1!"})
        h._handle_login(http)
        mock_audit.assert_called_once()
        assert mock_audit.call_args[1]["success"] is True

    @patch("aragora.server.handlers.auth.login.AUDIT_AVAILABLE", True)
    @patch("aragora.server.handlers.auth.login.audit_login")
    def test_audit_login_failure(self, mock_audit, _patch_lockout):
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "wrong"})
        h._handle_login(http)
        mock_audit.assert_called_once()
        assert mock_audit.call_args[1]["success"] is False

    @patch("aragora.server.handlers.auth.login.AUDIT_AVAILABLE", True)
    @patch("aragora.server.handlers.auth.login.audit_login")
    def test_audit_records_exact_ipv6_while_lockout_key_is_grouped(
        self, mock_audit, _patch_lockout
    ):
        store = SimpleUserStore(user=MockUser(), existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "wrong"})
        http.client_address = ("2001:db8:1:2::a", 52000)
        h._handle_login(http)
        assert mock_audit.call_args[1]["ip_address"] == "2001:db8:1:2::a"
        assert _patch_lockout._failures == [("user@example.com", "2001:db8:1:2::")]

    @patch("aragora.server.handlers.auth.login.AUDIT_AVAILABLE", True)
    @patch("aragora.server.handlers.auth.login.audit_security")
    def test_audit_security_on_lockout_escalation(self, mock_sec, monkeypatch):
        class LockoutEscalate(MockLockoutTracker):
            def record_failure(self, email="", ip=""):
                return (5, 300)

        tracker = LockoutEscalate()
        monkeypatch.setattr(
            "aragora.server.handlers.auth.login.get_lockout_tracker",
            lambda: tracker,
        )
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "wrong"})
        h._handle_login(http)
        mock_sec.assert_called_once()
        assert "locked" in mock_sec.call_args[1]["reason"]


class TestLoginHandlerTracker:
    """Lockout tracker resolution via handler_instance._get_lockout_tracker()."""

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_uses_handler_lockout_tracker(self, _tok, monkeypatch):
        """When the handler has _get_lockout_tracker, it should be used."""
        tracker = MockLockoutTracker()
        monkeypatch.setattr(
            "aragora.server.handlers.auth.login.get_lockout_tracker",
            lambda: tracker,
        )
        user = MockUser()
        store = SimpleUserStore(user=user, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "user@example.com", "password": "Correct-Password1!"})
        result = h._handle_login(http)
        assert _status(result) == 200
        assert len(tracker._resets) == 1


class TestLoginOrgMembershipJoinedAt:
    """The joined_at field is set from user.created_at."""

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_joined_at_from_created_at(self, _tok, _patch_lockout):
        ts = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        user = MockUser(email="alice@co.com", org_id="org-001", created_at=ts)
        org = MockOrg(id="org-001", name="Co")
        store = SimpleUserStore(user=user, org=org, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "alice@co.com", "password": "Correct-Password1!"})
        result = h._handle_login(http)
        body = _body(result)
        assert body["organizations"][0]["joined_at"] == ts.isoformat()

    @patch("aragora.billing.jwt_auth.create_token_pair", return_value=MockTokenPair())
    def test_joined_at_none_when_no_created_at(self, _tok, _patch_lockout):
        user = MockUser(email="bob@co.com", org_id="org-001")
        # Remove created_at attribute
        object.__delattr__(user, "created_at")
        org = MockOrg(id="org-001", name="Co")
        store = SimpleUserStore(user=user, org=org, existing_email=True)
        h = AuthHandler(server_context={"user_store": store})
        http = MockHTTPHandler(body={"email": "bob@co.com", "password": "Correct-Password1!"})
        result = h._handle_login(http)
        body = _body(result)
        assert body["organizations"][0]["joined_at"] is None
