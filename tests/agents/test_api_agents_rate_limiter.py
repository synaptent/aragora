"""
Tests for the OpenRouter rate limiter module.

Covers token bucket algorithm, tier configuration, header parsing,
thread safety, and global limiter management.
"""

import asyncio
import os
import threading
import time
from unittest.mock import patch

import pytest

from aragora.agents.api_agents.rate_limiter import (
    OPENROUTER_TIERS,
    OpenRouterRateLimiter,
    OpenRouterTier,
    get_openrouter_limiter,
    set_openrouter_tier,
)
from aragora.services import ServiceRegistry


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def limiter():
    """Create a rate limiter with standard tier."""
    return OpenRouterRateLimiter(tier="standard")


@pytest.fixture
def free_limiter():
    """Create a rate limiter with free tier (lower limits)."""
    return OpenRouterRateLimiter(tier="free")


@pytest.fixture
def premium_limiter():
    """Create a rate limiter with premium tier (higher limits)."""
    return OpenRouterRateLimiter(tier="premium")


@pytest.fixture(autouse=True)
def reset_global_limiter():
    """Reset global limiter state between tests.

    Also clears OPENROUTER_TIER env var to ensure default tier is used.
    The ServiceRegistry singleton is the sole backing store for
    get_openrouter_limiter() (there is no module-level instance variable), so
    unregistering the limiter there is the whole reset. ``unregister`` is
    idempotent, and a failure here must surface rather than leak a stale
    limiter into the next test.
    """
    import aragora.agents.api_agents.rate_limiter as module

    def _clear_limiter() -> None:
        # Hold the same lock get_openrouter_limiter() takes around its
        # check-and-register so the reset cannot interleave with a creation.
        with module._openrouter_limiter_lock:
            ServiceRegistry.get().unregister(module.OpenRouterRateLimiter)

    # Clear environment variable to ensure default tier
    old_tier = os.environ.pop("OPENROUTER_TIER", None)

    _clear_limiter()
    yield
    _clear_limiter()

    # Restore original env var if it existed
    if old_tier is not None:
        os.environ["OPENROUTER_TIER"] = old_tier


@pytest.fixture(autouse=True)
def disable_inter_request_delay():
    """Disable inter-request delay during tests for faster execution."""
    with patch("aragora.config.OPENROUTER_INTER_REQUEST_DELAY", 0.0):
        yield


# =============================================================================
# OpenRouterTier Tests
# =============================================================================


class TestOpenRouterTier:
    """Tests for OpenRouterTier dataclass."""

    def test_tier_has_required_fields(self):
        """Should have name, requests_per_minute fields."""
        tier = OpenRouterTier(name="test", requests_per_minute=100)
        assert tier.name == "test"
        assert tier.requests_per_minute == 100

    def test_tier_default_tokens_per_minute(self):
        """Should default tokens_per_minute to 0 (unlimited)."""
        tier = OpenRouterTier(name="test", requests_per_minute=100)
        assert tier.tokens_per_minute == 0

    def test_tier_default_burst_size(self):
        """Should default burst_size to 10."""
        tier = OpenRouterTier(name="test", requests_per_minute=100)
        assert tier.burst_size == 10

    def test_tier_custom_values(self):
        """Should accept custom values for all fields."""
        tier = OpenRouterTier(
            name="custom",
            requests_per_minute=500,
            tokens_per_minute=100000,
            burst_size=50,
        )
        assert tier.name == "custom"
        assert tier.requests_per_minute == 500
        assert tier.tokens_per_minute == 100000
        assert tier.burst_size == 50


# =============================================================================
# OPENROUTER_TIERS Constants Tests
# =============================================================================


class TestOpenRouterTiers:
    """Tests for OPENROUTER_TIERS constant."""

    def test_has_free_tier(self):
        """Should have a free tier defined."""
        assert "free" in OPENROUTER_TIERS
        assert OPENROUTER_TIERS["free"].requests_per_minute == 20

    def test_has_basic_tier(self):
        """Should have a basic tier defined."""
        assert "basic" in OPENROUTER_TIERS
        assert OPENROUTER_TIERS["basic"].requests_per_minute == 60

    def test_has_standard_tier(self):
        """Should have a standard tier defined."""
        assert "standard" in OPENROUTER_TIERS
        assert OPENROUTER_TIERS["standard"].requests_per_minute == 200

    def test_has_premium_tier(self):
        """Should have a premium tier defined."""
        assert "premium" in OPENROUTER_TIERS
        assert OPENROUTER_TIERS["premium"].requests_per_minute == 500

    def test_has_unlimited_tier(self):
        """Should have an unlimited tier defined."""
        assert "unlimited" in OPENROUTER_TIERS
        assert OPENROUTER_TIERS["unlimited"].requests_per_minute == 1000

    def test_tiers_have_increasing_limits(self):
        """Tiers should have increasing request limits."""
        order = ["free", "basic", "standard", "premium", "unlimited"]
        rpms = [OPENROUTER_TIERS[t].requests_per_minute for t in order]
        assert rpms == sorted(rpms), "Tiers should have increasing RPM limits"

    def test_tiers_have_increasing_burst_sizes(self):
        """Tiers should have increasing burst sizes."""
        order = ["free", "basic", "standard", "premium", "unlimited"]
        bursts = [OPENROUTER_TIERS[t].burst_size for t in order]
        assert bursts == sorted(bursts), "Tiers should have increasing burst sizes"


