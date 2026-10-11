"""
PostgreSQL Migration Runner for Aragora.

Provides async migration support for PostgreSQL databases with rollback support.

Usage:
    from aragora.persistence.migrations.postgres import PostgresMigrationRunner

    runner = PostgresMigrationRunner()
    await runner.migrate()              # Run pending migrations
    await runner.rollback(target=1)     # Rollback to version 1
    await runner.status()               # Check migration status
    await runner.migrate(dry_run=True)  # Preview migrations without applying
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Optional asyncpg import
try:
    import asyncpg
    from asyncpg import Connection, Pool

    ASYNCPG_AVAILABLE = True
except ImportError:
    asyncpg = None
    Pool = Any
    Connection = Any
    ASYNCPG_AVAILABLE = False


@dataclass
class MigrationRecord:
    """Record of an applied migration."""

    version: int
    name: str
    applied_at: datetime
    checksum: str | None = None


@dataclass
class MigrationResult:
    """Result of a migration operation."""

    success: bool
    migrations_applied: int
    migrations_rolled_back: int
    current_version: int
    errors: list[str]
    dry_run: bool = False


class PostgresMigrationRunner:
    """
    Async PostgreSQL migration runner.

    Discovers and applies migrations in order, tracking applied migrations
    in a _migrations table.
    """

    MIGRATIONS_TABLE = "_migrations"
    MIGRATIONS_DIR = Path(__file__).parent

    def __init__(
        self,
        pool: Pool | None = None,
        dsn: str | None = None,
    ):
        """
        Initialize the migration runner.

        Args:
            pool: Existing asyncpg pool to use
            dsn: PostgreSQL DSN (if pool not provided)
        """
        self._pool = pool
        self._dsn = dsn or os.environ.get("ARAGORA_POSTGRES_DSN") or os.environ.get("DATABASE_URL")
        self._migrations: dict[int, dict[str, Any]] = {}

    async def _get_pool(self) -> Pool:
        """Get or create connection pool."""
        if not ASYNCPG_AVAILABLE:
            raise RuntimeError(
                "PostgreSQL migrations require 'asyncpg' package. "
                "Install with: pip install aragora[postgres]"
            )

        if self._pool is not None:
            return self._pool

        if not self._dsn:
            raise RuntimeError(
                "PostgreSQL DSN not configured. Set ARAGORA_POSTGRES_DSN or pass dsn parameter."
            )

        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        return self._pool

    async def _ensure_migrations_table(self, conn: Connection) -> None:
        """Create migrations tracking table if it doesn't exist."""
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.MIGRATIONS_TABLE} (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT NOW(),
                checksum TEXT
            )
        """)

    async def _get_applied_versions(self, conn: Connection) -> set[int]:
        """Get set of applied migration versions."""
        # table name interpolation, parameterized
        rows = await conn.fetch(f"SELECT version FROM {self.MIGRATIONS_TABLE}")
        return {row["version"] for row in rows}

    async def _record_migration(
        self, conn: Connection, version: int, name: str, checksum: str | None = None
    ) -> None:
        """Record that a migration was applied."""
        await conn.execute(
            f"""
            INSERT INTO {self.MIGRATIONS_TABLE} (version, name, checksum)
            VALUES ($1, $2, $3)
        """,  # table name interpolation, parameterized
            version,
            name,
            checksum,
        )

    @staticmethod
    def _compute_checksum(sql: str) -> str:
        """Compute SHA-256 checksum for migration SQL."""
        normalized = sql.strip().replace("\r\n", "\n")
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def register_migration(
        self, version: int, name: str, up_sql: str, down_sql: str | None = None
    ) -> None:
        """
        Register a migration.

        Args:
            version: Migration version number
            name: Human-readable name
            up_sql: SQL to apply migration
            down_sql: SQL to reverse migration (optional)
        """
        checksum = self._compute_checksum(up_sql)

        async def migrate(conn: Connection) -> None:
            await conn.execute(up_sql)

        async def rollback(conn: Connection) -> None:
            if down_sql:
                await conn.execute(down_sql)
            else:
                raise ValueError(f"Migration {version} ({name}) has no rollback SQL defined")

        self._migrations[version] = {
            "name": name,
            "up": migrate,
            "down": rollback,
            "down_sql": down_sql,
            "checksum": checksum,
        }

    async def migrate(self, dry_run: bool = False, target: int | None = None) -> MigrationResult:
        """
        Run pending migrations.

        Args:
            dry_run: If True, preview migrations without applying
            target: Optional target version to migrate to

        Returns:
            MigrationResult with details of the operation
        """
        pool = await self._get_pool()
        applied_count = 0
        errors: list[str] = []
        current_version = 0

        async with pool.acquire() as conn:
            await self._ensure_migrations_table(conn)
            applied = await self._get_applied_versions(conn)
            current_version = max(applied) if applied else 0

            # Get pending migrations in order
            pending = sorted(v for v in self._migrations.keys() if v not in applied)

            # Filter by target if specified
            if target is not None:
                pending = [v for v in pending if v <= target]

            if dry_run:
                logger.info("[DRY RUN] Would apply %s migrations", len(pending))
                for version in pending:
                    migration = self._migrations[version]
                    logger.info(
                        "  - %s: %s (checksum: %s)",
                        version,
                        migration["name"],
                        migration["checksum"],
                    )
                return MigrationResult(
                    success=True,
                    migrations_applied=len(pending),
                    migrations_rolled_back=0,
                    current_version=current_version,
                    errors=[],
                    dry_run=True,
                )

            for version in pending:
                migration = self._migrations[version]
                name = migration["name"]
                checksum = migration["checksum"]
                logger.info("Applying migration %s: %s", version, name)

                try:
                    async with conn.transaction():
                        await migration["up"](conn)
                        await self._record_migration(conn, version, name, checksum)

                    applied_count += 1
                    current_version = version
                    logger.info("Migration %s applied successfully", version)
                except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                    error_msg = f"Migration {version} failed: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    break  # Stop on first error

        return MigrationResult(
            success=len(errors) == 0,
            migrations_applied=applied_count,
            migrations_rolled_back=0,
            current_version=current_version,
            errors=errors,
            dry_run=False,
        )

    async def rollback(
        self, target: int | None = None, steps: int = 1, dry_run: bool = False
    ) -> MigrationResult:
        """
        Rollback migrations.

        Args:
            target: Target version to rollback to (exclusive)
            steps: Number of migrations to rollback (ignored if target specified)
            dry_run: If True, preview rollback without applying

        Returns:
            MigrationResult with details of the operation
        """
        pool = await self._get_pool()
        rolled_back_count = 0
        errors: list[str] = []

        async with pool.acquire() as conn:
            await self._ensure_migrations_table(conn)

            # Get applied migrations in reverse order
            rows = await conn.fetch(
                # table name interpolation, parameterized
                f"SELECT version, name, checksum FROM {self.MIGRATIONS_TABLE} ORDER BY version DESC"
            )
            if not rows:
                return MigrationResult(
                    success=True,
                    migrations_applied=0,
                    migrations_rolled_back=0,
                    current_version=0,
                    errors=["No migrations to rollback"],
                    dry_run=dry_run,
                )

            current_version = rows[0]["version"]

            # Determine which migrations to rollback
            if target is not None:
                to_rollback = [r for r in rows if r["version"] > target]
            else:
                to_rollback = rows[:steps]

            if not to_rollback:
                return MigrationResult(
                    success=True,
                    migrations_applied=0,
                    migrations_rolled_back=0,
                    current_version=current_version,
                    errors=["No migrations to rollback"],
                    dry_run=dry_run,
                )

            if dry_run:
                logger.info("[DRY RUN] Would rollback %s migrations", len(to_rollback))
                for row in to_rollback:
                    logger.info("  - %s: %s", row["version"], row["name"])
                return MigrationResult(
                    success=True,
                    migrations_applied=0,
                    migrations_rolled_back=len(to_rollback),
                    current_version=current_version,
                    errors=[],
                    dry_run=True,
                )

            for row in to_rollback:
                version = row["version"]
                name = row["name"]

                if version not in self._migrations:
                    error_msg = f"Migration {version} ({name}) not found in registered migrations"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    break

                migration = self._migrations[version]

                # Verify checksum if available
                if row["checksum"] and migration["checksum"] != row["checksum"]:
                    logger.warning(
                        "Migration %s checksum mismatch: expected %s, got %s",
                        version,
                        row["checksum"],
                        migration["checksum"],
                    )

                if migration["down_sql"] is None:
                    error_msg = f"Migration {version} ({name}) has no rollback SQL"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    break

                logger.info("Rolling back migration %s: %s", version, name)

                try:
                    async with conn.transaction():
                        await migration["down"](conn)
                        await conn.execute(
                            # class constant table name
                            f"DELETE FROM {self.MIGRATIONS_TABLE} WHERE version = $1",
                            version,  # table name interpolation, parameterized
                        )

                    rolled_back_count += 1
                    current_version = version - 1
                    logger.info("Migration %s rolled back successfully", version)
                except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                    error_msg = f"Rollback of migration {version} failed: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    break

        # Get actual current version after rollback
        async with pool.acquire() as conn:
            # table name interpolation, parameterized
            rows = await conn.fetch(f"SELECT MAX(version) as version FROM {self.MIGRATIONS_TABLE}")
            current_version = rows[0]["version"] if rows and rows[0]["version"] else 0

        return MigrationResult(
            success=len(errors) == 0,
            migrations_applied=0,
            migrations_rolled_back=rolled_back_count,
            current_version=current_version,
            errors=errors,
            dry_run=False,
        )

    async def verify_checksums(self) -> dict[int, tuple[bool, str]]:
        """
        Verify checksums of applied migrations against registered migrations.

        Returns:
            Dict mapping version to (is_valid, message) tuple
        """
        pool = await self._get_pool()
        results: dict[int, tuple[bool, str]] = {}

        async with pool.acquire() as conn:
            await self._ensure_migrations_table(conn)
            # table name interpolation, parameterized
            rows = await conn.fetch(f"SELECT version, name, checksum FROM {self.MIGRATIONS_TABLE}")

            for row in rows:
                version = row["version"]
                stored_checksum = row["checksum"]

                if version not in self._migrations:
                    results[version] = (False, f"Migration {version} not registered")
                    continue

                current_checksum = self._migrations[version]["checksum"]

                if stored_checksum is None:
                    results[version] = (True, "No checksum stored (legacy migration)")
                elif stored_checksum == current_checksum:
                    results[version] = (True, "Checksum matches")
                else:
                    results[version] = (
                        False,
                        f"Checksum mismatch: stored={stored_checksum}, current={current_checksum}",
                    )

        return results

    async def status(self) -> dict:
        """
        Get migration status.

        Returns:
            Dict with current_version, pending_count, and migration lists
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await self._ensure_migrations_table(conn)
            applied = await self._get_applied_versions(conn)

            all_versions = set(self._migrations.keys())
            pending = sorted(all_versions - applied)
            current = max(applied) if applied else 0

            return {
                "current_version": current,
                "pending_count": len(pending),
                "applied": sorted(applied),
                "pending": pending,
            }

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


