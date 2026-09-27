"""
Production Guards for Storage Backends.

Enforces fail-closed semantics for storage backends in production environments.
When ARAGORA_REQUIRE_DISTRIBUTED=true (default in production), stores that
fall back to SQLite will raise errors instead of silently degrading.

This prevents multi-instance deployments from diverging due to per-node state.

Usage:
    from aragora.storage.production_guards import (
        require_distributed_store,
        is_production_mode,
        get_storage_mode,
    )

    # In store initialization:
    require_distributed_store("integration_store")

Environment Variables:
    ARAGORA_ENV: Environment name (production, staging, development)
    ARAGORA_REQUIRE_DISTRIBUTED: Force distributed storage requirement (true/false)
    ARAGORA_REQUIRE_DISTRIBUTED_STATE: Legacy alias for ARAGORA_REQUIRE_DISTRIBUTED
    ARAGORA_STORAGE_MODE: Override storage mode (postgres, redis, sqlite, file)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import cast

logger = logging.getLogger(__name__)


class StorageMode(str, Enum):
    """Storage backend modes.

    Preference order for persistent data:
    1. SUPABASE - Preferred (managed PostgreSQL with extras)
    2. POSTGRES - Self-hosted PostgreSQL (fallback)
    3. REDIS - For caching/sessions only
    4. SQLITE - Last resort (dev/test only)
    5. FILE/MEMORY - Testing only
    """

    SUPABASE = "supabase"  # Preferred for persistent data
    POSTGRES = "postgres"  # Self-hosted fallback
    REDIS = "redis"  # Caching, rate limiting, sessions
    SQLITE = "sqlite"  # Last resort (local only)
    FILE = "file"  # File-based (testing)
    MEMORY = "memory"  # In-memory (testing)


class EnvironmentMode(str, Enum):
    """Deployment environment modes."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    TEST = "test"


@dataclass
class StorageGuardConfig:
    """Configuration for storage guards."""

    require_distributed: bool = True
    allowed_fallback_envs: set[EnvironmentMode] = cast(set[EnvironmentMode], None)
    fail_open_stores: set[str] = cast(set[str], None)

    def __post_init__(self):
        if self.allowed_fallback_envs is None:
            self.allowed_fallback_envs = {
                EnvironmentMode.DEVELOPMENT,
                EnvironmentMode.TEST,
            }
        if self.fail_open_stores is None:
            # Stores that can safely fall back to local storage
            self.fail_open_stores = {
                "cache_store",  # Ephemeral cache
                "session_store",  # Short-lived sessions
                "workflow_store",  # Workflow definitions (static config, not dynamic state)
            }


# Global configuration
_config: StorageGuardConfig | None = None


def get_config() -> StorageGuardConfig:
    """Get or create storage guard configuration."""
    global _config
    if _config is None:
        require_value = os.environ.get("ARAGORA_REQUIRE_DISTRIBUTED")
        legacy_value = os.environ.get("ARAGORA_REQUIRE_DISTRIBUTED_STATE")
        if require_value is None and legacy_value is not None:
            require_value = legacy_value
        require_distributed = (require_value or "true").lower() in ("1", "true", "yes")
        _config = StorageGuardConfig(
            require_distributed=require_distributed,
        )
    return _config


def get_environment() -> EnvironmentMode:
    """Get the current environment mode."""
    env = os.environ.get("ARAGORA_ENV", "development").lower()

    if env in ("prod", "production"):
        return EnvironmentMode.PRODUCTION
    elif env in ("stage", "staging"):
        return EnvironmentMode.STAGING
    elif env in ("dev", "development"):
        return EnvironmentMode.DEVELOPMENT
    elif env in ("test", "testing"):
        return EnvironmentMode.TEST
    else:
        logger.warning("Unknown environment '%s', treating as development", env)
        return EnvironmentMode.DEVELOPMENT


def is_production_mode() -> bool:
    """Check if running in production mode."""
    return get_environment() in (
        EnvironmentMode.PRODUCTION,
        EnvironmentMode.STAGING,
    )