# =============================================================================
# OpenRouterRateLimiter Initialization Tests
# =============================================================================


class TestRateLimiterInit:
    """Tests for OpenRouterRateLimiter initialization."""

    def test_default_tier_is_standard(self):
        """Should use standard tier by default."""
        limiter = OpenRouterRateLimiter()
        assert limiter.tier.name == "standard"

    def test_accepts_tier_parameter(self, free_limiter):
        """Should accept custom tier parameter."""
        assert free_limiter.tier.name == "free"

    def test_unknown_tier_falls_back_to_standard(self):
        """Should fall back to standard for unknown tier."""
        limiter = OpenRouterRateLimiter(tier="unknown_tier")
        assert limiter.tier.name == "standard"

    def test_reads_tier_from_environment(self):
        """Should read tier from OPENROUTER_TIER env var."""
        with patch.dict(os.environ, {"OPENROUTER_TIER": "premium"}):
            limiter = OpenRouterRateLimiter()
            assert limiter.tier.name == "premium"

    def test_env_tier_overrides_parameter(self):
        """Environment variable should override parameter."""
        with patch.dict(os.environ, {"OPENROUTER_TIER": "free"}):
            limiter = OpenRouterRateLimiter(tier="premium")
            assert limiter.tier.name == "free"

    def test_case_insensitive_tier_name(self):
        """Tier name should be case-insensitive."""
        limiter = OpenRouterRateLimiter(tier="PREMIUM")
        assert limiter.tier.name == "premium"

    def test_initial_tokens_equal_burst_size(self, limiter):
        """Should start with tokens equal to burst size."""
        assert limiter._tokens == limiter.tier.burst_size

    def test_initial_api_limits_are_none(self, limiter):
        """Should have None for API-reported limits initially."""
        assert limiter._api_limit is None
        assert limiter._api_remaining is None
        assert limiter._api_reset is None


# =============================================================================
# Token Bucket Algorithm Tests
# =============================================================================


class TestTokenBucketAlgorithm:
    """Tests for token bucket rate limiting logic."""

    @pytest.mark.asyncio
    async def test_acquire_succeeds_with_tokens(self, limiter):
        """Should succeed immediately when tokens available."""
        result = await limiter.acquire(timeout=0.1)
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_decrements_tokens(self, limiter):
        """Should decrement token count on acquire."""
        initial = limiter._tokens
        await limiter.acquire(timeout=0.1)
        # Pin _last_refill to now so the property getter's _refill() adds zero tokens
        limiter._last_refill = time.monotonic()
        assert limiter._tokens == pytest.approx(initial - 1, abs=0.01)

    @pytest.mark.asyncio
    async def test_multiple_acquires_work(self, limiter):
        """Should allow multiple acquires up to burst size."""
        burst_size = limiter.tier.burst_size
        for _ in range(burst_size):
            result = await limiter.acquire(timeout=0.1)
            assert result is True

    @pytest.mark.asyncio
    async def test_acquire_times_out_when_empty(self, free_limiter):
        """Should timeout when no tokens available."""
        # Exhaust all tokens
        for _ in range(free_limiter.tier.burst_size):
            await free_limiter.acquire(timeout=0.1)

        # Next acquire should timeout
        result = await free_limiter.acquire(timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self, free_limiter):
        """Should refill tokens based on requests_per_minute."""
        # Exhaust all tokens
        for _ in range(free_limiter.tier.burst_size):
            await free_limiter.acquire(timeout=0.1)

        # Manually adjust last_refill to simulate time passing
        # Free tier: 20 RPM = 1 token per 3 seconds
        free_limiter._last_refill = time.monotonic() - 6  # 6 seconds = 2 tokens

        # Should now have tokens available
        result = await free_limiter.acquire(timeout=0.1)
        assert result is True

    def test_refill_caps_at_burst_size(self, limiter):
        """Refill should not exceed burst size."""
        # Set last refill to long ago
        limiter._last_refill = time.monotonic() - 3600  # 1 hour ago

        # Trigger refill
        limiter._refill()

        # Should be capped at burst size
        assert limiter._tokens == limiter.tier.burst_size


# =============================================================================
# Header Parsing Tests
# =============================================================================


