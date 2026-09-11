"""
Tests for aragora.server.auth module.

Tests AuthConfig class including token generation, validation,
revocation, and rate limiting.
"""

import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from aragora.server.auth import AuthenticationError, AuthConfig, check_auth, generate_shareable_link


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def auth_config():
    """Fresh AuthConfig for testing."""
    config = AuthConfig()
    config.api_token = "test_secret_key_12345"
    config.enabled = True
    config.token_ttl = 3600
    config.rate_limit_per_minute = 60
    config.ip_rate_limit_per_minute = 120
    config._revoked_tokens.clear()
    config._token_request_counts.clear()
    config._ip_request_counts.clear()
    return config


@pytest.fixture
def disabled_auth_config():
    """AuthConfig with auth disabled."""
    config = AuthConfig()
    config.enabled = False
    config.api_token = None
    return config


# =============================================================================
# Test Token Generation
# =============================================================================


class TestTokenGeneration:
    """Tests for token generation."""

    def test_token_format_three_parts(self, auth_config):
        """Token should have 3 parts: loop_id, expiry, signature."""
        token = auth_config.generate_token("loop123")
        parts = token.split(":")
        assert len(parts) == 3

    def test_token_signature_is_hex(self, auth_config):
        """Signature should be hexadecimal."""
        token = auth_config.generate_token("loop123")
        signature = token.split(":")[-1]
        # Should be valid hex
        int(signature, 16)
        assert len(signature) == 64  # SHA256 hex

    def test_generated_token_validates(self, auth_config):
        """Generated token should validate successfully."""
        token = auth_config.generate_token("loop123")
        assert auth_config.validate_token(token, "loop123") is True

    def test_different_tokens_different_signatures(self, auth_config):
        """Different loop_ids should produce different signatures."""
        token1 = auth_config.generate_token("loop1")
        token2 = auth_config.generate_token("loop2")
        sig1 = token1.split(":")[-1]
        sig2 = token2.split(":")[-1]
        assert sig1 != sig2

    def test_custom_expiration_respected(self, auth_config):
        """Custom expires_in should be used."""
        with patch("time.time", return_value=1000.0):
            token = auth_config.generate_token("loop", expires_in=500)

        # Check expiry in token
        parts = token.split(":")
        expiry = int(parts[1])
        assert expiry == 1500

    def test_disabled_auth_returns_empty_token(self, disabled_auth_config):
        """No api_token should return empty string."""
        token = disabled_auth_config.generate_token("loop123")
        assert token == ""

    def test_empty_loop_id(self, auth_config):
        """Empty loop_id should work."""
        token = auth_config.generate_token("")
        assert auth_config.validate_token(token, "") is True


# =============================================================================
# Test Token Validation
# =============================================================================


class TestTokenValidation:
    """Tests for token validation."""

    def test_valid_token_accepted(self, auth_config):
        """Valid token with matching loop_id should be accepted."""
        token = auth_config.generate_token("myloop")
        assert auth_config.validate_token(token, "myloop") is True

    def test_expired_token_rejected(self, auth_config):
        """Expired token should be rejected."""
        with patch("time.time", return_value=1000.0):
            token = auth_config.generate_token("loop", expires_in=100)

        with patch("time.time", return_value=1200.0):  # 200 seconds later
            assert auth_config.validate_token(token, "loop") is False

    def test_token_expiry_boundary(self, auth_config):
        """Token should be valid until expiry, rejected after."""
        with patch("time.time", return_value=1000.0):
            token = auth_config.generate_token("loop", expires_in=100)

        # Just before expiry - valid
        with patch("time.time", return_value=1099.0):
            assert auth_config.validate_token(token, "loop") is True

        # At expiry boundary - rejected (> check)
        with patch("time.time", return_value=1100.1):
            assert auth_config.validate_token(token, "loop") is False

    def test_signature_tampering_detected(self, auth_config):
        """Modified signature should be rejected."""
        token = auth_config.generate_token("loop")
        parts = token.split(":")
        # Tamper with signature
        tampered = f"{parts[0]}:{parts[1]}:{'0' * 64}"
        assert auth_config.validate_token(tampered, "loop") is False

    def test_payload_tampering_detected(self, auth_config):
        """Modified payload should be rejected."""
        token = auth_config.generate_token("loop")
        parts = token.split(":")
        # Tamper with expiry
        tampered = f"{parts[0]}:9999999999:{parts[2]}"
        assert auth_config.validate_token(tampered, "loop") is False

    def test_malformed_token_missing_colons(self, auth_config):
        """Token without proper structure should be rejected."""
        assert auth_config.validate_token("invalid_token", "loop") is False

    def test_malformed_token_invalid_expiry(self, auth_config):
        """Token with non-integer expiry should be rejected."""
        assert auth_config.validate_token("loop:notanumber:sig", "loop") is False

    def test_wrong_loop_id_rejected(self, auth_config):
        """Token for different loop should be rejected."""
        token = auth_config.generate_token("loop1")
        assert auth_config.validate_token(token, "loop2") is False

    def test_empty_loop_id_accepts_any(self, auth_config):
        """Empty loop_id in validation should accept any token."""
        token = auth_config.generate_token("specific_loop")
        # Empty loop_id in validation accepts any
        assert auth_config.validate_token(token, "") is True

    def test_disabled_auth_allows_all(self, disabled_auth_config):
        """Disabled auth should allow any token."""
        # No token provided when auth disabled
        assert disabled_auth_config.validate_token("", "") is True
        # Random token when auth disabled
        assert disabled_auth_config.validate_token("random", "") is True

    def test_revoked_token_rejected(self, auth_config):
        """Revoked token should be rejected."""
        token = auth_config.generate_token("loop")
        assert auth_config.validate_token(token, "loop") is True

        auth_config.revoke_token(token)
        assert auth_config.validate_token(token, "loop") is False

    def test_unicode_in_loop_id(self, auth_config):
        """Unicode characters in loop_id should work."""
        token = auth_config.generate_token("loop_日本語")
        assert auth_config.validate_token(token, "loop_日本語") is True

    def test_empty_token_rejected_when_enabled(self, auth_config):
        """Empty token should be rejected when auth enabled."""
        assert auth_config.validate_token("", "loop") is False
        assert auth_config.validate_token(None, "loop") is False


