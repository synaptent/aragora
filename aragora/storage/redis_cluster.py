"""
Redis Cluster Support for Enterprise Deployments.

Provides cluster-aware Redis connectivity for high-availability deployments.
Supports both standalone Redis and Redis Cluster modes with automatic detection.

Features:
- Automatic cluster vs standalone detection
- Connection pooling with health monitoring
- Graceful failover and reconnection
- Key hashing for cluster slot routing
- Read replica support for scaling reads

Usage:
    from aragora.storage.redis_cluster import get_cluster_client, ClusterConfig

    # Auto-detects cluster mode
    client = get_cluster_client()
    if client:
        client.set("key", "value")
        value = client.get("key")

Environment Variables:
    ARAGORA_REDIS_CLUSTER_NODES: Comma-separated list of cluster nodes
        e.g., "redis1:6379,redis2:6379,redis3:6379"
    ARAGORA_REDIS_CLUSTER_MODE: Force cluster mode ("auto", "cluster", "standalone")
    ARAGORA_REDIS_CLUSTER_MAX_CONNECTIONS: Max connections per node (default: 32)
    ARAGORA_REDIS_CLUSTER_SKIP_FULL_COVERAGE: Skip slot coverage check (default: false)
    ARAGORA_REDIS_CLUSTER_READ_FROM_REPLICAS: Enable read from replicas (default: true)
    ARAGORA_REDIS_CLUSTER_PASSWORD: Cluster authentication password

Requirements:
    pip install redis>=4.5.0  # Includes cluster support
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.type_protocols import RedisClientProtocol

logger = logging.getLogger(__name__)


class ClusterMode(Enum):
    """Redis deployment mode."""

    AUTO = "auto"
    CLUSTER = "cluster"
    STANDALONE = "standalone"


@dataclass
class ClusterConfig:
    """Configuration for Redis cluster connection."""

    # Node configuration
    nodes: list[tuple[str, int]] = field(default_factory=list)
    mode: ClusterMode = ClusterMode.AUTO

    # Connection settings
    max_connections_per_node: int = 32
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    retry_on_timeout: bool = True
    retry_on_error: list[type] = field(default_factory=list)
    max_retries: int = 3

    # Cluster-specific
    skip_full_coverage_check: bool = False
    read_from_replicas: bool = True
    require_full_coverage: bool = True

    # Authentication
    password: str | None = None
    username: str | None = None

    # Health checking
    health_check_interval: float = 30.0
    connection_timeout: float = 10.0

    # Encoding
    decode_responses: bool = True

    def __post_init__(self) -> None:
        """Validate and clamp configuration values to valid bounds."""
        # Bounds for max_connections_per_node: [1, 500]
        if self.max_connections_per_node < 1 or self.max_connections_per_node > 500:
            logger.warning(
                "max_connections_per_node=%d out of bounds [1, 500], clamping",
                self.max_connections_per_node,
            )
            self.max_connections_per_node = max(1, min(self.max_connections_per_node, 500))

        # Bounds for socket_timeout: [1.0, 300.0]
        if self.socket_timeout < 1.0 or self.socket_timeout > 300.0:
            logger.warning(
                "socket_timeout=%.1f out of bounds [1.0, 300.0], clamping",
                self.socket_timeout,
            )
            self.socket_timeout = max(1.0, min(self.socket_timeout, 300.0))

        # Bounds for socket_connect_timeout: [1.0, 60.0]
        if self.socket_connect_timeout < 1.0 or self.socket_connect_timeout > 60.0:
            logger.warning(
                "socket_connect_timeout=%.1f out of bounds [1.0, 60.0], clamping",
                self.socket_connect_timeout,
            )
            self.socket_connect_timeout = max(1.0, min(self.socket_connect_timeout, 60.0))

        # Bounds for health_check_interval: [5.0, 300.0]
        if self.health_check_interval < 5.0 or self.health_check_interval > 300.0:
            logger.warning(
                "health_check_interval=%.1f out of bounds [5.0, 300.0], clamping",
                self.health_check_interval,
            )
            self.health_check_interval = max(5.0, min(self.health_check_interval, 300.0))


def get_cluster_config() -> ClusterConfig:
    """Get cluster configuration from environment variables."""
    # Parse node list
    nodes_str = os.getenv("ARAGORA_REDIS_CLUSTER_NODES", "")
    nodes: list[tuple[str, int]] = []
    if nodes_str:
        for node in nodes_str.split(","):
            node = node.strip()
            if ":" in node:
                host, port_str = node.rsplit(":", 1)
                try:
                    nodes.append((host, int(port_str)))
                except ValueError:
                    logger.warning("Invalid cluster node: %s", node)
            elif node:
                nodes.append((node, 6379))

    # Fallback to single-node URL if no cluster nodes
    if not nodes:
        redis_url = os.getenv("ARAGORA_REDIS_URL", "")
        if redis_url:
            # Parse redis://host:port format
            if redis_url.startswith("redis://"):
                redis_url = redis_url[8:]
            if "@" in redis_url:
                redis_url = redis_url.split("@")[-1]
            if "/" in redis_url:
                redis_url = redis_url.split("/")[0]
            if ":" in redis_url:
                host, port_str = redis_url.rsplit(":", 1)
                try:
                    nodes.append((host, int(port_str)))
                except ValueError:
                    nodes.append((host, 6379))
            elif redis_url:
                nodes.append((redis_url, 6379))

    # Parse mode
    mode_str = os.getenv("ARAGORA_REDIS_CLUSTER_MODE", "auto").lower()
    try:
        mode = ClusterMode(mode_str)
    except ValueError:
        mode = ClusterMode.AUTO

    return ClusterConfig(
        nodes=nodes,
        mode=mode,
        max_connections_per_node=int(os.getenv("ARAGORA_REDIS_CLUSTER_MAX_CONNECTIONS", "32")),
        socket_timeout=float(os.getenv("ARAGORA_REDIS_SOCKET_TIMEOUT", "5.0")),
        socket_connect_timeout=float(os.getenv("ARAGORA_REDIS_SOCKET_CONNECT_TIMEOUT", "5.0")),
        skip_full_coverage_check=os.getenv("ARAGORA_REDIS_CLUSTER_SKIP_FULL_COVERAGE", "").lower()
        == "true",
        read_from_replicas=os.getenv("ARAGORA_REDIS_CLUSTER_READ_FROM_REPLICAS", "true").lower()
        == "true",
        password=os.getenv("ARAGORA_REDIS_CLUSTER_PASSWORD") or os.getenv("ARAGORA_REDIS_PASSWORD"),
        username=os.getenv("ARAGORA_REDIS_USERNAME"),
        health_check_interval=float(os.getenv("ARAGORA_REDIS_HEALTH_CHECK_INTERVAL", "30.0")),
    )


class ClusterHealthMonitor:
    """Monitors cluster health and triggers reconnection on failures."""

    def __init__(self, check_interval: float = 30.0):
        self.check_interval = check_interval
        self._last_check: float = 0
        self._healthy: bool = True
        self._consecutive_failures: int = 0
        self._lock = threading.Lock()

    def mark_success(self) -> None:
        """Mark a successful operation."""
        with self._lock:
            self._consecutive_failures = 0
            self._healthy = True

    def mark_failure(self) -> None:
        """Mark a failed operation."""
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._healthy = False

    @property
    def is_healthy(self) -> bool:
        """Check if cluster is healthy."""
        with self._lock:
            return self._healthy

    def should_check(self) -> bool:
        """Check if health check is due."""
        now = time.time()
        if now - self._last_check > self.check_interval:
            self._last_check = now
            return True
        return False


class RedisClusterClient:
    """
    Unified Redis client supporting both cluster and standalone modes.

    Automatically detects cluster mode and provides a consistent interface.
    """

    def __init__(self, config: ClusterConfig | None = None):
        """
        Initialize Redis cluster client.

        Args:
            config: Cluster configuration (uses environment if not provided)
        """
        self.config = config or get_cluster_config()
        self._client: RedisClientProtocol | None = None
        self._is_cluster: bool = False
        self._available: bool = False
        self._lock = threading.Lock()
        self._health_monitor = ClusterHealthMonitor(self.config.health_check_interval)

    def _detect_cluster_mode(self) -> bool:
        """Detect if target is a Redis Cluster or standalone instance."""
        if self.config.mode == ClusterMode.CLUSTER:
            return True
        if self.config.mode == ClusterMode.STANDALONE:
            return False

        # Auto-detect by trying CLUSTER INFO command
        if not self.config.nodes:
            return False

        try:
            import redis

            host, port = self.config.nodes[0]
            test_client = redis.Redis(
                host=host,
                port=port,
                password=self.config.password,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
            # Try cluster info - will raise ResponseError if not a cluster
            test_client.execute_command("CLUSTER", "INFO")
            test_client.close()
            logger.info("Detected Redis Cluster at %s:%s", host, port)
            return True
        except ImportError:
            logger.debug("redis package not installed for cluster detection")
            return False
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.debug("Connection failed during cluster detection: %s: %s", type(e).__name__, e)
            return False
        except (ValueError, RuntimeError) as e:
            # ResponseError indicates standalone mode, other errors logged for debugging
            logger.debug("Cluster detection result (standalone): %s: %s", type(e).__name__, e)
            return False

    def _create_client(self) -> RedisClientProtocol | None:
        """Create appropriate Redis client based on mode."""
        if not self.config.nodes:
            logger.warning("No Redis nodes configured")
            return None

        try:
            import redis
            from redis.cluster import RedisCluster, ClusterNode

            self._is_cluster = self._detect_cluster_mode()

            if self._is_cluster:
                # Create cluster client
                startup_nodes = [ClusterNode(host, port) for host, port in self.config.nodes]

                client: Any = RedisCluster(
                    startup_nodes=startup_nodes,
                    password=self.config.password,
                    socket_timeout=self.config.socket_timeout,
                    socket_connect_timeout=self.config.socket_connect_timeout,
                    retry_on_timeout=self.config.retry_on_timeout,
                    skip_full_coverage_check=self.config.skip_full_coverage_check,
                    read_from_replicas=self.config.read_from_replicas,
                    decode_responses=self.config.decode_responses,
                )

                # Test cluster connectivity
                client.ping()
                logger.info("Redis Cluster connected: %s startup nodes", len(self.config.nodes))
            else:
                # Create standalone client with connection pool
                host, port = self.config.nodes[0]
                pool = redis.ConnectionPool(
                    host=host,
                    port=port,
                    password=self.config.password,
                    max_connections=self.config.max_connections_per_node,
                    socket_timeout=self.config.socket_timeout,
                    socket_connect_timeout=self.config.socket_connect_timeout,
                    retry_on_timeout=self.config.retry_on_timeout,
                    decode_responses=self.config.decode_responses,
                )
                client = redis.Redis(connection_pool=pool)
                client.ping()
                logger.info("Redis standalone connected: %s:%s", host, port)

            self._available = True
            return client

        except ImportError:
            logger.error("redis package not installed. Install with: pip install 'redis>=4.5.0'")
            return None
        except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
            logger.error("Failed to connect to Redis: %s", e)
            return None

    def get_client(self) -> RedisClientProtocol | None:
        """Get or create Redis client (thread-safe lazy initialization)."""
        if self._client is not None:
            return self._client

        with self._lock:
            if self._client is None:
                self._client = self._create_client()
            return self._client

    def _require_client(self) -> RedisClientProtocol:
        """Return the active client or fail with the public unavailable error."""
        client = self.get_client()
        if client is None:
            raise RuntimeError("Redis client not available")
        return client

    @property
    def is_cluster(self) -> bool:
        """Check if connected to a cluster."""
        self.get_client()  # Ensure detection has run
        return self._is_cluster

    @property
    def is_available(self) -> bool:
        """Check if Redis is available."""
        return self._available and self._health_monitor.is_healthy

    def _execute_with_retry(
        self, operation: Callable[[], Any], max_retries: int | None = None
    ) -> Any:
        """Execute operation with retry logic.

        Note: This is a synchronous method. If called from an async context,
        use _execute_with_retry_async() instead to avoid blocking the event loop.
        """
        retries = max_retries or self.config.max_retries
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                client = self.get_client()
                if client is None:
                    raise RuntimeError("Redis client not available")

                result = operation()
                self._health_monitor.mark_success()
                return result

            except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
                last_error = e
                self._health_monitor.mark_failure()

                if attempt < retries:
                    wait_time = min(2**attempt * 0.1, 2.0)
                    logger.warning(
                        f"Redis operation failed (attempt {attempt + 1}/{retries + 1}): {e}. "
                        f"Retrying in {wait_time:.1f}s"
                    )
                    # Sync method - use blocking sleep
                    # For async contexts, use _execute_with_retry_async() instead
                    time.sleep(wait_time)

                    # Try to reconnect on cluster errors
                    if "MOVED" in str(e) or "CLUSTERDOWN" in str(e):
                        self._reconnect()

        logger.error("Redis operation failed after %s attempts: %s", retries + 1, last_error)
        if last_error is None:
            raise RuntimeError("Redis operation failed with unknown error")
        raise last_error

    async def _execute_with_retry_async(
        self, operation: Callable[[], Any], max_retries: int | None = None
    ) -> Any:
        """Execute operation with retry logic (async version).

        Use this method when calling from async contexts to avoid blocking
        the event loop during retry delays.
        """
        retries = max_retries or self.config.max_retries
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                client = self.get_client()
                if client is None:
                    raise RuntimeError("Redis client not available")

                # Run sync operation in executor to not block event loop
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, operation)
                self._health_monitor.mark_success()
                return result

            except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
                last_error = e
                self._health_monitor.mark_failure()

                if attempt < retries:
                    wait_time = min(2**attempt * 0.1, 2.0)
                    logger.warning(
                        f"Redis operation failed (attempt {attempt + 1}/{retries + 1}): {e}. "
                        f"Retrying in {wait_time:.1f}s"
                    )
                    # Use asyncio.sleep to not block the event loop
                    await asyncio.sleep(wait_time)

                    # Try to reconnect on cluster errors
                    if "MOVED" in str(e) or "CLUSTERDOWN" in str(e):
                        self._reconnect()

        logger.error("Redis operation failed after %s attempts: %s", retries + 1, last_error)
        if last_error is None:
            raise RuntimeError("Redis operation failed with unknown error")
        raise last_error

    def _reconnect(self) -> None:
        """Force reconnection to cluster."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except (ConnectionError, TimeoutError, OSError) as e:
                    logger.debug(
                        "Error closing Redis client during reconnect: %s: %s", type(e).__name__, e
                    )
                except (RuntimeError, ValueError) as e:
                    logger.warning(
                        "Unexpected error closing Redis client: %s: %s", type(e).__name__, e
                    )
                self._client = None
            self._client = self._create_client()
            if self._client is not None:
                logger.info("Redis client reconnected successfully")
            else:
                logger.warning("Redis client reconnection failed")

    # ==========================================================================
    # Standard Redis Operations (with retry)
    # ==========================================================================

    def get(self, key: str) -> str | None:
        """Get value for key."""

        def _get() -> str | None:
            client = self.get_client()
            if client is None:
                raise RuntimeError("Redis client not available")
            result = client.get(key)
            return str(result) if result is not None else None

        return self._execute_with_retry(_get)

    def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """Set key to value with optional expiration."""

        def _set() -> bool:
            client = self._require_client()
            return bool(client.set(key, value, ex=ex, px=px, nx=nx, xx=xx))

        return self._execute_with_retry(_set)

    def delete(self, *keys: str) -> int:
        """Delete one or more keys."""

        def _delete() -> int:
            client = self._require_client()
            return client.delete(*keys)

        return self._execute_with_retry(_delete)

    def exists(self, *keys: str) -> int:
        """Check if keys exist."""

        def _exists() -> int:
            client = self._require_client()
            return client.exists(*keys)

        return self._execute_with_retry(_exists)

    def expire(self, key: str, seconds: int) -> bool:
        """Set TTL on key."""

        def _expire() -> bool:
            client = self._require_client()
            return client.expire(key, seconds)

        return self._execute_with_retry(_expire)

    def ttl(self, key: str) -> int:
        """Get TTL of key."""

        def _ttl() -> int:
            client = self._require_client()
            return client.ttl(key)

        return self._execute_with_retry(_ttl)

    def incr(self, key: str) -> int:
        """Increment key."""

        def _incr() -> int:
            client = self._require_client()
            return client.incr(key)

        return self._execute_with_retry(_incr)

    def decr(self, key: str) -> int:
        """Decrement key."""

        def _decr() -> int:
            client = self._require_client()
            return client.decr(key)

        return self._execute_with_retry(_decr)

    # ==========================================================================
    # Hash Operations
    # ==========================================================================

    def hget(self, name: str, key: str) -> str | None:
        """Get field from hash."""

        def _hget() -> str | None:
            client = self._require_client()
            return client.hget(name, key)

        return self._execute_with_retry(_hget)

    def hset(self, name: str, key: str, value: str) -> int:
        """Set field in hash."""

        def _hset() -> int:
            client = self._require_client()
            return client.hset(name, key, value)

        return self._execute_with_retry(_hset)

    def hgetall(self, name: str) -> dict[str, str]:
        """Get all fields from hash."""

        def _hgetall() -> dict[str, str]:
            client = self._require_client()
            return client.hgetall(name)

        return self._execute_with_retry(_hgetall)

    def hdel(self, name: str, *keys: str) -> int:
        """Delete fields from hash."""

        def _hdel() -> int:
            client = self._require_client()
            return client.hdel(name, *keys)

        return self._execute_with_retry(_hdel)

    # ==========================================================================
    # Sorted Set Operations (for rate limiting)
    # ==========================================================================

    def zadd(self, name: str, mapping: dict[str, float]) -> int:
        """Add members to sorted set."""

        def _zadd() -> int:
            client = self._require_client()
            return client.zadd(name, mapping)

        return self._execute_with_retry(_zadd)

    def zrem(self, name: str, *members: str) -> int:
        """Remove members from sorted set."""

        def _zrem() -> int:
            client = self._require_client()
            return client.zrem(name, *members)

        return self._execute_with_retry(_zrem)

    def zcard(self, name: str) -> int:
        """Get sorted set cardinality."""

        def _zcard() -> int:
            client = self._require_client()
            return client.zcard(name)

        return self._execute_with_retry(_zcard)

    def zrangebyscore(
        self,
        name: str,
        min: float | str,
        max: float | str,
        withscores: bool = False,
    ) -> list[Any]:
        """Get members by score range."""

        def _zrangebyscore() -> list[Any]:
            client = self._require_client()
            return client.zrangebyscore(name, min, max, withscores=withscores)

        return self._execute_with_retry(_zrangebyscore)

    def zremrangebyscore(self, name: str, min: float | str, max: float | str) -> int:
        """Remove members by score range."""

        def _zremrangebyscore() -> int:
            client = self._require_client()
            return client.zremrangebyscore(name, min, max)

        return self._execute_with_retry(_zremrangebyscore)

    # ==========================================================================
    # Pipeline Support
    # ==========================================================================

    def pipeline(self, transaction: bool = True) -> Any:
        """Get pipeline for batch operations.

        Note: In cluster mode, all keys in pipeline must hash to same slot.
        Use hash tags like {user:123}:field to ensure slot affinity.
        """
        client = self.get_client()
        if client is None:
            raise RuntimeError("Redis client not available")
        return client.pipeline(transaction=transaction)

    # ==========================================================================
    # Cluster-specific Operations
    # ==========================================================================

    def get_cluster_info(self) -> dict[str, Any]:
        """Get cluster information (cluster mode only)."""
        if not self._is_cluster:
            return {"mode": "standalone", "cluster": False}

        try:
            client = self.get_client()
            if client is None:
                return {"mode": "cluster", "cluster": True, "error": "not connected"}

            # Parse cluster info
            info = client.execute_command("CLUSTER", "INFO")
            nodes = client.execute_command("CLUSTER", "NODES")

            return {
                "mode": "cluster",
                "cluster": True,
                "info": info,
                "node_count": len(nodes.strip().split("\n")) if isinstance(nodes, str) else 0,
            }
        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            logger.warning("Failed to get cluster info: %s", e)
            return {"mode": "cluster", "cluster": True, "error": "Failed to retrieve cluster info"}

    def get_slot_for_key(self, key: str) -> int:
        """Calculate cluster slot for key.

        Uses CRC16 algorithm per Redis Cluster specification.
        Handles hash tags for slot affinity.
        """
        # Check for hash tag
        start = key.find("{")
        if start >= 0:
            end = key.find("}", start + 1)
            if end > start + 1:
                key = key[start + 1 : end]

        # CRC16 CCITT
        def crc16(data: bytes) -> int:
            crc = 0
            for byte in data:
                crc ^= byte << 8
                for _ in range(8):
                    if crc & 0x8000:
                        crc = (crc << 1) ^ 0x1021
                    else:
                        crc = crc << 1
                    crc &= 0xFFFF
            return crc

        return crc16(key.encode()) % 16384

    # ==========================================================================
    # Health & Stats
    # ==========================================================================

    def ping(self) -> bool:
        """Ping Redis server."""
        try:
            client = self.get_client()
            if client is None:
                return False
            return client.ping()
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.debug("Redis ping failed: %s: %s", type(e).__name__, e)
            return False
        except (RuntimeError, ValueError) as e:
            logger.warning("Unexpected error during Redis ping: %s: %s", type(e).__name__, e)
            return False

    def info(self, section: str | None = None) -> dict[str, Any]:
        """Get server information."""

        def _info() -> dict[str, Any]:
            client = self.get_client()
            if client is None:
                raise RuntimeError("Redis client not available")
            return client.info(section) if section else client.info()

        return self._execute_with_retry(_info)

    def execute_command(self, *args: Any, **kwargs: Any) -> Any:
        """Execute an arbitrary Redis command."""

        def _execute() -> Any:
            client = self.get_client()
            if client is None:
                raise RuntimeError("Redis client not available")
            return client.execute_command(*args, **kwargs)

        return self._execute_with_retry(_execute)

    def get_stats(self) -> dict[str, Any]:
        """Get connection statistics."""
        client = self.get_client()
        stats: dict[str, Any] = {
            "available": self._available,
            "is_cluster": self._is_cluster,
            "healthy": self._health_monitor.is_healthy,
            "nodes": len(self.config.nodes),
        }

        if client is not None:
            try:
                info = client.info()
                stats["redis_version"] = info.get("redis_version", "unknown")
                stats["connected_clients"] = info.get("connected_clients", 0)
                stats["used_memory_human"] = info.get("used_memory_human", "unknown")
            except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
                logger.warning("Failed to retrieve Redis info: %s", e)
                stats["info_error"] = "Failed to retrieve Redis info"

        return stats

    def close(self) -> None:
        """Close Redis connection."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                    logger.info("Redis cluster client closed")
                except (ConnectionError, TimeoutError, OSError) as e:
                    logger.debug(
                        "Connection error while closing Redis client: %s: %s", type(e).__name__, e
                    )
                except (RuntimeError, ValueError) as e:
                    logger.error(
                        "Unexpected error closing Redis client: %s: %s", type(e).__name__, e
                    )
                finally:
                    self._client = None
                    self._available = False


# =============================================================================
# Module-level singleton
# =============================================================================

_cluster_client: RedisClusterClient | None = None
_lock = threading.Lock()


def get_cluster_client() -> RedisClusterClient | None:
    """Get shared cluster client instance (thread-safe singleton)."""
    global _cluster_client

    if _cluster_client is not None:
        return _cluster_client

    with _lock:
        if _cluster_client is None:
            config = get_cluster_config()
            if config.nodes:
                _cluster_client = RedisClusterClient(config)
                if not _cluster_client.ping():
                    logger.warning("Redis cluster client created but not responding")
            else:
                logger.debug("No Redis nodes configured, cluster client disabled")
        return _cluster_client


def reset_cluster_client() -> None:
    """Reset cluster client (for testing)."""
    global _cluster_client

    with _lock:
        if _cluster_client is not None:
            _cluster_client.close()
            _cluster_client = None


def is_cluster_available() -> bool:
    """Check if cluster client is available."""
    client = get_cluster_client()
    return client is not None and client.is_available


def get_redis_client() -> RedisClientProtocol | None:
    """Get a Redis client from the cluster client.

    This is a convenience function that returns the underlying Redis client
    from the cluster client. Useful when callers just need a standard Redis
    client interface.

    Returns:
        Redis client if cluster is available, None otherwise
    """
    client = get_cluster_client()
    if client is None:
        return None
    return client.get_client()


__all__ = [
    "ClusterConfig",
    "ClusterMode",
    "ClusterHealthMonitor",
    "RedisClusterClient",
    "get_cluster_config",
    "get_cluster_client",
    "get_redis_client",
    "reset_cluster_client",
    "is_cluster_available",
]
