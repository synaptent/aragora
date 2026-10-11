"""
Tier-based rate limiter implementation.

Provides rate limiting based on subscription tiers (free, starter,
professional, enterprise).
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any

from .base import (
    CLIENT_IP_HEADERS,
    _extract_client_ip,
    sanitize_rate_limit_key_component,
)
from .bucket import TokenBucket
from .limiter import RateLimitResult

logger = logging.getLogger(__name__)

# Tier-based rate limits (requests per minute, burst size)
TIER_RATE_LIMITS: dict[str, tuple[int, int]] = {
    "free": (10, 60),  # 10 req/min, 60 burst
    "starter": (50, 100),  # 50 req/min, 100 burst
    "professional": (200, 400),  # 200 req/min, 400 burst
    "enterprise": (1000, 2000),  # 1000 req/min, 2000 burst
}


class TierRateLimiter:
    """
    Tier-aware rate limiter that applies different limits based on subscription tier.

    Looks up user's organization tier and applies corresponding rate limits.
    Falls back to 'free' tier limits for unauthenticated requests.
    """

    def __init__(
        self,
        tier_limits: dict[str, tuple[int, int]] | None = None,
        max_entries: int = 10000,
    ):
        """
        Initialize tier rate limiter.

        Args:
            tier_limits: Dict mapping tier name to (requests_per_minute, burst_size).
            max_entries: Maximum bucket entries before LRU eviction.
        """
        self.tier_limits = tier_limits or TIER_RATE_LIMITS
        self.max_entries = max_entries

        # Separate buckets per tier for fair isolation
        self._tier_buckets: dict[str, OrderedDict[str, TokenBucket]] = {
            tier: OrderedDict() for tier in self.tier_limits
        }
        self._lock = threading.Lock()

    def get_tier_limits(self, tier: str) -> tuple[int, int]:
        """Get (rate, burst) for a tier, defaulting to free."""
        return self.tier_limits.get(tier.lower(), self.tier_limits.get("free", (10, 60)))

    def allow(
        self,
        client_key: str,
        tier: str = "free",
    ) -> RateLimitResult:
        """
        Check if request is allowed for given tier.

        Args:
            client_key: Unique client identifier (user_id, org_id, or IP).
            tier: Subscription tier name.

        Returns:
            RateLimitResult with allowed status and metadata.
        """
        tier = tier.lower()
        rate, burst = self.get_tier_limits(tier)

        with self._lock:
            if tier not in self._tier_buckets:
                self._tier_buckets[tier] = OrderedDict()

            buckets = self._tier_buckets[tier]

            if client_key in buckets:
                buckets.move_to_end(client_key)
                bucket = buckets[client_key]
            else:
                # LRU eviction
                max_per_tier = self.max_entries // len(self.tier_limits)
                while len(buckets) >= max_per_tier:
                    buckets.popitem(last=False)

                bucket = TokenBucket(rate, burst)
                buckets[client_key] = bucket

        allowed = bucket.consume(1)

        return RateLimitResult(
            allowed=allowed,
            remaining=bucket.remaining,
            limit=rate,
            retry_after=bucket.get_retry_after() if not allowed else 0,
            key=f"tier:{tier}:{client_key}",
        )

    def get_stats(self) -> dict[str, Any]:
        """Get tier rate limiter statistics."""
        with self._lock:
            return {
                "tier_buckets": {
                    tier: len(buckets) for tier, buckets in self._tier_buckets.items()
                },
                "tier_limits": self.tier_limits,
            }

    def reset(self) -> None:
        """Reset all rate limiter state."""
        with self._lock:
            for buckets in self._tier_buckets.values():
                buckets.clear()


# Global tier rate limiter instance
_tier_limiter: TierRateLimiter | None = None


def get_tier_rate_limiter() -> TierRateLimiter:
    """Get the global tier rate limiter instance."""
    global _tier_limiter
    if _tier_limiter is None:
        _tier_limiter = TierRateLimiter()
    return _tier_limiter


def check_tier_rate_limit(
    handler: Any,
    user_store: Any = None,
) -> RateLimitResult:
    """
    Check rate limit based on user's subscription tier.

    Extracts user from request, looks up their org tier, and applies
    tier-appropriate rate limits.

    Args:
        handler: HTTP request handler.
        user_store: UserStore instance for looking up orgs.

    Returns:
        RateLimitResult with allowed status.
    """
    limiter = get_tier_rate_limiter()

    # Default to free tier for anonymous/unauthenticated
    tier = "free"

    # Use secure IP extraction that respects TRUSTED_PROXIES
    remote_ip = "anonymous"
    if hasattr(handler, "client_address"):
        addr = handler.client_address
        if isinstance(addr, tuple) and len(addr) >= 1:
            remote_ip = str(addr[0])

    headers = {}
    if hasattr(handler, "headers"):
        headers = {name: handler.headers.get(name, "") for name in CLIENT_IP_HEADERS}

    client_key = sanitize_rate_limit_key_component(_extract_client_ip(headers, remote_ip))

    # Try to look up user tier
    if user_store:
        try:
            from aragora.billing.jwt_auth import extract_user_from_request

            auth_ctx = extract_user_from_request(handler, user_store)

            if auth_ctx.is_authenticated:
                # Use user_id as key for authenticated users (more stable)
                client_key = auth_ctx.user_id or client_key

                if auth_ctx.org_id:
                    org = user_store.get_organization_by_id(auth_ctx.org_id)
                    if org:
                        tier = org.tier.value
        except (ImportError, ValueError, TypeError, KeyError, RuntimeError) as e:
            logger.debug("Could not extract user tier: %s", e)

    return limiter.allow(client_key, tier)


__all__ = [
    "TIER_RATE_LIMITS",
    "TierRateLimiter",
    "get_tier_rate_limiter",
    "check_tier_rate_limit",
]
