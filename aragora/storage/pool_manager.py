"""
PostgreSQL Pool Manager - Event-loop aware pool lifecycle management.

Provides centralized pool creation and access that respects asyncpg's
event loop binding requirements. The shared pool MUST be initialized
early in the server startup sequence (after asyncio.run() starts).

Usage:
    # In server startup (inside async context):
    await initialize_shared_pool()

    # In store factories:
    if is_pool_initialized():
        pool = get_shared_pool()
        store = PostgresMyStore(pool)

    # In shutdown:
    await close_shared_pool()
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import warnings
from typing import TYPE_CHECKING, Any

from aragora.utils.async_utils import (
    get_pool_event_loop as _get_pool_event_loop,
    register_pool_event_loop_provider,
)

if TYPE_CHECKING:
    from asyncpg import Pool


logger = logging.getLogger(__name__)

# Global pool state
_shared_pool: Pool | None = None
_pool_event_loop: asyncio.AbstractEventLoop | None = None
_pool_config: dict[str, Any] = {}
_dedicated_loop_thread: threading.Thread | None = None
_pool_heal_lock = threading.Lock()


def _is_shared_pool_enabled() -> bool:
    """Check if shared pool feature is enabled via environment variable."""
    return os.environ.get("ARAGORA_USE_SHARED_POOL", "true").lower() in ("true", "1", "yes")


async def initialize_shared_pool(
    dsn: str | None = None,
    min_size: int = 5,
    max_size: int = 20,
    command_timeout: float = 60.0,
    statement_timeout: int = 60,
    force: bool = False,
) -> Pool | None:
    """
    Initialize the shared PostgreSQL pool in the current event loop.

    MUST be called from within an async context (after asyncio.run() starts).
    The pool will be bound to the current event loop and cannot be used
    from other event loops.

    If a stale pool exists (e.g., created on a temporary event loop during
    module imports), it will be closed and replaced with a fresh pool
    bound to the current (correct) event loop.

    Args:
        dsn: PostgreSQL connection string. If not provided, uses environment.
        min_size: Minimum pool connections (default 5)
        max_size: Maximum pool connections (default 20)
        command_timeout: Command timeout in seconds (default 60)
        statement_timeout: PostgreSQL statement_timeout in seconds (default 60)

    Returns:
        Pool instance if PostgreSQL is configured and initialization succeeds,
        None if PostgreSQL is not configured or shared pool is disabled.

    Raises:
        RuntimeError: If pool creation fails (after logging error)
    """
    global _shared_pool, _pool_event_loop, _pool_config

    # Check if feature is enabled
    if not _is_shared_pool_enabled():
        logger.info("[pool_manager] Shared pool disabled via ARAGORA_USE_SHARED_POOL=false")
        return None

    # Check if already initialized on THIS event loop
    if _shared_pool is not None and not force:
        current_loop = asyncio.get_running_loop()
        if _pool_event_loop is current_loop:
            logger.debug("[pool_manager] Shared pool already initialized on this loop")
            return _shared_pool

    # Force-close the existing pool when refreshing due to stale connections
    if force and _shared_pool is not None:
        logger.warning("[pool_manager] Force-reinitializing shared pool (stale connections)")
        try:
            await _shared_pool.close()
        except (OSError, RuntimeError) as close_err:
            logger.warning("[pool_manager] Error closing stale pool: %s", close_err)
            try:
                _shared_pool.terminate()
            except (OSError, RuntimeError):
                logger.debug("Failed to terminate stale pool", exc_info=True)
        _shared_pool = None
        _pool_event_loop = None

    # Check if PostgreSQL is configured
    from aragora.storage.connection_factory import (
        StorageBackendType,
        resolve_database_config,
    )

    config = resolve_database_config("shared", allow_sqlite=True)
    if config.backend_type == StorageBackendType.SQLITE:
        logger.info("[pool_manager] No PostgreSQL configured, skipping pool creation")
        return None

    # Create pool in current event loop
    try:
        from aragora.storage import postgres_store as _ps_mod

        effective_dsn = dsn or config.dsn
        current_loop = asyncio.get_running_loop()

        # Close any stale pool created on a different event loop.
        # This happens when module-level code (e.g., workflows.py template
        # registration) triggers get_postgres_pool() via run_async() /
        # asyncio.run(), which creates a temporary event loop. That pool
        # is then bound to the now-closed temp loop and is unusable.
        if _ps_mod._pool is not None:
            logger.warning(
                "[pool_manager] Clearing stale postgres_store._pool "
                "(created on different event loop) before shared pool init"
            )
            # Don't terminate() the stale pool - it was created on a now-dead
            # temporary event loop (from asyncio.run() during module import).
            # Calling terminate() sends disconnect commands to the database
            # server which can cause Supabase to temporarily reject new
            # connections ("Tenant or user not found"). Just null the reference
            # and let GC collect it - the dead loop means its connections are
            # already effectively orphaned.
            _ps_mod._pool = None

        # Also reset _shared_pool if it references the same stale pool
        if _shared_pool is not None:
            _shared_pool = None
            _pool_event_loop = None

        # Now create a fresh pool on the current event loop (with retry)
        from aragora.storage.postgres_store import get_postgres_pool

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                _ps_mod._pool = None  # Ensure clean state for each attempt
                _shared_pool = await get_postgres_pool(
                    dsn=effective_dsn,
                    min_size=min_size,
                    max_size=max_size,
                    command_timeout=command_timeout,
                    statement_timeout=statement_timeout,
                )
                break
            except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
                last_err = e
                logger.warning(
                    "[pool_manager] Pool creation attempt %s/3 failed: %s", attempt + 1, e
                )
                _ps_mod._pool = None
                if attempt < 2:
                    await asyncio.sleep(2.0 * (attempt + 1))
        else:
            # last_err is guaranteed to be set here since we only reach the else
            # branch if we never broke out of the loop (i.e., all attempts failed)
            if last_err is None:
                raise RuntimeError("Connection retry loop completed without error - logic error")
            raise last_err
        _pool_event_loop = current_loop
        _pool_config = {
            "dsn_hash": hash(effective_dsn) if effective_dsn else None,
            "min_size": min_size,
            "max_size": max_size,
            "is_supabase": config.is_supabase,
        }

        # Apply nest_asyncio to allow nested run_until_complete() calls.
        # This is required because PostgreSQL store sync wrappers use
        # run_async() which needs to work
        # from within handler coroutines running on this event loop.
        try:
            import nest_asyncio

            nest_asyncio.apply(_pool_event_loop)
            logger.warning("[pool_manager] nest_asyncio applied to main event loop")
        except ImportError:
            logger.warning(
                "[pool_manager] nest_asyncio not installed. "
                "Sync store wrappers may deadlock in async contexts. "
                "Install with: pip install nest_asyncio"
            )

        # Verify pool health
        try:
            async with _shared_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
        except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
            logger.error("[pool_manager] Pool health check failed after creation: %s", e)
            # Pool is broken, clean up and fall back
            try:
                _shared_pool.terminate()
            except (OSError, RuntimeError) as e:
                logger.warning("Failed to terminate broken database pool: %s", e)
            _shared_pool = None
            _pool_event_loop = None
            _pool_config = {}
            _ps_mod._pool = None
            return None

        pool_size = _shared_pool.get_size() if hasattr(_shared_pool, "get_size") else "unknown"
        backend_name = "Supabase" if config.is_supabase else "PostgreSQL"
        logger.warning(
            "[pool_manager] Shared %s pool initialized (size: %s, event_loop: %s)",
            backend_name,
            pool_size,
            id(_pool_event_loop),
        )
        return _shared_pool

    except (OSError, RuntimeError, ConnectionError, TimeoutError, ImportError) as e:
        logger.error("[pool_manager] Failed to initialize shared pool: %s", e)
        # Don't raise - let caller handle fallback to SQLite
        return None


def get_shared_pool() -> Pool | None:
    """
    Get the shared pool, validating it's being accessed from the correct event loop.

    Returns:
        Pool if available and event loop matches, None if not initialized.

    Raises:
        RuntimeError: If accessed from a different event loop than it was created in.
    """
    global _shared_pool, _pool_event_loop

    if _shared_pool is None:
        return None

    # Validate event loop when in async context
    try:
        current_loop = asyncio.get_running_loop()
        if _pool_event_loop and current_loop != _pool_event_loop:
            raise RuntimeError(
                f"Shared pool was created in event loop {id(_pool_event_loop)} "
                f"but accessed from {id(current_loop)}. "
                "asyncpg pools are event-loop bound and cannot be shared across loops."
            )
    except RuntimeError as e:
        if "no running event loop" in str(e).lower():
            # Sync context - pool access is valid but operations must be awaited
            pass
        else:
            raise

    return _shared_pool


def is_pool_initialized() -> bool:
    """Check if the shared pool has been initialized."""
    return _shared_pool is not None and _is_shared_pool_enabled()


def get_pool_event_loop() -> asyncio.AbstractEventLoop | None:
    """Compatibility shim for the foundation-owned pool-loop accessor."""
    warnings.warn(
        "aragora.storage.pool_manager.get_pool_event_loop is deprecated; import "
        "aragora.utils.async_utils.get_pool_event_loop instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_pool_event_loop()


def _ensure_pool_loop() -> asyncio.AbstractEventLoop | None:
    """Get or create a running event loop for pool operations.

    Fast path: if _pool_event_loop is alive, return it.
    Slow path: if stale, create a dedicated daemon thread with a persistent
    event loop, reinitialize the pool on it, and return it.

    Thread-safe via double-checked locking with _pool_heal_lock.
    """
    global _pool_event_loop, _dedicated_loop_thread

    loop = _pool_event_loop
    if loop is None:
        return None  # Pool was never initialized

    # Fast path: loop is healthy
    if not loop.is_closed() and loop.is_running():
        return loop

    # Slow path: loop is stale, need to heal
    with _pool_heal_lock:
        # Double-check after acquiring lock
        loop = _pool_event_loop
        if loop is not None and not loop.is_closed() and loop.is_running():
            return loop

        logger.warning(
            "[pool_manager] Pool event loop is stale (not running). "
            "Creating dedicated background event loop for pool operations."
        )

        # Create a new event loop in a dedicated daemon thread
        new_loop = asyncio.new_event_loop()
        ready_event = threading.Event()

        def _run_dedicated_loop() -> None:
            asyncio.set_event_loop(new_loop)
            ready_event.set()
            new_loop.run_forever()

        thread = threading.Thread(
            target=_run_dedicated_loop,
            name="aragora-pool-loop",
            daemon=True,
        )
        thread.start()

        # Wait for the loop to actually start running
        if not ready_event.wait(timeout=10.0):
            logger.error("[pool_manager] Dedicated event loop failed to start within 10s")
            return None

        # Reinitialize the pool on the new loop
        try:
            future = asyncio.run_coroutine_threadsafe(initialize_shared_pool(force=True), new_loop)
            result = future.result(timeout=30.0)
            if result is None:
                logger.error("[pool_manager] Pool reinitialization returned None on dedicated loop")
                new_loop.call_soon_threadsafe(new_loop.stop)
                return None
        except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
            logger.error("[pool_manager] Failed to reinitialize pool on dedicated loop: %s", e)
            new_loop.call_soon_threadsafe(new_loop.stop)
            return None

        _dedicated_loop_thread = thread
        # _pool_event_loop is already updated by initialize_shared_pool(force=True)
        logger.warning(
            "[pool_manager] Self-healed: pool reinitialized on dedicated loop "
            "(event_loop: %d, thread: %s)",
            id(_pool_event_loop),
            thread.name,
        )
        return _pool_event_loop


register_pool_event_loop_provider(_ensure_pool_loop)


def get_pool_info() -> dict[str, Any]:
    """Get information about the shared pool for diagnostics."""
    global _shared_pool, _pool_event_loop, _pool_config

    if _shared_pool is None:
        return {
            "initialized": False,
            "enabled": _is_shared_pool_enabled(),
        }

    pool_size = _shared_pool.get_size() if hasattr(_shared_pool, "get_size") else None
    free_size = _shared_pool.get_idle_size() if hasattr(_shared_pool, "get_idle_size") else None

    return {
        "initialized": True,
        "enabled": True,
        "pool_size": pool_size,
        "free_connections": free_size,
        "event_loop_id": id(_pool_event_loop) if _pool_event_loop else None,
        "is_supabase": _pool_config.get("is_supabase", False),
        "min_size": _pool_config.get("min_size"),
        "max_size": _pool_config.get("max_size"),
    }


async def close_shared_pool() -> None:
    """
    Close the shared pool during shutdown.

    Safe to call multiple times or when pool is not initialized.
    """
    global _shared_pool, _pool_event_loop, _pool_config, _dedicated_loop_thread

    if _shared_pool is None:
        logger.debug("[pool_manager] No shared pool to close")
        return

    try:
        await _shared_pool.close()
        logger.info("[pool_manager] Shared pool closed")
    except (OSError, RuntimeError, ConnectionError) as e:
        logger.warning("[pool_manager] Error closing shared pool: %s", e)
    finally:
        old_loop = _pool_event_loop
        _shared_pool = None
        _pool_event_loop = None
        _pool_config = {}
        # Stop the dedicated loop thread if one was created during self-healing
        if _dedicated_loop_thread is not None:
            if old_loop is not None and old_loop.is_running():
                old_loop.call_soon_threadsafe(old_loop.stop)
            _dedicated_loop_thread = None


def reset_shared_pool() -> None:
    """
    Reset pool state without closing (for testing only).

    WARNING: This does NOT close the pool properly. Only use in tests.
    """
    global _shared_pool, _pool_event_loop, _pool_config, _dedicated_loop_thread
    _shared_pool = None
    _pool_event_loop = None
    _pool_config = {}
    _dedicated_loop_thread = None


_POOL_UTILIZATION_WARNING_THRESHOLD = 0.70


def get_database_pool_health() -> dict[str, Any]:
    """Synchronous database pool health check using pool metrics.

    Returns pool utilization stats derived from the shared asyncpg pool.
    The pool is considered "connected" if it was successfully initialized
    and has a non-zero size (i.e., live connections exist).

    This function is safe to call from synchronous code (including
    handler dispatch that cannot ``await``).

    For a full async connectivity probe (``SELECT 1``), use
    :func:`check_database_health` instead.

    Returns a dict with:
        connected (bool): Whether the pool is initialized with connections.
        pool_active (int | None): In-use connections (size - idle).
        pool_idle (int | None): Idle connections.
        pool_size (int | None): Current total pool size.
        pool_utilization_pct (float | None): Percentage of max pool in use.
        status (str): "healthy", "degraded", "unhealthy", or "not_configured".
    """
    pool = get_shared_pool()

    if pool is None:
        return {
            "connected": False,
            "pool_active": None,
            "pool_idle": None,
            "pool_size": None,
            "pool_utilization_pct": None,
            "status": "not_configured",
        }

    # Gather pool metrics synchronously (asyncpg exposes these as sync calls)
    pool_size: int | None = pool.get_size() if hasattr(pool, "get_size") else None
    pool_idle: int | None = pool.get_idle_size() if hasattr(pool, "get_idle_size") else None
    pool_max: int | None = pool.get_max_size() if hasattr(pool, "get_max_size") else None
    pool_active: int | None = (
        (pool_size - pool_idle) if pool_size is not None and pool_idle is not None else None
    )

    utilization_pct: float | None = None
    if pool_max and pool_active is not None:
        utilization_pct = round((pool_active / pool_max) * 100, 1)

    # Pool exists and has connections -> connected
    connected = pool_size is not None and pool_size > 0

    # Determine status
    if not connected:
        status = "unhealthy"
    elif (
        utilization_pct is not None and utilization_pct > _POOL_UTILIZATION_WARNING_THRESHOLD * 100
    ):
        status = "degraded"
        logger.warning(
            "[pool_manager] Pool utilization %.1f%% exceeds %.0f%% threshold "
            "(active=%s, size=%s, max=%s)",
            utilization_pct,
            _POOL_UTILIZATION_WARNING_THRESHOLD * 100,
            pool_active,
            pool_size,
            pool_max,
        )
    else:
        status = "healthy"

    return {
        "connected": connected,
        "pool_active": pool_active,
        "pool_idle": pool_idle,
        "pool_size": pool_size,
        "pool_utilization_pct": utilization_pct,
        "status": status,
    }


async def check_database_health(timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Check database connectivity and pool utilization.

    Executes ``SELECT 1`` to verify the database is reachable and returns
    pool statistics.  The entire check is bounded by *timeout_seconds* so
    an unreachable database does not hang the health endpoint.

    Returns a dict with at least:
        connected (bool): Whether a query could be executed.
        pool_active (int | None): Active (in-use) connections.
        pool_idle (int | None): Idle connections.
        pool_size (int | None): Current total pool size.
        pool_utilization_pct (float | None): Percentage of pool in use.
        status (str): "healthy", "degraded", or "unhealthy".

    The check is intentionally tolerant:
    * If no pool is configured (e.g. SQLite-only deployment), it returns
      ``connected=False, status="not_configured"`` without raising.
    * If the pool exists but the query times out, ``connected=False``.
    * If utilization > 70 %, a warning is logged and status is "degraded".
    """
    pool = get_shared_pool()

    # --- No pool configured (DB-optional deployment) ---
    if pool is None:
        return {
            "connected": False,
            "pool_active": None,
            "pool_idle": None,
            "pool_size": None,
            "pool_utilization_pct": None,
            "status": "not_configured",
        }

    # --- Gather pool metrics (safe even if the query fails) ---
    pool_size: int | None = pool.get_size() if hasattr(pool, "get_size") else None
    pool_idle: int | None = pool.get_idle_size() if hasattr(pool, "get_idle_size") else None
    pool_max: int | None = pool.get_max_size() if hasattr(pool, "get_max_size") else None
    pool_active: int | None = (
        (pool_size - pool_idle) if pool_size is not None and pool_idle is not None else None
    )

    utilization_pct: float | None = None
    if pool_max and pool_active is not None:
        utilization_pct = round((pool_active / pool_max) * 100, 1)

    # --- Execute SELECT 1 with timeout ---
    connected = False
    try:
        async with asyncio.timeout(timeout_seconds):
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
        connected = True
    except TimeoutError:
        logger.warning(
            "[pool_manager] Database health check timed out after %.1fs", timeout_seconds
        )
    except (OSError, RuntimeError, ConnectionError) as exc:
        logger.warning("[pool_manager] Database health check failed: %s", exc)

    # --- Determine status ---
    if not connected:
        status = "unhealthy"
    elif (
        utilization_pct is not None and utilization_pct > _POOL_UTILIZATION_WARNING_THRESHOLD * 100
    ):
        status = "degraded"
        logger.warning(
            "[pool_manager] Pool utilization %.1f%% exceeds %.0f%% threshold "
            "(active=%s, size=%s, max=%s)",
            utilization_pct,
            _POOL_UTILIZATION_WARNING_THRESHOLD * 100,
            pool_active,
            pool_size,
            pool_max,
        )
    else:
        status = "healthy"

    return {
        "connected": connected,
        "pool_active": pool_active,
        "pool_idle": pool_idle,
        "pool_size": pool_size,
        "pool_utilization_pct": utilization_pct,
        "status": status,
    }


__all__ = [
    "initialize_shared_pool",
    "get_shared_pool",
    "get_pool_event_loop",
    "is_pool_initialized",
    "get_pool_info",
    "get_database_pool_health",
    "check_database_health",
    "close_shared_pool",
    "reset_shared_pool",
]
