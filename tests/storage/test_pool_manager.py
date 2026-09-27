"""Tests for PostgreSQL pool manager.

Tests cover:
1. Pool initialization and configuration
2. Event loop binding validation
3. Pool info and diagnostics
4. Pool shutdown and reset
5. Feature flag (ARAGORA_USE_SHARED_POOL)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.storage.pool_manager import (
    _is_shared_pool_enabled,
    close_shared_pool,
    get_pool_event_loop,
    get_pool_info,
    get_shared_pool,
    initialize_shared_pool,
    is_pool_initialized,
    reset_shared_pool,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def reset_pool_state():
    """Reset pool state before and after each test."""
    reset_shared_pool()
    yield
    reset_shared_pool()


@pytest.fixture
def mock_pool():
    """Create a mock asyncpg pool."""
    pool = MagicMock()
    pool.get_size.return_value = 10
    pool.get_idle_size.return_value = 5
    pool.close = AsyncMock()
    pool.terminate = MagicMock()

    # Mock acquire context manager
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=1)

    async_cm = AsyncMock()
    async_cm.__aenter__.return_value = mock_conn
    async_cm.__aexit__.return_value = None
    pool.acquire.return_value = async_cm

    return pool


# =============================================================================
# Test: Feature Flag
# =============================================================================


class TestIsSharedPoolEnabled:
    """Tests for _is_shared_pool_enabled function."""

    def test_enabled_by_default(self):
        """Shared pool is enabled by default."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove the env var if it exists
            import os

            os.environ.pop("ARAGORA_USE_SHARED_POOL", None)
            # Re-import to clear any cached value
            from aragora.storage import pool_manager

            result = pool_manager._is_shared_pool_enabled()
            assert result is True

    def test_enabled_with_true(self):
        """Shared pool enabled when ARAGORA_USE_SHARED_POOL=true."""
        with patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}):
            assert _is_shared_pool_enabled() is True

    def test_enabled_with_1(self):
        """Shared pool enabled when ARAGORA_USE_SHARED_POOL=1."""
        with patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "1"}):
            assert _is_shared_pool_enabled() is True

    def test_enabled_with_yes(self):
        """Shared pool enabled when ARAGORA_USE_SHARED_POOL=yes."""
        with patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "yes"}):
            assert _is_shared_pool_enabled() is True

    def test_disabled_with_false(self):
        """Shared pool disabled when ARAGORA_USE_SHARED_POOL=false."""
        with patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "false"}):
            assert _is_shared_pool_enabled() is False

    def test_disabled_with_0(self):
        """Shared pool disabled when ARAGORA_USE_SHARED_POOL=0."""
        with patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "0"}):
            assert _is_shared_pool_enabled() is False

    def test_disabled_with_no(self):
        """Shared pool disabled when ARAGORA_USE_SHARED_POOL=no."""
        with patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "no"}):
            assert _is_shared_pool_enabled() is False


# =============================================================================
# Test: Pool Initialization
# =============================================================================