# =============================================================================
# Test Token Revocation
# =============================================================================


class TestTokenRevocation:
    """Tests for token revocation."""

    def test_revoked_token_fails_validation(self, auth_config):
        """Revoked token should fail validation."""
        token = auth_config.generate_token("loop")
        auth_config.revoke_token(token)
        assert auth_config.validate_token(token, "loop") is False

    def test_revoke_twice_idempotent(self, auth_config):
        """Revoking same token twice should succeed."""
        token = auth_config.generate_token("loop")
        assert auth_config.revoke_token(token) is True
        assert auth_config.revoke_token(token) is True
        assert auth_config.get_revocation_count() == 1  # Only stored once

    def test_is_revoked_check(self, auth_config):
        """is_revoked should return correct status."""
        token = auth_config.generate_token("loop")
        assert auth_config.is_revoked(token) is False

        auth_config.revoke_token(token)
        assert auth_config.is_revoked(token) is True

    def test_revocation_capacity_cleanup(self, auth_config):
        """Max revocation capacity should trigger cleanup."""
        auth_config._max_revoked_tokens = 100

        # Add 100 revocations
        for i in range(100):
            auth_config.revoke_token(f"token_{i}")

        assert auth_config.get_revocation_count() == 100

        # Adding one more should trigger cleanup (remove 10%)
        auth_config.revoke_token("token_new")
        assert auth_config.get_revocation_count() <= 91

    def test_empty_token_revocation_returns_false(self, auth_config):
        """Empty token revocation should return False."""
        assert auth_config.revoke_token("") is False
        assert auth_config.revoke_token(None) is False

    def test_get_revocation_count(self, auth_config):
        """get_revocation_count should return correct count."""
        assert auth_config.get_revocation_count() == 0

        auth_config.revoke_token("token1")
        assert auth_config.get_revocation_count() == 1

        auth_config.revoke_token("token2")
        assert auth_config.get_revocation_count() == 2

    def test_revocation_uses_full_sha256_hash(self, auth_config):
        """Token revocation should use full 64-char SHA-256 hash, not truncated."""
        token = "test_token_for_hash_check"
        auth_config.revoke_token(token)

        # Compute the expected full SHA-256 hash
        expected_hash = hashlib.sha256(token.encode()).hexdigest()
        assert len(expected_hash) == 64  # Full SHA-256 is 64 hex chars

        # The stored hash should be the full 64-character hash
        with auth_config._revocation_lock:
            stored_hashes = list(auth_config._revoked_tokens.keys())
            assert len(stored_hashes) == 1
            assert stored_hashes[0] == expected_hash
            assert len(stored_hashes[0]) == 64

    def test_is_revoked_uses_full_sha256_hash(self, auth_config):
        """is_revoked should check against full SHA-256 hash."""
        token = "test_token_full_hash"
        full_hash = hashlib.sha256(token.encode()).hexdigest()

        # Manually insert with full hash
        with auth_config._revocation_lock:
            auth_config._revoked_tokens[full_hash] = time.time()

        # is_revoked should find it using full hash
        assert auth_config.is_revoked(token) is True

    def test_truncated_hash_not_used(self, auth_config):
        """Verify that truncated 16-char hashes are NOT used for revocation."""
        token = "test_token_no_truncation"
        truncated_hash = hashlib.sha256(token.encode()).hexdigest()[:16]

        # Insert with truncated hash (simulating old behavior)
        with auth_config._revocation_lock:
            auth_config._revoked_tokens[truncated_hash] = time.time()

        # is_revoked should NOT find it since it uses full hash now
        assert auth_config.is_revoked(token) is False


# =============================================================================
# Test Rate Limiting - Token
# =============================================================================


