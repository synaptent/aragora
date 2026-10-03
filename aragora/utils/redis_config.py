"""
Redis connection pool configuration.

Provides centralized Redis connection management with:
- Lazy initialization on first use
- Connection pooling for efficiency
- Automatic fallback when Redis unavailable
- Health checking with ping validation

Usage:
    from aragora.utils.redis_config import get_redis_pool, is_redis_available

    if is_redis_available():
        pool = get_redis_pool()
        client = redis.Redis(connection_pool=pool)
        client.set("key", "value")

Environment variables:
    ARAGORA_REDIS_URL: Redis connection URL (e.g., redis://localhost:6379)
    ARAGORA_REDIS_MAX_CONNECTIONS: Max pool connections (default: 50)
    ARAGORA_REDIS_SOCKET_TIMEOUT: Socket timeout in seconds (default: 5.0)
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from aragora.exceptions import REDIS_CONNECTION_ERRORS

logger = logging.getLogger(__name__)

# Module-level connection pool (lazy initialized)
_redis_pool: Any | None = None
_redis_available: bool | None = None
# Serializes first-use pool initialization so concurrent callers cannot create
# multiple pools or race on the cached globals.
_redis_lock = threading.Lock()


def _int_env(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to ``default``.

    A malformed value must not crash this foundation-layer module (it is on the
    lazy-init path consumed by ``aragora.utils.redis_cache``); log and degrade to
    the default instead of raising ``ValueError``.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r is not a valid integer; using default %d", name, raw, default)
        return default


def _float_env(name: str, default: float) -> float:
    """Read a float environment variable, falling back to ``default``.

    Mirrors :func:`_int_env`: a malformed value degrades to the default with a
    warning rather than raising ``ValueError`` on the Redis lazy-init path.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r is not a valid number; using default %s", name, raw, default)
        return default


def get_redis_url() -> str | None:
    """Get the Redis URL from environment.

    Returns:
        Redis URL if configured, None otherwise
    """
    return os.getenv("ARAGORA_REDIS_URL")


def get_redis_pool() -> Any | None:
    """Get shared Redis connection pool (lazy initialization).

    Thread-safe lazy initialization: first-use creation is guarded by a
    module-level lock (double-checked) so concurrent callers share a single
    pool rather than racing to build several. The pool is cached after the
    first successful call. Returns None if Redis is not configured or
    unavailable.

    The pool is configured with:
    - Max connections from ARAGORA_REDIS_MAX_CONNECTIONS (default 50)
    - Socket timeout of 5 seconds
    - Retry on timeout enabled
    - Automatic reconnection

    Returns:
        redis.ConnectionPool if Redis available, None otherwise
    """
    global _redis_pool, _redis_available

    # Fast path: return the cached pool / known-unavailable result without
    # taking the lock.
    if _redis_pool is not None:
        return _redis_pool
    if _redis_available is False:
        return None

    with _redis_lock:
        # Re-check under the lock: another thread may have finished init while
        # we were blocked.
        if _redis_pool is not None:
            return _redis_pool
        if _redis_available is False:
            return None

        url = get_redis_url()
        if not url:
            _redis_available = False
            return None

        try:
            import redis

            max_connections = _int_env("ARAGORA_REDIS_MAX_CONNECTIONS", 50)

            # Validate max_connections bounds
            if max_connections < 1:
                logger.warning(
                    "ARAGORA_REDIS_MAX_CONNECTIONS=%d is below minimum, clamping to 1",
                    max_connections,
                )
                max_connections = 1
            elif max_connections > 10000:
                logger.warning(
                    "ARAGORA_REDIS_MAX_CONNECTIONS=%d exceeds maximum, capping at 10000",
                    max_connections,
                )
                max_connections = 10000

            socket_timeout = _float_env("ARAGORA_REDIS_SOCKET_TIMEOUT", 5.0)

            pool = redis.ConnectionPool.from_url(
                url,
                max_connections=max_connections,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_timeout,
                retry_on_timeout=True,
                decode_responses=True,  # Return strings instead of bytes
            )

            # Test connection with ping before publishing the pool, so a failed
            # connection never leaves a half-initialized pool cached.
            test_client = redis.Redis(connection_pool=pool)
            test_client.ping()

            _redis_pool = pool
            _redis_available = True
            # Mask password in URL for logging
            safe_url = url.split("@")[-1] if "@" in url else url
            logger.info("Redis connected: %s", safe_url)
            return _redis_pool

        except ImportError:
            logger.debug("redis package not installed, Redis caching disabled")
            _redis_pool = None
            _redis_available = False
            return None
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("Redis connection failed: %s", e)
            _redis_pool = None
            _redis_available = False
            return None