def get_storage_mode() -> StorageMode | None:
    """Get the explicitly configured storage mode, if any."""
    mode = os.environ.get("ARAGORA_STORAGE_MODE", "").lower()
    if not mode:
        return None

    try:
        return StorageMode(mode)
    except ValueError:
        logger.warning("Unknown storage mode '%s'", mode)
        return None


class DistributedStateError(Exception):
    """
    Raised when a store falls back to local storage in production.

    This indicates a configuration or infrastructure issue that must be
    resolved before the service can safely handle requests.
    """

    def __init__(self, store_name: str, reason: str):
        self.store_name = store_name
        self.reason = reason
        super().__init__(
            f"Distributed storage required for '{store_name}' in production mode. "
            f"Reason: {reason}. "
            f"Set ARAGORA_REQUIRE_DISTRIBUTED=false (or ARAGORA_REQUIRE_DISTRIBUTED_STATE=false) "
            f"to allow fallback (NOT recommended for production)."
        )


def require_distributed_store(
    store_name: str,
    current_mode: StorageMode,
    reason: str = "Store initialized with local backend",
) -> None:
    """
    Enforce distributed storage requirement in production.

    Call this when a store falls back to SQLite, file, or memory storage.
    In production mode (unless explicitly disabled), this will raise an error.

    Args:
        store_name: Name of the store (for error messages)
        current_mode: The storage mode the store is using
        reason: Explanation of why fallback occurred

    Raises:
        DistributedStateError: If distributed storage is required but not available

    Example:
        if not postgres_available:
            require_distributed_store(
                "integration_store",
                StorageMode.SQLITE,
                "PostgreSQL connection failed"
            )
            # Will raise in production, continue in development
            self._backend = SQLiteBackend()
    """
    config = get_config()
    env = get_environment()

    # Allow fallback during pytest runs regardless of environment.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        logger.info(
            "Store '%s' using %s backend during tests (pytest override)",
            store_name,
            current_mode.value,
        )
        return

    # Allow fallback in development/test
    if env in config.allowed_fallback_envs:
        logger.info(
            "Store '%s' using %s backend (allowed in %s environment)",
            store_name,
            current_mode.value,
            env.value,
        )
        return

    # Allow fallback for explicitly excluded stores
    if store_name in config.fail_open_stores:
        logger.info("Store '%s' using %s backend (fail-open store)", store_name, current_mode.value)
        return

    # Allow fallback if explicitly disabled
    if not config.require_distributed:
        logger.warning(
            "Store '%s' using %s backend in %s environment. Distributed state enforcement is DISABLED. This is NOT recommended for multi-instance deployments.",
            store_name,
            current_mode.value,
            env.value,
        )
        return

    # Local storage modes that require distributed enforcement
    local_modes = {StorageMode.SQLITE, StorageMode.FILE, StorageMode.MEMORY}

    if current_mode in local_modes:
        raise DistributedStateError(store_name, reason)

    # Using distributed backend, all good
    logger.debug("Store '%s' using distributed backend: %s", store_name, current_mode.value)


