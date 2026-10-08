"""
Redis High-Availability Connection Factory.

Provides unified Redis client creation for different deployment modes:
- Standalone: Single Redis instance (development/testing)
- Sentinel: Redis Sentinel for automatic failover (production HA)
- Cluster: Redis Cluster for horizontal scaling (enterprise)

This module abstracts the complexity of different Redis topologies and provides
a simple, consistent interface for obtaining Redis clients.

Usage:
    from aragora.storage.redis_ha import get_redis_client, get_async_redis_client, RedisHAConfig

    # Synchronous client (auto-configured from environment)
    client = get_redis_client()
    if client:
        client.set("key", "value")

    # Async client
    async_client = await get_async_redis_client()
    if async_client:
        await async_client.set("key", "value")

    # Custom configuration
    config = RedisHAConfig(
        mode=RedisMode.SENTINEL,
        sentinel_hosts=["sentinel1:26379", "sentinel2:26379"],
        sentinel_master="mymaster",
    )
    client = get_redis_client(config)

Environment Variables:
    ARAGORA_REDIS_MODE: Redis mode ("standalone", "sentinel", "cluster")
    ARAGORA_REDIS_URL: Standalone Redis URL
    ARAGORA_REDIS_HOST: Standalone Redis host (default: localhost)
    ARAGORA_REDIS_PORT: Standalone Redis port (default: 6379)
    ARAGORA_REDIS_PASSWORD: Redis authentication password
    ARAGORA_REDIS_DB: Redis database number (default: 0)

    # Sentinel mode
    ARAGORA_REDIS_SENTINEL_HOSTS: Comma-separated sentinel hosts (host:port)
    ARAGORA_REDIS_SENTINEL_MASTER: Sentinel master name (default: mymaster)
    ARAGORA_REDIS_SENTINEL_PASSWORD: Sentinel authentication password

    # Cluster mode
    ARAGORA_REDIS_CLUSTER_NODES: Comma-separated cluster nodes (host:port)
    ARAGORA_REDIS_CLUSTER_READ_FROM_REPLICAS: Enable read from replicas (default: true)

    # Common settings
    ARAGORA_REDIS_SOCKET_TIMEOUT: Socket timeout in seconds (default: 5.0)
    ARAGORA_REDIS_SOCKET_CONNECT_TIMEOUT: Connect timeout in seconds (default: 5.0)
    ARAGORA_REDIS_MAX_CONNECTIONS: Max pool connections (default: 50)
    ARAGORA_REDIS_RETRY_ON_TIMEOUT: Retry on timeout (default: true)
    ARAGORA_REDIS_HEALTH_CHECK_INTERVAL: Health check interval (default: 30)
    ARAGORA_REDIS_DECODE_RESPONSES: Decode responses to strings (default: true)

Requirements:
    pip install redis>=4.5.0  # Includes Sentinel and Cluster support
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

logger = logging.getLogger(__name__)


class RedisMode(str, Enum):
    """Redis deployment mode."""

    STANDALONE = "standalone"
    SENTINEL = "sentinel"
    CLUSTER = "cluster"


def _resolve_sentinel_password(config: "RedisHAConfig") -> str | None:
    """Use only explicit Sentinel auth when configured."""
    return config.sentinel_password


@dataclass
class RedisHAConfig:
    """
    Configuration for Redis High-Availability connections.

    Supports three deployment modes:
    - STANDALONE: Single Redis instance with connection pooling
    - SENTINEL: Redis Sentinel for automatic master/replica failover
    - CLUSTER: Redis Cluster for horizontal scaling with sharding

    Attributes:
        mode: Redis deployment mode (standalone/sentinel/cluster)

        # Standalone configuration
        host: Redis server hostname
        port: Redis server port
        password: Redis authentication password
        db: Redis database number (standalone/sentinel only)
        url: Full Redis URL (overrides host/port if provided)

        # Sentinel configuration
        sentinel_hosts: List of sentinel host:port strings
        sentinel_master: Name of the master in Sentinel
        sentinel_password: Password for Sentinel connections
        sentinel_socket_timeout: Socket timeout for Sentinel

        # Cluster configuration
        cluster_nodes: List of cluster node host:port strings
        cluster_read_from_replicas: Enable reading from replicas
        cluster_skip_full_coverage_check: Skip slot coverage check

        # Common connection settings
        socket_timeout: Socket timeout in seconds
        socket_connect_timeout: Connection timeout in seconds
        max_connections: Maximum connections in pool
        retry_on_timeout: Retry operations on timeout
        health_check_interval: Seconds between health checks
        decode_responses: Decode byte responses to strings
        encoding: String encoding (default: utf-8)
        ssl: Enable SSL/TLS connections
        ssl_cert_reqs: SSL certificate requirements
        ssl_ca_certs: Path to CA certificates
    """

    mode: RedisMode = RedisMode.STANDALONE

    # Standalone configuration
    host: str = "localhost"
    port: int = 6379
    password: str | None = None
    db: int = 0
    url: str | None = None

    # Sentinel configuration
    sentinel_hosts: list[str] = field(default_factory=list)
    sentinel_master: str = "mymaster"
    sentinel_password: str | None = None
    sentinel_socket_timeout: float = 5.0

    # Cluster configuration
    cluster_nodes: list[str] = field(default_factory=list)
    cluster_read_from_replicas: bool = True
    cluster_skip_full_coverage_check: bool = False

    # Common connection settings
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    max_connections: int = 50
    retry_on_timeout: bool = True
    health_check_interval: int = 30
    decode_responses: bool = True
    encoding: str = "utf-8"

    # SSL/TLS settings
    ssl: bool = False
    ssl_cert_reqs: str | None = None
    ssl_ca_certs: str | None = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        # Convert sentinel_hosts if it's a string
        if isinstance(self.sentinel_hosts, str):
            self.sentinel_hosts = [h.strip() for h in self.sentinel_hosts.split(",") if h.strip()]

        # Convert cluster_nodes if it's a string
        if isinstance(self.cluster_nodes, str):
            self.cluster_nodes = [n.strip() for n in self.cluster_nodes.split(",") if n.strip()]

    @classmethod
    def from_env(cls) -> RedisHAConfig:
        """
        Create configuration from environment variables.

        Returns:
            RedisHAConfig populated from environment variables
        """
        # Determine mode
        mode_str = os.environ.get("ARAGORA_REDIS_MODE", "standalone").lower()
        try:
            mode = RedisMode(mode_str)
        except ValueError:
            logger.warning("Invalid Redis mode '%s', falling back to standalone", mode_str)
            mode = RedisMode.STANDALONE

        # Auto-detect mode if not explicitly set
        if mode == RedisMode.STANDALONE:
            sentinel_hosts_env = os.environ.get("ARAGORA_REDIS_SENTINEL_HOSTS", "")
            cluster_nodes_env = os.environ.get("ARAGORA_REDIS_CLUSTER_NODES", "")

            if sentinel_hosts_env:
                mode = RedisMode.SENTINEL
                logger.info("Auto-detected Sentinel mode from ARAGORA_REDIS_SENTINEL_HOSTS")
            elif cluster_nodes_env:
                mode = RedisMode.CLUSTER
                logger.info("Auto-detected Cluster mode from ARAGORA_REDIS_CLUSTER_NODES")

        # Parse sentinel hosts
        sentinel_hosts_str = os.environ.get("ARAGORA_REDIS_SENTINEL_HOSTS", "")
        sentinel_hosts: list[str] = [h.strip() for h in sentinel_hosts_str.split(",") if h.strip()]

        # Parse cluster nodes
        cluster_nodes_str = os.environ.get("ARAGORA_REDIS_CLUSTER_NODES", "")
        cluster_nodes: list[str] = [n.strip() for n in cluster_nodes_str.split(",") if n.strip()]

        # Parse URL for standalone defaults
        url = os.environ.get("ARAGORA_REDIS_URL") or os.environ.get("REDIS_URL")
        host = os.environ.get("ARAGORA_REDIS_HOST", "localhost")
        port = int(os.environ.get("ARAGORA_REDIS_PORT", "6379"))

        # Parse host/port from URL if provided
        if url and mode == RedisMode.STANDALONE:
            parsed_host, parsed_port = _parse_redis_url(url)
            if parsed_host:
                host = parsed_host
            if parsed_port:
                port = parsed_port

        return cls(
            mode=mode,
            # Standalone
            host=host,
            port=port,
            password=os.environ.get("ARAGORA_REDIS_PASSWORD"),
            db=int(os.environ.get("ARAGORA_REDIS_DB", "0")),
            url=url,
            # Sentinel
            sentinel_hosts=sentinel_hosts,
            sentinel_master=os.environ.get("ARAGORA_REDIS_SENTINEL_MASTER", "mymaster"),
            sentinel_password=os.environ.get("ARAGORA_REDIS_SENTINEL_PASSWORD"),
            sentinel_socket_timeout=float(
                os.environ.get("ARAGORA_REDIS_SENTINEL_SOCKET_TIMEOUT", "5.0")
            ),
            # Cluster
            cluster_nodes=cluster_nodes,
            cluster_read_from_replicas=os.environ.get(
                "ARAGORA_REDIS_CLUSTER_READ_FROM_REPLICAS", "true"
            ).lower()
            == "true",
            cluster_skip_full_coverage_check=os.environ.get(
                "ARAGORA_REDIS_CLUSTER_SKIP_FULL_COVERAGE", "false"
            ).lower()
            == "true",
            # Common
            socket_timeout=float(os.environ.get("ARAGORA_REDIS_SOCKET_TIMEOUT", "5.0")),
            socket_connect_timeout=float(
                os.environ.get("ARAGORA_REDIS_SOCKET_CONNECT_TIMEOUT", "5.0")
            ),
            max_connections=int(os.environ.get("ARAGORA_REDIS_MAX_CONNECTIONS", "50")),
            retry_on_timeout=os.environ.get("ARAGORA_REDIS_RETRY_ON_TIMEOUT", "true").lower()
            == "true",
            health_check_interval=int(os.environ.get("ARAGORA_REDIS_HEALTH_CHECK_INTERVAL", "30")),
            decode_responses=os.environ.get("ARAGORA_REDIS_DECODE_RESPONSES", "true").lower()
            == "true",
            # SSL
            ssl=os.environ.get("ARAGORA_REDIS_SSL", "false").lower() == "true",
            ssl_cert_reqs=os.environ.get("ARAGORA_REDIS_SSL_CERT_REQS"),
            ssl_ca_certs=os.environ.get("ARAGORA_REDIS_SSL_CA_CERTS"),
        )

    def get_parsed_sentinel_hosts(self) -> list[tuple[str, int]]:
        """
        Parse sentinel hosts into (host, port) tuples.

        Returns:
            List of (host, port) tuples for sentinel nodes
        """
        parsed: list[tuple[str, int]] = []
        for host_str in self.sentinel_hosts:
            host, port = _parse_host_port(host_str, default_port=26379)
            parsed.append((host, port))
        return parsed

    def get_parsed_cluster_nodes(self) -> list[tuple[str, int]]:
        """
        Parse cluster nodes into (host, port) tuples.

        Returns:
            List of (host, port) tuples for cluster nodes
        """
        parsed: list[tuple[str, int]] = []
        for node_str in self.cluster_nodes:
            host, port = _parse_host_port(node_str, default_port=6379)
            parsed.append((host, port))
        return parsed


def _parse_host_port(host_str: str, default_port: int = 6379) -> tuple[str, int]:
    """
    Parse a host:port string into components.

    Args:
        host_str: String in format "host:port" or "host"
        default_port: Port to use if not specified

    Returns:
        Tuple of (host, port)
    """
    if ":" in host_str:
        parts = host_str.rsplit(":", 1)
        try:
            return parts[0], int(parts[1])
        except ValueError:
            logger.warning("Invalid port in '%s', using default %s", host_str, default_port)
            return parts[0], default_port
    return host_str, default_port


def _parse_redis_url(url: str) -> tuple[str | None, int | None]:
    """
    Parse Redis URL to extract host and port.

    Args:
        url: Redis URL (e.g., redis://localhost:6379/0)

    Returns:
        Tuple of (host, port) or (None, None) if parsing fails
    """
    try:
        # Remove protocol
        if "://" in url:
            url = url.split("://", 1)[1]

        # Remove auth info
        if "@" in url:
            url = url.split("@", 1)[1]

        # Remove database path
        if "/" in url:
            url = url.split("/", 1)[0]

        # Parse host:port
        return _parse_host_port(url)
    except (ValueError, IndexError, AttributeError) as e:
        logger.debug("Failed to parse Redis URL: %s", e)
        return None, None


def get_redis_client(config: RedisHAConfig | None = None) -> Any | None:
    """
    Get appropriate synchronous Redis client based on configuration.

    This is the main entry point for obtaining a Redis client. It automatically
    selects the correct client type based on the configured mode:
    - STANDALONE: Standard redis.Redis with connection pooling
    - SENTINEL: redis.sentinel.Sentinel master connection
    - CLUSTER: redis.cluster.RedisCluster

    Args:
        config: Redis HA configuration (uses environment if not provided)

    Returns:
        Redis client or None if unavailable

    Example:
        >>> client = get_redis_client()
        >>> if client:
        ...     client.set("key", "value")
        ...     print(client.get("key"))
    """
    config = config or RedisHAConfig.from_env()

    try:
        if config.mode == RedisMode.SENTINEL:
            return _create_sentinel_client(config)
        elif config.mode == RedisMode.CLUSTER:
            return _create_cluster_client(config)
        else:
            return _create_standalone_client(config)
    except ImportError as e:
        logger.error("redis package not installed: %s. Install with: pip install redis>=4.5.0", e)
        return None
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error(
            "Failed to create Redis client (%s mode) - connection error: %s", config.mode.value, e
        )
        return None
    except ValueError as e:
        logger.error(
            "Failed to create Redis client (%s mode) - invalid config: %s", config.mode.value, e
        )
        return None


def _create_standalone_client(config: RedisHAConfig) -> Any:
    """Create standalone Redis client with connection pooling."""
    import redis

    # Build connection pool
    pool_kwargs = {
        "host": config.host,
        "port": config.port,
        "db": config.db,
        "password": config.password,
        "max_connections": config.max_connections,
        "socket_timeout": config.socket_timeout,
        "socket_connect_timeout": config.socket_connect_timeout,
        "retry_on_timeout": config.retry_on_timeout,
        "decode_responses": config.decode_responses,
        "encoding": config.encoding,
        "health_check_interval": config.health_check_interval,
    }

    # Add SSL settings if enabled
    if config.ssl:
        pool_kwargs["ssl"] = True
        if config.ssl_cert_reqs:
            pool_kwargs["ssl_cert_reqs"] = config.ssl_cert_reqs
        if config.ssl_ca_certs:
            pool_kwargs["ssl_ca_certs"] = config.ssl_ca_certs

    # Use URL if provided (overrides individual settings)
    if config.url:
        pool = redis.ConnectionPool.from_url(
            config.url,
            max_connections=config.max_connections,
            socket_timeout=config.socket_timeout,
            socket_connect_timeout=config.socket_connect_timeout,
            retry_on_timeout=config.retry_on_timeout,
            decode_responses=config.decode_responses,
            health_check_interval=config.health_check_interval,
        )
    else:
        pool_args: dict[str, Any] = pool_kwargs
        pool = redis.ConnectionPool(**pool_args)

    client = redis.Redis(connection_pool=pool)

    # Verify connection
    client.ping()
    logger.info("Connected to standalone Redis at %s:%s", config.host, config.port)

    return client


def _create_sentinel_client(config: RedisHAConfig) -> Any:
    """Create Redis Sentinel client for HA failover."""
    from redis.sentinel import Sentinel

    sentinel_hosts = config.get_parsed_sentinel_hosts()
    if not sentinel_hosts:
        raise ValueError("No sentinel hosts configured for Sentinel mode")

    # Build sentinel kwargs
    sentinel_kwargs = {
        "socket_timeout": config.sentinel_socket_timeout,
        "decode_responses": config.decode_responses,
        "encoding": config.encoding,
    }

    sentinel_password = _resolve_sentinel_password(config)
    if sentinel_password:
        sentinel_kwargs["password"] = sentinel_password

    # Build connection kwargs for master/replica connections
    connection_kwargs = {
        "socket_timeout": config.socket_timeout,
        "socket_connect_timeout": config.socket_connect_timeout,
        "retry_on_timeout": config.retry_on_timeout,
        "decode_responses": config.decode_responses,
        "encoding": config.encoding,
        "health_check_interval": config.health_check_interval,
        "db": config.db,
    }

    if config.password:
        connection_kwargs["password"] = config.password

    # Add SSL settings if enabled
    if config.ssl:
        connection_kwargs["ssl"] = True
        if config.ssl_cert_reqs:
            connection_kwargs["ssl_cert_reqs"] = config.ssl_cert_reqs
        if config.ssl_ca_certs:
            connection_kwargs["ssl_ca_certs"] = config.ssl_ca_certs

    # Create sentinel connection
    sentinel = cast(Any, Sentinel)(
        sentinel_hosts,
        sentinel_kwargs=sentinel_kwargs,
        **connection_kwargs,
    )

    # Get master connection
    master = sentinel.master_for(
        config.sentinel_master,
        socket_timeout=config.socket_timeout,
        decode_responses=config.decode_responses,
    )

    # Verify connection
    master.ping()
    logger.info(
        "Connected to Redis via Sentinel (master=%s, sentinels=%s)",
        config.sentinel_master,
        len(sentinel_hosts),
    )

    return master


def _create_cluster_client(config: RedisHAConfig) -> Any:
    """Create Redis Cluster client for horizontal scaling."""
    from redis.cluster import ClusterNode, RedisCluster

    cluster_nodes = config.get_parsed_cluster_nodes()
    if not cluster_nodes:
        raise ValueError("No cluster nodes configured for Cluster mode")

    startup_nodes = [ClusterNode(host, port) for host, port in cluster_nodes]

    # Build cluster kwargs
    cluster_kwargs = {
        "startup_nodes": startup_nodes,
        "password": config.password,
        "socket_timeout": config.socket_timeout,
        "socket_connect_timeout": config.socket_connect_timeout,
        "retry_on_timeout": config.retry_on_timeout,
        "skip_full_coverage_check": config.cluster_skip_full_coverage_check,
        "read_from_replicas": config.cluster_read_from_replicas,
        "decode_responses": config.decode_responses,
        "encoding": config.encoding,
        "health_check_interval": config.health_check_interval,
    }

    # Add SSL settings if enabled
    if config.ssl:
        cluster_kwargs["ssl"] = True
        if config.ssl_cert_reqs:
            cluster_kwargs["ssl_cert_reqs"] = config.ssl_cert_reqs
        if config.ssl_ca_certs:
            cluster_kwargs["ssl_ca_certs"] = config.ssl_ca_certs

    cluster_args: dict[str, Any] = cluster_kwargs
    client: Any = RedisCluster(**cluster_args)

    # Verify connection
    client.ping()
    logger.info("Connected to Redis Cluster (%s startup nodes)", len(cluster_nodes))

    return client


async def get_async_redis_client(config: RedisHAConfig | None = None) -> Any | None:
    """
    Get appropriate asynchronous Redis client based on configuration.

    This is the async counterpart to get_redis_client(). It returns an
    asyncio-compatible Redis client.

    Args:
        config: Redis HA configuration (uses environment if not provided)

    Returns:
        Async Redis client or None if unavailable

    Example:
        >>> client = await get_async_redis_client()
        >>> if client:
        ...     await client.set("key", "value")
        ...     value = await client.get("key")
    """
    config = config or RedisHAConfig.from_env()

    try:
        if config.mode == RedisMode.SENTINEL:
            return await _create_async_sentinel_client(config)
        elif config.mode == RedisMode.CLUSTER:
            return await _create_async_cluster_client(config)
        else:
            return await _create_async_standalone_client(config)
    except ImportError as e:
        logger.error("redis package not installed: %s. Install with: pip install redis>=4.5.0", e)
        return None
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error(
            "Failed to create async Redis client (%s mode) - connection error: %s",
            config.mode.value,
            e,
        )
        return None
    except ValueError as e:
        logger.error(
            "Failed to create async Redis client (%s mode) - invalid config: %s",
            config.mode.value,
            e,
        )
        return None


async def _create_async_standalone_client(config: RedisHAConfig) -> Any:
    """Create async standalone Redis client."""
    import redis.asyncio as aioredis

    # Build connection kwargs
    kwargs = {
        "host": config.host,
        "port": config.port,
        "db": config.db,
        "password": config.password,
        "socket_timeout": config.socket_timeout,
        "socket_connect_timeout": config.socket_connect_timeout,
        "retry_on_timeout": config.retry_on_timeout,
        "decode_responses": config.decode_responses,
        "encoding": config.encoding,
        "health_check_interval": config.health_check_interval,
        "max_connections": config.max_connections,
    }

    # Add SSL settings if enabled
    if config.ssl:
        kwargs["ssl"] = True
        if config.ssl_cert_reqs:
            kwargs["ssl_cert_reqs"] = config.ssl_cert_reqs
        if config.ssl_ca_certs:
            kwargs["ssl_ca_certs"] = config.ssl_ca_certs

    # Use URL if provided
    if config.url:
        client = aioredis.from_url(
            config.url,
            decode_responses=config.decode_responses,
            encoding=config.encoding,
            socket_timeout=config.socket_timeout,
            socket_connect_timeout=config.socket_connect_timeout,
            health_check_interval=config.health_check_interval,
            max_connections=config.max_connections,
        )
    else:
        redis_args: dict[str, Any] = kwargs
        client = aioredis.Redis(**redis_args)

    # Verify connection
    await client.ping()
    logger.info("Connected to async standalone Redis at %s:%s", config.host, config.port)

    return client


async def _create_async_sentinel_client(config: RedisHAConfig) -> Any:
    """Create async Redis Sentinel client."""
    from redis.asyncio.sentinel import Sentinel

    sentinel_hosts = config.get_parsed_sentinel_hosts()
    if not sentinel_hosts:
        raise ValueError("No sentinel hosts configured for Sentinel mode")

    # Build sentinel kwargs
    sentinel_kwargs = {
        "socket_timeout": config.sentinel_socket_timeout,
        "decode_responses": config.decode_responses,
        "encoding": config.encoding,
    }

    sentinel_password = _resolve_sentinel_password(config)
    if sentinel_password:
        sentinel_kwargs["password"] = sentinel_password

    # Build connection kwargs for master/replica connections
    connection_kwargs = {
        "socket_timeout": config.socket_timeout,
        "socket_connect_timeout": config.socket_connect_timeout,
        "retry_on_timeout": config.retry_on_timeout,
        "decode_responses": config.decode_responses,
        "encoding": config.encoding,
        "health_check_interval": config.health_check_interval,
        "db": config.db,
    }

    if config.password:
        connection_kwargs["password"] = config.password

    # Add SSL settings if enabled
    if config.ssl:
        connection_kwargs["ssl"] = True
        if config.ssl_cert_reqs:
            connection_kwargs["ssl_cert_reqs"] = config.ssl_cert_reqs
        if config.ssl_ca_certs:
            connection_kwargs["ssl_ca_certs"] = config.ssl_ca_certs

    # Create sentinel connection
    sentinel = cast(Any, Sentinel)(
        sentinel_hosts,
        sentinel_kwargs=sentinel_kwargs,
        **connection_kwargs,
    )

    # Get master connection
    master = sentinel.master_for(
        config.sentinel_master,
        decode_responses=config.decode_responses,
    )

    # Verify connection
    await master.ping()
    logger.info(
        "Connected to async Redis via Sentinel (master=%s, sentinels=%s)",
        config.sentinel_master,
        len(sentinel_hosts),
    )

    return master


async def _create_async_cluster_client(config: RedisHAConfig) -> Any:
    """Create async Redis Cluster client."""
    from redis.asyncio.cluster import ClusterNode, RedisCluster

    cluster_nodes = config.get_parsed_cluster_nodes()
    if not cluster_nodes:
        raise ValueError("No cluster nodes configured for Cluster mode")

    startup_nodes = [ClusterNode(host, port) for host, port in cluster_nodes]

    # Build cluster kwargs
    cluster_kwargs = {
        "startup_nodes": startup_nodes,
        "password": config.password,
        "socket_timeout": config.socket_timeout,
        "socket_connect_timeout": config.socket_connect_timeout,
        "retry_on_timeout": config.retry_on_timeout,
        "skip_full_coverage_check": config.cluster_skip_full_coverage_check,
        "read_from_replicas": config.cluster_read_from_replicas,
        "decode_responses": config.decode_responses,
        "encoding": config.encoding,
        "health_check_interval": config.health_check_interval,
    }

    # Add SSL settings if enabled
    if config.ssl:
        cluster_kwargs["ssl"] = True
        if config.ssl_cert_reqs:
            cluster_kwargs["ssl_cert_reqs"] = config.ssl_cert_reqs
        if config.ssl_ca_certs:
            cluster_kwargs["ssl_ca_certs"] = config.ssl_ca_certs

    async_cluster_args: dict[str, Any] = cluster_kwargs
    client: Any = RedisCluster(**async_cluster_args)

    # Verify connection - RedisCluster.ping() returns coroutine but type stubs don't reflect this
    await client.ping()
    logger.info("Connected to async Redis Cluster (%s startup nodes)", len(cluster_nodes))

    return client


# =============================================================================
# Singleton Management
# =============================================================================

_sync_client: Any | None = None
_async_client: Any | None = None
_lock = threading.Lock()


def get_cached_redis_client(config: RedisHAConfig | None = None) -> Any | None:
    """
    Get or create a cached synchronous Redis client (singleton pattern).

    This is useful when you want to share a single Redis connection across
    your application. For custom configurations, use get_redis_client() instead.

    Args:
        config: Redis HA configuration (only used on first call)

    Returns:
        Cached Redis client or None if unavailable
    """
    global _sync_client

    if _sync_client is not None:
        return _sync_client

    with _lock:
        if _sync_client is None:
            _sync_client = get_redis_client(config)
        return _sync_client


async def get_cached_async_redis_client(
    config: RedisHAConfig | None = None,
) -> Any | None:
    """
    Get or create a cached asynchronous Redis client (singleton pattern).

    This is useful when you want to share a single async Redis connection
    across your application.

    Args:
        config: Redis HA configuration (only used on first call)

    Returns:
        Cached async Redis client or None if unavailable
    """
    global _async_client

    if _async_client is not None:
        return _async_client

    with _lock:
        if _async_client is None:
            _async_client = await get_async_redis_client(config)
        return _async_client


def reset_cached_clients() -> None:
    """
    Reset cached Redis clients (for testing or reconfiguration).

    This closes any existing connections and clears the singleton cache.
    """
    global _sync_client, _async_client

    with _lock:
        if _sync_client is not None:
            try:
                _sync_client.close()
            except (ConnectionError, TimeoutError, OSError, AttributeError) as e:
                logger.debug("Error closing sync Redis client: %s", e)
            _sync_client = None

        if _async_client is not None:
            # Note: async close should be awaited, but we're in sync context
            # The connection will be cleaned up by garbage collector
            _async_client = None


# =============================================================================
# Health Check Utilities
# =============================================================================


def check_redis_health(config: RedisHAConfig | None = None) -> dict:
    """
    Check Redis connection health and return diagnostic information.

    Args:
        config: Redis HA configuration (uses environment if not provided)

    Returns:
        Dictionary with health status and diagnostic info
    """
    config = config or RedisHAConfig.from_env()
    result: dict[str, Any] = {
        "healthy": False,
        "mode": config.mode.value,
        "error": None,
        "latency_ms": None,
        "info": {},
    }

    try:
        import time

        start = time.monotonic()
        client = get_redis_client(config)

        if client is None:
            result["error"] = "Failed to create client"
            return result

        # Ping to check connectivity
        client.ping()
        result["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
        result["healthy"] = True

        # Get server info
        try:
            info = client.info()
            result["info"] = {
                "redis_version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "role": info.get("role", "unknown"),
            }

            # Add cluster-specific info
            if config.mode == RedisMode.CLUSTER:
                try:
                    cluster_info = client.cluster_info()
                    result["info"]["cluster_state"] = cluster_info.get("cluster_state", "unknown")
                    result["info"]["cluster_slots_ok"] = cluster_info.get("cluster_slots_ok", 0)
                except (ConnectionError, TimeoutError, OSError, AttributeError, KeyError) as e:
                    logger.warning("redis_ha operation failed: %s", e)

            # Add sentinel-specific info (check connected slaves)
            if config.mode == RedisMode.SENTINEL:
                result["info"]["connected_slaves"] = info.get("connected_slaves", 0)

        except (ConnectionError, TimeoutError, OSError, KeyError, TypeError) as e:
            logger.warning("Failed to retrieve Redis info: %s", e)
            result["info"]["error"] = "Failed to retrieve server info"

    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
        logger.warning("Redis health check failed: %s", e)
        result["error"] = "Redis connection failed"

    return result


async def check_async_redis_health(config: RedisHAConfig | None = None) -> dict:
    """
    Check async Redis connection health and return diagnostic information.

    Args:
        config: Redis HA configuration (uses environment if not provided)

    Returns:
        Dictionary with health status and diagnostic info
    """
    config = config or RedisHAConfig.from_env()
    result: dict[str, Any] = {
        "healthy": False,
        "mode": config.mode.value,
        "error": None,
        "latency_ms": None,
        "info": {},
    }

    try:
        import time

        start = time.monotonic()
        client = await get_async_redis_client(config)

        if client is None:
            result["error"] = "Failed to create client"
            return result

        # Ping to check connectivity
        await client.ping()
        result["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
        result["healthy"] = True

        # Get server info
        try:
            info = await client.info()
            result["info"] = {
                "redis_version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "role": info.get("role", "unknown"),
            }
        except (ConnectionError, TimeoutError, OSError, KeyError, TypeError) as e:
            logger.warning("Failed to retrieve async Redis info: %s", e)
            result["info"]["error"] = "Failed to retrieve server info"

    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
        logger.warning("Async Redis health check failed: %s", e)
        result["error"] = "Redis connection failed"

    return result


# Backward-compatible aliases
get_cached_client = get_cached_redis_client
close_cached_clients = reset_cached_clients

__all__ = [
    # Enums and config
    "RedisMode",
    "RedisHAConfig",
    # Client factories
    "get_redis_client",
    "get_async_redis_client",
    # Singleton management
    "get_cached_redis_client",
    "get_cached_async_redis_client",
    "reset_cached_clients",
    # Backward-compatible aliases
    "get_cached_client",
    "close_cached_clients",
    # Health checks
    "check_redis_health",
    "check_async_redis_health",
]
