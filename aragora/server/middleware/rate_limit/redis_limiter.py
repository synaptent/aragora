"""
Redis-backed rate limiter implementation.

Provides RedisRateLimiter for distributed rate limiting across multiple
server instances.

Features:
- Distributed rate limiting via Redis sorted sets and Lua scripts
- Circuit breaker integration for fault tolerance
- Redis HA support (Sentinel/Cluster via config)
- Distributed metrics aggregation
- Coordinated degraded mode across instances
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .base import (
    DEFAULT_RATE_LIMIT,
    IP_RATE_LIMIT,
    _normalize_ip,
    normalize_rate_limit_path,
    sanitize_rate_limit_key_component,
)
from .bucket import RedisTokenBucket
from .limiter import RateLimitConfig, RateLimiter, RateLimitResult

from aragora.exceptions import REDIS_CONNECTION_ERRORS

if TYPE_CHECKING:
    import redis

logger = logging.getLogger(__name__)

# Optional Redis support - redis_lib is set to None when import fails.
try:
    redis_lib: Any = importlib.import_module("redis")

    REDIS_AVAILABLE = True
except ImportError:
    redis_lib = None  # Optional dependency not installed
    REDIS_AVAILABLE = False

# Redis rate limiter fail-open policy (SECURITY: default to fail-closed)
# Set ARAGORA_RATE_LIMIT_FAIL_OPEN=true only in dev/testing
RATE_LIMIT_FAIL_OPEN = os.environ.get("ARAGORA_RATE_LIMIT_FAIL_OPEN", "false").lower() == "true"
# Number of consecutive Redis failures before falling back to in-memory limiting
REDIS_FAILURE_THRESHOLD = int(os.environ.get("ARAGORA_REDIS_FAILURE_THRESHOLD", "3"))
# Enable circuit breaker for Redis connection resilience
ENABLE_CIRCUIT_BREAKER = (
    os.environ.get("ARAGORA_RATE_LIMIT_CIRCUIT_BREAKER", "true").lower() == "true"
)
# Enable distributed metrics aggregation via Redis
ENABLE_DISTRIBUTED_METRICS = (
    os.environ.get("ARAGORA_RATE_LIMIT_DISTRIBUTED_METRICS", "true").lower() == "true"
)
# Metrics aggregation interval in seconds
METRICS_AGGREGATION_INTERVAL = int(os.environ.get("ARAGORA_RATE_LIMIT_METRICS_INTERVAL", "60"))

# Global Redis client (lazy-initialized)
_redis_client: redis.Redis | None = None
_redis_init_attempted: bool = False


def get_redis_client() -> redis.Redis | None:
    """
    Get Redis client if configured and available.

    Uses centralized redis_config for connection pooling, with fallback
    to settings-based configuration for backward compatibility.
    Returns None if Redis is not configured or unavailable.
    """
    global _redis_client, _redis_init_attempted

    if _redis_init_attempted:
        return _redis_client

    _redis_init_attempted = True

    if not REDIS_AVAILABLE:
        logger.debug("Redis package not installed, using in-memory rate limiting")
        return None

    # Try centralized redis_config first (preferred)
    try:
        from aragora.server.redis_config import get_redis_client as get_shared_client

        shared_client = get_shared_client()
        if shared_client is not None:
            _redis_client = shared_client
            logger.debug("Rate limiting using shared Redis connection pool")
            return _redis_client
    except ImportError:
        pass  # Fall back to settings-based configuration

    # Fall back to settings-based configuration
    try:
        from aragora.config.settings import get_settings

        settings = get_settings()

        redis_url = settings.rate_limit.redis_url
        if not redis_url:
            logger.debug("ARAGORA_REDIS_URL not set, using in-memory rate limiting")
            return None

        _redis_client = redis_lib.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        # Test connection
        _redis_client.ping()
        logger.info("Redis rate limiting enabled: %s", redis_url.split("@")[-1])
        return _redis_client

    except REDIS_CONNECTION_ERRORS as e:
        logger.warning("Redis connection failed, using in-memory rate limiting: %s", e)
        _redis_client = None
        return None
    except (ValueError, RuntimeError) as e:
        logger.warning("Redis connection failed, using in-memory rate limiting: %s", e)
        _redis_client = None
        return None


def reset_redis_client() -> None:
    """Reset Redis client (for testing)."""
    global _redis_client, _redis_init_attempted
    if _redis_client is not None:
        try:
            _redis_client.close()
        except (OSError, RuntimeError) as e:
            # Log but don't fail - we're resetting anyway
            logger.debug("Error closing Redis client during reset: %s", e)
    _redis_client = None
    _redis_init_attempted = False


class RateLimitCircuitBreaker:
    """
    Circuit breaker for Redis rate limiting operations.

    Provides fault tolerance by tracking failures and temporarily
    disabling Redis operations when the error rate exceeds thresholds.

    States:
    - CLOSED: Normal operation, requests go to Redis
    - OPEN: Redis disabled, all requests use fallback
    - HALF_OPEN: Testing if Redis has recovered
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        reset_timeout_seconds: float | None = None,
        half_open_max_calls: int = 3,
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before testing recovery
            half_open_max_calls: Max calls to allow in half-open state
        """
        if reset_timeout_seconds is not None:
            recovery_timeout = reset_timeout_seconds
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = self.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """Get current circuit state."""
        with self._lock:
            # Check if we should transition from OPEN to HALF_OPEN
            if self._state == self.OPEN and self._last_failure_time:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = self.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("Rate limit circuit breaker entering HALF_OPEN state")
            return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through to Redis."""
        state = self.state  # This may trigger state transition

        with self._lock:
            if state == self.CLOSED:
                return True
            elif state == self.HALF_OPEN:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False
            else:  # OPEN
                return False

    def record_success(self) -> None:
        """Record a successful Redis operation."""
        with self._lock:
            self._success_count += 1
            if self._state == self.HALF_OPEN:
                # Successful calls in half-open close the circuit
                if self._success_count >= self.half_open_max_calls:
                    self._state = self.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("Rate limit circuit breaker CLOSED (Redis recovered)")

    def record_failure(self) -> None:
        """Record a failed Redis operation."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == self.HALF_OPEN:
                # Any failure in half-open reopens the circuit
                self._state = self.OPEN
                logger.warning("Rate limit circuit breaker reopened due to failure in HALF_OPEN")
            elif self._state == self.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = self.OPEN
                    logger.warning(
                        "Rate limit circuit breaker OPEN after %s failures", self._failure_count
                    )

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        with self._lock:
            return {
                "state": self._state,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
                "last_failure_time": self._last_failure_time,
            }


class RedisRateLimiter:
    """
    Rate limiter using Redis for persistent storage.

    Provides the same interface as RateLimiter but stores state in Redis.
    Falls back to in-memory on Redis errors.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        default_limit: int = DEFAULT_RATE_LIMIT,
        ip_limit: int = IP_RATE_LIMIT,
        key_prefix: str = "aragora:ratelimit:",
        ttl_seconds: int = 120,
        enable_circuit_breaker: bool = ENABLE_CIRCUIT_BREAKER,
        enable_distributed_metrics: bool = ENABLE_DISTRIBUTED_METRICS,
        instance_id: str | None = None,
    ):
        """
        Initialize Redis rate limiter.

        Args:
            redis_client: Redis client instance.
            default_limit: Default requests per minute.
            ip_limit: Requests per minute per IP.
            key_prefix: Redis key prefix.
            ttl_seconds: TTL for Redis keys.
            enable_circuit_breaker: Enable circuit breaker for fault tolerance.
            enable_distributed_metrics: Enable distributed metrics aggregation.
            instance_id: Unique identifier for this server instance.
        """
        self.redis = redis_client
        self.default_limit = default_limit
        self.ip_limit = ip_limit
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self.instance_id = instance_id or os.environ.get(
            "ARAGORA_INSTANCE_ID", f"instance-{os.getpid()}"
        )

        # Circuit breaker for fault tolerance
        self._circuit_breaker: RateLimitCircuitBreaker | None = None
        if enable_circuit_breaker:
            self._circuit_breaker = RateLimitCircuitBreaker(
                failure_threshold=REDIS_FAILURE_THRESHOLD,
                recovery_timeout=30.0,
            )

        # In-memory fallback for when Redis fails
        self._fallback = RateLimiter(default_limit, ip_limit)

        # Per-endpoint configuration (stored in memory, not Redis)
        self._endpoint_configs: dict[str, RateLimitConfig] = {}

        # Cache of Redis buckets
        self._buckets: dict[str, RedisTokenBucket] = {}
        self._lock = threading.Lock()

        # Local observability metrics
        self._requests_allowed: int = 0
        self._requests_rejected: int = 0
        self._rejections_by_endpoint: dict[str, int] = {}
        self._redis_failures: int = 0
        self._fallback_requests: int = 0

        # Distributed metrics
        self._enable_distributed_metrics = enable_distributed_metrics
        self._metrics_key = f"{key_prefix}metrics:"
        self._last_metrics_sync: float = 0.0

    def configure_endpoint(
        self,
        endpoint: str,
        requests_per_minute: int,
        burst_size: int | None = None,
        key_type: str = "ip",
    ) -> None:
        """Configure rate limit for a specific endpoint."""
        normalized_endpoint = normalize_rate_limit_path(endpoint)
        self._endpoint_configs[normalized_endpoint] = RateLimitConfig(
            requests_per_minute=requests_per_minute,
            burst_size=burst_size,
            key_type=key_type,
        )
        # Also configure fallback
        self._fallback.configure_endpoint(
            normalized_endpoint, requests_per_minute, burst_size, key_type
        )

    def get_config(self, endpoint: str) -> RateLimitConfig:
        """Get rate limit config for an endpoint."""
        normalized_endpoint = normalize_rate_limit_path(endpoint)
        if normalized_endpoint in self._endpoint_configs:
            return self._endpoint_configs[normalized_endpoint]

        for path, config in self._endpoint_configs.items():
            if path.endswith("*") and normalized_endpoint.startswith(path[:-1]):
                return config

        return RateLimitConfig(requests_per_minute=self.default_limit)

    def _get_bucket(self, key: str, config: RateLimitConfig) -> RedisTokenBucket:
        """Get or create a Redis bucket."""
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = RedisTokenBucket(
                    self.redis,
                    key,
                    config.requests_per_minute,
                    config.burst_size,
                    self.key_prefix,
                    self.ttl_seconds,
                )
            return self._buckets[key]

    def allow(
        self,
        client_ip: str,
        endpoint: str | None = None,
        token: str | None = None,
        tenant_id: str | None = None,
    ) -> RateLimitResult:
        """Check if a request should be allowed."""
        # tenant_id is accepted for interface compatibility but currently unused
        # as Redis limiter keys are based on client_ip/endpoint/token
        _ = tenant_id
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

        # Determine the key based on config
        if config.key_type == "token" and safe_token:
            key = f"token:{safe_token}"
        elif config.key_type == "combined" and safe_endpoint:
            key = f"ep:{safe_endpoint}:ip:{safe_ip}"
        elif config.key_type == "endpoint" and safe_endpoint:
            key = f"ep:{safe_endpoint}"
        else:
            key = f"ip:{safe_ip}"

        # Check circuit breaker if enabled
        use_redis = True
        if self._circuit_breaker:
            use_redis = self._circuit_breaker.allow_request()
            if not use_redis:
                with self._lock:
                    self._fallback_requests += 1
                return self._fallback.allow(client_ip, endpoint, token)

        try:
            bucket = self._get_bucket(key, config)
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

            # Record success for circuit breaker
            if self._circuit_breaker:
                self._circuit_breaker.record_success()

            # Sync distributed metrics periodically
            if self._enable_distributed_metrics:
                self._maybe_sync_distributed_metrics()

            return RateLimitResult(
                allowed=allowed,
                remaining=bucket.remaining,
                limit=config.requests_per_minute,
                retry_after=bucket.get_retry_after() if not allowed else 0,
                key=key,
            )
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as e:
            logger.warning("Redis rate limit failed, using fallback: %s", e)

            # Record failure for circuit breaker
            if self._circuit_breaker:
                self._circuit_breaker.record_failure()

            with self._lock:
                self._redis_failures += 1
                self._fallback_requests += 1

            return self._fallback.allow(client_ip, endpoint, token)

    def get_client_key(self, handler: Any) -> str:
        """Extract client key from request handler."""
        return self._fallback.get_client_key(handler)

    def _maybe_sync_distributed_metrics(self) -> None:
        """Sync local metrics to Redis for aggregation (called periodically)."""
        now = time.time()
        if now - self._last_metrics_sync < METRICS_AGGREGATION_INTERVAL:
            return

        self._last_metrics_sync = now

        try:
            # Use Redis hash to store per-instance metrics
            instance_key = f"{self._metrics_key}{self.instance_id}"
            with self._lock:
                metrics_data: dict[str | bytes, bytes | float | int | str] = {
                    "requests_allowed": str(self._requests_allowed),
                    "requests_rejected": str(self._requests_rejected),
                    "redis_failures": str(self._redis_failures),
                    "fallback_requests": str(self._fallback_requests),
                    "last_sync": datetime.now(timezone.utc).isoformat(),
                }

            pipe = self.redis.pipeline()
            pipe.hset(instance_key, mapping=metrics_data)
            pipe.expire(instance_key, METRICS_AGGREGATION_INTERVAL * 3)  # TTL 3x interval
            pipe.execute()

        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
            logger.debug("Failed to sync distributed metrics: %s", e)

    def get_distributed_metrics(self) -> dict[str, Any]:
        """Get aggregated metrics from all instances."""
        aggregated: dict[str, Any] = {
            "total_requests_allowed": 0,
            "total_requests_rejected": 0,
            "total_redis_failures": 0,
            "total_fallback_requests": 0,
            "instances": {},
            "aggregation_time": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Scan for all instance metric keys
            instance_keys = list(self.redis.scan_iter(f"{self._metrics_key}*", count=100))

            for key in instance_keys:
                instance_id = key.replace(self._metrics_key, "")
                # Sync redis returns dict directly, async redis returns Awaitable
                raw_metrics = self.redis.hgetall(key)
                # Cast for sync Redis - this class uses sync operations only
                metrics: dict[Any, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}

                if metrics:
                    allowed = int(metrics.get("requests_allowed", 0))
                    rejected = int(metrics.get("requests_rejected", 0))
                    failures = int(metrics.get("redis_failures", 0))
                    fallback = int(metrics.get("fallback_requests", 0))

                    aggregated["total_requests_allowed"] += allowed
                    aggregated["total_requests_rejected"] += rejected
                    aggregated["total_redis_failures"] += failures
                    aggregated["total_fallback_requests"] += fallback

                    aggregated["instances"][instance_id] = {
                        "requests_allowed": allowed,
                        "requests_rejected": rejected,
                        "redis_failures": failures,
                        "fallback_requests": fallback,
                        "last_sync": metrics.get("last_sync"),
                    }

            total = aggregated["total_requests_allowed"] + aggregated["total_requests_rejected"]
            aggregated["total_rejection_rate"] = (
                aggregated["total_requests_rejected"] / total if total > 0 else 0.0
            )
            aggregated["instance_count"] = len(aggregated["instances"])

        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
            logger.warning("Failed to get distributed metrics: %s", e)
            aggregated["error"] = "Failed to retrieve distributed metrics"

        return aggregated

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics including observability metrics."""
        with self._lock:
            total_requests = self._requests_allowed + self._requests_rejected
            rejection_rate = self._requests_rejected / total_requests if total_requests > 0 else 0.0
            base_stats = {
                "backend": "redis",
                "instance_id": self.instance_id,
                "configured_endpoints": list(self._endpoint_configs.keys()),
                "default_limit": self.default_limit,
                "ip_limit": self.ip_limit,
                # Local observability metrics
                "requests_allowed": self._requests_allowed,
                "requests_rejected": self._requests_rejected,
                "total_requests": total_requests,
                "rejection_rate": rejection_rate,
                "rejections_by_endpoint": dict(self._rejections_by_endpoint),
                "redis_failures": self._redis_failures,
                "fallback_requests": self._fallback_requests,
            }

        # Add circuit breaker stats if enabled
        if self._circuit_breaker:
            base_stats["circuit_breaker"] = self._circuit_breaker.get_stats()

        try:
            # Count Redis keys with our prefix
            keys = list(self.redis.scan_iter(f"{self.key_prefix}*", count=1000))
            base_stats["redis_keys"] = len(keys)

            # Include distributed metrics if enabled
            if self._enable_distributed_metrics:
                base_stats["distributed"] = self.get_distributed_metrics()

            return base_stats
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
            logger.warning("Failed to get Redis rate limit stats: %s", e)
            base_stats["error"] = "Failed to retrieve Redis statistics"
            base_stats["fallback_stats"] = self._fallback.get_stats()
            return base_stats

    def reset_metrics(self) -> None:
        """Reset observability metrics (useful for testing)."""
        with self._lock:
            self._requests_allowed = 0
            self._requests_rejected = 0
            self._rejections_by_endpoint.clear()
        self._fallback.reset_metrics()

    def cleanup(self, max_age_seconds: int = 300) -> int:
        """Redis handles TTL-based cleanup automatically."""
        return 0

    def reset(self) -> None:
        """Reset all rate limiter state."""
        try:
            keys = list(self.redis.scan_iter(f"{self.key_prefix}*", count=10000))
            if keys:
                self.redis.delete(*keys)
        except (OSError, ValueError, RuntimeError, TypeError) as e:
            logger.warning("Redis reset failed: %s", e)

        with self._lock:
            self._buckets.clear()
        self._fallback.reset()


__all__ = [
    "REDIS_AVAILABLE",
    "RATE_LIMIT_FAIL_OPEN",
    "REDIS_FAILURE_THRESHOLD",
    "ENABLE_CIRCUIT_BREAKER",
    "ENABLE_DISTRIBUTED_METRICS",
    "get_redis_client",
    "reset_redis_client",
    "RateLimitCircuitBreaker",
    "RedisRateLimiter",
]