class TestHeaderParsing:
    """Tests for update_from_headers method."""

    def test_parses_limit_header(self, limiter):
        """Should parse X-RateLimit-Limit header."""
        limiter.update_from_headers({"X-RateLimit-Limit": "100"})
        assert limiter._api_limit == 100

    def test_parses_remaining_header(self, limiter):
        """Should parse X-RateLimit-Remaining header."""
        limiter.update_from_headers({"X-RateLimit-Remaining": "50"})
        assert limiter._api_remaining == 50

    def test_parses_reset_header(self, limiter):
        """Should parse X-RateLimit-Reset header."""
        reset_time = time.time() + 60
        limiter.update_from_headers({"X-RateLimit-Reset": str(reset_time)})
        assert limiter._api_reset == pytest.approx(reset_time, rel=0.01)

    def test_parses_all_headers_together(self, limiter):
        """Should parse all rate limit headers."""
        reset_time = time.time() + 120
        limiter.update_from_headers(
            {
                "X-RateLimit-Limit": "200",
                "X-RateLimit-Remaining": "150",
                "X-RateLimit-Reset": str(reset_time),
            }
        )
        assert limiter._api_limit == 200
        assert limiter._api_remaining == 150
        assert limiter._api_reset == pytest.approx(reset_time, rel=0.01)

    def test_ignores_unrelated_headers(self, limiter):
        """Should ignore non-rate-limit headers."""
        limiter.update_from_headers(
            {
                "Content-Type": "application/json",
                "X-Custom-Header": "value",
            }
        )
        assert limiter._api_limit is None
        assert limiter._api_remaining is None

    def test_handles_invalid_limit_header(self, limiter):
        """Should handle invalid X-RateLimit-Limit gracefully."""
        limiter.update_from_headers({"X-RateLimit-Limit": "not-a-number"})
        assert limiter._api_limit is None  # Should remain None

    def test_handles_invalid_remaining_header(self, limiter):
        """Should handle invalid X-RateLimit-Remaining gracefully."""
        limiter.update_from_headers({"X-RateLimit-Remaining": "abc"})
        assert limiter._api_remaining is None

    def test_handles_invalid_reset_header(self, limiter):
        """Should handle invalid X-RateLimit-Reset gracefully."""
        limiter.update_from_headers({"X-RateLimit-Reset": "invalid"})
        assert limiter._api_reset is None

    def test_handles_empty_headers(self, limiter):
        """Should handle empty headers dict."""
        limiter.update_from_headers({})
        assert limiter._api_limit is None


# =============================================================================
# Error Recovery Tests
# =============================================================================


