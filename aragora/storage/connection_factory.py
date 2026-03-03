"""
Unified Database Connection Factory for Aragora.

Implements the storage backend preference order:
1. Redis (caching, rate limiting, sessions - handled separately)
2. Supabase (preferred for persistent data)
3. Self-hosted PostgreSQL (fallback)
4. SQLite (last resort fallback)

Environment Variables:
    # Supabase (preferred)
    SUPABASE_URL: Supabase project URL
    SUPABASE_KEY: Supabase service role key
    SUPABASE_DB_PASSWORD: Database password for direct PostgreSQL access
    SUPABASE_POSTGRES_DSN: Explicit PostgreSQL connection string (optional)

    # Self-hosted PostgreSQL (fallback)
    ARAGORA_POSTGRES_DSN: Self-hosted PostgreSQL DSN
    DATABASE_URL: Alternative PostgreSQL DSN (common in PaaS)

    # Global settings
    ARAGORA_DB_BACKEND: Force specific backend ("supabase", "postgres", "sqlite", "auto")
    ARAGORA_<STORE>_BACKEND: Per-store override
    ARAGORA_<STORE>_STORE_BACKEND: Per-store override (legacy naming)
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any
from collections.abc import Sequence
from urllib.parse import urlparse

from aragora.persistence.db_config import get_default_data_dir

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)

_STORE_INIT_ERROR_TYPES: tuple[type[BaseException], ...] = (
    OSError,
    RuntimeError,
    ConnectionError,
    TimeoutError,
    ValueError,
)
try:
    # asyncpg emits driver-specific errors during pool/connection teardown races.
    # Treat them as backend init failures so caller-level SQLite fallback can proceed.
    from asyncpg.exceptions import InterfaceError as _AsyncpgInterfaceError
    from asyncpg.exceptions import PostgresError as _AsyncpgPostgresError
except ImportError:
    pass
else:
    _STORE_INIT_ERROR_TYPES = _STORE_INIT_ERROR_TYPES + (
        _AsyncpgInterfaceError,
        _AsyncpgPostgresError,
    )


class StorageBackendType(str, Enum):
    """Available storage backend types in preference order."""

    SUPABASE = "supabase"  # Preferred for persistent data
    POSTGRES = "postgres"  # Self-hosted fallback
    SQLITE = "sqlite"  # Last resort


@dataclass
class DatabaseConfig:
    """Resolved database configuration."""

    backend_type: StorageBackendType
    dsn: str | None
    is_supabase: bool
    pool: Any | None = None  # asyncpg Pool when available


# Global pool cache for connection reuse
_supabase_pool: Pool | None = None
_postgres_pool: Pool | None = None
_pool_lock = threading.Lock()


def _normalize_backend(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if not normalized or normalized == "auto":
        return None
    return normalized


def _get_backend_override(
    store_name: str,
    extra_envs: Sequence[str] | None = None,
    include_global: bool = True,
) -> str | None:
    candidates: list[str] = []
    if extra_envs:
        candidates.extend(extra_envs)
    candidates.append(f"ARAGORA_{store_name.upper()}_STORE_BACKEND")
    candidates.append(f"ARAGORA_{store_name.upper()}_BACKEND")
    if include_global:
        candidates.append("ARAGORA_DB_BACKEND")
    for key in candidates:
        normalized = _normalize_backend(os.environ.get(key))
        if normalized:
            return normalized
    return None


def _get_secret(name: str) -> str | None:
    """Get a secret from env or secrets manager.

    Args:
        name: Secret name (e.g., "SUPABASE_DB_PASSWORD")

    Returns:
        Secret value or None if not found
    """
    # First check environment
    value = os.environ.get(name)
    if value:
        return value

    # Try secrets manager as fallback
    try:
        from aragora.config.secrets import get_secret

        return get_secret(name)
    except ImportError:
        return None
    except (OSError, RuntimeError, ValueError):
        logger.debug("Secret fetch failed for %r, returning None", name, exc_info=True)
        return None


def get_supabase_postgres_dsn() -> str | None:
    """
    Get Supabase PostgreSQL connection string.

    Supabase provides direct PostgreSQL access. The DSN can be:
    1. Explicitly set via SUPABASE_POSTGRES_DSN (env or secrets manager)
    2. Derived from SUPABASE_URL + SUPABASE_DB_PASSWORD (env or secrets manager)

    Returns:
        PostgreSQL DSN for Supabase, or None if not configured
    """
    # Explicit DSN takes precedence (env or secrets manager)
    explicit_dsn = _get_secret("SUPABASE_POSTGRES_DSN")
    if explicit_dsn:
        logger.debug("Using explicit SUPABASE_POSTGRES_DSN")
        return explicit_dsn

    # Check if Supabase is configured for direct DB access
    supabase_url = _get_secret("SUPABASE_URL")
    db_password = _get_secret("SUPABASE_DB_PASSWORD")

    if not supabase_url or not db_password:
        return None

    # Derive PostgreSQL DSN from Supabase URL
    # Supabase URL format: https://<project-ref>.supabase.co
    # PostgreSQL format: postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres
    try:
        parsed = urlparse(supabase_url)
        project_ref = parsed.netloc.replace(".supabase.co", "")

        dsn = f"postgresql://postgres:{db_password}@db.{project_ref}.supabase.co:5432/postgres"
        logger.debug("Derived Supabase PostgreSQL DSN for project: %s", project_ref)
        return dsn
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("Failed to derive Supabase PostgreSQL DSN: %s", e)
        return None


def get_selfhosted_postgres_dsn() -> str | None:
    """
    Get self-hosted PostgreSQL connection string.

    Checks in order (env then secrets manager):
    1. ARAGORA_POSTGRES_DSN (preferred)
    2. DATABASE_URL (common convention in PaaS environments)

    Returns:
        PostgreSQL DSN, or None if not configured
    """
    return _get_secret("ARAGORA_POSTGRES_DSN") or _get_secret("DATABASE_URL")


def resolve_database_config(
    store_name: str = "default",
    allow_sqlite: bool = True,
) -> DatabaseConfig:
    """
    Resolve the database configuration based on preference order.

    Preference order:
    1. Supabase PostgreSQL (if configured)
    2. Self-hosted PostgreSQL (if configured)
    3. SQLite (if allowed)

    Args:
        store_name: Name of the store (for logging and per-store overrides)
        allow_sqlite: Whether to allow SQLite fallback

    Returns:
        DatabaseConfig with resolved backend information

    Raises:
        RuntimeError: If no suitable backend is available
    """
    # Check for explicit backend override (per-store or global)
    explicit_backend = _get_backend_override(store_name)

    if explicit_backend:
        if explicit_backend == "sqlite":
            if not allow_sqlite:
                raise RuntimeError(
                    f"SQLite not allowed for {store_name}. "
                    "Configure SUPABASE_URL or ARAGORA_POSTGRES_DSN."
                )
            logger.info("[%s] Using SQLite (explicit override)", store_name)
            return DatabaseConfig(
                backend_type=StorageBackendType.SQLITE,
                dsn=None,
                is_supabase=False,
            )

        if explicit_backend in ("postgres", "postgresql"):
            # Explicit postgres - use self-hosted, not Supabase
            dsn = get_selfhosted_postgres_dsn()
            if dsn:
                logger.info("[%s] Using self-hosted PostgreSQL (explicit)", store_name)
                return DatabaseConfig(
                    backend_type=StorageBackendType.POSTGRES,
                    dsn=dsn,
                    is_supabase=False,
                )
            message = (
                f"Explicit PostgreSQL backend requested for {store_name}, "
                "but ARAGORA_POSTGRES_DSN/DATABASE_URL is not configured."
            )
            if allow_sqlite:
                logger.warning("%s Falling back to auto-detect.", message)
            else:
                raise RuntimeError(message)

        if explicit_backend == "supabase":
            dsn = get_supabase_postgres_dsn()
            if dsn:
                logger.info("[%s] Using Supabase PostgreSQL (explicit)", store_name)
                return DatabaseConfig(
                    backend_type=StorageBackendType.SUPABASE,
                    dsn=dsn,
                    is_supabase=True,
                )
            message = (
                f"Explicit Supabase backend requested for {store_name}, "
                "but SUPABASE_URL + SUPABASE_DB_PASSWORD (or SUPABASE_POSTGRES_DSN) "
                "is not configured."
            )
            if allow_sqlite:
                logger.warning("%s Falling back to auto-detect.", message)
            else:
                raise RuntimeError(message)

        if explicit_backend in ("redis", "memory"):
            logger.warning(
                "[%s] Backend '%s' is not a persistent database backend. Falling back to auto-detect.",
                store_name,
                explicit_backend,
            )
        elif explicit_backend not in ("postgres", "postgresql", "supabase", "sqlite"):
            logger.warning(
                "[%s] Unknown backend override '%s'. Falling back to auto-detect.",
                store_name,
                explicit_backend,
            )

    # Auto-detect with preference order

    # 1. Try Supabase first (preferred)
    supabase_dsn = get_supabase_postgres_dsn()
    if supabase_dsn:
        logger.info("[%s] Using Supabase PostgreSQL (preferred)", store_name)
        return DatabaseConfig(
            backend_type=StorageBackendType.SUPABASE,
            dsn=supabase_dsn,
            is_supabase=True,
        )

    # 2. Try self-hosted PostgreSQL
    postgres_dsn = get_selfhosted_postgres_dsn()
    if postgres_dsn:
        logger.info("[%s] Using self-hosted PostgreSQL", store_name)
        return DatabaseConfig(
            backend_type=StorageBackendType.POSTGRES,
            dsn=postgres_dsn,
            is_supabase=False,
        )

    # 3. Fall back to SQLite
    if allow_sqlite:
        logger.info("[%s] Using SQLite (fallback)", store_name)
        return DatabaseConfig(
            backend_type=StorageBackendType.SQLITE,
            dsn=None,
            is_supabase=False,
        )

    raise RuntimeError(
        f"No suitable database backend for {store_name}. "
        f"Configure SUPABASE_URL + SUPABASE_DB_PASSWORD or "
        f"ARAGORA_POSTGRES_DSN / DATABASE_URL."
    )


async def get_database_pool(
    store_name: str = "default",
    allow_sqlite: bool = True,
    dsn_override: str | None = None,
) -> tuple[Pool | None, DatabaseConfig]:
    """
    Get an asyncpg connection pool based on preference order.

    Args:
        store_name: Name of the store for logging
        allow_sqlite: Whether SQLite fallback is allowed
        dsn_override: Optional DSN to use instead of auto-detection

    Returns:
        Tuple of (pool or None if SQLite, DatabaseConfig)
    """
    global _supabase_pool, _postgres_pool

    config = resolve_database_config(store_name, allow_sqlite)

    if config.backend_type == StorageBackendType.SQLITE:
        return None, config

    # Use override DSN if provided
    dsn = dsn_override or config.dsn

    # Get or create pool
    with _pool_lock:
        if config.is_supabase:
            if _supabase_pool is None:
                from aragora.storage.postgres_store import get_postgres_pool

                _supabase_pool = await get_postgres_pool(dsn=dsn)
            config.pool = _supabase_pool
            return _supabase_pool, config
        else:
            if _postgres_pool is None:
                from aragora.storage.postgres_store import get_postgres_pool

                _postgres_pool = await get_postgres_pool(dsn=dsn)
            config.pool = _postgres_pool
            return _postgres_pool, config


def is_production_environment() -> bool:
    """Check if running in production environment."""
    env = os.environ.get("ARAGORA_ENV", "development").lower()
    return env in ("production", "prod", "live", "staging", "stage")


def get_database_pool_sync(
    store_name: str = "default",
    allow_sqlite: bool = True,
    dsn_override: str | None = None,
) -> tuple[Pool | None, DatabaseConfig]:
    """
    Synchronous wrapper for get_database_pool.

    Handles event loop creation for threaded contexts safely.
    If called from an async context, returns config only (pool=None)
    and caller must handle async pool creation.
    """
    # First resolve config (always safe, no async)
    config = resolve_database_config(store_name, allow_sqlite)

    if config.backend_type == StorageBackendType.SQLITE:
        return None, config

    # Check if we're in an async context
    try:
        asyncio.get_running_loop()
        # We're in an async context - can't use run_until_complete
        # Return config with DSN, let caller handle pool creation async
        logger.debug("[%s] Async context detected, returning config only", store_name)
        return None, config
    except RuntimeError:
        # No running loop - safe to run async
        pass

    # Use run_async to safely run in sync context, avoiding deprecated get_event_loop()
    from aragora.utils.async_utils import run_async

    return run_async(get_database_pool(store_name, allow_sqlite, dsn_override))


async def close_all_pools() -> None:
    """Close all cached connection pools."""
    global _supabase_pool, _postgres_pool

    with _pool_lock:
        if _supabase_pool:
            await _supabase_pool.close()
            _supabase_pool = None
            logger.info("Closed Supabase connection pool")
        if _postgres_pool:
            await _postgres_pool.close()
            _postgres_pool = None
            logger.info("Closed PostgreSQL connection pool")


def reset_pools() -> None:
    """Reset pool cache (for testing)."""
    global _supabase_pool, _postgres_pool
    with _pool_lock:
        _supabase_pool = None
        _postgres_pool = None


async def _safe_store_init(store: Any, store_name: str) -> None:
    """Safely initialize a store asynchronously, logging any errors."""
    try:
        await store.initialize()
        logger.debug("[%s] Async store initialization completed", store_name)
    except (OSError, RuntimeError, ConnectionError, TimeoutError, ValueError) as e:
        logger.error("[%s] Async store initialization failed: %s", store_name, e)


def create_persistent_store(
    store_name: str,
    sqlite_class: type,
    postgres_class: type,
    db_filename: str,
    memory_class: type | None = None,
    data_dir: str | None = None,
) -> Any:
    """
    Create a persistent store instance with proper backend selection.

    This is a helper function to reduce code duplication across stores.
    It implements the preference order:
    1. Supabase PostgreSQL (if configured)
    2. Self-hosted PostgreSQL (if configured)
    3. SQLite (fallback, with production warning)

    Args:
        store_name: Name for logging and env var lookups
        sqlite_class: SQLite backend class
        postgres_class: PostgreSQL backend class
        db_filename: SQLite database filename
        memory_class: Optional in-memory backend (for testing)
        data_dir: Optional data directory override

    Returns:
        Initialized store instance

    Example:
        _store = create_persistent_store(
            "inbox",
            SQLiteUnifiedInboxStore,
            PostgresUnifiedInboxStore,
            "unified_inbox.db",
        )
    """
    from pathlib import Path

    # Check for memory backend override (testing only)
    backend_override = _get_backend_override(store_name, include_global=False)
    if backend_override == "memory" and memory_class:
        logger.info("[%s] Using in-memory store (testing)", store_name)
        return memory_class()

    # Check if we're in an async context - if so, we can't safely create PostgreSQL pools
    # because asyncpg pools are bound to specific event loops
    in_async_context = False
    try:
        asyncio.get_running_loop()
        in_async_context = True
    except RuntimeError as e:
        logger.warning("connection_factory operation failed: %s", e)

    # Determine if SQLite is allowed (not in production unless explicitly allowed)
    allow_sqlite = not is_production_environment()
    require_value = os.environ.get("ARAGORA_REQUIRE_DISTRIBUTED")
    legacy_value = os.environ.get("ARAGORA_REQUIRE_DISTRIBUTED_STATE")
    if require_value is None and legacy_value is not None:
        require_value = legacy_value
    if require_value is not None and is_production_environment():
        require_distributed = require_value.lower() in ("1", "true", "yes")
        if not require_distributed:
            allow_sqlite = True
    if os.environ.get("ARAGORA_ALLOW_SQLITE_FALLBACK", "").lower() in ("true", "1"):
        allow_sqlite = True

    # In async context, we MUST allow SQLite fallback because we can't safely create
    # PostgreSQL pools (asyncpg pools are event-loop bound)
    if in_async_context and not allow_sqlite:
        logger.warning(
            "[%s] Forcing SQLite fallback in async context. asyncpg pools cannot be created from within a running event loop. Initialize stores BEFORE starting the async server, or set ARAGORA_ALLOW_SQLITE_FALLBACK=true to suppress this warning.",
            store_name,
        )
        allow_sqlite = True

    # Get database configuration
    config = resolve_database_config(store_name, allow_sqlite=allow_sqlite)

    # Try PostgreSQL backends (Supabase or self-hosted)
    if config.backend_type in (StorageBackendType.SUPABASE, StorageBackendType.POSTGRES):
        # Check for pre-initialized shared pool FIRST
        # This is the recommended path: pool_manager initializes the pool
        # during server startup, and stores use it here
        try:
            from aragora.storage.pool_manager import get_shared_pool, is_pool_initialized

            if is_pool_initialized():
                pool = get_shared_pool()
                if pool:
                    try:
                        store = postgres_class(pool)
                        # Schedule async initialization if in async context
                        if hasattr(store, "initialize") and in_async_context:
                            loop = asyncio.get_running_loop()
                            loop.create_task(_safe_store_init(store, store_name))
                        elif hasattr(store, "initialize") and not in_async_context:
                            from aragora.utils.async_utils import run_async

                            run_async(store.initialize())
                        backend_name = "Supabase" if config.is_supabase else "PostgreSQL"
                        logger.info("[%s] Using shared pool (%s)", store_name, backend_name)
                        return store
                    except _STORE_INIT_ERROR_TYPES as e:
                        logger.warning("[%s] Shared pool store creation failed: %s", store_name, e)
        except ImportError:
            pass  # pool_manager not available

        if in_async_context:
            # No shared pool and can't safely create one from async context
            logger.warning(
                "[%s] Cannot initialize PostgreSQL from async context. asyncpg pools are event-loop bound. Initialize stores BEFORE starting the event loop, or use async store factory. Falling back to SQLite.",
                store_name,
            )
        else:
            try:
                pool, _ = get_database_pool_sync(store_name, allow_sqlite=allow_sqlite)
                if pool:
                    store = postgres_class(pool)
                    # Initialize if the store has an async initialize method
                    if hasattr(store, "initialize"):
                        from aragora.utils.async_utils import run_async

                        run_async(store.initialize())
                    backend_name = "Supabase" if config.is_supabase else "PostgreSQL"
                    logger.info("[%s] Initialized with %s", store_name, backend_name)
                    return store
                elif config.dsn:
                    from aragora.utils.async_utils import run_async

                    async def init_postgres():
                        from aragora.storage.postgres_store import get_postgres_pool

                        pool = await get_postgres_pool(dsn=config.dsn)
                        store = postgres_class(pool)
                        if hasattr(store, "initialize"):
                            await store.initialize()
                        return store

                    store = run_async(init_postgres())
                    backend_name = "Supabase" if config.is_supabase else "PostgreSQL"
                    logger.info("[%s] Initialized with %s", store_name, backend_name)
                    return store
            except _STORE_INIT_ERROR_TYPES + (ImportError,) as e:
                logger.warning("[%s] PostgreSQL unavailable: %s", store_name, e)
                if not allow_sqlite:
                    raise RuntimeError(
                        f"PostgreSQL required for {store_name} in production. "
                        f"Configure SUPABASE_URL or DATABASE_URL. Error: {e}"
                    )

    # SQLite fallback
    if not allow_sqlite:
        raise RuntimeError(
            f"No distributed storage available for {store_name} in production. "
            "Configure SUPABASE_URL + SUPABASE_DB_PASSWORD or DATABASE_URL."
        )

    # Determine data directory
    if data_dir:
        base_dir = Path(data_dir)
    else:
        base_dir = get_default_data_dir()

    db_path = base_dir / db_filename
    base_dir.mkdir(parents=True, exist_ok=True)

    if is_production_environment():
        logger.warning(
            "[%s] Using SQLite in production (not recommended). Configure Supabase or PostgreSQL for distributed deployments.",
            store_name,
        )

    logger.info("[%s] Using SQLite: %s", store_name, db_path)
    return sqlite_class(db_path)


def get_postgres_pool() -> Pool | None:
    """Get the cached PostgreSQL connection pool, if available.

    Returns:
        The cached asyncpg Pool, or None if not yet initialized.
    """
    return _postgres_pool


__all__ = [
    "StorageBackendType",
    "DatabaseConfig",
    "resolve_database_config",
    "get_database_pool",
    "get_database_pool_sync",
    "get_supabase_postgres_dsn",
    "get_selfhosted_postgres_dsn",
    "close_all_pools",
    "reset_pools",
    "is_production_environment",
    "create_persistent_store",
    "get_postgres_pool",
]