class TestTokenRateLimiting:
    """Tests for token-based rate limiting."""

    def test_rate_limit_enforced_at_threshold(self, auth_config):
        """Rate limit should block after threshold."""
        auth_config.rate_limit_per_minute = 5

        for i in range(5):
            allowed, remaining = auth_config.check_rate_limit("token1")
            assert allowed is True
            assert remaining == 4 - i

        # 6th request should be blocked
        allowed, remaining = auth_config.check_rate_limit("token1")
        assert allowed is False
        assert remaining == 0

    def test_per_token_isolation(self, auth_config):
        """Different tokens should have separate limits."""
        auth_config.rate_limit_per_minute = 3

        # Use up token1's limit
        for _ in range(3):
            auth_config.check_rate_limit("token1")

        # token1 is blocked
        allowed, _ = auth_config.check_rate_limit("token1")
        assert allowed is False

        # token2 should still work
        allowed, _ = auth_config.check_rate_limit("token2")
        assert allowed is True

    def test_sliding_window_behavior(self, auth_config):
        """Old requests should age out of window."""
        auth_config.rate_limit_per_minute = 2

        # Make requests at time 0
        with patch("time.time", return_value=1000.0):
            auth_config.check_rate_limit("token")
            auth_config.check_rate_limit("token")

            # Should be blocked
            allowed, _ = auth_config.check_rate_limit("token")
            assert allowed is False

        # After 61 seconds, old requests should age out
        with patch("time.time", return_value=1061.0):
            allowed, _ = auth_config.check_rate_limit("token")
            assert allowed is True

    def test_returns_tuple(self, auth_config):
        """Should return (allowed, remaining) tuple."""
        result = auth_config.check_rate_limit("token")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], int)

    def test_memory_bounds_respected(self, auth_config):
        """Max tracked entries should be respected."""
        auth_config._max_tracked_entries = 100

        # Add entries up to 90% threshold
        for i in range(91):
            auth_config.check_rate_limit(f"token_{i}")

        # Should trigger cleanup on next check
        auth_config.check_rate_limit("token_new")
        assert len(auth_config._token_request_counts) <= 100

    def test_stale_entry_cleanup(self, auth_config):
        """Stale entries should be cleaned up."""
        auth_config._max_tracked_entries = 10

        # Add old entries
        with patch("time.time", return_value=1000.0):
            for i in range(9):
                auth_config.check_rate_limit(f"token_{i}")

        # Move forward in time (entries become stale)
        with patch("time.time", return_value=1100.0):  # 100 seconds later
            # Trigger cleanup by exceeding 90% threshold
            auth_config.check_rate_limit("token_new")

            # Old stale entries should be cleaned
            # Only token_new should remain (others had no recent requests)

    def test_rate_limit_resets_after_window(self, auth_config):
        """Rate limit should reset after window expires."""
        auth_config.rate_limit_per_minute = 2

        with patch("time.time", return_value=1000.0):
            auth_config.check_rate_limit("token")
            auth_config.check_rate_limit("token")
            allowed, _ = auth_config.check_rate_limit("token")
            assert allowed is False

        # After window expires
        with patch("time.time", return_value=1061.0):
            allowed, remaining = auth_config.check_rate_limit("token")
            assert allowed is True
            assert remaining == 1


# =============================================================================
# Test Rate Limiting - IP
# =============================================================================


class TestIPRateLimiting:
    """Tests for IP-based rate limiting."""

    def test_ip_rate_limit_enforced(self, auth_config):
        """IP rate limit should block after threshold."""
        auth_config.ip_rate_limit_per_minute = 5

        for i in range(5):
            allowed, remaining = auth_config.check_rate_limit_by_ip("192.168.1.1")
            assert allowed is True
            assert remaining == 4 - i

        # 6th request should be blocked
        allowed, remaining = auth_config.check_rate_limit_by_ip("192.168.1.1")
        assert allowed is False
        assert remaining == 0

    def test_per_ip_isolation(self, auth_config):
        """Different IPs should have separate limits."""
        auth_config.ip_rate_limit_per_minute = 3

        # Use up first IP's limit
        for _ in range(3):
            auth_config.check_rate_limit_by_ip("192.168.1.1")

        # First IP is blocked
        allowed, _ = auth_config.check_rate_limit_by_ip("192.168.1.1")
        assert allowed is False

        # Second IP should still work
        allowed, _ = auth_config.check_rate_limit_by_ip("192.168.1.2")
        assert allowed is True

    def test_empty_ip_returns_allowed(self, auth_config):
        """Empty IP should return allowed without tracking."""
        allowed, remaining = auth_config.check_rate_limit_by_ip("")
        assert allowed is True
        assert remaining == auth_config.ip_rate_limit_per_minute

        # Verify no entry was created
        assert "" not in auth_config._ip_request_counts

    def test_ip_rate_limit_when_auth_disabled(self, disabled_auth_config):
        """IP rate limit should work even when auth disabled."""
        disabled_auth_config.ip_rate_limit_per_minute = 3

        for _ in range(3):
            disabled_auth_config.check_rate_limit_by_ip("10.0.0.1")

        allowed, _ = disabled_auth_config.check_rate_limit_by_ip("10.0.0.1")
        assert allowed is False

    def test_concurrent_ip_rate_limit_checks(self, auth_config):
        """Concurrent IP rate limit checks should be thread-safe."""
        auth_config.ip_rate_limit_per_minute = 100
        errors = []

        def check_limit():
            try:
                auth_config.check_rate_limit_by_ip("concurrent_ip")
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(check_limit) for _ in range(50)]
            for f in futures:
                f.result()

        assert len(errors) == 0

    def test_ip_memory_cleanup(self, auth_config):
        """IP rate limit should clean up stale entries."""
        auth_config._max_tracked_entries = 10

        # Add entries
        for i in range(9):
            auth_config.check_rate_limit_by_ip(f"192.168.1.{i}")

        assert len(auth_config._ip_request_counts) == 9


