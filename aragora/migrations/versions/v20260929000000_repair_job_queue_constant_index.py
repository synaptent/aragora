"""
Drop the constant ``idx_job_queue_pending_priority`` index on SQLite.

Migration created: 2026-09-29

Background
----------
Before its column guard, 20260201000000 ran
``CREATE INDEX IF NOT EXISTS "idx_job_queue_pending_priority" ON "job_queue"
("status", "priority", "scheduled_at")``. On a SQLite ``job_queue`` without a
``scheduled_at`` column (the runtime ``JobQueueStore`` shape), SQLite reads the
unmatched double-quoted name as a string literal and indexes a constant
instead of failing. Such a database still verifies 20260201000000 through its
``previous_checksums``, and the constant index keeps the name, so
``CREATE INDEX IF NOT EXISTS`` would never build the real index later.

This migration drops that index when one of its key columns is an expression
(the real index has only plain columns). If ``scheduled_at`` exists by then, it
builds the real index. PostgreSQL rejected the original statement, so there is
nothing to repair there. It is idempotent.
"""

import logging

from aragora.migrations.patterns import create_index_if_columns_exist, safe_drop_index
from aragora.migrations.runner import Migration
from aragora.storage.backends import DatabaseBackend, PostgreSQLBackend

logger = logging.getLogger(__name__)

INDEX = "idx_job_queue_pending_priority"
TABLE = "job_queue"
COLUMNS = ["status", "priority", "scheduled_at"]


def _indexes_an_expression(backend: DatabaseBackend) -> bool:
    """True if INDEX exists on TABLE and a key column is an expression (cid -2)."""
    rows = backend.fetch_all(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ? AND tbl_name = ?",
        (INDEX, TABLE),
    )
    if not rows:
        return False
    # PRAGMA index_xinfo rows: (seqno, cid, name, desc, coll, key)
    return any(
        row[1] == -2 and row[5] == 1 for row in backend.fetch_all(f'PRAGMA index_xinfo("{INDEX}")')
    )


def up_fn(backend: DatabaseBackend) -> None:
    """Replace the constant index left by the pre-guard 20260201000000 on SQLite."""
    if isinstance(backend, PostgreSQLBackend):
        logger.info("Migration 20260929000000: nothing to repair on PostgreSQL")
        return

    if not _indexes_an_expression(backend):
        return

    logger.warning("Dropping %s: it indexes a constant instead of %s.scheduled_at", INDEX, TABLE)
    safe_drop_index(backend, INDEX, concurrently=False)
    create_index_if_columns_exist(backend, INDEX, TABLE, COLUMNS, concurrently=False)


def down_fn(backend: DatabaseBackend) -> None:
    """Nothing to undo: the dropped index indexed a constant."""
    logger.info("Migration 20260929000000 rollback is a no-op")


migration = Migration(
    version=20260929000000,
    name="Drop constant job_queue scheduling index on SQLite",
    up_fn=up_fn,
    down_fn=down_fn,
)
