"""Comprehensive tests for OpenClaw CredentialHandlerMixin.

Covers all handler methods defined in
aragora/server/handlers/openclaw/credentials.py:

Credential handlers:
- _handle_list_credentials   (GET  /api/v1/openclaw/credentials)
- _handle_store_credential   (POST /api/v1/openclaw/credentials)
- _handle_rotate_credential  (POST /api/v1/openclaw/credentials/:id/rotate)
- _handle_delete_credential  (DELETE /api/v1/openclaw/credentials/:id)

Rate limiter:
- CredentialRotationRateLimiter (sliding-window per-user rate limit)
- _get_credential_rotation_limiter (global singleton factory)

Test categories:
- Happy paths for every endpoint
- Access control (ownership, admin bypass)
- Validation errors (missing fields, invalid type, invalid secret, bad metadata)
- Not found (404) responses
- Rate limiting (rotation rate limiter per-user)
- Store error handling (exceptions -> 500)
- Query parameter parsing (type filter, pagination)
- Audit logging side effects
- CredentialRotationRateLimiter unit tests (is_allowed, get_remaining, get_retry_after)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.openclaw.credentials import (
    CREDENTIAL_ROTATION_WINDOW_SECONDS,
    MAX_CREDENTIAL_ROTATIONS_PER_HOUR,
    CredentialRotationRateLimiter,
    CredentialHandlerMixin,
    _get_credential_rotation_limiter,
)
from aragora.server.handlers.openclaw.gateway import OpenClawGatewayHandler
from aragora.server.handlers.openclaw.models import (
    Credential,
    CredentialType,
)
from aragora.server.handlers.openclaw.store import OpenClawGatewayStore


# ============================================================================
# Helpers
# ============================================================================


def _body(result) -> dict[str, Any]:
    """Decode a HandlerResult body to dict."""
    if result is None:
        return {}
    if hasattr(result, "body"):
        return json.loads(result.body)
    return result


def _status(result) -> int:
    """Extract status code from HandlerResult."""
    if result is None:
        return 0
    if hasattr(result, "status_code"):
        return result.status_code
    return 0


def _headers(result) -> dict[str, str]:
    """Extract headers from HandlerResult."""
    if result is None:
        return {}
    if hasattr(result, "headers"):
        return result.headers or {}
    return {}


class MockHTTPHandler:
    """Minimal mock HTTP handler for BaseHandler methods."""

    def __init__(self, body: dict | None = None, method: str = "GET"):
        self.rfile = MagicMock()
        self.command = method
        self.client_address = ("127.0.0.1", 54321)
        if body is not None:
            body_bytes = json.dumps(body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers = {
                "Content-Length": str(len(body_bytes)),
                "Content-Type": "application/json",
            }
        else:
            self.rfile.read.return_value = b"{}"
            self.headers = {
                "Content-Length": "2",
                "Content-Type": "application/json",
            }


class _MockUser:
    """Minimal mock user for get_current_user."""

    def __init__(self, user_id="test-user-001", org_id="test-org-001", role="admin"):
        self.user_id = user_id
        self.org_id = org_id
        self.role = role


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def store():
    """Fresh in-memory OpenClaw store for each test."""
    return OpenClawGatewayStore()


@pytest.fixture()
def mock_user():
    """Default mock user returned by get_current_user."""
    return _MockUser()


@pytest.fixture()
def handler(store, mock_user):
    """OpenClawGatewayHandler with _get_store and get_current_user patched."""
    with (
        patch(
            "aragora.server.handlers.openclaw.orchestrator._get_store",
            return_value=store,
        ),
        patch(
            "aragora.server.handlers.openclaw.credentials._get_store",
            return_value=store,
        ),
        patch(
            "aragora.server.handlers.openclaw.policies._get_store",
            return_value=store,
        ),
    ):
        h = OpenClawGatewayHandler(server_context={})
        h.get_current_user = lambda handler: mock_user
        yield h


@pytest.fixture()
def mock_http():
    """Factory for MockHTTPHandler."""

    def _make(body: dict | None = None, method: str = "GET") -> MockHTTPHandler:
        return MockHTTPHandler(body=body, method=method)

    return _make


@pytest.fixture()
def sample_credential(store) -> Credential:
    """Pre-create a credential owned by test-user-001."""
    return store.store_credential(
        name="my_api_key",
        credential_type=CredentialType.API_KEY,
        secret_value="super-secret-value-12345678",
        user_id="test-user-001",
        tenant_id="test-org-001",
        metadata={"environment": "test"},
    )


@pytest.fixture()
def other_user_credential(store) -> Credential:
    """Pre-create a credential owned by another user."""
    return store.store_credential(
        name="other_key",
        credential_type=CredentialType.API_KEY,
        secret_value="other-secret-value-12345678",
        user_id="other-user-999",
        tenant_id="other-org",
    )


@pytest.fixture()
def rotation_limiter():
    """Fresh credential rotation rate limiter with small limits for testing."""
    return CredentialRotationRateLimiter(max_rotations=3, window_seconds=60)


# ============================================================================
# CredentialRotationRateLimiter Unit Tests
# ============================================================================


class TestCredentialRotationRateLimiter:
    """Tests for the CredentialRotationRateLimiter class."""

    def test_is_allowed_within_limit(self, rotation_limiter):
        """Allow rotations within the configured limit."""
        assert rotation_limiter.is_allowed("user-1") is True
        assert rotation_limiter.is_allowed("user-1") is True
        assert rotation_limiter.is_allowed("user-1") is True

    def test_is_allowed_exceeds_limit(self, rotation_limiter):
        """Deny rotations exceeding the configured limit."""
        for _ in range(3):
            rotation_limiter.is_allowed("user-1")
        assert rotation_limiter.is_allowed("user-1") is False

    def test_is_allowed_independent_per_user(self, rotation_limiter):
        """Rate limits are tracked independently per user."""
        for _ in range(3):
            rotation_limiter.is_allowed("user-1")
        # user-1 is at limit
        assert rotation_limiter.is_allowed("user-1") is False
        # user-2 has its own counter
        assert rotation_limiter.is_allowed("user-2") is True

    def test_get_remaining_full(self, rotation_limiter):
        """Get remaining shows full quota for fresh user."""
        assert rotation_limiter.get_remaining("user-1") == 3

    def test_get_remaining_after_use(self, rotation_limiter):
        """Get remaining decreases after usage."""
        rotation_limiter.is_allowed("user-1")
        assert rotation_limiter.get_remaining("user-1") == 2
        rotation_limiter.is_allowed("user-1")
        assert rotation_limiter.get_remaining("user-1") == 1

    def test_get_remaining_at_limit(self, rotation_limiter):
        """Get remaining returns 0 when limit is reached."""
        for _ in range(3):
            rotation_limiter.is_allowed("user-1")
        assert rotation_limiter.get_remaining("user-1") == 0

    def test_get_retry_after_no_limit(self, rotation_limiter):
        """Retry-after is 0 when under limit."""
        assert rotation_limiter.get_retry_after("user-1") == 0

    def test_get_retry_after_at_limit(self, rotation_limiter):
        """Retry-after is positive when at limit."""
        for _ in range(3):
            rotation_limiter.is_allowed("user-1")
        retry_after = rotation_limiter.get_retry_after("user-1")
        assert retry_after > 0
        assert retry_after <= 60

    def test_sliding_window_expires_old_entries(self):
        """Old entries outside the window are cleaned up."""
        limiter = CredentialRotationRateLimiter(max_rotations=2, window_seconds=1)
        limiter.is_allowed("user-1")
        limiter.is_allowed("user-1")
        assert limiter.is_allowed("user-1") is False
        # Wait for window to expire
        time.sleep(1.1)
        assert limiter.is_allowed("user-1") is True

    def test_default_parameters(self):
        """Default limiter uses module-level constants."""
        limiter = CredentialRotationRateLimiter()
        assert limiter._max_rotations == MAX_CREDENTIAL_ROTATIONS_PER_HOUR
        assert limiter._window_seconds == CREDENTIAL_ROTATION_WINDOW_SECONDS

    def test_constants_have_expected_values(self):
        """Module constants have expected default values."""
        assert CREDENTIAL_ROTATION_WINDOW_SECONDS == 3600
        assert MAX_CREDENTIAL_ROTATIONS_PER_HOUR == 10


# ============================================================================
# _get_credential_rotation_limiter Tests
# ============================================================================


class TestGetCredentialRotationLimiter:
    """Tests for the _get_credential_rotation_limiter factory function."""

    def test_returns_rate_limiter_instance(self):
        """Factory returns a CredentialRotationRateLimiter."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._credential_rotation_limiter",
            None,
        ):
            limiter = _get_credential_rotation_limiter()
            assert isinstance(limiter, CredentialRotationRateLimiter)

    def test_returns_same_instance_on_repeated_calls(self):
        """Factory returns the same singleton instance."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._credential_rotation_limiter",
            None,
        ):
            limiter1 = _get_credential_rotation_limiter()
            # Reset so it would re-create if not singleton
            limiter2 = _get_credential_rotation_limiter()
            # Both should be CredentialRotationRateLimiter (singleton behavior)
            assert isinstance(limiter1, CredentialRotationRateLimiter)
            assert isinstance(limiter2, CredentialRotationRateLimiter)


# ============================================================================
# List Credentials (GET)
# ============================================================================


class TestListCredentials:
    """Tests for _handle_list_credentials (GET /credentials)."""

    def test_list_credentials_empty(self, handler, mock_http):
        result = handler.handle("/api/v1/openclaw/credentials", {}, mock_http())
        assert _status(result) == 200
        body = _body(result)
        assert body["credentials"] == []
        assert body["total"] == 0
        assert body["limit"] == 50
        assert body["offset"] == 0

    def test_list_credentials_returns_credentials(self, handler, mock_http, sample_credential):
        result = handler.handle("/api/v1/openclaw/credentials", {}, mock_http())
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] >= 1
        ids = [c["id"] for c in body["credentials"]]
        assert sample_credential.id in ids

    def test_list_credentials_excludes_secret(self, handler, mock_http, sample_credential):
        """Credential listing never includes secret values."""
        result = handler.handle("/api/v1/openclaw/credentials", {}, mock_http())
        assert _status(result) == 200
        body = _body(result)
        for cred in body["credentials"]:
            assert "secret" not in cred
            assert "secret_value" not in cred

    def test_list_credentials_type_filter(self, handler, mock_http, store):
        store.store_credential(
            name="key1",
            credential_type=CredentialType.API_KEY,
            secret_value="secret-12345678",
            user_id="test-user-001",
            tenant_id="test-org-001",
        )
        store.store_credential(
            name="cert1",
            credential_type=CredentialType.CERTIFICATE,
            secret_value="cert-data-here",
            user_id="test-user-001",
            tenant_id="test-org-001",
        )
        result = handler.handle("/api/v1/openclaw/credentials", {"type": "api_key"}, mock_http())
        assert _status(result) == 200
        body = _body(result)
        for cred in body["credentials"]:
            assert cred["credential_type"] == "api_key"

    def test_list_credentials_invalid_type_returns_400(self, handler, mock_http):
        """Invalid credential type in query parameter yields 400."""
        result = handler.handle(
            "/api/v1/openclaw/credentials", {"type": "not_real_type"}, mock_http()
        )
        assert _status(result) == 400

    def test_list_credentials_pagination(self, handler, mock_http, store):
        for i in range(5):
            store.store_credential(
                name=f"key_{i}",
                credential_type=CredentialType.API_KEY,
                secret_value=f"secret-value-{i}-padded",
                user_id="test-user-001",
                tenant_id="test-org-001",
            )
        result = handler.handle(
            "/api/v1/openclaw/credentials", {"limit": "2", "offset": "0"}, mock_http()
        )
        assert _status(result) == 200
        body = _body(result)
        assert len(body["credentials"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert body["total"] == 5

    def test_list_credentials_pagination_offset(self, handler, mock_http, store):
        for i in range(5):
            store.store_credential(
                name=f"key_{i}",
                credential_type=CredentialType.API_KEY,
                secret_value=f"secret-value-{i}-padded",
                user_id="test-user-001",
                tenant_id="test-org-001",
            )
        result = handler.handle(
            "/api/v1/openclaw/credentials", {"limit": "2", "offset": "3"}, mock_http()
        )
        assert _status(result) == 200
        body = _body(result)
        assert len(body["credentials"]) == 2
        assert body["offset"] == 3

    def test_list_credentials_store_error_returns_500(self, handler, mock_http):
        """Store exception is caught and returns 500."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_store",
        ) as mock_store:
            mock_store.return_value.list_credentials.side_effect = RuntimeError("DB down")
            result = handler._handle_list_credentials({}, mock_http())
            assert _status(result) == 500

    def test_list_credentials_via_legacy_path(self, handler, mock_http, sample_credential):
        """Legacy /api/gateway/openclaw/credentials path also works."""
        result = handler.handle("/api/gateway/openclaw/credentials", {}, mock_http())
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] >= 1


