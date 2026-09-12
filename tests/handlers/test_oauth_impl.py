"""Tests for the _oauth_impl backward-compatibility shim module.

Covers:
- Re-exported symbols (OAuthHandler, config functions, models, state management)
- _validate_redirect_url() with various URL schemes, hosts, subdomains, edge cases
- _validate_state() wrapper behavior
- Module-level constants and URL endpoints
- OAuthUserInfo and _get_param models
- State management re-exports (_OAUTH_STATES, _STATE_TTL_SECONDS, etc.)
- __all__ correctness
"""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


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
# Import the module under test
# ---------------------------------------------------------------------------

import aragora.server.handlers.oauth._oauth_impl as _oauth_impl


# ============================================================================
# Re-export verification tests
# ============================================================================


class TestReExports:
    """Verify all expected names are re-exported from _oauth_impl."""

    def test_oauth_handler_reexported(self):
        assert hasattr(_oauth_impl, "OAuthHandler")

    def test_oauth_limiter_reexported(self):
        assert hasattr(_oauth_impl, "_oauth_limiter")

    def test_create_span_reexported(self):
        assert hasattr(_oauth_impl, "create_span")

    def test_add_span_attributes_reexported(self):
        assert hasattr(_oauth_impl, "add_span_attributes")

    def test_validate_oauth_config_reexported(self):
        assert callable(_oauth_impl.validate_oauth_config)

    def test_oauth_user_info_reexported(self):
        assert hasattr(_oauth_impl, "OAuthUserInfo")

    def test_get_param_reexported(self):
        assert callable(_oauth_impl._get_param)

    def test_oauth_states_reexported(self):
        assert hasattr(_oauth_impl, "_OAUTH_STATES")

    def test_state_ttl_seconds_reexported(self):
        assert hasattr(_oauth_impl, "_STATE_TTL_SECONDS")

    def test_max_oauth_states_reexported(self):
        assert hasattr(_oauth_impl, "MAX_OAUTH_STATES")

    def test_cleanup_expired_states_reexported(self):
        assert callable(_oauth_impl._cleanup_expired_states)

    def test_generate_state_reexported(self):
        assert callable(_oauth_impl._generate_state)

    def test_validate_state_internal_reexported(self):
        assert callable(_oauth_impl._validate_state_internal)

    def test_oauth_states_view_reexported(self):
        assert hasattr(_oauth_impl, "_OAuthStatesView")


# ============================================================================
# Config function re-export tests
# ============================================================================


class TestConfigFunctionReExports:
    """Verify all config helper functions are re-exported."""

    @pytest.mark.parametrize(
        "name",
        [
            "_get_secret",
            "_is_production",
            "_get_google_client_id",
            "_get_google_client_secret",
            "_get_github_client_id",
            "_get_github_client_secret",
            "_get_microsoft_client_id",
            "_get_microsoft_client_secret",
            "_get_microsoft_tenant",
            "_get_apple_client_id",
            "_get_apple_team_id",
            "_get_apple_key_id",
            "_get_apple_private_key",
            "_get_oidc_issuer",
            "_get_oidc_client_id",
            "_get_oidc_client_secret",
            "_get_google_redirect_uri",
            "_get_github_redirect_uri",
            "_get_microsoft_redirect_uri",
            "_get_apple_redirect_uri",
            "_get_oidc_redirect_uri",
            "_get_oauth_success_url",
            "_get_oauth_error_url",
            "_get_allowed_redirect_hosts",
        ],
    )
    def test_config_function_exists(self, name):
        assert hasattr(_oauth_impl, name), f"{name} not found on _oauth_impl"
        assert callable(getattr(_oauth_impl, name))


# ============================================================================
# Config constant re-export tests
# ============================================================================


class TestConfigConstantReExports:
    """Verify module-level config constants are re-exported."""

    @pytest.mark.parametrize(
        "name",
        [
            "_IS_PRODUCTION",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GITHUB_CLIENT_ID",
            "GITHUB_CLIENT_SECRET",
            "GOOGLE_REDIRECT_URI",
            "GITHUB_REDIRECT_URI",
            "OAUTH_SUCCESS_URL",
            "OAUTH_ERROR_URL",
            "ALLOWED_OAUTH_REDIRECT_HOSTS",
        ],
    )
    def test_constant_exists(self, name):
        assert hasattr(_oauth_impl, name), f"{name} not found on _oauth_impl"


# ============================================================================
# URL endpoint constant re-export tests
# ============================================================================


