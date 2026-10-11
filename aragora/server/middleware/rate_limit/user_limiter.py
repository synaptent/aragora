"""
Per-user rate limiter implementation.

Provides fine-grained rate limiting based on user_id rather than IP,
with per-action rate limits.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from .base import (
    CLIENT_IP_HEADERS,
    BURST_MULTIPLIER,
    _extract_client_ip,
    sanitize_rate_limit_key_component,
)
from .bucket import TokenBucket
from .limiter import RateLimitResult

logger = logging.getLogger(__name__)

# Per-user rate limits (requests per minute)
USER_RATE_LIMITS: dict[str, int] = {
    "default": 60,  # Default for authenticated users
    "debate_create": 10,  # Creating new debates
    "debate_search": 30,  # Searching debates (ReDoS protection)
    "vote": 30,  # Voting on proposals
    "agent_call": 120,  # Calling agent APIs
    "export": 5,  # Exporting data
    "admin": 300,  # Admin operations
    # New security-focused limits
    "batch_submit": 2,  # Batch operations (expensive)
    "evidence_collect": 10,  # Evidence collection (external APIs)
    "knowledge_query": 20,  # Knowledge base queries
    "memory_cleanup": 5,  # Memory management operations
    "plugin_install": 3,  # Plugin installation
    # Slack integration limits (per workspace:user)
    "slack_command": 10,  # Slash commands per user
    "slack_debate": 5,  # Debate creation via Slack
    "slack_gauntlet": 3,  # Gauntlet runs via Slack
}


class UserRateLimiter:
    """
    Per-authenticated-user rate limiter.

    Provides fine-grained rate limiting based on user_id rather than IP.
    This ensures that:
    1. Users behind shared IPs don't compete for rate limits
    2. Individual users can't abuse the system by changing IPs
    3. Different operations can have different limits per user

    Usage:
        limiter = UserRateLimiter()

        # Check if user can perform action
        result = limiter.allow(user_id="user-123", action="debate_create")
        if not result.allowed:
            return error_429(retry_after=result.retry_after)

        # Or use check_user_rate_limit helper
        result = check_user_rate_limit(handler, user_store, action="vote")
    """

    def __init__(
        self,
        action_limits: dict[str, int] | None = None,
        default_limit: int = 60,
        max_users: int = 10000,
    ):
        """
        Initialize per-user rate limiter.

        Args:
            action_limits: Dict mapping action name to requests_per_minute.
            default_limit: Default limit for unlisted actions.
            max_users: Maximum user entries before LRU eviction.
        """
        self.action_limits = action_limits or USER_RATE_LIMITS
        self.default_limit = default_limit
        self.max_users = max_users

        # Nested structure: action -> user_id -> TokenBucket
        self._user_buckets: dict[str, OrderedDict[str, TokenBucket]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def get_action_limit(self, action: str) -> int:
        """Get rate limit for an action."""
        return self.action_limits.get(action, self.default_limit)

    def allow(
        self,
        user_id: str,
        action: str = "default",
    ) -> RateLimitResult:
        """
        Check if user can perform action.

        Args:
            user_id: Unique user identifier.
            action: Action name (maps to rate limit).

        Returns:
            RateLimitResult with allowed status and metadata.
        """
        limit = self.get_action_limit(action)

        with self._lock:
            if action not in self._user_buckets:
                self._user_buckets[action] = OrderedDict()

            buckets = self._user_buckets[action]

            if user_id in buckets:
                buckets.move_to_end(user_id)
                bucket = buckets[user_id]
            else:
                # LRU eviction per action
                max_per_action = self.max_users // max(1, len(self._user_buckets))
                while len(buckets) >= max_per_action:
                    buckets.popitem(last=False)

                bucket = TokenBucket(limit, burst_size=int(limit * BURST_MULTIPLIER))
                buckets[user_id] = bucket

        allowed = bucket.consume(1)

        return RateLimitResult(
            allowed=allowed,
            remaining=bucket.remaining,
            limit=limit,
            retry_after=bucket.get_retry_after() if not allowed else 0,
            key=f"user:{user_id}:{action}",
        )

    def cleanup(self, max_age_seconds: int = 600) -> int:
        """Remove stale user entries."""
        with self._lock:
            now = time.monotonic()
            removed = 0

            for action, buckets in list(self._user_buckets.items()):
                stale = [
                    uid
                    for uid, bucket in buckets.items()
                    if now - bucket.last_refill > max_age_seconds
                ]
                for uid in stale:
                    del buckets[uid]
                    removed += 1

                if not buckets:
                    del self._user_buckets[action]

            return removed

    def get_user_status(self, user_id: str) -> dict[str, dict[str, Any]]:
        """Get rate limit status for a user across all actions."""
        with self._lock:
            status = {}
            for action, buckets in self._user_buckets.items():
                if user_id in buckets:
                    bucket = buckets[user_id]
                    status[action] = {
                        "remaining": bucket.remaining,
                        "limit": self.get_action_limit(action),
                        "retry_after": bucket.get_retry_after(),
                    }
            return status

    def get_stats(self) -> dict[str, Any]:
        """Get user rate limiter statistics."""
        with self._lock:
            return {
                "action_buckets": {
                    action: len(buckets) for action, buckets in self._user_buckets.items()
                },
                "action_limits": self.action_limits,
                "total_users": sum(len(buckets) for buckets in self._user_buckets.values()),
            }

    def reset(self) -> None:
        """Reset all rate limiter state."""
        with self._lock:
            self._user_buckets.clear()


# Global user rate limiter instance
_user_limiter: UserRateLimiter | None = None


def get_user_rate_limiter() -> UserRateLimiter:
    """Get the global user rate limiter instance."""
    global _user_limiter
    if _user_limiter is None:
        _user_limiter = UserRateLimiter()
    return _user_limiter


def check_user_rate_limit(
    handler: Any,
    user_store: Any = None,
    action: str = "default",
) -> RateLimitResult:
    """
    Check rate limit for authenticated user.

    Falls back to IP-based limiting for unauthenticated requests.

    Args:
        handler: HTTP request handler.
        user_store: UserStore instance for auth extraction.
        action: Action being performed (maps to rate limit).

    Returns:
        RateLimitResult with allowed status.
    """
    limiter = get_user_rate_limiter()

    # Default to IP-based key for unauthenticated
    # Use secure IP extraction that respects TRUSTED_PROXIES
    remote_ip = "anon"
    if hasattr(handler, "client_address"):
        addr = handler.client_address
        if isinstance(addr, tuple) and len(addr) >= 1:
            remote_ip = str(addr[0])

    headers = {}
    if hasattr(handler, "headers"):
        headers = {name: handler.headers.get(name, "") for name in CLIENT_IP_HEADERS}

    client_ip = sanitize_rate_limit_key_component(_extract_client_ip(headers, remote_ip))
    client_key = f"ip:{client_ip}" if client_ip != "anon" else "anon"

    # Try to extract authenticated user
    if user_store:
        try:
            from aragora.billing.jwt_auth import extract_user_from_request

            auth_ctx = extract_user_from_request(handler, user_store)

            if auth_ctx.is_authenticated and auth_ctx.user_id:
                client_key = auth_ctx.user_id
        except (ImportError, ValueError, TypeError, KeyError, RuntimeError) as e:
            logger.debug("Could not extract user for rate limiting: %s", e)

    return limiter.allow(client_key, action)


__all__ = [
    "USER_RATE_LIMITS",
    "UserRateLimiter",
    "get_user_rate_limiter",
    "check_user_rate_limit",
]
