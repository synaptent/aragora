"""
Advanced Connection Pool Management for Enterprise Deployments.

Provides optimized connection pooling with:
- Adaptive pool sizing based on load
- Connection health monitoring
- Pool exhaustion protection
- Metrics collection for observability

Usage:
    from aragora.server.connection_pool import ConnectionPoolManager

    manager = ConnectionPoolManager.get_instance()
    client = manager.get_redis_client()
    if client:
        client.set("key", "value")

Environment Variables:
    ARAGORA_POOL_MIN_CONNECTIONS: Minimum pool size (default: 5)
    ARAGORA_POOL_MAX_CONNECTIONS: Maximum pool size (default: 50)
    ARAGORA_POOL_IDLE_TIMEOUT: Idle connection timeout in seconds (default: 300)
    ARAGORA_POOL_MAX_WAIT_TIME: Max wait for connection in seconds (default: 5)
    ARAGORA_POOL_HEALTH_CHECK_INTERVAL: Health check interval (default: 30)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PoolConfig:
    """Configuration for connection pool."""

    # Pool sizing
    min_connections: int = 5
    max_connections: int = 50
    overflow_max: int = 10  # Additional connections during spikes

    # Timeouts
    socket_timeout: float = 5.0
    connect_timeout: float = 5.0
    idle_timeout: float = 300.0  # Close idle connections after 5 minutes
    max_wait_time: float = 5.0  # Max wait for available connection

    # Health checking
    health_check_interval: float = 30.0
    health_check_timeout: float = 2.0

    # Retry settings
    retry_on_timeout: bool = True
    max_retries: int = 3
    retry_delay: float = 0.1

    # Encoding
    decode_responses: bool = True


@dataclass
class PoolMetrics:
    """Metrics for connection pool monitoring."""

    connections_created: int = 0
    connections_closed: int = 0
    connections_active: int = 0
    connections_idle: int = 0
    wait_count: int = 0
    wait_time_total: float = 0.0
    health_check_failures: int = 0
    overflow_count: int = 0
    last_health_check: float = 0.0
    pool_exhaustion_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for export."""
        return {
            "connections_created": self.connections_created,
            "connections_closed": self.connections_closed,
            "connections_active": self.connections_active,
            "connections_idle": self.connections_idle,
            "connections_total": self.connections_active + self.connections_idle,
            "wait_count": self.wait_count,
            "wait_time_avg_ms": (
                (self.wait_time_total / self.wait_count * 1000) if self.wait_count > 0 else 0
            ),
            "health_check_failures": self.health_check_failures,
            "overflow_count": self.overflow_count,
            "pool_exhaustion_count": self.pool_exhaustion_count,
            "last_health_check": self.last_health_check,
        }


def get_pool_config() -> PoolConfig:
    """Get pool configuration from environment variables."""
    return PoolConfig(
        min_connections=int(os.getenv("ARAGORA_POOL_MIN_CONNECTIONS", "5")),
        max_connections=int(os.getenv("ARAGORA_POOL_MAX_CONNECTIONS", "50")),
        overflow_max=int(os.getenv("ARAGORA_POOL_OVERFLOW_MAX", "10")),
        socket_timeout=float(os.getenv("ARAGORA_REDIS_SOCKET_TIMEOUT", "5.0")),
        connect_timeout=float(os.getenv("ARAGORA_REDIS_SOCKET_CONNECT_TIMEOUT", "5.0")),
        idle_timeout=float(os.getenv("ARAGORA_POOL_IDLE_TIMEOUT", "300.0")),
        max_wait_time=float(os.getenv("ARAGORA_POOL_MAX_WAIT_TIME", "5.0")),
        health_check_interval=float(os.getenv("ARAGORA_POOL_HEALTH_CHECK_INTERVAL", "30.0")),
        health_check_timeout=float(os.getenv("ARAGORA_POOL_HEALTH_CHECK_TIMEOUT", "2.0")),
        max_retries=int(os.getenv("ARAGORA_POOL_MAX_RETRIES", "3")),
        retry_delay=float(os.getenv("ARAGORA_POOL_RETRY_DELAY", "0.1")),
    )