class TestURLEndpointReExports:
    """Verify OAuth provider URL constants are re-exported."""

    def test_google_auth_url(self):
        assert _oauth_impl.GOOGLE_AUTH_URL == "https://accounts.google.com/o/oauth2/v2/auth"

    def test_google_token_url(self):
        assert _oauth_impl.GOOGLE_TOKEN_URL == "https://oauth2.googleapis.com/token"

    def test_google_userinfo_url(self):
        assert _oauth_impl.GOOGLE_USERINFO_URL == "https://www.googleapis.com/oauth2/v2/userinfo"

    def test_github_auth_url(self):
        assert _oauth_impl.GITHUB_AUTH_URL == "https://github.com/login/oauth/authorize"

    def test_github_token_url(self):
        assert _oauth_impl.GITHUB_TOKEN_URL == "https://github.com/login/oauth/access_token"

    def test_github_userinfo_url(self):
        assert _oauth_impl.GITHUB_USERINFO_URL == "https://api.github.com/user"

    def test_github_emails_url(self):
        assert _oauth_impl.GITHUB_EMAILS_URL == "https://api.github.com/user/emails"

    def test_microsoft_auth_url_template(self):
        assert "{tenant}" in _oauth_impl.MICROSOFT_AUTH_URL_TEMPLATE

    def test_microsoft_token_url_template(self):
        assert "{tenant}" in _oauth_impl.MICROSOFT_TOKEN_URL_TEMPLATE

    def test_microsoft_userinfo_url(self):
        assert _oauth_impl.MICROSOFT_USERINFO_URL == "https://graph.microsoft.com/v1.0/me"

    def test_apple_auth_url(self):
        assert _oauth_impl.APPLE_AUTH_URL == "https://appleid.apple.com/auth/authorize"

    def test_apple_token_url(self):
        assert _oauth_impl.APPLE_TOKEN_URL == "https://appleid.apple.com/auth/token"

    def test_apple_keys_url(self):
        assert _oauth_impl.APPLE_KEYS_URL == "https://appleid.apple.com/auth/keys"


# ============================================================================
# _validate_redirect_url tests
# ============================================================================


