"""
Integration Configuration Store.

Provides persistent storage for chat platform integration configurations.
Survives server restarts and supports multi-instance deployments via Redis.

Backends:
- InMemoryIntegrationStore: Fast, single-instance only (for testing)
- SQLiteIntegrationStore: Persisted, single-instance (default for production)
- RedisIntegrationStore: Distributed, multi-instance (optional with fallback)
- PostgresIntegrationStore: Distributed, multi-instance (production)

Usage:
    from aragora.storage.integration_store import get_integration_store

    store = get_integration_store()
    await store.save(config)
    config = await store.get("slack", user_id="user123")

This module re-exports all symbols from the split backend modules for full
backward compatibility. All existing imports from this module continue to work.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from aragora.config import resolve_db_path

# Re-export models, types, and helpers (backward compatibility)
from aragora.storage.integration_models import (  # noqa: F401
    CRYPTO_AVAILABLE,
    SENSITIVE_KEYS,
    VALID_INTEGRATION_TYPES,
    IntegrationConfig,
    IntegrationType,
    UserIdMapping,
    _decrypt_settings,
    _encrypt_settings,
    _make_key,
    _record_user_mapping_cache_hit,
    _record_user_mapping_cache_miss,
    _record_user_mapping_operation,
)

# Re-export abstract base (backward compatibility)
from aragora.storage.integration_backends import IntegrationStoreBackend

# Re-export all backends (backward compatibility)
from aragora.storage.integration_memory import InMemoryIntegrationStore
from aragora.storage.integration_sqlite import SQLiteIntegrationStore
from aragora.storage.integration_redis import RedisIntegrationStore
from aragora.storage.integration_postgres import PostgresIntegrationStore

logger = logging.getLogger(__name__)

# =============================================================================
# Global Store Factory
# =============================================================================

_integration_store: IntegrationStoreBackend | None = None


def get_integration_store() -> IntegrationStoreBackend:
    """
    Get or create the integration store.

    Backend selection (in preference order):
    1. Supabase PostgreSQL (if SUPABASE_URL + SUPABASE_DB_PASSWORD configured)
    2. Self-hosted PostgreSQL (if DATABASE_URL or ARAGORA_POSTGRES_DSN configured)
    3. Redis (if ARAGORA_INTEGRATION_STORE_BACKEND=redis and ARAGORA_REDIS_URL configured)
    4. SQLite (fallback, with production warning)

    Override via:
    - ARAGORA_INTEGRATION_STORE_BACKEND: "memory", "sqlite", "postgres", "supabase", or "redis"
    - ARAGORA_DB_BACKEND: Global override

    Returns:
        Configured IntegrationStoreBackend instance
    """
    global _integration_store
    if _integration_store is not None:
        return _integration_store

    # Check store-specific backend first
    backend_type = os.environ.get("ARAGORA_INTEGRATION_STORE_BACKEND", "").lower()

    # Handle Redis explicitly (not part of standard persistent store preference)
    if backend_type == "redis":
        # Get data directory for SQLite fallback
        db_path = Path(resolve_db_path("integrations.db"))
        logger.info("Using Redis integration store with SQLite fallback")
        _integration_store = RedisIntegrationStore(db_path)
        return _integration_store

    # Use unified connection factory for persistent storage
    from aragora.storage.connection_factory import create_persistent_store

    _integration_store = create_persistent_store(
        store_name="integration",
        sqlite_class=SQLiteIntegrationStore,
        postgres_class=PostgresIntegrationStore,
        db_filename="integrations.db",
        memory_class=InMemoryIntegrationStore,
    )

    return _integration_store


def set_integration_store(store: IntegrationStoreBackend) -> None:
    """
    Set custom integration store.

    Useful for testing or custom deployments.
    """
    global _integration_store
    _integration_store = store
    logger.debug("Integration store backend set: %s", type(store).__name__)


def reset_integration_store() -> None:
    """Reset the global integration store (for testing)."""
    global _integration_store
    _integration_store = None


__all__ = [
    "IntegrationConfig",
    "IntegrationType",
    "VALID_INTEGRATION_TYPES",
    "SENSITIVE_KEYS",
    "UserIdMapping",
    "IntegrationStoreBackend",
    "InMemoryIntegrationStore",
    "SQLiteIntegrationStore",
    "RedisIntegrationStore",
    "PostgresIntegrationStore",
    "get_integration_store",
    "set_integration_store",
    "reset_integration_store",
]