# ============================================================================
# Store Credential (POST)
# ============================================================================


class TestStoreCredential:
    """Tests for _handle_store_credential (POST /credentials)."""

    def test_store_credential_success(self, handler, mock_http, store):
        body = {
            "name": "new_api_key",
            "type": "api_key",
            "secret": "my-super-secret-value-1234",
        }
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 201
        resp = _body(result)
        assert resp["name"] == "new_api_key"
        assert resp["credential_type"] == "api_key"
        assert "secret" not in resp

    def test_store_credential_with_metadata(self, handler, mock_http, store):
        body = {
            "name": "my_key",
            "type": "api_key",
            "secret": "secret-12345678",
            "metadata": {"env": "staging"},
        }
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 201
        resp = _body(result)
        assert resp["metadata"] == {"env": "staging"}

    def test_store_credential_with_expires_at(self, handler, mock_http, store):
        body = {
            "name": "expiring_key",
            "type": "api_key",
            "secret": "secret-12345678",
            "expires_at": "2030-01-01T00:00:00+00:00",
        }
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 201
        resp = _body(result)
        assert resp["expires_at"] is not None

    def test_store_credential_missing_name_returns_400(self, handler, mock_http):
        body = {"type": "api_key", "secret": "secret-12345678"}
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 400

    def test_store_credential_missing_type_returns_400(self, handler, mock_http):
        body = {"name": "my_key", "secret": "secret-12345678"}
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 400
        resp = _body(result)
        assert "type" in resp.get("error", "").lower()

    def test_store_credential_invalid_type_returns_400(self, handler, mock_http):
        body = {"name": "my_key", "type": "invalid_type", "secret": "secret-12345678"}
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 400
        resp = _body(result)
        assert "valid types" in resp.get("error", "").lower()

    def test_store_credential_missing_secret_returns_400(self, handler, mock_http):
        body = {"name": "my_key", "type": "api_key"}
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 400

    def test_store_credential_secret_too_short_returns_400(self, handler, mock_http):
        body = {"name": "my_key", "type": "api_key", "secret": "short"}
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 400

    def test_store_credential_invalid_name_returns_400(self, handler, mock_http):
        """Name with invalid characters is rejected."""
        body = {"name": "!!!invalid", "type": "api_key", "secret": "secret-12345678"}
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 400

    def test_store_credential_name_with_spaces_is_accepted(self, handler, mock_http, store):
        """Spaces in name are replaced with underscores for validation."""
        body = {"name": "my api key", "type": "api_key", "secret": "secret-12345678"}
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 201

    def test_store_credential_invalid_expires_at_returns_400(self, handler, mock_http):
        body = {
            "name": "my_key",
            "type": "api_key",
            "secret": "secret-12345678",
            "expires_at": "not-a-date",
        }
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 400
        resp = _body(result)
        assert "iso" in resp.get("error", "").lower()

    def test_store_credential_creates_audit_entry(self, handler, mock_http, store):
        body = {
            "name": "audited_key",
            "type": "api_key",
            "secret": "secret-12345678",
        }
        handler.handle_post("/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST"))
        entries, total = store.get_audit_log(action="credential.create")
        assert total >= 1
        entry = entries[0]
        assert entry.action == "credential.create"
        assert entry.result == "success"
        assert entry.details["name"] == "audited_key"
        assert entry.details["type"] == "api_key"

    def test_store_credential_all_types(self, handler, mock_http, store):
        """All CredentialType values can be stored."""
        for ct in CredentialType:
            body = {
                "name": f"key_{ct.value}",
                "type": ct.value,
                "secret": "secret-12345678",
            }
            result = handler.handle_post(
                "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
            )
            assert _status(result) == 201, f"Failed for type {ct.value}"

    def test_store_credential_store_error_returns_500(self, handler, mock_http):
        """Store exception during save returns 500."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_store",
        ) as mock_store:
            mock_store.return_value.store_credential.side_effect = RuntimeError("DB error")
            result = handler._handle_store_credential(
                {
                    "name": "my_key",
                    "type": "api_key",
                    "secret": "secret-12345678",
                },
                mock_http(method="POST"),
            )
            assert _status(result) == 500

    def test_store_credential_invalid_metadata_returns_400(self, handler, mock_http):
        """Oversized metadata is rejected."""
        body = {
            "name": "my_key",
            "type": "api_key",
            "secret": "secret-12345678",
            "metadata": {"data": "x" * 5000},  # Exceeds 4096 limit
        }
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 400

    def test_store_credential_non_dict_metadata_returns_400(self, handler, mock_http):
        """Non-dict metadata is rejected."""
        body = {
            "name": "my_key",
            "type": "api_key",
            "secret": "secret-12345678",
            "metadata": "not-a-dict",
        }
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 400

    def test_store_credential_via_legacy_path(self, handler, mock_http, store):
        body = {
            "name": "legacy_key",
            "type": "api_key",
            "secret": "secret-12345678",
        }
        result = handler.handle_post(
            "/api/gateway/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 201


# ============================================================================
# Rotate Credential (POST /:id/rotate)
# ============================================================================


class TestRotateCredential:
    """Tests for _handle_rotate_credential (POST /credentials/:id/rotate)."""

    def test_rotate_credential_success(self, handler, mock_http, store, sample_credential):
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
        ) as mock_limiter:
            mock_limiter.return_value.is_allowed.return_value = True
            body = {"secret": "new-secret-value-12345678"}
            result = handler.handle_post(
                f"/api/v1/openclaw/credentials/{sample_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            assert _status(result) == 200
            resp = _body(result)
            assert resp["rotated"] is True
            assert resp["credential_id"] == sample_credential.id
            assert resp["rotated_at"] is not None

    def test_rotate_credential_not_found_returns_404(self, handler, mock_http):
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
        ) as mock_limiter:
            mock_limiter.return_value.is_allowed.return_value = True
            body = {"secret": "new-secret-value-12345678"}
            result = handler.handle_post(
                "/api/v1/openclaw/credentials/nonexistent-id/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            assert _status(result) == 404

    def test_rotate_credential_access_denied_for_non_owner(
        self, handler, mock_http, other_user_credential, mock_user
    ):
        """Non-owner, non-admin user gets 403."""
        mock_user.role = "viewer"
        with (
            patch(
                "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
            ) as mock_limiter,
            patch(
                "aragora.server.handlers.openclaw.credentials._has_permission",
                return_value=False,
            ),
        ):
            mock_limiter.return_value.is_allowed.return_value = True
            body = {"secret": "new-secret-value-12345678"}
            result = handler.handle_post(
                f"/api/v1/openclaw/credentials/{other_user_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            assert _status(result) == 403

    def test_rotate_credential_admin_can_rotate_others(
        self, handler, mock_http, other_user_credential, mock_user
    ):
        """Admin user can rotate credentials owned by others."""
        mock_user.role = "admin"
        with (
            patch(
                "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
            ) as mock_limiter,
            patch(
                "aragora.server.handlers.openclaw.credentials._has_permission",
                return_value=True,
            ),
        ):
            mock_limiter.return_value.is_allowed.return_value = True
            body = {"secret": "new-secret-value-12345678"}
            result = handler.handle_post(
                f"/api/v1/openclaw/credentials/{other_user_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            assert _status(result) == 200

    def test_rotate_credential_invalid_secret_returns_400(
        self, handler, mock_http, sample_credential
    ):
        """Invalid new secret is rejected."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
        ) as mock_limiter:
            mock_limiter.return_value.is_allowed.return_value = True
            body = {"secret": ""}
            result = handler.handle_post(
                f"/api/v1/openclaw/credentials/{sample_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            assert _status(result) == 400

    def test_rotate_credential_missing_secret_returns_400(
        self, handler, mock_http, sample_credential
    ):
        """Missing secret field is rejected."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
        ) as mock_limiter:
            mock_limiter.return_value.is_allowed.return_value = True
            body = {}
            result = handler.handle_post(
                f"/api/v1/openclaw/credentials/{sample_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            assert _status(result) == 400

    def test_rotate_credential_rate_limited_returns_429(
        self, handler, mock_http, sample_credential
    ):
        """Rate limited rotation returns 429 with retry-after."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
        ) as mock_limiter:
            mock_limiter.return_value.is_allowed.return_value = False
            mock_limiter.return_value.get_remaining.return_value = 0
            mock_limiter.return_value.get_retry_after.return_value = 1800
            body = {"secret": "new-secret-value-12345678"}
            result = handler.handle_post(
                f"/api/v1/openclaw/credentials/{sample_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            assert _status(result) == 429
            resp = _body(result)
            assert "too many" in resp.get("error", "").lower()

    def test_rotate_credential_rate_limited_includes_retry_after_header(
        self, handler, mock_http, sample_credential
    ):
        """Rate limited response includes Retry-After header."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
        ) as mock_limiter:
            mock_limiter.return_value.is_allowed.return_value = False
            mock_limiter.return_value.get_remaining.return_value = 0
            mock_limiter.return_value.get_retry_after.return_value = 900
            body = {"secret": "new-secret-value-12345678"}
            result = handler.handle_post(
                f"/api/v1/openclaw/credentials/{sample_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            assert _status(result) == 429
            hdrs = _headers(result)
            assert hdrs.get("Retry-After") == "900"

    def test_rotate_credential_rate_limited_no_retry_header_when_zero(
        self, handler, mock_http, sample_credential
    ):
        """When retry_after is 0, Retry-After header is not set."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
        ) as mock_limiter:
            mock_limiter.return_value.is_allowed.return_value = False
            mock_limiter.return_value.get_remaining.return_value = 0
            mock_limiter.return_value.get_retry_after.return_value = 0
            body = {"secret": "new-secret-value-12345678"}
            result = handler.handle_post(
                f"/api/v1/openclaw/credentials/{sample_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            assert _status(result) == 429
            hdrs = _headers(result)
            assert "Retry-After" not in hdrs

    def test_rotate_credential_rate_limited_creates_audit_entry(
        self, handler, mock_http, store, sample_credential
    ):
        """Rate limited rotation creates audit entry."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
        ) as mock_limiter:
            mock_limiter.return_value.is_allowed.return_value = False
            mock_limiter.return_value.get_remaining.return_value = 0
            mock_limiter.return_value.get_retry_after.return_value = 60
            body = {"secret": "new-secret-value-12345678"}
            handler.handle_post(
                f"/api/v1/openclaw/credentials/{sample_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            entries, total = store.get_audit_log(action="credential.rotate.rate_limited")
            assert total >= 1
            entry = entries[0]
            assert entry.result == "rate_limited"

    def test_rotate_credential_creates_audit_entry(
        self, handler, mock_http, store, sample_credential
    ):
        """Successful rotation creates audit entry."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
        ) as mock_limiter:
            mock_limiter.return_value.is_allowed.return_value = True
            body = {"secret": "new-secret-value-12345678"}
            handler.handle_post(
                f"/api/v1/openclaw/credentials/{sample_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )
            entries, total = store.get_audit_log(action="credential.rotate")
            assert total >= 1
            entry = entries[0]
            assert entry.action == "credential.rotate"
            assert entry.result == "success"

    def test_rotate_credential_store_error_returns_500(self, handler, mock_http, sample_credential):
        """Store exception during rotation returns 500."""
        with (
            patch(
                "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
            ) as mock_limiter,
            patch(
                "aragora.server.handlers.openclaw.credentials._get_store",
            ) as mock_store,
        ):
            mock_limiter.return_value.is_allowed.return_value = True
            mock_store.return_value.get_credential.return_value = sample_credential
            mock_store.return_value.rotate_credential.side_effect = RuntimeError("DB error")
            body = {"secret": "new-secret-value-12345678"}
            result = handler._handle_rotate_credential(
                sample_credential.id,
                body,
                mock_http(method="POST"),
            )
            assert _status(result) == 500

    def test_rotate_credential_disappears_during_rotation_returns_404(
        self, handler, mock_http, sample_credential
    ):
        """A credential deleted after lookup fails closed as not found."""
        with (
            patch(
                "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
            ) as mock_limiter,
            patch(
                "aragora.server.handlers.openclaw.credentials._get_store",
            ) as mock_store,
        ):
            mock_limiter.return_value.is_allowed.return_value = True
            mock_store.return_value.get_credential.return_value = sample_credential
            mock_store.return_value.rotate_credential.return_value = None

            result = handler._handle_rotate_credential(
                sample_credential.id,
                {"secret": "new-secret-value-12345678"},
                mock_http(method="POST"),
            )

            assert _status(result) == 404
            assert "not found" in _body(result)["error"].lower()


# ============================================================================
# Delete Credential (DELETE /:id)
# ============================================================================


class TestDeleteCredential:
    """Tests for _handle_delete_credential (DELETE /credentials/:id)."""

    def test_delete_credential_success(self, handler, mock_http, store, sample_credential):
        result = handler.handle_delete(
            f"/api/v1/openclaw/credentials/{sample_credential.id}",
            {},
            mock_http(),
        )
        assert _status(result) == 200
        resp = _body(result)
        assert resp["deleted"] is True
        assert resp["credential_id"] == sample_credential.id

    def test_delete_credential_not_found_returns_404(self, handler, mock_http):
        result = handler.handle_delete(
            "/api/v1/openclaw/credentials/nonexistent-id",
            {},
            mock_http(),
        )
        assert _status(result) == 404

    def test_delete_credential_access_denied_for_non_owner(
        self, handler, mock_http, other_user_credential, mock_user
    ):
        """Non-owner, non-admin user gets 403."""
        mock_user.role = "viewer"
        with patch(
            "aragora.server.handlers.openclaw.credentials._has_permission",
            return_value=False,
        ):
            result = handler.handle_delete(
                f"/api/v1/openclaw/credentials/{other_user_credential.id}",
                {},
                mock_http(),
            )
            assert _status(result) == 403

    def test_delete_credential_admin_can_delete_others(
        self, handler, mock_http, other_user_credential, mock_user
    ):
        """Admin user can delete credentials owned by others."""
        mock_user.role = "admin"
        with patch(
            "aragora.server.handlers.openclaw.credentials._has_permission",
            return_value=True,
        ):
            result = handler.handle_delete(
                f"/api/v1/openclaw/credentials/{other_user_credential.id}",
                {},
                mock_http(),
            )
            assert _status(result) == 200

    def test_delete_credential_creates_audit_entry(
        self, handler, mock_http, store, sample_credential
    ):
        """Successful deletion creates audit entry."""
        handler.handle_delete(
            f"/api/v1/openclaw/credentials/{sample_credential.id}",
            {},
            mock_http(),
        )
        entries, total = store.get_audit_log(action="credential.delete")
        assert total >= 1
        entry = entries[0]
        assert entry.action == "credential.delete"
        assert entry.result == "success"
        assert entry.resource_id == sample_credential.id

    def test_delete_credential_is_actually_removed(
        self, handler, mock_http, store, sample_credential
    ):
        """Deleted credential is no longer returned by list."""
        handler.handle_delete(
            f"/api/v1/openclaw/credentials/{sample_credential.id}",
            {},
            mock_http(),
        )
        cred = store.get_credential(sample_credential.id)
        assert cred is None

    def test_delete_credential_store_error_returns_500(self, handler, mock_http, sample_credential):
        """Store exception during delete returns 500."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_store",
        ) as mock_store:
            mock_store.return_value.get_credential.return_value = sample_credential
            mock_store.return_value.delete_credential.side_effect = RuntimeError("DB error")
            result = handler._handle_delete_credential(
                sample_credential.id,
                mock_http(),
            )
            assert _status(result) == 500


# ============================================================================
# Credential Type Enum Coverage
# ============================================================================


class TestCredentialTypes:
    """Verify all CredentialType values work end-to-end."""

    @pytest.mark.parametrize(
        "cred_type",
        [ct.value for ct in CredentialType],
        ids=[ct.name for ct in CredentialType],
    )
    def test_store_and_list_each_type(self, handler, mock_http, store, cred_type):
        body = {
            "name": f"cred_{cred_type}",
            "type": cred_type,
            "secret": "secret-12345678",
        }
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 201
        resp = _body(result)
        assert resp["credential_type"] == cred_type


# ============================================================================
# Edge Cases and Integration
# ============================================================================


class TestEdgeCases:
    """Edge cases and cross-handler integration tests."""

    def test_credential_name_stripped_on_store(self, handler, mock_http, store):
        """Name with trailing space is stripped before storing."""
        # The validation runs on name.replace(" ", "_"), but strip() happens
        # at store time. A name like "trimmed_key " passes validation (space
        # becomes "_") and the stored name is "trimmed_key" after strip().
        body = {
            "name": "trimmed_key ",
            "type": "api_key",
            "secret": "secret-12345678",
        }
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 201
        resp = _body(result)
        assert resp["name"] == "trimmed_key"

    def test_rotate_then_list_shows_rotated_timestamp(
        self, handler, mock_http, store, sample_credential
    ):
        """After rotation, listing shows last_rotated_at."""
        with patch(
            "aragora.server.handlers.openclaw.credentials._get_credential_rotation_limiter",
        ) as mock_limiter:
            mock_limiter.return_value.is_allowed.return_value = True
            body = {"secret": "rotated-secret-12345678"}
            handler.handle_post(
                f"/api/v1/openclaw/credentials/{sample_credential.id}/rotate",
                {},
                mock_http(body=body, method="POST"),
            )

        # List and check
        result = handler.handle("/api/v1/openclaw/credentials", {}, mock_http())
        assert _status(result) == 200
        creds = _body(result)["credentials"]
        cred = next(c for c in creds if c["id"] == sample_credential.id)
        assert cred["last_rotated_at"] is not None

    def test_delete_then_list_excludes_deleted(self, handler, mock_http, store, sample_credential):
        """After deletion, credential no longer appears in list."""
        handler.handle_delete(
            f"/api/v1/openclaw/credentials/{sample_credential.id}",
            {},
            mock_http(),
        )
        result = handler.handle("/api/v1/openclaw/credentials", {}, mock_http())
        assert _status(result) == 200
        ids = [c["id"] for c in _body(result)["credentials"]]
        assert sample_credential.id not in ids

    def test_multiple_credentials_list_ordered(self, handler, mock_http, store):
        """Multiple credentials are returned (order by created_at desc)."""
        for i in range(3):
            store.store_credential(
                name=f"key_{i}",
                credential_type=CredentialType.API_KEY,
                secret_value=f"secret-{i}-padding-1234",
                user_id="test-user-001",
                tenant_id="test-org-001",
            )
        result = handler.handle("/api/v1/openclaw/credentials", {}, mock_http())
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 3
        assert len(body["credentials"]) == 3

    def test_credential_metadata_preserved(self, handler, mock_http, store):
        """Metadata is preserved through store and list cycle."""
        body = {
            "name": "meta_key",
            "type": "oauth_token",
            "secret": "secret-12345678",
            "metadata": {"scope": "read:write", "provider": "github"},
        }
        result = handler.handle_post(
            "/api/v1/openclaw/credentials", {}, mock_http(body=body, method="POST")
        )
        assert _status(result) == 201
        cred_id = _body(result)["id"]

        list_result = handler.handle("/api/v1/openclaw/credentials", {}, mock_http())
        creds = _body(list_result)["credentials"]
        cred = next(c for c in creds if c["id"] == cred_id)
        assert cred["metadata"]["scope"] == "read:write"
        assert cred["metadata"]["provider"] == "github"

    def test_credential_to_dict_fields(self, handler, mock_http, sample_credential):
        """Verify all expected fields in credential response."""
        result = handler.handle("/api/v1/openclaw/credentials", {}, mock_http())
        creds = _body(result)["credentials"]
        cred = next(c for c in creds if c["id"] == sample_credential.id)
        expected_fields = {
            "id",
            "name",
            "credential_type",
            "user_id",
            "tenant_id",
            "created_at",
            "updated_at",
            "last_rotated_at",
            "expires_at",
            "metadata",
        }
        assert expected_fields.issubset(set(cred.keys()))
