"""
Tests for aragora.persistence.postgres_pool - PostgreSQL connection pool with read replica support.

Tests cover:
- Pool initialization (primary and replicas)
- Connection acquisition and routing
- Timeout handling
- Health checks and replica selection
- Connection wrapper metrics
- Pool statistics
- Concurrent acquisition
- Global pool management
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.persistence.postgres_pool import (
    ConnectionWrapper,
    PoolStats,
    ReplicaAwarePool,
    ReplicaHealth,
    _parse_replica_dsns,
    close_pool,
    configure_pool,
    get_pool,
)


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def mock_asyncpg_pool():
    """Create a mock asyncpg pool."""
    pool = MagicMock()
    pool.acquire = AsyncMock()
    pool.release = AsyncMock()
    pool.close = AsyncMock()
    pool.get_size = MagicMock(return_value=5)
    pool.get_idle_size = MagicMock(return_value=3)
    return pool


@pytest.fixture
def mock_asyncpg_connection():
    """Create a mock asyncpg connection."""
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[{"id": 1, "name": "test"}])
    conn.fetchrow = AsyncMock(return_value={"id": 1, "name": "test"})
    conn.fetchval = AsyncMock(return_value=42)
    conn.execute = AsyncMock(return_value="INSERT 1")
    conn.executemany = AsyncMock(return_value=None)
    return conn


@pytest.fixture
def mock_create_pool(mock_asyncpg_pool):
    """Patch asyncpg.create_pool to return our mock."""
    with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock:
        mock.return_value = mock_asyncpg_pool
        yield mock


@pytest.fixture
async def initialized_pool(mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection):
    """Create an initialized ReplicaAwarePool with mocked asyncpg."""
    mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

    pool = ReplicaAwarePool(
        primary_dsn="postgresql://primary:5432/db",
        replica_dsns=["postgresql://replica1:5432/db", "postgresql://replica2:5432/db"],
        min_size=2,
        max_size=10,
        health_check_interval=30.0,
    )
    await pool.initialize()
    yield pool
    await pool.close()


@pytest.fixture(autouse=True)
def reset_global_pool():
    """Reset global pool state before each test."""
    import aragora.persistence.postgres_pool as module

    module._pool = None
    yield
    module._pool = None


# ===========================================================================
# Test Helper Functions
# ===========================================================================


class TestParseReplicaDsns:
    """Tests for _parse_replica_dsns helper function."""

    def test_empty_string(self):
        """Empty string returns empty list."""
        assert _parse_replica_dsns("") == []

    def test_whitespace_only(self):
        """Whitespace-only string returns empty list."""
        assert _parse_replica_dsns("   ") == []

    def test_single_dsn(self):
        """Single DSN is parsed correctly."""
        result = _parse_replica_dsns("postgresql://host:5432/db")
        assert result == ["postgresql://host:5432/db"]

    def test_multiple_dsns(self):
        """Multiple comma-separated DSNs are parsed."""
        result = _parse_replica_dsns("postgresql://host1:5432/db,postgresql://host2:5432/db")
        assert result == [
            "postgresql://host1:5432/db",
            "postgresql://host2:5432/db",
        ]

    def test_strips_whitespace(self):
        """Whitespace around DSNs is stripped."""
        result = _parse_replica_dsns(
            "  postgresql://host1:5432/db  ,  postgresql://host2:5432/db  "
        )
        assert result == [
            "postgresql://host1:5432/db",
            "postgresql://host2:5432/db",
        ]

    def test_ignores_empty_entries(self):
        """Empty entries are ignored."""
        result = _parse_replica_dsns("postgresql://host1:5432/db,,postgresql://host2:5432/db,")
        assert result == [
            "postgresql://host1:5432/db",
            "postgresql://host2:5432/db",
        ]


# ===========================================================================
# Test PoolStats Dataclass
# ===========================================================================


class TestPoolStats:
    """Tests for PoolStats dataclass."""

    def test_default_values(self):
        """Default values are all zero."""
        stats = PoolStats()
        assert stats.total_connections == 0
        assert stats.active_connections == 0
        assert stats.idle_connections == 0
        assert stats.wait_count == 0
        assert stats.total_queries == 0
        assert stats.read_queries == 0
        assert stats.write_queries == 0

    def test_custom_values(self):
        """Custom values are stored correctly."""
        stats = PoolStats(
            total_connections=10,
            active_connections=5,
            idle_connections=5,
            wait_count=100,
            total_queries=1000,
            read_queries=800,
            write_queries=200,
        )
        assert stats.total_connections == 10
        assert stats.active_connections == 5
        assert stats.idle_connections == 5
        assert stats.wait_count == 100
        assert stats.total_queries == 1000
        assert stats.read_queries == 800
        assert stats.write_queries == 200

    def test_to_dict(self):
        """to_dict returns correct dictionary."""
        stats = PoolStats(
            total_connections=10,
            active_connections=5,
            idle_connections=5,
            wait_count=100,
            total_queries=1000,
            read_queries=800,
            write_queries=200,
        )
        result = stats.to_dict()

        assert result == {
            "total_connections": 10,
            "active_connections": 5,
            "idle_connections": 5,
            "wait_count": 100,
            "total_queries": 1000,
            "read_queries": 800,
            "write_queries": 200,
        }

    def test_pool_stats_calculation(self):
        """Verify stats aggregation works correctly."""
        stats = PoolStats()

        # Simulate query counting
        stats.total_queries += 10
        stats.read_queries += 7
        stats.write_queries += 3

        assert stats.total_queries == 10
        assert stats.read_queries == 7
        assert stats.write_queries == 3

        # Verify consistency
        assert stats.read_queries + stats.write_queries == stats.total_queries


# ===========================================================================
# Test ReplicaHealth Dataclass
# ===========================================================================


class TestReplicaHealth:
    """Tests for ReplicaHealth dataclass."""

    def test_default_values(self):
        """Default values are correct."""
        health = ReplicaHealth(dsn="postgresql://host:5432/db")

        assert health.dsn == "postgresql://host:5432/db"
        assert health.healthy is True
        assert health.last_check == 0.0
        assert health.consecutive_failures == 0
        assert health.latency_ms == 0.0

    def test_custom_values(self):
        """Custom values are stored correctly."""
        health = ReplicaHealth(
            dsn="postgresql://host:5432/db",
            healthy=False,
            last_check=1234567890.0,
            consecutive_failures=5,
            latency_ms=50.5,
        )

        assert health.dsn == "postgresql://host:5432/db"
        assert health.healthy is False
        assert health.last_check == 1234567890.0
        assert health.consecutive_failures == 5
        assert health.latency_ms == 50.5


# ===========================================================================
# Test ReplicaAwarePool Initialization
# ===========================================================================


class TestPoolInitialization:
    """Tests for ReplicaAwarePool initialization."""

    def test_pool_initialization_creates_primary_pool(self, mock_create_pool, mock_asyncpg_pool):
        """Verify primary pool is created during initialization."""
        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            min_size=2,
            max_size=10,
        )

        # Run initialization
        asyncio.run(pool.initialize())

        # Verify create_pool was called for primary
        mock_create_pool.assert_called_once_with(
            "postgresql://primary:5432/db",
            min_size=2,
            max_size=10,
        )

        # Verify primary pool is set
        assert pool._primary_pool == mock_asyncpg_pool
        assert pool._initialized is True

        # Cleanup
        asyncio.run(pool.close())

    def test_pool_initialization_with_replicas(self, mock_create_pool, mock_asyncpg_pool):
        """Verify replica pools are created during initialization."""
        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=[
                "postgresql://replica1:5432/db",
                "postgresql://replica2:5432/db",
            ],
            min_size=2,
            max_size=10,
        )

        # Run initialization
        asyncio.run(pool.initialize())

        # Verify create_pool was called for primary and both replicas
        assert mock_create_pool.call_count == 3

        # Verify replica pools are stored
        assert len(pool._replica_pools) == 2

        # Verify replica health tracking is initialized
        assert len(pool._replica_health) == 2
        assert "postgresql://replica1:5432/db" in pool._replica_health
        assert "postgresql://replica2:5432/db" in pool._replica_health

        # Verify health task is started
        assert pool._health_task is not None

        # Cleanup
        asyncio.run(pool.close())

    def test_initialization_is_idempotent(self, mock_create_pool, mock_asyncpg_pool):
        """Multiple initialize calls only create pools once."""
        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )

        # Initialize twice
        asyncio.run(pool.initialize())
        asyncio.run(pool.initialize())

        # Should only call create_pool once
        assert mock_create_pool.call_count == 1

        # Cleanup
        asyncio.run(pool.close())

    def test_initialization_without_asyncpg(self):
        """Initialization handles missing asyncpg gracefully."""
        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )

        with patch.dict("sys.modules", {"asyncpg": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'asyncpg'")):
                # Should not raise, just log warning
                asyncio.run(pool.initialize())

        # Pool should not be initialized
        assert pool._primary_pool is None

    def test_initialization_with_failed_replica(self, mock_create_pool, mock_asyncpg_pool):
        """Failed replica initialization doesn't prevent primary from working."""
        # Make second replica fail
        call_count = [0]

        async def mock_create(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 3:  # Third call is second replica
                raise ConnectionError("Failed to connect")
            return mock_asyncpg_pool

        mock_create_pool.side_effect = mock_create

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=[
                "postgresql://replica1:5432/db",
                "postgresql://replica2:5432/db",
            ],
        )

        # Should not raise
        asyncio.run(pool.initialize())

        # Primary should work
        assert pool._primary_pool is not None

        # Only one replica should be available
        assert len(pool._replica_pools) == 1

        # Cleanup
        asyncio.run(pool.close())