# Singleton instance
_runner: PostgresMigrationRunner | None = None


def get_postgres_migration_runner() -> PostgresMigrationRunner:
    """Get or create the global PostgreSQL migration runner."""
    global _runner
    if _runner is None:
        _runner = PostgresMigrationRunner()
        # Register built-in migrations
        _register_core_migrations(_runner)
    return _runner


def _register_core_migrations(runner: PostgresMigrationRunner) -> None:
    """
    Register the core Aragora migrations.

    This function orchestrates registration of all core migrations by calling
    stage-specific helper functions. Each helper registers one migration version.
    """
    _register_migration_001_initial_schema(runner)
    _register_migration_002_lockout_support(runner)
    _register_migration_003_debates_memory(runner)
    _register_migration_004_knowledge_mound(runner)
    _register_migration_005_knowledge_mound_advanced(runner)


def _register_migration_001_initial_schema(runner: PostgresMigrationRunner) -> None:
    """
    Register migration 001: Initial schema.

    Creates core tables for users, organizations, usage tracking, OAuth,
    audit logging, and organization invitations.
    """
    runner.register_migration(
        version=1,
        name="Initial schema",
        up_sql="""
            -- Users table
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                name TEXT DEFAULT '',
                org_id TEXT,
                role TEXT DEFAULT 'member',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                last_login_at TIMESTAMPTZ,
                is_active BOOLEAN DEFAULT TRUE,
                email_verified BOOLEAN DEFAULT FALSE,
                avatar_url TEXT,
                preferences JSONB DEFAULT '{}'
            );

            -- Organizations table
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                tier TEXT DEFAULT 'free',
                owner_id TEXT REFERENCES users(id),
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                settings JSONB DEFAULT '{}'
            );

            -- Add foreign key after both tables exist
            ALTER TABLE users ADD CONSTRAINT fk_users_org
                FOREIGN KEY (org_id) REFERENCES organizations(id)
                ON DELETE SET NULL;

            -- Usage events table
            CREATE TABLE IF NOT EXISTS usage_events (
                id SERIAL PRIMARY KEY,
                org_id TEXT NOT NULL REFERENCES organizations(id),
                event_type TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                metadata JSONB DEFAULT '{}',
                timestamp TIMESTAMPTZ DEFAULT NOW()
            );

            -- OAuth providers table
            CREATE TABLE IF NOT EXISTS oauth_providers (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                email TEXT,
                access_token TEXT,
                refresh_token TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(provider, provider_user_id)
            );

            -- Audit log table
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                user_id TEXT,
                org_id TEXT,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                details JSONB DEFAULT '{}',
                ip_address INET,
                user_agent TEXT
            );

            -- Organization invitations table
            CREATE TABLE IF NOT EXISTS org_invitations (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL REFERENCES organizations(id),
                email TEXT NOT NULL,
                role TEXT DEFAULT 'member',
                token TEXT UNIQUE NOT NULL,
                invited_by TEXT REFERENCES users(id),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                expires_at TIMESTAMPTZ,
                accepted_at TIMESTAMPTZ
            );

            -- Create indexes
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE INDEX IF NOT EXISTS idx_users_org ON users(org_id);
            CREATE INDEX IF NOT EXISTS idx_orgs_slug ON organizations(slug);
            CREATE INDEX IF NOT EXISTS idx_orgs_stripe ON organizations(stripe_customer_id);
            CREATE INDEX IF NOT EXISTS idx_usage_org ON usage_events(org_id);
            CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_log(org_id);
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_invitations_token ON org_invitations(token);
            CREATE INDEX IF NOT EXISTS idx_invitations_email ON org_invitations(email);
        """,
        down_sql="""
            DROP TABLE IF EXISTS org_invitations;
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS oauth_providers;
            DROP TABLE IF EXISTS usage_events;
            ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_users_org;
            DROP TABLE IF EXISTS organizations;
            DROP TABLE IF EXISTS users;
        """,
    )


