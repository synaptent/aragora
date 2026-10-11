"""
Default rate limiter helpers.

Provides a conservative, always-on rate limiting layer for handlers that
do not explicitly use the rate_limit decorators.  Supports three auth tiers
(public / authenticated / admin) with configurable RPM and burst limits.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from typing import Any

from .base import CLIENT_IP_HEADERS, _extract_client_ip, sanitize_rate_limit_key_component
from .bucket import TokenBucket
from .limiter import RateLimitResult

logger = logging.getLogger(__name__)

# Conservative defaults by auth tier: (requests_per_minute, burst_size)
DEFAULT_RATE_LIMITS: dict[str, tuple[int, int]] = {
    "public": (30, 60),
    "authenticated": (120, 240),
    "admin": (300, 600),
}


def determine_auth_tier(handler: Any) -> tuple[str, str]:
    """Determine auth tier and client key for a request handler.

    Returns:
        Tuple of (tier, client_key) where tier is one of
        "public", "authenticated", or "admin".
    """
    # Extract IP-based fallback key
    remote_ip = "anonymous"
    if hasattr(handler, "client_address"):
        addr = handler.client_address
        if isinstance(addr, tuple) and len(addr) >= 1:
            remote_ip = str(addr[0])

    headers: dict[str, str] = {}
    if hasattr(handler, "headers"):
        h = handler.headers
        if isinstance(h, dict):
            headers = h
        else:
            headers = {name: h.get(name, "") if h else "" for name in CLIENT_IP_HEADERS}

    client_ip = _extract_client_ip(headers, remote_ip)
    fallback_key = sanitize_rate_limit_key_component(client_ip)

    # Try JWT-based auth extraction
    try:
        from aragora.billing.jwt_auth import extract_user_from_request

        auth_ctx = extract_user_from_request(handler)

        if getattr(auth_ctx, "is_authenticated", False):
            user_id = getattr(auth_ctx, "user_id", None) or fallback_key

            # Check for admin
            is_admin = getattr(auth_ctx, "is_admin", False)
            roles = getattr(auth_ctx, "roles", [])
            permissions = getattr(auth_ctx, "permissions", [])

            # Normalize roles to a set of lowercase strings
            if isinstance(roles, (list, tuple, set, frozenset)):
                role_set = {str(r).lower() for r in roles}
            else:
                role_set = set()

            # Normalize permissions similarly
            if isinstance(permissions, (list, tuple, set, frozenset)):
                perm_set = {str(p).lower() for p in permissions}
            else:
                perm_set = set()

            if is_admin or "admin" in role_set or "admin" in perm_set:
                return "admin", str(user_id)

            return "authenticated", str(user_id)

        # Not authenticated
        if not getattr(auth_ctx, "is_authenticated", True):
            return "public", fallback_key

    except (ImportError, AttributeError, ValueError, TypeError):
        pass

    return "public", fallback_key


def _extract_request_path(handler: Any) -> str | None:
    path = getattr(handler, "path", None)
    if not path:
        return None
    return path.split("?", 1)[0]


def _extract_token(handler: Any) -> str | None:
    headers = getattr(handler, "headers", None)
    if not headers:
        return None
    token = headers.get("Authorization") or headers.get("authorization")
    if not token:
        return None
    return sanitize_rate_limit_key_component(str(token))


def _extract_tenant_id(handler: Any) -> str | None:
    auth_ctx = getattr(handler, "_auth_context", None)
    if auth_ctx is not None:
        tenant = getattr(auth_ctx, "org_id", None) or getattr(auth_ctx, "workspace_id", None)
        if tenant:
            return sanitize_rate_limit_key_component(str(tenant))

    headers = getattr(handler, "headers", None)
    if headers:
        tenant = headers.get("X-Tenant-ID") or headers.get("X-Workspace-ID")
        if tenant:
            return sanitize_rate_limit_key_component(str(tenant))
    return None


def get_handler_default_rpm(handler: Any) -> int | None:
    """Get custom default requests-per-minute from handler, or None."""
    rpm = getattr(handler, "DEFAULT_RATE_LIMIT_RPM", None)
    if rpm is not None:
        return int(rpm)
    return None


def handler_has_rate_limit_decorator(handler: Any, handler_method_name: str) -> bool:
    """Check if the handler method has an explicit rate limit decorator."""
    if not handler or not handler_method_name:
        return False
    method = getattr(handler, handler_method_name, None)
    if method is None:
        return False
    return bool(getattr(method, "_rate_limited", False))


def _is_rate_limiting_globally_disabled() -> bool:
    """Check if rate limiting is globally disabled via environment variable."""
    return os.environ.get("ARAGORA_DISABLE_ALL_RATE_LIMITS", "").lower() in (
        "1",
        "true",
        "yes",
    )


def should_apply_default_rate_limit(handler: Any, handler_method_name: str) -> bool:
    """Apply default limiter only when no explicit decorator is present.

    Returns False if:
    - The handler has ``RATE_LIMIT_EXEMPT = True``
    - The handler has ``_skip_default_rate_limit = True``
    - ``ARAGORA_DISABLE_ALL_RATE_LIMITS`` environment variable is set
    - The handler method already has an explicit ``@rate_limit`` decorator
    """
    if _is_rate_limiting_globally_disabled():
        return False
    if getattr(handler, "RATE_LIMIT_EXEMPT", False):
        return False
    if getattr(handler, "_skip_default_rate_limit", False):
        return False
    return not handler_has_rate_limit_decorator(handler, handler_method_name)


class DefaultRateLimiter:
    """Tier-aware default rate limiter.

    Maintains separate token buckets per (tier, client_key) pair so that
    public, authenticated, and admin traffic each get their own limits.
    """

    def __init__(
        self,
        rate_limits: dict[str, int] | None = None,
        tier_limits: dict[str, tuple[int, int]] | None = None,
        max_entries: int = 10000,
    ) -> None:
        # tier_limits takes precedence if provided; otherwise fall back
        # to rate_limits (old-style dict[str, int]) or defaults.
        if tier_limits is not None:
            self._tier_limits = dict(tier_limits)
        elif rate_limits is not None:
            # Legacy compatibility: rate_limits was dict[str, int]
            self._tier_limits = {
                k: (v, v * 2) if isinstance(v, int) else v for k, v in rate_limits.items()
            }
        else:
            self._tier_limits = dict(DEFAULT_RATE_LIMITS)

        self.max_entries = max_entries

        # Separate buckets per tier for fair isolation
        self._tier_buckets: dict[str, OrderedDict[str, TokenBucket]] = {
            tier: OrderedDict() for tier in self._tier_limits
        }
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tier_limits(self, tier: str) -> tuple[int, int]:
        """Get ``(rate, burst)`` for a tier, defaulting to public."""
        return self._tier_limits.get(
            tier.lower(),
            self._tier_limits.get("public", (30, 60)),
        )

    def allow(self, client_key: str, tier: str = "public") -> RateLimitResult:
        """Check if a request is allowed under the given tier.

        Args:
            client_key: Unique client identifier (user_id or IP).
            tier: Auth tier name ("public", "authenticated", "admin").

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
                n_tiers = max(len(self._tier_limits), 1)
                max_per_tier = self.max_entries // n_tiers
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
            key=f"default:{tier}:{client_key}",
        )

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics."""
        with self._lock:
            return {
                "tier_buckets": {
                    tier: len(buckets) for tier, buckets in self._tier_buckets.items()
                },
                "tier_limits": dict(self._tier_limits),
            }

    def reset(self) -> None:
        """Reset all rate limiter state."""
        with self._lock:
            for buckets in self._tier_buckets.values():
                buckets.clear()


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_default_limiter: DefaultRateLimiter | None = None


def get_default_rate_limiter() -> DefaultRateLimiter:
    """Get global DefaultRateLimiter instance."""
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = DefaultRateLimiter()
    return _default_limiter


def reset_default_rate_limiter() -> None:
    """Reset global DefaultRateLimiter instance."""
    global _default_limiter
    _default_limiter = None


def check_default_rate_limit(handler: Any) -> RateLimitResult:
    """Check default rate limit for a handler.

    Extracts the auth tier and client key from the handler, then delegates
    to the global :class:`DefaultRateLimiter`.
    """
    tier, client_key = determine_auth_tier(handler)
    return get_default_rate_limiter().allow(client_key, tier)


__all__ = [
    "DEFAULT_RATE_LIMITS",
    "DefaultRateLimiter",
    "get_default_rate_limiter",
    "reset_default_rate_limiter",
    "determine_auth_tier",
    "check_default_rate_limit",
    "handler_has_rate_limit_decorator",
    "should_apply_default_rate_limit",
    "get_handler_default_rpm",
]
