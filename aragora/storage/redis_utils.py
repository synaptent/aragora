"""
Redis Client Utilities for Storage Backends.

Provides a unified interface for getting Redis clients that automatically
uses Redis Cluster when configured, or falls back to standalone mode.

This module bridges the storage backends with the Redis cluster support,
enabling transparent high-availability without changes to store implementations.

Usage:
    from aragora.storage.redis_utils import get_redis_client

    client = get_redis_client()
    if client:
        client.set("key", "value")
        value = client.get("key")

Environment Variables:
    ARAGORA_REDIS_CLUSTER_NODES: Comma-separated list of cluster nodes
        If set, cluster mode will be attempted first
    ARAGORA_REDIS_URL: Standalone Redis URL (used if cluster not configured)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from aragora.type_protocols import RedisClientProtocol

logger = logging.getLogger(__name__)

_cached_client: Any | None = None
_initialized = False


def get_redis_client(redis_url: str | None = None) -> RedisClientProtocol | None:
    """
    Get Redis client, preferring cluster mode when configured.

    Checks for cluster configuration first. If cluster nodes are configured,
    uses the RedisClusterClient which provides:
    - Automatic failover and reconnection
    - Health monitoring
    - Read replica support
    - Connection pooling

    Falls back to standalone Redis if cluster is not configured.

    Args:
        redis_url: Optional Redis URL (for standalone mode)
                  Defaults to ARAGORA_REDIS_URL environment variable

    Returns:
        Redis client or None if not available
    """
    global _cached_client, _initialized

    if _initialized and redis_url is None:
        return _cached_client

    # Check for cluster configuration
    cluster_nodes = os.getenv("ARAGORA_REDIS_CLUSTER_NODES", "")
    if cluster_nodes:
        try:
            from aragora.storage.redis_cluster import get_cluster_client

            client = get_cluster_client()
            if client and client.is_available:
                logger.info("Using Redis Cluster client for storage")
                if redis_url is None:
                    _cached_client = client
                    _initialized = True
                return client
        except ImportError:
            logger.debug("Redis cluster module not available")
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning("Failed to initialize Redis cluster: %s", e)

    # Fall back to standalone Redis
    url = cast(str, redis_url or os.getenv("ARAGORA_REDIS_URL", "redis://localhost:6379"))
    try:
        import redis

        standalone_client = redis.from_url(url, encoding="utf-8", decode_responses=True)
        standalone_client.ping()
        logger.info("Using standalone Redis client at %s", url)
        if redis_url is None:
            _cached_client = standalone_client
            _initialized = True
        return cast(Any, standalone_client)
    except ImportError:
        logger.debug("redis package not installed")
        return None
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        redis.exceptions.ConnectionError,
        redis.exceptions.RedisError,
    ) as e:
        logger.debug("Redis not available: %s", e)
        if redis_url is None:
            _initialized = True
        return None


def reset_redis_client() -> None:
    """Reset cached Redis client (for testing)."""
    global _cached_client, _initialized
    _cached_client = None
    _initialized = False


def is_cluster_mode() -> bool:
    """Check if running in Redis Cluster mode."""
    try:
        from aragora.storage.redis_cluster import get_cluster_client

        client = get_cluster_client()
        return client is not None and client.is_cluster
    except ImportError:
        return False
    except Exception as e:  # noqa: BLE001 - Cluster check fallback
        logger.debug("Redis cluster mode check failed: %s", e)
        return False


__all__ = [
    "get_redis_client",
    "reset_redis_client",
    "is_cluster_mode",
]
