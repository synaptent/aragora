"""
Tenant-based rate limiter implementation.

Provides per-tenant rate limiting to enforce fair usage across organizations
or workspaces.
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
    BURST_MULTIPLIER,
    DEFAULT_RATE_LIMIT,
    _extract_client_ip,
    sanitize_rate_limit_key_component,
)
from .bucket import TokenBucket
from .limiter import RateLimitResult

logger = logging.getLogger(__name__)


# Per-tenant rate limits (requests per minute)
DEFAULT_TENANT_RATE_LIMITS: dict[str, int] = {
    "default": DEFAULT_RATE_LIMIT,
}


@dataclass
class TenantRateLimitConfig:
    """Configuration for tenant rate limiting."""

    default_limit: int = DEFAULT_RATE_LIMIT
    default_burst: int | None = None
    max_tenants: int = 10000
    use_quota_manager: bool = True
    fallback_to_default: bool = True


class TenantRateLimiter:
    """
    Per-tenant rate limiter.

    Uses a token bucket per tenant. Supports optional TenantContext
    integration for automatic tenant resolution.
    """

    def __init__(
        self,
        action_limits: dict[str, int] | None = None,
        default_limit: int = DEFAULT_RATE_LIMIT,
        max_tenants: int = 10000,
        *,
        config: TenantRateLimitConfig | None = None,
        quota_manager: Any = None,
    ) -> None:
        if config is not None:
            self.config = config
            default_limit = config.default_limit
            max_tenants = config.max_tenants
        else:
            self.config = TenantRateLimitConfig(
                default_limit=default_limit,
                max_tenants=max_tenants,
            )
        self.action_limits = action_limits or DEFAULT_TENANT_RATE_LIMITS
        self.default_limit = default_limit
        self.max_tenants = max_tenants
        self._quota_manager = quota_manager

        # Flat tenant buckets: tenant_id -> TokenBucket
        self._tenant_buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

        # Stats tracking
        self._total_requests = 0
        self._total_rejections = 0
        self._requests_by_tenant: dict[str, int] = {}
        self._rejections_by_tenant: dict[str, int] = {}

    def get_action_limit(self, action: str) -> int:
        """Get rate limit for an action."""
        return self.action_limits.get(action, self.default_limit)

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics."""
        with self._lock:
            return {
                "total_requests": self._total_requests,
                "total_rejections": self._total_rejections,
                "tenant_count": len(self._tenant_buckets),
                "requests_by_tenant": dict(self._requests_by_tenant),
                "rejections_by_tenant": dict(self._rejections_by_tenant),
            }

    def get_tenant_stats(self, tenant_id: str) -> dict[str, Any]:
        """Get stats for a specific tenant."""
        with self._lock:
            bucket = self._tenant_buckets.get(tenant_id)
            return {
                "tenant_id": tenant_id,
                "rate_limit": self.default_limit,
                "burst_size": int(self.default_limit * BURST_MULTIPLIER)
                if self.config.default_burst is None
                else self.config.default_burst,
                "requests": self._requests_by_tenant.get(tenant_id, 0),
                "remaining": bucket.remaining if bucket else self.default_limit,
            }

    def allow(self, tenant_id: str | None = None, action: str = "default") -> RateLimitResult:
        """Check if tenant can perform action.

        If tenant_id is not provided, reads from TenantContext.
        """
        # Resolve tenant_id
        if tenant_id is None:
            tenant_id = self._resolve_tenant_from_context()

        # Sanitize tenant_id to prevent key injection
        if tenant_id:
            tenant_id = sanitize_rate_limit_key_component(tenant_id)

        if not tenant_id:
            if not self.config.fallback_to_default:
                return RateLimitResult(
                    allowed=True, remaining=0, limit=0, retry_after=0, key="no_tenant"
                )
            tenant_id = "default"

        limit = self.default_limit
        burst = (
            int(limit * BURST_MULTIPLIER)
            if self.config.default_burst is None
            else self.config.default_burst
        )

        # Consult QuotaManager for tenant-specific limits when available
        if (
            self.config.use_quota_manager
            and self._quota_manager is not None
            and tenant_id != "default"
        ):
            try:
                tenant_limits = self._quota_manager._get_limits_for_tenant(tenant_id)
                if tenant_limits and "api_requests" in tenant_limits:
                    api_limit = tenant_limits["api_requests"]
                    if hasattr(api_limit, "limit"):
                        limit = api_limit.limit
                    if hasattr(api_limit, "burst_limit") and api_limit.burst_limit:
                        burst = api_limit.burst_limit
                    else:
                        burst = int(limit * BURST_MULTIPLIER)
            except (ImportError, ValueError, TypeError, KeyError, RuntimeError) as e:
                logger.debug(
                    "QuotaManager lookup failed for tenant %s, using defaults: %s", tenant_id, e
                )

        with self._lock:
            self._total_requests += 1
            self._requests_by_tenant[tenant_id] = self._requests_by_tenant.get(tenant_id, 0) + 1

            if tenant_id in self._tenant_buckets:
                self._tenant_buckets.move_to_end(tenant_id)
                bucket = self._tenant_buckets[tenant_id]
            else:
                while len(self._tenant_buckets) >= self.max_tenants:
                    self._tenant_buckets.popitem(last=False)
                bucket = TokenBucket(limit, burst_size=burst)
                self._tenant_buckets[tenant_id] = bucket

        allowed = bucket.consume(1)

        if not allowed:
            with self._lock:
                self._total_rejections += 1
                self._rejections_by_tenant[tenant_id] = (
                    self._rejections_by_tenant.get(tenant_id, 0) + 1
                )

        key = f"tenant:{tenant_id}" if tenant_id != "default" else "default"

        return RateLimitResult(
            allowed=allowed,
            remaining=bucket.remaining,
            limit=limit,
            retry_after=bucket.get_retry_after() if not allowed else 0,
            key=key,
        )

    def _resolve_tenant_from_context(self) -> str | None:
        """Read tenant ID from TenantContext if available."""
        try:
            from aragora.tenancy.context import get_current_tenant_id

            return get_current_tenant_id()
        except ImportError:
            return None

    def reset_tenant(self, tenant_id: str) -> None:
        """Reset rate limit state for a specific tenant."""
        with self._lock:
            self._tenant_buckets.pop(tenant_id, None)
            self._requests_by_tenant.pop(tenant_id, None)
            self._rejections_by_tenant.pop(tenant_id, None)

    def cleanup(self, max_age_seconds: int = 600) -> int:
        """Remove stale tenant entries."""
        with self._lock:
            now = time.monotonic()
            stale = [
                tenant
                for tenant, bucket in self._tenant_buckets.items()
                if now - bucket.last_refill > max_age_seconds
            ]
            for tenant in stale:
                del self._tenant_buckets[tenant]
            return len(stale)

    def reset(self) -> None:
        """Reset all tenant rate limiter state."""
        with self._lock:
            self._tenant_buckets.clear()
            self._total_requests = 0
            self._total_rejections = 0
            self._requests_by_tenant.clear()
            self._rejections_by_tenant.clear()


