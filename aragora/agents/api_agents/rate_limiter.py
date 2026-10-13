"""
API provider rate limiting infrastructure.

Provides token bucket rate limiting for API calls with:
- Per-provider rate limiters (Anthropic, OpenAI, OpenRouter, etc.)
- Configurable tiers with different RPM limits
- Thread-safe operation with per-provider locks (no global lock contention)
- Exponential backoff for rate limit recovery
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass

from aragora.shared.rate_limiting import ExponentialBackoff

logger = logging.getLogger(__name__)


@dataclass
class OpenRouterTier:
    """Rate limit configuration for an OpenRouter pricing tier."""

    name: str
    requests_per_minute: int
    tokens_per_minute: int = 0  # 0 = unlimited
    burst_size: int = 10  # Allow short bursts


# OpenRouter tier configurations (based on their pricing)
OPENROUTER_TIERS = {
    "free": OpenRouterTier(name="free", requests_per_minute=20, burst_size=5),
    "basic": OpenRouterTier(name="basic", requests_per_minute=60, burst_size=15),
    "standard": OpenRouterTier(name="standard", requests_per_minute=200, burst_size=30),
    "premium": OpenRouterTier(name="premium", requests_per_minute=500, burst_size=50),
    "unlimited": OpenRouterTier(name="unlimited", requests_per_minute=1000, burst_size=100),
}


@dataclass
class ProviderTier:
    """Rate limit configuration for an API provider."""

    name: str
    requests_per_minute: int
    tokens_per_minute: int = 0  # 0 = unlimited
    burst_size: int = 10  # Allow short bursts


# Provider-specific default tiers (based on typical API limits)
# These can be overridden via environment variables
PROVIDER_DEFAULT_TIERS: dict[str, ProviderTier] = {
    # Anthropic: 1000 RPM for paid, 60 for free tier
    "anthropic": ProviderTier(name="anthropic", requests_per_minute=1000, burst_size=50),
    # OpenAI: Varies by tier, using reasonable default
    "openai": ProviderTier(name="openai", requests_per_minute=500, burst_size=30),
    # Mistral: 5 requests/sec = 300 RPM
    "mistral": ProviderTier(name="mistral", requests_per_minute=300, burst_size=20),
    # Gemini: 60 RPM free, 1000 RPM paid
    "gemini": ProviderTier(name="gemini", requests_per_minute=60, burst_size=15),
    # Grok (xAI): Similar to Anthropic
    "grok": ProviderTier(name="grok", requests_per_minute=500, burst_size=30),
    # OpenRouter: Use standard tier as default
    "openrouter": ProviderTier(name="openrouter", requests_per_minute=200, burst_size=30),
    # Ollama (local): Higher limits since it's local
    "ollama": ProviderTier(name="ollama", requests_per_minute=1000, burst_size=100),
    # LM Studio (local): Higher limits since it's local
    "lm_studio": ProviderTier(name="lm_studio", requests_per_minute=1000, burst_size=100),
}


class OpenRouterRateLimiter:
    """Rate limiter for OpenRouter API calls.

    Uses the shared TokenBucket for core rate limiting with OpenRouter-specific
    tiers and exponential backoff for quota error recovery.

    Thread-safe for use across multiple agent instances.
    Uses asyncio.Lock for async methods to avoid blocking the event loop.
    """

    def __init__(self, tier: str = "standard"):
        """
        Initialize rate limiter with specified tier.

        Tier can be set via OPENROUTER_TIER environment variable.
        """
        from aragora.shared.rate_limiting import TokenBucket

        tier_name = os.environ.get("OPENROUTER_TIER", tier).lower()
        self.tier = OPENROUTER_TIERS.get(tier_name, OPENROUTER_TIERS["standard"])

        # Delegate core token bucket logic to shared implementation
        self._bucket = TokenBucket(
            rate_per_minute=self.tier.requests_per_minute,
            burst=self.tier.burst_size,
            name=f"openrouter:{self.tier.name}",
        )

        # Exponential backoff for quota exhaustion recovery
        self._backoff = ExponentialBackoff(base_delay=2.0, max_delay=60.0, jitter=0.15)

        logger.debug(
            "OpenRouter rate limiter initialized: tier=%s, rpm=%s",
            self.tier.name,
            self.tier.requests_per_minute,
        )

    async def acquire(self, timeout: float = 30.0) -> bool:
        """
        Acquire permission to make an API request.

        Blocks until a token is available or timeout is reached.
        Uses exponential backoff when recovering from rate limit errors.
        Returns True if acquired, False if timed out.

        Uses asyncio.Lock internally so waiting coroutines yield to the
        event loop instead of blocking the entire thread.
        """
        start_time = time.monotonic()
        deadline = start_time + timeout

        # If in backoff state, wait before trying
        if self._backoff.is_backing_off:
            backoff_delay = self._backoff.get_delay()
            remaining = deadline - time.monotonic()
            if backoff_delay > remaining:
                logger.debug(f"Backoff delay {backoff_delay:.1f}s exceeds timeout {remaining:.1f}s")
                return False
            logger.debug(f"rate_limiter_backoff_wait delay={backoff_delay:.1f}s")
            await asyncio.sleep(backoff_delay)

        # Adjust timeout for time spent in backoff
        remaining_timeout = max(0.0, deadline - time.monotonic())

        # Delegate to shared token bucket
        acquired = await self._bucket.acquire_async(timeout=remaining_timeout)

        if not acquired:
            logger.debug("OpenRouter rate limit timeout")
            return False

        # Stagger delay to allow parallel token acquisition
        from aragora.config import OPENROUTER_INTER_REQUEST_DELAY

        if OPENROUTER_INTER_REQUEST_DELAY > 0:
            await asyncio.sleep(OPENROUTER_INTER_REQUEST_DELAY)

        return True

    def update_from_headers(self, headers: dict) -> None:
        """Update rate limit state from API response headers.

        OpenRouter returns standard rate limit headers:
        - X-RateLimit-Limit: Total requests allowed
        - X-RateLimit-Remaining: Requests remaining
        - X-RateLimit-Reset: Unix timestamp when limit resets

        Delegates to shared TokenBucket for header parsing.
        """
        self._bucket.update_from_headers(headers)

    def release_on_error(self) -> None:
        """Release a token back on request error (optional, for retries)."""
        self._bucket.release()

    def record_rate_limit_error(self, status_code: int = 429) -> float:
        """Record a rate limit error (429/403) and return backoff delay.

        Call this when the API returns a rate limit error. The limiter will
        enter backoff state and subsequent acquire() calls will wait accordingly.

        Args:
            status_code: HTTP status code (429=rate limited, 403=quota exceeded)

        Returns:
            The recommended delay before retrying (in seconds)
        """
        logger.debug("rate_limit_error status=%s", status_code)
        delay = self._backoff.record_failure()
        # Also release the token back since request failed
        self.release_on_error()
        return delay

    def record_success(self) -> None:
        """Record a successful API request.

        Call this after a request succeeds to reset backoff state.
        This allows normal rate limiting to resume after recovery.
        """
        self._backoff.reset()

    @property
    def is_backing_off(self) -> bool:
        """Check if currently in exponential backoff due to rate limit errors."""
        return self._backoff.is_backing_off

    @property
    def stats(self) -> dict:
        """Get current rate limiter statistics."""
        bucket_stats = self._bucket.stats
        return {
            "tier": self.tier.name,
            "rpm_limit": self.tier.requests_per_minute,
            "tokens_available": int(bucket_stats.get("tokens_available", 0)),
            "burst_size": self.tier.burst_size,
            "api_limit": bucket_stats.get("api_limit"),
            "api_remaining": bucket_stats.get("api_remaining"),
            "backoff_failures": self._backoff.failure_count,
            "is_backing_off": self._backoff.is_backing_off,
            "acquired": bucket_stats.get("acquired", 0),
            "rejected": bucket_stats.get("rejected", 0),
        }

    def request(self, timeout: float = 30.0) -> RateLimitContext:
        """Context manager for rate-limited API requests.

        Provides cleaner async with syntax for acquiring and optionally
        releasing rate limit tokens.

        Usage:
            async with limiter.request() as acquired:
                if acquired:
                    response = await make_api_call()
                else:
                    raise TimeoutError("Rate limit timeout")

            # Or with auto-release on error:
            async with limiter.request() as ctx:
                if ctx:
                    try:
                        response = await make_api_call()
                    except (ConnectionError, TimeoutError, OSError):
                        ctx.release_on_error()
                        raise
        """
        return RateLimitContext(self, timeout)

    # Backward-compatible properties for internal state access
    @property
    def _tokens(self) -> float:
        """Backward-compatible access to available tokens."""
        return self._bucket.available_tokens

    @_tokens.setter
    def _tokens(self, value: float) -> None:
        """Backward-compatible setter for tokens (for testing)."""
        with self._bucket._sync_lock:
            self._bucket._tokens = value

    @property
    def _api_limit(self) -> int | None:
        """Backward-compatible access to API limit."""
        return self._bucket._api_limit

    @property
    def _api_remaining(self) -> int | None:
        """Backward-compatible access to API remaining."""
        return self._bucket._api_remaining

    @property
    def _api_reset(self) -> float | None:
        """Backward-compatible access to API reset time."""
        return self._bucket._api_reset

    @property
    def _last_refill(self) -> float:
        """Backward-compatible access to last refill time."""
        return self._bucket._last_refill

    @_last_refill.setter
    def _last_refill(self, value: float) -> None:
        """Backward-compatible setter for last refill (for testing)."""
        self._bucket._last_refill = value

    def _refill(self) -> None:
        """Backward-compatible refill method (for testing)."""
        self._bucket._refill()


class RateLimitContext:
    """Async context manager for rate limit acquisition.

    Acquires a rate limit token on entry and optionally releases on error.
    """

    def __init__(self, limiter: OpenRouterRateLimiter, timeout: float):
        self._limiter = limiter
        self._timeout = timeout
        self._acquired = False

    async def __aenter__(self) -> RateLimitContext:
        """Acquire rate limit on context entry."""
        self._acquired = await self._limiter.acquire(self._timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context (no automatic release)."""
        pass

    def __bool__(self) -> bool:
        """Check if rate limit was acquired."""
        return self._acquired

    def release_on_error(self) -> None:
        """Release the token back on request error."""
        if self._acquired:
            self._limiter.release_on_error()


