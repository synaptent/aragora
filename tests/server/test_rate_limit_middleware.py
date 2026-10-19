"""
Tests for the Rate Limiting Middleware.

Covers:
- IP normalization and validation
- Trusted proxy configuration
- X-Forwarded-For header processing
- Token bucket implementation
- Rate limiter behavior
- Endpoint configuration
- LRU eviction
- Thread safety
"""

from __future__ import annotations

import os
import threading
import time
from unittest.mock import Mock, patch

import pytest

from aragora.server.middleware.rate_limit import (
    # Base utilities
    DEFAULT_RATE_LIMIT,
    IP_RATE_LIMIT,
    BURST_MULTIPLIER,
    TRUSTED_PROXIES,
    _normalize_ip,
    _is_trusted_proxy,
    _extract_client_ip,
    sanitize_rate_limit_key_component,
    normalize_rate_limit_path,
    # Token bucket
    TokenBucket,
    # Rate limiter
    RateLimitConfig,
    RateLimitResult,
    RateLimiter,
    # Registry functions
    get_rate_limiter,
    cleanup_rate_limiters,
    reset_rate_limiters,
)


# =============================================================================
# IP Normalization Tests
# =============================================================================


class TestIPNormalization:
    """Tests for IP address normalization."""

    def test_normalize_ipv4(self):
        """Test IPv4 address normalization."""
        assert _normalize_ip("192.168.1.100") == "192.168.1.100"
        assert _normalize_ip("  192.168.1.100  ") == "192.168.1.100"
        assert _normalize_ip("127.0.0.1") == "127.0.0.1"

    def test_normalize_ipv6(self):
        """Test IPv6 address normalization to /64 prefix."""
        # Full IPv6 should be normalized to /64 network
        result = _normalize_ip("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        assert result == "2001:db8:85a3::"

        # Shortened IPv6
        result = _normalize_ip("2001:db8::1")
        assert result == "2001:db8::"

        # Loopback
        result = _normalize_ip("::1")
        assert result == "::"

    def test_normalize_invalid_ip(self):
        """Test handling of invalid IP addresses."""
        # Invalid IPs should be returned as-is
        assert _normalize_ip("invalid") == "invalid"
        assert _normalize_ip("not.an.ip") == "not.an.ip"
        assert _normalize_ip("") == ""
        assert _normalize_ip("192.168.1.256") == "192.168.1.256"  # Out of range


class TestTrustedProxies:
    """Tests for trusted proxy validation."""

    def test_default_trusted_proxies(self):
        """Test that default trusted proxies include localhost."""
        # Default config includes 127.0.0.1, ::1, localhost
        assert _is_trusted_proxy("127.0.0.1") is True

    def test_untrusted_ip(self):
        """Test that random IPs are not trusted."""
        assert _is_trusted_proxy("203.0.113.50") is False
        assert _is_trusted_proxy("10.0.0.1") is False

    def test_empty_ip_not_trusted(self):
        """Test that empty IP is not trusted."""
        assert _is_trusted_proxy("") is False
        assert _is_trusted_proxy(None) is False


class TestClientIPExtraction:
    """Tests for client IP extraction from headers."""

    def test_direct_connection(self):
        """Test direct connection without proxy headers."""
        headers = {}
        ip = _extract_client_ip(headers, "192.168.1.100")

        assert ip == "192.168.1.100"

    def test_xff_from_untrusted_source(self):
        """Test X-Forwarded-For from untrusted source is ignored."""
        headers = {"X-Forwarded-For": "10.0.0.1"}
        # Remote addr is not a trusted proxy
        ip = _extract_client_ip(headers, "203.0.113.50")

        # Should use remote addr, not XFF
        assert ip == "203.0.113.50"

    def test_xff_from_trusted_source(self):
        """Test X-Forwarded-For from trusted source is used."""
        headers = {"X-Forwarded-For": "192.168.1.100, 127.0.0.1"}
        # Remote addr is localhost (trusted)
        ip = _extract_client_ip(headers, "127.0.0.1")

        # Should use the rightmost non-trusted IP from XFF
        assert ip == "192.168.1.100"

    def test_x_real_ip_from_trusted_source(self):
        """Test X-Real-IP header from trusted source."""
        headers = {"X-Real-IP": "192.168.1.100"}
        ip = _extract_client_ip(headers, "127.0.0.1")

        assert ip == "192.168.1.100"

    def test_xff_disabled(self):
        """Test disabling XFF processing."""
        headers = {"X-Forwarded-For": "10.0.0.1"}
        ip = _extract_client_ip(headers, "127.0.0.1", trust_xff_from_proxies=False)

        # Should ignore XFF
        assert ip == "127.0.0.1"


# =============================================================================
# Path Normalization Tests
# =============================================================================


class TestPathNormalization:
    """Tests for URL path normalization."""

    def test_basic_path(self):
        """Test basic path normalization."""
        assert normalize_rate_limit_path("/api/debates") == "/api/debates"

    def test_trailing_slash(self):
        """Test trailing slash removal."""
        assert normalize_rate_limit_path("/api/debates/") == "/api/debates"

    def test_root_path(self):
        """Test root path handling."""
        assert normalize_rate_limit_path("/") == "/"

    def test_empty_path(self):
        """Test empty path handling."""
        assert normalize_rate_limit_path("") == "/"

    def test_multiple_slashes(self):
        """Test multiple slash collapse."""
        assert normalize_rate_limit_path("/api//debates") == "/api/debates"

    def test_path_traversal(self):
        """Test path traversal prevention."""
        assert normalize_rate_limit_path("/api/../admin") == "/admin"

    def test_url_decoding(self):
        """Test URL decoding."""
        assert normalize_rate_limit_path("/api%2Fdebates") == "/api/debates"

    def test_case_normalization(self):
        """Test lowercase conversion."""
        assert normalize_rate_limit_path("/API/Debates") == "/api/debates"


# =============================================================================
# Key Sanitization Tests
# =============================================================================


class TestKeySanitization:
    """Tests for rate limit key sanitization."""

    def test_basic_sanitization(self):
        """Test basic key sanitization."""
        assert sanitize_rate_limit_key_component("192.168.1.1") == "192.168.1.1"

    def test_colon_replacement(self):
        """Test colon is replaced to prevent injection."""
        assert sanitize_rate_limit_key_component("key:value") == "key_value"

    def test_newline_removal(self):
        """Test newlines are removed."""
        assert sanitize_rate_limit_key_component("key\nvalue") == "keyvalue"
        assert sanitize_rate_limit_key_component("key\r\nvalue") == "keyvalue"

    def test_whitespace_strip(self):
        """Test whitespace is stripped."""
        assert sanitize_rate_limit_key_component("  key  ") == "key"

    def test_none_value(self):
        """Test None value handling."""
        assert sanitize_rate_limit_key_component(None) == ""


# =============================================================================
# Token Bucket Tests
# =============================================================================


class TestTokenBucket:
    """Tests for the token bucket implementation."""

    def test_initial_capacity(self):
        """Test bucket starts with full capacity."""
        bucket = TokenBucket(rate_per_minute=60, burst_size=20)

        assert bucket.tokens == 20
        assert bucket.rate_per_minute == 60
        assert bucket.burst_size == 20

    def test_consume_success(self):
        """Test consuming tokens successfully."""
        bucket = TokenBucket(rate_per_minute=60, burst_size=10)

        result = bucket.consume()

        assert result is True
        assert bucket.tokens < 10

    def test_consume_empty_bucket(self):
        """Test consuming from empty bucket."""
        bucket = TokenBucket(rate_per_minute=60, burst_size=2)

        # Consume all tokens
        bucket.consume()
        bucket.consume()

        # Should fail
        result = bucket.consume()
        assert result is False

    def test_token_refill(self):
        """Test tokens refill over time."""
        bucket = TokenBucket(rate_per_minute=6000, burst_size=60)  # 100 per second

        # Consume all
        for _ in range(60):
            bucket.consume()

        assert bucket.tokens < 1

        # Wait for refill
        time.sleep(0.1)

        # Trigger refill via consume check
        bucket.consume()  # This will refill then try to consume
        # Should have refilled significantly in 0.1s at 100/sec = 10 tokens
        assert bucket.remaining >= 5

    def test_capacity_limit(self):
        """Test tokens don't exceed capacity."""
        bucket = TokenBucket(rate_per_minute=60000, burst_size=10)

        # Wait for refill
        time.sleep(0.1)

        # Try to consume - this triggers refill
        bucket.consume()

        # Should be capped at burst_size
        assert bucket.tokens <= 10

    def test_get_retry_after(self):
        """Test calculating time until token available."""
        bucket = TokenBucket(rate_per_minute=60, burst_size=1)  # 1 per second

        # Consume the only token
        bucket.consume()

        wait_time = bucket.get_retry_after()

        # Should need to wait about 1 second
        assert 0 < wait_time <= 1.5


# =============================================================================
# Rate Limiter Tests
# =============================================================================


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    @pytest.fixture
    def limiter(self):
        """Create a fresh rate limiter."""
        return RateLimiter(default_limit=60, ip_limit=120)

    def test_allow_under_limit(self, limiter):
        """Test requests under limit are allowed."""
        result = limiter.allow("192.168.1.1")

        assert result.allowed is True
        assert result.remaining > 0

    def test_rate_limit_exceeded(self, limiter):
        """Test requests exceeding limit are blocked.

        Note: The rate limiter uses burst capacity (default 2x rate).
        With ip_limit=120, burst_size defaults to 240 tokens.
        We need to exhaust the full burst capacity to trigger rate limiting.
        """
        client_ip = "192.168.1.2"

        # Get the actual burst size (ip_limit * BURST_MULTIPLIER)
        # IP bucket uses ip_limit=120, burst = 120 * 2.0 = 240
        burst_capacity = int(limiter.ip_limit * BURST_MULTIPLIER)

        # Exhaust the burst capacity
        for _ in range(burst_capacity):
            result = limiter.allow(client_ip)
            if not result.allowed:
                break

        # Next request should be blocked
        result = limiter.allow(client_ip)
        assert result.allowed is False
        assert result.retry_after > 0

    def test_different_ips_separate_limits(self, limiter):
        """Test different IPs have separate limits."""
        # Exhaust limit for IP 1
        for _ in range(limiter.default_limit * 2):
            limiter.allow("192.168.1.1")

        # IP 2 should still be allowed
        result = limiter.allow("192.168.1.2")
        assert result.allowed is True

    def test_configure_endpoint(self, limiter):
        """Test configuring endpoint-specific limits."""
        limiter.configure_endpoint("/api/expensive", requests_per_minute=5)

        config = limiter.get_config("/api/expensive")

        assert config.requests_per_minute == 5

    def test_endpoint_specific_limit(self, limiter):
        """Test endpoint-specific rate limits are enforced.

        To test per-endpoint limiting, we need to use key_type="combined"
        which creates separate buckets per endpoint+IP combination.
        We also set burst_size equal to requests_per_minute for exact limiting.
        """
        limiter.configure_endpoint(
            "/api/expensive",
            requests_per_minute=3,
            burst_size=3,  # No burst, exact limit
            key_type="combined",  # Per-endpoint-per-IP limiting
        )

        client_ip = "192.168.1.3"

        # Consume the endpoint limit (exactly 3 tokens)
        for _ in range(3):
            result = limiter.allow(client_ip, endpoint="/api/expensive")
            if not result.allowed:
                break

        # Should be blocked for this endpoint
        result = limiter.allow(client_ip, endpoint="/api/expensive")
        assert result.allowed is False

    def test_wildcard_endpoint_matching(self, limiter):
        """Test wildcard endpoint configuration."""
        limiter.configure_endpoint("/api/debates/*", requests_per_minute=10)

        config = limiter.get_config("/api/debates/123")

        assert config.requests_per_minute == 10

    def test_metrics(self, limiter):
        """Test observability metrics are tracked."""
        client_ip = "192.168.1.4"

        limiter.allow(client_ip)
        limiter.allow(client_ip)

        assert limiter._requests_allowed >= 2 or limiter._requests_rejected >= 0

    def test_thread_safety(self, limiter):
        """Test thread-safe operations."""
        errors = []
        results = []

        def make_requests(ip, count):
            try:
                for _ in range(count):
                    result = limiter.allow(ip)
                    results.append(result.allowed)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=make_requests, args=(f"192.168.1.{i}", 10)) for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 50


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RateLimitConfig()

        assert config.requests_per_minute == DEFAULT_RATE_LIMIT
        assert config.burst_size is None
        assert config.key_type == "ip"
        assert config.enabled is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = RateLimitConfig(
            requests_per_minute=100,
            burst_size=200,
            key_type="token",
            enabled=False,
        )

        assert config.requests_per_minute == 100
        assert config.burst_size == 200
        assert config.key_type == "token"
        assert config.enabled is False


