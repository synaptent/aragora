"""
Database-backed Share Link Storage.

Provides persistent storage for debate sharing settings with:
- TTL-based expiration and cleanup
- Thread-safe concurrent access
- View count tracking
- Token-based lookups

Supports SQLite (default) and PostgreSQL backends.
Replaces the in-memory ShareStore for production use.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path

from aragora.storage.backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
)
from aragora.storage.base_store import SQLiteStore
from aragora.storage.connection_factory import is_postgres_backend
from aragora.storage.share_models import DebateVisibility, ShareSettings

logger = logging.getLogger(__name__)


class ShareLinkStore(SQLiteStore):
    """
    Database-backed store for debate sharing settings.

    Supports SQLite (default) and PostgreSQL backends.
    Provides persistent storage with automatic TTL cleanup,
    replacing the in-memory ShareStore for production deployments.

    Features:
    - Atomic save/update operations
    - Token-based lookups for public access
    - Automatic expired link cleanup
    - View count tracking

    Usage:
        store = ShareLinkStore("share_links.db")  # stored under ARAGORA_DATA_DIR
        store.save(settings)
        settings = store.get_by_token("abc123")
    """

    SCHEMA_NAME = "share_links"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS share_links (
            token TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL UNIQUE,
            visibility TEXT NOT NULL DEFAULT 'private',
            owner_id TEXT,
            org_id TEXT,
            created_at REAL NOT NULL,
            expires_at REAL,
            allow_comments INTEGER DEFAULT 0,
            allow_forking INTEGER DEFAULT 0,
            view_count INTEGER DEFAULT 0,
            last_viewed_at REAL
        );

        CREATE INDEX IF NOT EXISTS idx_share_links_debate
        ON share_links(debate_id);

        CREATE INDEX IF NOT EXISTS idx_share_links_expires
        ON share_links(expires_at)
        WHERE expires_at IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_share_links_owner
        ON share_links(owner_id);

        CREATE INDEX IF NOT EXISTS idx_share_links_org
        ON share_links(org_id, visibility);
    """

    def __init__(
        self,
        db_path: str | Path = "share_links.db",
        cleanup_interval: int = 300,
        backend: str | None = None,
        database_url: str | None = None,
        **kwargs,
    ):
        """
        Initialize the share link store.

        Args:
            db_path: Path to SQLite database file (used when backend="sqlite")
            cleanup_interval: Seconds between automatic TTL cleanups (default: 5 min)
            backend: Database backend ("sqlite" or "postgresql")
            database_url: PostgreSQL connection URL
        """
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()

        # Determine backend type
        env_url = os.environ.get("DATABASE_URL") or os.environ.get("ARAGORA_DATABASE_URL")
        actual_url = database_url or env_url

        if backend is None:
            env_backend = os.environ.get("ARAGORA_DB_BACKEND", "sqlite").lower()
            backend = (
                "postgresql" if (actual_url and is_postgres_backend(env_backend)) else "sqlite"
            )

        self.backend_type = backend
        self._backend: DatabaseBackend | None = None

        if backend == "postgresql":
            if not actual_url:
                raise ValueError("PostgreSQL backend requires DATABASE_URL")
            if not POSTGRESQL_AVAILABLE:
                raise ImportError("psycopg2 required for PostgreSQL")
            self._backend = PostgreSQLBackend(actual_url)
            self._init_postgresql_schema()
            logger.info("ShareLinkStore using PostgreSQL backend")
        else:
            # Use SQLiteStore initialization for SQLite
            super().__init__(db_path, **kwargs)
            logger.info("ShareLinkStore initialized: %s", db_path)

    def _init_postgresql_schema(self) -> None:
        """Initialize PostgreSQL schema."""
        if self._backend is None:
            return

        # Create table
        self._backend.execute_write("""
            CREATE TABLE IF NOT EXISTS share_links (
                token TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL UNIQUE,
                visibility TEXT NOT NULL DEFAULT 'private',
                owner_id TEXT,
                org_id TEXT,
                created_at REAL NOT NULL,
                expires_at REAL,
                allow_comments INTEGER DEFAULT 0,
                allow_forking INTEGER DEFAULT 0,
                view_count INTEGER DEFAULT 0,
                last_viewed_at REAL
            )
        """)

        # Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_share_links_debate ON share_links(debate_id)",
            "CREATE INDEX IF NOT EXISTS idx_share_links_owner ON share_links(owner_id)",
            "CREATE INDEX IF NOT EXISTS idx_share_links_org ON share_links(org_id, visibility)",
        ]
        for idx_sql in indexes:
            try:
                self._backend.execute_write(idx_sql)
            except (OSError, RuntimeError, ValueError) as e:
                logger.debug("Index creation skipped: %s", e)

        # Run post-init cleanup
        self._post_init()

    def _post_init(self) -> None:
        """Run cleanup on startup."""
        self.cleanup_expired()

    def save(self, settings: ShareSettings) -> None:
        """
        Save or update sharing settings.

        Uses UPSERT semantics - creates new record or updates existing
        based on debate_id uniqueness constraint.

        Args:
            settings: ShareSettings object to persist
        """
        # Generate token if needed and not already set
        token = settings.share_token
        if token is None:
            token = self._generate_token()

        params = (
            token,
            settings.debate_id,
            (
                settings.visibility.value
                if hasattr(settings.visibility, "value")
                else settings.visibility
            ),
            settings.owner_id,
            settings.org_id,
            settings.created_at,
            settings.expires_at,
            int(settings.allow_comments),
            int(settings.allow_forking),
            settings.view_count,
            None,
        )

        if self._backend is not None:
            self._backend.execute_write(
                """
                INSERT INTO share_links (
                    token, debate_id, visibility, owner_id, org_id,
                    created_at, expires_at, allow_comments, allow_forking,
                    view_count, last_viewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(debate_id) DO UPDATE SET
                    token = COALESCE(EXCLUDED.token, share_links.token),
                    visibility = EXCLUDED.visibility,
                    owner_id = COALESCE(EXCLUDED.owner_id, share_links.owner_id),
                    org_id = COALESCE(EXCLUDED.org_id, share_links.org_id),
                    expires_at = EXCLUDED.expires_at,
                    allow_comments = EXCLUDED.allow_comments,
                    allow_forking = EXCLUDED.allow_forking
                """,
                params,
            )
        else:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO share_links (
                        token, debate_id, visibility, owner_id, org_id,
                        created_at, expires_at, allow_comments, allow_forking,
                        view_count, last_viewed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(debate_id) DO UPDATE SET
                        token = COALESCE(excluded.token, token),
                        visibility = excluded.visibility,
                        owner_id = COALESCE(excluded.owner_id, owner_id),
                        org_id = COALESCE(excluded.org_id, org_id),
                        expires_at = excluded.expires_at,
                        allow_comments = excluded.allow_comments,
                        allow_forking = excluded.allow_forking
                    """,
                    params,
                )

        self._maybe_cleanup()
        logger.debug("Saved share settings for debate %s", settings.debate_id)

    def get(self, debate_id: str) -> ShareSettings | None:
        """
        Get sharing settings by debate ID.

        Args:
            debate_id: The debate identifier

        Returns:
            ShareSettings if found and not expired, None otherwise
        """
        query = """
            SELECT token, debate_id, visibility, owner_id, org_id,
                   created_at, expires_at, allow_comments, allow_forking,
                   view_count, last_viewed_at
            FROM share_links
            WHERE debate_id = ?
        """

        if self._backend is not None:
            row = self._backend.fetch_one(query, (debate_id,))
        else:
            row = self.fetch_one(query, (debate_id,))

        if not row:
            return None

        return self._row_to_settings(row)

    def get_by_token(self, token: str) -> ShareSettings | None:
        """
        Get sharing settings by share token.

        Args:
            token: The share token

        Returns:
            ShareSettings if found and not expired, None otherwise
        """
        query = """
            SELECT token, debate_id, visibility, owner_id, org_id,
                   created_at, expires_at, allow_comments, allow_forking,
                   view_count, last_viewed_at
            FROM share_links
            WHERE token = ?
        """

        if self._backend is not None:
            row = self._backend.fetch_one(query, (token,))
        else:
            row = self.fetch_one(query, (token,))

        if not row:
            return None

        return self._row_to_settings(row)

    def delete(self, debate_id: str) -> bool:
        """
        Delete sharing settings for a debate.

        Args:
            debate_id: The debate identifier

        Returns:
            True if a record was deleted
        """
        if self._backend is not None:
            row = self._backend.fetch_one(
                "SELECT 1 FROM share_links WHERE debate_id = ?",
                (debate_id,),
            )
            if not row:
                return False
            self._backend.execute_write(
                "DELETE FROM share_links WHERE debate_id = ?",
                (debate_id,),
            )
            logger.info("Deleted share settings for debate %s", debate_id)
            return True

        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM share_links WHERE debate_id = ?",
                (debate_id,),
            )
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("Deleted share settings for debate %s", debate_id)

        return deleted

    def revoke_token(self, debate_id: str) -> bool:
        """
        Revoke (nullify) the share token for a debate.

        The record remains but the token is cleared, invalidating
        any existing share links.

        Args:
            debate_id: The debate identifier

        Returns:
            True if a token was revoked
        """
        if self._backend is not None:
            row = self._backend.fetch_one(
                "SELECT 1 FROM share_links WHERE debate_id = ? AND token IS NOT NULL",
                (debate_id,),
            )
            if not row:
                return False
            self._backend.execute_write(
                """
                UPDATE share_links
                SET token = NULL
                WHERE debate_id = ? AND token IS NOT NULL
                """,
                (debate_id,),
            )
            logger.info("Revoked share token for debate %s", debate_id)
            return True

        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE share_links
                SET token = NULL
                WHERE debate_id = ? AND token IS NOT NULL
                """,
                (debate_id,),
            )
            revoked = cursor.rowcount > 0

        if revoked:
            logger.info("Revoked share token for debate %s", debate_id)

        return revoked

    def increment_view_count(self, debate_id: str) -> None:
        """
        Atomically increment the view count for a shared debate.

        Also updates last_viewed_at timestamp.

        Args:
            debate_id: The debate identifier
        """
        params = (time.time(), debate_id)

        if self._backend is not None:
            self._backend.execute_write(
                """
                UPDATE share_links
                SET view_count = view_count + 1,
                    last_viewed_at = ?
                WHERE debate_id = ?
                """,
                params,
            )
        else:
            with self.connection() as conn:
                conn.execute(
                    """
                    UPDATE share_links
                    SET view_count = view_count + 1,
                        last_viewed_at = ?
                    WHERE debate_id = ?
                    """,
                    params,
                )

    def cleanup_expired(self) -> int:
        """
        Remove expired share links from the database.

        Returns:
            Number of expired records deleted
        """
        cutoff = time.time()

        if self._backend is not None:
            row = self._backend.fetch_one(
                """
                SELECT COUNT(*) FROM share_links
                WHERE expires_at IS NOT NULL AND expires_at < ?
                """,
                (cutoff,),
            )
            removed = row[0] if row else 0
            if removed > 0:
                self._backend.execute_write(
                    """
                    DELETE FROM share_links
                    WHERE expires_at IS NOT NULL AND expires_at < ?
                    """,
                    (cutoff,),
                )
        else:
            with self.connection() as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM share_links
                    WHERE expires_at IS NOT NULL AND expires_at < ?
                    """,
                    (cutoff,),
                )
                removed = cursor.rowcount

        self._last_cleanup = time.time()

        if removed > 0:
            logger.info("ShareLinkStore cleanup: removed %s expired links", removed)

        return removed

    def _maybe_cleanup(self) -> None:
        """Run cleanup if cleanup_interval has passed."""
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            self.cleanup_expired()

    def _generate_token(self) -> str:
        """Generate a secure share token."""
        return secrets.token_urlsafe(16)

    def _row_to_settings(self, row: tuple) -> ShareSettings:
        """Convert a database row to ShareSettings object."""
        return ShareSettings(
            debate_id=row[1],
            visibility=DebateVisibility(row[2]),
            share_token=row[0],
            owner_id=row[3],
            org_id=row[4],
            created_at=row[5],
            expires_at=row[6],
            allow_comments=bool(row[7]),
            allow_forking=bool(row[8]),
            view_count=row[9] or 0,
        )

    def get_stats(self) -> dict:
        """
        Get statistics about share links.

        Returns:
            Dict with counts by visibility, expired count, etc.
        """
        stats = {}

        if self._backend is not None:
            # Total count
            row = self._backend.fetch_one("SELECT COUNT(*) FROM share_links")
            stats["total"] = row[0] if row else 0

            # By visibility
            rows = self._backend.fetch_all(
                "SELECT visibility, COUNT(*) FROM share_links GROUP BY visibility"
            )
            stats["by_visibility"] = {r[0]: r[1] for r in rows}

            # With active tokens
            row = self._backend.fetch_one(
                "SELECT COUNT(*) FROM share_links WHERE token IS NOT NULL"
            )
            stats["with_tokens"] = row[0] if row else 0

            # Expired (but not yet cleaned up)
            row = self._backend.fetch_one(
                """
                SELECT COUNT(*) FROM share_links
                WHERE expires_at IS NOT NULL AND expires_at < ?
                """,
                (time.time(),),
            )
            stats["expired"] = row[0] if row else 0

            # Total views
            row = self._backend.fetch_one("SELECT SUM(view_count) FROM share_links")
            stats["total_views"] = row[0] or 0 if row else 0
        else:
            # Total count
            row = self.fetch_one("SELECT COUNT(*) FROM share_links")
            stats["total"] = row[0] if row else 0

            # By visibility
            rows = self.fetch_all(
                "SELECT visibility, COUNT(*) FROM share_links GROUP BY visibility"
            )
            stats["by_visibility"] = {row[0]: row[1] for row in rows}

            # With active tokens
            row = self.fetch_one("SELECT COUNT(*) FROM share_links WHERE token IS NOT NULL")
            stats["with_tokens"] = row[0] if row else 0

            # Expired (but not yet cleaned up)
            row = self.fetch_one(
                """
                SELECT COUNT(*) FROM share_links
                WHERE expires_at IS NOT NULL AND expires_at < ?
                """,
                (time.time(),),
            )
            stats["expired"] = row[0] if row else 0

            # Total views
            row = self.fetch_one("SELECT SUM(view_count) FROM share_links")
            stats["total_views"] = row[0] or 0 if row else 0

        return stats

    def close(self) -> None:
        """Close database connection."""
        if self._backend is not None:
            self._backend.close()
            self._backend = None


__all__ = ["ShareLinkStore"]
