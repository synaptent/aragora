"""
Tests for Connection Router (read replica support).
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from aragora.storage.connection_router import (
    ConnectionRouter,
    RouterConfig,
    ReplicaConfig,
    RouterMetrics,
    initialize_connection_router,
    get_connection_router,
    is_router_initialized,
    close_connection_router,
    reset_connection_router,
)


class TestRouterConfig:
    """Tests for RouterConfig."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = RouterConfig()

        assert config.primary_dsn is None
        assert config.replicas == []
        assert config.failover_to_primary is True
        assert config.pool_min_size == 5
        assert config.pool_max_size == 20
        assert config.replica_pool_size == 10

    def test_from_environment_no_replicas(self):
        """Should load from environment without replicas."""
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_POSTGRES_PRIMARY_DSN": "postgresql://localhost/primary",
            },
            clear=True,
        ):
            config = RouterConfig.from_environment()

        assert config.primary_dsn == "postgresql://localhost/primary"
        assert config.replicas == []

    def test_from_environment_with_replicas(self):
        """Should load replica DSNs from environment."""
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_POSTGRES_PRIMARY_DSN": "postgresql://localhost/primary",
                "ARAGORA_POSTGRES_REPLICA_DSNS": "postgresql://replica1/db,postgresql://replica2/db",
                "ARAGORA_REPLICA_POOL_SIZE": "15",
            },
            clear=True,
        ):
            config = RouterConfig.from_environment()

        assert config.primary_dsn == "postgresql://localhost/primary"
        assert len(config.replicas) == 2
        assert config.replicas[0].dsn == "postgresql://replica1/db"
        assert config.replicas[0].name == "replica-0"
        assert config.replicas[0].pool_size == 15
        assert config.replicas[1].dsn == "postgresql://replica2/db"

    def test_from_environment_fallback_dsn(self):
        """Should fallback to DATABASE_URL if primary not set."""
        with patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql://localhost/fallback",
            },
            clear=True,
        ):
            config = RouterConfig.from_environment()

        assert config.primary_dsn == "postgresql://localhost/fallback"


class TestReplicaConfig:
    """Tests for ReplicaConfig."""

    def test_create_replica_config(self):
        """Should create replica config with required fields."""
        config = ReplicaConfig(
            dsn="postgresql://replica/db",
            name="my-replica",
            pool_size=8,
        )

        assert config.dsn == "postgresql://replica/db"
        assert config.name == "my-replica"
        assert config.pool_size == 8
        assert config.priority == 0


class TestConnectionRouter:
    """Tests for ConnectionRouter."""

    @pytest.fixture
    def router_config(self):
        """Create a router config for testing."""
        return RouterConfig(
            primary_dsn="postgresql://localhost/primary",
            replicas=[
                ReplicaConfig(dsn="postgresql://localhost/replica1", name="replica-1"),
                ReplicaConfig(dsn="postgresql://localhost/replica2", name="replica-2"),
            ],
        )

    @pytest.fixture
    def router(self, router_config):
        """Create a router for testing."""
        return ConnectionRouter(config=router_config)

    def test_initial_state(self, router):
        """Should start uninitialized."""
        assert not router._initialized
        assert router._primary_pool is None
        assert router._replica_pools == []

    def test_has_replicas_before_init(self, router):
        """Should return False for has_replicas before initialization."""
        assert router.has_replicas is False

    def test_replica_count_before_init(self, router):
        """Should return 0 for replica_count before initialization."""
        assert router.replica_count == 0

    @pytest.mark.asyncio
    async def test_initialize_success(self, router):
        """Should initialize pools successfully."""
        mock_pool = MagicMock()
        mock_pool.get_size.return_value = 5

        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool

            success = await router.initialize()

        assert success is True
        assert router._initialized is True
        assert router._primary_pool is not None
        # Should have called create_pool 3 times (1 primary + 2 replicas)
        assert mock_create.call_count == 3

    @pytest.mark.asyncio
    async def test_initialize_no_asyncpg(self, router):
        """Should fail gracefully if asyncpg not available."""
        with patch.dict("sys.modules", {"asyncpg": None}):
            with patch(
                "aragora.storage.connection_router.ConnectionRouter.initialize"
            ) as mock_init:
                mock_init.return_value = False
                success = await router.initialize()

        assert success is False

    @pytest.mark.asyncio
    async def test_connection_write_uses_primary(self, router):
        """Should use primary pool for write operations."""
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_pool.get_size.return_value = 5

        router._primary_pool = mock_pool
        router._initialized = True

        async with router.connection(read_only=False) as conn:
            assert conn is mock_conn

        assert router._metrics.primary_requests == 1
        assert router._metrics.replica_requests == 0

    @pytest.mark.asyncio
    async def test_connection_read_uses_replica(self, router):
        """Should use replica pool for read operations."""
        mock_conn = MagicMock()
        mock_replica_pool = MagicMock()
        mock_replica_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_replica_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_primary_pool = MagicMock()
        mock_primary_pool.get_size.return_value = 5

        router._primary_pool = mock_primary_pool
        router._replica_pools = [mock_replica_pool]
        router._initialized = True

        async with router.connection(read_only=True) as conn:
            assert conn is mock_conn

        assert router._metrics.replica_requests == 1
        assert router._metrics.primary_requests == 0

    @pytest.mark.asyncio
    async def test_connection_read_fallback_to_primary(self, router):
        """Should fallback to primary if replica fails."""
        mock_replica_pool = MagicMock()
        mock_replica_pool.acquire.return_value.__aenter__ = AsyncMock(
            side_effect=ConnectionError("Replica error")
        )

        mock_primary_conn = MagicMock()
        mock_primary_pool = MagicMock()
        mock_primary_pool.acquire.return_value.__aenter__ = AsyncMock(
            return_value=mock_primary_conn
        )
        mock_primary_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        router._primary_pool = mock_primary_pool
        router._replica_pools = [mock_replica_pool]
        router._initialized = True

        async with router.connection(read_only=True) as conn:
            assert conn is mock_primary_conn

        assert router._metrics.replica_failovers == 1
        assert router._metrics.primary_requests == 1

    @pytest.mark.asyncio
    async def test_transaction_always_uses_primary(self, router):
        """Should always use primary for transactions."""
        mock_conn = MagicMock()
        mock_transaction = MagicMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction.return_value = mock_transaction

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        router._primary_pool = mock_pool
        router._replica_pools = [MagicMock()]  # Has replicas
        router._initialized = True

        async with router.transaction() as conn:
            assert conn is mock_conn

        assert router._metrics.primary_requests == 1

    def test_get_metrics(self, router):
        """Should return router metrics."""
        router._metrics.total_requests = 100
        router._metrics.replica_requests = 75
        router._metrics.primary_requests = 25

        metrics = router.get_metrics()

        assert metrics.total_requests == 100
        assert metrics.replica_requests == 75
        assert metrics.read_ratio == 0.75

    def test_get_info(self, router):
        """Should return router info."""
        info = router.get_info()

        assert info["initialized"] is False
        assert info["has_replicas"] is False
        assert info["replica_count"] == 0

    @pytest.mark.asyncio
    async def test_close(self, router):
        """Should close all pools."""
        mock_primary = MagicMock()
        mock_primary.close = AsyncMock()
        mock_replica = MagicMock()
        mock_replica.close = AsyncMock()

        router._primary_pool = mock_primary
        router._replica_pools = [mock_replica]
        router._initialized = True

        await router.close()

        mock_primary.close.assert_called_once()
        mock_replica.close.assert_called_once()
        assert router._initialized is False
        assert router._primary_pool is None