# =============================================================================
# Test Bearer Header Extraction
# =============================================================================


class TestBearerHeaderExtraction:
    """Tests for extracting tokens from requests."""

    def test_bearer_header_extracted(self, auth_config):
        """Bearer token should be extracted from header."""
        headers = {"Authorization": "Bearer my_token_here"}
        token = auth_config.extract_token_from_request(headers, {})
        assert token == "my_token_here"

    def test_case_sensitivity(self, auth_config):
        """Only 'Bearer' (capital B) should work."""
        headers = {"Authorization": "bearer my_token"}
        token = auth_config.extract_token_from_request(headers, {})
        assert token is None  # lowercase 'bearer' not recognized

    def test_query_param_fallback(self, auth_config):
        """Query params should be ignored for security (returns None)."""
        headers = {}
        query_params = {"token": ["query_token"]}
        token = auth_config.extract_token_from_request(headers, query_params)
        # Query params are NOT supported (they appear in server logs)
        assert token is None

    def test_bearer_takes_precedence(self, auth_config):
        """Bearer header should be the only accepted method."""
        headers = {"Authorization": "Bearer header_token"}
        query_params = {"token": ["query_token"]}
        token = auth_config.extract_token_from_request(headers, query_params)
        assert token == "header_token"

    def test_missing_authorization_returns_none(self, auth_config):
        """Missing Authorization header should return None."""
        token = auth_config.extract_token_from_request({}, {})
        assert token is None


# =============================================================================
# Test check_auth Integration
# =============================================================================


class TestCheckAuthIntegration:
    """Tests for check_auth function."""

    def test_auth_disabled_allows_all(self):
        """Disabled auth should allow all requests."""
        from aragora.server.auth import auth_config

        original_enabled = auth_config.enabled
        try:
            auth_config.enabled = False
            auth_config._ip_request_counts.clear()

            result = check_auth({}, "", "", "")
            assert result[0] is True
        finally:
            auth_config.enabled = original_enabled

    def test_auth_disabled_still_enforces_ip_limit(self):
        """IP rate limit should work even when auth disabled."""
        from aragora.server.auth import auth_config

        original_enabled = auth_config.enabled
        original_limit = auth_config.ip_rate_limit_per_minute
        try:
            auth_config.enabled = False
            auth_config.ip_rate_limit_per_minute = 3
            auth_config._ip_request_counts.clear()

            # Use up IP limit
            for _ in range(3):
                check_auth({}, "", "", "test_ip")

            # Should be blocked
            result = check_auth({}, "", "", "test_ip")
            assert result[0] is False
        finally:
            auth_config.enabled = original_enabled
            auth_config.ip_rate_limit_per_minute = original_limit

    def test_ip_rate_limit_blocks_before_token(self):
        """IP rate limit should block before token validation."""
        from aragora.server.auth import auth_config

        original_enabled = auth_config.enabled
        original_limit = auth_config.ip_rate_limit_per_minute
        try:
            auth_config.enabled = True
            auth_config.ip_rate_limit_per_minute = 2
            auth_config._ip_request_counts.clear()

            # Use up IP limit
            for _ in range(2):
                check_auth({}, "", "", "block_test_ip")

            # Should be blocked even with valid token
            token = auth_config.generate_token("loop")
            headers = {"Authorization": f"Bearer {token}"}
            result = check_auth(headers, "", "loop", "block_test_ip")
            assert result[0] is False
        finally:
            auth_config.enabled = original_enabled
            auth_config.ip_rate_limit_per_minute = original_limit

    def test_returns_tuple(self):
        """Should return (authenticated, remaining) tuple."""
        from aragora.server.auth import auth_config

        original_enabled = auth_config.enabled
        try:
            auth_config.enabled = False
            result = check_auth({}, "", "", "")
            assert isinstance(result, tuple)
            assert len(result) == 2
        finally:
            auth_config.enabled = original_enabled

    def test_no_token_when_enabled_returns_false(self):
        """Missing token when auth enabled should return False."""
        from aragora.server.auth import auth_config

        original_enabled = auth_config.enabled
        original_token = auth_config.api_token
        try:
            auth_config.enabled = True
            auth_config.api_token = "secret"
            auth_config._ip_request_counts.clear()

            result = check_auth({}, "", "", "some_ip")
            assert result[0] is False
        finally:
            auth_config.enabled = original_enabled
            auth_config.api_token = original_token


# =============================================================================
# Test generate_shareable_link
# =============================================================================


class TestGenerateShareableLink:
    """Tests for generate_shareable_link function."""

    def test_appends_token_to_url(self):
        """Should append session to URL."""
        from aragora.server.auth import auth_config

        original_token = auth_config.api_token
        original_enabled = auth_config.enabled
        try:
            auth_config.api_token = "secret"
            auth_config.enabled = True

            link = generate_shareable_link("http://example.com", "loop123")
            assert "session=" in link
            assert link.startswith("http://example.com?session=")
        finally:
            auth_config.api_token = original_token
            auth_config.enabled = original_enabled

    def test_uses_ampersand_when_query_exists(self):
        """Should use & when URL already has query params."""
        from aragora.server.auth import auth_config

        original_token = auth_config.api_token
        original_enabled = auth_config.enabled
        try:
            auth_config.api_token = "secret"
            auth_config.enabled = True

            link = generate_shareable_link("http://example.com?foo=bar", "loop123")
            assert "&session=" in link
        finally:
            auth_config.api_token = original_token
            auth_config.enabled = original_enabled

    def test_no_token_returns_original_url(self):
        """No api_token should return original URL."""
        from aragora.server.auth import auth_config

        original_token = auth_config.api_token
        try:
            auth_config.api_token = None

            link = generate_shareable_link("http://example.com", "loop123")
            assert link == "http://example.com"
        finally:
            auth_config.api_token = original_token


