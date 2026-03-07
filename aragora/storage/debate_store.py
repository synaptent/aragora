"""SQLite-backed store for persisting playground debate results.

Enables shareable debate links by saving results with a unique ID
and supporting retrieval via GET /api/v1/playground/debate/{id}.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

from aragora.storage.base_store import SQLiteStore

logger = logging.getLogger(__name__)

_DEFAULT_TTL_DAYS = 30


def normalize_cache_key(topic: str, model_ids: list[str], rounds: int) -> str:
    """Compute a content-addressed cache key for a debate configuration."""
    normalized_topic = re.sub(r"\s+", " ", topic.strip().lower())
    sorted_models = "|".join(sorted(model_ids))
    raw = f"{normalized_topic}|{sorted_models}|{rounds}"
    return hashlib.sha256(raw.encode()).hexdigest()


class DebateResultStore(SQLiteStore):
    """Persist playground debate results for shareable links."""

    SCHEMA_NAME = "debate_results"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS debate_results (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            result_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'playground',
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_debate_results_created
            ON debate_results(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_debate_results_expires
            ON debate_results(expires_at);
        CREATE TABLE IF NOT EXISTS debate_cache_index (
            cache_key TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL,
            topic_normalized TEXT NOT NULL,
            model_ids TEXT NOT NULL,
            rounds INTEGER NOT NULL,
            created_at REAL NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_cache_created
            ON debate_cache_index(created_at);
    """

    def save(
        self,
        debate_id: str,
        topic: str,
        result: dict[str, Any],
        *,
        source: str = "playground",
        ttl_days: int = _DEFAULT_TTL_DAYS,
    ) -> None:
        """Save a debate result."""
        now = time.time()
        expires_at = now + (ttl_days * 86400)
        result_json = json.dumps(result, default=str)

        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO debate_results
                    (id, topic, result_json, source, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (debate_id, topic, result_json, source, now, expires_at),
            )

    def get(self, debate_id: str) -> dict[str, Any] | None:
        """Retrieve a debate result by ID, returning None if expired or missing."""
        now = time.time()
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT result_json FROM debate_results
                WHERE id = ? AND expires_at > ?
                """,
                (debate_id, now),
            ).fetchone()

        if row is None:
            return None

        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt debate result for %s", debate_id)
            return None

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent debate metadata (not full results)."""
        now = time.time()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, topic, source, created_at FROM debate_results
                WHERE expires_at > ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()

        return [
            {
                "id": r[0],
                "topic": r[1],
                "source": r[2],
                "created_at": r[3],
            }
            for r in rows
        ]

    def save_cache_index(
        self,
        cache_key: str,
        debate_id: str,
        topic_normalized: str,
        model_ids: str,
        rounds: int,
    ) -> None:
        """Save a cache index entry mapping a content hash to a debate ID."""
        now = time.time()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO debate_cache_index
                    (cache_key, debate_id, topic_normalized, model_ids, rounds, created_at, hit_count)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (cache_key, debate_id, topic_normalized, model_ids, rounds, now),
            )

    def get_by_cache_key(self, cache_key: str) -> dict[str, Any] | None:
        """Look up a cached debate result by content-addressed key.

        Returns the debate result dict if the cache entry exists and the
        underlying debate has not expired.  On a cache miss (no index row
        or expired debate), returns None and cleans up any orphaned index row.
        On a hit, increments hit_count.
        """
        with self.connection() as conn:
            row = conn.execute(
                "SELECT debate_id FROM debate_cache_index WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()

        if row is None:
            return None

        debate_id = row[0]
        result = self.get(debate_id)

        if result is None:
            # Underlying debate expired or missing — clean up orphaned index row
            with self.connection() as conn:
                conn.execute(
                    "DELETE FROM debate_cache_index WHERE cache_key = ?",
                    (cache_key,),
                )
            return None

        # Cache hit — increment counter
        with self.connection() as conn:
            conn.execute(
                "UPDATE debate_cache_index SET hit_count = hit_count + 1 WHERE cache_key = ?",
                (cache_key,),
            )

        return result

    def cleanup_expired(self) -> int:
        """Delete expired entries. Returns count of deleted rows."""
        now = time.time()
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM debate_results WHERE expires_at <= ?",
                (now,),
            )
            return cursor.rowcount


# Module-level singleton
_store: DebateResultStore | None = None


def get_debate_store() -> DebateResultStore:
    """Get or create the singleton DebateResultStore."""
    global _store  # noqa: PLW0603
    if _store is None:
        _store = DebateResultStore("debate_results.db")
    return _store
