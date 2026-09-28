"""
Knowledge Mound Composite Indexes Migration.

This migration adds composite indexes to optimize common query patterns in the
Knowledge Mound PostgreSQL store:

1. (workspace_id, node_type, confidence DESC) - Combined filtering queries
2. (updated_at DESC, workspace_id) - Recent nodes queries by workspace
3. (from_node_id, relationship_type, to_node_id) - Path traversal queries
4. (validation_status, staleness_score) - Revalidation queue optimization

These indexes are designed to be additive and idempotent - they use
IF NOT EXISTS to safely run multiple times without errors.
"""

import logging

from aragora.migrations.patterns import get_missing_columns
from aragora.migrations.runner import Migration
from aragora.storage.backends import DatabaseBackend, PostgreSQLBackend

logger = logging.getLogger(__name__)


def _table_exists(backend: DatabaseBackend, table: str) -> bool:
    """Check if a table exists."""
    try:
        if isinstance(backend, PostgreSQLBackend):
            rows = backend.fetch_all(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_name = %s
                """,
                (table,),
            )
        else:
            # SQLite
            rows = backend.fetch_all(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
        return len(rows) > 0
    except Exception:  # noqa: BLE001
        return False


def _index_exists(backend: DatabaseBackend, index_name: str) -> bool:
    """Check if an index exists."""
    try:
        if isinstance(backend, PostgreSQLBackend):
            rows = backend.fetch_all(
                """
                SELECT indexname FROM pg_indexes
                WHERE indexname = %s
                """,
                (index_name,),
            )
        else:
            # SQLite
            rows = backend.fetch_all(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (index_name,),
            )
        return len(rows) > 0
    except Exception:  # noqa: BLE001
        return False


def _create_index(
    backend: DatabaseBackend, index_name: str, table: str, columns: list[str], sql: str
) -> None:
    """Run ``sql`` unless ``table`` lacks one of ``columns``.

    The Knowledge Mound stores create these tables at runtime, and the SQLite
    KnowledgeMoundMetaStore's knowledge_nodes has no staleness_score column.
    """
    missing = get_missing_columns(backend, table, columns)
    if missing:
        logger.warning(
            "Skipping index %s: table %s has no column(s) %s",
            index_name,
            table,
            ", ".join(missing),
        )
        return
    backend.execute_write(sql)


def up_fn(backend: DatabaseBackend) -> None:
    """Apply the migration - add composite indexes for Knowledge Mound."""
    # =========================================================================
    # 1. Composite index for combined workspace + type + confidence filtering
    # =========================================================================
    # This index optimizes queries like:
    # SELECT * FROM knowledge_nodes
    # WHERE workspace_id = ? AND node_type = ?
    # ORDER BY confidence DESC
    if _table_exists(backend, "knowledge_nodes"):
        logger.info("Adding composite index for workspace_id, node_type, confidence DESC")
        _create_index(
            backend,
            "idx_km_workspace_type_confidence",
            "knowledge_nodes",
            ["workspace_id", "node_type", "confidence"],
            "CREATE INDEX IF NOT EXISTS idx_km_workspace_type_confidence "
            "ON knowledge_nodes(workspace_id, node_type, confidence DESC)",
        )

        # =====================================================================
        # 2. Composite index for recent nodes query by workspace
        # =====================================================================
        # This index optimizes queries like:
        # SELECT * FROM knowledge_nodes
        # WHERE workspace_id = ?
        # ORDER BY updated_at DESC
        logger.info("Adding composite index for updated_at DESC, workspace_id")
        _create_index(
            backend,
            "idx_km_updated_workspace",
            "knowledge_nodes",
            ["updated_at", "workspace_id"],
            "CREATE INDEX IF NOT EXISTS idx_km_updated_workspace "
            "ON knowledge_nodes(updated_at DESC, workspace_id)",
        )

        # =====================================================================
        # 3. Composite index for revalidation queue optimization
        # =====================================================================
        # This index optimizes queries like:
        # SELECT * FROM knowledge_nodes
        # WHERE validation_status = 'unverified'
        # ORDER BY staleness_score DESC
        logger.info("Adding composite index for validation_status, staleness_score")
        _create_index(
            backend,
            "idx_km_validation_staleness",
            "knowledge_nodes",
            ["validation_status", "staleness_score"],
            "CREATE INDEX IF NOT EXISTS idx_km_validation_staleness "
            "ON knowledge_nodes(validation_status, staleness_score DESC)",
        )
    else:
        logger.info("knowledge_nodes table does not exist, skipping node indexes")

    # =========================================================================
    # 4. Composite index for path/relationship traversal queries
    # =========================================================================
    # This index optimizes queries like:
    # SELECT * FROM knowledge_relationships
    # WHERE from_node_id = ? AND relationship_type = ?
    # (also supports finding specific edges between nodes)
    if _table_exists(backend, "knowledge_relationships"):
        logger.info("Adding composite index for from_node_id, relationship_type, to_node_id")
        _create_index(
            backend,
            "idx_km_rel_path",
            "knowledge_relationships",
            ["from_node_id", "relationship_type", "to_node_id"],
            "CREATE INDEX IF NOT EXISTS idx_km_rel_path "
            "ON knowledge_relationships(from_node_id, relationship_type, to_node_id)",
        )
    else:
        logger.info("knowledge_relationships table does not exist, skipping relationship index")

    logger.info("Knowledge Mound composite indexes migration applied successfully")


def down_fn(backend: DatabaseBackend) -> None:
    """Rollback the migration - remove composite indexes."""
    # Drop indexes in reverse order of creation
    # Using IF EXISTS for safety in case they were already dropped

    logger.info("Dropping Knowledge Mound composite indexes")

    backend.execute_write("DROP INDEX IF EXISTS idx_km_rel_path")
    backend.execute_write("DROP INDEX IF EXISTS idx_km_validation_staleness")
    backend.execute_write("DROP INDEX IF EXISTS idx_km_updated_workspace")
    backend.execute_write("DROP INDEX IF EXISTS idx_km_workspace_type_confidence")

    logger.info("Knowledge Mound composite indexes migration rolled back")


migration = Migration(
    version=20260202000000,
    name="Knowledge Mound composite indexes for query optimization",
    up_fn=up_fn,
    down_fn=down_fn,
    # Checksum of up_fn/down_fn before the column guards, so databases that
    # applied that version still verify. The guards only skip indexes naming a
    # column the table lacks, which failed to apply.
    checksum="4fff064b3fc0e4a8280fe9739e2cf094ba03d112b4c61bcc6899cd084c074671",
)
