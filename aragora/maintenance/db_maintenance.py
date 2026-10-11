"""
Database maintenance for Aragora SQLite databases.

Provides automated maintenance to keep databases performant:
- VACUUM: Reclaim unused space (weekly)
- ANALYZE: Update query optimizer statistics (daily)
- WAL checkpoint: Flush write-ahead log (on startup)
- Data retention: Clean up old records (configurable)
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# Default database directory (respects ARAGORA_DATA_DIR)
def _get_default_db_dir() -> Path:
    from aragora.persistence.db_config import get_nomic_dir

    return get_nomic_dir()


DEFAULT_DB_DIR = _get_default_db_dir()

# All known database files (relative to DB_DIR)
KNOWN_DATABASES = [
    "elo.db",
    "agent_elo.db",
    "continuum.db",
    "agora_memory.db",
    "agent_memories.db",
    "consensus_memory.db",
    "aragora_calibration.db",
    "aragora_insights.db",
    "aragora_personas.db",
    "aragora_positions.db",
    "agent_calibration.db",
    "agent_relationships.db",
    "debate_embeddings.db",
    "genesis.db",
    "grounded_positions.db",
    "meta_learning.db",
    "persona_lab.db",
    "personas.db",
    "agent_personas.db",
    "position_ledger.db",
    "prompt_evolution.db",
    "semantic_patterns.db",
    "suggestion_feedback.db",
    "traces/debate_traces.db",
]

# Whitelist of allowed table names for cleanup operations (SQL injection prevention)
ALLOWED_CLEANUP_TABLES = frozenset(
    {
        "match_history",
        "memories",
        "embeddings",
        "traces",
        "debates",
        "critiques",
        "patterns",
        "ratings",
        "positions",
        "consensus",
        "suggestions",
    }
)

# Allowed timestamp column names
ALLOWED_TIMESTAMP_COLUMNS = frozenset(
    {
        "created_at",
        "timestamp",
        "recorded_at",
    }
)


class DatabaseMaintenance:
    """Automated maintenance for Aragora SQLite databases."""

    def __init__(self, db_dir: Path | str = DEFAULT_DB_DIR):
        self.db_dir = Path(db_dir)
        self._last_vacuum: datetime | None = None
        self._last_analyze: datetime | None = None

    def get_databases(self) -> list[Path]:
        """Get list of all database files that exist."""
        databases = []
        for db_name in KNOWN_DATABASES:
            db_path = self.db_dir / db_name
            if db_path.exists():
                databases.append(db_path)

        # Also find any .db files not in the known list
        for db_file in self.db_dir.glob("**/*.db"):
            if db_file not in databases:
                databases.append(db_file)

        return databases

    def checkpoint_wal(self, db_path: Path) -> bool:
        """Checkpoint WAL file for a single database.

        Flushes write-ahead log to main database file.
        Safe to run frequently, very fast operation.
        """
        if not db_path.exists():
            logger.debug("WAL checkpoint skipped for %s: file not found", db_path.name)
            return False
        try:
            with sqlite3.connect(str(db_path), timeout=30) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return True
        except sqlite3.Error as e:
            logger.warning("WAL checkpoint failed for %s: %s", db_path.name, e)
            return False

    def checkpoint_all_wal(self) -> dict[str, bool]:
        """Checkpoint WAL for all databases."""
        results = {}
        for db_path in self.get_databases():
            results[db_path.name] = self.checkpoint_wal(db_path)

        success_count = sum(results.values())
        logger.info("[maintenance] WAL checkpoint: %s/%s databases", success_count, len(results))
        return results

    def vacuum(self, db_path: Path) -> bool:
        """VACUUM a single database.

        Reclaims unused space and defragments the database.
        Can be slow for large databases - run weekly.
        """
        if not db_path.exists():
            logger.warning("VACUUM skipped for %s: file not found", db_path.name)
            return False
        try:
            start = time.time()
            with sqlite3.connect(str(db_path), timeout=300) as conn:
                conn.execute("VACUUM")
            elapsed = time.time() - start
            logger.debug("VACUUM %s completed in %.1fs", db_path.name, elapsed)
            return True
        except sqlite3.Error as e:
            logger.warning("VACUUM failed for %s: %s", db_path.name, e)
            return False

    def vacuum_all(self) -> dict[str, bool]:
        """VACUUM all databases."""
        results = {}
        start = time.time()

        for db_path in self.get_databases():
            results[db_path.name] = self.vacuum(db_path)

        elapsed = time.time() - start
        success_count = sum(results.values())
        logger.info(
            "[maintenance] VACUUM: %s/%s databases in %.1fs", success_count, len(results), elapsed
        )

        self._last_vacuum = datetime.now()
        return results

    def analyze(self, db_path: Path) -> bool:
        """ANALYZE a single database.

        Updates query optimizer statistics for better query plans.
        Fast operation - safe to run daily.
        """
        if not db_path.exists():
            logger.warning("ANALYZE skipped for %s: file not found", db_path.name)
            return False
        try:
            with sqlite3.connect(str(db_path), timeout=60) as conn:
                conn.execute("ANALYZE")
            return True
        except sqlite3.Error as e:
            logger.warning("ANALYZE failed for %s: %s", db_path.name, e)
            return False

    def analyze_all(self) -> dict[str, bool]:
        """ANALYZE all databases."""
        results = {}
        for db_path in self.get_databases():
            results[db_path.name] = self.analyze(db_path)

        success_count = sum(results.values())
        logger.info("[maintenance] ANALYZE: %s/%s databases", success_count, len(results))

        self._last_analyze = datetime.now()
        return results

    def cleanup_old_data(
        self,
        days: int = 90,
        tables: dict[str, str] | None = None,
    ) -> dict[str, int]:
        """Clean up records older than specified days.

        Args:
            days: Records older than this many days will be deleted
            tables: Dict mapping db_name -> table_name with 'created_at' column.
                   If None, uses default cleanup targets.

        Returns:
            Dict mapping table names to number of deleted rows.

        Raises:
            ValueError: If a table name is not in the allowed whitelist.
        """
        if tables is None:
            # Default cleanup targets (tables with timestamp columns)
            tables = {
                "elo.db": "match_history",
                "agent_elo.db": "match_history",
                "continuum.db": "memories",
                "debate_embeddings.db": "embeddings",
                "traces/debate_traces.db": "traces",
            }

        # Validate all table names against whitelist (SQL injection prevention)
        for table_name in tables.values():
            if table_name not in ALLOWED_CLEANUP_TABLES:
                raise ValueError(
                    f"Invalid table name: {table_name}. "
                    f"Allowed tables: {', '.join(sorted(ALLOWED_CLEANUP_TABLES))}"
                )

        cutoff = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        results = {}

        for db_name, table_name in tables.items():
            db_path = self.db_dir / db_name
            if not db_path.exists():
                continue

            try:
                with sqlite3.connect(str(db_path), timeout=60) as conn:
                    cursor = conn.cursor()

                    # Check if table exists (parameterized query)
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table_name,),
                    )
                    if not cursor.fetchone():
                        continue

                    # Try allowed timestamp column names
                    # table_name is validated above, col is from hardcoded whitelist
                    for col in ALLOWED_TIMESTAMP_COLUMNS:
                        try:
                            # Safe: table_name validated against whitelist, col from whitelist
                            cursor.execute(
                                f"DELETE FROM {table_name} WHERE {col} < ?",  # noqa: S608 -- validated table/col
                                (cutoff_str,),  # noqa: S608 -- table name interpolation, parameterized
                            )
                            deleted = cursor.rowcount
                            if deleted > 0:
                                conn.commit()
                                results[f"{db_name}:{table_name}"] = deleted
                                logger.info(
                                    "[maintenance] Cleaned %s old records from %s:%s",
                                    deleted,
                                    db_name,
                                    table_name,
                                )
                            break
                        except sqlite3.OperationalError:
                            continue  # Column doesn't exist, try next

            except sqlite3.Error as e:
                logger.warning("Cleanup failed for %s: %s", db_name, e)

        return results

    def get_stats(self) -> dict:
        """Get maintenance statistics."""
        databases = self.get_databases()
        total_size = sum(db.stat().st_size for db in databases if db.exists())

        return {
            "database_count": len(databases),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "last_vacuum": self._last_vacuum.isoformat() if self._last_vacuum else None,
            "last_analyze": self._last_analyze.isoformat() if self._last_analyze else None,
            "databases": [db.name for db in databases],
        }


def run_startup_maintenance(db_dir: Path | str = DEFAULT_DB_DIR) -> dict:
    """Run startup maintenance tasks.

    Called when nomic loop or server starts. Performs:
    - WAL checkpoint for all databases
    - ANALYZE if not done recently

    Returns:
        Dict with maintenance results
    """
    maintenance = DatabaseMaintenance(db_dir)

    logger.info("[maintenance] Running startup maintenance...")

    results = {
        "wal_checkpoint": maintenance.checkpoint_all_wal(),
        "stats": maintenance.get_stats(),
    }

    # Check if ANALYZE was done recently (within 24 hours)
    state_file = Path(db_dir) / "maintenance_state.json"
    should_analyze = True

    if state_file.exists():
        try:
            import json

            with open(state_file) as f:
                state = json.load(f)
                last_analyze = datetime.fromisoformat(state.get("last_analyze", "2000-01-01"))
                if datetime.now() - last_analyze < timedelta(hours=24):
                    should_analyze = False
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.debug("Could not read maintenance state: %s", e)

    if should_analyze:
        results["analyze"] = maintenance.analyze_all()

        # Save state
        try:
            import json

            with open(state_file, "w") as f:
                json.dump(
                    {
                        "last_analyze": datetime.now().isoformat(),
                        "last_startup": datetime.now().isoformat(),
                    },
                    f,
                )
        except OSError as e:
            logger.debug("Could not save maintenance state: %s", e)

    logger.info("[maintenance] Startup maintenance complete")
    return results


def schedule_maintenance(
    db_dir: Path | str = DEFAULT_DB_DIR,
    vacuum_interval_days: int = 7,
    analyze_interval_hours: int = 24,
    cleanup_retention_days: int = 90,
) -> dict:
    """Run scheduled maintenance if due.

    Call this periodically (e.g., at the start of each nomic cycle).
    Will only run tasks if sufficient time has passed since last run.

    Returns:
        Dict with tasks that were run
    """
    maintenance = DatabaseMaintenance(db_dir)
    state_file = Path(db_dir) / "maintenance_state.json"
    results: dict = {"tasks_run": []}

    # Load state
    state = {}
    if state_file.exists():
        try:
            import json

            with open(state_file) as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("Could not read maintenance state: %s", e)

    now = datetime.now()

    # Check if VACUUM is due
    last_vacuum = datetime.fromisoformat(state.get("last_vacuum", "2000-01-01"))
    if now - last_vacuum >= timedelta(days=vacuum_interval_days):
        logger.info("[maintenance] Running scheduled VACUUM...")
        results["vacuum"] = maintenance.vacuum_all()
        results["tasks_run"].append("vacuum")
        state["last_vacuum"] = now.isoformat()

    # Check if ANALYZE is due
    last_analyze = datetime.fromisoformat(state.get("last_analyze", "2000-01-01"))
    if now - last_analyze >= timedelta(hours=analyze_interval_hours):
        logger.info("[maintenance] Running scheduled ANALYZE...")
        results["analyze"] = maintenance.analyze_all()
        results["tasks_run"].append("analyze")
        state["last_analyze"] = now.isoformat()

    # Check if cleanup is due (weekly)
    last_cleanup = datetime.fromisoformat(state.get("last_cleanup", "2000-01-01"))
    if now - last_cleanup >= timedelta(days=7):
        logger.info(
            "[maintenance] Cleaning up records older than %s days...", cleanup_retention_days
        )
        results["cleanup"] = maintenance.cleanup_old_data(days=cleanup_retention_days)
        results["tasks_run"].append("cleanup")
        state["last_cleanup"] = now.isoformat()

    # Save state
    if results["tasks_run"]:
        try:
            import json

            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)
        except OSError as e:
            logger.debug("Could not save maintenance state: %s", e)

    return results
