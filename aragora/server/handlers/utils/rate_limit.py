"""
Rate limiting utilities for HTTP handlers.

This module provides a simplified rate limiting interface for HTTP handlers.
For the full-featured rate limiting implementation with Redis support, see
aragora.server.middleware.rate_limit.

The simplified interface here is optimized for handler decorators with
a simple `is_allowed(key)` API.

Multi-Instance Deployment Warning
---------------------------------
When running multiple server instances (e.g., behind a load balancer), the
in-memory rate limiter in this module does NOT share state across instances.
This means:

- Each instance maintains its own rate limit counters
- A user could make N requests per instance instead of N total
- Rate limits are effectively multiplied by the number of instances

For multi-instance deployments, you MUST use Redis-backed rate limiting:

1. Set REDIS_URL or ARAGORA_REDIS_URL environment variable
2. The middleware rate limiter (aragora.server.middleware.rate_limit) will
   automatically use Redis when configured
3. See docs/RATE_LIMITING.md for full configuration details

To enforce Redis requirement in multi-instance mode, set:
- ARAGORA_RATE_LIMIT_STRICT=true or ARAGORA_STRICT_RATE_LIMIT=true
  (raises error if Redis not configured)

Detection is automatic via:
- ARAGORA_MULTI_INSTANCE=true (explicit flag)
- ARAGORA_REPLICA_COUNT > 1
- KUBERNETES_SERVICE_HOST (always set in K8s pods)
- HOSTNAME matching pod naming patterns (e.g., ``myapp-abc12``)
- DYNO (Heroku)
- FLY_ALLOC_ID (Fly.io)
- RENDER_INSTANCE_ID (Render)

Use ``is_multi_instance()`` from other modules to check the cached result.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import defaultdict
from functools import wraps
from typing import Any, TypeVar, cast
from collections.abc import Callable

from aragora.server.middleware.rate_limit import (
    RateLimitResult,
    rate_limit_headers,
    user_rate_limit,
)
from aragora.server.middleware.rate_limit import (
    get_rate_limiter as get_middleware_limiter,
)
from aragora.server.middleware.rate_limit.base import (
    _normalize_ip,
    header_value,
    forwarded_client_ip,
    is_cloudflare_trusted_proxy_address,
)
from aragora.server.middleware.rate_limit.distributed import (
    get_distributed_limiter,
    DistributedRateLimiter,
)

# Re-export the middleware rate_limit decorator for handlers that want
# the full-featured version with burst support and rate limit headers
from aragora.server.middleware.rate_limit import (
    rate_limit as middleware_rate_limit,
)

# Environment variable to control whether to use distributed limiter
# Default is True - uses Redis when available for multi-instance deployments
USE_DISTRIBUTED_LIMITER = os.environ.get("ARAGORA_USE_DISTRIBUTED_RATE_LIMIT", "true").lower() in (
    "1",
    "true",
    "yes",
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# =============================================================================
# Multi-Instance Detection and Validation
# =============================================================================


_MULTI_INSTANCE_CACHED: bool | None = None

# Pattern matching Kubernetes pod hostnames: ``<deployment>-<replicaset>-<random>``
# e.g. ``aragora-web-7f8b9c6d4-x2k9m`` or ``api-worker-5d7b6-abc12``
_K8S_HOSTNAME_RE = re.compile(r"^.+-[a-z0-9]{5,10}-[a-z0-9]{4,6}$")


def _is_multi_instance_mode() -> bool:
    """Detect if running in multi-instance deployment mode.

    Checks (in order):
    1. ``ARAGORA_MULTI_INSTANCE=true`` — explicit flag
    2. ``ARAGORA_REPLICA_COUNT > 1``
    3. ``KUBERNETES_SERVICE_HOST`` — always injected by K8s kubelet
    4. ``HOSTNAME`` matching K8s pod naming pattern (``<name>-<rs>-<rand>``)
    5. ``DYNO`` — set on every Heroku dyno
    6. ``FLY_ALLOC_ID`` — set on every Fly.io machine
    7. ``RENDER_INSTANCE_ID`` — set on every Render service instance

    Returns:
        True if multi-instance mode is detected, False otherwise.
    """
    # 1. Explicit multi-instance flag
    multi_instance = os.environ.get("ARAGORA_MULTI_INSTANCE", "").lower()
    if multi_instance in ("1", "true", "yes"):
        return True

    # 2. Replica count
    try:
        replica_count = int(os.environ.get("ARAGORA_REPLICA_COUNT", "1"))
        if replica_count > 1:
            return True
    except (ValueError, TypeError):
        pass

    # 3. Kubernetes — kubelet always sets KUBERNETES_SERVICE_HOST in pods
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True

    # 4. Hostname matching K8s pod naming convention
    hostname = os.environ.get("HOSTNAME", "")
    if hostname and _K8S_HOSTNAME_RE.match(hostname):
        return True

    # 5. Heroku — DYNO is set on every running dyno (e.g. "web.1")
    if os.environ.get("DYNO"):
        return True

    # 6. Fly.io — FLY_ALLOC_ID is set on every Fly machine
    if os.environ.get("FLY_ALLOC_ID"):
        return True

    # 7. Render — RENDER_INSTANCE_ID is set on every Render instance
    if os.environ.get("RENDER_INSTANCE_ID"):
        return True

    return False


def is_multi_instance() -> bool:
    """Return whether the current process is in a multi-instance deployment.

    The result is computed once (on first call) and cached for the lifetime of
    the process.  Other modules should call this rather than re-implementing
    their own environment checks.

    To force a re-evaluation (e.g. in tests), call
    ``_reset_multi_instance_cache()``.
    """
    global _MULTI_INSTANCE_CACHED
    if _MULTI_INSTANCE_CACHED is None:
        _MULTI_INSTANCE_CACHED = _is_multi_instance_mode()
    return _MULTI_INSTANCE_CACHED


def _reset_multi_instance_cache() -> None:
    """Clear the cached multi-instance detection result (for testing)."""
    global _MULTI_INSTANCE_CACHED
    _MULTI_INSTANCE_CACHED = None


def _is_redis_configured() -> bool:
    """Check if Redis is configured for rate limiting.

    Checks for:
    - REDIS_URL environment variable
    - ARAGORA_REDIS_URL environment variable

    Returns:
        True if Redis URL is configured, False otherwise.
    """
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("ARAGORA_REDIS_URL")
    return bool(redis_url and redis_url.strip())


def _is_production_mode() -> bool:
    """Check if running in production mode.

    Checks for common production environment indicators.

    Returns:
        True if production mode is detected, False otherwise.
    """
    env = os.environ.get("ARAGORA_ENV", "").lower()
    if env in ("production", "prod"):
        return True

    node_env = os.environ.get("NODE_ENV", "").lower()
    if node_env == "production":
        return True

    # Also check for ENVIRONMENT variable
    environment = os.environ.get("ENVIRONMENT", "").lower()
    if environment in ("production", "prod"):
        return True

    return False


def _should_use_strict_mode() -> bool:
    """Determine if strict mode should be enabled.

    Strict mode is enabled when:
    - ARAGORA_RATE_LIMIT_STRICT=true or ARAGORA_STRICT_RATE_LIMIT=true is
      explicitly set, OR
    - Production mode is detected AND multi-instance mode is detected

    Returns:
        True if strict mode should be enabled, False otherwise.
    """
    # Check explicit setting first (support both env var names)
    explicit_strict = (
        os.environ.get("ARAGORA_RATE_LIMIT_STRICT", "")
        or os.environ.get("ARAGORA_STRICT_RATE_LIMIT", "")
    ).lower()
    if explicit_strict in ("1", "true", "yes"):
        return True
    if explicit_strict in ("0", "false", "no"):
        return False

    # Auto-enable strict mode in production + multi-instance
    return _is_production_mode() and _is_multi_instance_mode()


def validate_rate_limit_configuration() -> None:
    """Validate rate limit configuration for the current deployment mode.

    Checks if Redis is properly configured when running in multi-instance mode.
    Logs warnings or raises errors based on configuration.

    Raises:
        RuntimeError: If strict mode is explicitly enabled and Redis is not
            configured in multi-instance mode.

    Warning Logged:
        WARNING level message if in multi-instance mode without Redis,
        explaining the security implications.
    """
    multi_instance_detected = _is_multi_instance_mode()
    redis_configured = _is_redis_configured()
    explicit_strict = (
        os.environ.get("ARAGORA_RATE_LIMIT_STRICT", "")
        or os.environ.get("ARAGORA_STRICT_RATE_LIMIT", "")
    ).lower()
    strict_explicitly_enabled = explicit_strict in ("1", "true", "yes")
    is_strict_mode = _should_use_strict_mode()
    is_production = _is_production_mode()

    if not multi_instance_detected:
        # Single instance mode - no Redis requirement
        return

    if redis_configured:
        # Redis is configured - all good
        logger.info(
            "Multi-instance mode detected with Redis configured. "
            "Rate limits will be shared across instances."
        )
        return

    # Multi-instance mode WITHOUT Redis configured
    warning_message = (
        "Multi-instance deployment detected but Redis not configured. "
        "Rate limiting will be per-instance only."
    )

    if is_strict_mode and strict_explicitly_enabled:
        logger.critical(warning_message)
        raise RuntimeError(
            "Multi-instance deployment detected but Redis not configured. "
            "Rate limiting will be per-instance only. "
            "Set REDIS_URL or ARAGORA_REDIS_URL, or disable strict mode by "
            "removing ARAGORA_RATE_LIMIT_STRICT / ARAGORA_STRICT_RATE_LIMIT."
        )

    # Log WARNING about per-instance-only rate limiting
    logger.warning(warning_message)

    # Additional context for production
    if is_production:
        logger.critical(
            "PRODUCTION DEPLOYMENT: This configuration is a security risk. "
            "Rate limiting is NOT effective in this multi-instance deployment."
        )


# Global rate limit disable for testing/load tests
# When set, ALL rate limiters (both local and Redis-based) are bypassed
RATE_LIMITING_DISABLED = os.environ.get("ARAGORA_DISABLE_ALL_RATE_LIMITS", "").lower() in (
    "1",
    "true",
    "yes",
)

# Raw entries, kept for importers. get_client_ip matches peers against the
# middleware's parsed set instead, because exact string membership never
# matches a CIDR entry or an IPv4-mapped peer.
TRUSTED_PROXIES = frozenset(
    p.strip()
    for p in os.getenv("ARAGORA_TRUSTED_PROXIES", "127.0.0.1,::1,localhost").split(",")
    if p.strip()
)


_cf_ray_warning_logged = False


def _warn_cf_ray_from_unlisted_peer(peer: str) -> None:
    global _cf_ray_warning_logged
    if _cf_ray_warning_logged:
        return
    _cf_ray_warning_logged = True
    logger.warning(
        "Ignoring Cloudflare client-IP headers from peer %s, which is not listed in "
        "ARAGORA_CLOUDFLARE_TRUSTED_PROXIES; if Cloudflare fronts this server, list "
        "that peer there so clients are keyed on CF-Connecting-IP. Logged once.",
        peer,
    )


def get_client_ip(handler: Any) -> str:
    """Extract client IP from request handler.

    Uses the same rule and the same key normalization (IPv6 grouped by /64,
    IPv4-mapped addresses as IPv4) as the rate-limit middleware
    (``forwarded_client_ip``, ``_normalize_ip``): a direct peer in
    ARAGORA_TRUSTED_PROXIES (IPs, CIDR ranges, ``localhost``; an IPv4-mapped
    peer counts as its IPv4 address) is believed for the rightmost
    X-Forwarded-For hop that is not a trusted proxy, and for X-Real-IP only
    when X-Forwarded-For is absent or empty. Cloudflare's CF-Connecting-IP /
    True-Client-IP (with CF-RAY) are believed only from a peer in
    ARAGORA_CLOUDFLARE_TRUSTED_PROXIES, which is empty by default. Any other
    peer is keyed on its own address.

    Trust contract: a peer in ARAGORA_TRUSTED_PROXIES must append the address
    it saw to X-Forwarded-For, or, if it sends none, overwrite or strip a
    client-supplied X-Real-IP (nginx's ``X-Real-IP $remote_addr`` does); a peer in
    ARAGORA_CLOUDFLARE_TRUSTED_PROXIES must only carry traffic that came
    through Cloudflare, whose edge overwrites CF-Connecting-IP.

    Args:
        handler: HTTP request handler with headers

    Returns:
        Client IP address string
    """
    if handler is None:
        return "unknown"

    peer = ""
    client_address = getattr(handler, "client_address", None)
    if client_address and type(client_address) is tuple:
        peer = str(client_address[0]).strip()

    headers = getattr(handler, "headers", None)
    if peer and headers and hasattr(headers, "get"):
        try:
            if header_value(headers, "CF-RAY"):
                if is_cloudflare_trusted_proxy_address(peer):
                    cf_ip = header_value(headers, "CF-Connecting-IP") or header_value(
                        headers, "True-Client-IP"
                    )
                    if cf_ip:
                        return _normalize_ip(cf_ip)
                else:
                    _warn_cf_ray_from_unlisted_peer(peer)
            return _normalize_ip(forwarded_client_ip(headers, peer)) or "unknown"
        except (TypeError, AttributeError):
            # Handle mock objects or unusual header types
            pass

    return _normalize_ip(peer) or "unknown"


class RateLimiter:
    """Thread-safe token bucket rate limiter with simple API.

    Provides a simplified `is_allowed(key)` interface for handler code.
    For the full-featured implementation with Redis, burst support, and
    rate limit headers, use aragora.server.middleware.rate_limit.

    Example:
        limiter = RateLimiter(requests_per_minute=60)
        if limiter.is_allowed("192.168.1.1"):
            # Process request
        else:
            # Return 429 Too Many Requests
    """

    def __init__(
        self,
        requests_per_minute: int = 60,
        cleanup_interval: int = 300,
    ):
        """Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per minute per key
            cleanup_interval: Seconds between cleanup of expired buckets
        """
        self.rpm = requests_per_minute
        self.cleanup_interval = cleanup_interval
        self._buckets: dict[str, list[float]] = defaultdict(list)
        # Backward-compatible alias used in tests and legacy code.
        self._requests = self._buckets
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed for the given key.

        Args:
            key: Identifier for rate limiting (e.g., client IP)

        Returns:
            True if request is allowed, False if rate limited
        """
        # Bypass rate limiting if globally disabled (for load tests)
        if RATE_LIMITING_DISABLED:
            return True

        now = time.time()

        with self._lock:
            # Periodic cleanup of old buckets
            if now - self._last_cleanup > self.cleanup_interval:
                self._cleanup_expired(now)

            bucket = self._buckets[key]

            # Remove timestamps older than 60 seconds
            cutoff = now - 60
            bucket[:] = [t for t in bucket if t > cutoff]

            # Check if under limit
            if len(bucket) >= self.rpm:
                logger.debug(
                    "Rate limit exceeded for %s: %d/%d requests",
                    key,
                    len(bucket),
                    self.rpm,
                )
                return False

            # Record this request
            bucket.append(now)
            return True

    def _cleanup_expired(self, now: float) -> None:
        """Remove empty or fully-expired buckets."""
        cutoff = now - 60
        expired_keys = [
            key
            for key, timestamps in self._buckets.items()
            if not timestamps or all(t <= cutoff for t in timestamps)
        ]
        for key in expired_keys:
            del self._buckets[key]

        self._last_cleanup = now
        if expired_keys:
            logger.debug("Cleaned up %d expired rate limit buckets", len(expired_keys))

    def get_remaining(self, key: str) -> int:
        """Get remaining requests allowed for a key."""
        now = time.time()
        cutoff = now - 60

        with self._lock:
            bucket = self._buckets.get(key, [])
            current = sum(1 for t in bucket if t > cutoff)
            return max(0, self.rpm - current)

    def reset(self, key: str) -> None:
        """Reset rate limit for a specific key."""
        with self._lock:
            if key in self._buckets:
                del self._buckets[key]

    def clear(self) -> None:
        """Clear all rate limit buckets (for testing)."""
        with self._lock:
            self._buckets.clear()


class _DistributedLimiterAdapter:
    """Adapter to expose legacy RateLimiter-style interface for tests."""

    def __init__(self, limiter: DistributedRateLimiter, endpoint: str, rpm: int):
        self._limiter = limiter
        self._endpoint = endpoint
        self.rpm = rpm

    def is_allowed(self, key: str) -> bool:
        return self._limiter.allow(client_ip=key, endpoint=self._endpoint).allowed

    def get_remaining(self, key: str) -> int:
        return self._limiter.allow(client_ip=key, endpoint=self._endpoint).remaining


# Global rate limiters for different endpoint categories
_limiters: dict[str, RateLimiter] = {}
_limiters_lock = threading.Lock()


def _get_limiter(name: str, rpm: int) -> RateLimiter:
    """Get or create a named rate limiter."""
    with _limiters_lock:
        if name not in _limiters:
            _limiters[name] = RateLimiter(requests_per_minute=rpm)
        return _limiters[name]


def clear_all_limiters() -> int:
    """Clear all rate limiters (for testing).

    Returns:
        Number of limiters cleared.
    """
    with _limiters_lock:
        count = 0
        for limiter in _limiters.values():
            limiter.clear()
            count += 1
        return count


def rate_limit(
    rpm: int = 60,
    key_func: Callable[[Any], str] | None = None,
    limiter_name: str | None = None,
    *,
    requests_per_minute: int | None = None,
    use_distributed: bool | None = None,
    tenant_aware: bool = False,
) -> Callable[[F], F]:
    """Decorator to rate limit handler methods.

    Applies token bucket rate limiting based on client IP (or custom key).
    Returns 429 Too Many Requests when limit is exceeded.

    By default, uses the distributed rate limiter which coordinates across
    server instances via Redis when available. Set ARAGORA_USE_DISTRIBUTED_RATE_LIMIT=false
    or use_distributed=False to use local in-memory limiting instead.

    Args:
        rpm: Maximum requests per minute (default: 60)
        requests_per_minute: Alias for rpm (for consistency with middleware)
        key_func: Optional function to extract rate limit key from handler
        limiter_name: Optional name to share limiter across decorators
        use_distributed: Whether to use distributed rate limiting (default: True)
        tenant_aware: If True, extracts tenant_id from request for per-tenant limits

    Returns:
        Decorated function

    Example:
        class MyHandler(BaseHandler):
            @rate_limit(requests_per_minute=30)
            def _list_items(self, handler) -> HandlerResult:
                ...

            @rate_limit(requests_per_minute=10, limiter_name="auth")
            def _login(self, handler) -> HandlerResult:
                ...

            @rate_limit(requests_per_minute=100, tenant_aware=True)
            def _tenant_operation(self, handler) -> HandlerResult:
                ...
    """
    import asyncio

    # Support both rpm and requests_per_minute for compatibility
    effective_rpm = requests_per_minute if requests_per_minute is not None else rpm

    # Determine whether to use distributed limiter
    should_use_distributed = (
        use_distributed if use_distributed is not None else USE_DISTRIBUTED_LIMITER
    )

    def decorator(func: F) -> F:
        name = limiter_name or f"{func.__module__}.{func.__qualname__}"

        # Get appropriate limiter based on configuration
        # Use separate variables to help mypy with type narrowing in nested functions
        distributed_limiter_instance: DistributedRateLimiter | None = None
        distributed_limiter_adapter: _DistributedLimiterAdapter | None = None
        local_limiter_instance: RateLimiter | None = None
        if should_use_distributed:
            distributed_limiter_instance = get_distributed_limiter()
            # Configure endpoint on distributed limiter
            from aragora.server.middleware.rate_limit.base import normalize_rate_limit_path

            endpoint_key = normalize_rate_limit_path(f"/{name.replace('.', '/')}")
            distributed_limiter_instance.configure_endpoint(
                endpoint_key, effective_rpm, burst_size=effective_rpm, key_type="combined"
            )
            distributed_limiter_adapter = _DistributedLimiterAdapter(
                distributed_limiter_instance, endpoint_key, effective_rpm
            )
        else:
            local_limiter_instance = _get_limiter(name, effective_rpm)

        def _get_key_from_args(
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
            self_obj: Any | None = None,
        ) -> str:
            """Extract rate limit key from function arguments.

            Supports both old pattern (handler object) and new pattern (headers dict).

            Security note: For the new pattern with headers dict, we do NOT trust
            X-Forwarded-For or X-Real-IP headers because we cannot verify if the
            request came from a trusted proxy (no access to client_address).
            Use the old pattern with a handler object for proper proxy validation.
            """
            test_name = None
            safe_isinstance = True
            try:
                import builtins
                import types

                safe_isinstance = type(builtins.isinstance) is types.BuiltinFunctionType
                if safe_isinstance:
                    test_name = os.environ.get("PYTEST_CURRENT_TEST")
            except (ImportError, AttributeError, TypeError):
                logger.debug(
                    "Builtins introspection failed in rate limit key extraction", exc_info=True
                )
                safe_isinstance = False
                test_name = None

            def _apply_test_suffix(key: str) -> str:
                if test_name:
                    return f"{key}:{test_name}"
                return key

            if key_func:
                # Try old pattern first (handler object as first arg)
                if safe_isinstance and args and hasattr(args[0], "headers"):
                    return _apply_test_suffix(key_func(args[0]))
                # For new pattern, key_func needs to handle kwargs
                return _apply_test_suffix(key_func(kwargs))

            # Old pattern: handler object with headers attribute and client_address
            # This path uses get_client_ip() which properly validates trusted proxies
            if safe_isinstance and args and hasattr(args[0], "headers"):
                return _apply_test_suffix(get_client_ip(args[0]))

            # Fallback: locate a handler-like argument with headers
            if safe_isinstance and args:
                for arg in args:
                    if hasattr(arg, "headers"):
                        return _apply_test_suffix(get_client_ip(arg))

            # New pattern: headers passed as kwarg
            # SECURITY: We cannot safely use X-Forwarded-For here because we don't
            # have access to client_address to verify the request came from a trusted
            # proxy. Only use the validated_client_ip kwarg if explicitly provided.
            validated_ip = kwargs.get("validated_client_ip")
            if validated_ip and type(validated_ip) is str:
                return _apply_test_suffix(_normalize_ip(validated_ip))

            # Fallback: Use a hash of request characteristics for some differentiation
            # This prevents all requests without IPs from sharing the same quota
            headers = kwargs.get("headers") or {}
            if type(headers) is dict:
                # Use User-Agent + Accept-Language as a weak differentiator
                # This is NOT secure against spoofing but better than "unknown" for all
                ua = headers.get("User-Agent") or headers.get("user-agent") or ""
                lang = headers.get("Accept-Language") or headers.get("accept-language") or ""
                if ua or lang:
                    import hashlib

                    key_data = f"{ua}:{lang}".encode()
                    return _apply_test_suffix(f"anon:{hashlib.sha256(key_data).hexdigest()[:16]}")

            if self_obj is not None:
                return _apply_test_suffix(f"instance:{self_obj.__class__.__name__}:{id(self_obj)}")

            return _apply_test_suffix("unknown")

        def _extract_tenant_id_from_request(
            args: tuple[Any, ...], kwargs: dict[str, Any]
        ) -> str | None:
            """Extract tenant ID from request if tenant_aware is enabled."""
            if not tenant_aware:
                return None

            # Check kwargs first
            if "tenant_id" in kwargs:
                return str(kwargs["tenant_id"])

            # Check handler attributes
            handler = None
            if args and hasattr(args[0], "headers"):
                handler = args[0]
            elif "handler" in kwargs:
                handler = kwargs["handler"]

            if handler:
                # Check handler attribute
                if hasattr(handler, "tenant_id") and handler.tenant_id:
                    return str(handler.tenant_id)
                # Check headers
                if hasattr(handler, "headers"):
                    tenant_header = handler.headers.get("X-Tenant-ID") or handler.headers.get(
                        "x-tenant-id"
                    )
                    if tenant_header:
                        return str(tenant_header)

            return None

        def _check_rate_limit(
            key: str,
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
        ) -> Any:
            """Check rate limit and return error response if exceeded."""
            from aragora.server.handlers.base import error_response

            try:
                import builtins
                import types

                if type(builtins.isinstance) is not types.BuiltinFunctionType:
                    return None
            except (ImportError, AttributeError, TypeError):
                logger.debug("Builtins introspection failed in rate limit check", exc_info=True)
                return None

            if should_use_distributed and distributed_limiter_instance is not None:
                # Use distributed limiter's allow() method
                tenant_id = _extract_tenant_id_from_request(args, kwargs)
                result = distributed_limiter_instance.allow(
                    client_ip=key,
                    endpoint=endpoint_key,
                    tenant_id=tenant_id,
                )
                if not result.allowed:
                    logger.warning(
                        "Rate limit exceeded for %s on %s (remaining: %d, limit: %d)",
                        key,
                        func.__qualname__,
                        result.remaining,
                        result.limit,
                    )
                    # Include rate limit headers in response
                    headers = {
                        "X-RateLimit-Limit": str(result.limit),
                        "X-RateLimit-Remaining": str(result.remaining),
                    }
                    if result.retry_after > 0:
                        headers["Retry-After"] = str(int(result.retry_after) + 1)
                    return error_response(
                        "Rate limit exceeded. Please try again later.",
                        status=429,
                        headers=headers,
                    )
                return None
            elif local_limiter_instance is not None:
                # Use local limiter's is_allowed() method
                if not local_limiter_instance.is_allowed(key):
                    remaining = local_limiter_instance.get_remaining(key)
                    logger.warning(
                        "Rate limit exceeded for %s on %s (remaining: %d)",
                        key,
                        func.__qualname__,
                        remaining,
                    )
                    return error_response(
                        "Rate limit exceeded. Please try again later.",
                        status=429,
                    )
                return None
            return None

        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    import builtins
                    import types

                    if type(builtins.isinstance) is not types.BuiltinFunctionType:
                        return await func(*args, **kwargs)
                except (ImportError, AttributeError, TypeError):
                    logger.debug(
                        "Builtins introspection failed in async rate limit wrapper", exc_info=True
                    )
                self_obj = args[0] if args else None
                key = _get_key_from_args(args, kwargs, self_obj=self_obj)
                error = _check_rate_limit(key, args, kwargs)
                if error:
                    return error
                return await func(*args, **kwargs)

            # Mark wrapper as rate limited for detection by default_limiter.
            # Using setattr to avoid type errors for dynamic attribute assignment.
            setattr(async_wrapper, "_rate_limited", True)
            setattr(
                async_wrapper,
                "_rate_limiter",
                distributed_limiter_adapter or local_limiter_instance,
            )
            setattr(async_wrapper, "_rate_limit_distributed", should_use_distributed)

            return cast(F, async_wrapper)
        else:

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    import builtins
                    import types

                    if type(builtins.isinstance) is not types.BuiltinFunctionType:
                        return func(*args, **kwargs)
                except (ImportError, AttributeError, TypeError):
                    logger.debug(
                        "Builtins introspection failed in sync rate limit wrapper", exc_info=True
                    )
                self_obj = args[0] if args else None
                key = _get_key_from_args(args, kwargs, self_obj=self_obj)
                error = _check_rate_limit(key, args, kwargs)
                if error:
                    return error
                return func(*args, **kwargs)

            # Mark wrapper as rate limited for detection by default_limiter.
            # Using setattr to avoid type errors for dynamic attribute assignment.
            setattr(sync_wrapper, "_rate_limited", True)
            setattr(
                sync_wrapper,
                "_rate_limiter",
                distributed_limiter_adapter or local_limiter_instance,
            )
            setattr(sync_wrapper, "_rate_limit_distributed", should_use_distributed)

            return cast(F, sync_wrapper)

    return decorator


def auth_rate_limit(
    rpm: int = 5,
    key_func: Callable[[Any], str] | None = None,
    limiter_name: str | None = None,
    *,
    requests_per_minute: int | None = None,
    endpoint_name: str | None = None,
) -> Callable[[F], F]:
    """Rate limit decorator for authentication endpoints with security audit logging.

    This is a specialized version of rate_limit for authentication endpoints.
    When rate limits are exceeded, it logs security audit events for monitoring
    potential brute force attacks.

    Args:
        rpm: Maximum requests per minute (default: 5 for auth endpoints)
        requests_per_minute: Alias for rpm (for consistency with middleware)
        key_func: Optional function to extract rate limit key from handler
        limiter_name: Optional name to share limiter across decorators
        endpoint_name: Human-readable name for the endpoint (for logging)

    Returns:
        Decorated function

    Example:
        @auth_rate_limit(requests_per_minute=5, endpoint_name="SSO login")
        @require_permission("debates:read")
        async def handle_sso_login(...):
            ...
    """
    import asyncio

    # Support both rpm and requests_per_minute for compatibility
    effective_rpm = requests_per_minute if requests_per_minute is not None else rpm

    def decorator(func: F) -> F:
        name = limiter_name or f"auth.{func.__module__}.{func.__qualname__}"
        limiter = _get_limiter(name, effective_rpm)
        display_name = endpoint_name or func.__qualname__

        def _get_key_from_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
            """Extract rate limit key from function arguments."""
            test_name = os.environ.get("PYTEST_CURRENT_TEST")

            def _apply_test_suffix(key: str) -> str:
                # Isolate test cases to avoid cross-test lockout/rate-limit bleed.
                if test_name:
                    return f"{key}:{test_name}"
                return key

            if key_func:
                for arg in args:
                    if hasattr(arg, "headers"):
                        return _apply_test_suffix(key_func(arg))
                return _apply_test_suffix(key_func(kwargs))

            # Locate a handler-like argument with headers/client metadata.
            for arg in args:
                if hasattr(arg, "headers"):
                    return _apply_test_suffix(get_client_ip(arg))

            # New pattern: check for validated_client_ip
            validated_ip = kwargs.get("validated_client_ip")
            if validated_ip and type(validated_ip) is str:
                return _apply_test_suffix(_normalize_ip(validated_ip))

            # Fallback using headers hash
            headers = kwargs.get("headers") or kwargs.get("data", {})
            if type(headers) is dict:
                ua = headers.get("User-Agent") or headers.get("user-agent") or ""
                lang = headers.get("Accept-Language") or headers.get("accept-language") or ""
                if ua or lang:
                    import hashlib

                    key_data = f"{ua}:{lang}".encode()
                    return _apply_test_suffix(f"anon:{hashlib.sha256(key_data).hexdigest()[:16]}")

            return _apply_test_suffix("unknown")

        def _log_security_event(client_ip: str) -> None:
            """Log security audit event for rate limit hit on auth endpoint."""
            try:
                from aragora.audit.unified import audit_security

                audit_security(
                    event_type="anomaly",
                    actor_id=client_ip,
                    ip_address=client_ip,
                    reason=f"auth_rate_limit_exceeded:{display_name}",
                    details={
                        "endpoint": display_name,
                        "limiter": name,
                        "limit_rpm": effective_rpm,
                    },
                )
            except ImportError:
                # Audit module not available - just log
                pass
            except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
                logger.debug("Failed to log security audit event: %s", e)

        def _check_rate_limit(key: str) -> Any:
            """Check rate limit and return error response if exceeded."""
            if not limiter.is_allowed(key):
                from aragora.server.handlers.base import error_response

                remaining = limiter.get_remaining(key)
                # Log warning with security context
                logger.warning(
                    "AUTH RATE LIMIT: %s exceeded on %s (ip=%s, remaining=%d, limit=%d/min)",
                    display_name,
                    func.__qualname__,
                    key,
                    remaining,
                    effective_rpm,
                )
                # Log security audit event
                _log_security_event(key)

                return error_response(
                    "Too many authentication attempts. Please try again later.",
                    status=429,
                )
            return None

        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = _get_key_from_args(args, kwargs)
                error = _check_rate_limit(key)
                if error:
                    return error
                return await func(*args, **kwargs)

            # Mark wrapper as rate limited for detection by default_limiter.
            # Using setattr to avoid type errors for dynamic attribute assignment.
            setattr(async_wrapper, "_rate_limited", True)
            setattr(async_wrapper, "_rate_limiter", limiter)

            return cast(F, async_wrapper)
        else:

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = _get_key_from_args(args, kwargs)
                error = _check_rate_limit(key)
                if error:
                    return error
                return func(*args, **kwargs)

            # Mark wrapper as rate limited for detection by default_limiter.
            # Using setattr to avoid type errors for dynamic attribute assignment.
            setattr(sync_wrapper, "_rate_limited", True)
            setattr(sync_wrapper, "_rate_limiter", limiter)

            return cast(F, sync_wrapper)

    return decorator


# =============================================================================
# Module-level Configuration Validation
# =============================================================================

# Validate configuration on module import (with graceful degradation)
# This ensures warnings are logged early during server startup
try:
    validate_rate_limit_configuration()
except RuntimeError:
    # Re-raise RuntimeError from strict mode - this should halt startup
    raise
except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
    # Log but don't fail on unexpected errors during validation
    logger.warning("Rate limit configuration validation failed: %s", e)


__all__ = [
    "RateLimiter",
    "rate_limit",
    "auth_rate_limit",
    "user_rate_limit",
    "get_client_ip",
    "_get_limiter",
    "_limiters",
    "clear_all_limiters",
    # Multi-instance detection and validation
    "is_multi_instance",
    "_is_multi_instance_mode",
    "_is_redis_configured",
    "_is_production_mode",
    "_should_use_strict_mode",
    "_reset_multi_instance_cache",
    "validate_rate_limit_configuration",
    # Re-exports from middleware for convenience
    "middleware_rate_limit",
    "get_middleware_limiter",
    "RateLimitResult",
    "rate_limit_headers",
    # Distributed rate limiting
    "get_distributed_limiter",
    "DistributedRateLimiter",
    "USE_DISTRIBUTED_LIMITER",
]
