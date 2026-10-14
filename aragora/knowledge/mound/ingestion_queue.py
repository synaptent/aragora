"""Dead letter queue for failed Knowledge Mound ingestions.

Provides SQLite-backed storage for debate outcomes that failed to ingest
into the Knowledge Mound, allowing retry at startup or on demand.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class IngestionDeadLetterQueue:
    """SQLite-backed dead letter queue for failed KM ingestions."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from aragora.persistence.db_config import get_default_data_dir

            data_dir = Path(get_default_data_dir())
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "ingestion_dlq.db")

        self._db_path = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the DLQ table if it doesn't exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_dlq (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    debate_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0
                )
                """
            )

    def enqueue(self, debate_id: str, result_dict: dict[str, Any], error: str) -> None:
        """Store a failed ingestion for later retry."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO ingestion_dlq (debate_id, result_json, error, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    debate_id,
                    json.dumps(result_dict, default=str),
                    error,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        logger.warning(
            "[ingestion_dlq] Enqueued failed ingestion for debate %s: %s",
            debate_id,
            error,
        )

    def list_failed(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent failed ingestions."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM ingestion_dlq ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def process_queue(self, ingest_fn: Any = None) -> int:
        """Retry all queued items, return count of successes.

        Args:
            ingest_fn: Async or sync callable that accepts a result dict.
                       If None, items remain in queue.

        Returns:
            Number of successfully processed items.
        """
        if ingest_fn is None:
            return 0

        items = self.list_failed(limit=100)
        if not items:
            return 0

        import asyncio

        success_ids: list[int] = []
        for item in items:
            try:
                result_dict = json.loads(item["result_json"])
                if asyncio.iscoroutinefunction(ingest_fn):
                    try:
                        asyncio.get_running_loop()
                        # Cannot await in sync context; skip
                        continue
                    except RuntimeError:
                        pass
                    asyncio.run(ingest_fn(result_dict))
                else:
                    ingest_fn(result_dict)
                success_ids.append(item["id"])
            except (OSError, RuntimeError, ValueError) as e:
                logger.debug(
                    "[ingestion_dlq] Retry failed for debate %s: %s",
                    item["debate_id"],
                    e,
                )
                # Increment retry count
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute(
                        "UPDATE ingestion_dlq SET retry_count = retry_count + 1 WHERE id = ?",
                        (item["id"],),
                    )

        # Delete successes
        if success_ids:
            with sqlite3.connect(self._db_path) as conn:
                placeholders = ",".join("?" for _ in success_ids)
                conn.execute(
                    # parameterized query
                    f"DELETE FROM ingestion_dlq WHERE id IN ({placeholders})",
                    success_ids,
                )
            logger.info(
                "[ingestion_dlq] Processed %d/%d items from DLQ",
                len(success_ids),
                len(items),
            )

        return len(success_ids)

    def clear(self) -> int:
        """Remove all items from the queue. Returns count removed."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("DELETE FROM ingestion_dlq")
            return cursor.rowcount
