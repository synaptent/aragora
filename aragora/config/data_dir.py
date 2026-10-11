"""Data-directory resolution and SQLite file layout.

Stdlib-only, so every layer (including ``aragora.config``) can work out where
Aragora keeps its SQLite files without importing ``aragora.persistence``.
``aragora.persistence.db_config`` re-exports these names and builds the
per-database path helpers on top of them.

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
    "LEGACY_DB_NAMES",
    "get_db_mode",
    "get_default_data_dir",
]

import os
from enum import Enum
from pathlib import Path


def _is_within_root(path: Path, root: Path) -> bool:
    """Return whether path resolves inside root."""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


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
    """Return a stable runtime data dir for a linked worktree, if applicable.

    The path stays rooted inside the linked worktree so sandboxed worker lanes
    can create SQLite artifacts without escaping back to the shared gitdir.
    """
    repo_root = _find_repo_root(start or Path.cwd())
    if repo_root is None:
        return None

    gitdir = _read_worktree_gitdir(repo_root)
    if gitdir is None or gitdir.parent.name != "worktrees":
        return None

    worktree_nomic = repo_root / ".nomic"
    if worktree_nomic.exists() and _is_within_root(worktree_nomic, repo_root):
        return worktree_nomic

    worktree_data = repo_root / "data"
    if worktree_data.exists() and _is_within_root(worktree_data, repo_root):
        return worktree_data

    if _is_within_root(worktree_nomic, repo_root):
        return worktree_nomic
    return None


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