# =============================================================================
# Test Configuration
# =============================================================================


class TestAuthConfiguration:
    """Tests for AuthConfig configuration."""

    def test_configure_from_env_with_token(self):
        """Should enable auth when ARAGORA_API_TOKEN is set."""
        import os

        config = AuthConfig()
        with patch.dict(os.environ, {"ARAGORA_API_TOKEN": "test_secret"}):
            config.configure_from_env()

        assert config.enabled is True
        assert config.api_token == "test_secret"

    def test_configure_from_env_without_token(self):
        """Should keep auth disabled when no token."""
        import os

        config = AuthConfig()
        with patch.dict(os.environ, {}, clear=True):
            # Remove ARAGORA_API_TOKEN if present
            env_copy = os.environ.copy()
            env_copy.pop("ARAGORA_API_TOKEN", None)
            with patch.dict(os.environ, env_copy, clear=True):
                config.configure_from_env()

        assert config.enabled is False

    @pytest.mark.parametrize("env_name", ["ARAGORA_ENV", "ARAGORA_ENVIRONMENT"])
    @pytest.mark.parametrize("env_value", ["production", "prod", "staging", "stage"])
    def test_configure_requires_managed_auth_for_strict_modes(self, env_name, env_value):
        config = AuthConfig()
        with patch.dict(os.environ, {env_name: env_value}, clear=True):
            with pytest.raises(AuthenticationError):
                config.configure_from_env()

    @pytest.mark.parametrize(
        "env", [{"ARAGORA_ENV": "production"}, {"ARAGORA_SECRETS_STRICT": "true"}]
    )
    def test_configure_rejects_env_only_token_in_strict_mode(self, env):
        config = AuthConfig()
        with patch.dict(
            os.environ,
            {**env, "ARAGORA_API_TOKEN": "raw-env-token"},
            clear=True,
        ):
            with pytest.raises(AuthenticationError):
                config.configure_from_env()

    def test_configure_rejects_invalid_explicit_custody_in_development(self):
        config = AuthConfig()
        with patch.dict(os.environ, {"ARAGORA_SECRETS_DIR": "relative/path"}, clear=True):
            with pytest.raises(AuthenticationError, match="Invalid .* custody"):
                config.configure_from_env()

    def test_configure_uses_mounted_api_token_in_production(self, tmp_path):
        from aragora.config.secrets import SecretManager, SecretsConfig

        secret_path = tmp_path / "ARAGORA_API_TOKEN"
        secret_path.write_text("mounted-token", encoding="utf-8")
        secret_path.chmod(0o600)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        config = AuthConfig()
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=True),
        ):
            config.configure_from_env()

        assert config.enabled is True
        assert config.api_token == "mounted-token"

    def test_configure_ttl_from_env(self):
        """Should load TTL from environment."""
        import os

        config = AuthConfig()
        with patch.dict(os.environ, {"ARAGORA_TOKEN_TTL": "7200"}):
            config.configure_from_env()

        assert config.token_ttl == 7200

    def test_invalid_ttl_ignored(self):
        """Invalid TTL should be ignored."""
        import os

        config = AuthConfig()
        original_ttl = config.token_ttl
        with patch.dict(os.environ, {"ARAGORA_TOKEN_TTL": "not_a_number"}):
            config.configure_from_env()

        assert config.token_ttl == original_ttl

    def test_configure_origins_from_env(self):
        """Should load origins from centralized CORS config."""
        config = AuthConfig()
        expected_origins = ["http://localhost:3000", "http://example.com"]
        with patch("aragora.server.auth.cors_config") as mock_cors:
            mock_cors.get_origins_list.return_value = expected_origins
            config.configure_from_env()

        assert "http://localhost:3000" in config.allowed_origins
        assert "http://example.com" in config.allowed_origins


# =============================================================================
# Test Rate Limit Boundary Conditions
# =============================================================================