class TestValidateRedirectUrl:
    """Test _validate_redirect_url() with various inputs."""

    def test_allowed_https_host(self):
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("https://example.com/callback") is True

    def test_allowed_http_host(self):
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"localhost"}),
        ):
            assert _oauth_impl._validate_redirect_url("http://localhost/callback") is True

    def test_disallowed_host(self):
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("https://evil.com/callback") is False

    def test_subdomain_matching(self):
        """Subdomain of allowed host should be allowed."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("https://sub.example.com/callback") is True

    def test_deeply_nested_subdomain_matching(self):
        """Deeply nested subdomain of allowed host should be allowed."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("https://a.b.c.example.com/path") is True

    def test_ftp_scheme_blocked(self):
        """Non http/https schemes should be blocked."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("ftp://example.com/file") is False

    def test_javascript_scheme_blocked(self):
        """javascript: scheme must be blocked."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("javascript:alert(1)") is False

    def test_data_scheme_blocked(self):
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("data:text/html,<h1>hi</h1>") is False

    def test_empty_url(self):
        """Empty URL should return False."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("") is False

    def test_url_no_host(self):
        """URL without a host should return False."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("https://") is False

    def test_host_case_insensitive(self):
        """Host matching should be case-insensitive."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("https://EXAMPLE.COM/path") is True

    def test_empty_allowed_hosts(self):
        """When allowlist is empty, all hosts should be rejected."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset(),
        ):
            assert _oauth_impl._validate_redirect_url("https://example.com/callback") is False

    def test_multiple_allowed_hosts(self):
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com", "myapp.io"}),
        ):
            assert _oauth_impl._validate_redirect_url("https://example.com/cb") is True
            assert _oauth_impl._validate_redirect_url("https://myapp.io/cb") is True
            assert _oauth_impl._validate_redirect_url("https://other.com/cb") is False

    def test_localhost_with_port(self):
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"localhost"}),
        ):
            assert _oauth_impl._validate_redirect_url("http://localhost:3000/callback") is True

    def test_ip_address_allowed(self):
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"127.0.0.1"}),
        ):
            assert _oauth_impl._validate_redirect_url("http://127.0.0.1:8080/callback") is True

    def test_ip_address_not_allowed(self):
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"127.0.0.1"}),
        ):
            assert _oauth_impl._validate_redirect_url("http://192.168.1.1/callback") is False

    def test_partial_host_match_not_allowed(self):
        """A host that ends with the allowed host string but is not a subdomain should fail."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            # "notexample.com" ends with "example.com" but is NOT a subdomain
            # The code checks for host.endswith(f".{allowed}"), so this should fail
            assert _oauth_impl._validate_redirect_url("https://notexample.com/callback") is False

    def test_exception_in_url_parsing_returns_false(self):
        """If _get_allowed_redirect_hosts raises, should return False gracefully."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            side_effect=AttributeError("boom"),
        ):
            assert _oauth_impl._validate_redirect_url("https://example.com/callback") is False

    def test_value_error_returns_false(self):
        """ValueError during parsing should return False."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            side_effect=ValueError("bad"),
        ):
            assert _oauth_impl._validate_redirect_url("https://example.com/cb") is False

    def test_type_error_returns_false(self):
        """TypeError during processing should return False."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            side_effect=TypeError("bad type"),
        ):
            assert _oauth_impl._validate_redirect_url("https://example.com/cb") is False

    def test_key_error_returns_false(self):
        """KeyError during processing should return False."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            side_effect=KeyError("missing"),
        ):
            assert _oauth_impl._validate_redirect_url("https://example.com/cb") is False

    def test_url_with_query_params(self):
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert (
                _oauth_impl._validate_redirect_url("https://example.com/cb?code=abc&state=xyz")
                is True
            )

    def test_url_with_fragment(self):
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("https://example.com/cb#token=abc") is True

    def test_public_oauth_patch_is_respected(self):
        """Patching the public oauth module path should still drive validation."""
        import aragora.server.handlers.oauth as oauth_public

        with patch.object(
            oauth_public,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"public.example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("https://public.example.com/callback") is True
            assert _oauth_impl._validate_redirect_url("https://example.com/callback") is False

    def test_url_with_path_only(self):
        """Relative path without scheme should return False."""
        with patch.object(
            _oauth_impl,
            "_get_allowed_redirect_hosts",
            return_value=frozenset({"example.com"}),
        ):
            assert _oauth_impl._validate_redirect_url("/callback") is False


# ============================================================================
# _validate_state wrapper tests
# ============================================================================


class TestValidateState:
    """Test the _validate_state() wrapper function."""

    def test_delegates_to_internal(self):
        """_validate_state should delegate to _validate_state_internal."""
        expected = {"user_id": "u1", "redirect_url": "/home"}
        with patch.object(
            _oauth_impl,
            "_validate_state_internal",
            return_value=expected,
        ):
            result = _oauth_impl._validate_state("some-state-token")
            assert result == expected

    def test_returns_none_for_invalid_state(self):
        with patch.object(
            _oauth_impl,
            "_validate_state_internal",
            return_value=None,
        ):
            result = _oauth_impl._validate_state("invalid-token")
            assert result is None

    def test_passes_state_argument_through(self):
        mock_fn = MagicMock(return_value=None)
        with patch.object(_oauth_impl, "_validate_state_internal", mock_fn):
            _oauth_impl._validate_state("my-token-123")
            mock_fn.assert_called_once_with("my-token-123")


# ============================================================================
# OAuthUserInfo model tests
# ============================================================================


class TestOAuthUserInfo:
    """Test the re-exported OAuthUserInfo dataclass."""

    def test_create_minimal(self):
        info = _oauth_impl.OAuthUserInfo(
            provider="google",
            provider_user_id="12345",
            email="user@example.com",
            name="Test User",
        )
        assert info.provider == "google"
        assert info.provider_user_id == "12345"
        assert info.email == "user@example.com"
        assert info.name == "Test User"
        assert info.picture is None
        assert info.email_verified is False

    def test_create_with_all_fields(self):
        info = _oauth_impl.OAuthUserInfo(
            provider="github",
            provider_user_id="gh-99",
            email="dev@github.com",
            name="Dev User",
            picture="https://avatars.github.com/u/99",
            email_verified=True,
        )
        assert info.picture == "https://avatars.github.com/u/99"
        assert info.email_verified is True


# ============================================================================
# _get_param utility tests
# ============================================================================


class TestGetParam:
    """Test the re-exported _get_param utility function."""

    def test_string_value(self):
        params = {"code": "abc123"}
        assert _oauth_impl._get_param(params, "code") == "abc123"

    def test_list_value_returns_first(self):
        params = {"code": ["abc123", "def456"]}
        assert _oauth_impl._get_param(params, "code") == "abc123"

    def test_empty_list_returns_default(self):
        params = {"code": []}
        assert _oauth_impl._get_param(params, "code") is None

    def test_missing_key_returns_default(self):
        params = {"other": "value"}
        assert _oauth_impl._get_param(params, "code") is None

    def test_custom_default(self):
        params = {}
        assert _oauth_impl._get_param(params, "code", "fallback") == "fallback"

    def test_empty_dict(self):
        assert _oauth_impl._get_param({}, "key") is None

    def test_none_value_in_dict(self):
        """If the value is None in the dict, it should be returned as-is (not default)."""
        params = {"key": None}
        assert _oauth_impl._get_param(params, "key", "default") is None


# ============================================================================
# __all__ tests
# ============================================================================


class TestModuleAll:
    """Verify __all__ contains expected public exports."""

    def test_all_contains_oauth_handler(self):
        assert "OAuthHandler" in _oauth_impl.__all__

    def test_all_contains_validate_oauth_config(self):
        assert "validate_oauth_config" in _oauth_impl.__all__

    def test_all_length(self):
        assert len(_oauth_impl.__all__) == 2


# ============================================================================
# State management constant tests
# ============================================================================


class TestStateManagementConstants:
    """Test state management re-exported constants."""

    def test_state_ttl_seconds_value(self):
        assert _oauth_impl._STATE_TTL_SECONDS == 600

    def test_max_oauth_states_value(self):
        assert _oauth_impl.MAX_OAUTH_STATES == 10000


# ============================================================================
# Module identity tests
# ============================================================================


class TestModuleIdentity:
    """Test that the module is properly registered in sys.modules."""

    def test_module_in_sys_modules(self):
        assert "aragora.server.handlers.oauth._oauth_impl" in sys.modules

    def test_module_logger_exists(self):
        """The module creates a logger named after itself."""
        assert hasattr(_oauth_impl, "_logger")
        assert _oauth_impl._logger.name == "aragora.server.handlers.oauth._oauth_impl"