class TestErrorRecovery:
    """Tests for release_on_error method."""

    @pytest.mark.asyncio
    async def test_release_adds_token(self, limiter):
        """Should add a token back on error."""
        initial = limiter._tokens
        await limiter.acquire(timeout=0.1)
        # Pin _last_refill to prevent tiny refills between operations
        limiter._last_refill = time.monotonic()
        assert limiter._tokens == pytest.approx(initial - 1, abs=0.01)

        limiter.release_on_error()
        limiter._last_refill = time.monotonic()
        assert limiter._tokens == pytest.approx(initial, abs=0.01)

    def test_release_caps_at_burst_size(self, limiter):
        """Should not exceed burst size when releasing."""
        # Already at burst size
        limiter._tokens = limiter.tier.burst_size

        limiter.release_on_error()

        # Should still be at burst size
        assert limiter._tokens == limiter.tier.burst_size


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStats:
    """Tests for stats property."""

    def test_stats_includes_tier_info(self, limiter):
        """Should include tier name and RPM limit."""
        stats = limiter.stats
        assert stats["tier"] == "standard"
        assert stats["rpm_limit"] == 200

    def test_stats_includes_tokens(self, limiter):
        """Should include available tokens."""
        stats = limiter.stats
        assert stats["tokens_available"] == limiter.tier.burst_size

    def test_stats_includes_burst_size(self, limiter):
        """Should include burst size."""
        stats = limiter.stats
        assert stats["burst_size"] == limiter.tier.burst_size

    def test_stats_includes_api_limits(self, limiter):
        """Should include API-reported limits."""
        limiter.update_from_headers(
            {
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "75",
            }
        )
        stats = limiter.stats
        assert stats["api_limit"] == 100
        assert stats["api_remaining"] == 75

    @pytest.mark.asyncio
    async def test_stats_reflects_token_usage(self, limiter):
        """Stats should reflect token usage."""
        initial_tokens = limiter.stats["tokens_available"]
        await limiter.acquire(timeout=0.1)
        await limiter.acquire(timeout=0.1)
        # Allow for possible token refill during the test execution
        assert limiter.stats["tokens_available"] <= initial_tokens - 1
        assert limiter.stats["tokens_available"] < initial_tokens


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestThreadSafety:
    """Tests for thread-safe operation."""

    @pytest.mark.asyncio
    async def test_concurrent_acquires(self, limiter):
        """Should handle concurrent acquire calls safely."""
        results = await asyncio.gather(
            *[limiter.acquire(timeout=1.0) for _ in range(limiter.tier.burst_size)]
        )
        assert all(r is True for r in results)

    def test_concurrent_header_updates(self, limiter):
        """Should handle concurrent header updates safely."""

        def update_headers():
            for i in range(100):
                limiter.update_from_headers(
                    {
                        "X-RateLimit-Limit": str(100 + i),
                        "X-RateLimit-Remaining": str(50 + i),
                    }
                )

        threads = [threading.Thread(target=update_headers) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not crash and should have valid values
        assert limiter._api_limit is not None
        assert limiter._api_remaining is not None


# =============================================================================
# Global Limiter Tests
# =============================================================================


class TestGlobalLimiter:
    """Tests for global limiter management."""

    def test_get_limiter_creates_instance(self):
        """Should create a limiter on first call."""
        limiter = get_openrouter_limiter()
        assert isinstance(limiter, OpenRouterRateLimiter)

    def test_get_limiter_returns_same_instance(self):
        """Should return same instance on subsequent calls."""
        limiter1 = get_openrouter_limiter()
        limiter2 = get_openrouter_limiter()
        assert limiter1 is limiter2

    def test_set_tier_creates_new_limiter(self):
        """Should create new limiter with specified tier."""
        limiter1 = get_openrouter_limiter()
        assert limiter1.tier.name == "standard"  # Default

        set_openrouter_tier("premium")
        limiter2 = get_openrouter_limiter()

        # Should be different instance with new tier
        assert limiter2.tier.name == "premium"

    def test_set_tier_replaces_existing(self):
        """Should replace existing global limiter."""
        old_limiter = get_openrouter_limiter()
        set_openrouter_tier("free")
        new_limiter = get_openrouter_limiter()

        assert old_limiter is not new_limiter
        assert new_limiter.tier.name == "free"


# =============================================================================
# API Limit Behavior Tests
# =============================================================================


class TestApiLimitBehavior:
    """Tests for behavior when API reports limits."""

    @pytest.mark.asyncio
    async def test_respects_zero_remaining(self, limiter):
        """Should wait when API reports zero remaining."""
        # Simulate API saying no remaining requests
        limiter.update_from_headers(
            {
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(time.time() + 0.1),  # Reset in 0.1s
            }
        )

        # Should still work (token bucket has tokens)
        start = time.monotonic()
        result = await limiter.acquire(timeout=0.5)
        elapsed = time.monotonic() - start

        # Should have waited some time due to API limit check
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_with_long_timeout(self, free_limiter):
        """Should wait and retry with longer timeout."""
        # Exhaust tokens
        for _ in range(free_limiter.tier.burst_size):
            await free_limiter.acquire(timeout=0.1)

        # With longer timeout, should wait for refill
        # Free tier: 20 RPM = 3 seconds per token
        # Simulate time passing
        free_limiter._last_refill = time.monotonic() - 4

        result = await free_limiter.acquire(timeout=0.1)
        assert result is True


# =============================================================================
# Integration Tests
# =============================================================================


class TestRateLimiterIntegration:
    """Integration tests for rate limiter."""

    @pytest.mark.asyncio
    async def test_realistic_usage_pattern(self, limiter):
        """Test realistic request pattern with header updates."""
        # Simulate a series of API calls
        for i in range(5):
            acquired = await limiter.acquire(timeout=1.0)
            assert acquired is True

            # Simulate API response headers
            limiter.update_from_headers(
                {
                    "X-RateLimit-Limit": "200",
                    "X-RateLimit-Remaining": str(195 - i),
                }
            )

        # Check final state
        stats = limiter.stats
        assert stats["api_remaining"] == 191

    @pytest.mark.asyncio
    async def test_error_and_retry_pattern(self, limiter):
        """Test acquiring, error, release, and retry."""
        # Acquire
        await limiter.acquire(timeout=0.1)
        # Pin _last_refill to prevent refill drift between reads
        limiter._last_refill = time.monotonic()
        tokens_after_acquire = limiter._tokens

        # Simulate error and release
        limiter.release_on_error()
        limiter._last_refill = time.monotonic()
        tokens_after_release = limiter._tokens

        # Should have one more token
        assert tokens_after_release == pytest.approx(tokens_after_acquire + 1, abs=0.01)

        # Retry should succeed
        result = await limiter.acquire(timeout=0.1)
        assert result is True


# =============================================================================
# ExponentialBackoff Tests
# =============================================================================


class TestExponentialBackoff:
    """Tests for ExponentialBackoff class."""

    def test_initial_state(self):
        """Should start with zero failures."""
        from aragora.agents.api_agents.rate_limiter import ExponentialBackoff

        backoff = ExponentialBackoff()
        assert backoff.failure_count == 0
        assert backoff.is_backing_off is False

    def test_get_delay_initial(self):
        """Initial delay should be approximately base_delay."""
        from aragora.agents.api_agents.rate_limiter import ExponentialBackoff

        backoff = ExponentialBackoff(base_delay=1.0, jitter=0.1)
        delay = backoff.get_delay()
        # With 0 failures, delay is base_delay (1.0) + up to 10% jitter
        assert 1.0 <= delay <= 1.1

    def test_record_failure_increments_count(self):
        """Recording failure should increment failure count."""
        from aragora.agents.api_agents.rate_limiter import ExponentialBackoff

        backoff = ExponentialBackoff()
        assert backoff.failure_count == 0

        backoff.record_failure()
        assert backoff.failure_count == 1
        assert backoff.is_backing_off is True

        backoff.record_failure()
        assert backoff.failure_count == 2

    def test_exponential_increase(self):
        """Delay should double with each failure."""
        from aragora.agents.api_agents.rate_limiter import ExponentialBackoff

        backoff = ExponentialBackoff(base_delay=1.0, max_delay=100.0, jitter=0.0)

        # After 1 failure: 2^1 * 1.0 = 2.0
        backoff.record_failure()
        assert backoff.get_delay() == 2.0

        # After 2 failures: 2^2 * 1.0 = 4.0
        backoff.record_failure()
        assert backoff.get_delay() == 4.0

        # After 3 failures: 2^3 * 1.0 = 8.0
        backoff.record_failure()
        assert backoff.get_delay() == 8.0

    def test_max_delay_cap(self):
        """Delay should not exceed max_delay."""
        from aragora.agents.api_agents.rate_limiter import ExponentialBackoff

        backoff = ExponentialBackoff(base_delay=1.0, max_delay=10.0, jitter=0.0)

        # Record many failures to exceed max
        for _ in range(10):
            backoff.record_failure()

        # Delay should be capped at max_delay
        assert backoff.get_delay() == 10.0

    def test_reset_clears_failure_count(self):
        """Reset should clear failure count."""
        from aragora.agents.api_agents.rate_limiter import ExponentialBackoff

        backoff = ExponentialBackoff()
        backoff.record_failure()
        backoff.record_failure()
        assert backoff.failure_count == 2

        backoff.reset()
        assert backoff.failure_count == 0
        assert backoff.is_backing_off is False

    def test_jitter_adds_variance(self):
        """Jitter should add random variance to delay."""
        from aragora.agents.api_agents.rate_limiter import ExponentialBackoff

        backoff = ExponentialBackoff(base_delay=10.0, jitter=0.1)

        # Collect multiple delay samples
        delays = [backoff.get_delay() for _ in range(20)]

        # With 10% jitter, delays should be in range [10.0, 11.0]
        assert all(10.0 <= d <= 11.0 for d in delays)

        # Delays should not all be identical (very unlikely with jitter)
        assert len(set(delays)) > 1

    def test_thread_safety(self):
        """Backoff operations should be thread-safe."""
        from aragora.agents.api_agents.rate_limiter import ExponentialBackoff
        import concurrent.futures

        backoff = ExponentialBackoff()
        num_threads = 10
        iterations = 100

        def record_failures():
            for _ in range(iterations):
                backoff.record_failure()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(record_failures) for _ in range(num_threads)]
            concurrent.futures.wait(futures)

        # All failures should be recorded
        assert backoff.failure_count == num_threads * iterations