class TestRateLimitBoundaries:
    """Tests for rate limit boundary conditions."""

    def test_rate_limit_exactly_at_limit(self, auth_config):
        """Request count exactly at limit should be rejected."""
        auth_config.rate_limit_per_minute = 5

        # Make exactly 5 requests
        for i in range(5):
            allowed, remaining = auth_config.check_rate_limit("boundary_token")
            assert allowed is True

        # The 6th request (at limit) should be rejected
        allowed, remaining = auth_config.check_rate_limit("boundary_token")
        assert allowed is False
        assert remaining == 0

    def test_rate_limit_one_below_limit(self, auth_config):
        """Request at limit-1 should be allowed with remaining=1."""
        auth_config.rate_limit_per_minute = 3

        # Make 2 requests (limit - 1)
        auth_config.check_rate_limit("token")
        allowed, remaining = auth_config.check_rate_limit("token")

        assert allowed is True
        assert remaining == 1  # One slot left before hitting limit

    def test_rate_limit_boundary_60_seconds(self, auth_config):
        """Requests at exactly 60 seconds should be excluded from window."""
        auth_config.rate_limit_per_minute = 2

        # Make requests at time 1000
        with patch("time.time", return_value=1000.0):
            auth_config.check_rate_limit("token")
            auth_config.check_rate_limit("token")

        # Exactly 60 seconds later, old requests should be excluded
        with patch("time.time", return_value=1060.0):
            # Window is > window_start, so 1000.0 is NOT > 1000.0
            # Requests at 1000.0 are excluded when window_start = 1000.0
            allowed, remaining = auth_config.check_rate_limit("token")
            assert allowed is True

    def test_ip_rate_limit_exactly_at_limit(self, auth_config):
        """IP request count exactly at limit should be rejected."""
        auth_config.ip_rate_limit_per_minute = 3

        for _ in range(3):
            auth_config.check_rate_limit_by_ip("192.168.1.100")

        allowed, remaining = auth_config.check_rate_limit_by_ip("192.168.1.100")
        assert allowed is False
        assert remaining == 0


# =============================================================================
# Test Combined Rate Limits
# =============================================================================


class TestCombinedRateLimits:
    """Tests for interactions between token and IP rate limits."""

    def test_both_rate_limits_exceeded_ip_checked_first(self):
        """When both token and IP limits exceeded, IP is checked first."""
        from aragora.server.auth import auth_config

        original_enabled = auth_config.enabled
        original_token_limit = auth_config.rate_limit_per_minute
        original_ip_limit = auth_config.ip_rate_limit_per_minute
        original_api_token = auth_config.api_token

        try:
            auth_config.enabled = True
            auth_config.api_token = "test_secret"
            auth_config.rate_limit_per_minute = 5
            auth_config.ip_rate_limit_per_minute = 3
            auth_config._ip_request_counts.clear()
            auth_config._token_request_counts.clear()

            # Generate a valid token
            token = auth_config.generate_token("loop")

            # Use up IP limit (3 requests)
            for _ in range(3):
                check_auth({"Authorization": f"Bearer {token}"}, "", "loop", "test_combined_ip")

            # Both limits not exceeded yet for token, but IP is exhausted
            # Next request should fail due to IP limit (checked first)
            result = check_auth(
                {"Authorization": f"Bearer {token}"}, "", "loop", "test_combined_ip"
            )
            assert result[0] is False

        finally:
            auth_config.enabled = original_enabled
            auth_config.rate_limit_per_minute = original_token_limit
            auth_config.ip_rate_limit_per_minute = original_ip_limit
            auth_config.api_token = original_api_token

    def test_different_tokens_same_ip(self, auth_config):
        """Multiple tokens from same IP should share IP rate limit."""
        auth_config.ip_rate_limit_per_minute = 4

        # Use different tokens but same IP
        auth_config.check_rate_limit_by_ip("shared_ip")  # token1
        auth_config.check_rate_limit_by_ip("shared_ip")  # token2
        auth_config.check_rate_limit_by_ip("shared_ip")  # token3
        auth_config.check_rate_limit_by_ip("shared_ip")  # token4

        # IP limit should be exhausted regardless of token
        allowed, _ = auth_config.check_rate_limit_by_ip("shared_ip")
        assert allowed is False

    def test_same_token_different_ips(self, auth_config):
        """Same token from different IPs should share token rate limit."""
        auth_config.rate_limit_per_minute = 3

        # Same token, different IPs
        auth_config.check_rate_limit("shared_token")  # IP1
        auth_config.check_rate_limit("shared_token")  # IP2
        auth_config.check_rate_limit("shared_token")  # IP3

        # Token limit should be exhausted regardless of IP
        allowed, _ = auth_config.check_rate_limit("shared_token")
        assert allowed is False


# =============================================================================
# Test Token Edge Cases
# =============================================================================


class TestTokenEdgeCases:
    """Tests for token edge cases."""

    def test_revoke_expired_token(self, auth_config):
        """Revoking already-expired token should succeed."""
        with patch("time.time", return_value=1000.0):
            token = auth_config.generate_token("loop", expires_in=10)

        # Token is now expired
        with patch("time.time", return_value=1100.0):
            # Should still be able to revoke it
            result = auth_config.revoke_token(token)
            assert result is True
            assert auth_config.is_revoked(token) is True

    def test_revoke_then_regenerate_same_loop_id(self, auth_config):
        """New token for same loop_id after revocation should work."""
        # Generate and revoke first token at time 1000
        with patch("time.time", return_value=1000.0):
            token1 = auth_config.generate_token("myloop")
        auth_config.revoke_token(token1)

        # Generate new token for same loop_id at time 1001 (different timestamp = different token)
        with patch("time.time", return_value=1001.0):
            token2 = auth_config.generate_token("myloop")

        # Tokens should be different due to different expiry times
        assert token1 != token2

        # Validate at a time before both expire
        with patch("time.time", return_value=1500.0):
            # Old token should still be revoked
            assert auth_config.validate_token(token1, "myloop") is False
            # New token should work
            assert auth_config.validate_token(token2, "myloop") is True

    def test_token_with_zero_ttl(self, auth_config):
        """Token with 0 TTL should be immediately invalid."""
        with patch("time.time", return_value=1000.0):
            token = auth_config.generate_token("loop", expires_in=0)

        # Even at the same time, token should be expired (expires = current time)
        with patch("time.time", return_value=1000.1):
            assert auth_config.validate_token(token, "loop") is False

    def test_token_with_negative_ttl(self, auth_config):
        """Token with negative TTL should be immediately invalid."""
        with patch("time.time", return_value=1000.0):
            token = auth_config.generate_token("loop", expires_in=-100)

        # Should be expired
        with patch("time.time", return_value=1000.0):
            assert auth_config.validate_token(token, "loop") is False