class ProviderRateLimiter:
    """Generic rate limiter for any API provider.

    Uses the shared TokenBucket for core rate limiting with provider-specific
    configurations and exponential backoff for quota error recovery.

    Thread-safe with per-instance locks (no global lock contention).
    Uses asyncio.Lock for async methods to avoid blocking the event loop.
    """

    def __init__(self, provider: str, rpm: int | None = None, burst: int | None = None):
        """
        Initialize rate limiter for a specific provider.

        Args:
            provider: Provider name (e.g., 'anthropic', 'openai', 'gemini')
            rpm: Override requests per minute (uses provider default if None)
            burst: Override burst size (uses provider default if None)

        Rate limits can be overridden via environment variables:
            ARAGORA_{PROVIDER}_RPM - Requests per minute
            ARAGORA_{PROVIDER}_BURST - Burst size
        """
        from aragora.shared.rate_limiting import TokenBucket

        self.provider = provider.lower()

        # Get default tier for provider
        default_tier = PROVIDER_DEFAULT_TIERS.get(
            self.provider, ProviderTier(name=self.provider, requests_per_minute=100, burst_size=10)
        )

        # Allow environment variable overrides
        env_prefix = f"ARAGORA_{self.provider.upper()}"
        self.requests_per_minute = (
            rpm or int(os.environ.get(f"{env_prefix}_RPM", 0)) or default_tier.requests_per_minute
        )
        self.burst_size = (
            burst or int(os.environ.get(f"{env_prefix}_BURST", 0)) or default_tier.burst_size
        )

        # Delegate core token bucket logic to shared implementation
        self._bucket = TokenBucket(
            rate_per_minute=self.requests_per_minute,
            burst=self.burst_size,
            name=f"provider:{self.provider}",
        )

        # Exponential backoff for quota exhaustion recovery
        self._backoff = ExponentialBackoff(base_delay=2.0, max_delay=60.0, jitter=0.15)

        logger.debug(
            "Provider rate limiter initialized: provider=%s, rpm=%s, burst=%s",
            self.provider,
            self.requests_per_minute,
            self.burst_size,
        )

    async def acquire(self, timeout: float = 30.0) -> bool:
        """
        Acquire permission to make an API request.

        Blocks until a token is available or timeout is reached.
        Uses exponential backoff when recovering from rate limit errors.
        Returns True if acquired, False if timed out.

        Uses asyncio.Lock internally so waiting coroutines yield to the
        event loop instead of blocking the entire thread.
        """
        start_time = time.monotonic()
        deadline = start_time + timeout

        # If in backoff state, wait before trying
        if self._backoff.is_backing_off:
            backoff_delay = self._backoff.get_delay()
            remaining = deadline - time.monotonic()
            if backoff_delay > remaining:
                logger.debug(
                    f"[{self.provider}] Backoff delay {backoff_delay:.1f}s "
                    f"exceeds timeout {remaining:.1f}s"
                )
                return False
            logger.debug(f"[{self.provider}] rate_limiter_backoff_wait delay={backoff_delay:.1f}s")
            await asyncio.sleep(backoff_delay)

        # Adjust timeout for time spent in backoff
        remaining_timeout = max(0.0, deadline - time.monotonic())

        # Delegate to shared token bucket
        acquired = await self._bucket.acquire_async(timeout=remaining_timeout)

        if not acquired:
            logger.debug("[%s] rate limit timeout", self.provider)
            return False

        # Stagger delay to allow parallel token acquisition
        from aragora.config import INTER_REQUEST_DELAY_SECONDS

        if INTER_REQUEST_DELAY_SECONDS > 0:
            await asyncio.sleep(INTER_REQUEST_DELAY_SECONDS)

        return True

    def update_from_headers(self, headers: dict) -> None:
        """Update rate limit state from API response headers.

        Delegates to shared TokenBucket for header parsing.
        """
        self._bucket.update_from_headers(headers)

    def release_on_error(self) -> None:
        """Release a token back on request error (optional, for retries)."""
        self._bucket.release()

    def record_rate_limit_error(self, status_code: int = 429) -> float:
        """Record a rate limit error (429/403) and return backoff delay."""
        logger.debug("[%s] rate_limit_error status=%s", self.provider, status_code)
        delay = self._backoff.record_failure()
        self.release_on_error()
        return delay

    def record_success(self) -> None:
        """Record a successful API request to reset backoff state."""
        self._backoff.reset()

    @property
    def is_backing_off(self) -> bool:
        """Check if currently in exponential backoff due to rate limit errors."""
        return self._backoff.is_backing_off

    @property
    def stats(self) -> dict:
        """Get current rate limiter statistics."""
        bucket_stats = self._bucket.stats
        return {
            "provider": self.provider,
            "rpm_limit": self.requests_per_minute,
            "tokens_available": int(bucket_stats.get("tokens_available", 0)),
            "burst_size": self.burst_size,
            "api_limit": bucket_stats.get("api_limit"),
            "api_remaining": bucket_stats.get("api_remaining"),
            "backoff_failures": self._backoff.failure_count,
            "is_backing_off": self._backoff.is_backing_off,
            "acquired": bucket_stats.get("acquired", 0),
            "rejected": bucket_stats.get("rejected", 0),
        }

    def request(self, timeout: float = 30.0) -> ProviderRateLimitContext:
        """Context manager for rate-limited API requests."""
        return ProviderRateLimitContext(self, timeout)

    # Backward-compatible properties for internal state access
    @property
    def _tokens(self) -> float:
        """Backward-compatible access to available tokens."""
        return self._bucket.available_tokens

    @_tokens.setter
    def _tokens(self, value: float) -> None:
        """Backward-compatible setter for tokens (for testing)."""
        with self._bucket._sync_lock:
            self._bucket._tokens = value

    @property
    def _api_limit(self) -> int | None:
        """Backward-compatible access to API limit."""
        return self._bucket._api_limit

    @property
    def _api_remaining(self) -> int | None:
        """Backward-compatible access to API remaining."""
        return self._bucket._api_remaining

    @property
    def _api_reset(self) -> float | None:
        """Backward-compatible access to API reset time."""
        return self._bucket._api_reset

    @property
    def _last_refill(self) -> float:
        """Backward-compatible access to last refill time."""
        return self._bucket._last_refill

    @_last_refill.setter
    def _last_refill(self, value: float) -> None:
        """Backward-compatible setter for last refill (for testing)."""
        self._bucket._last_refill = value

    def _refill(self) -> None:
        """Backward-compatible refill method (for testing)."""
        self._bucket._refill()