_tenant_limiter: TenantRateLimiter | None = None


def get_tenant_rate_limiter() -> TenantRateLimiter:
    """Get the global tenant rate limiter instance."""
    global _tenant_limiter
    if _tenant_limiter is None:
        _tenant_limiter = TenantRateLimiter()
    return _tenant_limiter


def reset_tenant_rate_limiter() -> None:
    """Reset the global tenant rate limiter."""
    global _tenant_limiter
    _tenant_limiter = None


def _extract_tenant_id(handler: Any) -> str:
    auth_ctx = getattr(handler, "_auth_context", None)
    tenant = None
    if auth_ctx is not None:
        tenant = getattr(auth_ctx, "org_id", None) or getattr(auth_ctx, "workspace_id", None)

    headers = getattr(handler, "headers", None)
    if headers and tenant is None:
        tenant = headers.get("X-Tenant-ID") or headers.get("X-Workspace-ID")

    if tenant:
        return sanitize_rate_limit_key_component(str(tenant))

    # Fall back to IP-based key when tenant context is absent
    remote_ip = "anonymous"
    if hasattr(handler, "client_address"):
        addr = handler.client_address
        if isinstance(addr, tuple) and len(addr) >= 1:
            remote_ip = str(addr[0])

    headers = {}
    if hasattr(handler, "headers"):
        headers = {name: handler.headers.get(name, "") for name in CLIENT_IP_HEADERS}

    return sanitize_rate_limit_key_component(_extract_client_ip(headers, remote_ip))


def check_tenant_rate_limit(
    handler: Any = None,
    action: str = "default",
    *,
    tenant_id: str | None = None,
) -> RateLimitResult:
    """Check tenant rate limit.

    Can be called with:
    - handler: Extract tenant from request handler
    - tenant_id: Use explicit tenant ID
    - Neither: Read from TenantContext
    """
    limiter = get_tenant_rate_limiter()
    if tenant_id is not None:
        resolved_id = sanitize_rate_limit_key_component(tenant_id)
    elif handler is not None:
        resolved_id = _extract_tenant_id(handler)
    else:
        # Read from TenantContext
        try:
            from aragora.tenancy.context import get_current_tenant_id

            tid = get_current_tenant_id()
            resolved_id = sanitize_rate_limit_key_component(tid or "anonymous")
        except ImportError:
            resolved_id = "anonymous"
    return limiter.allow(resolved_id, action)


__all__ = [
    "DEFAULT_TENANT_RATE_LIMITS",
    "TenantRateLimiter",
    "TenantRateLimitConfig",
    "get_tenant_rate_limiter",
    "reset_tenant_rate_limiter",
    "check_tenant_rate_limit",
]