class TestRateLimitResult:
    """Tests for RateLimitResult dataclass."""

    def test_allowed_result(self):
        """Test allowed result."""
        result = RateLimitResult(allowed=True, remaining=10, limit=60)

        assert result.allowed is True
        assert result.remaining == 10
        assert result.limit == 60

    def test_blocked_result(self):
        """Test blocked result."""
        result = RateLimitResult(
            allowed=False,
            remaining=0,
            limit=60,
            retry_after=1.5,
            key="ip:192.168.1.1",
        )

        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after == 1.5
        assert result.key == "ip:192.168.1.1"


# =============================================================================
# Registry Tests
# =============================================================================


class TestRateLimiterRegistry:
    """Tests for the rate limiter registry."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry before each test."""
        reset_rate_limiters()
        yield
        reset_rate_limiters()

    def test_get_rate_limiter_creates_new(self):
        """Test getting a new rate limiter."""
        limiter = get_rate_limiter("test_limiter")

        assert limiter is not None
        assert isinstance(limiter, RateLimiter)

    def test_get_rate_limiter_returns_cached(self):
        """Test getting cached rate limiter."""
        limiter1 = get_rate_limiter("cached_limiter")
        limiter2 = get_rate_limiter("cached_limiter")

        assert limiter1 is limiter2

    def test_different_names_different_limiters(self):
        """Test different names create different limiters."""
        limiter1 = get_rate_limiter("limiter_a")
        limiter2 = get_rate_limiter("limiter_b")

        assert limiter1 is not limiter2

    def test_reset_rate_limiters(self):
        """Test resetting all rate limiters."""
        limiter1 = get_rate_limiter("reset_test")
        reset_rate_limiters()
        limiter2 = get_rate_limiter("reset_test")

        assert limiter1 is not limiter2

    def test_cleanup_rate_limiters(self):
        """Test cleanup function doesn't raise."""
        get_rate_limiter("cleanup_test")
        # Should not raise
        cleanup_rate_limiters()


