"""
Rate limiter implementation.

Provides the core RateLimiter class for IP-based, token-based, and
endpoint-based rate limiting with LRU eviction.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from .base import (
    CLIENT_IP_HEADERS,
    DEFAULT_RATE_LIMIT,
    IP_RATE_LIMIT,
    _extract_client_ip,
    _normalize_ip,
    normalize_rate_limit_path,
    sanitize_rate_limit_key_component,
)
from .bucket import TokenBucket

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit rule."""

    requests_per_minute: int = DEFAULT_RATE_LIMIT
    burst_size: int | None = None
    key_type: str = "ip"  # "ip", "token", "endpoint", "combined", "tenant"
    enabled: bool = True


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int = 0
    limit: int = 0
    retry_after: float = 0
    key: str = ""


class RateLimiter:
    """
    Unified rate limiter for API endpoints.

    Supports per-IP, per-token, and per-endpoint rate limiting with
    automatic cleanup of stale entries via LRU eviction.
    """

    def __init__(
        self,
        default_limit: int = DEFAULT_RATE_LIMIT,
        ip_limit: int = IP_RATE_LIMIT,
        cleanup_interval: int = 300,  # 5 minutes
        max_entries: int = 10000,
    ):
        """
        Initialize rate limiter.

        Args:
            default_limit: Default requests per minute for unspecified endpoints.
            ip_limit: Requests per minute per IP address.
            cleanup_interval: Seconds between stats logging.
            max_entries: Maximum entries before LRU eviction.
        """
        self.default_limit = default_limit
        self.ip_limit = ip_limit
        self.cleanup_interval = cleanup_interval
        self.max_entries = max_entries

        # Buckets by key type (OrderedDict for LRU eviction)
        self._ip_buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        self._token_buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        self._tenant_buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        self._endpoint_buckets: dict[str, OrderedDict[str, TokenBucket]] = {}

        # Per-endpoint configuration
        self._endpoint_configs: dict[str, RateLimitConfig] = {}

        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

        # Observability metrics
        self._requests_allowed: int = 0
        self._requests_rejected: int = 0
        self._rejections_by_endpoint: dict[str, int] = {}

    def configure_endpoint(
        self,
        endpoint: str,
        requests_per_minute: int,
        burst_size: int | None = None,
        key_type: str = "combined",
    ) -> None:
        """
        Configure rate limit for a specific endpoint.

        Args:
            endpoint: API endpoint path (e.g., "/api/debates").
            requests_per_minute: Max requests per minute.
            burst_size: Max burst capacity (default: 2x rate).
            key_type: How to key the limit ("ip", "token", "endpoint", "combined").
        """
        if burst_size is None:
            burst_size = requests_per_minute
        self._endpoint_configs[endpoint] = RateLimitConfig(
            requests_per_minute=requests_per_minute,
            burst_size=burst_size,
            key_type=key_type,
        )

    def get_config(self, endpoint: str) -> RateLimitConfig:
        """Get rate limit config for an endpoint."""
        if endpoint in self._endpoint_configs:
            return self._endpoint_configs[endpoint]

        # Check for prefix match (wildcard endpoints)
        for path, config in self._endpoint_configs.items():
            if path.endswith("*") and endpoint.startswith(path[:-1]):
                return config

        return RateLimitConfig(requests_per_minute=self.default_limit)

    def allow(
        self,
        client_ip: str,
        endpoint: str | None = None,
        token: str | None = None,
        tenant_id: str | None = None,
    ) -> RateLimitResult:
        """
        Check if a request should be allowed.

        Args:
            client_ip: Client IP address.
            endpoint: Optional endpoint for per-endpoint limits.
            token: Optional auth token for per-token limits.
            tenant_id: Optional tenant ID for per-tenant limits.

        Returns:
            RateLimitResult with allowed status and metadata.
        """
        self._maybe_cleanup()

        normalized_endpoint = normalize_rate_limit_path(endpoint) if endpoint else None
        config = self.get_config(normalized_endpoint) if normalized_endpoint else RateLimitConfig()
        if not config.enabled:
            return RateLimitResult(allowed=True, limit=0)

        client_ip = _normalize_ip(client_ip or "anonymous")
        safe_ip = sanitize_rate_limit_key_component(client_ip)
        safe_token = sanitize_rate_limit_key_component(token) if token else None
        safe_endpoint = (
            sanitize_rate_limit_key_component(normalized_endpoint) if normalized_endpoint else None
        )
        safe_tenant = sanitize_rate_limit_key_component(tenant_id) if tenant_id else None

        # Determine the key based on config
        if config.key_type == "tenant" and safe_tenant:
            key = f"tenant:{safe_tenant}"
            bucket = self._get_or_create_tenant_bucket(safe_tenant, config)
        elif config.key_type == "token" and safe_token:
            key = f"token:{safe_token}"
            bucket = self._get_or_create_token_bucket(safe_token, config)
        elif config.key_type == "combined" and safe_endpoint:
            key = f"ep:{safe_endpoint}:ip:{safe_ip}"
            bucket = self._get_or_create_endpoint_bucket(safe_endpoint, safe_ip, config)
        elif config.key_type == "endpoint" and safe_endpoint:
            key = f"ep:{safe_endpoint}"
            bucket = self._get_or_create_endpoint_bucket(safe_endpoint, "_global", config)
        else:
            # Default to IP-based limiting
            key = f"ip:{safe_ip}"
            bucket = self._get_or_create_ip_bucket(safe_ip)

        allowed = bucket.consume(1)

        # Track metrics
        with self._lock:
            if allowed:
                self._requests_allowed += 1
            else:
                self._requests_rejected += 1
                if safe_endpoint:
                    self._rejections_by_endpoint[safe_endpoint] = (
                        self._rejections_by_endpoint.get(safe_endpoint, 0) + 1
                    )

        return RateLimitResult(
            allowed=allowed,
            remaining=bucket.remaining,
            limit=config.requests_per_minute,
            retry_after=bucket.get_retry_after() if not allowed else 0,
            key=key,
        )

    def _get_or_create_ip_bucket(self, ip: str) -> TokenBucket:
        """Get or create an IP-based bucket with LRU eviction."""
        with self._lock:
            if ip in self._ip_buckets:
                self._ip_buckets.move_to_end(ip)
                return self._ip_buckets[ip]

            # Evict oldest entries if at capacity
            max_ip_buckets = self.max_entries // 4
            while len(self._ip_buckets) >= max_ip_buckets:
                self._ip_buckets.popitem(last=False)

            self._ip_buckets[ip] = TokenBucket(self.ip_limit)
            return self._ip_buckets[ip]

    def _get_or_create_token_bucket(
        self,
        token: str,
        config: RateLimitConfig,
    ) -> TokenBucket:
        """Get or create a token-based bucket with LRU eviction."""
        with self._lock:
            if token in self._token_buckets:
                self._token_buckets.move_to_end(token)
                return self._token_buckets[token]

            max_token_buckets = self.max_entries // 4
            while len(self._token_buckets) >= max_token_buckets:
                self._token_buckets.popitem(last=False)

            self._token_buckets[token] = TokenBucket(
                config.requests_per_minute,
                config.burst_size,
            )
            return self._token_buckets[token]

    def _get_or_create_tenant_bucket(
        self,
        tenant_id: str,
        config: RateLimitConfig,
    ) -> TokenBucket:
        """Get or create a tenant-based bucket with LRU eviction."""
        with self._lock:
            if tenant_id in self._tenant_buckets:
                self._tenant_buckets.move_to_end(tenant_id)
                return self._tenant_buckets[tenant_id]

            max_tenant_buckets = self.max_entries // 4
            while len(self._tenant_buckets) >= max_tenant_buckets:
                self._tenant_buckets.popitem(last=False)

            self._tenant_buckets[tenant_id] = TokenBucket(
                config.requests_per_minute,
                config.burst_size,
            )
            return self._tenant_buckets[tenant_id]

    def _get_or_create_endpoint_bucket(
        self,
        endpoint: str,
        key: str,
        config: RateLimitConfig,
    ) -> TokenBucket:
        """Get or create an endpoint-specific bucket with LRU eviction."""
        with self._lock:
            if endpoint not in self._endpoint_buckets:
                self._endpoint_buckets[endpoint] = OrderedDict()

            buckets = self._endpoint_buckets[endpoint]
            if key in buckets:
                buckets.move_to_end(key)
                return buckets[key]

            max_endpoint_buckets = self.max_entries // 4
            total_endpoint_entries = sum(len(b) for b in self._endpoint_buckets.values())
            while total_endpoint_entries >= max_endpoint_buckets and len(buckets) > 0:
                buckets.popitem(last=False)
                total_endpoint_entries -= 1

            buckets[key] = TokenBucket(
                config.requests_per_minute,
                config.burst_size,
            )
            return buckets[key]

    def _maybe_cleanup(self) -> None:
        """Periodic stats logging."""
        now = time.monotonic()
        if now - self._last_cleanup < self.cleanup_interval:
            return

        with self._lock:
            self._last_cleanup = now
            total = (
                len(self._ip_buckets)
                + len(self._token_buckets)
                + len(self._tenant_buckets)
                + sum(len(v) for v in self._endpoint_buckets.values())
            )

            if total > 0:
                logger.debug(
                    "Rate limiter stats: %s IP, %s token, %s tenant, %s endpoint buckets",
                    len(self._ip_buckets),
                    len(self._token_buckets),
                    len(self._tenant_buckets),
                    sum(len(v) for v in self._endpoint_buckets.values()),
                )

    def cleanup(self, max_age_seconds: int = 300) -> int:
        """
        Remove all stale entries older than max_age_seconds.

        This is more aggressive than _maybe_cleanup - it actually removes
        entries based on last activity time, not just LRU eviction.

        Args:
            max_age_seconds: Maximum age in seconds before entry is removed.

        Returns:
            Number of entries removed.
        """
        with self._lock:
            now = time.monotonic()
            removed = 0

            # For simplicity with token buckets that use monotonic time,
            # we can check last_refill against now
            for bucket_dict in [self._ip_buckets, self._token_buckets, self._tenant_buckets]:
                stale_keys = [
                    key
                    for key, bucket in bucket_dict.items()
                    if now - bucket.last_refill > max_age_seconds
                ]
                for key in stale_keys:
                    del bucket_dict[key]
                    removed += 1

            # Clean endpoint buckets
            for endpoint, buckets in list(self._endpoint_buckets.items()):
                stale_keys = [
                    key
                    for key, bucket in buckets.items()
                    if now - bucket.last_refill > max_age_seconds
                ]
                for key in stale_keys:
                    del buckets[key]
                    removed += 1

                # Remove empty endpoint dicts
                if not buckets:
                    del self._endpoint_buckets[endpoint]

            if removed > 0:
                logger.debug("Rate limiter cleanup removed %s stale entries", removed)

            return removed

    def reset(self) -> None:
        """Reset all rate limiter state. Primarily for testing."""
        with self._lock:
            self._ip_buckets.clear()
            self._token_buckets.clear()
            self._tenant_buckets.clear()
            self._endpoint_buckets.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics including observability metrics."""
        with self._lock:
            total_requests = self._requests_allowed + self._requests_rejected
            rejection_rate = self._requests_rejected / total_requests if total_requests > 0 else 0.0
            return {
                # Bucket counts
                "ip_buckets": len(self._ip_buckets),
                "token_buckets": len(self._token_buckets),
                "tenant_buckets": len(self._tenant_buckets),
                "endpoint_buckets": {
                    ep: len(buckets) for ep, buckets in self._endpoint_buckets.items()
                },
                # Configuration
                "configured_endpoints": list(self._endpoint_configs.keys()),
                "default_limit": self.default_limit,
                "ip_limit": self.ip_limit,
                # Observability metrics
                "requests_allowed": self._requests_allowed,
                "requests_rejected": self._requests_rejected,
                "total_requests": total_requests,
                "rejection_rate": rejection_rate,
                "rejections_by_endpoint": dict(self._rejections_by_endpoint),
            }

    def reset_metrics(self) -> None:
        """Reset observability metrics (useful for testing)."""
        with self._lock:
            self._requests_allowed = 0
            self._requests_rejected = 0
            self._rejections_by_endpoint.clear()

    def get_client_key(self, handler: Any) -> str:
        """
        Extract client key from request handler.

        Only trusts X-Forwarded-For when request comes from a trusted proxy
        (configured via ARAGORA_TRUSTED_PROXIES environment variable).
        Falls back to 'anonymous' if neither available.

        Args:
            handler: HTTP request handler.

        Returns:
            Client identifier string.
        """
        if handler is None:
            return "anonymous"

        # Get direct connection IP
        remote_ip = "anonymous"
        if hasattr(handler, "client_address"):
            addr = handler.client_address
            if isinstance(addr, tuple) and len(addr) >= 1:
                remote_ip = str(addr[0])

        headers = {}
        if hasattr(handler, "headers"):
            headers = {name: handler.headers.get(name, "") for name in CLIENT_IP_HEADERS}

        if remote_ip == "anonymous" and headers:
            forwarded = headers.get("X-Forwarded-For", "")
            if forwarded:
                candidate = str(forwarded).split(",")[0].strip()
                if candidate:
                    return sanitize_rate_limit_key_component(candidate)
            real_ip = headers.get("X-Real-IP", "")
            if real_ip:
                candidate = str(real_ip).strip()
                if candidate:
                    return sanitize_rate_limit_key_component(candidate)

        # Only trust XFF from configured trusted proxies
        client_ip = _extract_client_ip(headers, remote_ip)
        return sanitize_rate_limit_key_component(client_ip)


__all__ = [
    "RateLimitConfig",
    "RateLimitResult",
    "RateLimiter",
]
