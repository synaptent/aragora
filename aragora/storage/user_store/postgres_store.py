"""
PostgresUserStore - PostgreSQL backend for user and organization persistence.

Async implementation for production multi-instance deployments
with horizontal scaling and concurrent writes.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncpg import Pool


# Re-export from submodules for backward compatibility
from .postgres_store_users import UserOperationsMixin
from .postgres_store_orgs import OrganizationOperationsMixin
from .postgres_store_security import SecurityOperationsMixin

logger = logging.getLogger(__name__)


class PostgresUserStore(
    UserOperationsMixin,
    OrganizationOperationsMixin,
    SecurityOperationsMixin,
):
    """
    PostgreSQL-backed storage for users and organizations.

    Async implementation for production multi-instance deployments
    with horizontal scaling and concurrent writes.
    """

    SCHEMA_NAME = "user_store"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            name TEXT DEFAULT '',
            org_id TEXT,
            role TEXT DEFAULT 'member',
            is_active BOOLEAN DEFAULT TRUE,
            email_verified BOOLEAN DEFAULT FALSE,
            api_key TEXT UNIQUE,
            api_key_hash TEXT UNIQUE,
            api_key_prefix TEXT,
            api_key_created_at TIMESTAMPTZ,
            api_key_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_login_at TIMESTAMPTZ,
            mfa_secret TEXT,
            mfa_enabled BOOLEAN DEFAULT FALSE,
            mfa_backup_codes TEXT,
            token_version INTEGER DEFAULT 1,
            failed_login_attempts INTEGER DEFAULT 0,
            lockout_until TIMESTAMPTZ,
            last_failed_login_at TIMESTAMPTZ,
            preferences JSONB DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_api_key_hash ON users(api_key_hash);
        CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id);
        CREATE INDEX IF NOT EXISTS idx_users_org_role ON users(org_id, role);
        CREATE INDEX IF NOT EXISTS idx_users_email_active ON users(email, is_active);

        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            tier TEXT DEFAULT 'free',
            owner_id TEXT,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            debates_used_this_month INTEGER DEFAULT 0,
            billing_cycle_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            settings JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_orgs_slug ON organizations(slug);
        CREATE INDEX IF NOT EXISTS idx_orgs_stripe ON organizations(stripe_customer_id);

        CREATE TABLE IF NOT EXISTS usage_events (
            id SERIAL PRIMARY KEY,
            org_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_usage_org ON usage_events(org_id);
        CREATE INDEX IF NOT EXISTS idx_usage_org_type ON usage_events(org_id, event_type);

        CREATE TABLE IF NOT EXISTS oauth_providers (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_user_id TEXT NOT NULL,
            email TEXT,
            linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(provider, provider_user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_oauth_user ON oauth_providers(user_id);
        CREATE INDEX IF NOT EXISTS idx_oauth_provider ON oauth_providers(provider, provider_user_id);

        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            user_id TEXT,
            org_id TEXT,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            old_value JSONB,
            new_value JSONB,
            metadata JSONB DEFAULT '{}',
            ip_address TEXT,
            user_agent TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
        CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_log(org_id);
        CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

        CREATE TABLE IF NOT EXISTS org_invitations (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            token TEXT UNIQUE NOT NULL,
            invited_by TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            accepted_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_invitations_org ON org_invitations(org_id);
        CREATE INDEX IF NOT EXISTS idx_invitations_email ON org_invitations(email);
        CREATE INDEX IF NOT EXISTS idx_invitations_token ON org_invitations(token);
        CREATE INDEX IF NOT EXISTS idx_invitations_status ON org_invitations(status);
    """

    # Lockout policy constants
    LOCKOUT_THRESHOLD_1 = 3
    LOCKOUT_THRESHOLD_2 = 6
    LOCKOUT_THRESHOLD_3 = 10
    LOCKOUT_DURATION_1 = timedelta(minutes=5)
    LOCKOUT_DURATION_2 = timedelta(minutes=30)
    LOCKOUT_DURATION_3 = timedelta(hours=24)

    # Explicit columns for SELECT queries - prevents SELECT * data exposure
    _USER_COLUMNS = (
        "id, email, password_hash, password_salt, name, org_id, role, "
        "is_active, email_verified, api_key, api_key_hash, api_key_prefix, "
        "api_key_created_at, api_key_expires_at, created_at, updated_at, "
        "last_login_at, mfa_secret, mfa_enabled, mfa_backup_codes, token_version"
    )
    _ORG_COLUMNS = (
        "id, name, slug, tier, owner_id, stripe_customer_id, "
        "stripe_subscription_id, debates_used_this_month, billing_cycle_start, "
        "settings, created_at, updated_at"
    )
    _INVITATION_COLUMNS = (
        "id, org_id, email, role, token, invited_by, status, "
        "created_at, expires_at, accepted_by, accepted_at"
    )
    _AUDIT_LOG_COLUMNS = (
        "id, timestamp, user_id, org_id, action, resource_type, "
        "resource_id, old_value, new_value, metadata, ip_address, user_agent"
    )

    def __init__(self, pool: Pool):
        """
        Initialize PostgresUserStore.

        Args:
            pool: asyncpg connection pool
        """
        self.__pool = pool
        self._initialized = False
        logger.info("PostgresUserStore initialized")

    @property
    def _pool(self) -> Pool:
        """Get the connection pool, auto-refreshing from the shared pool if it has been replaced.

        When the shared pool is force-refreshed (e.g., after InterfaceError recovery),
        this property detects the change and updates the local reference so all subsequent
        operations use the fresh pool instead of the closed/stale one.
        """
        try:
            from aragora.storage.pool_manager import get_shared_pool

            shared = get_shared_pool()
            if shared is not None and shared is not self.__pool:
                logger.info("PostgresUserStore: pool reference updated from shared pool")
                self.__pool = shared
        except (ImportError, RuntimeError):
            pass  # pool_manager not available or event loop mismatch
        return self.__pool

    @_pool.setter
    def _pool(self, value: Pool) -> None:
        self.__pool = value

    async def initialize(self) -> None:
        """Initialize database schema."""
        if self._initialized:
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(self.INITIAL_SCHEMA)
        except Exception as e:  # noqa: BLE001 - filter for read-only replicas, re-raises otherwise
            # Handle read-only replicas gracefully — schema already exists there
            err_msg = str(e).lower()
            if "read-only" in err_msg or "read only" in err_msg:
                logger.info(
                    "[%s] Read-only database detected, skipping schema init",
                    self.SCHEMA_NAME,
                )
            else:
                raise

        self._initialized = True
        logger.debug("[%s] Schema initialized", self.SCHEMA_NAME)

    def close(self) -> None:
        """Close is a no-op for pool-based stores (pool managed externally)."""
        pass


__all__ = [
    "PostgresUserStore",
    # Re-exports from submodules
    "UserOperationsMixin",
    "OrganizationOperationsMixin",
    "SecurityOperationsMixin",
]
