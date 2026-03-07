"""
Centralized database configuration for Aragora.

This module provides a single source of truth for all database paths.
Supports both legacy (individual databases) and consolidated mode.

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

import os
from enum import Enum
from pathlib import Path


def _find_repo_root(start: Path) -> Path | None:
    """Return the nearest parent that contains a Git marker."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _read_worktree_gitdir(repo_root: Path) -> Path | None:
    """Resolve the per-worktree gitdir target when running in a linked worktree."""
    git_marker = repo_root / ".git"
    if not git_marker.is_file():
        return None

    try:
        raw = git_marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    prefix = "gitdir:"
    if not raw.startswith(prefix):
        return None

    gitdir = Path(raw[len(prefix) :].strip())
    if not gitdir.is_absolute():
        gitdir = (repo_root / gitdir).resolve()
    return gitdir.resolve()


def _linked_worktree_data_dir(start: Path | None = None) -> Path | None:
    """Return a stable runtime data dir for a linked worktree, if applicable."""
    repo_root = _find_repo_root(start or Path.cwd())
    if repo_root is None:
        return None

    gitdir = _read_worktree_gitdir(repo_root)
    if gitdir is None or gitdir.parent.name != "worktrees":
        return None

    common_git_dir = gitdir.parent.parent
    return common_git_dir / "aragora" / "data" / gitdir.name


class DatabaseType(Enum):
    """Enumeration of all database types in Aragora."""

    # Core databases
    DEBATES = "debates"
    TRACES = "traces"
    TOURNAMENTS = "tournaments"
    EMBEDDINGS = "embeddings"
    POSITIONS = "positions"

    # Memory databases
    CONTINUUM_MEMORY = "continuum_memory"
    AGENT_MEMORIES = "agent_memories"
    CONSENSUS_MEMORY = "consensus_memory"
    AGORA_MEMORY = "agora_memory"
    SEMANTIC_PATTERNS = "semantic_patterns"
    SUGGESTION_FEEDBACK = "suggestion_feedback"

    # Analytics databases
    ELO = "elo"
    CALIBRATION = "calibration"
    INSIGHTS = "insights"
    PROMPT_EVOLUTION = "prompt_evolution"
    META_LEARNING = "meta_learning"

    # Agent databases
    PERSONAS = "personas"
    RELATIONSHIPS = "relationships"
    LABORATORY = "laboratory"
    TRUTH_GROUNDING = "truth_grounding"
    GENESIS = "genesis"
    GENOMES = "genomes"

    # Evolution databases
    EVOLUTION = "evolution"  # Nomic rollbacks and cycle evolution history

    # Billing databases
    BILLING = "billing"  # Usage sync watermarks and billing state

    # Onboarding databases
    ONBOARDING = "onboarding"  # User onboarding flows and progress


class DatabaseMode(Enum):
    """Database organization modes."""

    LEGACY = "legacy"  # Individual database files (current)
    CONSOLIDATED = "consolidated"  # Four consolidated databases


def get_default_data_dir() -> Path:
    """Resolve the default data directory for SQLite artifacts."""
    env_dir = os.environ.get("ARAGORA_DATA_DIR") or os.environ.get("ARAGORA_NOMIC_DIR")
    if env_dir:
        return Path(env_dir)

    worktree_data_dir = _linked_worktree_data_dir()
    if worktree_data_dir is not None:
        return worktree_data_dir

    # Prefer existing .nomic/ for backwards compatibility, otherwise use data/
    nomic_dir = Path(".nomic")
    if nomic_dir.exists():
        return nomic_dir

    data_dir = Path("data")
    if data_dir.exists():
        return data_dir

    return nomic_dir


# Mapping from DatabaseType to legacy file names
LEGACY_DB_NAMES = {
    # Core
    DatabaseType.DEBATES: "debates.db",
    DatabaseType.TRACES: "traces.db",
    DatabaseType.TOURNAMENTS: "tournaments.db",
    DatabaseType.EMBEDDINGS: "debate_embeddings.db",
    DatabaseType.POSITIONS: "grounded_positions.db",
    # Memory
    DatabaseType.CONTINUUM_MEMORY: "continuum.db",
    DatabaseType.AGENT_MEMORIES: "agent_memories.db",
    DatabaseType.CONSENSUS_MEMORY: "consensus_memory.db",
    DatabaseType.AGORA_MEMORY: "agora_memory.db",
    DatabaseType.SEMANTIC_PATTERNS: "semantic_patterns.db",
    DatabaseType.SUGGESTION_FEEDBACK: "suggestion_feedback.db",
    # Analytics
    DatabaseType.ELO: "agent_elo.db",
    DatabaseType.CALIBRATION: "agent_calibration.db",
    DatabaseType.INSIGHTS: "aragora_insights.db",
    DatabaseType.PROMPT_EVOLUTION: "prompt_evolution.db",
    DatabaseType.META_LEARNING: "meta_learning.db",
    # Agents
    DatabaseType.PERSONAS: "agent_personas.db",
    DatabaseType.RELATIONSHIPS: "agent_relationships.db",
    DatabaseType.LABORATORY: "persona_lab.db",
    DatabaseType.TRUTH_GROUNDING: "aragora_positions.db",
    DatabaseType.GENESIS: "genesis.db",
    DatabaseType.GENOMES: "genesis.db",
    # Evolution
    DatabaseType.EVOLUTION: "evolution.db",
    # Billing
    DatabaseType.BILLING: "billing.db",
    # Onboarding
    DatabaseType.ONBOARDING: "onboarding.db",
}

# Mapping from DatabaseType to consolidated database
CONSOLIDATED_DB_MAPPING = {
    # Core database
    DatabaseType.DEBATES: "core.db",
    DatabaseType.TRACES: "core.db",
    DatabaseType.TOURNAMENTS: "core.db",
    DatabaseType.EMBEDDINGS: "core.db",
    DatabaseType.POSITIONS: "core.db",
    # Memory database
    DatabaseType.CONTINUUM_MEMORY: "memory.db",
    DatabaseType.AGENT_MEMORIES: "memory.db",
    DatabaseType.CONSENSUS_MEMORY: "memory.db",
    DatabaseType.AGORA_MEMORY: "memory.db",
    DatabaseType.SEMANTIC_PATTERNS: "memory.db",
    DatabaseType.SUGGESTION_FEEDBACK: "memory.db",
    # Analytics database
    DatabaseType.ELO: "analytics.db",
    DatabaseType.CALIBRATION: "analytics.db",
    DatabaseType.INSIGHTS: "analytics.db",
    DatabaseType.PROMPT_EVOLUTION: "analytics.db",
    DatabaseType.META_LEARNING: "analytics.db",
    # Agents database
    DatabaseType.PERSONAS: "agents.db",
    DatabaseType.RELATIONSHIPS: "agents.db",
    DatabaseType.LABORATORY: "agents.db",
    DatabaseType.TRUTH_GROUNDING: "agents.db",
    DatabaseType.GENESIS: "agents.db",
    DatabaseType.GENOMES: "agents.db",
    # Evolution
    DatabaseType.EVOLUTION: "core.db",
    # Billing
    DatabaseType.BILLING: "analytics.db",
    # Onboarding
    DatabaseType.ONBOARDING: "core.db",
}


def get_db_mode() -> DatabaseMode:
    """Get the current database mode from environment."""
    mode_str = os.environ.get("ARAGORA_DB_MODE", "consolidated").lower()
    try:
        return DatabaseMode(mode_str)
    except ValueError:
        return DatabaseMode.CONSOLIDATED


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