# =============================================================================
# Test IP Address Edge Cases
# =============================================================================


class TestIPAddressEdgeCases:
    """Tests for IP address edge cases."""

    def test_ipv6_rate_limiting(self, auth_config):
        """IPv6 addresses should be tracked correctly."""
        auth_config.ip_rate_limit_per_minute = 3

        ipv6_addr = "2001:0db8:85a3:0000:0000:8a2e:0370:7334"

        for _ in range(3):
            allowed, _ = auth_config.check_rate_limit_by_ip(ipv6_addr)
            assert allowed is True

        # Should be blocked
        allowed, _ = auth_config.check_rate_limit_by_ip(ipv6_addr)
        assert allowed is False

    def test_ipv6_compressed_format(self, auth_config):
        """Compressed IPv6 addresses should be tracked correctly."""
        auth_config.ip_rate_limit_per_minute = 2

        ipv6_addr = "::1"  # Localhost in IPv6

        auth_config.check_rate_limit_by_ip(ipv6_addr)
        auth_config.check_rate_limit_by_ip(ipv6_addr)

        allowed, _ = auth_config.check_rate_limit_by_ip(ipv6_addr)
        assert allowed is False

    def test_malformed_ip_address_still_tracked(self, auth_config):
        """Malformed IP strings should still be tracked (no crash)."""
        auth_config.ip_rate_limit_per_minute = 2

        malformed_ip = "not.an.ip.address"

        # Should not crash
        allowed, _ = auth_config.check_rate_limit_by_ip(malformed_ip)
        assert allowed is True

        auth_config.check_rate_limit_by_ip(malformed_ip)
        allowed, _ = auth_config.check_rate_limit_by_ip(malformed_ip)
        assert allowed is False


# =============================================================================
# Test Bearer Header Edge Cases
# =============================================================================


class TestBearerHeaderParsing:
    """Tests for bearer header parsing edge cases."""

    def test_bearer_with_tab_separator(self, auth_config):
        """Tab after 'Bearer' instead of space should not extract token."""
        headers = {"Authorization": "Bearer\tmy_token"}
        token = auth_config.extract_token_from_request(headers, {})
        # "Bearer " (with space) is required, tab should not work
        assert token is None

    def test_bearer_with_multiple_spaces(self, auth_config):
        """Multiple spaces after 'Bearer' should include leading spaces in token."""
        headers = {"Authorization": "Bearer  my_token"}
        token = auth_config.extract_token_from_request(headers, {})
        # Should include the leading space
        assert token == " my_token"

    def test_multiple_token_query_params(self, auth_config):
        """Query params are ignored for security - should return None."""
        headers = {}
        query_params = {"token": ["first_token", "second_token", "third_token"]}
        token = auth_config.extract_token_from_request(headers, query_params)
        # Query params not supported (they appear in logs)
        assert token is None

    def test_empty_token_query_param(self, auth_config):
        """Query params are ignored for security - should return None."""
        headers = {}
        query_params = {"token": [""]}
        token = auth_config.extract_token_from_request(headers, query_params)
        # Query params not supported (they appear in logs)
        assert token is None

    def test_empty_token_list(self, auth_config):
        """Empty token list in query params should return None."""
        headers = {}
        query_params = {"token": []}
        token = auth_config.extract_token_from_request(headers, query_params)
        assert token is None


# =============================================================================
# Test Concurrent Access
# =============================================================================