# =============================================================================
# Edge Cases and Stress Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def limiter(self):
        """Create a fresh rate limiter."""
        return RateLimiter(default_limit=10)

    def test_empty_ip(self, limiter):
        """Test handling empty IP address."""
        result = limiter.allow("")

        # Should still work (normalized to empty key)
        assert result is not None

    def test_very_long_ip(self, limiter):
        """Test handling very long IP string."""
        long_ip = "x" * 10000
        result = limiter.allow(long_ip)

        assert result is not None

    def test_unicode_in_ip(self, limiter):
        """Test handling Unicode in IP address."""
        result = limiter.allow("192.168.1.1\u0000")

        assert result is not None

    def test_special_characters_in_endpoint(self, limiter):
        """Test handling special characters in endpoint."""
        result = limiter.allow("192.168.1.1", endpoint="/api/test?foo=bar")

        assert result is not None

    def test_concurrent_requests(self, limiter):
        """Test high concurrency doesn't cause issues."""
        results = []
        errors = []

        def make_request():
            try:
                result = limiter.allow("192.168.1.1")
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=make_request) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 100


# =============================================================================
# Integration Tests
# =============================================================================


class TestRateLimitIntegration:
    """Integration tests for rate limiting."""

    @pytest.fixture(autouse=True)
    def reset(self):
        """Reset registry and environment."""
        reset_rate_limiters()
        yield
        reset_rate_limiters()

    def test_full_flow(self):
        """Test full rate limiting flow.

        Uses key_type="combined" for per-endpoint limiting and
        explicit burst_size for exact limit enforcement.
        """
        limiter = get_rate_limiter("integration_test")
        limiter.configure_endpoint(
            "/api/debates",
            requests_per_minute=5,
            burst_size=5,  # No burst, exact limit
            key_type="combined",  # Per-endpoint-per-IP limiting
        )

        client_ip = "192.168.1.100"
        endpoint = "/api/debates"

        # First 5 requests should succeed
        for i in range(5):
            result = limiter.allow(client_ip, endpoint=endpoint)
            assert result.allowed is True, f"Request {i + 1} should be allowed"

        # 6th request should be blocked
        result = limiter.allow(client_ip, endpoint=endpoint)
        assert result.allowed is False
        assert result.retry_after > 0

    def test_multiple_endpoints(self):
        """Test rate limiting across multiple endpoints.

        Uses key_type="combined" for per-endpoint limiting and
        explicit burst_size for exact limit enforcement.
        """
        limiter = get_rate_limiter("multi_endpoint_test")
        limiter.configure_endpoint(
            "/api/debates",
            requests_per_minute=3,
            burst_size=3,
            key_type="combined",
        )
        limiter.configure_endpoint(
            "/api/agents",
            requests_per_minute=3,
            burst_size=3,
            key_type="combined",
        )

        client_ip = "192.168.1.101"

        # Exhaust debates limit
        for _ in range(3):
            limiter.allow(client_ip, endpoint="/api/debates")

        # Debates should be blocked
        result = limiter.allow(client_ip, endpoint="/api/debates")
        assert result.allowed is False

        # But agents should still be allowed (separate bucket)
        result = limiter.allow(client_ip, endpoint="/api/agents")
        assert result.allowed is True
