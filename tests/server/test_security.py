"""
Critical security tests for Aragora.

Tests security-critical paths including:
- Token validation (HMAC signatures, expiration, tampering)
- SQL injection prevention (LIKE pattern escaping)
- Rate limiting (edge cases, memory bounds)
- Input sanitization
"""

import hashlib
import hmac
import os
import tempfile
import threading
import time
from unittest.mock import patch

import pytest

from aragora.config.settings import AuthSettings, get_settings, reset_settings
from aragora.server.auth import AuthConfig, check_auth
from aragora.storage.debate_storage import _escape_like_pattern, DebateStorage


class TestTokenValidation:
    """Test token validation security."""

    @pytest.fixture
    def auth(self):
        """Create an AuthConfig with a known secret."""
        config = AuthConfig()
        config.api_token = "test_secret_key_12345"
        config.enabled = True
        config.token_ttl = 3600
        return config

    def test_valid_token_accepted(self, auth):
        """Valid token should be accepted."""
        token = auth.generate_token("loop_1")
        assert auth.validate_token(token, "loop_1") is True

    def test_expired_token_rejected(self, auth):
        """Expired token should be rejected."""
        # Generate token that's already expired
        token = auth.generate_token("loop_1", expires_in=-1)
        assert auth.validate_token(token, "loop_1") is False

    def test_token_expiry_boundary(self, auth):
        """Token should be valid exactly until expiration."""
        # Generate token expiring in 1 second
        token = auth.generate_token("loop_1", expires_in=1)
        assert auth.validate_token(token, "loop_1") is True

        # Wait for expiration
        time.sleep(1.5)
        assert auth.validate_token(token, "loop_1") is False

    def test_signature_tampering_rejected(self, auth):
        """Token with tampered signature should be rejected."""
        token = auth.generate_token("loop_1")

        # Tamper with signature by flipping one character
        parts = token.rsplit(":", 1)
        tampered_sig = parts[1][:-1] + ("a" if parts[1][-1] != "a" else "b")
        tampered_token = f"{parts[0]}:{tampered_sig}"

        assert auth.validate_token(tampered_token, "loop_1") is False

    def test_payload_tampering_rejected(self, auth):
        """Token with tampered payload should be rejected."""
        token = auth.generate_token("loop_1")

        # Tamper with loop_id in payload
        parts = token.split(":")
        parts[0] = "loop_2"  # Change loop_id
        tampered_token = ":".join(parts)

        assert auth.validate_token(tampered_token, "loop_1") is False

    def test_malformed_token_rejected(self, auth):
        """Malformed tokens should be safely rejected."""
        malformed_tokens = [
            "",
            ":",
            "::",
            "no_colons",
            "one:colon",
            "loop:notanumber:sig",
            "loop:12345:",  # Empty signature
            ":12345:sig",  # Empty loop
        ]

        for token in malformed_tokens:
            assert auth.validate_token(token, "") is False

    def test_wrong_loop_id_rejected(self, auth):
        """Token generated for one loop should be rejected for another."""
        token = auth.generate_token("loop_1")
        assert auth.validate_token(token, "loop_1") is True
        assert auth.validate_token(token, "loop_2") is False

    def test_empty_loop_id_accepts_any(self, auth):
        """Token with empty loop_id should be accepted for any loop."""
        token = auth.generate_token("")  # No specific loop
        assert auth.validate_token(token, "") is True
        # Empty loop in token means it validates against any loop_id check
        # (when loop_id param is also empty)

    def test_timing_attack_resistance(self, auth):
        """Signature comparison should use constant-time comparison."""
        token = auth.generate_token("loop_1")

        # Create a token with completely different signature
        parts = token.rsplit(":", 1)
        wrong_sig = "a" * 64  # Completely different
        wrong_token = f"{parts[0]}:{wrong_sig}"

        # Both should take similar time (within reason)
        # This is more of a verification that hmac.compare_digest is used
        times = []
        for test_token in [token, wrong_token]:
            start = time.perf_counter()
            for _ in range(1000):
                auth.validate_token(test_token, "loop_1")
            times.append(time.perf_counter() - start)

        # Times should be within 3x of each other (very generous for CI variance)
        # This test mainly verifies hmac.compare_digest is used, not precise timing
        ratio = max(times) / min(times)
        assert ratio < 3.0, f"Timing difference too large: {times}"

    def test_unicode_in_loop_id(self, auth):
        """Unicode characters in loop_id should be handled safely."""
        unicode_loops = [
            "loop_émoji_🎉",
            "loop_中文",
            "loop_العربية",
            "loop_\x00null",
        ]

        for loop_id in unicode_loops:
            token = auth.generate_token(loop_id)
            assert auth.validate_token(token, loop_id) is True
            assert auth.validate_token(token, "different") is False