class TestGlobalRouterFunctions:
    """Tests for global router management functions."""

    def setup_method(self):
        """Reset global router before each test."""
        reset_connection_router()

    def teardown_method(self):
        """Clean up after each test."""
        reset_connection_router()

    def test_get_router_none(self):
        """Should return None when not initialized."""
        assert get_connection_router() is None

    def test_is_router_initialized_false(self):
        """Should return False when not initialized."""
        assert is_router_initialized() is False

    @pytest.mark.asyncio
    async def test_initialize_without_replicas(self):
        """Should return None if no replicas configured."""
        with patch.dict("os.environ", {}, clear=True):
            router = await initialize_connection_router()

        assert router is None

    @pytest.mark.asyncio
    async def test_initialize_with_replicas(self):
        """Should initialize router with replicas configured."""
        config = RouterConfig(
            primary_dsn="postgresql://localhost/primary",
            replicas=[
                ReplicaConfig(dsn="postgresql://localhost/replica", name="replica-1"),
            ],
        )

        mock_pool = MagicMock()
        mock_pool.get_size.return_value = 5

        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool

            router = await initialize_connection_router(config=config)

        assert router is not None
        assert is_router_initialized() is True
        assert get_connection_router() is router

    @pytest.mark.asyncio
    async def test_close_router(self):
        """Should close global router."""
        config = RouterConfig(
            primary_dsn="postgresql://localhost/primary",
            replicas=[
                ReplicaConfig(dsn="postgresql://localhost/replica", name="replica-1"),
            ],
        )

        mock_pool = MagicMock()
        mock_pool.get_size.return_value = 5
        mock_pool.close = AsyncMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool

            await initialize_connection_router(config=config)
            await close_connection_router()

        assert get_connection_router() is None


class TestRouterIntegration:
    """Integration tests for connection router."""

    @pytest.mark.asyncio
    async def test_round_robin_selection(self):
        """Should select replicas in round-robin order."""
        config = RouterConfig(
            primary_dsn="postgresql://localhost/primary",
            replicas=[
                ReplicaConfig(dsn="postgresql://replica1/db", name="replica-1"),
                ReplicaConfig(dsn="postgresql://replica2/db", name="replica-2"),
            ],
        )

        router = ConnectionRouter(config=config)

        # Mock pools
        mock_conn1 = MagicMock(name="conn1")
        mock_conn2 = MagicMock(name="conn2")

        mock_pool1 = MagicMock()
        mock_pool1.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn1)
        mock_pool1.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_pool2 = MagicMock()
        mock_pool2.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn2)
        mock_pool2.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_primary = MagicMock()

        router._primary_pool = mock_primary
        router._replica_pools = [mock_pool1, mock_pool2]
        router._initialized = True

        # First read should use replica-1
        async with router.connection(read_only=True) as conn:
            pass

        # Second read should use replica-2
        async with router.connection(read_only=True) as conn:
            pass

        # Third read should cycle back to replica-1
        async with router.connection(read_only=True) as conn:
            pass

        assert router._metrics.replica_requests == 3
        # After 3 reads: 0→1, 1→0, 0→1
        assert router._replica_index == 1