class ProviderRateLimitContext:
    """Async context manager for provider rate limit acquisition."""

    def __init__(self, limiter: ProviderRateLimiter, timeout: float):
        self._limiter = limiter
        self._timeout = timeout
        self._acquired = False

    async def __aenter__(self) -> ProviderRateLimitContext:
        """Acquire rate limit on context entry."""
        self._acquired = await self._limiter.acquire(self._timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context (no automatic release)."""
        pass

    def __bool__(self) -> bool:
        """Check if rate limit was acquired."""
        return self._acquired

    def release_on_error(self) -> None:
        """Release the token back on request error."""
        if self._acquired:
            self._limiter.release_on_error()


class ProviderRateLimiterRegistry:
    """Registry for per-provider rate limiters.

    Provides isolated rate limiters for each API provider to avoid
    global lock contention. Each provider gets its own rate limiter
    instance with its own lock.

    Thread-safe access to rate limiters with lazy initialization.
    """

    def __init__(self) -> None:
        self._limiters: dict[str, ProviderRateLimiter] = {}
        self._lock = threading.Lock()

    def get(
        self, provider: str, rpm: int | None = None, burst: int | None = None
    ) -> ProviderRateLimiter:
        """Get or create a rate limiter for a provider.

        Args:
            provider: Provider name (e.g., 'anthropic', 'openai')
            rpm: Override requests per minute (only used on first access)
            burst: Override burst size (only used on first access)

        Returns:
            ProviderRateLimiter instance for the provider
        """
        provider = provider.lower()

        # Fast path: check without lock
        if provider in self._limiters:
            return self._limiters[provider]

        # Slow path: create new limiter with lock
        with self._lock:
            # Double-check after acquiring lock
            if provider not in self._limiters:
                self._limiters[provider] = ProviderRateLimiter(
                    provider=provider, rpm=rpm, burst=burst
                )
                logger.debug("Created rate limiter for provider: %s", provider)
            return self._limiters[provider]

    def reset(self, provider: str | None = None) -> None:
        """Reset rate limiter(s).

        Args:
            provider: Provider to reset, or None to reset all
        """
        with self._lock:
            if provider:
                if provider.lower() in self._limiters:
                    del self._limiters[provider.lower()]
                    logger.debug("Reset rate limiter for provider: %s", provider)
            else:
                self._limiters.clear()
                logger.debug("Reset all provider rate limiters")

    def stats(self) -> dict[str, dict]:
        """Get statistics for all registered rate limiters."""
        with self._lock:
            return {provider: limiter.stats for provider, limiter in self._limiters.items()}

    def providers(self) -> list:
        """Get list of registered provider names."""
        with self._lock:
            return list(self._limiters.keys())


# Global registry for per-provider rate limiters
_provider_registry: ProviderRateLimiterRegistry | None = None
_provider_registry_lock = threading.Lock()


def get_provider_limiter(
    provider: str, rpm: int | None = None, burst: int | None = None
) -> ProviderRateLimiter:
    """Get a rate limiter for a specific API provider.

    This is the primary interface for getting rate limiters.
    Each provider gets its own rate limiter instance with its own lock,
    eliminating global lock contention.

    Args:
        provider: Provider name (e.g., 'anthropic', 'openai', 'gemini', 'grok')
        rpm: Override requests per minute (only used on first access)
        burst: Override burst size (only used on first access)

    Returns:
        ProviderRateLimiter instance for the provider

    Example:
        # Get rate limiter for Anthropic
        limiter = get_provider_limiter("anthropic")

        # Use rate limiter
        async with limiter.request() as ctx:
            if ctx:
                response = await make_api_call()
    """
    global _provider_registry

    if _provider_registry is None:
        with _provider_registry_lock:
            if _provider_registry is None:
                _provider_registry = ProviderRateLimiterRegistry()

    return _provider_registry.get(provider, rpm=rpm, burst=burst)


def get_provider_registry() -> ProviderRateLimiterRegistry:
    """Get the global provider rate limiter registry.

    Returns:
        The singleton ProviderRateLimiterRegistry instance
    """
    global _provider_registry

    if _provider_registry is None:
        with _provider_registry_lock:
            if _provider_registry is None:
                _provider_registry = ProviderRateLimiterRegistry()

    return _provider_registry


def reset_provider_limiters(provider: str | None = None) -> None:
    """Reset rate limiter(s) for providers.

    Args:
        provider: Provider to reset, or None to reset all
    """
    global _provider_registry
    if provider is None:
        # Full reset - clear the global registry entirely
        with _provider_registry_lock:
            _provider_registry = None
    else:
        # Reset specific provider only
        registry = get_provider_registry()
        registry.reset(provider)


# Use ServiceRegistry for rate limiter singleton management
_openrouter_limiter_lock = threading.Lock()


def get_openrouter_limiter() -> OpenRouterRateLimiter:
    """Get or create the global OpenRouter rate limiter.

    Uses ServiceRegistry for centralized singleton management.
    """
    from aragora.runtime.service_registry import ServiceRegistry

    with _openrouter_limiter_lock:
        registry = ServiceRegistry.get()
        if not registry.has(OpenRouterRateLimiter):
            registry.register(OpenRouterRateLimiter, OpenRouterRateLimiter())
        return registry.resolve(OpenRouterRateLimiter)


def set_openrouter_tier(tier: str) -> None:
    """Set the OpenRouter rate limit tier.

    Valid tiers: free, basic, standard, premium, unlimited
    """
    from aragora.runtime.service_registry import ServiceRegistry

    with _openrouter_limiter_lock:
        registry = ServiceRegistry.get()
        registry.register(OpenRouterRateLimiter, OpenRouterRateLimiter(tier=tier))


__all__ = [
    # Exponential backoff
    "ExponentialBackoff",
    # OpenRouter (legacy)
    "OpenRouterTier",
    "OPENROUTER_TIERS",
    "OpenRouterRateLimiter",
    "RateLimitContext",
    "get_openrouter_limiter",
    "set_openrouter_tier",
    # Per-provider rate limiters (new)
    "ProviderTier",
    "PROVIDER_DEFAULT_TIERS",
    "ProviderRateLimiter",
    "ProviderRateLimitContext",
    "ProviderRateLimiterRegistry",
    "get_provider_limiter",
    "get_provider_registry",
    "reset_provider_limiters",
]