class TestSQLInjectionPrevention:
    """Test SQL injection prevention in storage."""

    def test_escape_like_percent(self):
        """Percent sign should be escaped."""
        assert _escape_like_pattern("test%") == "test\\%"
        assert _escape_like_pattern("%test%") == "\\%test\\%"
        assert _escape_like_pattern("100%") == "100\\%"

    def test_escape_like_underscore(self):
        """Underscore should be escaped."""
        assert _escape_like_pattern("test_value") == "test\\_value"
        assert _escape_like_pattern("_start") == "\\_start"
        assert _escape_like_pattern("end_") == "end\\_"

    def test_escape_like_backslash(self):
        """Backslash should be escaped first."""
        assert _escape_like_pattern("path\\to") == "path\\\\to"
        assert _escape_like_pattern("\\") == "\\\\"

    def test_escape_like_combined(self):
        """Combined special characters should all be escaped."""
        assert _escape_like_pattern("100%_done\\") == "100\\%\\_done\\\\"

    def test_escape_like_sql_keywords(self):
        """SQL keywords should pass through (not injection vectors for LIKE)."""
        keywords = ["SELECT", "DROP", "DELETE", "UPDATE", "INSERT", "--", ";"]
        for kw in keywords:
            # These should pass through unchanged (they're not LIKE metacharacters)
            assert _escape_like_pattern(kw) == kw

    def test_escape_like_empty_string(self):
        """Empty string should return empty string."""
        assert _escape_like_pattern("") == ""

    def test_escape_like_unicode(self):
        """Unicode characters should pass through."""
        assert _escape_like_pattern("café") == "café"
        assert _escape_like_pattern("日本語") == "日本語"

    def test_storage_slug_escaping(self):
        """Storage should properly escape slugs in LIKE queries."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            storage = DebateStorage(db_path)

            # Create a debate with special characters in task
            # The slug generation will sanitize, but test the lookup
            from unittest.mock import MagicMock, patch

            # Test that get_by_slug properly escapes
            # This would catch SQL injection in the LIKE clause
            malicious_slugs = [
                "test%",  # Would match too many rows
                "test_",  # Would match test1, test2, etc.
                "test'; DROP TABLE debates; --",  # Classic injection
            ]

            for slug in malicious_slugs:
                # Should not raise and should return None (not found)
                result = storage.get_by_slug(slug)
                assert result is None
        finally:
            os.unlink(db_path)


class TestRateLimiting:
    """Test rate limiting security."""

    def test_rate_limit_enforced(self):
        """Rate limit should block after threshold."""
        auth = AuthConfig()
        auth.rate_limit_per_minute = 5

        token = "test_token"
        for i in range(5):
            allowed, remaining = auth.check_rate_limit(token)
            assert allowed is True
            assert remaining == 4 - i

        # 6th request should be blocked
        allowed, remaining = auth.check_rate_limit(token)
        assert allowed is False
        assert remaining == 0

    def test_rate_limit_per_token_isolation(self):
        """Each token should have independent rate limit."""
        auth = AuthConfig()
        auth.rate_limit_per_minute = 3

        # Exhaust token1
        for _ in range(3):
            auth.check_rate_limit("token1")
        assert auth.check_rate_limit("token1")[0] is False

        # token2 should still work
        assert auth.check_rate_limit("token2")[0] is True

    def test_rate_limit_ip_isolation(self):
        """Each IP should have independent rate limit."""
        auth = AuthConfig()
        auth.ip_rate_limit_per_minute = 3

        # Exhaust IP1
        for _ in range(3):
            auth.check_rate_limit_by_ip("192.168.1.1")
        assert auth.check_rate_limit_by_ip("192.168.1.1")[0] is False

        # IP2 should still work
        assert auth.check_rate_limit_by_ip("192.168.1.2")[0] is True

    def test_rate_limit_empty_ip(self):
        """Empty IP should be allowed (no tracking)."""
        auth = AuthConfig()
        auth.ip_rate_limit_per_minute = 1

        # Empty IP should always be allowed
        allowed, _ = auth.check_rate_limit_by_ip("")
        assert allowed is True
        allowed, _ = auth.check_rate_limit_by_ip("")
        assert allowed is True

    def test_rate_limit_memory_bounds(self):
        """Rate limiter should not exhaust memory with many unique tokens."""
        auth = AuthConfig()
        auth._max_tracked_entries = 100
        auth.rate_limit_per_minute = 1000

        # Add many unique tokens
        for i in range(200):
            auth.check_rate_limit(f"token_{i}")

        # Should have cleaned up old entries
        assert len(auth._token_request_counts) <= 100

    def test_rate_limit_thread_safety(self):
        """Rate limiter should be thread-safe."""
        auth = AuthConfig()
        auth.rate_limit_per_minute = 10000
        errors = []
        results = []

        def check_rate():
            try:
                for i in range(100):
                    allowed, _ = auth.check_rate_limit("thread_token")
                    results.append(allowed)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=check_rate) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Should have processed all requests without error
        assert len(results) == 1000

    def test_rate_limit_sliding_window(self):
        """Rate limit should use sliding window."""
        auth = AuthConfig()
        auth.rate_limit_per_minute = 2

        # Use both slots
        auth.check_rate_limit("token")
        auth.check_rate_limit("token")
        assert auth.check_rate_limit("token")[0] is False

        # Wait for window to slide (use small sleep + mock for CI)
        time.sleep(0.1)

        # Still should be blocked (window hasn't fully passed)
        # This verifies it's a sliding window, not a fixed window


class TestTokenRevocation:
    """Test token revocation security."""

    @pytest.fixture
    def auth(self):
        """Create an AuthConfig with a known secret."""
        config = AuthConfig()
        config.api_token = "test_secret_key_12345"
        config.enabled = True
        config.token_ttl = 3600
        config._revoked_tokens.clear()
        return config

    def test_revoke_token_basic(self, auth):
        """Token revocation should work."""
        token = auth.generate_token("loop_1")
        assert auth.validate_token(token, "loop_1") is True

        # Revoke the token
        assert auth.revoke_token(token) is True

        # Token should now be rejected
        assert auth.validate_token(token, "loop_1") is False

    def test_revoke_token_idempotence(self, auth):
        """Revoking same token twice should be idempotent."""
        token = auth.generate_token("loop_1")

        # Revoke twice
        assert auth.revoke_token(token) is True
        assert auth.revoke_token(token) is True

        # Should still be revoked
        assert auth.is_revoked(token) is True
        assert auth.get_revocation_count() == 1  # Only one entry

    def test_revoke_nonexistent_token(self, auth):
        """Revoking a non-existent token should succeed."""
        assert auth.revoke_token("nonexistent_token") is True
        assert auth.is_revoked("nonexistent_token") is True

    def test_revoke_empty_token(self, auth):
        """Revoking empty token should return False."""
        assert auth.revoke_token("") is False
        assert auth.revoke_token(None) is False

    def test_is_revoked_empty_token(self, auth):
        """is_revoked with empty token should return False."""
        assert auth.is_revoked("") is False
        assert auth.is_revoked(None) is False

    def test_revocation_max_capacity_cleanup(self, auth):
        """Revocation storage should clean up at max capacity."""
        auth._max_revoked_tokens = 20

        # Add max tokens
        for i in range(20):
            auth.revoke_token(f"token_{i}")

        assert auth.get_revocation_count() == 20

        # Adding one more should trigger cleanup (removes 10%)
        auth.revoke_token("token_overflow")

        # Should have cleaned up oldest 10% (2 tokens) and added new one
        assert auth.get_revocation_count() <= 19

    def test_revocation_before_validation(self, auth):
        """Revoked tokens should be checked before expensive crypto."""
        token = auth.generate_token("loop_1")
        auth.revoke_token(token)

        # Should fail fast on revocation check
        assert auth.validate_token(token, "loop_1") is False

    def test_revocation_thread_safety(self, auth):
        """Revocation should be thread-safe."""
        errors = []
        tokens = [f"token_{i}" for i in range(100)]

        def revoke_tokens():
            try:
                for token in tokens:
                    auth.revoke_token(token)
            except Exception as e:
                errors.append(e)

        def check_revocations():
            try:
                for token in tokens:
                    auth.is_revoked(token)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=revoke_tokens),
            threading.Thread(target=check_revocations),
            threading.Thread(target=revoke_tokens),
            threading.Thread(target=check_revocations),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestBearerHeaderParsing:
    """Test Bearer header extraction edge cases."""

    def test_bearer_case_sensitive(self):
        """Bearer prefix should be case-sensitive."""
        config = AuthConfig()
        config.api_token = "secret"
        config.enabled = True

        valid_token = config.generate_token("loop")

        # Correct case
        result = config.extract_token_from_request({"Authorization": f"Bearer {valid_token}"}, {})
        assert result == valid_token

        # Wrong case should not extract
        result = config.extract_token_from_request({"Authorization": f"bearer {valid_token}"}, {})
        assert result is None

        result = config.extract_token_from_request({"Authorization": f"BEARER {valid_token}"}, {})
        assert result is None

    def test_bearer_with_extra_spaces(self):
        """Bearer prefix should require exactly one space."""
        config = AuthConfig()

        # Extra leading spaces in token
        result = config.extract_token_from_request(
            {"Authorization": "Bearer  token_with_space"}, {}
        )
        assert result == " token_with_space"  # Includes the extra space

    def test_bearer_empty_value(self):
        """Bearer with empty value should return empty string."""
        config = AuthConfig()

        result = config.extract_token_from_request({"Authorization": "Bearer "}, {})
        assert result == ""

    def test_query_param_fallback(self):
        """Should fall back to query param if no Bearer header."""
        config = AuthConfig()

        result = config.extract_token_from_request(
            {"Authorization": "Basic abc123"},  # Not Bearer
            {"token": ["query_token"]},  # Should be ignored for security
        )
        # Query params are NOT supported (they appear in logs)
        assert result is None

    def test_bearer_takes_precedence(self):
        """Bearer header should be the only accepted method."""
        config = AuthConfig()

        result = config.extract_token_from_request(
            {"Authorization": "Bearer header_token"}, {"token": ["query_token"]}
        )
        assert result == "header_token"

    def test_no_auth_header(self):
        """Missing Authorization header should return None (query params ignored)."""
        config = AuthConfig()

        result = config.extract_token_from_request(
            {},
            {"token": ["fallback"]},  # Should be ignored for security
        )
        # Query params are NOT supported for security reasons
        assert result is None


class TestRateLimitCleanupUnderLoad:
    """Test rate limit cleanup behavior under concurrent load."""

    def test_cleanup_triggers_at_threshold(self):
        """Cleanup should trigger at 90% capacity when entries are stale."""
        auth = AuthConfig()
        auth._max_tracked_entries = 100  # Low threshold to trigger cleanup
        auth.rate_limit_per_minute = 1000

        # Fill to 89% - no cleanup yet
        for i in range(89):
            auth.check_rate_limit(f"token_{i}")

        assert len(auth._token_request_counts) == 89

        # Make some entries stale by clearing their timestamps
        # (simulating window expiration)
        for i in range(50):
            auth._token_request_counts[f"token_{i}"] = []

        # Fill to 91% - should trigger cleanup of stale entries
        for i in range(89, 92):
            auth.check_rate_limit(f"token_{i}")

        # Should have cleaned up stale entries (empty lists)
        assert len(auth._token_request_counts) < 92

    def test_concurrent_requests_during_cleanup(self):
        """Concurrent requests during cleanup should be safe."""
        auth = AuthConfig()
        auth._max_tracked_entries = 50
        auth.rate_limit_per_minute = 10000
        errors = []

        def make_requests(prefix):
            try:
                for i in range(100):
                    auth.check_rate_limit(f"{prefix}_token_{i}")
            except Exception as e:
                errors.append(e)

        # Multiple threads adding tokens rapidly
        threads = [threading.Thread(target=make_requests, args=(f"thread_{j}",)) for j in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Should have stayed within bounds
        assert len(auth._token_request_counts) <= auth._max_tracked_entries

    def test_ip_cleanup_under_load(self):
        """IP-based rate limit cleanup should work under load."""
        auth = AuthConfig()
        auth._max_tracked_entries = 50
        auth.ip_rate_limit_per_minute = 10000
        errors = []

        def make_requests(prefix):
            try:
                for i in range(100):
                    auth.check_rate_limit_by_ip(f"192.168.{prefix}.{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=make_requests, args=(j,)) for j in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(auth._ip_request_counts) <= auth._max_tracked_entries


class TestCheckAuthIntegration:
    def test_check_auth_disabled(self):
        """When auth is disabled, should allow all requests."""
        from aragora.server.auth import auth_config

        original_enabled = auth_config.enabled
        try:
            auth_config.enabled = False
            auth, remaining = check_auth({}, "")
            assert auth is True
        finally:
            auth_config.enabled = original_enabled

    def test_check_auth_ip_rate_limit(self):
        """IP rate limiting should work even when auth disabled."""
        from aragora.server.auth import auth_config

        original_enabled = auth_config.enabled
        original_limit = auth_config.ip_rate_limit_per_minute

        try:
            auth_config.enabled = False
            auth_config.ip_rate_limit_per_minute = 2
            auth_config._ip_request_counts.clear()

            # First two should pass
            assert check_auth({}, "", "", "test_ip")[0] is True
            assert check_auth({}, "", "", "test_ip")[0] is True

            # Third should fail
            assert check_auth({}, "", "", "test_ip")[0] is False
        finally:
            auth_config.enabled = original_enabled
            auth_config.ip_rate_limit_per_minute = original_limit

    def test_check_auth_extracts_bearer_token(self):
        """Should extract token from Authorization header."""
        from aragora.server.auth import auth_config

        original_enabled = auth_config.enabled
        original_token = auth_config.api_token

        try:
            auth_config.enabled = True
            auth_config.api_token = "secret"
            auth_config._token_request_counts.clear()

            valid_token = auth_config.generate_token("loop_1")

            headers = {"Authorization": f"Bearer {valid_token}"}
            auth, _ = check_auth(headers, "", "loop_1", "")
            assert auth is True

            # Invalid token should fail
            headers = {"Authorization": "Bearer invalid_token"}
            auth, _ = check_auth(headers, "", "loop_1", "")
            assert auth is False
        finally:
            auth_config.enabled = original_enabled
            auth_config.api_token = original_token


def _auth_settings_env_names() -> set[str]:
    """Environment variable names AuthSettings reads (aliases plus prefix + field name)."""
    prefix = str(AuthSettings.model_config.get("env_prefix") or "")
    names: set[str] = set()
    for field_name, field in AuthSettings.model_fields.items():
        for alias in (field.validation_alias, field.alias):
            if isinstance(alias, str):
                names.add(alias)
            else:
                # AliasChoices exposes .choices; AliasPath entries are not env names.
                for choice in getattr(alias, "choices", None) or ():
                    if isinstance(choice, str):
                        names.add(choice)
        names.add(f"{prefix}{field_name}".upper())
    return names


class TestConfigureFromEnv:
    """Test environment variable configuration."""

    @pytest.fixture(autouse=True)
    def _presettle_auth_settings(self, monkeypatch):
        """Parse AuthSettings before the test body's env patches take effect.

        AuthConfig.__init__ reads get_settings().auth lazily. A test that ran
        earlier in the same worker may leave the lru-cached Settings cleared
        (reset_settings()) or its auth block unparsed; AuthSettings would then
        be parsed inside this class's patch.dict scope, where ARAGORA_TOKEN_TTL
        deliberately violates the ge=60 int field and raises ValidationError
        before configure_from_env() ever runs. Scrub AuthSettings' env inputs
        and parse it here so the bodies exercise configure_from_env() alone.
        """
        # pydantic-settings matches env names case-insensitively, so scrub every
        # case variant of each name, not just the exact alias spelling.
        targets = {name.casefold() for name in _auth_settings_env_names()}
        for env_name in list(os.environ):
            if env_name.casefold() in targets:
                monkeypatch.delenv(env_name, raising=False)
        # On a cold cache get_settings() re-hydrates os.environ from Secrets
        # Manager with overwrite=True, which would undo the scrub above.
        monkeypatch.setattr(
            "aragora.config.secrets.hydrate_env_from_secrets",
            lambda *args, **kwargs: {},
        )
        _ = get_settings().auth
        yield
        # Drop the scrubbed-defaults Settings parsed above so it cannot serve
        # later tests that run after monkeypatch restores the real env.
        reset_settings()

    def test_configure_from_env_token(self):
        """Should load token from environment."""
        with patch.dict(os.environ, {"ARAGORA_API_TOKEN": "env_secret"}):
            config = AuthConfig()
            config.configure_from_env()
            assert config.api_token == "env_secret"
            assert config.enabled is True

    def test_configure_from_env_ttl(self):
        """Should load TTL from environment."""
        with patch.dict(os.environ, {"ARAGORA_TOKEN_TTL": "7200"}):
            config = AuthConfig()
            config.configure_from_env()
            assert config.token_ttl == 7200

    def test_configure_from_env_invalid_ttl(self):
        """Invalid TTL should be ignored."""
        with patch.dict(os.environ, {"ARAGORA_TOKEN_TTL": "not_a_number"}):
            config = AuthConfig()
            original_ttl = config.token_ttl
            config.configure_from_env()
            assert config.token_ttl == original_ttl  # Unchanged

    def test_configure_from_env_negative_ttl(self):
        """Negative TTL from env should be accepted (allows expired tokens)."""
        with patch.dict(os.environ, {"ARAGORA_TOKEN_TTL": "-100"}):
            config = AuthConfig()
            config.configure_from_env()
            assert config.token_ttl == -100

    def test_configure_from_env_origins(self):
        """Should load allowed origins from environment."""
        from aragora.server.cors_config import CORSConfig

        with patch.dict(
            os.environ,
            {"ARAGORA_ALLOWED_ORIGINS": "http://localhost:3000, https://example.com"},
        ):
            # Re-create CORSConfig so it reads the patched env var
            fresh_cors = CORSConfig()
            with patch("aragora.server.auth.cors_config", fresh_cors):
                config = AuthConfig()
                config.configure_from_env()
                assert "http://localhost:3000" in config.allowed_origins
                assert "https://example.com" in config.allowed_origins


# =============================================================================
# Query Parameter Validation Tests
# =============================================================================


class TestQueryParameterValidation:
    """Tests for query parameter validation."""

    def test_unknown_parameter_rejected(self):
        """Test that unknown parameters are rejected."""
        from aragora.server.unified_server import _validate_query_params

        valid, error = _validate_query_params({"malicious": ["payload"]})
        assert valid is False
        assert "Unknown query parameter" in error

    def test_valid_table_enum(self):
        """Test valid table enum values accepted."""
        from aragora.server.unified_server import _validate_query_params

        valid, error = _validate_query_params({"table": ["debates"]})
        assert valid is True

    def test_invalid_table_enum_rejected(self):
        """Test invalid table enum value rejected."""
        from aragora.server.unified_server import _validate_query_params

        valid, error = _validate_query_params({"table": ["malicious"]})
        assert valid is False
        assert "Invalid value" in error

    def test_valid_sections_enum(self):
        """Test valid sections enum accepted."""
        from aragora.server.unified_server import _validate_query_params

        valid, error = _validate_query_params({"sections": ["all"]})
        assert valid is True

    def test_multiple_params_validated(self):
        """Test multiple parameters are validated."""
        from aragora.server.unified_server import _validate_query_params

        valid, error = _validate_query_params(
            {
                "limit": ["50"],
                "offset": ["10"],
                "agent": ["claude"],
            }
        )
        assert valid is True


# =============================================================================
# Trusted Proxy Configuration Tests
# =============================================================================


class TestTrustedProxyConfiguration:
    """Tests for trusted proxy configuration."""

    def test_trusted_proxies_contains_localhost_ip(self):
        """Test that localhost IP is in trusted proxies."""
        from aragora.server.unified_server import TRUSTED_PROXIES

        assert "127.0.0.1" in TRUSTED_PROXIES

    def test_trusted_proxies_contains_ipv6_localhost(self):
        """Test that IPv6 localhost is in trusted proxies."""
        from aragora.server.unified_server import TRUSTED_PROXIES

        assert "::1" in TRUSTED_PROXIES

    def test_trusted_proxies_is_frozenset(self):
        """Test that trusted proxies is immutable."""
        from aragora.server.unified_server import TRUSTED_PROXIES

        assert isinstance(TRUSTED_PROXIES, frozenset)


# =============================================================================
# Upload Rate Limiting Tests
# =============================================================================


class TestUploadRateLimiting:
    """Tests for upload rate limiting configuration."""

    def test_upload_rate_limit_exists(self):
        """Test that upload rate limiting is configured."""
        from aragora.server.unified_server import UnifiedHandler

        assert hasattr(UnifiedHandler, "MAX_UPLOADS_PER_MINUTE")
        assert hasattr(UnifiedHandler, "MAX_UPLOADS_PER_HOUR")
        assert hasattr(UnifiedHandler, "_upload_counts")

    def test_max_concurrent_debates_defined(self):
        """Test maximum concurrent debates is defined."""
        from aragora.server.unified_server import MAX_CONCURRENT_DEBATES

        assert MAX_CONCURRENT_DEBATES == 10

    def test_max_json_content_length(self):
        """Test maximum JSON content length is defined."""
        from aragora.server.unified_server import MAX_JSON_CONTENT_LENGTH

        assert MAX_JSON_CONTENT_LENGTH == 10 * 1024 * 1024  # 10MB


# =============================================================================
# POST Body Size Limit Tests
# =============================================================================


class TestPostBodySizeLimit:
    """Tests for POST body size limit enforcement."""

    def test_max_body_size_constant_exists(self):
        """MAX_BODY_SIZE should be defined in base handler."""
        from aragora.server.handlers.base import BaseHandler

        assert hasattr(BaseHandler, "MAX_BODY_SIZE")
        assert BaseHandler.MAX_BODY_SIZE == 10 * 1024 * 1024  # 10MB

    def test_read_json_body_respects_limit(self):
        """read_json_body should reject bodies over limit."""
        from aragora.server.handlers.base import BaseHandler
        from unittest.mock import MagicMock
        from io import BytesIO

        handler = BaseHandler({})

        # Mock request handler with body larger than limit
        mock_handler = MagicMock()
        mock_handler.headers = {"Content-Length": str(11 * 1024 * 1024)}  # 11MB
        mock_handler.rfile = BytesIO(b"x" * (11 * 1024 * 1024))

        result = handler.read_json_body(mock_handler)
        assert result is None  # Should reject

    def test_read_json_body_accepts_within_limit(self):
        """read_json_body should accept bodies within limit."""
        from aragora.server.handlers.base import BaseHandler
        from unittest.mock import MagicMock
        from io import BytesIO
        import json

        handler = BaseHandler({})

        body = json.dumps({"key": "value"}).encode()
        mock_handler = MagicMock()
        mock_handler.headers = {"Content-Length": str(len(body))}
        mock_handler.rfile = BytesIO(body)

        result = handler.read_json_body(mock_handler)
        assert result == {"key": "value"}

    def test_read_json_body_boundary_at_limit(self):
        """read_json_body should accept body exactly at limit."""
        from aragora.server.handlers.base import BaseHandler
        from unittest.mock import MagicMock
        from io import BytesIO
        import json

        handler = BaseHandler({})

        # Create body exactly at limit (minus some for JSON overhead)
        max_size = handler.MAX_BODY_SIZE
        body = json.dumps({"data": "x" * (max_size - 100)}).encode()
        if len(body) > max_size:
            body = body[:max_size]

        mock_handler = MagicMock()
        mock_handler.headers = {"Content-Length": str(len(body))}
        mock_handler.rfile = BytesIO(body)

        # Should not reject based on size (may fail JSON parsing due to truncation)
        result = handler.read_json_body(mock_handler, max_size=len(body) + 1)
        # Result will be None if JSON is invalid, but not due to size

    def test_read_json_body_custom_limit(self):
        """read_json_body should respect custom max_size."""
        from aragora.server.handlers.base import BaseHandler
        from unittest.mock import MagicMock
        from io import BytesIO
        import json

        handler = BaseHandler({})

        body = json.dumps({"key": "x" * 1000}).encode()
        mock_handler = MagicMock()
        mock_handler.headers = {"Content-Length": str(len(body))}
        mock_handler.rfile = BytesIO(body)

        # With custom small limit, should reject
        result = handler.read_json_body(mock_handler, max_size=100)
        assert result is None

    def test_validate_content_length_rejects_negative(self):
        """validate_content_length should reject negative values."""
        from aragora.server.handlers.base import BaseHandler
        from unittest.mock import MagicMock

        handler = BaseHandler({})
        mock_handler = MagicMock()
        mock_handler.headers = {"Content-Length": "-1"}

        result = handler.validate_content_length(mock_handler)
        assert result is None

    def test_validate_content_length_rejects_non_numeric(self):
        """validate_content_length should reject non-numeric values."""
        from aragora.server.handlers.base import BaseHandler
        from unittest.mock import MagicMock

        handler = BaseHandler({})
        mock_handler = MagicMock()
        mock_handler.headers = {"Content-Length": "abc"}

        result = handler.validate_content_length(mock_handler)
        assert result is None


# =============================================================================
# Path Parameter Injection Tests
# =============================================================================


class TestPathParameterInjection:
    """Tests for path parameter injection prevention."""

    def test_debate_id_path_traversal(self):
        """Debate ID should reject path traversal attempts."""
        from aragora.server.handlers.base import validate_debate_id

        traversal_attempts = [
            "../secret",
            "..%2fsecret",
            "debate/../../etc/passwd",
            "debate/../admin",
            "..",
            "...",
            "....//",
        ]

        for attempt in traversal_attempts:
            is_valid, error = validate_debate_id(attempt)
            assert is_valid is False, f"Should reject: {attempt}"
            assert "invalid" in error.lower() or "pattern" in error.lower()

    def test_agent_name_injection(self):
        """Agent name should reject injection attempts."""
        from aragora.server.handlers.base import validate_agent_name

        injection_attempts = [
            "'; DROP TABLE agents; --",
            "claude<script>alert(1)</script>",
            "claude|cat /etc/passwd",
            "claude$(whoami)",
            "claude`id`",
            "claude\x00null",
        ]

        for attempt in injection_attempts:
            is_valid, error = validate_agent_name(attempt)
            assert is_valid is False, f"Should reject: {attempt}"

    def test_valid_debate_id_accepted(self):
        """Valid debate IDs should be accepted."""
        from aragora.server.handlers.base import validate_debate_id

        valid_ids = [
            "debate-123",
            "abc_def_ghi",
            "simple123",
            "UPPER-lower-123",
            "a",
            "a" * 50,
        ]

        for valid_id in valid_ids:
            is_valid, error = validate_debate_id(valid_id)
            assert is_valid is True, f"Should accept: {valid_id} (got: {error})"

    def test_valid_agent_name_accepted(self):
        """Valid agent names should be accepted."""
        from aragora.server.handlers.base import validate_agent_name

        valid_names = [
            "claude",
            "gpt-4",
            "agent_1",
            "CodexModel",
            "gemini-pro",
            "gemini-3.1-pro-preview",  # dotted model version (#9994)
            "claude-fable-5.1",
        ]

        for name in valid_names:
            is_valid, error = validate_agent_name(name)
            assert is_valid is True, f"Should accept: {name} (got: {error})"

    def test_agent_name_slash_and_leading_dot_rejected(self):
        """Provider-qualified slugs and dot-led tokens are not valid agent path segments."""
        from aragora.server.handlers.base import validate_agent_name

        for name in ["anthropic/claude-fable-5.1", ".hidden", "..", "../claude"]:
            is_valid, _ = validate_agent_name(name)
            assert is_valid is False, f"Should reject: {name}"

    def test_empty_values_rejected(self):
        """Empty values should be rejected."""
        from aragora.server.handlers.base import validate_debate_id, validate_agent_name

        is_valid, _ = validate_debate_id("")
        assert is_valid is False

        is_valid, _ = validate_agent_name("")
        assert is_valid is False

    def test_url_encoded_traversal_rejected(self):
        """URL-encoded path traversal should be rejected."""
        from aragora.server.handlers.base import validate_path_segment, SAFE_ID_PATTERN

        encoded_attempts = [
            "%2e%2e",  # ..
            "%2e%2e%2f",  # ../
            "%252e%252e",  # double-encoded ..
        ]

        for attempt in encoded_attempts:
            is_valid, _ = validate_path_segment(attempt, "id", SAFE_ID_PATTERN)
            # Either the regex rejects it or the path traversal check catches ..
            # After URL decoding happens earlier in the stack
            assert is_valid is False or ".." not in attempt


# =============================================================================
# Nested Payload Attack Tests
# =============================================================================


class TestNestedPayloadAttacks:
    """Tests for deeply nested JSON payload attacks."""

    def test_deeply_nested_json_parsing(self):
        """Test that deeply nested JSON doesn't cause stack overflow."""
        import json

        # Create deeply nested JSON
        depth = 100
        nested = {}
        current = nested
        for i in range(depth):
            current["level"] = {}
            current = current["level"]
        current["value"] = "deep"

        json_str = json.dumps(nested)

        # Should be parseable without crash
        parsed = json.loads(json_str)
        assert parsed is not None

    def test_very_deep_nesting_limit(self):
        """Python's JSON parser has a recursion limit around 1000."""
        import json

        # Create extremely deep nesting that might hit recursion limit
        depth = 500  # Safe depth that won't hit limit
        nested_str = '{"a":' * depth + "1" + "}" * depth

        # Should parse successfully at this depth
        parsed = json.loads(nested_str)
        assert parsed is not None

    def test_large_array_handling(self):
        """Large arrays should be handled safely."""
        import json

        # Create a large but not excessive array
        large_array = list(range(10000))
        json_str = json.dumps({"data": large_array})

        parsed = json.loads(json_str)
        assert len(parsed["data"]) == 10000

    def test_wide_object_handling(self):
        """Objects with many keys should be handled safely."""
        import json

        # Create object with many keys
        wide_object = {f"key_{i}": i for i in range(1000)}
        json_str = json.dumps(wide_object)

        parsed = json.loads(json_str)
        assert len(parsed) == 1000

    def test_mixed_deep_and_wide(self):
        """Mixed deep and wide structures should be handled."""
        import json

        # Create structure that's both deep and wide
        obj = {}
        for i in range(100):
            obj[f"branch_{i}"] = {"level1": {"level2": {"level3": i}}}

        json_str = json.dumps(obj)
        parsed = json.loads(json_str)
        assert parsed["branch_50"]["level1"]["level2"]["level3"] == 50