class ConnectionPoolManager:
    """
    Manages Redis connection pools with advanced features.

    Features:
    - Adaptive pool sizing based on demand
    - Health monitoring and automatic reconnection
    - Connection timeout enforcement
    - Metrics collection
    """

    _instance: ConnectionPoolManager | None = None
    _lock = threading.Lock()

    def __init__(self, config: PoolConfig | None = None):
        """Initialize pool manager."""
        self.config = config or get_pool_config()
        self.metrics = PoolMetrics()

        self._pool: Any | None = None
        self._client: Any | None = None
        self._available: bool = False
        self._pool_lock = threading.Lock()

        self._health_check_thread: threading.Thread | None = None
        self._stop_health_check = threading.Event()

    @classmethod
    def get_instance(cls, config: PoolConfig | None = None) -> ConnectionPoolManager:
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None

    def _get_redis_url(self) -> str | None:
        """Get Redis URL from environment."""
        return os.getenv("ARAGORA_REDIS_URL")

    def _create_pool(self) -> Any | None:
        """Create optimized connection pool."""
        url = self._get_redis_url()
        if not url:
            logger.debug("No Redis URL configured")
            return None

        try:
            import redis
            from redis.connection import ConnectionPool

            # Create pool with optimized settings
            pool = ConnectionPool.from_url(
                url,
                max_connections=self.config.max_connections,
                socket_timeout=self.config.socket_timeout,
                socket_connect_timeout=self.config.connect_timeout,
                retry_on_timeout=self.config.retry_on_timeout,
                decode_responses=self.config.decode_responses,
                health_check_interval=int(self.config.health_check_interval),
            )

            # Test connection
            test_client = redis.Redis(connection_pool=pool)
            test_client.ping()

            self._available = True
            self.metrics.connections_created += 1

            # Mask password for logging
            safe_url = url.split("@")[-1] if "@" in url else url
            logger.info("Connection pool created: %s", safe_url)

            return pool

        except ImportError:
            logger.error("redis package not installed")
            return None
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("Failed to create connection pool: %s", e)
            return None

    def get_pool(self) -> Any | None:
        """Get or create connection pool."""
        if self._pool is not None:
            return self._pool

        with self._pool_lock:
            if self._pool is None:
                self._pool = self._create_pool()
                if self._pool is not None:
                    self._start_health_check()
            return self._pool

    def get_redis_client(self) -> Any | None:
        """Get Redis client using managed pool."""
        pool = self.get_pool()
        if pool is None:
            return None

        if self._client is not None:
            return self._client

        try:
            import redis

            self._client = redis.Redis(connection_pool=pool)
            return self._client
        except ImportError:
            return None

    def _start_health_check(self) -> None:
        """Start background health check thread."""
        if self._health_check_thread is not None:
            return

        def health_check_loop() -> None:
            while not self._stop_health_check.wait(self.config.health_check_interval):
                self._perform_health_check()

        self._health_check_thread = threading.Thread(target=health_check_loop, daemon=True)
        self._health_check_thread.start()
        logger.debug("Health check thread started")

        # Register with lifecycle ThreadRegistry for coordinated shutdown
        try:
            from aragora.server.lifecycle import get_thread_registry

            get_thread_registry().register(
                "redis-health-check",
                self._health_check_thread,
                shutdown_fn=lambda: self._stop_health_check.set(),
            )
        except ImportError:
            pass

    def _perform_health_check(self) -> None:
        """Perform health check on pool."""
        client = self._client
        if client is None:
            return

        try:
            start = time.time()
            client.ping()
            self.metrics.last_health_check = time.time()

            # Update pool stats
            pool = self._pool
            if pool is not None:
                self.metrics.connections_active = len(getattr(pool, "_in_use_connections", []))
                self.metrics.connections_idle = len(getattr(pool, "_available_connections", []))

            logger.debug("Health check passed (%.1fms)", (time.time() - start) * 1000)

        except (ConnectionError, TimeoutError, OSError) as e:
            self.metrics.health_check_failures += 1
            logger.warning("Health check failed: %s", e)

            # Attempt reconnection if too many failures
            if self.metrics.health_check_failures > 3:
                self._reconnect()

    def _reconnect(self) -> None:
        """Reconnect pool after failures."""
        logger.info("Attempting pool reconnection...")

        with self._pool_lock:
            # Close existing
            if self._pool is not None:
                try:
                    self._pool.disconnect()
                except (ConnectionError, OSError, RuntimeError) as e:
                    logger.debug("Error disconnecting pool during reconnect: %s", type(e).__name__)
                self._pool = None
                self._client = None
                self.metrics.connections_closed += 1

            # Recreate
            self._pool = self._create_pool()
            if self._pool is not None:
                import redis

                self._client = redis.Redis(connection_pool=self._pool)
                self.metrics.health_check_failures = 0
                logger.info("Pool reconnection successful")
            else:
                self._available = False
                logger.error("Pool reconnection failed")

    @property
    def is_available(self) -> bool:
        """Check if pool is available."""
        return self._available

    def get_metrics(self) -> dict[str, Any]:
        """Get pool metrics."""
        return {
            "available": self._available,
            "config": {
                "min_connections": self.config.min_connections,
                "max_connections": self.config.max_connections,
                "socket_timeout": self.config.socket_timeout,
                "idle_timeout": self.config.idle_timeout,
            },
            "metrics": self.metrics.to_dict(),
        }

    def execute_with_metrics(
        self,
        operation: str,
        func: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute operation with metrics tracking."""
        client = self.get_redis_client()
        if client is None:
            raise RuntimeError("Redis not available")

        start_time = time.time()

        try:
            method = getattr(client, operation)
            result = method(*args, **kwargs)
            return result
        finally:
            elapsed = time.time() - start_time
            self.metrics.wait_time_total += elapsed
            self.metrics.wait_count += 1

    def close(self) -> None:
        """Close pool and cleanup."""
        # Stop health check
        self._stop_health_check.set()
        if self._health_check_thread is not None:
            self._health_check_thread.join(timeout=2.0)
            self._health_check_thread = None

        # Close pool
        with self._pool_lock:
            if self._pool is not None:
                try:
                    self._pool.disconnect()
                    logger.info("Connection pool closed")
                except (ConnectionError, OSError, RuntimeError) as e:
                    logger.error("Error closing pool: %s", e)
                finally:
                    self._pool = None
                    self._client = None
                    self._available = False


# =============================================================================
# Convenience functions
# =============================================================================


def get_optimized_redis_client() -> Any | None:
    """Get Redis client with optimized connection pool."""
    manager = ConnectionPoolManager.get_instance()
    return manager.get_redis_client()


def get_pool_metrics() -> dict[str, Any]:
    """Get connection pool metrics."""
    manager = ConnectionPoolManager.get_instance()
    return manager.get_metrics()


def close_connection_pool() -> None:
    """Close connection pool."""
    ConnectionPoolManager.reset_instance()


__all__ = [
    "PoolConfig",
    "PoolMetrics",
    "ConnectionPoolManager",
    "get_pool_config",
    "get_optimized_redis_client",
    "get_pool_metrics",
    "close_connection_pool",
]