def _register_migration_002_lockout_support(runner: PostgresMigrationRunner) -> None:
    """
    Register migration 002: Add lockout support.

    Adds columns to the users table for tracking failed login attempts
    and account lockout state.
    """
    runner.register_migration(
        version=2,
        name="Add lockout support",
        up_sql="""
            -- Add lockout columns to users
            ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS lockout_until TIMESTAMPTZ;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS last_failed_login TIMESTAMPTZ;

            -- Index for finding locked users
            CREATE INDEX IF NOT EXISTS idx_users_lockout ON users(lockout_until)
                WHERE lockout_until IS NOT NULL;
        """,
        down_sql="""
            DROP INDEX IF EXISTS idx_users_lockout;
            ALTER TABLE users DROP COLUMN IF EXISTS last_failed_login;
            ALTER TABLE users DROP COLUMN IF EXISTS lockout_until;
            ALTER TABLE users DROP COLUMN IF EXISTS failed_login_attempts;
        """,
    )


def _register_migration_003_debates_memory(runner: PostgresMigrationRunner) -> None:
    """
    Register migration 003: Debates and memory tables.

    Creates tables for debate tracking, debate messages, agent ELO ratings,
    and consensus memory storage.
    """
    runner.register_migration(
        version=3,
        name="Debates and memory tables",
        up_sql="""
            -- Debates table
            CREATE TABLE IF NOT EXISTS debates (
                id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                org_id TEXT REFERENCES organizations(id),
                user_id TEXT REFERENCES users(id),
                status TEXT DEFAULT 'pending',
                result JSONB,
                config JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ,
                rounds_used INTEGER DEFAULT 0,
                consensus_reached BOOLEAN DEFAULT FALSE,
                confidence REAL DEFAULT 0.0
            );

            -- Debate messages
            CREATE TABLE IF NOT EXISTS debate_messages (
                id SERIAL PRIMARY KEY,
                debate_id TEXT NOT NULL REFERENCES debates(id) ON DELETE CASCADE,
                agent TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                round INTEGER DEFAULT 1,
                timestamp TIMESTAMPTZ DEFAULT NOW()
            );

            -- Agent ELO ratings
            CREATE TABLE IF NOT EXISTS agent_elo (
                agent TEXT PRIMARY KEY,
                rating REAL DEFAULT 1500.0,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                last_game_at TIMESTAMPTZ,
                metadata JSONB DEFAULT '{}'
            );

            -- Consensus memory
            CREATE TABLE IF NOT EXISTS consensus_memory (
                id TEXT PRIMARY KEY,
                task_hash TEXT NOT NULL,
                task TEXT NOT NULL,
                answer TEXT,
                confidence REAL DEFAULT 0.0,
                debate_id TEXT REFERENCES debates(id),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                hits INTEGER DEFAULT 0
            );

            -- Create indexes
            CREATE INDEX IF NOT EXISTS idx_debates_org ON debates(org_id);
            CREATE INDEX IF NOT EXISTS idx_debates_user ON debates(user_id);
            CREATE INDEX IF NOT EXISTS idx_debates_status ON debates(status);
            CREATE INDEX IF NOT EXISTS idx_debates_created ON debates(created_at);
            CREATE INDEX IF NOT EXISTS idx_messages_debate ON debate_messages(debate_id);
            CREATE INDEX IF NOT EXISTS idx_consensus_hash ON consensus_memory(task_hash);
        """,
        down_sql="""
            DROP TABLE IF EXISTS consensus_memory;
            DROP TABLE IF EXISTS agent_elo;
            DROP TABLE IF EXISTS debate_messages;
            DROP TABLE IF EXISTS debates;
        """,
    )


