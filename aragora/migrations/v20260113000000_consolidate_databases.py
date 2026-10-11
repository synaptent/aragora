"""
Database Consolidation Migration

Migrates data from 20+ legacy SQLite databases to 4 consolidated databases:
- core.db: debates, traces, tournaments, embeddings, positions
- memory.db: continuum, agent memories, consensus, critiques, semantic patterns
- analytics.db: ELO, calibration, insights, prompt evolution
- agents.db: personas, relationships, experiments, genesis

Usage:
    # Dry run (read-only, shows what would be migrated)
    python -m aragora.migrations.v20260113000000_consolidate_databases --dry-run

    # Full migration
    python -m aragora.migrations.v20260113000000_consolidate_databases

    # Rollback (clears consolidated tables)
    python -m aragora.migrations.v20260113000000_consolidate_databases --rollback
"""

from __future__ import annotations

import logging
import re
import sqlite3
import sys
from pathlib import Path
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Whitelist of valid table names for SQL injection prevention
# Table names must match SQLite identifier rules: alphanumeric + underscore
_VALID_TABLE_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Allowed tables in consolidated databases (exhaustive whitelist)
_ALLOWED_TABLES = frozenset(
    {
        # Core tables
        "debates",
        "embeddings",
        "positions",
        "detected_flips",
        "traces",
        "trace_events",
        # Memory tables
        "continuum_memory",
        "tier_transitions",
        "continuum_memory_archive",
        "meta_learning_state",
        "memories",
        "reflection_schedule",
        "consensus",
        "dissent",
        "critiques",
        "patterns",
        "agent_reputation",
        "semantic_embeddings",
        "suggestion_injections",
        "contributor_stats",
        # Analytics tables
        "ratings",
        "matches",
        "elo_history",
        "calibration_predictions",
        "domain_calibration",
        "calibration_buckets",
        "insights",
        "debate_summaries",
        "prompt_versions",
        "evolution_history",
        "meta_hyperparams",
        "meta_efficiency_log",
        # Agent tables
        "personas",
        "performance_history",
        "agent_relationships",
        "position_history",
        "debate_outcomes",
        "experiments",
        "emergent_traits",
        "genomes",
        "populations",
        "genesis_events",
    }
)


def _validate_identifier(name: str) -> str:
    """
    Validate SQL identifier format to prevent SQL injection.

    Use this for identifiers from legacy/external sources where
    we can't whitelist all valid names.

    Args:
        name: Identifier (table/column name) to validate

    Returns:
        The validated identifier

    Raises:
        ValueError: If identifier has invalid format
    """
    if not name:
        raise ValueError("Identifier cannot be empty")

    if not _VALID_TABLE_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid SQL identifier format: {name}")

    return name


def _validate_table_name(table: str) -> str:
    """
    Validate table name against whitelist to prevent SQL injection.

    Use this for tables in our consolidated databases.

    Args:
        table: Table name to validate

    Returns:
        The validated table name

    Raises:
        ValueError: If table name is not in whitelist or has invalid format
    """
    # Check pattern first (defense in depth)
    _validate_identifier(table)

    # Check whitelist
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Table '{table}' not in allowed tables whitelist")

    return table


# Migration version
VERSION = "20260113000000"
NAME = "consolidate_databases"


