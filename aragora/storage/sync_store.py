"""
Persistent storage for enterprise connector sync state.

Provides SQLite/PostgreSQL-backed storage for:
- Connector configurations (with encrypted credentials)
- Sync job history and status
- Sync statistics and metrics

Usage:
    store = SyncStore()
    await store.initialize()

    # Save connector config
    await store.save_connector(connector_id, config)

    # Record sync job
    await store.record_sync_start(connector_id, sync_id)
    await store.record_sync_complete(sync_id, items_synced, status)

    # Get history
    history = await store.get_sync_history(connector_id, limit=50)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from aragora.config import resolve_db_path

if TYPE_CHECKING:
    import aiosqlite
    import asyncpg

logger = logging.getLogger(__name__)

# Import distributed state requirements
from aragora.control_plane.leader import (
    DistributedStateError,
    is_distributed_state_required,
)

# Import encryption (optional - graceful degradation if not available)
# Declare types for fallback case
get_encryption_service: Any = None
is_encryption_required: Any = None
EncryptionError: Any = Exception
CRYPTO_AVAILABLE = False

try:
    from aragora.security.encryption import (  # type: ignore[no-redef]
        get_encryption_service,
        is_encryption_required,
        EncryptionError,
        CRYPTO_AVAILABLE,
    )
except ImportError:
    # CRYPTO_AVAILABLE stays False from line 53

    def _fallback_get_encryption_service() -> Any:
        raise RuntimeError("Encryption not available")

    def _fallback_is_encryption_required() -> bool:
        """Fallback when security module unavailable - still check env vars."""
        import os

        if os.environ.get("ARAGORA_ENCRYPTION_REQUIRED", "").lower() in ("true", "1", "yes"):
            return True
        if os.environ.get("ARAGORA_ENV") == "production":
            return True
        return False

    class _FallbackEncryptionError(Exception):
        """Fallback exception when security module unavailable."""

        def __init__(self, operation: str, reason: str, store: str = ""):
            self.operation = operation
            self.reason = reason
            self.store = store
            super().__init__(
                f"Encryption {operation} failed in {store}: {reason}. "
                f"Set ARAGORA_ENCRYPTION_REQUIRED=false to allow plaintext fallback."
            )

    get_encryption_service = _fallback_get_encryption_service
    is_encryption_required = _fallback_is_encryption_required
    EncryptionError = _FallbackEncryptionError


# Import metrics (optional - graceful degradation if not available)
# Define fallback functions with proper signatures first
def _noop_record_encryption_operation(
    operation: str, success: bool, latency_seconds: float
) -> None:
    """No-op fallback when metrics module is unavailable."""
    pass


def _noop_record_encryption_error(operation: str, error_type: str) -> None:
    """No-op fallback when metrics module is unavailable."""
    pass


# Try to import real implementations
record_encryption_operation = _noop_record_encryption_operation
record_encryption_error = _noop_record_encryption_error
METRICS_AVAILABLE = False

try:
    from aragora.observability.metrics import (  # type: ignore[attr-defined]
        record_encryption_operation as _real_record_encryption_operation,
        record_encryption_error as _real_record_encryption_error,
    )

    record_encryption_operation = _real_record_encryption_operation  # type: ignore[assignment]
    record_encryption_error = _real_record_encryption_error
    METRICS_AVAILABLE = True
except (ImportError, AttributeError):
    # Metrics functions are optional and may not be exported in all configurations
    logger.debug("encryption metrics unavailable, running without instrumentation")


# Credential fields that should be encrypted
CREDENTIAL_KEYWORDS = frozenset(
    [
        "api_key",
        "secret",
        "password",
        "token",
        "auth_token",
        "access_key",
        "private_key",
        "credentials",
        "client_secret",
    ]
)


def _is_sensitive_key(key: str) -> bool:
    """Check if a config key is sensitive (should be encrypted)."""
    key_lower = key.lower()
    return any(kw in key_lower for kw in CREDENTIAL_KEYWORDS)


def _encrypt_config(
    config: dict[str, Any], use_encryption: bool, connector_id: str = ""
) -> dict[str, Any]:
    """
    Encrypt sensitive fields in connector config.

    Uses connector_id as Associated Authenticated Data (AAD) to bind the
    ciphertext to a specific connector, preventing cross-connector attacks.

    Raises:
        EncryptionError: If encryption fails and ARAGORA_ENCRYPTION_REQUIRED is True.
    """
    import time

    if not use_encryption or not config:
        return config

    sensitive_keys = [k for k in config if _is_sensitive_key(k)]
    if not sensitive_keys:
        return config

    if not CRYPTO_AVAILABLE:
        if is_encryption_required():
            raise EncryptionError(
                "encrypt",
                "cryptography library not available",
                "sync_store",
            )
        return config

    try:
        start = time.perf_counter()
        service = get_encryption_service()
        # AAD binds config to this specific connector
        result = service.encrypt_fields(
            config, sensitive_keys, connector_id if connector_id else None
        )
        latency = time.perf_counter() - start
        record_encryption_operation("encrypt", True, latency)
        return result
    except (OSError, ValueError, TypeError, RuntimeError) as e:
        record_encryption_error("encrypt", type(e).__name__)
        if is_encryption_required():
            logger.warning("Config encryption failed for %s: %s", connector_id, e)
            raise EncryptionError(
                "encrypt",
                "Config encryption failed",
                "sync_store",
            ) from e
        logger.warning("Config encryption unavailable for %s: %s", connector_id, e)
        return config


def _decrypt_config(
    config: dict[str, Any], use_encryption: bool, connector_id: str = ""
) -> dict[str, Any]:
    """
    Decrypt sensitive fields in connector config.

    AAD must match what was used during encryption.
    """
    import time

    if not use_encryption or not CRYPTO_AVAILABLE or not config:
        return config

    # Check for encryption markers - if none present, it's legacy data
    has_encrypted = any(isinstance(v, dict) and v.get("_encrypted") for v in config.values())
    if not has_encrypted:
        return config  # Legacy unencrypted data - return as-is

    try:
        start = time.perf_counter()
        service = get_encryption_service()
        sensitive_keys = [
            k for k in config if isinstance(config[k], dict) and config[k].get("_encrypted")
        ]
        if not sensitive_keys:
            return config
        result = service.decrypt_fields(
            config, sensitive_keys, connector_id if connector_id else None
        )
        latency = time.perf_counter() - start
        record_encryption_operation("decrypt", True, latency)
        return result
    except (OSError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("Config decryption failed for %s: %s", connector_id, e)
        record_encryption_error("decrypt", type(e).__name__)
        return config


@dataclass
class ConnectorConfig:
    """Stored connector configuration."""

    id: str
    connector_type: str
    name: str
    config: dict[str, Any]
    status: str = "configured"  # configured, active, error, disabled
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    items_indexed: int = 0
    error_message: str | None = None


@dataclass
class SyncJob:
    """Record of a sync operation."""

    id: str
    connector_id: str
    status: str  # running, completed, failed, cancelled
    started_at: datetime
    completed_at: datetime | None = None
    items_synced: int = 0
    items_failed: int = 0
    error_message: str | None = None
    duration_seconds: float | None = None


class SyncStore:
    """
    Persistent storage backend for connector sync state.

    Supports SQLite (default) and PostgreSQL backends.
    Uses aiosqlite for async SQLite access.
    """

    def __init__(
        self,
        database_url: str | None = None,
        use_encryption: bool = True,
    ):
        """
        Initialize the sync store.

        Args:
            database_url: Database URL. Defaults to SQLite file under ARAGORA_DATA_DIR.
                - sqlite:///path/to/db.sqlite
                - postgresql://user:pass@host/db
            use_encryption: Whether to encrypt sensitive config fields
        """
        default_sqlite_path = resolve_db_path("connectors.db")
        default_url = f"sqlite:///{default_sqlite_path}"
        candidate_url = database_url or os.environ.get("ARAGORA_SYNC_DATABASE_URL")
        if candidate_url:
            if "://" in candidate_url:
                self._database_url = candidate_url
            else:
                self._database_url = f"sqlite:///{resolve_db_path(candidate_url)}"
        else:
            self._database_url = default_url
        self._use_encryption = use_encryption
        self._initialized = False
        self._connection: aiosqlite.Connection | asyncpg.Connection | None = None

        # In-memory cache for fast access
        self._connectors_cache: dict[str, ConnectorConfig] = {}
        self._active_jobs: dict[str, SyncJob] = {}
        self._sync_history: list[SyncJob] = []

    async def initialize(self) -> None:
        """Initialize database connection and create tables."""
        if self._initialized:
            return

        if self._database_url.startswith("sqlite"):
            await self._init_sqlite()
        elif self._database_url.startswith("postgresql"):
            await self._init_postgres()
        else:
            raise ValueError(f"Unsupported database URL: {self._database_url}")

        self._initialized = True
        logger.info("SyncStore initialized with %s", self._database_url.split("://")[0])

    async def _init_sqlite(self) -> None:
        """Initialize SQLite database."""
        try:
            import aiosqlite
        except ImportError:
            # Check if distributed state is required (multi-instance or production)
            if is_distributed_state_required():
                raise DistributedStateError(
                    "sync_store",
                    "aiosqlite not installed for SQLite persistence. "
                    "Install with: pip install aiosqlite or set ARAGORA_SINGLE_INSTANCE=true.",
                )
            logger.warning(
                "CONNECTOR SYNC STORE: aiosqlite not installed - using in-memory fallback. "
                "DATA WILL BE LOST ON RESTART! Install with: pip install aiosqlite. "
                "Set ARAGORA_MULTI_INSTANCE=true to enforce persistent storage."
            )
            return

        # Extract path from URL
        db_path = self._database_url.replace("sqlite:///", "")

        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        self._connection = await aiosqlite.connect(db_path)
        if self._connection is None:
            raise RuntimeError("Database connection failed")

        # Create tables
        await self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS connectors (
                id TEXT PRIMARY KEY,
                connector_type TEXT NOT NULL,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL,
                status TEXT DEFAULT 'configured',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_sync_at TEXT,
                last_sync_status TEXT,
                items_indexed INTEGER DEFAULT 0,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS sync_jobs (
                id TEXT PRIMARY KEY,
                connector_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                items_synced INTEGER DEFAULT 0,
                items_failed INTEGER DEFAULT 0,
                error_message TEXT,
                duration_seconds REAL,
                FOREIGN KEY (connector_id) REFERENCES connectors(id)
            );

            CREATE INDEX IF NOT EXISTS idx_sync_jobs_connector
                ON sync_jobs(connector_id, started_at DESC);

            CREATE INDEX IF NOT EXISTS idx_connectors_status
                ON connectors(status);
        """)
        await self._connection.commit()

        # Load connectors into cache
        async with self._connection.execute("SELECT * FROM connectors") as cursor:
            async for row in cursor:
                connector_id = row[0]
                config = ConnectorConfig(
                    id=connector_id,
                    connector_type=row[1],
                    name=row[2],
                    config=_decrypt_config(json.loads(row[3]), self._use_encryption, connector_id),
                    status=row[4],
                    created_at=datetime.fromisoformat(row[5]),
                    updated_at=datetime.fromisoformat(row[6]),
                    last_sync_at=datetime.fromisoformat(row[7]) if row[7] else None,
                    last_sync_status=row[8],
                    items_indexed=row[9] or 0,
                    error_message=row[10],
                )
                self._connectors_cache[config.id] = config

        # Recover stale running jobs (mark as interrupted)
        await self._recover_running_jobs()

    async def _init_postgres(self) -> None:
        """Initialize PostgreSQL database."""
        try:
            import asyncpg
        except ImportError:
            # Check if distributed state is required (multi-instance or production)
            if is_distributed_state_required():
                raise DistributedStateError(
                    "sync_store",
                    "asyncpg not installed for PostgreSQL persistence. "
                    "Install with: pip install asyncpg or set ARAGORA_SINGLE_INSTANCE=true.",
                )
            logger.warning(
                "CONNECTOR SYNC STORE: asyncpg not installed - using in-memory fallback. "
                "DATA WILL BE LOST ON RESTART! Install with: pip install asyncpg. "
                "Set ARAGORA_MULTI_INSTANCE=true to enforce persistent storage."
            )
            return

        self._connection = await asyncpg.connect(self._database_url)
        if self._connection is None:
            raise RuntimeError("Database connection failed")

        # Create tables
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS connectors (
                id TEXT PRIMARY KEY,
                connector_type TEXT NOT NULL,
                name TEXT NOT NULL,
                config_json JSONB NOT NULL,
                status TEXT DEFAULT 'configured',
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                last_sync_at TIMESTAMPTZ,
                last_sync_status TEXT,
                items_indexed INTEGER DEFAULT 0,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS sync_jobs (
                id TEXT PRIMARY KEY,
                connector_id TEXT NOT NULL REFERENCES connectors(id),
                status TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL,
                completed_at TIMESTAMPTZ,
                items_synced INTEGER DEFAULT 0,
                items_failed INTEGER DEFAULT 0,
                error_message TEXT,
                duration_seconds REAL
            );

            CREATE INDEX IF NOT EXISTS idx_sync_jobs_connector
                ON sync_jobs(connector_id, started_at DESC);

            CREATE INDEX IF NOT EXISTS idx_connectors_status
                ON connectors(status);
        """)

        # Load connectors into cache
        # Cast to asyncpg.Connection since we checked database_url above
        pg_conn = cast("asyncpg.Connection[Any]", self._connection)
        rows = await pg_conn.fetch("SELECT * FROM connectors")
        for row in rows:
            connector_id = row["id"]
            config_json = row["config_json"]
            config_data = json.loads(config_json) if isinstance(config_json, str) else config_json
            config = ConnectorConfig(
                id=connector_id,
                connector_type=row["connector_type"],
                name=row["name"],
                config=_decrypt_config(config_data, self._use_encryption, connector_id),
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                last_sync_at=row["last_sync_at"],
                last_sync_status=row["last_sync_status"],
                items_indexed=row["items_indexed"] or 0,
                error_message=row["error_message"],
            )
            self._connectors_cache[config.id] = config

        # Recover stale running jobs (mark as interrupted)
        await self._recover_running_jobs()

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            self._initialized = False

    async def _recover_running_jobs(self) -> int:
        """
        Recover sync jobs that were running when the server was restarted.

        Jobs with status='running' that are not in _active_jobs (i.e., were
        running during a previous server instance) are marked as 'interrupted'.
        This prevents them from appearing as perpetually running.

        Returns:
            Number of jobs recovered (marked as interrupted)
        """
        if not self._connection:
            return 0

        recovered = 0
        now = datetime.now(timezone.utc)

        try:
            if self._database_url.startswith("sqlite"):
                # Find running jobs that aren't in our active memory
                async with self._connection.execute(
                    "SELECT id, connector_id, started_at FROM sync_jobs WHERE status = 'running'"
                ) as cursor:
                    async for row in cursor:
                        job_id = row[0]
                        connector_id = row[1]
                        # If not in our active jobs, it was running in a previous instance
                        if job_id not in self._active_jobs:
                            started_at_str = row[2]
                            if started_at_str:
                                started_at = datetime.fromisoformat(started_at_str)
                                # Ensure timezone-aware (assume UTC if naive)
                                if started_at.tzinfo is None:
                                    started_at = started_at.replace(tzinfo=timezone.utc)
                            else:
                                started_at = now
                            duration = (now - started_at).total_seconds()

                            await self._connection.execute(
                                """
                                UPDATE sync_jobs
                                SET status = 'interrupted',
                                    completed_at = ?,
                                    duration_seconds = ?,
                                    error_message = 'Job interrupted by server restart'
                                WHERE id = ?
                                """,
                                (now.isoformat(), duration, job_id),
                            )
                            recovered += 1

                            # Also update connector status if it was active
                            if connector_id in self._connectors_cache:
                                connector = self._connectors_cache[connector_id]
                                if connector.status == "active":
                                    connector.status = "configured"
                                    connector.last_sync_status = "interrupted"
                                    connector.last_sync_at = now
                                    # Persist connector status change
                                    await self._connection.execute(
                                        """
                                        UPDATE connectors
                                        SET status = 'configured',
                                            last_sync_status = 'interrupted',
                                            last_sync_at = ?,
                                            updated_at = ?
                                        WHERE id = ?
                                        """,
                                        (now.isoformat(), now.isoformat(), connector_id),
                                    )

                if recovered > 0:
                    await self._connection.commit()
                    logger.info(
                        "SyncStore: Recovered %s interrupted sync jobs from previous server instance",
                        recovered,
                    )

            elif self._database_url.startswith("postgresql"):
                # PostgreSQL version
                # Cast to asyncpg.Connection since we checked database_url above
                pg_conn = cast("asyncpg.Connection[Any]", self._connection)
                rows = await pg_conn.fetch(
                    "SELECT id, connector_id, started_at FROM sync_jobs WHERE status = 'running'"
                )
                for row in rows:
                    job_id = row["id"]
                    if job_id not in self._active_jobs:
                        started_at = row["started_at"]
                        if started_at is None:
                            started_at = now
                        elif started_at.tzinfo is None:
                            # Ensure timezone-aware (assume UTC if naive)
                            started_at = started_at.replace(tzinfo=timezone.utc)
                        duration = (now - started_at).total_seconds()

                        await self._connection.execute(
                            """
                            UPDATE sync_jobs
                            SET status = 'interrupted',
                                completed_at = $1,
                                duration_seconds = $2,
                                error_message = 'Job interrupted by server restart'
                            WHERE id = $3
                            """,
                            now,
                            duration,
                            job_id,
                        )
                        recovered += 1

                        connector_id = row["connector_id"]
                        if connector_id in self._connectors_cache:
                            connector = self._connectors_cache[connector_id]
                            if connector.status == "active":
                                connector.status = "configured"
                                connector.last_sync_status = "interrupted"
                                connector.last_sync_at = now
                                # Persist connector status change
                                await self._connection.execute(
                                    """
                                    UPDATE connectors
                                    SET status = 'configured',
                                        last_sync_status = 'interrupted',
                                        last_sync_at = $1,
                                        updated_at = $1
                                    WHERE id = $2
                                    """,
                                    now,
                                    connector_id,
                                )

                if recovered > 0:
                    logger.info(
                        "SyncStore: Recovered %s interrupted sync jobs from previous server instance",
                        recovered,
                    )

        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as e:
            logger.warning("SyncStore: Failed to recover running jobs: %s", e)

        return recovered

    async def recover_running_jobs(self) -> int:
        """
        Public method to recover running jobs.

        Call this after initialize() if you want explicit control over recovery.
        By default, recovery happens automatically during initialization.

        Returns:
            Number of jobs recovered (marked as interrupted)
        """
        return await self._recover_running_jobs()

    # ==================== Connector Operations ====================

    async def save_connector(
        self,
        connector_id: str,
        connector_type: str,
        name: str,
        config: dict[str, Any],
    ) -> ConnectorConfig:
        """
        Save or update a connector configuration.

        Args:
            connector_id: Unique connector ID
            connector_type: Type (github, s3, sharepoint, etc.)
            name: Display name
            config: Configuration dictionary (credentials encrypted if enabled)

        Returns:
            Saved ConnectorConfig
        """
        now = datetime.now(timezone.utc)

        existing = self._connectors_cache.get(connector_id)
        if existing:
            # Update
            existing.name = name
            existing.config = config
            existing.updated_at = now
            connector = existing
        else:
            # Create new
            connector = ConnectorConfig(
                id=connector_id,
                connector_type=connector_type,
                name=name,
                config=config,
                created_at=now,
                updated_at=now,
            )

        self._connectors_cache[connector_id] = connector

        # Persist to database
        if self._connection:
            # Encrypt config with connector_id as AAD for integrity
            encrypted_config = _encrypt_config(config, self._use_encryption, connector_id)
            config_json = json.dumps(encrypted_config)

            if self._database_url.startswith("sqlite"):
                await self._connection.execute(
                    """
                    INSERT OR REPLACE INTO connectors
                    (id, connector_type, name, config_json, status,
                     created_at, updated_at, last_sync_at, last_sync_status,
                     items_indexed, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        connector.id,
                        connector.connector_type,
                        connector.name,
                        config_json,
                        connector.status,
                        connector.created_at.isoformat(),
                        connector.updated_at.isoformat(),
                        connector.last_sync_at.isoformat() if connector.last_sync_at else None,
                        connector.last_sync_status,
                        connector.items_indexed,
                        connector.error_message,
                    ),
                )
                await self._connection.commit()
            else:
                # PostgreSQL
                await self._connection.execute(
                    """
                    INSERT INTO connectors
                    (id, connector_type, name, config_json, status,
                     created_at, updated_at, last_sync_at, last_sync_status,
                     items_indexed, error_message)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        config_json = EXCLUDED.config_json,
                        updated_at = EXCLUDED.updated_at
                """,
                    connector.id,
                    connector.connector_type,
                    connector.name,
                    encrypted_config,
                    connector.status,
                    connector.created_at,
                    connector.updated_at,
                    connector.last_sync_at,
                    connector.last_sync_status,
                    connector.items_indexed,
                    connector.error_message,
                )

        return connector

    async def get_connector(self, connector_id: str) -> ConnectorConfig | None:
        """Get connector by ID."""
        return self._connectors_cache.get(connector_id)

    async def list_connectors(
        self,
        status: str | None = None,
        connector_type: str | None = None,
    ) -> list[ConnectorConfig]:
        """List all connectors, optionally filtered."""
        connectors = list(self._connectors_cache.values())

        if status:
            connectors = [c for c in connectors if c.status == status]
        if connector_type:
            connectors = [c for c in connectors if c.connector_type == connector_type]

        return sorted(connectors, key=lambda c: c.updated_at, reverse=True)

    async def delete_connector(self, connector_id: str) -> bool:
        """Delete a connector."""
        if connector_id not in self._connectors_cache:
            return False

        del self._connectors_cache[connector_id]

        if self._connection:
            if self._database_url.startswith("sqlite"):
                await self._connection.execute(
                    "DELETE FROM connectors WHERE id = ?", (connector_id,)
                )
                await self._connection.commit()
            else:
                await self._connection.execute("DELETE FROM connectors WHERE id = $1", connector_id)

        return True

    async def update_connector_status(
        self,
        connector_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update connector status."""
        connector = self._connectors_cache.get(connector_id)
        if not connector:
            return

        connector.status = status
        connector.error_message = error_message
        connector.updated_at = datetime.now(timezone.utc)

        if self._connection:
            if self._database_url.startswith("sqlite"):
                await self._connection.execute(
                    """
                    UPDATE connectors
                    SET status = ?, error_message = ?, updated_at = ?
                    WHERE id = ?
                """,
                    (status, error_message, connector.updated_at.isoformat(), connector_id),
                )
                await self._connection.commit()

    # ==================== Sync Job Operations ====================

    async def record_sync_start(
        self,
        connector_id: str,
        sync_id: str | None = None,
    ) -> SyncJob:
        """Record the start of a sync operation."""
        job = SyncJob(
            id=sync_id or str(uuid4()),
            connector_id=connector_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )

        self._active_jobs[job.id] = job

        # Update connector status
        if connector_id in self._connectors_cache:
            self._connectors_cache[connector_id].status = "active"

        # Persist
        if self._connection:
            if self._database_url.startswith("sqlite"):
                await self._connection.execute(
                    """
                    INSERT INTO sync_jobs
                    (id, connector_id, status, started_at)
                    VALUES (?, ?, ?, ?)
                """,
                    (job.id, job.connector_id, job.status, job.started_at.isoformat()),
                )
                # Also update connector status in database
                await self._connection.execute(
                    "UPDATE connectors SET status = 'active', updated_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), connector_id),
                )
                await self._connection.commit()
            elif self._database_url.startswith("postgresql"):
                await self._connection.execute(
                    """
                    INSERT INTO sync_jobs
                    (id, connector_id, status, started_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    job.id,
                    job.connector_id,
                    job.status,
                    job.started_at,
                )
                # Also update connector status in database
                await self._connection.execute(
                    "UPDATE connectors SET status = 'active', updated_at = $1 WHERE id = $2",
                    datetime.now(timezone.utc),
                    connector_id,
                )

        return job

    async def record_sync_progress(
        self,
        sync_id: str,
        items_synced: int,
        items_failed: int = 0,
    ) -> None:
        """Update sync progress."""
        job = self._active_jobs.get(sync_id)
        if job:
            job.items_synced = items_synced
            job.items_failed = items_failed

    async def record_sync_complete(
        self,
        sync_id: str,
        status: str = "completed",
        items_synced: int | None = None,
        items_failed: int = 0,
        error_message: str | None = None,
    ) -> SyncJob | None:
        """Record sync completion."""
        job = self._active_jobs.pop(sync_id, None)
        if not job:
            return None

        job.status = status
        job.completed_at = datetime.now(timezone.utc)
        job.duration_seconds = (job.completed_at - job.started_at).total_seconds()
        if items_synced is not None:
            job.items_synced = items_synced
        job.items_failed = items_failed
        job.error_message = error_message

        # Update connector
        connector = self._connectors_cache.get(job.connector_id)
        if connector:
            connector.status = "configured" if status == "completed" else "error"
            connector.last_sync_at = job.completed_at
            connector.last_sync_status = status
            if status == "completed":
                connector.items_indexed += job.items_synced
                connector.error_message = None
            else:
                connector.error_message = error_message

        # Persist
        if self._connection:
            if self._database_url.startswith("sqlite"):
                await self._connection.execute(
                    """
                    UPDATE sync_jobs
                    SET status = ?, completed_at = ?, items_synced = ?,
                        items_failed = ?, error_message = ?, duration_seconds = ?
                    WHERE id = ?
                """,
                    (
                        job.status,
                        job.completed_at.isoformat(),
                        job.items_synced,
                        job.items_failed,
                        job.error_message,
                        job.duration_seconds,
                        job.id,
                    ),
                )
                await self._connection.commit()
        else:
            self._sync_history.append(job)

        return job

    async def get_sync_history(
        self,
        connector_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SyncJob]:
        """Get sync history, optionally filtered by connector."""
        jobs = []

        if self._connection and self._database_url.startswith("sqlite"):
            params: tuple[Any, ...]
            if connector_id:
                query = """
                    SELECT * FROM sync_jobs
                    WHERE connector_id = ?
                    ORDER BY started_at DESC
                    LIMIT ? OFFSET ?
                """
                params = (connector_id, limit, offset)
            else:
                query = """
                    SELECT * FROM sync_jobs
                    ORDER BY started_at DESC
                    LIMIT ? OFFSET ?
                """
                params = (limit, offset)

            async with self._connection.execute(query, params) as cursor:
                async for row in cursor:
                    jobs.append(
                        SyncJob(
                            id=row[0],
                            connector_id=row[1],
                            status=row[2],
                            started_at=datetime.fromisoformat(row[3]),
                            completed_at=datetime.fromisoformat(row[4]) if row[4] else None,
                            items_synced=row[5] or 0,
                            items_failed=row[6] or 0,
                            error_message=row[7],
                            duration_seconds=row[8],
                        )
                    )

        elif not self._connection:
            jobs.extend(self._sync_history)

        # Include active jobs
        for job in self._active_jobs.values():
            if connector_id is None or job.connector_id == connector_id:
                jobs.append(job)

        return sorted(jobs, key=lambda j: j.started_at, reverse=True)[:limit]

    async def get_sync_stats(
        self,
        connector_id: str | None = None,
    ) -> dict[str, Any]:
        """Get aggregate sync statistics."""
        stats = {
            "total_syncs": 0,
            "successful_syncs": 0,
            "failed_syncs": 0,
            "total_items_synced": 0,
            "total_items_failed": 0,
            "avg_duration_seconds": 0.0,
            "active_syncs": len(self._active_jobs),
        }

        if self._connection and self._database_url.startswith("sqlite"):
            stats_params: tuple[Any, ...]
            if connector_id:
                query = """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                        SUM(items_synced) as items_synced,
                        SUM(items_failed) as items_failed,
                        AVG(duration_seconds) as avg_duration
                    FROM sync_jobs
                    WHERE connector_id = ?
                """
                stats_params = (connector_id,)
            else:
                query = """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                        SUM(items_synced) as items_synced,
                        SUM(items_failed) as items_failed,
                        AVG(duration_seconds) as avg_duration
                    FROM sync_jobs
                """
                stats_params = ()

            async with self._connection.execute(query, stats_params) as cursor:
                row = await cursor.fetchone()
                if row:
                    stats["total_syncs"] = row[0] or 0
                    stats["successful_syncs"] = row[1] or 0
                    stats["failed_syncs"] = row[2] or 0
                    stats["total_items_synced"] = row[3] or 0
                    stats["total_items_failed"] = row[4] or 0
                    stats["avg_duration_seconds"] = row[5] or 0.0
        elif not self._connection:
            history_jobs = [
                job
                for job in self._sync_history
                if connector_id is None or job.connector_id == connector_id
            ]
            total_syncs = len(history_jobs)
            successful_syncs = len([job for job in history_jobs if job.status == "completed"])
            failed_syncs = len([job for job in history_jobs if job.status == "failed"])
            total_items_synced = sum(job.items_synced for job in history_jobs)
            total_items_failed = sum(job.items_failed for job in history_jobs)
            durations = [job.duration_seconds for job in history_jobs if job.duration_seconds]
            avg_duration = sum(durations) / len(durations) if durations else 0.0

            stats["total_syncs"] = total_syncs
            stats["successful_syncs"] = successful_syncs
            stats["failed_syncs"] = failed_syncs
            stats["total_items_synced"] = total_items_synced
            stats["total_items_failed"] = total_items_failed
            stats["avg_duration_seconds"] = avg_duration

        return stats


# Global instance for easy access
_store: SyncStore | None = None


async def get_sync_store() -> SyncStore:
    """Get the global SyncStore instance, initializing if needed."""
    global _store
    if _store is None:
        _store = SyncStore()
        await _store.initialize()
    return _store


__all__ = [
    "SyncStore",
    "SyncJob",
    "ConnectorConfig",
    "get_sync_store",
]