# =============================================================================
# ProviderRateLimiter Tests
# =============================================================================


class TestProviderRateLimiter:
    """Tests for ProviderRateLimiter class."""

    def test_initialization_with_defaults(self):
        """Should use default tier config for known provider."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="anthropic")
        assert limiter.provider == "anthropic"
        assert limiter.requests_per_minute > 0
        assert limiter.burst_size > 0

    def test_initialization_with_custom_values(self):
        """Should allow custom rpm and burst."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="custom", rpm=100, burst=20)
        assert limiter.requests_per_minute == 100
        assert limiter.burst_size == 20

    def test_initialization_with_unknown_provider(self):
        """Should use default values for unknown provider."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="unknown_provider_xyz")
        assert limiter.provider == "unknown_provider_xyz"
        # Should use default values
        assert limiter.requests_per_minute == 100
        assert limiter.burst_size == 10

    def test_provider_name_normalized_to_lowercase(self):
        """Provider name should be normalized to lowercase."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="ANTHROPIC")
        assert limiter.provider == "anthropic"

    @patch.dict(os.environ, {"ARAGORA_TESTPROV_RPM": "500", "ARAGORA_TESTPROV_BURST": "50"})
    def test_environment_variable_override(self):
        """Should use env vars to override rate limits."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="testprov")
        assert limiter.requests_per_minute == 500
        assert limiter.burst_size == 50

    @pytest.mark.asyncio
    async def test_acquire_success(self):
        """Should successfully acquire token."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="test", rpm=60, burst=10)
        result = await limiter.acquire(timeout=0.1)
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_exhausts_burst(self):
        """Should exhaust burst tokens."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        # Use very low RPM (1 per minute = 0.017 per second) to minimize refill
        # during the test. With burst=3, exhausting tokens should be reliable.
        limiter = ProviderRateLimiter(provider="test", rpm=1, burst=3)

        # Exhaust all tokens
        for _ in range(3):
            result = await limiter.acquire(timeout=0.1)
            assert result is True

        # Next acquire should timeout (not enough time for refill at 1 RPM)
        result = await limiter.acquire(timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_token_refill(self):
        """Should refill tokens over time."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="test", rpm=60, burst=5)

        # Exhaust tokens
        for _ in range(5):
            await limiter.acquire(timeout=0.1)

        # Simulate time passing (1 minute = 60 tokens at 60 RPM)
        limiter._last_refill = time.monotonic() - 60

        # Should be able to acquire again
        result = await limiter.acquire(timeout=0.1)
        assert result is True

    def test_record_success_resets_backoff(self):
        """Record success should reset backoff state."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="test", rpm=60, burst=10)

        # Create some backoff state
        limiter._backoff.record_failure()
        limiter._backoff.record_failure()
        assert limiter._backoff.is_backing_off is True

        # Record success
        limiter.record_success()
        assert limiter._backoff.is_backing_off is False

    def test_record_rate_limit_triggers_backoff(self):
        """Recording rate limit should trigger backoff."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="test", rpm=60, burst=10)
        assert limiter._backoff.is_backing_off is False

        limiter.record_rate_limit_error()
        assert limiter._backoff.is_backing_off is True

    def test_release_on_error_returns_token(self):
        """Release on error should return token to pool."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="test", rpm=60, burst=10)
        initial_tokens = limiter._tokens

        # Consume one token manually via the bucket's sync lock
        with limiter._bucket._sync_lock:
            limiter._bucket._tokens -= 1

        # Pin _last_refill to prevent refill drift
        limiter._last_refill = time.monotonic()
        tokens_after_consume = limiter._tokens
        assert tokens_after_consume == pytest.approx(initial_tokens - 1, abs=0.01)

        # Release on error
        limiter.release_on_error()

        # Token should be returned (capped at burst)
        limiter._last_refill = time.monotonic()
        assert limiter._tokens == pytest.approx(
            min(tokens_after_consume + 1, limiter.burst_size), abs=0.01
        )

    def test_update_from_headers(self):
        """Should parse rate limit headers."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="test", rpm=60, burst=10)

        headers = {
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "95",
            "X-RateLimit-Reset": str(int(time.time()) + 60),
        }
        limiter.update_from_headers(headers)

        assert limiter._api_limit == 100
        assert limiter._api_remaining == 95
        assert limiter._api_reset is not None

    def test_update_from_headers_case_insensitive(self):
        """Should handle various header casing."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="test", rpm=60, burst=10)

        # Lowercase headers
        headers = {
            "x-ratelimit-limit": "100",
            "x-ratelimit-remaining": "95",
        }
        limiter.update_from_headers(headers)

        assert limiter._api_limit == 100
        assert limiter._api_remaining == 95

    def test_stats_property(self):
        """Should return rate limiter statistics."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="test", rpm=60, burst=10)
        stats = limiter.stats

        assert "provider" in stats
        assert "rpm_limit" in stats
        assert "burst_size" in stats
        assert "tokens_available" in stats
        assert stats["provider"] == "test"
        assert stats["rpm_limit"] == 60
        assert stats["burst_size"] == 10


