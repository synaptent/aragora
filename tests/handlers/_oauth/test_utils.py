"""Tests for aragora/server/handlers/_oauth/utils.py.

Covers all exported utilities:
- _maybe_await: coroutine vs plain value handling
- OAuthRateLimiterWrapper: backward-compat wrapper around OAuthRateLimiter
- _impl(): lazy module resolution from sys.modules
- TokenHealthStatus: enum values
- TokenHealthResult: dataclass + to_dict()
- TokenHealthChecker: expiration state machine (VALID / EXPIRING_SOON / EXPIRING_TODAY / EXPIRED / UNKNOWN)
- get_token_health_checker: singleton accessor
- OAuthStateDataExtractor: dict & object state access, metadata, to_dict()
- PermissionCheckResult: dataclass
- OAuthPermissionHelper: primary + fallback permission checks, RBAC fallback
- get_oauth_permission_helper: singleton accessor
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers._oauth.utils import (
    OAuthPermissionHelper,
    OAuthRateLimiterWrapper,
    OAuthStateDataExtractor,
    PermissionCheckResult,
    TokenHealthChecker,
    TokenHealthResult,
    TokenHealthStatus,
    _impl,
    _maybe_await,
    _oauth_limiter,
    get_oauth_permission_helper,
    get_token_health_checker,
)
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
    return json.loads(result.body)


def _status(result: object) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


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


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset module-level singletons between tests."""
    import aragora.server.handlers._oauth.utils as mod

    mod._token_health_checker = None
    mod._oauth_permission_helper = None
    yield
    mod._token_health_checker = None
    mod._oauth_permission_helper = None


# ===========================================================================
# _maybe_await
# ===========================================================================