def _register_migration_004_knowledge_mound(runner: PostgresMigrationRunner) -> None:
    """
    Register migration 004: Knowledge mound tables.

    Creates core knowledge mound tables for items, relationships (links),
    and staleness tracking.
    """
    runner.register_migration(
        version=4,
        name="Knowledge mound tables",
        up_sql="""
            -- Knowledge items
            CREATE TABLE IF NOT EXISTS knowledge_items (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                content TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT,
                confidence REAL DEFAULT 0.5,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                expires_at TIMESTAMPTZ,
                metadata JSONB DEFAULT '{}',
                embedding BYTEA
            );

            -- Knowledge links (relationships)
            CREATE TABLE IF NOT EXISTS knowledge_links (
                id SERIAL PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES knowledge_items(id) ON DELETE CASCADE,
                target_id TEXT NOT NULL REFERENCES knowledge_items(id) ON DELETE CASCADE,
                relationship TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(source_id, target_id, relationship)
            );

            -- Knowledge staleness tracking
            CREATE TABLE IF NOT EXISTS knowledge_staleness (
                item_id TEXT PRIMARY KEY REFERENCES knowledge_items(id) ON DELETE CASCADE,
                last_validated TIMESTAMPTZ DEFAULT NOW(),
                staleness_score REAL DEFAULT 0.0,
                validation_count INTEGER DEFAULT 0,
                needs_revalidation BOOLEAN DEFAULT FALSE
            );

            -- Create indexes
            CREATE INDEX IF NOT EXISTS idx_knowledge_workspace ON knowledge_items(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge_items(source_type, source_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_created ON knowledge_items(created_at);
            CREATE INDEX IF NOT EXISTS idx_links_source ON knowledge_links(source_id);
            CREATE INDEX IF NOT EXISTS idx_links_target ON knowledge_links(target_id);
            CREATE INDEX IF NOT EXISTS idx_staleness_revalidate ON knowledge_staleness(needs_revalidation)
                WHERE needs_revalidation = TRUE;
        """,
        down_sql="""
            DROP TABLE IF EXISTS knowledge_staleness;
            DROP TABLE IF EXISTS knowledge_links;
            DROP TABLE IF EXISTS knowledge_items;
        """,
    )