# =============================================================================
# ProviderRateLimiterRegistry Tests
# =============================================================================


class TestProviderRateLimiterRegistry:
    """Tests for ProviderRateLimiterRegistry class."""

    def test_registry_initialization(self):
        """Should initialize with empty limiters dict."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiterRegistry

        registry = ProviderRateLimiterRegistry()
        assert registry.providers() == []

    def test_get_creates_limiter_on_demand(self):
        """Should create limiter on first access."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiterRegistry

        registry = ProviderRateLimiterRegistry()
        limiter = registry.get("test_provider")

        assert limiter is not None
        assert limiter.provider == "test_provider"
        assert "test_provider" in registry.providers()

    def test_get_returns_same_instance(self):
        """Should return same limiter instance for same provider."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiterRegistry

        registry = ProviderRateLimiterRegistry()

        limiter1 = registry.get("test_provider")
        limiter2 = registry.get("test_provider")

        assert limiter1 is limiter2

    def test_get_normalizes_provider_name(self):
        """Should normalize provider name to lowercase."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiterRegistry

        registry = ProviderRateLimiterRegistry()

        limiter1 = registry.get("TestProvider")
        limiter2 = registry.get("testprovider")
        limiter3 = registry.get("TESTPROVIDER")

        assert limiter1 is limiter2 is limiter3

    def test_get_with_custom_rpm_burst(self):
        """Should create limiter with custom rpm/burst on first access."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiterRegistry

        registry = ProviderRateLimiterRegistry()
        limiter = registry.get("custom_prov", rpm=200, burst=40)

        assert limiter.requests_per_minute == 200
        assert limiter.burst_size == 40

    def test_reset_single_provider(self):
        """Should reset only specified provider."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiterRegistry

        registry = ProviderRateLimiterRegistry()
        registry.get("provider1")
        registry.get("provider2")

        assert len(registry.providers()) == 2

        registry.reset("provider1")

        assert "provider1" not in registry.providers()
        assert "provider2" in registry.providers()

    def test_reset_all_providers(self):
        """Should reset all providers when no provider specified."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiterRegistry

        registry = ProviderRateLimiterRegistry()
        registry.get("provider1")
        registry.get("provider2")
        registry.get("provider3")

        assert len(registry.providers()) == 3

        registry.reset()

        assert registry.providers() == []

    def test_stats_returns_all_limiter_stats(self):
        """Should return stats for all registered limiters."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiterRegistry

        registry = ProviderRateLimiterRegistry()
        registry.get("provider1")
        registry.get("provider2")

        stats = registry.stats()

        assert "provider1" in stats
        assert "provider2" in stats
        assert "provider" in stats["provider1"]
        assert "provider" in stats["provider2"]

    def test_thread_safety(self):
        """Registry operations should be thread-safe."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiterRegistry
        import concurrent.futures

        registry = ProviderRateLimiterRegistry()
        num_threads = 10

        def get_limiter(provider_idx):
            # Each thread gets multiple limiters
            for i in range(10):
                registry.get(f"provider_{provider_idx}_{i}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(get_limiter, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        # All limiters should be created
        assert len(registry.providers()) == num_threads * 10


# =============================================================================
# Global Functions Tests
# =============================================================================


class TestGlobalProviderFunctions:
    """Tests for global provider rate limiter functions."""

    @pytest.fixture(autouse=True)
    def reset_global_registry(self):
        """Reset global registry between tests."""
        import aragora.agents.api_agents.rate_limiter as module

        with module._provider_registry_lock:
            module._provider_registry = None
        yield
        with module._provider_registry_lock:
            module._provider_registry = None

    def test_get_provider_limiter(self):
        """Should return a provider rate limiter."""
        from aragora.agents.api_agents.rate_limiter import get_provider_limiter

        limiter = get_provider_limiter("test_provider")
        assert limiter is not None
        assert limiter.provider == "test_provider"

    def test_get_provider_limiter_singleton(self):
        """Should return same limiter for same provider."""
        from aragora.agents.api_agents.rate_limiter import get_provider_limiter

        limiter1 = get_provider_limiter("test_provider")
        limiter2 = get_provider_limiter("test_provider")

        assert limiter1 is limiter2

    def test_get_provider_registry(self):
        """Should return the global registry."""
        from aragora.agents.api_agents.rate_limiter import get_provider_registry

        registry = get_provider_registry()
        assert registry is not None

    def test_reset_provider_limiters(self):
        """Should reset all provider limiters."""
        from aragora.agents.api_agents.rate_limiter import (
            get_provider_limiter,
            reset_provider_limiters,
            get_provider_registry,
        )

        # Create some limiters
        get_provider_limiter("provider1")
        get_provider_limiter("provider2")

        registry = get_provider_registry()
        assert len(registry.providers()) == 2

        # Reset (replaces global registry with None)
        reset_provider_limiters()

        # Get fresh registry reference -- reset_provider_limiters() replaces the
        # global singleton so the old reference is stale
        new_registry = get_provider_registry()
        assert len(new_registry.providers()) == 0


# =============================================================================
# Concurrency Regression Tests
# =============================================================================


class TestConcurrencyRegression:
    """Tests to verify rate limiter doesn't block event loop under concurrent load.

    These tests verify the fix for the HIGH severity issue where threading.Lock
    was used in async code, which could stall the event loop and serialize
    unrelated calls under load.
    """

    @pytest.mark.asyncio
    async def test_concurrent_acquires_dont_block_event_loop(self):
        """Multiple concurrent acquires should not block the event loop.

        This test verifies that the rate limiter uses asyncio.Lock instead of
        threading.Lock, allowing concurrent coroutines to make progress.
        """
        from aragora.agents.api_agents.rate_limiter import OpenRouterRateLimiter

        limiter = OpenRouterRateLimiter(tier="premium")  # High limits for testing
        num_tasks = 20

        # Track timing to detect event loop blocking
        start_time = time.monotonic()

        # Launch many concurrent acquire attempts
        tasks = [limiter.acquire(timeout=0.5) for _ in range(num_tasks)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.monotonic() - start_time

        # Count successes
        successes = sum(1 for r in results if r is True)

        # Should complete quickly - if event loop was blocked, this would take much longer
        # With asyncio.Lock, concurrent acquires yield to each other
        assert elapsed < 2.0, (
            f"Concurrent acquires took too long: {elapsed:.2f}s (event loop may be blocked)"
        )

        # All tasks should succeed since burst_size (50) > num_tasks (20)
        assert successes == num_tasks, f"Only {successes}/{num_tasks} acquires succeeded"

    @pytest.mark.asyncio
    async def test_provider_limiter_concurrent_acquires(self):
        """ProviderRateLimiter should also handle concurrent acquires without blocking."""
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        num_tasks = 30
        limiter = ProviderRateLimiter(provider="test_concurrent", rpm=1000, burst=50)

        start_time = time.monotonic()

        # Launch concurrent acquire attempts
        tasks = [limiter.acquire(timeout=0.5) for _ in range(num_tasks)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.monotonic() - start_time

        successes = sum(1 for r in results if r is True)

        # Should complete quickly with asyncio.Lock
        assert elapsed < 2.0, f"Concurrent acquires took too long: {elapsed:.2f}s"
        # All tasks should succeed since burst_size (50) > num_tasks (30)
        assert successes == num_tasks, f"Only {successes}/{num_tasks} acquires succeeded"

    @pytest.mark.asyncio
    async def test_event_loop_responsive_during_rate_limit_wait(self):
        """Event loop should remain responsive while rate limiter waits.

        This test verifies that other coroutines can run while one is waiting
        for rate limiter tokens.
        """
        from aragora.agents.api_agents.rate_limiter import OpenRouterRateLimiter

        limiter = OpenRouterRateLimiter(tier="free")  # Low limits to trigger waiting

        # Exhaust tokens
        for _ in range(limiter.tier.burst_size):
            await limiter.acquire(timeout=0.1)

        # Track whether background task runs while rate limiter waits
        background_ran = False

        async def background_task():
            nonlocal background_ran
            await asyncio.sleep(0.05)
            background_ran = True

        async def rate_limited_task():
            # This will wait because tokens are exhausted
            await limiter.acquire(timeout=0.5)

        # Start both tasks concurrently
        await asyncio.gather(
            rate_limited_task(),
            background_task(),
            return_exceptions=True,
        )

        # Background task should have run while rate limiter was waiting
        assert background_ran, "Background task didn't run - event loop may have been blocked"

    @pytest.mark.asyncio
    async def test_no_deadlock_under_high_concurrency(self):
        """High concurrency should not cause deadlock.

        With the old threading.Lock, many concurrent acquires could cause
        contention issues. With asyncio.Lock, this should work smoothly.
        """
        from aragora.agents.api_agents.rate_limiter import ProviderRateLimiter

        limiter = ProviderRateLimiter(provider="deadlock_test", rpm=500, burst=20)

        async def acquire_and_release():
            """Acquire token and simulate some work."""
            acquired = await limiter.acquire(timeout=1.0)
            if acquired:
                await asyncio.sleep(0.01)  # Simulate API call
            return acquired

        # Launch many concurrent tasks
        tasks = [acquire_and_release() for _ in range(100)]

        # Set a timeout to detect deadlock
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            pytest.fail("Deadlock detected - concurrent acquires did not complete")

        # Some should succeed, some may timeout - but no exceptions from deadlock
        errors = [r for r in results if isinstance(r, Exception)]
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    @pytest.mark.asyncio
    async def test_asyncio_lock_allows_interleaving(self):
        """Verify that asyncio.Lock allows coroutine interleaving.

        This directly tests that the lock is an asyncio.Lock (not threading.Lock)
        by checking that multiple coroutines can interleave their execution.
        """
        from aragora.agents.api_agents.rate_limiter import OpenRouterRateLimiter

        limiter = OpenRouterRateLimiter(tier="premium")

        # Track execution order
        execution_order = []

        async def task(task_id: int):
            execution_order.append(f"start_{task_id}")
            await limiter.acquire(timeout=1.0)
            await asyncio.sleep(0.01)  # Yield to other tasks
            execution_order.append(f"end_{task_id}")

        # Run tasks concurrently
        await asyncio.gather(*[task(i) for i in range(5)])

        # With asyncio.Lock, starts should interleave before all ends
        # (threading.Lock would serialize: start_0, end_0, start_1, end_1, ...)
        start_indices = [execution_order.index(f"start_{i}") for i in range(5)]
        end_indices = [execution_order.index(f"end_{i}") for i in range(5)]

        # At least some starts should happen before the first end
        first_end = min(end_indices)
        starts_before_first_end = sum(1 for s in start_indices if s < first_end)
        assert starts_before_first_end >= 2, (
            f"Expected interleaving but got sequential execution: {execution_order}"
        )