def validate_store_config(
    store_name: str,
    supabase_dsn: str | None = None,
    postgres_url: str | None = None,
    redis_url: str | None = None,
    fallback_mode: StorageMode = StorageMode.SQLITE,
) -> StorageMode:
    """
    Validate and determine storage mode for a store.

    Preference order for persistent data:
    1. Supabase PostgreSQL (preferred)
    2. Self-hosted PostgreSQL (fallback)
    3. Redis (for caching/sessions only)
    4. SQLite (last resort, dev/test only)

    In production, this ensures a distributed backend is available.
    In development, falls back gracefully to local storage.

    Args:
        store_name: Name of the store
        supabase_dsn: Supabase PostgreSQL connection DSN (preferred)
        postgres_url: Self-hosted PostgreSQL connection URL (fallback)
        redis_url: Redis connection URL (for caching stores)
        fallback_mode: Mode to use if distributed storage unavailable

    Returns:
        The storage mode to use

    Raises:
        DistributedStateError: If distributed storage required but unavailable
    """
    # Check for explicit override
    explicit_mode = get_storage_mode()
    if explicit_mode:
        logger.info("Store '%s' using explicit mode: %s", store_name, explicit_mode.value)
        require_distributed_store(
            store_name,
            explicit_mode,
            "Explicit mode configured via ARAGORA_STORAGE_MODE",
        )
        return explicit_mode

    # 1. Try Supabase first (preferred for persistent data)
    if supabase_dsn:
        logger.info("Store '%s' using Supabase PostgreSQL (preferred)", store_name)
        return StorageMode.SUPABASE

    # 2. Try self-hosted PostgreSQL (fallback)
    if postgres_url:
        logger.info("Store '%s' using self-hosted PostgreSQL", store_name)
        return StorageMode.POSTGRES

    # 3. Try Redis (for caching/session stores)
    if redis_url:
        logger.info("Store '%s' using Redis backend", store_name)
        return StorageMode.REDIS

    # 4. Fall back to local storage (with production guard)
    require_distributed_store(
        store_name,
        fallback_mode,
        "No Supabase, PostgreSQL, or Redis configured. "
        "Set SUPABASE_URL + SUPABASE_DB_PASSWORD, DATABASE_URL, or ARAGORA_REDIS_URL.",
    )

    logger.info("Store '%s' using %s backend (fallback)", store_name, fallback_mode.value)
    return fallback_mode


def check_multi_instance_readiness() -> dict[str, bool]:
    """
    Check if all critical stores are configured for multi-instance deployment.

    Returns:
        Dict mapping store names to readiness status
    """
    from aragora.storage.integration_store import get_integration_store
    from aragora.storage.webhook_store import get_webhook_store
    from aragora.storage.gmail_token_store import get_gmail_token_store

    stores = {
        "integration_store": False,
        "webhook_store": False,
        "gmail_token_store": False,
        "workflow_store": False,
        "checkpoint_store": False,
        "user_store": False,
        "audit_log": False,
    }

    # Check each store's backend
    try:
        int_store = get_integration_store()
        stores["integration_store"] = getattr(int_store, "_uses_distributed", False)
    except (OSError, RuntimeError, ValueError, ImportError) as e:
        logger.debug("Could not check integration_store: %s", e)

    try:
        webhook_store = get_webhook_store()
        stores["webhook_store"] = getattr(webhook_store, "_uses_distributed", False)
    except (OSError, RuntimeError, ValueError, ImportError) as e:
        logger.debug("Could not check webhook_store: %s", e)

    try:
        gmail_store = get_gmail_token_store()
        stores["gmail_token_store"] = getattr(gmail_store, "_uses_distributed", False)
    except (OSError, RuntimeError, ValueError, ImportError) as e:
        logger.debug("Could not check gmail_token_store: %s", e)

    # Check user store - critical for authentication
    try:
        from aragora.storage.user_store import get_user_store, PostgresUserStore

        user_store = get_user_store()
        stores["user_store"] = isinstance(user_store, PostgresUserStore)
    except (OSError, RuntimeError, ValueError, ImportError) as e:
        logger.debug("Could not check user_store: %s", e)

    # Check audit log - critical for compliance
    try:
        from aragora.audit.log import get_audit_log

        audit_log = get_audit_log()
        # Note: AuditLog currently uses SQLite backend for simplicity.
        # For distributed deployments, implement PostgresAuditLog backend
        # when horizontal scaling of audit data is required.
        stores["audit_log"] = getattr(audit_log, "_uses_distributed", False)
    except (OSError, RuntimeError, ValueError, ImportError) as e:
        logger.debug("Could not check audit_log: %s", e)

    return stores


__all__ = [
    "StorageMode",
    "EnvironmentMode",
    "StorageGuardConfig",
    "DistributedStateError",
    "get_config",
    "get_environment",
    "is_production_mode",
    "get_storage_mode",
    "require_distributed_store",
    "validate_store_config",
    "check_multi_instance_readiness",
]