class DatabaseConsolidator:
    """Handles migration from legacy to consolidated databases."""

    def __init__(self, nomic_dir: str | None = None, dry_run: bool = False):
        """
        Initialize consolidator.

        Args:
            nomic_dir: Path to .nomic directory (default: from config)
            dry_run: If True, don't write changes
        """
        self.dry_run = dry_run
        self.stats: dict[str, dict[str, int]] = {}

        # Resolve paths
        if nomic_dir:
            self.nomic_dir = Path(nomic_dir)
        else:
            from aragora.persistence.db_config import get_nomic_dir

            self.nomic_dir = Path(get_nomic_dir())

        # Consolidated databases are at project root, not inside .nomic
        project_root = self.nomic_dir.parent
        self.consolidated_dir = project_root / "consolidated"

        # Ensure consolidated directory exists
        self.consolidated_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Consolidator initialized: nomic_dir=%s, dry_run=%s", self.nomic_dir, dry_run)

    def _connect(self, db_path: Path) -> sqlite3.Connection | None:
        """Connect to a database if it exists."""
        if not db_path.exists():
            logger.debug("Database not found: %s", db_path)
            return None

        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(self, conn: sqlite3.Connection, table: str) -> bool:
        """Check if a table exists in the database."""
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return cursor.fetchone() is not None

    def _get_column_names(self, conn: sqlite3.Connection, table: str) -> list[str]:
        """Get column names for a table."""
        # Validate identifier format to prevent SQL injection
        validated_table = _validate_identifier(table)
        cursor = conn.execute(f"PRAGMA table_info({validated_table})")
        return [row[1] for row in cursor.fetchall()]

    def _copy_table(
        self,
        source_conn: sqlite3.Connection,
        target_conn: sqlite3.Connection,
        source_table: str,
        target_table: str,
        column_mapping: dict[str, str] | None = None,
        transform: Callable[[dict], dict] | None = None,
    ) -> int:
        """
        Copy data from source table to target table.

        Args:
            source_conn: Source database connection
            target_conn: Target database connection
            source_table: Source table name
            target_table: Target table name
            column_mapping: Optional {source_col: target_col} mapping
            transform: Optional row transform function

        Returns:
            Number of rows copied
        """
        # Validate table names to prevent SQL injection
        # Source table: validate identifier format (legacy tables may vary)
        validated_source = _validate_identifier(source_table)
        # Target table: validate against whitelist (our controlled databases)
        validated_target = _validate_table_name(target_table)

        if not self._table_exists(source_conn, validated_source):
            logger.debug("Source table %s not found", validated_source)
            return 0

        # Get source columns
        source_cols = self._get_column_names(source_conn, validated_source)
        target_cols = self._get_column_names(target_conn, validated_target)

        # Build column mapping
        if column_mapping is None:
            column_mapping = {}

        # Auto-map columns that exist in both
        mapped_cols = []
        for src_col in source_cols:
            tgt_col = column_mapping.get(src_col, src_col)
            if tgt_col in target_cols:
                mapped_cols.append((src_col, tgt_col))

        if not mapped_cols:
            logger.warning(
                "No matching columns between %s and %s", validated_source, validated_target
            )
            return 0

        # Read source data (validated_source already checked)
        # internal query construction
        cursor = source_conn.execute(f"SELECT * FROM {validated_source}")
        rows = cursor.fetchall()

        if not rows:
            return 0

        # Copy rows
        copied = 0
        for row in rows:
            row_dict = dict(row)

            # Apply transform if provided
            if transform:
                row_dict = transform(row_dict)
                if row_dict is None:
                    continue

            # Build INSERT statement
            values = []
            cols = []
            for src_col, tgt_col in mapped_cols:
                if src_col in row_dict:
                    cols.append(tgt_col)
                    values.append(row_dict[src_col])

            if not cols:
                continue

            placeholders = ",".join("?" * len(cols))
            col_list = ",".join(cols)

            if not self.dry_run:
                try:
                    # validated_target already checked against whitelist
                    target_conn.execute(
                        # column name interpolation, parameterized
                        f"INSERT OR REPLACE INTO {validated_target} ({col_list}) VALUES ({placeholders})",
                        values,
                    )
                    copied += 1
                except sqlite3.IntegrityError as e:
                    logger.debug("Skip duplicate: %s", e)
            else:
                copied += 1

        return copied

    def migrate_core(self) -> dict[str, int]:
        """Migrate core databases (debates, traces, embeddings, positions)."""
        stats: dict[str, int] = {}

        target_path = self.consolidated_dir / "core.db"
        target_conn = self._connect(target_path)
        if not target_conn:
            logger.error("Cannot connect to target: %s", target_path)
            return stats

        # Execute schema if needed
        schema_path = Path(__file__).parent.parent / "persistence" / "schemas" / "core.sql"
        if schema_path.exists():
            target_conn.executescript(schema_path.read_text())
            target_conn.commit()

        try:
            # 1. Migrate debates from server storage
            for db_name in ["debates.db", "aragora_debates.db"]:
                source_path = self.nomic_dir / db_name
                source_conn = self._connect(source_path)
                if source_conn:
                    count = self._copy_table(source_conn, target_conn, "debates", "debates")
                    stats[f"{db_name}/debates"] = count
                    source_conn.close()

            # 2. Migrate embeddings
            for db_name in ["debate_embeddings.db"]:
                source_path = self.nomic_dir / db_name
                source_conn = self._connect(source_path)
                if source_conn:
                    count = self._copy_table(source_conn, target_conn, "embeddings", "embeddings")
                    stats[f"{db_name}/embeddings"] = count
                    source_conn.close()

            # 3. Migrate positions
            for db_name in ["grounded_positions.db", "aragora_positions.db"]:
                source_path = self.nomic_dir / db_name
                source_conn = self._connect(source_path)
                if source_conn:
                    count = self._copy_table(source_conn, target_conn, "positions", "positions")
                    stats[f"{db_name}/positions"] = count

                    # Also copy detected_flips if exists
                    count = self._copy_table(
                        source_conn, target_conn, "detected_flips", "detected_flips"
                    )
                    if count > 0:
                        stats[f"{db_name}/detected_flips"] = count

                    source_conn.close()

            # 4. Migrate traces
            traces_dir = self.nomic_dir / "traces"
            traces_path = traces_dir / "debate_traces.db" if traces_dir.exists() else None
            if traces_path and traces_path.exists():
                source_conn = self._connect(traces_path)
                if source_conn:
                    count = self._copy_table(source_conn, target_conn, "traces", "traces")
                    stats["traces/traces"] = count

                    count = self._copy_table(
                        source_conn, target_conn, "trace_events", "trace_events"
                    )
                    if count > 0:
                        stats["traces/trace_events"] = count

                    source_conn.close()

            if not self.dry_run:
                target_conn.commit()

        finally:
            target_conn.close()

        self.stats["core"] = stats
        return stats

    def migrate_memory(self) -> dict[str, int]:
        """Migrate memory databases (continuum, consensus, critiques)."""
        stats: dict[str, int] = {}

        target_path = self.consolidated_dir / "memory.db"
        target_conn = self._connect(target_path)
        if not target_conn:
            logger.error("Cannot connect to target: %s", target_path)
            return stats

        # Execute schema if needed
        schema_path = Path(__file__).parent.parent / "persistence" / "schemas" / "memory.sql"
        if schema_path.exists():
            target_conn.executescript(schema_path.read_text())
            target_conn.commit()

        try:
            # 1. Migrate continuum memory
            for db_name in ["continuum.db", "continuum_memory.db"]:
                source_path = self.nomic_dir / db_name
                source_conn = self._connect(source_path)
                if source_conn:
                    count = self._copy_table(
                        source_conn, target_conn, "continuum_memory", "continuum_memory"
                    )
                    stats[f"{db_name}/continuum_memory"] = count

                    count = self._copy_table(
                        source_conn, target_conn, "tier_transitions", "tier_transitions"
                    )
                    if count > 0:
                        stats[f"{db_name}/tier_transitions"] = count

                    count = self._copy_table(
                        source_conn,
                        target_conn,
                        "continuum_memory_archive",
                        "continuum_memory_archive",
                    )
                    if count > 0:
                        stats[f"{db_name}/archive"] = count

                    count = self._copy_table(
                        source_conn, target_conn, "meta_learning_state", "meta_learning_state"
                    )
                    if count > 0:
                        stats[f"{db_name}/meta_learning"] = count

                    source_conn.close()

            # 2. Migrate agent memories
            source_path = self.nomic_dir / "agent_memories.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(source_conn, target_conn, "memories", "memories")
                stats["agent_memories/memories"] = count

                count = self._copy_table(
                    source_conn, target_conn, "reflection_schedule", "reflection_schedule"
                )
                if count > 0:
                    stats["agent_memories/reflection_schedule"] = count

                source_conn.close()

            # 3. Migrate consensus memory
            source_path = self.nomic_dir / "consensus_memory.db"
            source_conn = self._connect(source_path)
            if source_conn:
                # Map 'position' column to 'conclusion' in target
                count = self._copy_table(
                    source_conn,
                    target_conn,
                    "consensus",
                    "consensus",
                    column_mapping={"position": "conclusion"},
                )
                stats["consensus_memory/consensus"] = count

                # Map columns for dissent
                count = self._copy_table(
                    source_conn,
                    target_conn,
                    "dissent",
                    "dissent",
                    column_mapping={
                        "consensus_id": "debate_id",
                        "agent_name": "agent_id",
                        "dissent_position": "content",
                    },
                )
                if count > 0:
                    stats["consensus_memory/dissent"] = count

                source_conn.close()

            # 4. Migrate agora memory (critique patterns)
            source_path = self.nomic_dir / "agora_memory.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(source_conn, target_conn, "critiques", "critiques")
                stats["agora_memory/critiques"] = count

                count = self._copy_table(source_conn, target_conn, "patterns", "patterns")
                if count > 0:
                    stats["agora_memory/patterns"] = count

                count = self._copy_table(
                    source_conn, target_conn, "agent_reputation", "agent_reputation"
                )
                if count > 0:
                    stats["agora_memory/agent_reputation"] = count

                source_conn.close()

            # 5. Migrate semantic patterns
            source_path = self.nomic_dir / "semantic_patterns.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(
                    source_conn, target_conn, "embeddings", "semantic_embeddings"
                )
                stats["semantic_patterns/embeddings"] = count
                source_conn.close()

            # 6. Migrate suggestion feedback
            source_path = self.nomic_dir / "suggestion_feedback.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(
                    source_conn, target_conn, "suggestion_injections", "suggestion_injections"
                )
                stats["suggestion_feedback/injections"] = count

                count = self._copy_table(
                    source_conn, target_conn, "contributor_stats", "contributor_stats"
                )
                if count > 0:
                    stats["suggestion_feedback/contributor_stats"] = count

                source_conn.close()

            if not self.dry_run:
                target_conn.commit()

        finally:
            target_conn.close()

        self.stats["memory"] = stats
        return stats

    def migrate_analytics(self) -> dict[str, int]:
        """Migrate analytics databases (ELO, calibration, insights)."""
        stats: dict[str, int] = {}

        target_path = self.consolidated_dir / "analytics.db"
        target_conn = self._connect(target_path)
        if not target_conn:
            logger.error("Cannot connect to target: %s", target_path)
            return stats

        # Execute schema if needed
        schema_path = Path(__file__).parent.parent / "persistence" / "schemas" / "analytics.sql"
        if schema_path.exists():
            target_conn.executescript(schema_path.read_text())
            target_conn.commit()

        try:
            # 1. Migrate ELO ratings
            source_path = self.nomic_dir / "agent_elo.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(source_conn, target_conn, "ratings", "ratings")
                stats["agent_elo/ratings"] = count

                count = self._copy_table(source_conn, target_conn, "matches", "matches")
                if count > 0:
                    stats["agent_elo/matches"] = count

                count = self._copy_table(source_conn, target_conn, "elo_history", "elo_history")
                if count > 0:
                    stats["agent_elo/history"] = count

                source_conn.close()

            # 2. Migrate calibration
            source_path = self.nomic_dir / "agent_calibration.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(
                    source_conn, target_conn, "calibration_predictions", "calibration_predictions"
                )
                stats["calibration/predictions"] = count

                count = self._copy_table(
                    source_conn, target_conn, "domain_calibration", "domain_calibration"
                )
                if count > 0:
                    stats["calibration/domain"] = count

                count = self._copy_table(
                    source_conn, target_conn, "calibration_buckets", "calibration_buckets"
                )
                if count > 0:
                    stats["calibration/buckets"] = count

                source_conn.close()

            # 3. Migrate insights
            source_path = self.nomic_dir / "aragora_insights.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(source_conn, target_conn, "insights", "insights")
                stats["insights/insights"] = count

                count = self._copy_table(
                    source_conn, target_conn, "debate_summaries", "debate_summaries"
                )
                if count > 0:
                    stats["insights/summaries"] = count

                source_conn.close()

            # 4. Migrate prompt evolution
            source_path = self.nomic_dir / "prompt_evolution.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(
                    source_conn, target_conn, "prompt_versions", "prompt_versions"
                )
                stats["prompt_evolution/versions"] = count

                count = self._copy_table(
                    source_conn, target_conn, "evolution_history", "evolution_history"
                )
                if count > 0:
                    stats["prompt_evolution/history"] = count

                source_conn.close()

            # 5. Migrate meta-learning
            source_path = self.nomic_dir / "meta_learning.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(
                    source_conn, target_conn, "meta_hyperparams", "meta_hyperparams"
                )
                stats["meta_learning/hyperparams"] = count

                count = self._copy_table(
                    source_conn, target_conn, "meta_efficiency_log", "meta_efficiency_log"
                )
                if count > 0:
                    stats["meta_learning/efficiency"] = count

                source_conn.close()

            if not self.dry_run:
                target_conn.commit()

        finally:
            target_conn.close()

        self.stats["analytics"] = stats
        return stats

    def migrate_agents(self) -> dict[str, int]:
        """Migrate agent databases (personas, relationships, genesis)."""
        stats: dict[str, int] = {}

        target_path = self.consolidated_dir / "agents.db"
        target_conn = self._connect(target_path)
        if not target_conn:
            logger.error("Cannot connect to target: %s", target_path)
            return stats

        # Execute schema if needed
        schema_path = Path(__file__).parent.parent / "persistence" / "schemas" / "agents.sql"
        if schema_path.exists():
            target_conn.executescript(schema_path.read_text())
            target_conn.commit()

        try:
            # 1. Migrate personas
            for db_name in ["agent_personas.db", "aragora_personas.db"]:
                source_path = self.nomic_dir / db_name
                source_conn = self._connect(source_path)
                if source_conn:
                    count = self._copy_table(source_conn, target_conn, "personas", "personas")
                    stats[f"{db_name}/personas"] = count

                    count = self._copy_table(
                        source_conn, target_conn, "performance_history", "performance_history"
                    )
                    if count > 0:
                        stats[f"{db_name}/performance"] = count

                    source_conn.close()

            # 2. Migrate relationships
            source_path = self.nomic_dir / "agent_relationships.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(
                    source_conn, target_conn, "agent_relationships", "agent_relationships"
                )
                stats["relationships/relationships"] = count

                count = self._copy_table(
                    source_conn, target_conn, "position_history", "position_history"
                )
                if count > 0:
                    stats["relationships/positions"] = count

                count = self._copy_table(
                    source_conn, target_conn, "debate_outcomes", "debate_outcomes"
                )
                if count > 0:
                    stats["relationships/outcomes"] = count

                source_conn.close()

            # 3. Migrate persona lab
            source_path = self.nomic_dir / "persona_lab.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(source_conn, target_conn, "experiments", "experiments")
                stats["persona_lab/experiments"] = count

                count = self._copy_table(
                    source_conn, target_conn, "emergent_traits", "emergent_traits"
                )
                if count > 0:
                    stats["persona_lab/traits"] = count

                source_conn.close()

            # 4. Migrate genesis
            source_path = self.nomic_dir / "genesis.db"
            source_conn = self._connect(source_path)
            if source_conn:
                count = self._copy_table(source_conn, target_conn, "genomes", "genomes")
                stats["genesis/genomes"] = count

                count = self._copy_table(source_conn, target_conn, "populations", "populations")
                if count > 0:
                    stats["genesis/populations"] = count

                count = self._copy_table(
                    source_conn, target_conn, "genesis_events", "genesis_events"
                )
                if count > 0:
                    stats["genesis/events"] = count

                source_conn.close()

            if not self.dry_run:
                target_conn.commit()

        finally:
            target_conn.close()

        self.stats["agents"] = stats
        return stats

    def run(self) -> dict[str, dict[str, int]]:
        """Run full consolidation migration."""
        logger.info("=" * 60)
        logger.info("DATABASE CONSOLIDATION MIGRATION %s", "(DRY RUN)" if self.dry_run else "")
        logger.info("=" * 60)

        # Run all migrations
        self.migrate_core()
        self.migrate_memory()
        self.migrate_analytics()
        self.migrate_agents()

        # Log summary
        total = 0
        logger.info("=" * 60)
        logger.info("MIGRATION SUMMARY")
        logger.info("=" * 60)

        for db_name, tables in self.stats.items():
            db_total = sum(tables.values())
            total += db_total
            logger.info("%s.db:", db_name)
            for table, count in sorted(tables.items()):
                if count > 0:
                    logger.info("  %s: %s rows", table, count)
            logger.info("  Total: %s rows", db_total)

        logger.info("-" * 60)
        logger.info("TOTAL ROWS MIGRATED: %s", total)
        logger.info("-" * 60)

        if self.dry_run:
            logger.info("[DRY RUN] No changes were made to databases.")
        else:
            logger.info(
                "Migration complete. Set ARAGORA_DB_MODE=consolidated to use new databases."
            )

        return self.stats

    def rollback(self) -> None:
        """Rollback migration by clearing consolidated tables."""
        logger.info("Rolling back consolidation migration...")

        for db_name in ["core.db", "memory.db", "analytics.db", "agents.db"]:
            db_path = self.consolidated_dir / db_name
            if not db_path.exists():
                continue

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Get all tables except schema tracking
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_%'"
            )
            tables = [row[0] for row in cursor.fetchall()]

            for table in tables:
                if not self.dry_run:
                    # Validate table name against whitelist before DELETE
                    try:
                        validated_table = _validate_table_name(table)
                        # table name interpolation, parameterized
                        cursor.execute(f"DELETE FROM {validated_table}")
                        logger.info("Cleared %s/%s", db_name, validated_table)
                    except ValueError as e:
                        logger.warning("Skipping unknown table %s: %s", table, e)

            if not self.dry_run:
                conn.commit()
            conn.close()

        logger.info("Rollback complete." if not self.dry_run else "[DRY RUN] No changes made.")


# Migration functions for aragora.migrations.runner
def up_fn(conn: sqlite3.Connection) -> None:
    """Upgrade function for migration runner."""
    consolidator = DatabaseConsolidator()
    consolidator.run()


def down_fn(conn: sqlite3.Connection) -> None:
    """Downgrade function for migration runner."""
    consolidator = DatabaseConsolidator()
    consolidator.rollback()


# CLI entry point
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    dry_run = "--dry-run" in sys.argv
    rollback = "--rollback" in sys.argv

    consolidator = DatabaseConsolidator(dry_run=dry_run)

    if rollback:
        consolidator.rollback()
    else:
        consolidator.run()