def redis_pool_initialized() -> bool:
    """Report whether the shared Redis pool has already been built.

    Read-only: never triggers pool initialization, never opens a socket, and
    never latches ``_redis_available``. Intended for fast health probes that
    must stay off the network (see ``readiness_probe_fast``).
    """
    return _redis_pool is not None


def is_redis_available() -> bool:
    """Check if Redis is available.

    Triggers pool initialization if not already done.

    Returns:
        True if Redis is configured and responding, False otherwise
    """
    global _redis_available

    if _redis_available is not None:
        return _redis_available

    # Try to initialize the pool
    get_redis_pool()
    return _redis_available or False


def get_redis_client() -> Any | None:
    """Get a Redis client using the shared pool.

    Convenience function that returns a ready-to-use Redis client.

    Returns:
        redis.Redis instance if available, None otherwise
    """
    pool = get_redis_pool()
    if pool is None:
        return None

    try:
        import redis

        return redis.Redis(connection_pool=pool)
    except ImportError:
        return None


def close_redis_pool() -> None:
    """Close the Redis connection pool.

    Call during graceful shutdown to release connections. Safe to call even if
    the pool was never initialized. Takes ``_redis_lock`` so teardown cannot
    race a concurrent ``get_redis_pool`` first-use init on the shared globals.
    """
    global _redis_pool, _redis_available

    with _redis_lock:
        if _redis_pool is not None:
            try:
                _redis_pool.disconnect()
                logger.debug("Redis connection pool closed")
            except (ConnectionError, OSError, RuntimeError, TimeoutError) as e:
                logger.warning("Error closing Redis pool: %s", e)
            finally:
                _redis_pool = None

        _redis_available = None


def reset_redis_state() -> None:
    """Reset Redis state for testing.

    Clears cached pool and availability flag to allow re-initialization. Takes
    ``_redis_lock`` so the reset is atomic against a concurrent
    ``get_redis_pool`` init on the shared globals.
    """
    global _redis_pool, _redis_available
    with _redis_lock:
        _redis_pool = None
        _redis_available = None


async def get_async_redis_client() -> Any | None:
    """Get an async Redis client.

    Creates an async Redis connection using aioredis-compatible interface.
    Falls back to sync client with async wrapper if redis-py >= 4.2 is available.

    Returns:
        Async Redis client if available, None otherwise
    """
    url = get_redis_url()
    if not url:
        return None

    try:
        import redis.asyncio as aioredis

        socket_timeout = _float_env("ARAGORA_REDIS_SOCKET_TIMEOUT", 5.0)

        client = aioredis.from_url(
            url,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
            decode_responses=True,
        )

        # Test connection
        await client.ping()
        logger.info("Async Redis client connected")
        return client

    except ImportError:
        logger.debug("redis.asyncio not available for async Redis client")
        return None
    except REDIS_CONNECTION_ERRORS as e:
        logger.warning("Async Redis connection failed: %s", e)
        return None


__all__ = [
    "get_redis_url",
    "get_redis_pool",
    "get_redis_client",
    "get_async_redis_client",
    "is_redis_available",
    "close_redis_pool",
    "reset_redis_state",
]