def _register_migration_005_knowledge_mound_advanced(runner: PostgresMigrationRunner) -> None:
    """
    Register migration 005: Knowledge Mound advanced tables and indexes.

    Creates advanced Knowledge Mound schema including:
    - knowledge_nodes: Extended node schema with visibility and validation
    - provenance_chains: Provenance tracking for knowledge origin
    - knowledge_relationships: Graph relationships between nodes
    - node_topics: Topic categorization
    - culture_patterns: Organizational learning patterns
    - staleness_checks: Staleness tracking
    - archived_nodes: Archived node storage
    - access_grants: Fine-grained sharing permissions
    - Performance indexes for all tables
    """
    runner.register_migration(
        version=5,
        name="Knowledge Mound advanced tables and indexes",
        up_sql="""
            -- Knowledge nodes (core metadata) - extended schema
            CREATE TABLE IF NOT EXISTS knowledge_nodes (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                node_type TEXT NOT NULL CHECK (node_type IN ('fact', 'claim', 'memory', 'evidence', 'consensus', 'entity', 'culture')),
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                tier TEXT DEFAULT 'slow' CHECK (tier IN ('fast', 'medium', 'slow', 'glacial')),
                surprise_score REAL DEFAULT 0.0,
                update_count INTEGER DEFAULT 1,
                consolidation_score REAL DEFAULT 0.0,
                validation_status TEXT DEFAULT 'unverified',
                consensus_proof_id TEXT,
                last_validated_at TIMESTAMPTZ,
                staleness_score REAL DEFAULT 0.0,
                revalidation_requested BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                metadata JSONB DEFAULT '{}',
                visibility TEXT DEFAULT 'workspace' CHECK (visibility IN ('private', 'workspace', 'organization', 'public', 'system')),
                visibility_set_by TEXT,
                is_discoverable BOOLEAN DEFAULT TRUE
            );

            -- Provenance tracking
            CREATE TABLE IF NOT EXISTS provenance_chains (
                id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                agent_id TEXT,
                debate_id TEXT,
                document_id TEXT,
                user_id TEXT,
                parent_provenance_id TEXT REFERENCES provenance_chains(id),
                transformation_type TEXT,
                transformations JSONB DEFAULT '[]',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            -- Graph relationships
            CREATE TABLE IF NOT EXISTS knowledge_relationships (
                id TEXT PRIMARY KEY,
                from_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                to_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                relationship_type TEXT NOT NULL CHECK (relationship_type IN ('supports', 'contradicts', 'derived_from', 'related_to', 'supersedes', 'cites', 'elaborates')),
                strength REAL DEFAULT 1.0,
                created_by TEXT,
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            -- Topics for categorization
            CREATE TABLE IF NOT EXISTS node_topics (
                node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                topic TEXT NOT NULL,
                PRIMARY KEY (node_id, topic)
            );

            -- Culture patterns (organizational learning)
            CREATE TABLE IF NOT EXISTS culture_patterns (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                pattern_type TEXT NOT NULL,
                pattern_key TEXT NOT NULL,
                pattern_value JSONB NOT NULL,
                observation_count INTEGER DEFAULT 1,
                confidence REAL DEFAULT 0.5,
                first_observed_at TIMESTAMPTZ NOT NULL,
                last_observed_at TIMESTAMPTZ NOT NULL,
                contributing_debates TEXT[],
                metadata JSONB DEFAULT '{}'
            );

            -- Staleness tracking
            CREATE TABLE IF NOT EXISTS staleness_checks (
                id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                checked_at TIMESTAMPTZ NOT NULL,
                staleness_score REAL NOT NULL,
                trigger TEXT NOT NULL,
                revalidation_requested BOOLEAN DEFAULT FALSE,
                revalidation_completed_at TIMESTAMPTZ,
                metadata JSONB DEFAULT '{}'
            );

            -- Archived nodes
            CREATE TABLE IF NOT EXISTS archived_nodes (
                id TEXT PRIMARY KEY,
                original_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                node_data JSONB NOT NULL,
                archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                archived_by TEXT
            );

            -- Access grants for fine-grained sharing
            CREATE TABLE IF NOT EXISTS access_grants (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                grantee_type TEXT NOT NULL CHECK (grantee_type IN ('user', 'role', 'workspace', 'organization')),
                grantee_id TEXT NOT NULL,
                permissions TEXT[] DEFAULT '{read}',
                granted_by TEXT,
                granted_at TIMESTAMPTZ DEFAULT NOW(),
                expires_at TIMESTAMPTZ,
                UNIQUE(item_id, grantee_type, grantee_id)
            );

            -- Performance indexes for knowledge_nodes
            CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_workspace ON knowledge_nodes(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_workspace_type ON knowledge_nodes(workspace_id, node_type);
            CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_workspace_visibility ON knowledge_nodes(workspace_id, visibility);
            CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_created ON knowledge_nodes(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_workspace_created ON knowledge_nodes(workspace_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_content_hash ON knowledge_nodes(content_hash);

            -- Performance indexes for provenance_chains
            CREATE INDEX IF NOT EXISTS idx_provenance_chains_node ON provenance_chains(node_id);
            CREATE INDEX IF NOT EXISTS idx_provenance_chains_source ON provenance_chains(source_type, source_id);
            CREATE INDEX IF NOT EXISTS idx_provenance_chains_debate ON provenance_chains(debate_id) WHERE debate_id IS NOT NULL;

            -- Performance indexes for knowledge_relationships
            CREATE INDEX IF NOT EXISTS idx_knowledge_relationships_from ON knowledge_relationships(from_node_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_relationships_to ON knowledge_relationships(to_node_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_relationships_nodes ON knowledge_relationships(from_node_id, to_node_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_relationships_type ON knowledge_relationships(relationship_type);

            -- Performance indexes for node_topics
            CREATE INDEX IF NOT EXISTS idx_node_topics_topic ON node_topics(topic);

            -- Performance indexes for culture_patterns
            CREATE INDEX IF NOT EXISTS idx_culture_patterns_workspace ON culture_patterns(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_culture_patterns_workspace_type ON culture_patterns(workspace_id, pattern_type);

            -- Performance indexes for staleness_checks
            CREATE INDEX IF NOT EXISTS idx_staleness_checks_node ON staleness_checks(node_id, checked_at DESC);

            -- Performance indexes for access_grants (hot path)
            CREATE INDEX IF NOT EXISTS idx_access_grants_item ON access_grants(item_id);
            CREATE INDEX IF NOT EXISTS idx_access_grants_grantee ON access_grants(grantee_type, grantee_id);
            CREATE INDEX IF NOT EXISTS idx_access_grants_item_grantee ON access_grants(item_id, grantee_type, grantee_id);

            -- Performance indexes for archived_nodes
            CREATE INDEX IF NOT EXISTS idx_archived_nodes_original ON archived_nodes(original_id);
            CREATE INDEX IF NOT EXISTS idx_archived_nodes_workspace ON archived_nodes(workspace_id, archived_at DESC);
        """,
        down_sql="""
            DROP TABLE IF EXISTS access_grants;
            DROP TABLE IF EXISTS archived_nodes;
            DROP TABLE IF EXISTS staleness_checks;
            DROP TABLE IF EXISTS culture_patterns;
            DROP TABLE IF EXISTS node_topics;
            DROP TABLE IF EXISTS knowledge_relationships;
            DROP TABLE IF EXISTS provenance_chains;
            DROP TABLE IF EXISTS knowledge_nodes;
        """,
    )