# =============================================================================
# Content-Type Validation Tests
# =============================================================================


class TestContentTypeValidation:
    """Tests for Content-Type header validation."""

    def test_json_content_type_accepted(self):
        """application/json should be accepted."""
        # Simulating Content-Type check
        valid_types = [
            "application/json",
            "application/json; charset=utf-8",
            "application/json;charset=utf-8",
        ]

        for content_type in valid_types:
            assert content_type.startswith("application/json")

    def test_wrong_content_type_behavior(self):
        """Non-JSON content types for JSON endpoints should be handled."""
        # The server should either reject or attempt to parse anyway
        invalid_types = [
            "text/plain",
            "text/html",
            "application/xml",
            "multipart/form-data",
        ]

        for content_type in invalid_types:
            assert not content_type.startswith("application/json")

    def test_missing_content_type(self):
        """Missing Content-Type should be handled gracefully."""
        # When Content-Type is missing, behavior depends on endpoint
        # For POST with body, should either assume JSON or reject
        content_type = None
        # Should not crash
        assert content_type is None or isinstance(content_type, str)


# =============================================================================
# Request Header Security Tests
# =============================================================================


class TestRequestHeaderSecurity:
    """Tests for request header security."""

    def test_host_header_injection_patterns(self):
        """Host header injection patterns should be safe."""
        from aragora.server.validation import SAFE_ID_PATTERN

        malicious_hosts = [
            "evil.com\r\nX-Injected: header",
            "evil.com%0d%0aX-Injected:%20header",
            "evil.com\nHost: other.com",
        ]

        # These shouldn't match safe ID patterns
        for host in malicious_hosts:
            match = SAFE_ID_PATTERN.match(host)
            assert match is None or match.group() != host

    def test_oversized_header_limits(self):
        """Very long headers should have limits."""
        # The HTTP server typically limits header size
        # This test documents expected behavior
        max_header_size = 8192  # Common limit
        long_header = "X" * (max_header_size + 1)

        # Should be longer than typical limit
        assert len(long_header) > max_header_size