class TestMaybeAwait:
    """Tests for the _maybe_await helper."""

    @pytest.mark.asyncio
    async def test_plain_value_returned_as_is(self):
        result = await _maybe_await(42)
        assert result == 42

    @pytest.mark.asyncio
    async def test_none_returned_as_is(self):
        result = await _maybe_await(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_string_returned_as_is(self):
        result = await _maybe_await("hello")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_dict_returned_as_is(self):
        d = {"key": "value"}
        result = await _maybe_await(d)
        assert result is d

    @pytest.mark.asyncio
    async def test_coroutine_is_awaited(self):
        async def coro():
            return "async_result"

        result = await _maybe_await(coro())
        assert result == "async_result"

    @pytest.mark.asyncio
    async def test_awaitable_returning_none(self):
        async def coro():
            return None

        result = await _maybe_await(coro())
        assert result is None


# ===========================================================================
# OAuthRateLimiterWrapper
# ===========================================================================


class TestOAuthRateLimiterWrapper:
    """Tests for the backward-compat rate limiter wrapper."""

    def test_is_allowed_returns_bool(self):
        result = _oauth_limiter.is_allowed("10.0.0.1")
        assert isinstance(result, bool)
        assert result is True

    def test_first_request_is_allowed(self):
        assert _oauth_limiter.is_allowed("10.0.0.2") is True

    def test_rpm_property_returns_int(self):
        rpm = _oauth_limiter.rpm
        assert isinstance(rpm, int)
        assert rpm > 0

    def test_different_keys_are_independent(self):
        assert _oauth_limiter.is_allowed("10.0.0.3", "auth_start") is True
        assert _oauth_limiter.is_allowed("10.0.0.4", "auth_start") is True

    def test_wrapper_delegates_to_global_limiter(self):
        """Verify the wrapper fetches the global limiter each call (not cached)."""
        wrapper = OAuthRateLimiterWrapper()
        # First call succeeds
        assert wrapper.is_allowed("10.0.0.5") is True

    def test_endpoint_type_passed_through(self):
        wrapper = OAuthRateLimiterWrapper()
        assert wrapper.is_allowed("10.0.0.6", endpoint_type="callback") is True

    def test_rpm_matches_auth_start_limit(self):
        """rpm should reflect the auth_start_limit from config."""
        wrapper = OAuthRateLimiterWrapper()
        from aragora.server.middleware.rate_limit.oauth_limiter import get_oauth_limiter

        limiter = get_oauth_limiter()
        assert wrapper.rpm == limiter.config.auth_start_limit


# ===========================================================================
# _impl()
# ===========================================================================


class TestImpl:
    """Tests for the _impl() lazy module resolver."""

    @pytest.fixture(autouse=True)
    def _ensure_impl_module_loaded(self):
        """Import _oauth_impl so it exists in sys.modules."""
        import aragora.server.handlers.oauth._oauth_impl  # noqa: F401

    def test_returns_module(self):
        result = _impl()
        assert isinstance(result, ModuleType)

    def test_returns_oauth_impl_module(self):
        result = _impl()
        assert result.__name__ == "aragora.server.handlers.oauth._oauth_impl"

    def test_module_has_expected_attributes(self):
        """_oauth_impl should re-export key names like _oauth_limiter."""
        mod = _impl()
        assert hasattr(mod, "_oauth_limiter")

    def test_returns_same_object_from_sys_modules(self):
        result = _impl()
        assert result is sys.modules["aragora.server.handlers.oauth._oauth_impl"]


# ===========================================================================
# TokenHealthStatus
# ===========================================================================


class TestTokenHealthStatus:
    """Tests for the TokenHealthStatus enum."""

    def test_valid_value(self):
        assert TokenHealthStatus.VALID.value == "valid"

    def test_expiring_soon_value(self):
        assert TokenHealthStatus.EXPIRING_SOON.value == "expiring_soon"

    def test_expiring_today_value(self):
        assert TokenHealthStatus.EXPIRING_TODAY.value == "expiring_today"

    def test_expired_value(self):
        assert TokenHealthStatus.EXPIRED.value == "expired"

    def test_unknown_value(self):
        assert TokenHealthStatus.UNKNOWN.value == "unknown"

    def test_all_values_unique(self):
        vals = [s.value for s in TokenHealthStatus]
        assert len(vals) == len(set(vals))

    def test_is_string_enum(self):
        assert isinstance(TokenHealthStatus.VALID, str)
        assert TokenHealthStatus.VALID == "valid"


# ===========================================================================
# TokenHealthResult
# ===========================================================================


class TestTokenHealthResult:
    """Tests for the TokenHealthResult dataclass."""

    def test_defaults(self):
        r = TokenHealthResult(status=TokenHealthStatus.VALID)
        assert r.expires_at is None
        assert r.seconds_remaining is None
        assert r.needs_refresh is False
        assert r.message == ""

    def test_to_dict_keys(self):
        r = TokenHealthResult(
            status=TokenHealthStatus.EXPIRED,
            expires_at=1000.0,
            seconds_remaining=0,
            needs_refresh=True,
            message="Token has expired",
        )
        d = r.to_dict()
        assert d["status"] == "expired"
        assert d["expires_at"] == 1000.0
        assert d["seconds_remaining"] == 0
        assert d["needs_refresh"] is True
        assert d["message"] == "Token has expired"

    def test_to_dict_with_defaults(self):
        r = TokenHealthResult(status=TokenHealthStatus.UNKNOWN)
        d = r.to_dict()
        assert d["status"] == "unknown"
        assert d["expires_at"] is None
        assert d["seconds_remaining"] is None
        assert d["needs_refresh"] is False
        assert d["message"] == ""


# ===========================================================================
# TokenHealthChecker
# ===========================================================================


class TestTokenHealthChecker:
    """Tests for the unified token health checker."""

    def test_none_expires_at_returns_unknown(self):
        checker = TokenHealthChecker()
        result = checker.check(None)
        assert result.status == TokenHealthStatus.UNKNOWN
        assert result.expires_at is None
        assert "No expiration" in result.message

    def test_expired_token(self):
        checker = TokenHealthChecker()
        now = 2000.0
        result = checker.check(expires_at=1000.0, current_time=now)
        assert result.status == TokenHealthStatus.EXPIRED
        assert result.seconds_remaining == 0
        assert result.needs_refresh is True
        assert result.expires_at == 1000.0

    def test_expired_exactly_at_zero(self):
        """Boundary: seconds_remaining == 0 should be EXPIRED."""
        checker = TokenHealthChecker()
        now = 1000.0
        result = checker.check(expires_at=1000.0, current_time=now)
        assert result.status == TokenHealthStatus.EXPIRED
        assert result.needs_refresh is True

    def test_expiring_soon_within_one_hour(self):
        checker = TokenHealthChecker()
        now = 1000.0
        # 30 minutes remaining (1800 seconds)
        result = checker.check(expires_at=now + 1800, current_time=now)
        assert result.status == TokenHealthStatus.EXPIRING_SOON
        assert result.needs_refresh is True
        assert result.seconds_remaining == 1800
        assert "minutes" in result.message

    def test_expiring_soon_boundary_at_threshold(self):
        """Boundary: exactly at the 1-hour threshold."""
        checker = TokenHealthChecker()
        now = 1000.0
        result = checker.check(expires_at=now + 3600, current_time=now)
        assert result.status == TokenHealthStatus.EXPIRING_SOON

    def test_expiring_today_within_24_hours(self):
        checker = TokenHealthChecker()
        now = 1000.0
        # 12 hours remaining
        remaining = 12 * 3600
        result = checker.check(expires_at=now + remaining, current_time=now)
        assert result.status == TokenHealthStatus.EXPIRING_TODAY
        assert result.needs_refresh is False
        assert result.seconds_remaining == remaining
        assert "hours" in result.message

    def test_expiring_today_boundary_at_threshold(self):
        """Boundary: exactly at the 24-hour threshold."""
        checker = TokenHealthChecker()
        now = 1000.0
        result = checker.check(expires_at=now + 86400, current_time=now)
        assert result.status == TokenHealthStatus.EXPIRING_TODAY

    def test_valid_token_well_in_future(self):
        checker = TokenHealthChecker()
        now = 1000.0
        # 7 days remaining
        remaining = 7 * 86400
        result = checker.check(expires_at=now + remaining, current_time=now)
        assert result.status == TokenHealthStatus.VALID
        assert result.needs_refresh is False
        assert result.seconds_remaining == remaining
        assert "valid" in result.message.lower()

    def test_valid_just_past_24h_threshold(self):
        """Just past the 24-hour threshold should be VALID."""
        checker = TokenHealthChecker()
        now = 1000.0
        result = checker.check(expires_at=now + 86401, current_time=now)
        assert result.status == TokenHealthStatus.VALID

    def test_custom_thresholds(self):
        """Custom thresholds should shift the boundaries."""
        checker = TokenHealthChecker(
            expiring_soon_threshold=600,  # 10 minutes
            expiring_today_threshold=7200,  # 2 hours
        )
        now = 1000.0

        # 5 minutes remaining -> EXPIRING_SOON
        result = checker.check(expires_at=now + 300, current_time=now)
        assert result.status == TokenHealthStatus.EXPIRING_SOON

        # 1 hour remaining -> EXPIRING_TODAY (under 2h threshold)
        result = checker.check(expires_at=now + 3600, current_time=now)
        assert result.status == TokenHealthStatus.EXPIRING_TODAY

        # 3 hours remaining -> VALID (over 2h threshold)
        result = checker.check(expires_at=now + 10800, current_time=now)
        assert result.status == TokenHealthStatus.VALID

    def test_uses_real_time_when_no_current_time(self):
        """When current_time is omitted, time.time() is used."""
        checker = TokenHealthChecker()
        far_future = time.time() + 1_000_000
        result = checker.check(expires_at=far_future)
        assert result.status == TokenHealthStatus.VALID

    def test_negative_seconds_remaining_is_expired(self):
        checker = TokenHealthChecker()
        result = checker.check(expires_at=500.0, current_time=1000.0)
        assert result.status == TokenHealthStatus.EXPIRED
        assert result.seconds_remaining == 0


# ===========================================================================
# get_token_health_checker singleton
# ===========================================================================


class TestGetTokenHealthChecker:
    """Tests for the singleton accessor."""

    def test_returns_token_health_checker(self):
        checker = get_token_health_checker()
        assert isinstance(checker, TokenHealthChecker)

    def test_singleton_returns_same_instance(self):
        c1 = get_token_health_checker()
        c2 = get_token_health_checker()
        assert c1 is c2

    def test_default_thresholds(self):
        checker = get_token_health_checker()
        assert checker.expiring_soon_threshold == 3600
        assert checker.expiring_today_threshold == 86400


# ===========================================================================
# OAuthStateDataExtractor
# ===========================================================================


class TestOAuthStateDataExtractor:
    """Tests for safe state data extraction."""

    # --- Dict-based state ---

    def test_get_from_dict(self):
        ext = OAuthStateDataExtractor({"tenant_id": "t1", "user_id": "u1"})
        assert ext.get("tenant_id") == "t1"
        assert ext.get("user_id") == "u1"

    def test_get_missing_from_dict_returns_default(self):
        ext = OAuthStateDataExtractor({"tenant_id": "t1"})
        assert ext.get("missing") is None
        assert ext.get("missing", "fallback") == "fallback"

    def test_get_from_metadata_dict(self):
        state = {"metadata": {"user_id": "u2", "org": "org1"}}
        ext = OAuthStateDataExtractor(state)
        assert ext.get_from_metadata("user_id") == "u2"
        assert ext.get_from_metadata("org") == "org1"
        assert ext.get_from_metadata("missing") is None

    def test_get_from_metadata_missing_metadata(self):
        ext = OAuthStateDataExtractor({"tenant_id": "t1"})
        assert ext.get_from_metadata("user_id") is None

    # --- Object-based state ---

    def test_get_from_object(self):
        @dataclass
        class State:
            tenant_id: str = "t1"
            user_id: str = "u1"

        ext = OAuthStateDataExtractor(State())
        assert ext.get("tenant_id") == "t1"
        assert ext.get("user_id") == "u1"

    def test_get_missing_from_object(self):
        @dataclass
        class State:
            tenant_id: str = "t1"

        ext = OAuthStateDataExtractor(State())
        assert ext.get("missing") is None
        assert ext.get("missing", "fb") == "fb"

    def test_get_from_metadata_object(self):
        @dataclass
        class Meta:
            user_id: str = "u3"

        @dataclass
        class State:
            metadata: Meta = None

        s = State(metadata=Meta())
        ext = OAuthStateDataExtractor(s)
        assert ext.get_from_metadata("user_id") == "u3"

    def test_get_from_metadata_object_dict_metadata(self):
        """Object state with dict metadata."""

        @dataclass
        class State:
            metadata: dict = None

        s = State(metadata={"user_id": "u4"})
        ext = OAuthStateDataExtractor(s)
        assert ext.get_from_metadata("user_id") == "u4"

    # --- None state ---

    def test_none_state_returns_defaults(self):
        ext = OAuthStateDataExtractor(None)
        assert ext.get("tenant_id") is None
        assert ext.get("tenant_id", "def") == "def"
        assert ext.get_from_metadata("user_id") is None
        assert ext.get_from_metadata("user_id", "def") == "def"

    # --- Convenience methods ---

    def test_get_tenant_id_direct(self):
        ext = OAuthStateDataExtractor({"tenant_id": "t5"})
        assert ext.get_tenant_id() == "t5"

    def test_get_tenant_id_from_metadata(self):
        ext = OAuthStateDataExtractor({"metadata": {"tenant_id": "t6"}})
        assert ext.get_tenant_id() == "t6"

    def test_get_tenant_id_fallback_to_org_id(self):
        ext = OAuthStateDataExtractor({"org_id": "org7"})
        assert ext.get_tenant_id() == "org7"

    def test_get_tenant_id_org_id_from_metadata(self):
        ext = OAuthStateDataExtractor({"metadata": {"org_id": "org8"}})
        assert ext.get_tenant_id() == "org8"

    def test_get_tenant_id_none_when_missing(self):
        ext = OAuthStateDataExtractor({})
        assert ext.get_tenant_id() is None

    def test_get_user_id_direct(self):
        ext = OAuthStateDataExtractor({"user_id": "u9"})
        assert ext.get_user_id() == "u9"

    def test_get_user_id_from_metadata(self):
        ext = OAuthStateDataExtractor({"metadata": {"user_id": "u10"}})
        assert ext.get_user_id() == "u10"

    def test_get_user_id_none_when_missing(self):
        ext = OAuthStateDataExtractor({})
        assert ext.get_user_id() is None

    def test_get_redirect_url(self):
        ext = OAuthStateDataExtractor({"redirect_url": "https://example.com"})
        assert ext.get_redirect_url() == "https://example.com"

    def test_get_redirect_url_default(self):
        ext = OAuthStateDataExtractor({})
        assert ext.get_redirect_url() == ""
        assert ext.get_redirect_url(default="/home") == "/home"

    def test_get_redirect_url_falsy_falls_back_to_default(self):
        """If redirect_url is empty string, should return the default."""
        ext = OAuthStateDataExtractor({"redirect_url": ""})
        assert ext.get_redirect_url(default="/fallback") == "/fallback"

    def test_get_workspace_id_direct(self):
        ext = OAuthStateDataExtractor({"workspace_id": "ws1"})
        assert ext.get_workspace_id() == "ws1"

    def test_get_workspace_id_from_metadata(self):
        ext = OAuthStateDataExtractor({"metadata": {"workspace_id": "ws2"}})
        assert ext.get_workspace_id() == "ws2"

    def test_get_workspace_id_none(self):
        ext = OAuthStateDataExtractor({})
        assert ext.get_workspace_id() is None

    # --- to_dict ---

    def test_to_dict_from_dict_state(self):
        state = {"tenant_id": "t1", "user_id": "u1", "extra": "val"}
        ext = OAuthStateDataExtractor(state)
        d = ext.to_dict()
        assert d == state
        # Should be a copy, not same object
        assert d is not state

    def test_to_dict_from_none_state(self):
        ext = OAuthStateDataExtractor(None)
        assert ext.to_dict() == {}

    def test_to_dict_from_object_state(self):
        @dataclass
        class State:
            tenant_id: str = "t1"
            user_id: str = "u1"
            redirect_url: str = "/home"

        ext = OAuthStateDataExtractor(State())
        d = ext.to_dict()
        assert d["tenant_id"] == "t1"
        assert d["user_id"] == "u1"
        assert d["redirect_url"] == "/home"

    def test_to_dict_from_object_skips_none_attrs(self):
        @dataclass
        class State:
            tenant_id: str = None
            user_id: str = "u2"

        ext = OAuthStateDataExtractor(State())
        d = ext.to_dict()
        assert "tenant_id" not in d
        assert d["user_id"] == "u2"

    def test_to_dict_from_object_includes_metadata(self):
        @dataclass
        class State:
            metadata: dict = None

        ext = OAuthStateDataExtractor(State(metadata={"k": "v"}))
        d = ext.to_dict()
        assert d["metadata"] == {"k": "v"}

    def test_tenant_id_direct_takes_priority_over_metadata(self):
        """Direct tenant_id should be preferred over metadata tenant_id."""
        ext = OAuthStateDataExtractor(
            {
                "tenant_id": "direct",
                "metadata": {"tenant_id": "meta"},
            }
        )
        assert ext.get_tenant_id() == "direct"


# ===========================================================================
# PermissionCheckResult
# ===========================================================================


class TestPermissionCheckResult:
    """Tests for the PermissionCheckResult dataclass."""

    def test_defaults(self):
        r = PermissionCheckResult(allowed=True)
        assert r.allowed is True
        assert r.error_response is None
        assert r.permission_used == ""
        assert r.fallback_used is False

    def test_denied(self):
        r = PermissionCheckResult(
            allowed=False,
            error_response={"error": "forbidden"},
            permission_used="oauth.install",
            fallback_used=False,
        )
        assert r.allowed is False
        assert r.error_response == {"error": "forbidden"}
        assert r.permission_used == "oauth.install"

    def test_fallback_used(self):
        r = PermissionCheckResult(
            allowed=True,
            permission_used="connectors.authorize",
            fallback_used=True,
        )
        assert r.fallback_used is True


# ===========================================================================
# OAuthPermissionHelper
# ===========================================================================


class TestOAuthPermissionHelper:
    """Tests for unified OAuth permission checking."""

    def test_primary_permission_allowed_via_handler(self):
        """Handler._check_permission returns None -> allowed."""
        helper = OAuthPermissionHelper()
        handler = MagicMock()
        handler._check_permission.return_value = None
        auth_ctx = MagicMock()

        result = helper.check(handler, auth_ctx, "oauth.install")

        assert result.allowed is True
        assert result.permission_used == "oauth.install"
        assert result.fallback_used is False
        handler._check_permission.assert_called_once_with(auth_ctx, "oauth.install", None)

    def test_primary_permission_denied_no_fallback(self):
        """Handler._check_permission returns error -> denied (no fallback)."""
        helper = OAuthPermissionHelper()
        handler = MagicMock()
        error_resp = MagicMock()
        handler._check_permission.return_value = error_resp
        auth_ctx = MagicMock()

        result = helper.check(handler, auth_ctx, "oauth.install")

        assert result.allowed is False
        assert result.error_response is error_resp

    def test_fallback_permission_used_when_primary_denied(self):
        """Primary denied -> fallback allowed."""
        helper = OAuthPermissionHelper()
        handler = MagicMock()
        error_resp = MagicMock()
        # Primary returns error, fallback returns None (allowed)
        handler._check_permission.side_effect = [error_resp, None]
        auth_ctx = MagicMock()

        result = helper.check(
            handler,
            auth_ctx,
            "oauth.install",
            fallback_permission="connectors.authorize",
        )

        assert result.allowed is True
        assert result.permission_used == "connectors.authorize"
        assert result.fallback_used is True

    def test_both_primary_and_fallback_denied(self):
        """Both primary and fallback denied -> denied with fallback error."""
        helper = OAuthPermissionHelper()
        handler = MagicMock()
        error1 = MagicMock(name="error1")
        error2 = MagicMock(name="error2")
        handler._check_permission.side_effect = [error1, error2]
        auth_ctx = MagicMock()

        result = helper.check(
            handler,
            auth_ctx,
            "oauth.install",
            fallback_permission="connectors.authorize",
        )

        assert result.allowed is False
        # error_response should be the fallback's error
        assert result.error_response is error2

    def test_primary_raises_exception_skips_fallback(self):
        """Primary raises ValueError -> error stays None -> fallback NOT tried.

        The code checks ``if fallback_permission and error is not None``.
        When the primary raises, error stays None, so the fallback branch
        is skipped and the result is denied.
        """
        helper = OAuthPermissionHelper()
        handler = MagicMock()
        handler._check_permission.side_effect = ValueError("bad")
        auth_ctx = MagicMock()

        result = helper.check(
            handler,
            auth_ctx,
            "oauth.install",
            fallback_permission="connectors.authorize",
        )

        assert result.allowed is False
        assert result.error_response is None

    def test_primary_raises_no_fallback(self):
        """Primary raises exception, no fallback -> denied."""
        helper = OAuthPermissionHelper()
        handler = MagicMock()
        handler._check_permission.side_effect = TypeError("nope")
        auth_ctx = MagicMock()

        result = helper.check(handler, auth_ctx, "oauth.install")

        assert result.allowed is False
        assert result.error_response is None  # No error set when exception occurred

    def test_resource_id_passed_through(self):
        """resource_id should be forwarded to _check_permission."""
        helper = OAuthPermissionHelper()
        handler = MagicMock()
        handler._check_permission.return_value = None
        auth_ctx = MagicMock()

        result = helper.check(
            handler,
            auth_ctx,
            "oauth.install",
            resource_id="res-123",
        )

        assert result.allowed is True
        handler._check_permission.assert_called_once_with(auth_ctx, "oauth.install", "res-123")

    def test_handler_without_check_permission_uses_rbac_fallback(self):
        """Handler without _check_permission -> falls through to RBAC checker."""
        helper = OAuthPermissionHelper()
        handler = object()  # No _check_permission attribute
        auth_ctx = MagicMock()

        mock_checker = MagicMock()
        mock_perm_result = MagicMock()
        mock_perm_result.allowed = True
        mock_checker.check_permission.return_value = mock_perm_result

        with patch(
            "aragora.rbac.checker.get_permission_checker",
            return_value=mock_checker,
        ):
            result = helper.check(handler, auth_ctx, "oauth.install")

        assert result.allowed is True
        assert result.permission_used == "oauth.install"

    def test_check_single_permission_rbac_allowed(self):
        """_check_single_permission falls back to RBAC checker when handler has no method."""
        helper = OAuthPermissionHelper()
        handler = object()  # No _check_permission
        auth_ctx = MagicMock()

        mock_checker = MagicMock()
        mock_perm_result = MagicMock()
        mock_perm_result.allowed = True
        mock_checker.check_permission.return_value = mock_perm_result

        with patch(
            "aragora.rbac.checker.get_permission_checker",
            return_value=mock_checker,
        ):
            error = helper._check_single_permission(handler, auth_ctx, "oauth.install", None)

        assert error is None  # None means allowed

    def test_check_single_permission_rbac_denied(self):
        """_check_single_permission returns 403 when RBAC denies."""
        helper = OAuthPermissionHelper()
        handler = object()  # No _check_permission
        auth_ctx = MagicMock()

        mock_checker = MagicMock()
        mock_perm_result = MagicMock()
        mock_perm_result.allowed = False
        mock_checker.check_permission.return_value = mock_perm_result

        with patch(
            "aragora.rbac.checker.get_permission_checker",
            return_value=mock_checker,
        ):
            error = helper._check_single_permission(handler, auth_ctx, "oauth.install", None)

        assert error is not None
        assert _status(error) == 403
        body = _body(error)
        assert body["error"] == "forbidden"

    def test_check_single_permission_rbac_import_error_allows(self):
        """When RBAC checker raises ImportError internally, allow by default.

        The local import ``from aragora.rbac.checker import get_permission_checker``
        is wrapped in a try/except ImportError inside _check_single_permission.
        We simulate this by making the checker itself raise ImportError.
        """
        helper = OAuthPermissionHelper()
        handler = object()  # No _check_permission
        auth_ctx = MagicMock()

        with patch(
            "aragora.rbac.checker.get_permission_checker",
            side_effect=ImportError("no rbac"),
        ):
            error = helper._check_single_permission(handler, auth_ctx, "oauth.install", None)

        assert error is None  # Allow if no checker available

    def test_primary_exception_types_caught(self):
        """All documented exception types should be caught on primary."""
        helper = OAuthPermissionHelper()
        auth_ctx = MagicMock()

        for exc_cls in (ValueError, AttributeError, TypeError, KeyError, ImportError):
            handler = MagicMock()
            handler._check_permission.side_effect = exc_cls("test")

            result = helper.check(handler, auth_ctx, "perm")
            assert result.allowed is False

    def test_fallback_exception_types_caught(self):
        """All documented exception types should be caught on fallback."""
        helper = OAuthPermissionHelper()
        auth_ctx = MagicMock()

        for exc_cls in (ValueError, AttributeError, TypeError, KeyError, ImportError):
            handler = MagicMock()
            error_resp = MagicMock()
            handler._check_permission.side_effect = [error_resp, exc_cls("test")]

            result = helper.check(
                handler,
                auth_ctx,
                "perm",
                fallback_permission="fallback",
            )
            assert result.allowed is False


# ===========================================================================
# get_oauth_permission_helper singleton
# ===========================================================================


class TestGetOAuthPermissionHelper:
    """Tests for the singleton accessor."""

    def test_returns_permission_helper(self):
        helper = get_oauth_permission_helper()
        assert isinstance(helper, OAuthPermissionHelper)

    def test_singleton_returns_same_instance(self):
        h1 = get_oauth_permission_helper()
        h2 = get_oauth_permission_helper()
        assert h1 is h2


# ===========================================================================
# OAuthHandlerProtocol (structural test)
# ===========================================================================


class TestOAuthHandlerProtocol:
    """Verify the Protocol is importable and has expected methods."""

    def test_protocol_importable(self):
        from aragora.server.handlers._oauth.utils import OAuthHandlerProtocol

        assert OAuthHandlerProtocol is not None

    def test_protocol_has_expected_methods(self):
        from aragora.server.handlers._oauth.utils import OAuthHandlerProtocol

        expected = [
            "_get_user_store",
            "_redirect_with_error",
            "_redirect_with_tokens",
            "_check_permission",
            "_complete_oauth_flow",
            "_find_user_by_oauth",
            "_link_oauth_to_user",
            "_create_oauth_user",
            "_handle_account_linking",
            "read_json_body",
            "_handle_google_auth_start",
            "_handle_github_auth_start",
            "_handle_microsoft_auth_start",
            "_handle_apple_auth_start",
            "_handle_oidc_auth_start",
            "_handle_google_callback",
            "_handle_github_callback",
            "_handle_microsoft_callback",
            "_handle_apple_callback",
            "_handle_oidc_callback",
        ]
        for name in expected:
            assert hasattr(OAuthHandlerProtocol, name), f"Missing method: {name}"


# ===========================================================================
# _IMPL_MODULE constant
# ===========================================================================


class TestImplModuleConstant:
    """Tests for the _IMPL_MODULE constant."""

    def test_value(self):
        from aragora.server.handlers._oauth.utils import _IMPL_MODULE

        assert _IMPL_MODULE == "aragora.server.handlers.oauth._oauth_impl"

    def test_module_exists_in_sys_modules_after_import(self):
        """The _oauth_impl module is available in sys.modules after importing it."""
        import aragora.server.handlers.oauth._oauth_impl  # noqa: F401
        from aragora.server.handlers._oauth.utils import _IMPL_MODULE

        assert _IMPL_MODULE in sys.modules