class TestConcurrentAccess:
    """Tests for concurrent access scenarios."""

    def test_concurrent_rate_limit_updates(self, auth_config):
        """Multiple threads hitting rate limit simultaneously should be thread-safe."""
        auth_config.rate_limit_per_minute = 100
        errors = []
        results = []

        def worker():
            try:
                for _ in range(10):
                    allowed, remaining = auth_config.check_rate_limit("concurrent_token")
                    results.append((allowed, remaining))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All requests should have been processed
        assert len(results) == 100

    def test_revoke_during_validation_concurrent(self, auth_config):
        """Token revoked while being validated in another thread should be safe."""
        errors = []
        token = auth_config.generate_token("loop")

        def validator():
            try:
                for _ in range(50):
                    auth_config.validate_token(token, "loop")
            except Exception as e:
                errors.append(e)

        def revoker():
            try:
                time.sleep(0.001)  # Small delay to let validator start
                auth_config.revoke_token(token)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=validator),
            threading.Thread(target=revoker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Token should be revoked now
        assert auth_config.is_revoked(token) is True

    def test_cleanup_during_rate_limit_check(self, auth_config):
        """Rate limit cleanup triggered during concurrent access should be safe."""
        auth_config._max_tracked_entries = 50
        auth_config.rate_limit_per_minute = 1000
        errors = []

        def worker(worker_id):
            try:
                for i in range(20):
                    auth_config.check_rate_limit(f"token_{worker_id}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Should have cleaned up to stay under limit
        assert len(auth_config._token_request_counts) <= 50

    def test_concurrent_revocation_and_is_revoked(self, auth_config):
        """Concurrent revocation and is_revoked checks should be thread-safe."""
        errors = []
        tokens = [auth_config.generate_token(f"loop_{i}") for i in range(20)]

        def revoker():
            try:
                for token in tokens:
                    auth_config.revoke_token(token)
            except Exception as e:
                errors.append(e)

        def checker():
            try:
                for token in tokens:
                    auth_config.is_revoked(token)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=revoker),
            threading.Thread(target=checker),
            threading.Thread(target=checker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# =============================================================================
# Test Security Edge Cases
# =============================================================================


class TestSecurityEdgeCases:
    """Security-focused edge case tests."""

    def test_revocation_storage_limit_enforced(self, auth_config):
        """Verify 10,000 revocation limit is enforced with cleanup."""
        auth_config._max_revoked_tokens = 100  # Use smaller limit for testing

        # Add 100 revocations
        for i in range(100):
            auth_config.revoke_token(f"security_token_{i}")

        assert auth_config.get_revocation_count() == 100

        # Adding more should trigger cleanup
        for i in range(20):
            auth_config.revoke_token(f"security_token_extra_{i}")

        # Should stay within bounds
        assert auth_config.get_revocation_count() <= 100

    def test_rate_limit_memory_bounded(self, auth_config):
        """Verify rate limit tracking doesn't grow unbounded."""
        auth_config._max_tracked_entries = 100
        auth_config.rate_limit_per_minute = 1000

        # Add many unique tokens
        for i in range(150):
            auth_config.check_rate_limit(f"memory_token_{i}")

        # Should have cleaned up
        assert len(auth_config._token_request_counts) <= 100

    def test_ip_rate_limit_memory_bounded(self, auth_config):
        """Verify IP rate limit tracking doesn't grow unbounded."""
        auth_config._max_tracked_entries = 100
        auth_config.ip_rate_limit_per_minute = 1000

        # Add many unique IPs
        for i in range(150):
            auth_config.check_rate_limit_by_ip(f"192.168.{i // 256}.{i % 256}")

        # Should have cleaned up
        assert len(auth_config._ip_request_counts) <= 100


# =============================================================================
# Test Loop ID Extraction and Validation
# =============================================================================


class TestLoopIdExtraction:
    """Tests for extract_loop_id_from_token."""

    def test_extract_loop_id_from_valid_token(self, auth_config):
        """Should extract loop_id from a valid token."""
        token = auth_config.generate_token("my_loop_123")
        loop_id = auth_config.extract_loop_id_from_token(token)
        assert loop_id == "my_loop_123"

    def test_extract_loop_id_empty_token(self, auth_config):
        """Should return None for empty token."""
        assert auth_config.extract_loop_id_from_token("") is None
        assert auth_config.extract_loop_id_from_token(None) is None

    def test_extract_loop_id_invalid_format(self, auth_config):
        """Should return None for malformed tokens."""
        assert auth_config.extract_loop_id_from_token("invalid") is None
        assert auth_config.extract_loop_id_from_token("one:two") is None
        # ":::" produces ":" which is technically valid format but empty-ish
        # The key test is that malformed tokens don't crash


class TestValidateTokenForLoop:
    """Tests for validate_token_for_loop."""

    def test_valid_token_for_correct_loop(self, auth_config):
        """Should validate token for the correct loop."""
        token = auth_config.generate_token("loop_abc")
        is_valid, err = auth_config.validate_token_for_loop(token, "loop_abc")
        assert is_valid is True
        assert err == ""

    def test_valid_token_for_wrong_loop(self, auth_config):
        """Should reject token for a different loop."""
        token = auth_config.generate_token("loop_abc")
        is_valid, err = auth_config.validate_token_for_loop(token, "loop_xyz")
        assert is_valid is False
        assert "not authorized for loop" in err

    def test_revoked_token_rejected(self, auth_config):
        """Should reject revoked tokens."""
        token = auth_config.generate_token("loop_abc")
        auth_config.revoke_token(token)
        is_valid, err = auth_config.validate_token_for_loop(token, "loop_abc")
        assert is_valid is False
        assert "revoked" in err.lower()

    def test_missing_token_rejected(self, auth_config):
        """Should reject missing tokens."""
        is_valid, err = auth_config.validate_token_for_loop("", "loop_abc")
        assert is_valid is False
        assert "Authentication required" in err

    def test_missing_loop_id_rejected(self, auth_config):
        """Should reject missing loop_id."""
        token = auth_config.generate_token("loop_abc")
        is_valid, err = auth_config.validate_token_for_loop(token, "")
        assert is_valid is False
        assert "Loop ID required" in err

    def test_disabled_auth_allows_all(self, disabled_auth_config):
        """Should allow all when auth is disabled."""
        is_valid, err = disabled_auth_config.validate_token_for_loop("any_token", "any_loop")
        assert is_valid is True
        assert err == ""

    def test_expired_token_rejected(self, auth_config):
        """Should reject expired tokens."""
        token = auth_config.generate_token("loop_abc", expires_in=-1)
        is_valid, err = auth_config.validate_token_for_loop(token, "loop_abc")
        assert is_valid is False
        assert "Invalid or expired" in err
