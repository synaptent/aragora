"""
Aragora Configuration (Legacy Module).

.. deprecated:: 2.9.0
    This module is deprecated and will be removed in version 3.0.0.
    Please migrate to the new configuration API:

    - For database paths: Use ``aragora.persistence.db_config.get_db_path()``
    - For settings: Use ``aragora.config.settings.get_settings()``
    - For concurrency: Use ``aragora.config.settings.get_settings().concurrency``

    Migration timeline:
    - v2.9.0 (Jan 2026): Deprecation warnings added
    - v3.0.0 (planned): This module will be removed

Centralized configuration with environment variable overrides.
Import these values instead of hardcoding throughout the codebase.
"""

from __future__ import annotations


import os
import warnings
from pathlib import Path
from typing import Any

from aragora.persistence.db_config import get_default_data_dir

# Emit deprecation warning on import
warnings.warn(
    "aragora.config.legacy is deprecated and will be removed in v3.0.0. "
    "Use aragora.config.settings or aragora.persistence.db_config instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Explicit exports for type checking and IDE support
__all__ = [
    # Helper functions
    "get_api_key",
    "validate_configuration",
    "ConfigurationError",
    # Authentication
    "TOKEN_TTL_SECONDS",
    "SHAREABLE_LINK_TTL",
    # Rate Limiting
    "DEFAULT_RATE_LIMIT",
    "IP_RATE_LIMIT",
    # API Limits
    "MAX_API_LIMIT",
    "DEFAULT_PAGINATION",
    "MAX_CONTENT_LENGTH",
    "MAX_QUESTION_LENGTH",
    # Debate Defaults
    "DEFAULT_ROUNDS",
    "MAX_ROUNDS",
    "DEFAULT_CONSENSUS",
    "DEBATE_TIMEOUT_SECONDS",
    "AGENT_TIMEOUT_SECONDS",
    # Agents
    "DEFAULT_AGENTS",
    "STREAMING_CAPABLE_AGENTS",
    "ALLOWED_AGENT_TYPES",
    # Cache TTLs - Leaderboard & Rankings
    "CACHE_TTL_LEADERBOARD",
    "CACHE_TTL_LB_RANKINGS",
    "CACHE_TTL_LB_MATCHES",
    "CACHE_TTL_LB_REPUTATION",
    "CACHE_TTL_LB_TEAMS",
    "CACHE_TTL_LB_STATS",
    "CACHE_TTL_LB_INTROSPECTION",
    # Cache TTLs - Agent Data
    "CACHE_TTL_AGENT_PROFILE",
    "CACHE_TTL_AGENT_H2H",
    "CACHE_TTL_AGENT_FLIPS",
    "CACHE_TTL_AGENT_REPUTATION",
    "CACHE_TTL_RECENT_MATCHES",
    "CACHE_TTL_CALIBRATION_LB",
    "CACHE_TTL_FLIPS_RECENT",
    "CACHE_TTL_FLIPS_SUMMARY",
    # Cache TTLs - Analytics
    "CACHE_TTL_ANALYTICS",
    "CACHE_TTL_ANALYTICS_RANKING",
    "CACHE_TTL_ANALYTICS_DEBATES",
    "CACHE_TTL_ANALYTICS_MEMORY",
    # Cache TTLs - Analytics Dashboard
    "CACHE_TTL_ANALYTICS_OVERVIEW",
    "CACHE_TTL_ANALYTICS_SUMMARY",
    "CACHE_TTL_ANALYTICS_AGENTS",
    "CACHE_TTL_ANALYTICS_COSTS",
    # Cache TTLs - Consensus
    "CACHE_TTL_CONSENSUS",
    "CACHE_TTL_CONSENSUS_SIMILAR",
    "CACHE_TTL_CONSENSUS_SETTLED",
    "CACHE_TTL_CONSENSUS_STATS",
    "CACHE_TTL_RECENT_DISSENTS",
    "CACHE_TTL_CONTRARIAN_VIEWS",
    "CACHE_TTL_RISK_WARNINGS",
    # Cache TTLs - Memory & Learning
    "CACHE_TTL_REPLAYS_LIST",
    "CACHE_TTL_LEARNING_EVOLUTION",
    "CACHE_TTL_META_LEARNING",
    "CACHE_TTL_CRITIQUE_PATTERNS",
    "CACHE_TTL_CRITIQUE_STATS",
    "CACHE_TTL_ARCHIVE_STATS",
    "CACHE_TTL_ALL_REPUTATIONS",
    # Cache TTLs - Dashboard
    "CACHE_TTL_DASHBOARD_DEBATES",
    # Cache TTLs - Embeddings
    "CACHE_TTL_EMBEDDINGS",
    # Cache TTLs - Generic
    "CACHE_TTL_METHOD",
    "CACHE_TTL_QUERY",
    # WebSocket
    "WS_MAX_MESSAGE_SIZE",
    "WS_HEARTBEAT_INTERVAL",
    # Storage
    "DEFAULT_STORAGE_DIR",
    "MAX_LOG_BYTES",
    # Database
    "DB_TIMEOUT_SECONDS",
    "DB_MODE",
    "NOMIC_DIR",
    "DATA_DIR",
    "get_db_path",
    "validate_db_path",
    "resolve_db_path",
    # Database Paths (legacy - prefer get_db_path())
    "DB_ELO_PATH",
    "DB_MEMORY_PATH",
    "DB_INSIGHTS_PATH",
    "DB_CONSENSUS_PATH",
    "DB_CALIBRATION_PATH",
    "DB_LAB_PATH",
    "DB_PERSONAS_PATH",
    "DB_POSITIONS_PATH",
    "DB_GENESIS_PATH",
    # Evidence Collection
    "MAX_SNIPPETS_PER_CONNECTOR",
    "MAX_TOTAL_SNIPPETS",
    "SNIPPET_MAX_LENGTH",
    # Deep Audit
    "DEEP_AUDIT_ROUNDS",
    "CROSS_EXAMINATION_DEPTH",
    "RISK_THRESHOLD",
    # ELO System
    "ELO_INITIAL_RATING",
    "ELO_K_FACTOR",
    "ELO_CALIBRATION_MIN_COUNT",
    # Debate Limits
    "MAX_AGENTS_PER_DEBATE",
    "MAX_CONCURRENT_DEBATES",
    "USER_EVENT_QUEUE_SIZE",
    # State Management Limits
    "MAX_ACTIVE_DEBATES",
    "MAX_ACTIVE_LOOPS",
    "MAX_DEBATE_STATES",
    "MAX_EVENT_QUEUE_SIZE",
    "MAX_REPLAY_QUEUE_SIZE",
    # Belief Network
    "BELIEF_MAX_ITERATIONS",
    "BELIEF_CONVERGENCE_THRESHOLD",
    # SSL/TLS
    "SSL_ENABLED",
    "SSL_CERT_PATH",
    "SSL_KEY_PATH",
    # GraphQL
    "GRAPHQL_ENABLED",
    "GRAPHQL_INTROSPECTION",
    "GRAPHIQL_ENABLED",
]

# Import consolidated environment helpers

from aragora.config.env_helpers import (
    env_int as _env_int,
    env_float as _env_float,
    env_str as _env_str,
    env_bool as _env_bool,
)


def get_api_key(*env_vars: str, required: bool = True) -> str | None:
    """Get and validate an API key from managed custody or the environment.

    Checks each variable in order, returning the first valid
    (non-empty, non-whitespace) value found. Strips whitespace from the result.

    Priority order:
    1. Configured managed custody
    2. Environment variables

    Args:
        *env_vars: Environment variable names to check (in order of preference)
        required: If True, raise ValueError when no valid key found

    Returns:
        The stripped API key, or None if not required and not found

    Raises:
        ValueError: If required=True and no valid key found
        SecretNotFoundError: If strict mode requires managed custody for a missing key
        SecretSourceError: If explicitly configured custody is unsafe

    Example:
        >>> api_key = get_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY")
        >>> optional_key = get_api_key("BACKUP_KEY", required=False)
    """
    try:
        from aragora.config.secrets import (
            SecretNotFoundError,
            get_secret,
            get_secret_presence,
            is_critical_secret,
            is_secret_presence_available,
            is_strict_mode,
        )
    except ImportError:
        for var in env_vars:
            value = os.getenv(var)
            if value and value.strip():
                return value.strip()
    else:
        for var in env_vars:
            presence = get_secret_presence(var)
            if not is_secret_presence_available(presence):
                continue
            if presence.source == "env" and not required:
                value = os.getenv(var)
            else:
                try:
                    value = get_secret(var)
                except SecretNotFoundError:
                    if required:
                        raise
                    continue
                if not value and presence.source == "env":
                    value = os.getenv(var)
            if value and value.strip():
                return value.strip()
        if required and is_strict_mode():
            for var in env_vars:
                if is_critical_secret(var):
                    raise SecretNotFoundError(var)

    if required:
        var_names = " or ".join(env_vars)
        raise ValueError(f"{var_names} environment variable required")
    return None


# === Authentication ===
TOKEN_TTL_SECONDS = _env_int("ARAGORA_TOKEN_TTL", 3600)
SHAREABLE_LINK_TTL = _env_int("ARAGORA_SHAREABLE_LINK_TTL", 3600)

# === Rate Limiting ===
DEFAULT_RATE_LIMIT = _env_int("ARAGORA_RATE_LIMIT", 60)  # requests per minute
IP_RATE_LIMIT = _env_int("ARAGORA_IP_RATE_LIMIT", 120)

# === API Limits ===
MAX_API_LIMIT = _env_int("ARAGORA_MAX_API_LIMIT", 100)
DEFAULT_PAGINATION = _env_int("ARAGORA_DEFAULT_PAGINATION", 20)
MAX_CONTENT_LENGTH = _env_int("ARAGORA_MAX_CONTENT_LENGTH", 100 * 1024 * 1024)  # 100MB
MAX_QUESTION_LENGTH = _env_int("ARAGORA_MAX_QUESTION_LENGTH", 10000)

# === Debate Defaults ===
DEFAULT_ROUNDS = _env_int("ARAGORA_DEFAULT_ROUNDS", 9)
MAX_ROUNDS = _env_int("ARAGORA_MAX_ROUNDS", 12)
DEFAULT_CONSENSUS = _env_str("ARAGORA_DEFAULT_CONSENSUS", "judge")
# Timeout budget: 3 agents × 3 rounds × 4min = 36min theoretical max
# Using 15min gives headroom for consensus + some agent calls
DEBATE_TIMEOUT_SECONDS = _env_int("ARAGORA_DEBATE_TIMEOUT", 900)  # 15 minutes
AGENT_TIMEOUT_SECONDS = _env_int("ARAGORA_AGENT_TIMEOUT", 240)  # 4 minutes per agent call

# Concurrency limits to prevent API rate limit exhaustion
# These are now also available via get_settings().concurrency for Pydantic validation
MAX_CONCURRENT_PROPOSALS = _env_int("ARAGORA_MAX_CONCURRENT_PROPOSALS", 10)
MAX_CONCURRENT_CRITIQUES = _env_int("ARAGORA_MAX_CONCURRENT_CRITIQUES", 20)
MAX_CONCURRENT_REVISIONS = _env_int("ARAGORA_MAX_CONCURRENT_REVISIONS", 10)
MAX_CONCURRENT_STREAMING = _env_int("ARAGORA_MAX_CONCURRENT_STREAMING", 3)
MAX_CONCURRENT_BRANCHES = _env_int("ARAGORA_MAX_CONCURRENT_BRANCHES", 3)
# Legacy stagger delay for proposal phase (0.0 = disabled, use semaphore instead)
PROPOSAL_STAGGER_SECONDS = _env_float("ARAGORA_PROPOSAL_STAGGER_SECONDS", 0.0)

# Heartbeat and timeout configuration
HEARTBEAT_INTERVAL_SECONDS = _env_int("ARAGORA_HEARTBEAT_INTERVAL", 15)


def get_concurrency_settings() -> Any:
    """Get concurrency settings with Pydantic validation.

    Preferred over direct constant access for new code.
    Provides type safety and validation via Pydantic.

    Returns:
        ConcurrencySettings instance with validated values
    """
    from aragora.config.settings import get_settings

    return get_settings().concurrency


# Language enforcement for multilingual models (DeepSeek, Kimi, Qwen)
DEFAULT_DEBATE_LANGUAGE = _env_str("ARAGORA_DEBATE_LANGUAGE", "English")
ENFORCE_RESPONSE_LANGUAGE = _env_bool("ARAGORA_ENFORCE_LANGUAGE", True)

# Inter-request stagger delays to prevent API rate limiting from burst requests
INTER_REQUEST_DELAY_SECONDS = _env_float("ARAGORA_INTER_REQUEST_DELAY", 1.5)
OPENROUTER_INTER_REQUEST_DELAY = _env_float("ARAGORA_OPENROUTER_INTER_REQUEST_DELAY", 2.0)

# Streaming configuration for real-time token display
# Reduced batch size (was 50) for more progressive streaming appearance
STREAM_BATCH_SIZE = _env_int("ARAGORA_STREAM_BATCH_SIZE", 10)
# Reduced interval (was 10) for faster token delivery to frontend
STREAM_DRAIN_INTERVAL_MS = _env_int("ARAGORA_STREAM_DRAIN_INTERVAL_MS", 5)

# === Agents ===
DEFAULT_AGENTS = _env_str(
    "ARAGORA_DEFAULT_AGENTS",
    "grok,anthropic-api,openai-api,deepseek,mistral,gemini,qwen,kimi",
)
STREAMING_CAPABLE_AGENTS = _env_str(
    "ARAGORA_STREAMING_AGENTS", "grok,anthropic-api,openai-api,mistral"
)

# Valid agent types (allowlist for security)
# Single source of truth - import this instead of duplicating
ALLOWED_AGENT_TYPES = frozenset(
    {
        # Built-in
        "demo",
        # CLI-based
        "codex",
        "claude",
        "openai",
        "gemini-cli",
        "grok-cli",
        "qwen-cli",
        "deepseek-cli",
        "kilocode",
        # API-based (direct)
        "gemini",
        "ollama",
        "anthropic-api",
        "openai-api",
        "grok",
        "mistral-api",  # Legacy - use "mistral" via OpenRouter
        "codestral",  # Legacy - use Mistral API directly
        # API-based (via OpenRouter)
        "deepseek",
        "deepseek-r1",
        "llama",
        "mistral",
        "qwen",
        "qwen-max",
        "yi",
        "kimi",
        "kimi-thinking",
        "llama4-maverick",
        "llama4-scout",
        "sonar",
        "command-r",
        "jamba",
        "openrouter",
        # External framework proxy
        "external-framework",
        "openclaw",
        # Multi-framework integrations
        "crewai",
        "autogen",
        "langgraph",
    }
)

# === Caching TTLs (seconds) ===
# Standard tiers - use these for most cases:
#   SHORT=60s   - Real-time or frequently-changing data
#   MEDIUM=120s - Frequently queried, moderate volatility
#   DEFAULT=300s - Standard cache duration
#   LONG=600s   - Stable data, less frequent queries
#   EXTENDED=900s - Aggregate statistics
#   VERY_LONG=1800s - Expensive computation, rarely changes
#   EMBEDDING=3600s - Very expensive, rarely invalidated

# --- Leaderboard & Rankings ---
CACHE_TTL_LEADERBOARD = _env_int("ARAGORA_CACHE_LEADERBOARD", 300)  # 5 min
CACHE_TTL_LB_RANKINGS = _env_int("ARAGORA_CACHE_LB_RANKINGS", 300)  # 5 min
CACHE_TTL_LB_MATCHES = _env_int("ARAGORA_CACHE_LB_MATCHES", 120)  # 2 min
CACHE_TTL_LB_REPUTATION = _env_int("ARAGORA_CACHE_LB_REPUTATION", 300)  # 5 min
CACHE_TTL_LB_TEAMS = _env_int("ARAGORA_CACHE_LB_TEAMS", 600)  # 10 min
CACHE_TTL_LB_STATS = _env_int("ARAGORA_CACHE_LB_STATS", 900)  # 15 min
CACHE_TTL_LB_INTROSPECTION = _env_int("ARAGORA_CACHE_LB_INTROSPECTION", 600)  # 10 min

# --- Agent Data ---
CACHE_TTL_AGENT_PROFILE = _env_int("ARAGORA_CACHE_AGENT_PROFILE", 600)  # 10 min
CACHE_TTL_AGENT_H2H = _env_int("ARAGORA_CACHE_AGENT_H2H", 600)  # 10 min
CACHE_TTL_AGENT_FLIPS = _env_int("ARAGORA_CACHE_AGENT_FLIPS", 300)  # 5 min
CACHE_TTL_AGENT_REPUTATION = _env_int("ARAGORA_CACHE_AGENT_REPUTATION", 120)  # 2 min
CACHE_TTL_RECENT_MATCHES = _env_int("ARAGORA_CACHE_RECENT_MATCHES", 120)  # 2 min
CACHE_TTL_CALIBRATION_LB = _env_int("ARAGORA_CACHE_CALIBRATION_LB", 300)  # 5 min
CACHE_TTL_FLIPS_RECENT = _env_int("ARAGORA_CACHE_FLIPS_RECENT", 300)  # 5 min
CACHE_TTL_FLIPS_SUMMARY = _env_int("ARAGORA_CACHE_FLIPS_SUMMARY", 600)  # 10 min

# --- Analytics ---
CACHE_TTL_ANALYTICS = _env_int("ARAGORA_CACHE_ANALYTICS", 600)  # 10 min
CACHE_TTL_ANALYTICS_RANKING = _env_int("ARAGORA_CACHE_ANALYTICS_RANKING", 300)  # 5 min
CACHE_TTL_ANALYTICS_DEBATES = _env_int("ARAGORA_CACHE_ANALYTICS_DEBATES", 300)  # 5 min
CACHE_TTL_ANALYTICS_MEMORY = _env_int("ARAGORA_CACHE_ANALYTICS_MEMORY", 1800)  # 30 min

# --- Analytics Dashboard (workspace-scoped) ---
CACHE_TTL_ANALYTICS_OVERVIEW = _env_int(
    "ARAGORA_CACHE_ANALYTICS_OVERVIEW", 60
)  # 1 min (fast refresh)
CACHE_TTL_ANALYTICS_SUMMARY = _env_int("ARAGORA_CACHE_ANALYTICS_SUMMARY", 300)  # 5 min
CACHE_TTL_ANALYTICS_AGENTS = _env_int("ARAGORA_CACHE_ANALYTICS_AGENTS", 300)  # 5 min
CACHE_TTL_ANALYTICS_COSTS = _env_int("ARAGORA_CACHE_ANALYTICS_COSTS", 300)  # 5 min

# --- Consensus ---
CACHE_TTL_CONSENSUS = _env_int("ARAGORA_CACHE_CONSENSUS", 240)  # 4 min
CACHE_TTL_CONSENSUS_SIMILAR = _env_int("ARAGORA_CACHE_CONSENSUS_SIMILAR", 240)  # 4 min
CACHE_TTL_CONSENSUS_SETTLED = _env_int("ARAGORA_CACHE_CONSENSUS_SETTLED", 600)  # 10 min
CACHE_TTL_CONSENSUS_STATS = _env_int("ARAGORA_CACHE_CONSENSUS_STATS", 600)  # 10 min
CACHE_TTL_RECENT_DISSENTS = _env_int("ARAGORA_CACHE_RECENT_DISSENTS", 300)  # 5 min
CACHE_TTL_CONTRARIAN_VIEWS = _env_int("ARAGORA_CACHE_CONTRARIAN_VIEWS", 300)  # 5 min
CACHE_TTL_RISK_WARNINGS = _env_int("ARAGORA_CACHE_RISK_WARNINGS", 300)  # 5 min

# --- Memory & Learning ---
CACHE_TTL_REPLAYS_LIST = _env_int("ARAGORA_CACHE_REPLAYS_LIST", 120)  # 2 min
CACHE_TTL_LEARNING_EVOLUTION = _env_int("ARAGORA_CACHE_LEARNING_EVOLUTION", 600)  # 10 min
CACHE_TTL_META_LEARNING = _env_int("ARAGORA_CACHE_META_LEARNING", 60)  # 1 min
CACHE_TTL_CRITIQUE_PATTERNS = _env_int("ARAGORA_CACHE_CRITIQUE_PATTERNS", 120)  # 2 min
CACHE_TTL_CRITIQUE_STATS = _env_int("ARAGORA_CACHE_CRITIQUE_STATS", 300)  # 5 min
CACHE_TTL_ARCHIVE_STATS = _env_int("ARAGORA_CACHE_ARCHIVE_STATS", 600)  # 10 min
CACHE_TTL_ALL_REPUTATIONS = _env_int("ARAGORA_CACHE_ALL_REPUTATIONS", 300)  # 5 min

# --- Dashboard ---
CACHE_TTL_DASHBOARD_DEBATES = _env_int("ARAGORA_CACHE_DASHBOARD_DEBATES", 600)  # 10 min

# --- Embeddings (expensive computation) ---
CACHE_TTL_EMBEDDINGS = _env_int("ARAGORA_CACHE_EMBEDDINGS", 3600)  # 1 hour

# --- Generic cache tiers (for utils/cache.py) ---
CACHE_TTL_METHOD = _env_int("ARAGORA_CACHE_METHOD", 300)  # 5 min
CACHE_TTL_QUERY = _env_int("ARAGORA_CACHE_QUERY", 60)  # 1 min

# === Pulse Scheduler ===
# Auto-start the pulse debate scheduler when the server starts
# Set to "false" or "0" to disable
PULSE_SCHEDULER_AUTOSTART = _env_bool("PULSE_SCHEDULER_AUTOSTART", True)
# Poll interval in seconds (how often to check for trending topics)
PULSE_SCHEDULER_POLL_INTERVAL = _env_int("PULSE_SCHEDULER_POLL_INTERVAL", 300)  # 5 min
# Maximum debates per hour (rate limiting)
PULSE_SCHEDULER_MAX_PER_HOUR = _env_int("PULSE_SCHEDULER_MAX_PER_HOUR", 6)

# === WebSocket ===
# Note: 64KB default prevents memory exhaustion from malicious large messages
# Increase for deployments with trusted clients/large message payloads
WS_MAX_MESSAGE_SIZE = _env_int("ARAGORA_WS_MAX_MESSAGE_SIZE", 64 * 1024)  # 64KB default
WS_HEARTBEAT_INTERVAL = _env_int("ARAGORA_WS_HEARTBEAT", 30)

# === Storage ===
DEFAULT_STORAGE_DIR = _env_str("ARAGORA_STORAGE_DIR", ".aragora")
MAX_LOG_BYTES = _env_int("ARAGORA_MAX_LOG_BYTES", 100 * 1024)  # 100KB

# === Database ===
DB_TIMEOUT_SECONDS = _env_float("ARAGORA_DB_TIMEOUT", 30.0)

# Database mode: "legacy" (individual DBs) or "consolidated" (4 combined DBs)
# See aragora.persistence.db_config for full configuration
# Default: "consolidated" - uses 4 combined databases for better performance
DB_MODE = _env_str("ARAGORA_DB_MODE", "consolidated")

# Nomic directory for databases (relative to working directory)
_DEFAULT_DATA_DIR = get_default_data_dir()
NOMIC_DIR = str(_DEFAULT_DATA_DIR)

# Consolidated data directory (all runtime data under one location)
# Default: .nomic (existing convention) or data/ if present
# Production recommended: /var/lib/aragora or ~/.aragora
DATA_DIR = _DEFAULT_DATA_DIR.resolve()


def validate_db_path(path_str: str, base_dir: Path | None = None) -> Path:
    """
    Validate database path is within allowed directory.

    Prevents path traversal attacks by ensuring resolved path
    stays within the base directory.

    Args:
        path_str: Relative path to database file
        base_dir: Base directory (defaults to DATA_DIR)

    Returns:
        Resolved absolute path

    Raises:
        ConfigurationError: If path escapes base directory
    """
    if base_dir is None:
        base_dir = get_default_data_dir().resolve()

    resolved = (base_dir / path_str).resolve()

    # Security: Ensure path doesn't escape base directory
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError:
        raise ConfigurationError(
            f"Database path escapes data directory: {path_str} "
            f"(resolved to {resolved}, base is {base_dir})"
        )

    return resolved


def get_db_path(name: str, ensure_dir: bool = True) -> Path:
    """
    Get consolidated database path within DATA_DIR.

    This is the preferred method for getting database paths.
    Ensures all databases are stored under DATA_DIR.
    Respects ARAGORA_DB_MODE for consolidated vs legacy mode.

    Args:
        name: Database name (e.g., "agent_elo.db", "continuum.db")
        ensure_dir: If True, create DATA_DIR if it doesn't exist

    Returns:
        Absolute path to database file

    Example:
        >>> elo_path = get_db_path("agent_elo.db")
        >>> # Returns: /absolute/path/to/.nomic/agent_elo.db (legacy)
        >>> # Returns: /absolute/path/to/.nomic/analytics.db (consolidated)
    """
    data_dir = get_default_data_dir().resolve()
    if ensure_dir:
        data_dir.mkdir(parents=True, exist_ok=True)

    # Check if we should use consolidated mode
    try:
        from aragora.persistence.db_config import (
            CONSOLIDATED_DB_MAPPING,
            LEGACY_DB_NAMES,
            DatabaseMode,
            get_db_mode,
        )

        mode = get_db_mode()
        if mode == DatabaseMode.CONSOLIDATED:
            # Map legacy name to DatabaseType
            for db_type, legacy_name in LEGACY_DB_NAMES.items():
                if legacy_name == name:
                    consolidated_name = CONSOLIDATED_DB_MAPPING[db_type]
                    return data_dir / consolidated_name
            # If not found in mapping, fall through to legacy behavior
    except ImportError:
        pass  # db_config not available, use legacy behavior

    return validate_db_path(name, base_dir=data_dir)


def resolve_db_path(path_str: str | Path) -> str:
    """
    Resolve a database path with a guard against stray root-level files.

    - Absolute paths are returned as-is.
    - Bare filenames are redirected under ARAGORA_DATA_DIR (with consolidated mapping).
    - Relative paths with subdirectories are rooted under ARAGORA_DATA_DIR.
    - Special SQLite paths (":memory:", "file:...") are preserved.
    """
    raw = str(path_str)
    if raw == ":memory:" or raw.startswith("file:"):
        return raw

    path = Path(raw)
    if path.is_absolute():
        return str(path)

    if path.parent == Path("."):
        resolved = get_db_path(path.name)
        if resolved != path:
            import logging

            logging.getLogger(__name__).debug(
                "Redirecting SQLite DB path %s -> %s (ARAGORA_DATA_DIR)",
                path,
                resolved,
            )
        return str(resolved)

    # Preserve relative subpaths but keep them under ARAGORA_DATA_DIR
    resolved = validate_db_path(path.as_posix())
    if resolved != path:
        import logging

        logging.getLogger(__name__).debug(
            "Redirecting SQLite DB path %s -> %s (ARAGORA_DATA_DIR)",
            path,
            resolved,
        )
    return str(resolved)


# Database name constants (for use with get_db_path)
DB_NAMES = {
    "elo": "agent_elo.db",
    "memory": "continuum.db",
    "insights": "aragora_insights.db",
    "consensus": "consensus_memory.db",
    "calibration": "agent_calibration.db",
    "lab": "persona_lab.db",
    "personas": "agent_personas.db",
    "positions": "grounded_positions.db",
    "genesis": "genesis.db",
    "blacklist": "token_blacklist.db",
}


# Lazy deprecation - warn only on access via property-like pattern
_DB_PATH_DEFAULTS = {
    "DB_ELO_PATH": ("ARAGORA_DB_ELO", "agent_elo.db"),
    "DB_MEMORY_PATH": ("ARAGORA_DB_MEMORY", "continuum.db"),
    "DB_INSIGHTS_PATH": ("ARAGORA_DB_INSIGHTS", "aragora_insights.db"),
    "DB_CONSENSUS_PATH": ("ARAGORA_DB_CONSENSUS", "consensus_memory.db"),
    "DB_CALIBRATION_PATH": ("ARAGORA_DB_CALIBRATION", "agent_calibration.db"),
    "DB_LAB_PATH": ("ARAGORA_DB_LAB", "persona_lab.db"),
    "DB_PERSONAS_PATH": ("ARAGORA_DB_PERSONAS", "agent_personas.db"),
    "DB_POSITIONS_PATH": ("ARAGORA_DB_POSITIONS", "grounded_positions.db"),
    "DB_GENESIS_PATH": ("ARAGORA_DB_GENESIS", "genesis.db"),
    "DB_KNOWLEDGE_PATH": ("ARAGORA_DB_KNOWLEDGE", "knowledge"),
    "DB_CULTURE_PATH": ("ARAGORA_DB_CULTURE", "culture.db"),
}

# =============================================================================
# DEPRECATED DATABASE PATH CONSTANTS
# =============================================================================
# These constants are DEPRECATED as of January 2026.
# Use the new API from aragora.persistence.db_config instead:
#
#   from aragora.persistence.db_config import DatabaseType, get_db_path
#
#   db_path = get_db_path(DatabaseType.ELO)           # Instead of DB_ELO_PATH
#   db_path = get_db_path(DatabaseType.CONTINUUM_MEMORY)  # Instead of DB_MEMORY_PATH
#   db_path = get_db_path(DatabaseType.INSIGHTS)      # Instead of DB_INSIGHTS_PATH
#   db_path = get_db_path(DatabaseType.CONSENSUS_MEMORY)  # Instead of DB_CONSENSUS_PATH
#   db_path = get_db_path(DatabaseType.CALIBRATION)   # Instead of DB_CALIBRATION_PATH
#   db_path = get_db_path(DatabaseType.LABORATORY)    # Instead of DB_LAB_PATH
#   db_path = get_db_path(DatabaseType.PERSONAS)      # Instead of DB_PERSONAS_PATH
#   db_path = get_db_path(DatabaseType.POSITIONS)     # Instead of DB_POSITIONS_PATH
#   db_path = get_db_path(DatabaseType.GENESIS)       # Instead of DB_GENESIS_PATH
#   db_path = get_db_path(DatabaseType.KNOWLEDGE)     # Instead of DB_KNOWLEDGE_PATH
#
# The new API provides:
#   - Proper Path objects instead of strings
#   - Automatic nomic_dir resolution
#   - Support for consolidated database mode
#   - Type safety with DatabaseType enum
# =============================================================================
DB_ELO_PATH = _env_str("ARAGORA_DB_ELO", "agent_elo.db")
DB_MEMORY_PATH = _env_str("ARAGORA_DB_MEMORY", "continuum.db")
DB_INSIGHTS_PATH = _env_str("ARAGORA_DB_INSIGHTS", "aragora_insights.db")
DB_CONSENSUS_PATH = _env_str("ARAGORA_DB_CONSENSUS", "consensus_memory.db")
DB_CALIBRATION_PATH = _env_str("ARAGORA_DB_CALIBRATION", "agent_calibration.db")
DB_LAB_PATH = _env_str("ARAGORA_DB_LAB", "persona_lab.db")
DB_PERSONAS_PATH = _env_str("ARAGORA_DB_PERSONAS", "agent_personas.db")
DB_POSITIONS_PATH = _env_str("ARAGORA_DB_POSITIONS", "grounded_positions.db")
DB_GENESIS_PATH = _env_str("ARAGORA_DB_GENESIS", "genesis.db")
DB_KNOWLEDGE_PATH = Path(_env_str("ARAGORA_DB_KNOWLEDGE", str(DATA_DIR / "knowledge")))
DB_CULTURE_PATH = _env_str("ARAGORA_DB_CULTURE", "culture.db")

# === Evidence Collection ===
MAX_SNIPPETS_PER_CONNECTOR = _env_int("ARAGORA_MAX_SNIPPETS_CONNECTOR", 3)
MAX_TOTAL_SNIPPETS = _env_int("ARAGORA_MAX_TOTAL_SNIPPETS", 8)
SNIPPET_MAX_LENGTH = _env_int("ARAGORA_SNIPPET_MAX_LENGTH", 1000)

# === Deep Audit ===
DEEP_AUDIT_ROUNDS = _env_int("ARAGORA_DEEP_AUDIT_ROUNDS", 6)
CROSS_EXAMINATION_DEPTH = _env_int("ARAGORA_CROSS_EXAM_DEPTH", 3)
RISK_THRESHOLD = _env_float("ARAGORA_RISK_THRESHOLD", 0.7)

# === ELO System ===
ELO_INITIAL_RATING = _env_int("ARAGORA_ELO_INITIAL", 1500)
ELO_K_FACTOR = _env_int("ARAGORA_ELO_K_FACTOR", 32)
ELO_CALIBRATION_MIN_COUNT = _env_int("ARAGORA_ELO_CALIBRATION_MIN_COUNT", 10)

# === Debate Limits ===
MAX_AGENTS_PER_DEBATE = _env_int("ARAGORA_MAX_AGENTS_PER_DEBATE", 10)
MAX_CONCURRENT_DEBATES = _env_int("ARAGORA_MAX_CONCURRENT_DEBATES", 10)
USER_EVENT_QUEUE_SIZE = _env_int("ARAGORA_USER_EVENT_QUEUE_SIZE", 10000)

# === State Management Limits ===
# Max bounded collections to prevent memory leaks
MAX_ACTIVE_DEBATES = _env_int("ARAGORA_MAX_ACTIVE_DEBATES", 1000)
MAX_ACTIVE_LOOPS = _env_int("ARAGORA_MAX_ACTIVE_LOOPS", 1000)
MAX_DEBATE_STATES = _env_int("ARAGORA_MAX_DEBATE_STATES", 500)
MAX_EVENT_QUEUE_SIZE = _env_int(
    "ARAGORA_MAX_EVENT_QUEUE_SIZE", 50000
)  # Increased for high-volume debates
MAX_REPLAY_QUEUE_SIZE = _env_int("ARAGORA_MAX_REPLAY_QUEUE_SIZE", 10000)

# === Belief Network ===
BELIEF_MAX_ITERATIONS = _env_int("ARAGORA_BELIEF_MAX_ITERATIONS", 100)
BELIEF_CONVERGENCE_THRESHOLD = _env_float("ARAGORA_BELIEF_CONVERGENCE_THRESHOLD", 0.001)

# === SSL/TLS ===
SSL_ENABLED = _env_bool("ARAGORA_SSL_ENABLED", False)
SSL_CERT_PATH = _env_str("ARAGORA_SSL_CERT", "")
SSL_KEY_PATH = _env_str("ARAGORA_SSL_KEY", "")

# === GraphQL ===
# Enable GraphQL API endpoint at /graphql
GRAPHQL_ENABLED = _env_bool("ARAGORA_GRAPHQL_ENABLED", True)
# Enable schema introspection (default: true in dev, false in prod)
# Note: Actual default is computed at runtime based on ARAGORA_ENV
_graphql_introspection_default = _env_str("ARAGORA_ENV", "development") != "production"
GRAPHQL_INTROSPECTION = _env_bool("ARAGORA_GRAPHQL_INTROSPECTION", _graphql_introspection_default)
# Enable GraphiQL playground (default: same as dev mode)
_graphiql_default = _env_str("ARAGORA_ENV", "development") != "production"
GRAPHIQL_ENABLED = _env_bool("ARAGORA_GRAPHIQL_ENABLED", _graphiql_default)

# ============================================================================
# Configuration Validation
# ============================================================================


class ConfigurationError(Exception):
    """Raised when configuration is invalid."""

    pass


def validate_configuration(strict: bool = False) -> dict:
    """
    Validate configuration at startup.

    Checks that:
    - Numeric values are in valid ranges
    - Required paths exist (if SSL enabled)
    - At least one API provider is configured (in strict mode)

    Args:
        strict: If True, require at least one API key to be set

    Returns:
        Dict with validation results:
        {
            "valid": True/False,
            "errors": [...],
            "warnings": [...],
            "config_summary": {...}
        }

    Raises:
        ConfigurationError: If strict=True and critical errors found
    """
    import logging

    logger = logging.getLogger(__name__)

    errors = []
    warnings = []

    # Validate numeric ranges
    if DEFAULT_RATE_LIMIT <= 0:
        errors.append(f"ARAGORA_RATE_LIMIT must be positive, got {DEFAULT_RATE_LIMIT}")

    if MAX_ROUNDS < 1:
        errors.append(f"ARAGORA_MAX_ROUNDS must be >= 1, got {MAX_ROUNDS}")

    if DEFAULT_ROUNDS > MAX_ROUNDS:
        warnings.append(f"ARAGORA_DEFAULT_ROUNDS ({DEFAULT_ROUNDS}) > MAX_ROUNDS ({MAX_ROUNDS})")

    if DB_TIMEOUT_SECONDS <= 0:
        errors.append(f"ARAGORA_DB_TIMEOUT must be positive, got {DB_TIMEOUT_SECONDS}")

    if DEBATE_TIMEOUT_SECONDS < 30:
        warnings.append(f"ARAGORA_DEBATE_TIMEOUT is very low ({DEBATE_TIMEOUT_SECONDS}s)")

    if WS_MAX_MESSAGE_SIZE < 1024:
        warnings.append(f"ARAGORA_WS_MAX_MESSAGE_SIZE is very low ({WS_MAX_MESSAGE_SIZE} bytes)")

    if MAX_AGENTS_PER_DEBATE > 20:
        warnings.append(
            f"ARAGORA_MAX_AGENTS_PER_DEBATE is high ({MAX_AGENTS_PER_DEBATE}), may cause performance issues"
        )

    # Validate DATA_DIR
    if DATA_DIR.exists():
        if not DATA_DIR.is_dir():
            errors.append(f"ARAGORA_DATA_DIR exists but is not a directory: {DATA_DIR}")
        elif not os.access(DATA_DIR, os.W_OK):
            warnings.append(f"ARAGORA_DATA_DIR is not writable: {DATA_DIR}")
    else:
        # Try to create it
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("Created data directory: %s", DATA_DIR)
        except PermissionError:
            errors.append(f"Cannot create ARAGORA_DATA_DIR: {DATA_DIR} (permission denied)")
        except OSError as e:
            errors.append(f"Cannot create ARAGORA_DATA_DIR: {DATA_DIR} ({e})")

    # Check for orphaned database files in project root
    root_db_files = list(Path(".").glob("*.db"))
    if root_db_files and DATA_DIR != Path(".").resolve():
        warnings.append(
            f"Found {len(root_db_files)} .db files in project root. "
            f"Consider migrating to ARAGORA_DATA_DIR ({DATA_DIR})"
        )

    # Validate SSL configuration if enabled
    if SSL_ENABLED:
        if not SSL_CERT_PATH:
            errors.append("ARAGORA_SSL_ENABLED=true but ARAGORA_SSL_CERT not set")
        elif not os.path.exists(SSL_CERT_PATH):
            errors.append(f"SSL certificate not found: {SSL_CERT_PATH}")

        if not SSL_KEY_PATH:
            errors.append("ARAGORA_SSL_ENABLED=true but ARAGORA_SSL_KEY not set")
        elif not os.path.exists(SSL_KEY_PATH):
            errors.append(f"SSL key not found: {SSL_KEY_PATH}")

    # Check API keys (in strict mode)
    api_keys_found = []
    api_keys_checked = [
        ("ANTHROPIC_API_KEY", "Anthropic"),
        ("OPENAI_API_KEY", "OpenAI"),
        ("GEMINI_API_KEY", "Gemini"),
        ("GOOGLE_API_KEY", "Google"),
        ("XAI_API_KEY", "xAI/Grok"),
        ("GROK_API_KEY", "Grok"),
        ("OPENROUTER_API_KEY", "OpenRouter"),
    ]

    for env_var, provider in api_keys_checked:
        if os.getenv(env_var):
            api_keys_found.append(provider)

    if strict and not api_keys_found:
        errors.append(
            "No API keys configured. Set at least one of: "
            + ", ".join(var for var, _ in api_keys_checked)
        )
    elif not api_keys_found:
        warnings.append("No API keys configured - agent functionality will be limited")

    # Build config summary
    config_summary = {
        "rate_limit": DEFAULT_RATE_LIMIT,
        "debate_timeout": DEBATE_TIMEOUT_SECONDS,
        "max_rounds": MAX_ROUNDS,
        "default_rounds": DEFAULT_ROUNDS,
        "max_agents_per_debate": MAX_AGENTS_PER_DEBATE,
        "ws_max_message_size": WS_MAX_MESSAGE_SIZE,
        "db_timeout": DB_TIMEOUT_SECONDS,
        "data_dir": str(DATA_DIR),
        "ssl_enabled": SSL_ENABLED,
        "api_providers": api_keys_found,
    }

    # Log configuration at startup
    is_valid = len(errors) == 0
    if is_valid:
        logger.info("Configuration validated successfully")
        logger.info("  Data directory: %s", DATA_DIR)
        logger.info("  API providers: %s", ", ".join(api_keys_found) if api_keys_found else "none")
        logger.info("  Rate limit: %s req/min", DEFAULT_RATE_LIMIT)
        logger.info("  Debate timeout: %ss", DEBATE_TIMEOUT_SECONDS)
        logger.info("  SSL: %s", "enabled" if SSL_ENABLED else "disabled")
    else:
        for error in errors:
            logger.error("Configuration error: %s", error)
    for warning in warnings:
        logger.warning("Configuration warning: %s", warning)

    result = {
        "valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "config_summary": config_summary,
    }

    if strict and errors:
        raise ConfigurationError(f"Configuration validation failed: {'; '.join(errors)}")

    return result
