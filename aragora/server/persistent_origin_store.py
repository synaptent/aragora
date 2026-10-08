"""
Persistent Origin Store for Bidirectional Routing.

Provides durable storage for debate origins and email reply routing with:
- PostgreSQL backend (primary) for production
- SQLite fallback for development
- In-memory LRU cache for performance
- TTL-based automatic cleanup

This store survives server restarts and supports multi-instance deployments.

Usage:
    from aragora.server.persistent_origin_store import get_origin_store

    store = await get_origin_store()

    # Register a debate origin
    await store.register_origin(
        origin_id="debate-abc123",
        origin_type="debate",
        platform="slack",
        channel_id="C1234567",
        user_id="U1234567",
        metadata={"thread_ts": "1234567890.123456"},
    )

    # Retrieve origin
    origin = await store.get_origin("debate-abc123")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# TTL for origin records (default 24 hours)
DEFAULT_TTL_SECONDS = int(os.environ.get("ARAGORA_ORIGIN_TTL", 86400))

# Maximum LRU cache size
MAX_CACHE_SIZE = int(os.environ.get("ARAGORA_ORIGIN_CACHE_SIZE", 10000))


@dataclass
class OriginRecord:
    """A routing origin record."""

    origin_id: str
    origin_type: str  # 'debate', 'email_reply', 'chat_thread'
    platform: str  # 'slack', 'teams', 'discord', 'telegram', 'whatsapp', 'email', 'gchat'
    channel_id: str
    user_id: str
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    thread_id: str | None = None
    message_id: str | None = None
    result_sent: bool = False
    result_sent_at: float | None = None

    def __post_init__(self):
        if self.expires_at is None:
            self.expires_at = self.created_at + DEFAULT_TTL_SECONDS

    def is_expired(self) -> bool:
        """Check if this origin has expired."""
        return self.expires_at is not None and time.time() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin_id": self.origin_id,
            "origin_type": self.origin_type,
            "platform": self.platform,
            "channel_id": self.channel_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
            "thread_id": self.thread_id,
            "message_id": self.message_id,
            "result_sent": self.result_sent,
            "result_sent_at": self.result_sent_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OriginRecord:
        return cls(
            origin_id=data["origin_id"],
            origin_type=data["origin_type"],
            platform=data["platform"],
            channel_id=data["channel_id"],
            user_id=data["user_id"],
            created_at=data.get("created_at", time.time()),
            expires_at=data.get("expires_at"),
            metadata=data.get("metadata", {}),
            thread_id=data.get("thread_id"),
            message_id=data.get("message_id"),
            result_sent=data.get("result_sent", False),
            result_sent_at=data.get("result_sent_at"),
        )


class PersistentOriginStore:
    """
    Persistent origin store with PostgreSQL primary and SQLite fallback.

    Uses a two-tier architecture:
    1. In-memory LRU cache for fast reads
    2. PostgreSQL or SQLite for durability
    """

    def __init__(
        self,
        database_url: str | None = None,
        cache_size: int = MAX_CACHE_SIZE,
    ):
        """
        Initialize the persistent origin store.

        Args:
            database_url: Database connection URL. If not provided, auto-detects:
                - Uses ARAGORA_ROUTING_DATABASE_URL if set
                - Falls back to ARAGORA_DATABASE_URL for PostgreSQL
                - Falls back to SQLite file in ARAGORA_DATA_DIR
            cache_size: Maximum number of origins to cache in memory
        """
        self._database_url = database_url
        self._cache_size = cache_size
        self._initialized = False
        self._pool: Any | None = None  # asyncpg.Pool when using PostgreSQL
        self._sqlite_path: str | None = None
        self._use_postgres = False

        # In-memory LRU cache: origin_id -> OriginRecord
        self._cache: dict[str, OriginRecord] = {}
        self._cache_order: list[str] = []  # For LRU eviction

    def _require_pool(self) -> Any:
        """Return the initialized PostgreSQL pool."""
        pool = self._pool
        if pool is None:
            raise RuntimeError("PostgreSQL pool is not initialized")
        return pool

    def _require_sqlite_path(self) -> str:
        """Return the initialized SQLite database path."""
        path = self._sqlite_path
        if path is None:
            raise RuntimeError("SQLite path is not initialized")
        return path

    async def initialize(self) -> None:
        """Initialize database connection and schema."""
        if self._initialized:
            return

        # Determine database URL
        url = self._database_url or os.environ.get("ARAGORA_ROUTING_DATABASE_URL")
        if not url:
            url = os.environ.get("ARAGORA_DATABASE_URL", "")

        # Try PostgreSQL first
        if url.startswith("postgresql://") or url.startswith("postgres://"):
            if await self._init_postgres(url):
                self._use_postgres = True
                self._initialized = True
                logger.info("PersistentOriginStore initialized with PostgreSQL")
                return

        # Fall back to SQLite
        await self._init_sqlite()
        self._initialized = True
        logger.info("PersistentOriginStore initialized with SQLite")

    async def _init_postgres(self, url: str) -> bool:
        """Initialize PostgreSQL connection pool and schema."""
        try:
            import asyncpg
        except ImportError:
            logger.debug("asyncpg not installed, falling back to SQLite")
            return False

        try:
            self._pool = await asyncpg.create_pool(
                url,
                min_size=2,
                max_size=10,
                command_timeout=60,
            )

            # Create schema
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS routing_origins (
                        origin_id TEXT PRIMARY KEY,
                        origin_type TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        channel_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        expires_at TIMESTAMPTZ,
                        metadata_json JSONB,
                        thread_id TEXT,
                        message_id TEXT,
                        result_sent BOOLEAN DEFAULT FALSE,
                        result_sent_at TIMESTAMPTZ
                    )
                """)

                # Create indexes for efficient lookups
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_origins_expires
                        ON routing_origins(expires_at)
                        WHERE expires_at IS NOT NULL
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_origins_platform_channel
                        ON routing_origins(platform, channel_id)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_origins_type
                        ON routing_origins(origin_type)
                """)

            return True

        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.warning("PostgreSQL initialization failed: %s", e)
            if self._pool:
                await self._pool.close()
                self._pool = None
            return False

    async def _init_sqlite(self) -> None:
        """Initialize SQLite database."""
        # Only set path if not already set (allows test injection)
        if self._sqlite_path is None:
            from aragora.persistence.db_config import get_nomic_dir

            self._sqlite_path = str(get_nomic_dir() / "routing_origins.db")
        Path(self._sqlite_path).parent.mkdir(parents=True, exist_ok=True)

        # SQLite is synchronous, run in thread pool
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._create_sqlite_schema)

    def _create_sqlite_schema(self) -> None:
        """Create SQLite schema (synchronous)."""
        with sqlite3.connect(self._require_sqlite_path()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS routing_origins (
                    origin_id TEXT PRIMARY KEY,
                    origin_type TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    metadata_json TEXT,
                    thread_id TEXT,
                    message_id TEXT,
                    result_sent INTEGER DEFAULT 0,
                    result_sent_at REAL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_origins_expires ON routing_origins(expires_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_origins_platform_channel ON routing_origins(platform, channel_id)"
            )
            conn.commit()

    async def close(self) -> None:
        """Close database connections."""
        if self._pool:
            await self._pool.close()
            self._pool = None
        self._initialized = False
        self._cache.clear()
        self._cache_order.clear()

    # ==================== Core Operations ====================

    async def register_origin(
        self,
        origin_id: str,
        origin_type: str,
        platform: str,
        channel_id: str,
        user_id: str,
        thread_id: str | None = None,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> OriginRecord:
        """
        Register a new routing origin.

        Args:
            origin_id: Unique identifier for the origin
            origin_type: Type of origin ('debate', 'email_reply', 'chat_thread')
            platform: Platform name
            channel_id: Channel/chat ID on the platform
            user_id: User who initiated
            thread_id: Optional thread ID
            message_id: Optional message ID
            metadata: Optional additional metadata
            ttl_seconds: Optional custom TTL (default: 24 hours)

        Returns:
            OriginRecord instance
        """
        if not self._initialized:
            await self.initialize()

        now = time.time()
        expires_at = now + (ttl_seconds or DEFAULT_TTL_SECONDS)

        origin = OriginRecord(
            origin_id=origin_id,
            origin_type=origin_type,
            platform=platform,
            channel_id=channel_id,
            user_id=user_id,
            created_at=now,
            expires_at=expires_at,
            metadata=metadata or {},
            thread_id=thread_id,
            message_id=message_id,
        )

        # Save to persistent store
        if self._use_postgres:
            await self._save_postgres(origin)
        else:
            await self._save_sqlite(origin)

        # Update cache
        self._cache_put(origin)

        logger.debug("Registered origin %s (%s) from %s", origin_id, origin_type, platform)
        return origin

    async def get_origin(self, origin_id: str) -> OriginRecord | None:
        """
        Get an origin by ID.

        Checks cache first, then persistent store.
        """
        if not self._initialized:
            await self.initialize()

        # Check cache first
        if origin_id in self._cache:
            origin = self._cache[origin_id]
            if not origin.is_expired():
                self._cache_touch(origin_id)
                return origin
            else:
                # Expired in cache, remove it
                self._cache_remove(origin_id)

        # Load from persistent store
        if self._use_postgres:
            loaded_origin = await self._load_postgres(origin_id)
        else:
            loaded_origin = await self._load_sqlite(origin_id)

        if loaded_origin and not loaded_origin.is_expired():
            self._cache_put(loaded_origin)
            return loaded_origin

        return None

    async def mark_result_sent(
        self,
        origin_id: str,
        result_data: dict[str, Any] | None = None,
    ) -> bool:
        """
        Mark that the result has been sent for an origin.

        Args:
            origin_id: Origin identifier
            result_data: Optional result data to store in metadata

        Returns:
            True if origin was found and updated
        """
        if not self._initialized:
            await self.initialize()

        origin = await self.get_origin(origin_id)
        if not origin:
            return False

        origin.result_sent = True
        origin.result_sent_at = time.time()
        if result_data:
            origin.metadata["result"] = result_data

        # Update persistent store
        if self._use_postgres:
            await self._save_postgres(origin)
        else:
            await self._save_sqlite(origin)

        # Update cache
        self._cache_put(origin)

        return True

    async def list_pending(
        self,
        origin_type: str | None = None,
        platform: str | None = None,
        limit: int = 100,
    ) -> list[OriginRecord]:
        """
        List origins that haven't had results sent yet.

        Args:
            origin_type: Filter by origin type
            platform: Filter by platform
            limit: Maximum results to return

        Returns:
            List of pending OriginRecord instances
        """
        if not self._initialized:
            await self.initialize()

        if self._use_postgres:
            return await self._list_pending_postgres(origin_type, platform, limit)
        else:
            return await self._list_pending_sqlite(origin_type, platform, limit)

    async def cleanup_expired(self) -> int:
        """
        Remove expired origin records.

        Returns:
            Number of records removed
        """
        if not self._initialized:
            await self.initialize()

        # Clean cache
        expired_cache = [k for k, v in self._cache.items() if v.is_expired()]
        for k in expired_cache:
            self._cache_remove(k)

        # Clean persistent store
        if self._use_postgres:
            count = await self._cleanup_postgres()
        else:
            count = await self._cleanup_sqlite()

        if count > 0:
            logger.info("Cleaned up %s expired routing origins", count)

        return count

    # ==================== PostgreSQL Operations ====================

    async def _save_postgres(self, origin: OriginRecord) -> None:
        """Save origin to PostgreSQL."""
        async with self._require_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO routing_origins
                    (origin_id, origin_type, platform, channel_id, user_id,
                     created_at, expires_at, metadata_json, thread_id, message_id,
                     result_sent, result_sent_at)
                VALUES ($1, $2, $3, $4, $5,
                        to_timestamp($6), to_timestamp($7), $8, $9, $10,
                        $11, to_timestamp($12))
                ON CONFLICT (origin_id) DO UPDATE SET
                    result_sent = EXCLUDED.result_sent,
                    result_sent_at = EXCLUDED.result_sent_at,
                    metadata_json = EXCLUDED.metadata_json
                """,
                origin.origin_id,
                origin.origin_type,
                origin.platform,
                origin.channel_id,
                origin.user_id,
                origin.created_at,
                origin.expires_at,
                json.dumps(origin.metadata),
                origin.thread_id,
                origin.message_id,
                origin.result_sent,
                origin.result_sent_at,
            )

    async def _load_postgres(self, origin_id: str) -> OriginRecord | None:
        """Load origin from PostgreSQL."""
        async with self._require_pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT origin_id, origin_type, platform, channel_id, user_id,
                       EXTRACT(EPOCH FROM created_at), EXTRACT(EPOCH FROM expires_at),
                       metadata_json, thread_id, message_id,
                       result_sent, EXTRACT(EPOCH FROM result_sent_at)
                FROM routing_origins
                WHERE origin_id = $1
                """,
                origin_id,
            )

            if row:
                return OriginRecord(
                    origin_id=row[0],
                    origin_type=row[1],
                    platform=row[2],
                    channel_id=row[3],
                    user_id=row[4],
                    created_at=row[5],
                    expires_at=row[6],
                    metadata=json.loads(row[7]) if row[7] else {},
                    thread_id=row[8],
                    message_id=row[9],
                    result_sent=row[10],
                    result_sent_at=row[11],
                )

        return None

    async def _list_pending_postgres(
        self, origin_type: str | None, platform: str | None, limit: int
    ) -> list[OriginRecord]:
        """List pending origins from PostgreSQL."""
        conditions = ["result_sent = FALSE", "expires_at > NOW()"]
        params: list[str | int] = []

        if origin_type:
            params.append(origin_type)
            conditions.append(f"origin_type = ${len(params)}")
        if platform:
            params.append(platform)
            conditions.append(f"platform = ${len(params)}")

        params.append(limit)

        query = f"""
            SELECT origin_id, origin_type, platform, channel_id, user_id,
                   EXTRACT(EPOCH FROM created_at), EXTRACT(EPOCH FROM expires_at),
                   metadata_json, thread_id, message_id,
                   result_sent, EXTRACT(EPOCH FROM result_sent_at)
            FROM routing_origins
            WHERE {" AND ".join(conditions)}
            ORDER BY created_at DESC
            LIMIT ${len(params)}
        """  # noqa: S608 -- dynamic clause from internal state

        results = []
        async with self._require_pool().acquire() as conn:
            rows = await conn.fetch(query, *params)
            for row in rows:
                results.append(
                    OriginRecord(
                        origin_id=row[0],
                        origin_type=row[1],
                        platform=row[2],
                        channel_id=row[3],
                        user_id=row[4],
                        created_at=row[5],
                        expires_at=row[6],
                        metadata=json.loads(row[7]) if row[7] else {},
                        thread_id=row[8],
                        message_id=row[9],
                        result_sent=row[10],
                        result_sent_at=row[11],
                    )
                )

        return results

    async def _cleanup_postgres(self) -> int:
        """Remove expired records from PostgreSQL."""
        async with self._require_pool().acquire() as conn:
            result = await conn.execute("DELETE FROM routing_origins WHERE expires_at < NOW()")
            # Parse "DELETE N" result
            count = int(result.split()[-1]) if result else 0
            return count

    # ==================== SQLite Operations ====================

    async def _save_sqlite(self, origin: OriginRecord) -> None:
        """Save origin to SQLite."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._save_sqlite_sync, origin)

    def _save_sqlite_sync(self, origin: OriginRecord) -> None:
        """Synchronous SQLite save."""
        with sqlite3.connect(self._require_sqlite_path()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO routing_origins
                    (origin_id, origin_type, platform, channel_id, user_id,
                     created_at, expires_at, metadata_json, thread_id, message_id,
                     result_sent, result_sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    origin.origin_id,
                    origin.origin_type,
                    origin.platform,
                    origin.channel_id,
                    origin.user_id,
                    origin.created_at,
                    origin.expires_at,
                    json.dumps(origin.metadata),
                    origin.thread_id,
                    origin.message_id,
                    1 if origin.result_sent else 0,
                    origin.result_sent_at,
                ),
            )
            conn.commit()

    async def _load_sqlite(self, origin_id: str) -> OriginRecord | None:
        """Load origin from SQLite."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._load_sqlite_sync, origin_id)

    def _load_sqlite_sync(self, origin_id: str) -> OriginRecord | None:
        """Synchronous SQLite load."""
        with sqlite3.connect(self._require_sqlite_path()) as conn:
            cursor = conn.execute("SELECT * FROM routing_origins WHERE origin_id = ?", (origin_id,))
            row = cursor.fetchone()

        if row:
            return OriginRecord(
                origin_id=row[0],
                origin_type=row[1],
                platform=row[2],
                channel_id=row[3],
                user_id=row[4],
                created_at=row[5],
                expires_at=row[6],
                metadata=json.loads(row[7]) if row[7] else {},
                thread_id=row[8],
                message_id=row[9],
                result_sent=bool(row[10]),
                result_sent_at=row[11],
            )

        return None

    async def _list_pending_sqlite(
        self, origin_type: str | None, platform: str | None, limit: int
    ) -> list[OriginRecord]:
        """List pending origins from SQLite."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._list_pending_sqlite_sync, origin_type, platform, limit
        )

    def _list_pending_sqlite_sync(
        self, origin_type: str | None, platform: str | None, limit: int
    ) -> list[OriginRecord]:
        """Synchronous SQLite list pending."""
        conditions = ["result_sent = 0", "expires_at > ?"]
        params: list[Any] = [time.time()]

        if origin_type:
            conditions.append("origin_type = ?")
            params.append(origin_type)
        if platform:
            conditions.append("platform = ?")
            params.append(platform)

        params.append(limit)

        query = f"""
            SELECT * FROM routing_origins
            WHERE {" AND ".join(conditions)}
            ORDER BY created_at DESC
            LIMIT ?
        """  # noqa: S608 -- dynamic clause from internal state

        with sqlite3.connect(self._require_sqlite_path()) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        results = []
        for row in rows:
            results.append(
                OriginRecord(
                    origin_id=row[0],
                    origin_type=row[1],
                    platform=row[2],
                    channel_id=row[3],
                    user_id=row[4],
                    created_at=row[5],
                    expires_at=row[6],
                    metadata=json.loads(row[7]) if row[7] else {},
                    thread_id=row[8],
                    message_id=row[9],
                    result_sent=bool(row[10]),
                    result_sent_at=row[11],
                )
            )

        return results

    async def _cleanup_sqlite(self) -> int:
        """Remove expired records from SQLite."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._cleanup_sqlite_sync)

    def _cleanup_sqlite_sync(self) -> int:
        """Synchronous SQLite cleanup."""
        with sqlite3.connect(self._require_sqlite_path()) as conn:
            cursor = conn.execute(
                "DELETE FROM routing_origins WHERE expires_at < ?", (time.time(),)
            )
            count = cursor.rowcount
            conn.commit()
        return count

    # ==================== Cache Operations ====================

    def _cache_put(self, origin: OriginRecord) -> None:
        """Add or update an origin in the cache."""
        origin_id = origin.origin_id

        # Remove if exists (for LRU ordering)
        if origin_id in self._cache:
            self._cache_order.remove(origin_id)

        # Add to cache
        self._cache[origin_id] = origin
        self._cache_order.append(origin_id)

        # Evict if over size limit
        while len(self._cache) > self._cache_size:
            oldest = self._cache_order.pop(0)
            del self._cache[oldest]

    def _cache_touch(self, origin_id: str) -> None:
        """Move an origin to the end of the LRU list."""
        if origin_id in self._cache_order:
            self._cache_order.remove(origin_id)
            self._cache_order.append(origin_id)

    def _cache_remove(self, origin_id: str) -> None:
        """Remove an origin from the cache."""
        if origin_id in self._cache:
            del self._cache[origin_id]
        if origin_id in self._cache_order:
            self._cache_order.remove(origin_id)


# Global singleton
_store: PersistentOriginStore | None = None
_store_lock = asyncio.Lock()


async def get_origin_store() -> PersistentOriginStore:
    """Get the global PersistentOriginStore instance."""
    global _store
    if _store is None:
        async with _store_lock:
            if _store is None:
                _store = PersistentOriginStore()
                await _store.initialize()
    return _store


def reset_origin_store() -> None:
    """Reset the global origin store (for testing)."""
    global _store
    _store = None


__all__ = [
    "PersistentOriginStore",
    "OriginRecord",
    "get_origin_store",
    "reset_origin_store",
]
