"""
Centralized database configuration for Aragora.

This module provides a single source of truth for all database paths.
Supports both legacy (individual databases) and consolidated mode.
Data-directory resolution and the database file layout live in
``aragora.config.data_dir`` (so the config layer can use them); this module
re-exports them.

Usage:
    from aragora.persistence.db_config import get_db_path, DatabaseType

    # Get path for a specific database type
    elo_path = get_db_path(DatabaseType.ELO)
    memory_path = get_db_path(DatabaseType.CONTINUUM_MEMORY)

Environment Variables:
    ARAGORA_DB_MODE: "legacy" or "consolidated" (default: "consolidated")
    ARAGORA_DATA_DIR: Base directory for databases (default: ".nomic" or "data" if present)
    ARAGORA_NOMIC_DIR: Legacy alias for data directory (default: ".nomic" or "data")
"""

from __future__ import annotations

__all__ = [
    "CONSOLIDATED_DB_MAPPING",
    "DatabaseMode",
    "DatabaseType",
    "DEFAULT_DATA_DIR",
    "DEFAULT_NOMIC_DIR",
    "LEGACY_DB_NAMES",
    "get_db_mode",
    "get_db_path",
    "get_db_path_str",
    "get_default_data_dir",
    "get_elo_db_path",
    "get_genesis_db_path",
    "get_insights_db_path",
    "get_memory_db_path",
    "get_nomic_dir",
    "get_personas_db_path",
    "get_positions_db_path",
]

from pathlib import Path

from aragora.config.data_dir import (
    CONSOLIDATED_DB_MAPPING,
    LEGACY_DB_NAMES,
    DatabaseMode,
    DatabaseType,
    get_db_mode,
    get_default_data_dir,
)


def get_nomic_dir() -> Path:
    """Get the base directory for databases."""
    return get_default_data_dir()


def get_db_path(
    db_type: DatabaseType,
    nomic_dir: Path | None = None,
    mode: DatabaseMode | None = None,
) -> Path:
    """
    Get the path to a database file.

    Args:
        db_type: The type of database to get the path for
        nomic_dir: Base directory (defaults to ARAGORA_DATA_DIR or default data dir)
        mode: Database mode (defaults to ARAGORA_DB_MODE or "consolidated")

    Returns:
        Path to the database file
    """
    if nomic_dir is None:
        nomic_dir = get_nomic_dir()

    if mode is None:
        mode = get_db_mode()

    if not isinstance(db_type, DatabaseType):
        try:
            if isinstance(db_type, str):
                db_type = DatabaseType(db_type)
            elif hasattr(db_type, "value"):
                db_type = DatabaseType(db_type.value)
            else:
                db_type = DatabaseType(str(db_type))
        except (ValueError, KeyError) as exc:
            raise KeyError(db_type) from exc

    if mode == DatabaseMode.CONSOLIDATED:
        db_name = CONSOLIDATED_DB_MAPPING[db_type]
    else:
        db_name = LEGACY_DB_NAMES[db_type]

    return nomic_dir / db_name


def get_db_path_str(
    db_type: DatabaseType,
    nomic_dir: Path | None = None,
    mode: DatabaseMode | None = None,
) -> str:
    """Get the path to a database file as a string."""
    return str(get_db_path(db_type, nomic_dir, mode))


# Convenience functions for common database types
def get_elo_db_path(nomic_dir: Path | None = None) -> Path:
    """Get path to ELO/ratings database."""
    return get_db_path(DatabaseType.ELO, nomic_dir)


def get_memory_db_path(nomic_dir: Path | None = None) -> Path:
    """Get path to continuum memory database."""
    return get_db_path(DatabaseType.CONTINUUM_MEMORY, nomic_dir)


def get_positions_db_path(nomic_dir: Path | None = None) -> Path:
    """Get path to positions database."""
    return get_db_path(DatabaseType.POSITIONS, nomic_dir)


def get_personas_db_path(nomic_dir: Path | None = None) -> Path:
    """Get path to personas database."""
    return get_db_path(DatabaseType.PERSONAS, nomic_dir)


def get_insights_db_path(nomic_dir: Path | None = None) -> Path:
    """Get path to insights database."""
    return get_db_path(DatabaseType.INSIGHTS, nomic_dir)


def get_genesis_db_path(nomic_dir: Path | None = None) -> Path:
    """Get path to genesis database."""
    return get_db_path(DatabaseType.GENESIS, nomic_dir)


# Database path constants for backwards compatibility
# These will be deprecated in favor of get_db_path()
DEFAULT_DATA_DIR = get_default_data_dir()
DEFAULT_NOMIC_DIR = DEFAULT_DATA_DIR

# Legacy path constants (for reference during migration)
DB_ELO_PATH = DEFAULT_NOMIC_DIR / "agent_elo.db"
DB_CONTINUUM_PATH = DEFAULT_NOMIC_DIR / "continuum.db"
DB_POSITIONS_PATH = DEFAULT_NOMIC_DIR / "grounded_positions.db"
DB_PERSONAS_PATH = DEFAULT_NOMIC_DIR / "agent_personas.db"
DB_INSIGHTS_PATH = DEFAULT_NOMIC_DIR / "aragora_insights.db"
DB_GENESIS_PATH = DEFAULT_NOMIC_DIR / "genesis.db"