# ===========================================================================
# Test Connection Acquisition
# ===========================================================================


class TestConnectionAcquisition:
    """Tests for connection acquisition."""

    @pytest.mark.asyncio
    async def test_acquire_connection_from_primary(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Basic connection acquisition from primary pool."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )
        await pool.initialize()

        async with pool.acquire() as conn:
            assert conn is not None
            assert isinstance(conn, ConnectionWrapper)
            assert conn._is_replica is False

        # Verify acquire and release were called
        mock_asyncpg_pool.acquire.assert_called_once()
        mock_asyncpg_pool.release.assert_called_once_with(mock_asyncpg_connection)

        await pool.close()

    @pytest.mark.asyncio
    async def test_acquire_readonly_routes_to_replica(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Verify readonly=True routes to replicas when available."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=["postgresql://replica1:5432/db"],
        )
        await pool.initialize()

        # Acquire readonly connection
        async with pool.acquire(readonly=True) as conn:
            assert conn is not None
            assert conn._is_replica is True

        await pool.close()

    @pytest.mark.asyncio
    async def test_acquire_readonly_falls_back_to_primary(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Readonly acquisition falls back to primary when no replicas."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )
        await pool.initialize()

        # Acquire readonly connection (no replicas configured)
        async with pool.acquire(readonly=True) as conn:
            assert conn is not None
            assert conn._is_replica is False  # Falls back to primary

        await pool.close()

    @pytest.mark.asyncio
    async def test_acquire_timeout_raises_error(self, mock_create_pool, mock_asyncpg_pool):
        """Timeout during acquisition raises TimeoutError."""

        # Make acquire hang forever
        async def slow_acquire():
            await asyncio.sleep(10)

        mock_asyncpg_pool.acquire.side_effect = slow_acquire

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )
        await pool.initialize()

        with pytest.raises(asyncio.TimeoutError):
            async with pool.acquire(timeout=0.1):
                pass

        await pool.close()

    @pytest.mark.asyncio
    async def test_acquire_without_initialization_auto_initializes(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Acquiring without explicit initialization auto-initializes."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )

        # Don't call initialize explicitly
        async with pool.acquire() as conn:
            assert conn is not None

        # Should have auto-initialized
        assert pool._initialized is True

        await pool.close()

    @pytest.mark.asyncio
    async def test_acquire_without_primary_raises_error(self, mock_create_pool):
        """Acquiring without primary pool raises RuntimeError."""
        pool = ReplicaAwarePool()  # No DSN

        # Force initialization state without primary pool
        pool._initialized = True
        pool._primary_pool = None

        with pytest.raises(RuntimeError, match="Primary pool not initialized"):
            async with pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_acquire_increments_wait_count(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Wait count is incremented on acquisition."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )
        await pool.initialize()

        initial_wait = pool._stats.wait_count

        async with pool.acquire():
            pass

        assert pool._stats.wait_count == initial_wait + 1

        await pool.close()

    @pytest.mark.asyncio
    async def test_acquire_tracks_active_connections(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Active connection count is tracked."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )
        await pool.initialize()

        assert pool._stats.active_connections == 0

        async with pool.acquire():
            assert pool._stats.active_connections == 1

        # After context exit, count decreases
        assert pool._stats.active_connections == 0

        await pool.close()


# ===========================================================================
# Test Health Checks
# ===========================================================================


class TestHealthChecks:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_marks_unhealthy_replica(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Health check marks replica as unhealthy after consecutive failures."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection
        mock_asyncpg_connection.fetchval = AsyncMock(
            side_effect=ConnectionError("Connection failed")
        )

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=["postgresql://replica1:5432/db"],
            health_check_interval=0.1,
        )
        await pool.initialize()

        # Get the replica health object
        dsn = "postgresql://replica1:5432/db"
        health = pool._replica_health[dsn]

        # Initially healthy
        assert health.healthy is True

        # Manually trigger health check multiple times
        for _ in range(3):
            await pool._check_replica_health()

        # Should be marked unhealthy after 3 consecutive failures
        assert health.healthy is False
        assert health.consecutive_failures >= 3

        await pool.close()

    @pytest.mark.asyncio
    async def test_health_check_restores_healthy_replica(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Health check restores replica to healthy state."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection
        mock_asyncpg_connection.fetchval = AsyncMock(return_value=1)

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=["postgresql://replica1:5432/db"],
        )
        await pool.initialize()

        dsn = "postgresql://replica1:5432/db"
        health = pool._replica_health[dsn]

        # Manually mark as unhealthy
        health.healthy = False
        health.consecutive_failures = 5

        # Run health check (should succeed)
        await pool._check_replica_health()

        # Should be restored to healthy
        assert health.healthy is True
        assert health.consecutive_failures == 0
        assert health.latency_ms > 0  # Latency recorded

        await pool.close()

    @pytest.mark.asyncio
    async def test_unhealthy_replica_excluded_from_selection(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Unhealthy replicas are excluded from load balancing."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=[
                "postgresql://replica1:5432/db",
                "postgresql://replica2:5432/db",
            ],
        )
        await pool.initialize()

        # Mark all replicas as unhealthy
        for health in pool._replica_health.values():
            health.healthy = False

        # Should return None (no healthy replicas)
        selected = pool._select_healthy_replica()
        assert selected is None

        # Acquire readonly should fall back to primary
        async with pool.acquire(readonly=True) as conn:
            assert conn._is_replica is False

        await pool.close()

    @pytest.mark.asyncio
    async def test_healthy_replica_count_property(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """healthy_replica_count property returns correct count."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=[
                "postgresql://replica1:5432/db",
                "postgresql://replica2:5432/db",
            ],
        )
        await pool.initialize()

        # All healthy initially
        assert pool.healthy_replica_count == 2

        # Mark one unhealthy
        dsns = list(pool._replica_health.keys())
        pool._replica_health[dsns[0]].healthy = False

        assert pool.healthy_replica_count == 1

        await pool.close()


# ===========================================================================
# Test ConnectionWrapper
# ===========================================================================


class TestConnectionWrapper:
    """Tests for ConnectionWrapper class."""

    def test_connection_wrapper_records_metrics(self, mock_asyncpg_connection):
        """Verify metrics are recorded for queries."""
        pool = ReplicaAwarePool(primary_dsn="postgresql://primary:5432/db")
        wrapper = ConnectionWrapper(mock_asyncpg_connection, pool, is_replica=False)

        initial_total = pool._stats.total_queries
        initial_read = pool._stats.read_queries
        initial_write = pool._stats.write_queries

        # Execute various operations
        asyncio.run(wrapper.fetch("SELECT 1"))
        asyncio.run(wrapper.fetchrow("SELECT 1"))
        asyncio.run(wrapper.fetchval("SELECT 1"))
        asyncio.run(wrapper.execute("INSERT INTO x"))
        asyncio.run(wrapper.executemany("INSERT INTO x", []))

        # Verify metrics
        assert pool._stats.total_queries == initial_total + 5
        # fetch/fetchrow/fetchval on non-replica count as writes (readonly=False in wrapper)
        # execute/executemany always count as writes
        assert pool._stats.write_queries == initial_write + 5

    def test_connection_wrapper_replica_metrics(self, mock_asyncpg_connection):
        """Replica wrapper records read queries."""
        pool = ReplicaAwarePool(primary_dsn="postgresql://primary:5432/db")
        wrapper = ConnectionWrapper(mock_asyncpg_connection, pool, is_replica=True)

        initial_read = pool._stats.read_queries

        # Execute fetch operations on replica
        asyncio.run(wrapper.fetch("SELECT 1"))
        asyncio.run(wrapper.fetchrow("SELECT 1"))
        asyncio.run(wrapper.fetchval("SELECT 1"))

        # Should count as read queries
        assert pool._stats.read_queries == initial_read + 3

    def test_connection_wrapper_forwards_attributes(self, mock_asyncpg_connection):
        """Unknown attributes are forwarded to underlying connection."""
        pool = ReplicaAwarePool(primary_dsn="postgresql://primary:5432/db")
        wrapper = ConnectionWrapper(mock_asyncpg_connection, pool, is_replica=False)

        # Add custom attribute to mock
        mock_asyncpg_connection.custom_attr = "test_value"

        # Should be accessible through wrapper
        assert wrapper.custom_attr == "test_value"

    def test_connection_wrapper_exposes_underlying_connection(self, mock_asyncpg_connection):
        """connection property exposes underlying connection."""
        pool = ReplicaAwarePool(primary_dsn="postgresql://primary:5432/db")
        wrapper = ConnectionWrapper(mock_asyncpg_connection, pool, is_replica=False)

        assert wrapper.connection is mock_asyncpg_connection


# ===========================================================================
# Test Concurrent Acquisition
# ===========================================================================


class TestConcurrentAcquisition:
    """Tests for concurrent connection acquisition."""

    @pytest.mark.asyncio
    async def test_concurrent_acquisition(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Multiple concurrent acquisitions work correctly."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )
        await pool.initialize()

        async def acquire_and_use():
            async with pool.acquire() as conn:
                await conn.fetch("SELECT 1")
                await asyncio.sleep(0.01)  # Simulate some work
                return True

        # Run multiple concurrent acquisitions
        results = await asyncio.gather(*[acquire_and_use() for _ in range(10)])

        assert all(results)
        assert pool._stats.total_queries == 10

        await pool.close()

    @pytest.mark.asyncio
    async def test_concurrent_readonly_and_write(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Concurrent readonly and write acquisitions work correctly."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=["postgresql://replica1:5432/db"],
        )
        await pool.initialize()

        async def read_operation():
            async with pool.acquire(readonly=True) as conn:
                await conn.fetch("SELECT 1")
                return "read"

        async def write_operation():
            async with pool.acquire(readonly=False) as conn:
                await conn.execute("INSERT INTO x VALUES (1)")
                return "write"

        # Mix of read and write operations
        tasks = [
            read_operation(),
            write_operation(),
            read_operation(),
            write_operation(),
            read_operation(),
        ]

        results = await asyncio.gather(*tasks)

        assert results.count("read") == 3
        assert results.count("write") == 2

        await pool.close()


# ===========================================================================
# Test Pool Properties and Statistics
# ===========================================================================


class TestPoolProperties:
    """Tests for pool properties and statistics."""

    @pytest.mark.asyncio
    async def test_stats_property(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """stats property returns current statistics."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )
        await pool.initialize()

        stats = pool.stats

        assert type(stats).__name__ == "PoolStats"
        assert stats.total_connections == 5  # From mock
        assert stats.idle_connections == 3  # From mock

        await pool.close()

    @pytest.mark.asyncio
    async def test_replica_count_property(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """replica_count property returns correct count."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=[
                "postgresql://replica1:5432/db",
                "postgresql://replica2:5432/db",
            ],
        )
        await pool.initialize()

        assert pool.replica_count == 2

        await pool.close()

    @pytest.mark.asyncio
    async def test_get_health_status(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """get_health_status returns comprehensive status."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=["postgresql://replica1:5432/db"],
        )
        await pool.initialize()

        status = pool.get_health_status()

        assert status["initialized"] is True
        assert status["primary_healthy"] is True
        assert status["replica_count"] == 1
        assert status["healthy_replicas"] == 1
        assert "stats" in status
        assert "replicas" in status

        await pool.close()


# ===========================================================================
# Test Global Pool Management
# ===========================================================================


class TestGlobalPoolManagement:
    """Tests for global pool configuration and management."""

    def test_configure_pool_creates_pool(self):
        """configure_pool creates a new pool instance."""
        pool = configure_pool(
            primary_dsn="postgresql://primary:5432/db",
            min_size=5,
            max_size=20,
        )

        assert pool is not None
        # Use type name check to avoid importlib mode class identity issues
        assert type(pool).__name__ == "ReplicaAwarePool"
        assert pool._primary_dsn == "postgresql://primary:5432/db"
        assert pool._min_size == 5
        assert pool._max_size == 20

    def test_get_pool_returns_configured_pool(self):
        """get_pool returns the configured pool."""
        configure_pool(primary_dsn="postgresql://test:5432/db")
        pool = get_pool()

        assert pool._primary_dsn == "postgresql://test:5432/db"

    def test_get_pool_creates_default_pool(self):
        """get_pool creates a default pool if none configured."""
        pool = get_pool()

        assert pool is not None
        assert type(pool).__name__ == "ReplicaAwarePool"

    @pytest.mark.asyncio
    async def test_close_pool_closes_global_pool(self, mock_create_pool, mock_asyncpg_pool):
        """close_pool closes and clears the global pool."""
        pool = configure_pool(primary_dsn="postgresql://primary:5432/db")
        await pool.initialize()

        await close_pool()

        # Global pool should be cleared
        import aragora.persistence.postgres_pool as module

        assert module._pool is None


# ===========================================================================
# Test Pool Closure
# ===========================================================================


class TestPoolClosure:
    """Tests for pool closure."""

    @pytest.mark.asyncio
    async def test_close_cancels_health_task(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Closing pool cancels health check task."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=["postgresql://replica1:5432/db"],
            health_check_interval=0.1,
        )
        await pool.initialize()

        assert pool._health_task is not None

        await pool.close()

        # Health task should be cancelled
        assert pool._health_task.cancelled() or pool._health_task.done()
        assert pool._initialized is False

    @pytest.mark.asyncio
    async def test_close_closes_all_pools(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Closing pool closes primary and all replicas."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=[
                "postgresql://replica1:5432/db",
                "postgresql://replica2:5432/db",
            ],
        )
        await pool.initialize()

        await pool.close()

        # Close should be called on primary and replicas
        # (mock is reused, so call count = 3 for init, then close is called 3 times)
        assert mock_asyncpg_pool.close.call_count >= 1


# ===========================================================================
# Test Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_acquire_context_manager_releases_on_exception(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Connection is released even if exception occurs in context."""
        mock_asyncpg_pool.acquire.return_value = mock_asyncpg_connection

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )
        await pool.initialize()

        with pytest.raises(ValueError):
            async with pool.acquire() as conn:
                raise ValueError("test error")

        # Connection should still be released
        mock_asyncpg_pool.release.assert_called_once()

        # Active connections should be back to 0
        assert pool._stats.active_connections == 0

        await pool.close()

    @pytest.mark.asyncio
    async def test_select_healthy_replica_empty_pools(self):
        """_select_healthy_replica handles empty pool list."""
        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
        )

        # No replica pools
        assert pool._replica_pools == []

        selected = pool._select_healthy_replica()
        assert selected is None

    @pytest.mark.asyncio
    async def test_health_check_with_timeout(
        self, mock_create_pool, mock_asyncpg_pool, mock_asyncpg_connection
    ):
        """Health check handles timeout correctly."""

        # Make health check hang
        async def slow_acquire():
            await asyncio.sleep(10)
            return mock_asyncpg_connection

        mock_asyncpg_pool.acquire = slow_acquire

        pool = ReplicaAwarePool(
            primary_dsn="postgresql://primary:5432/db",
            replica_dsns=["postgresql://replica1:5432/db"],
        )

        # Manually set up replica health without full initialization
        pool._replica_pools = [mock_asyncpg_pool]
        pool._replica_dsns = ["postgresql://replica1:5432/db"]
        pool._replica_health = {
            "postgresql://replica1:5432/db": ReplicaHealth(dsn="postgresql://replica1:5432/db")
        }

        # Run health check with timeout (should not hang forever)
        # The internal timeout is 5.0 seconds, but we use a shorter test
        with patch(
            "asyncio.timeout",
            return_value=MagicMock(
                __aenter__=AsyncMock(side_effect=asyncio.TimeoutError()),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            await pool._check_replica_health()

        # Should increment failure count
        health = pool._replica_health["postgresql://replica1:5432/db"]
        assert health.consecutive_failures >= 1

    def test_record_query_increments_counters(self):
        """_record_query correctly increments counters."""
        pool = ReplicaAwarePool(primary_dsn="postgresql://primary:5432/db")

        # Record read queries
        pool._record_query(readonly=True)
        pool._record_query(readonly=True)

        # Record write queries
        pool._record_query(readonly=False)

        assert pool._stats.total_queries == 3
        assert pool._stats.read_queries == 2
        assert pool._stats.write_queries == 1