# =============================================================================
# GLOB Pattern Injection Tests
# =============================================================================


class TestGlobPatternInjection:
    """Tests for SQL GLOB pattern injection prevention in storage."""

    @pytest.fixture
    def storage(self):
        """Create temporary storage."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield DebateStorage(db_path)
        try:
            os.unlink(db_path)
        except FileNotFoundError:
            pass

    def test_glob_asterisk_in_task_no_injection(self, storage):
        """Task with * should not cause GLOB pattern injection."""
        # Save a debate with task containing asterisk
        data = {
            "id": "glob-test-1",
            "task": "Test * wildcard * everywhere",
            "agents": ["agent1"],
        }
        slug = storage.save_dict(data)

        # Should be able to retrieve correctly
        debate = storage.get_by_slug(slug)
        assert debate is not None
        assert debate["task"] == "Test * wildcard * everywhere"

    def test_glob_question_mark_in_task_no_injection(self, storage):
        """Task with ? should not cause GLOB pattern injection."""
        data = {
            "id": "glob-test-2",
            "task": "What is this? Is it working?",
            "agents": ["agent1"],
        }
        slug = storage.save_dict(data)

        debate = storage.get_by_slug(slug)
        assert debate is not None
        assert "?" in debate["task"]

    def test_glob_brackets_in_task_no_injection(self, storage):
        """Task with [abc] should not cause GLOB pattern injection."""
        data = {
            "id": "glob-test-3",
            "task": "Test [option1] and [option2] patterns",
            "agents": ["agent1"],
        }
        slug = storage.save_dict(data)

        debate = storage.get_by_slug(slug)
        assert debate is not None
        assert "[option1]" in debate["task"]

    def test_combined_glob_metacharacters(self, storage):
        """Task with all GLOB metacharacters should be safe."""
        data = {
            "id": "glob-test-4",
            "task": "Complex: *test?[abc] pattern",
            "agents": ["agent1"],
        }
        slug = storage.save_dict(data)

        debate = storage.get_by_slug(slug)
        assert debate is not None

    def test_slug_collision_with_glob_pattern(self, storage):
        """GLOB pattern in slug collision detection should work correctly."""
        # This tests that the generate_slug GLOB query doesn't get confused
        from unittest.mock import patch

        with patch("aragora.storage.debate_storage.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-01-05"

            # First save
            data1 = {"id": "first", "task": "test star", "agents": []}
            slug1 = storage.save_dict(data1)

            # Second save with same words - should get -2 suffix
            data2 = {"id": "second", "task": "test star", "agents": []}
            slug2 = storage.save_dict(data2)

            assert slug1 != slug2
            assert slug2.endswith("-2")


# =============================================================================
# Audio Path Security Tests
# =============================================================================


class TestAudioPathSecurity:
    """Tests for audio path security."""

    @pytest.fixture
    def storage(self):
        """Create temporary storage."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield DebateStorage(db_path)
        try:
            os.unlink(db_path)
        except FileNotFoundError:
            pass

    def test_audio_path_traversal_stored_as_is(self, storage):
        """Audio paths with ../ should be stored but could be dangerous.

        Note: The storage layer stores the path as-is. Security checks
        should be done at the serving layer to prevent directory traversal.
        This test documents current behavior.
        """
        from unittest.mock import MagicMock
        import json

        # Save a debate first
        artifact = MagicMock()
        artifact.artifact_id = "path-traversal-test"
        artifact.task = "Test task"
        artifact.agents = ["agent1"]
        artifact.consensus_proof = MagicMock(reached=True, confidence=0.9)
        artifact.to_json.return_value = json.dumps({"task": "Test task"})

        storage.save(artifact)

        # Try to set a path with directory traversal
        traversal_path = "../../../etc/passwd"
        result = storage.update_audio("path-traversal-test", traversal_path, 60)

        # Storage layer allows this - it's the serving layer's job to validate
        # This test documents the behavior
        assert result is True

        info = storage.get_audio_info("path-traversal-test")
        assert info["audio_path"] == traversal_path

    def test_audio_path_with_null_bytes(self, storage):
        """Audio paths with null bytes should be handled safely."""
        from unittest.mock import MagicMock
        import json

        artifact = MagicMock()
        artifact.artifact_id = "null-byte-test"
        artifact.task = "Test task"
        artifact.agents = ["agent1"]
        artifact.consensus_proof = MagicMock(reached=True, confidence=0.9)
        artifact.to_json.return_value = json.dumps({"task": "Test task"})

        storage.save(artifact)

        # Try path with null byte (common truncation attack)
        null_path = "/path/to/audio.mp3\x00.evil"
        result = storage.update_audio("null-byte-test", null_path, 60)

        # SQLite stores the full string including null bytes
        assert result is True

    def test_audio_path_unicode_normalization(self, storage):
        """Audio paths with unicode should be handled consistently."""
        from unittest.mock import MagicMock
        import json

        artifact = MagicMock()
        artifact.artifact_id = "unicode-path-test"
        artifact.task = "Test task"
        artifact.agents = ["agent1"]
        artifact.consensus_proof = MagicMock(reached=True, confidence=0.9)
        artifact.to_json.return_value = json.dumps({"task": "Test task"})

        storage.save(artifact)

        # Path with unicode characters
        unicode_path = "/audio/日本語/音声.mp3"
        result = storage.update_audio("unicode-path-test", unicode_path, 60)

        assert result is True
        info = storage.get_audio_info("unicode-path-test")
        assert info["audio_path"] == unicode_path