class TestInitializeSharedPool:
    """Tests for initialize_shared_pool function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self):
        """initialize_shared_pool returns None when feature is disabled."""
        with patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "false"}):
            result = await initialize_shared_pool()
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_sqlite(self):
        """initialize_shared_pool returns None for SQLite backend."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.SQLITE
        mock_config.dsn = None
        mock_config.is_supabase = False

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
        ):
            result = await initialize_shared_pool()
            assert result is None

    @pytest.mark.asyncio
    async def test_initializes_pool_successfully(self, mock_pool):
        """initialize_shared_pool creates pool on success."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.POSTGRES
        mock_config.dsn = "postgresql://test:test@localhost/test"
        mock_config.is_supabase = False

        mock_ps_mod = MagicMock()
        mock_ps_mod._pool = None
        mock_ps_mod.get_postgres_pool = AsyncMock(return_value=mock_pool)

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres_store": mock_ps_mod}),
            patch(
                "aragora.storage.postgres_store.get_postgres_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
        ):
            result = await initialize_shared_pool()

            assert result is mock_pool
            assert is_pool_initialized() is True

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        """initialize_shared_pool retries up to 3 times."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.POSTGRES
        mock_config.dsn = "postgresql://test:test@localhost/test"
        mock_config.is_supabase = False

        mock_ps_mod = MagicMock()
        mock_ps_mod._pool = None

        call_count = 0

        async def failing_get_pool(**kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectionError(f"Connection failed attempt {call_count}")

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres_store": mock_ps_mod}),
            patch(
                "aragora.storage.postgres_store.get_postgres_pool",
                new=failing_get_pool,
            ),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            # Should not raise (returns None on failure)
            result = await initialize_shared_pool()

            # Should have retried 3 times
            assert call_count == 3
            # Returns None after all retries fail
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_existing_pool_on_same_loop(self, mock_pool):
        """initialize_shared_pool returns existing pool if called twice on same loop."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.POSTGRES
        mock_config.dsn = "postgresql://test:test@localhost/test"
        mock_config.is_supabase = False

        mock_ps_mod = MagicMock()
        mock_ps_mod._pool = None

        get_pool_mock = AsyncMock(return_value=mock_pool)

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres_store": mock_ps_mod}),
            patch(
                "aragora.storage.postgres_store.get_postgres_pool",
                new=get_pool_mock,
            ),
        ):
            result1 = await initialize_shared_pool()
            result2 = await initialize_shared_pool()

            assert result1 is mock_pool
            assert result2 is mock_pool
            # Should only create pool once
            assert get_pool_mock.call_count == 1


# =============================================================================
# Test: Get Shared Pool
# =============================================================================


class TestGetSharedPool:
    """Tests for get_shared_pool function."""

    def test_returns_none_when_not_initialized(self):
        """get_shared_pool returns None when pool not initialized."""
        reset_shared_pool()
        result = get_shared_pool()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_pool_when_initialized(self, mock_pool):
        """get_shared_pool returns pool when initialized."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.POSTGRES
        mock_config.dsn = "postgresql://test:test@localhost/test"
        mock_config.is_supabase = False

        mock_ps_mod = MagicMock()
        mock_ps_mod._pool = None

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres_store": mock_ps_mod}),
            patch(
                "aragora.storage.postgres_store.get_postgres_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
        ):
            await initialize_shared_pool()
            result = get_shared_pool()
            assert result is mock_pool


# =============================================================================
# Test: Pool Info
# =============================================================================


class TestGetPoolInfo:
    """Tests for get_pool_info function."""

    def test_returns_not_initialized_when_no_pool(self):
        """get_pool_info returns initialized=False when pool not created."""
        reset_shared_pool()
        info = get_pool_info()

        assert info["initialized"] is False
        assert "enabled" in info

    @pytest.mark.asyncio
    async def test_returns_full_info_when_initialized(self, mock_pool):
        """get_pool_info returns full diagnostics when pool is initialized."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.POSTGRES
        mock_config.dsn = "postgresql://test:test@localhost/test"
        mock_config.is_supabase = False

        mock_ps_mod = MagicMock()
        mock_ps_mod._pool = None

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres_store": mock_ps_mod}),
            patch(
                "aragora.storage.postgres_store.get_postgres_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
        ):
            await initialize_shared_pool()
            info = get_pool_info()

            assert info["initialized"] is True
            assert info["enabled"] is True
            assert info["pool_size"] == 10
            assert info["free_connections"] == 5
            assert info["event_loop_id"] is not None


# =============================================================================
# Test: Pool Event Loop
# =============================================================================


class TestGetPoolEventLoop:
    """Tests for get_pool_event_loop function."""

    def test_returns_none_when_not_initialized(self):
        """get_pool_event_loop returns None when pool not initialized."""
        reset_shared_pool()
        with pytest.warns(
            DeprecationWarning,
            match=r"aragora\.storage\.pool_manager\.get_pool_event_loop",
        ):
            result = get_pool_event_loop()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_loop_when_initialized(self, mock_pool):
        """get_pool_event_loop returns event loop when pool initialized."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.POSTGRES
        mock_config.dsn = "postgresql://test:test@localhost/test"
        mock_config.is_supabase = False

        mock_ps_mod = MagicMock()
        mock_ps_mod._pool = None

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres_store": mock_ps_mod}),
            patch(
                "aragora.storage.postgres_store.get_postgres_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
        ):
            await initialize_shared_pool()
            with pytest.warns(
                DeprecationWarning,
                match=r"aragora\.storage\.pool_manager\.get_pool_event_loop",
            ):
                result = get_pool_event_loop()

            assert result is not None
            assert result is asyncio.get_running_loop()


# =============================================================================
# Test: Is Pool Initialized
# =============================================================================


class TestIsPoolInitialized:
    """Tests for is_pool_initialized function."""

    def test_returns_false_when_not_initialized(self):
        """is_pool_initialized returns False when pool not created."""
        reset_shared_pool()
        assert is_pool_initialized() is False

    def test_returns_false_when_disabled(self):
        """is_pool_initialized returns False when feature disabled."""
        with patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "false"}):
            assert is_pool_initialized() is False

    @pytest.mark.asyncio
    async def test_returns_true_when_initialized(self, mock_pool):
        """is_pool_initialized returns True when pool created."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.POSTGRES
        mock_config.dsn = "postgresql://test:test@localhost/test"
        mock_config.is_supabase = False

        mock_ps_mod = MagicMock()
        mock_ps_mod._pool = None

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres_store": mock_ps_mod}),
            patch(
                "aragora.storage.postgres_store.get_postgres_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
        ):
            await initialize_shared_pool()
            assert is_pool_initialized() is True


# =============================================================================
# Test: Close Shared Pool
# =============================================================================


class TestCloseSharedPool:
    """Tests for close_shared_pool function."""

    @pytest.mark.asyncio
    async def test_safe_to_call_when_not_initialized(self):
        """close_shared_pool is safe to call when pool not initialized."""
        reset_shared_pool()
        await close_shared_pool()  # Should not raise
        assert is_pool_initialized() is False

    @pytest.mark.asyncio
    async def test_closes_pool_and_resets_state(self, mock_pool):
        """close_shared_pool closes pool and resets global state."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.POSTGRES
        mock_config.dsn = "postgresql://test:test@localhost/test"
        mock_config.is_supabase = False

        mock_ps_mod = MagicMock()
        mock_ps_mod._pool = None

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres_store": mock_ps_mod}),
            patch(
                "aragora.storage.postgres_store.get_postgres_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
        ):
            await initialize_shared_pool()
            assert is_pool_initialized() is True

            await close_shared_pool()

            assert is_pool_initialized() is False
            mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_close_error_gracefully(self, mock_pool):
        """close_shared_pool handles errors during close."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.POSTGRES
        mock_config.dsn = "postgresql://test:test@localhost/test"
        mock_config.is_supabase = False

        mock_ps_mod = MagicMock()
        mock_ps_mod._pool = None
        mock_pool.close = AsyncMock(side_effect=RuntimeError("Close failed"))

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres_store": mock_ps_mod}),
            patch(
                "aragora.storage.postgres_store.get_postgres_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
        ):
            await initialize_shared_pool()
            await close_shared_pool()  # Should not raise

            # State should still be reset
            assert is_pool_initialized() is False


# =============================================================================
# Test: Reset Shared Pool
# =============================================================================


class TestResetSharedPool:
    """Tests for reset_shared_pool function."""

    @pytest.mark.asyncio
    async def test_resets_state_without_closing(self, mock_pool):
        """reset_shared_pool resets state without calling close."""
        from aragora.storage.connection_factory import StorageBackendType

        mock_config = MagicMock()
        mock_config.backend_type = StorageBackendType.POSTGRES
        mock_config.dsn = "postgresql://test:test@localhost/test"
        mock_config.is_supabase = False

        mock_ps_mod = MagicMock()
        mock_ps_mod._pool = None

        with (
            patch.dict("os.environ", {"ARAGORA_USE_SHARED_POOL": "true"}),
            patch(
                "aragora.storage.connection_factory.resolve_database_config",
                return_value=mock_config,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres_store": mock_ps_mod}),
            patch(
                "aragora.storage.postgres_store.get_postgres_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
        ):
            await initialize_shared_pool()
            reset_shared_pool()

            assert is_pool_initialized() is False
            # close should NOT have been called
            mock_pool.close.assert_not_called()

    def test_safe_to_call_when_not_initialized(self):
        """reset_shared_pool is safe to call when pool not initialized."""
        reset_shared_pool()  # Should not raise
        reset_shared_pool()  # Safe to call multiple times