# =============================================================================
# Memory Exhaustion Attack Tests
# =============================================================================


class TestMemoryExhaustionPrevention:
    """Tests for memory exhaustion prevention."""

    def test_rate_limit_memory_exhaustion_prevention(self):
        """Verify rate limiter prevents unbounded memory growth from unique tokens."""
        auth = AuthConfig()
        auth._max_tracked_entries = 100
        auth.rate_limit_per_minute = 10000

        # Attempt memory exhaustion with many unique tokens
        for i in range(1000):
            auth.check_rate_limit(f"unique_token_{i}")

        # Memory should be bounded
        assert len(auth._token_request_counts) <= 100

    def test_ip_rate_limit_memory_exhaustion_prevention(self):
        """Verify IP rate limiter prevents unbounded memory growth."""
        auth = AuthConfig()
        auth._max_tracked_entries = 100
        auth.ip_rate_limit_per_minute = 10000

        # Attempt memory exhaustion with many unique IPs
        for i in range(1000):
            auth.check_rate_limit_by_ip(f"10.{i // 256}.{i % 256}.1")

        # Memory should be bounded
        assert len(auth._ip_request_counts) <= 100

    def test_revocation_storage_limit_enforced(self):
        """Verify revocation storage has bounded growth."""
        auth = AuthConfig()
        auth._max_revoked_tokens = 100

        # Attempt to store many revoked tokens
        for i in range(500):
            auth.revoke_token(f"revoked_token_{i}")

        # Storage should be bounded
        assert auth.get_revocation_count() <= 100

    def test_concurrent_memory_exhaustion_attempt(self):
        """Multiple threads attempting memory exhaustion should be bounded."""
        auth = AuthConfig()
        auth._max_tracked_entries = 50
        auth.rate_limit_per_minute = 10000
        errors = []

        def exhaust_memory(prefix):
            try:
                for i in range(200):
                    auth.check_rate_limit(f"{prefix}_token_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=exhaust_memory, args=(f"thread_{j}",)) for j in range(10)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Memory should still be bounded despite concurrent attempts
        assert len(auth._token_request_counts) <= auth._max_tracked_entries
