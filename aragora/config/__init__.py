"""
Aragora Configuration Package.

This package provides both validated Pydantic settings (new) and
module-level constants (legacy) for configuration.

New code should use the Pydantic settings:
    from aragora.config.settings import get_settings
    settings = get_settings()
    timeout = settings.database.timeout_seconds

Legacy constants are still available for backward compatibility:

See settings.py for the full validated configuration schema.
"""

# Re-export Pydantic settings for convenient access
# Re-export legacy constants for backward compatibility
# Suppress deprecation warning for this internal re-export; the warning should
# only fire when external code imports aragora.config.legacy directly.
# Legacy constants and helpers are lazily imported via __getattr__ below
# to avoid pulling in heavy transitive dependencies at package import time.
_LEGACY_NAMES: set[str] = {
    "AGENT_TIMEOUT_SECONDS",
    "BELIEF_CONVERGENCE_THRESHOLD",
    "BELIEF_MAX_ITERATIONS",
    "CACHE_TTL_AGENT_FLIPS",
    "CACHE_TTL_AGENT_H2H",
    "CACHE_TTL_AGENT_PROFILE",
    "CACHE_TTL_AGENT_REPUTATION",
    "CACHE_TTL_ALL_REPUTATIONS",
    "CACHE_TTL_ANALYTICS",
    "CACHE_TTL_ANALYTICS_AGENTS",
    "CACHE_TTL_ANALYTICS_COSTS",
    "CACHE_TTL_ANALYTICS_DEBATES",
    "CACHE_TTL_ANALYTICS_MEMORY",
    "CACHE_TTL_ANALYTICS_OVERVIEW",
    "CACHE_TTL_ANALYTICS_RANKING",
    "CACHE_TTL_ANALYTICS_SUMMARY",
    "CACHE_TTL_ARCHIVE_STATS",
    "CACHE_TTL_CALIBRATION_LB",
    "CACHE_TTL_CONSENSUS",
    "CACHE_TTL_CONSENSUS_SETTLED",
    "CACHE_TTL_CONSENSUS_SIMILAR",
    "CACHE_TTL_CONSENSUS_STATS",
    "CACHE_TTL_CONTRARIAN_VIEWS",
    "CACHE_TTL_CRITIQUE_PATTERNS",
    "CACHE_TTL_CRITIQUE_STATS",
    "CACHE_TTL_DASHBOARD_DEBATES",
    "CACHE_TTL_EMBEDDINGS",
    "CACHE_TTL_FLIPS_RECENT",
    "CACHE_TTL_FLIPS_SUMMARY",
    "CACHE_TTL_LB_INTROSPECTION",
    "CACHE_TTL_LB_MATCHES",
    "CACHE_TTL_LB_RANKINGS",
    "CACHE_TTL_LB_REPUTATION",
    "CACHE_TTL_LB_STATS",
    "CACHE_TTL_LB_TEAMS",
    "CACHE_TTL_LEADERBOARD",
    "CACHE_TTL_LEARNING_EVOLUTION",
    "CACHE_TTL_META_LEARNING",
    "CACHE_TTL_METHOD",
    "CACHE_TTL_QUERY",
    "CACHE_TTL_RECENT_DISSENTS",
    "CACHE_TTL_RECENT_MATCHES",
    "CACHE_TTL_REPLAYS_LIST",
    "CACHE_TTL_RISK_WARNINGS",
    "CROSS_EXAMINATION_DEPTH",
    "ConfigurationError",
    "DB_CALIBRATION_PATH",
    "DB_CONSENSUS_PATH",
    "DB_CULTURE_PATH",
    "DB_ELO_PATH",
    "DB_GENESIS_PATH",
    "DB_INSIGHTS_PATH",
    "DB_KNOWLEDGE_PATH",
    "DB_LAB_PATH",
    "DB_MEMORY_PATH",
    "DB_MODE",
    "DB_PERSONAS_PATH",
    "DB_POSITIONS_PATH",
    "DB_TIMEOUT_SECONDS",
    "DEBATE_TIMEOUT_SECONDS",
    "DEEP_AUDIT_ROUNDS",
    "DEFAULT_AGENTS",
    "DEFAULT_CONSENSUS",
    "DEFAULT_DEBATE_LANGUAGE",
    "DEFAULT_PAGINATION",
    "DEFAULT_RATE_LIMIT",
    "DEFAULT_ROUNDS",
    "DEFAULT_STORAGE_DIR",
    "ELO_CALIBRATION_MIN_COUNT",
    "ELO_INITIAL_RATING",
    "ELO_K_FACTOR",
    "ENFORCE_RESPONSE_LANGUAGE",
    "HEARTBEAT_INTERVAL_SECONDS",
    "INTER_REQUEST_DELAY_SECONDS",
    "IP_RATE_LIMIT",
    "MAX_ACTIVE_DEBATES",
    "MAX_ACTIVE_LOOPS",
    "MAX_AGENTS_PER_DEBATE",
    "MAX_API_LIMIT",
    "MAX_CONCURRENT_BRANCHES",
    "MAX_CONCURRENT_CRITIQUES",
    "MAX_CONCURRENT_DEBATES",
    "MAX_CONCURRENT_PROPOSALS",
    "MAX_CONCURRENT_REVISIONS",
    "MAX_CONCURRENT_STREAMING",
    "MAX_CONTENT_LENGTH",
    "MAX_DEBATE_STATES",
    "MAX_EVENT_QUEUE_SIZE",
    "MAX_LOG_BYTES",
    "MAX_QUESTION_LENGTH",
    "MAX_REPLAY_QUEUE_SIZE",
    "MAX_ROUNDS",
    "MAX_SNIPPETS_PER_CONNECTOR",
    "MAX_TOTAL_SNIPPETS",
    "NOMIC_DIR",
    "OPENROUTER_INTER_REQUEST_DELAY",
    "PROPOSAL_STAGGER_SECONDS",
    "RISK_THRESHOLD",
    "SHAREABLE_LINK_TTL",
    "SNIPPET_MAX_LENGTH",
    "SSL_CERT_PATH",
    "SSL_ENABLED",
    "SSL_KEY_PATH",
    "STREAMING_CAPABLE_AGENTS",
    "STREAM_BATCH_SIZE",
    "STREAM_DRAIN_INTERVAL_MS",
    "TOKEN_TTL_SECONDS",
    "USER_EVENT_QUEUE_SIZE",
    "WS_HEARTBEAT_INTERVAL",
    "WS_MAX_MESSAGE_SIZE",
    "ProviderKey",
    "get_api_key",
    "get_provider_key",
    "resolve_db_path",
    "select_provider_key",
    "validate_configuration",
}
from .settings import (
    # Constants
    ALLOWED_AGENT_TYPES,
    AgentSettings,
    APILimitSettings,
    # Nested settings classes (for type hints)
    AuthSettings,
    BeliefSettings,
    CacheSettings,
    DatabaseSettings,
    DebateSettings,
    EloSettings,
    EvidenceSettings,
    IntegrationSettings,
    RateLimitSettings,
    # Main settings class and accessor
    Settings,
    SSLSettings,
    StorageSettings,
    WebSocketSettings,
    get_settings,
    reset_settings,
)

# Re-export stability markers for honest epistemics
from .stability import (
    FeatureStabilityInfo,
    Stability,
    get_feature_info,
    get_feature_stability,
    get_stability_badge,
    get_stability_color,
    list_features_by_stability,
    stability_marker,
)

# Re-export centralized timeout configuration
from .timeouts import Timeouts

# Re-export feature flag registry
from .feature_flags import (
    FeatureFlagRegistry,
    FlagCategory,
    FlagDefinition,
    FlagStatus,
    get_flag_registry,
    reset_flag_registry,
    is_enabled,
    get_flag,
)

# Re-export performance SLO configuration
# Performance SLOs are lazily imported via __getattr__ below.
_SLO_NAMES: set[str] = {
    "SLOConfig",
    "get_slo_config",
    "reset_slo_config",
    "check_latency_slo",
    "LatencySLO",
    "ThroughputSLO",
    "AvailabilitySLO",
}

# Re-export configuration validator
from .validator import (
    ConfigurationError as ValidatorConfigurationError,
    get_missing_required_keys,
    print_config_status,
    validate_all,
    validate_production,
)


def _default_agent_list_from_csv(value: str) -> list[str]:
    return [agent.strip() for agent in value.split(",") if agent.strip()]


import importlib as _importlib
import types as _types
from typing import Any as _Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path as _Path

    from .legacy import ProviderKey as ProviderKey

    # Explicit type declarations for lazily-loaded legacy names.
    # These allow mypy to resolve types without triggering runtime imports.
    def resolve_db_path(path_str: str | _Path) -> str: ...
    def get_api_key(*env_vars: str, required: bool = True) -> str | None: ...
    def get_provider_key(*env_vars: str, consumer: str) -> str | None: ...
    def select_provider_key(*env_vars: str, consumer: str) -> ProviderKey | None: ...
    def validate_configuration() -> dict[str, _Any]: ...

    DB_TIMEOUT_SECONDS: float
    NOMIC_DIR: str
    DB_MEMORY_PATH: str
    DB_ELO_PATH: str
    DB_CONSENSUS_PATH: str
    DB_INSIGHTS_PATH: str
    DB_KNOWLEDGE_PATH: str
    DB_GENESIS_PATH: str
    DB_CULTURE_PATH: str
    DB_CALIBRATION_PATH: str
    DB_LAB_PATH: str
    DB_PERSONAS_PATH: str
    DB_POSITIONS_PATH: str
    DB_MODE: str
    DEFAULT_STORAGE_DIR: str
    AGENT_TIMEOUT_SECONDS: float
    DEBATE_TIMEOUT_SECONDS: float
    DEFAULT_AGENTS: str
    DEFAULT_AGENT_LIST: list[str]
    DEFAULT_CONSENSUS: str
    DEFAULT_DEBATE_LANGUAGE: str
    DEFAULT_ROUNDS: int
    DEFAULT_PAGINATION: int
    DEFAULT_RATE_LIMIT: int
    MAX_ROUNDS: int
    MAX_AGENTS_PER_DEBATE: int
    MAX_ACTIVE_DEBATES: int
    MAX_ACTIVE_LOOPS: int
    MAX_CONCURRENT_BRANCHES: int
    MAX_CONCURRENT_CRITIQUES: int
    MAX_CONCURRENT_DEBATES: int
    MAX_CONCURRENT_PROPOSALS: int
    MAX_CONCURRENT_REVISIONS: int
    MAX_CONCURRENT_STREAMING: int
    MAX_CONTENT_LENGTH: int
    MAX_DEBATE_STATES: int
    MAX_EVENT_QUEUE_SIZE: int
    MAX_LOG_BYTES: int
    MAX_QUESTION_LENGTH: int
    MAX_REPLAY_QUEUE_SIZE: int
    MAX_API_LIMIT: int
    MAX_SNIPPETS_PER_CONNECTOR: int
    MAX_TOTAL_SNIPPETS: int
    SNIPPET_MAX_LENGTH: int
    ELO_K_FACTOR: float
    ELO_INITIAL_RATING: float
    ELO_CALIBRATION_MIN_COUNT: int
    BELIEF_CONVERGENCE_THRESHOLD: float
    BELIEF_MAX_ITERATIONS: int
    CROSS_EXAMINATION_DEPTH: int
    DEEP_AUDIT_ROUNDS: int
    RISK_THRESHOLD: float
    ENFORCE_RESPONSE_LANGUAGE: bool
    HEARTBEAT_INTERVAL_SECONDS: float
    INTER_REQUEST_DELAY_SECONDS: float
    OPENROUTER_INTER_REQUEST_DELAY: float
    PROPOSAL_STAGGER_SECONDS: float
    IP_RATE_LIMIT: int
    SHAREABLE_LINK_TTL: int
    SSL_CERT_PATH: str
    SSL_ENABLED: bool
    SSL_KEY_PATH: str
    STREAMING_CAPABLE_AGENTS: list[str]
    STREAM_BATCH_SIZE: int
    STREAM_DRAIN_INTERVAL_MS: int
    TOKEN_TTL_SECONDS: int
    USER_EVENT_QUEUE_SIZE: int
    WS_HEARTBEAT_INTERVAL: int
    WS_MAX_MESSAGE_SIZE: int
    CACHE_TTL_AGENT_FLIPS: int
    CACHE_TTL_AGENT_H2H: int
    CACHE_TTL_AGENT_PROFILE: int
    CACHE_TTL_AGENT_REPUTATION: int
    CACHE_TTL_ALL_REPUTATIONS: int
    CACHE_TTL_ANALYTICS: int
    CACHE_TTL_ANALYTICS_AGENTS: int
    CACHE_TTL_ANALYTICS_COSTS: int
    CACHE_TTL_ANALYTICS_DEBATES: int
    CACHE_TTL_ANALYTICS_MEMORY: int
    CACHE_TTL_ANALYTICS_OVERVIEW: int
    CACHE_TTL_ANALYTICS_RANKING: int
    CACHE_TTL_ANALYTICS_SUMMARY: int
    CACHE_TTL_ARCHIVE_STATS: int
    CACHE_TTL_CALIBRATION_LB: int
    CACHE_TTL_CONSENSUS: int
    CACHE_TTL_CONSENSUS_SETTLED: int
    CACHE_TTL_CONSENSUS_SIMILAR: int
    CACHE_TTL_CONSENSUS_STATS: int
    CACHE_TTL_CONTRARIAN_VIEWS: int
    CACHE_TTL_CRITIQUE_PATTERNS: int
    CACHE_TTL_CRITIQUE_STATS: int
    CACHE_TTL_DASHBOARD_DEBATES: int
    CACHE_TTL_EMBEDDINGS: int
    CACHE_TTL_FLIPS_RECENT: int
    CACHE_TTL_FLIPS_SUMMARY: int
    CACHE_TTL_LB_INTROSPECTION: int
    CACHE_TTL_LB_MATCHES: int
    CACHE_TTL_LB_RANKINGS: int
    CACHE_TTL_LB_REPUTATION: int
    CACHE_TTL_LB_STATS: int
    CACHE_TTL_LB_TEAMS: int
    CACHE_TTL_LEADERBOARD: int
    CACHE_TTL_LEARNING_EVOLUTION: int
    CACHE_TTL_META_LEARNING: int
    CACHE_TTL_METHOD: int
    CACHE_TTL_QUERY: int
    CACHE_TTL_RECENT_DISSENTS: int
    CACHE_TTL_RECENT_MATCHES: int
    CACHE_TTL_REPLAYS_LIST: int
    CACHE_TTL_RISK_WARNINGS: int

    class ConfigurationError(Exception): ...


_legacy_mod: _types.ModuleType | None = None
_slo_mod: _types.ModuleType | None = None


def _get_legacy_mod() -> _types.ModuleType:
    global _legacy_mod
    if _legacy_mod is None:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            _legacy_mod = _importlib.import_module("aragora.config.legacy")
    return _legacy_mod


def _get_slo_mod() -> _types.ModuleType:
    global _slo_mod
    if _slo_mod is None:
        _slo_mod = _importlib.import_module("aragora.config.performance_slos")
    return _slo_mod


def __getattr__(name: str) -> _Any:
    if name in _LEGACY_NAMES:
        mod = _get_legacy_mod()
        value = getattr(mod, name)
        # NOTE: We intentionally do NOT cache in globals() here.
        # Legacy constants (e.g. DEFAULT_CONSENSUS) are computed from
        # environment variables at import time in the legacy module.
        # Caching them in this module's globals() would prevent tests
        # that modify env vars from seeing updated values, causing
        # cross-test pollution.  The performance cost of the extra
        # getattr on the legacy module is negligible since these names
        # are rarely accessed in hot paths.
        return value
    if name in _SLO_NAMES:
        mod = _get_slo_mod()
        value = getattr(mod, name)
        # Same rationale as legacy names: avoid globals() caching.
        return value
    if name == "DEFAULT_AGENT_LIST":
        # Derived from DEFAULT_AGENTS; must not be cached either.
        return _default_agent_list_from_csv(__getattr__("DEFAULT_AGENTS"))
    raise AttributeError(f"module 'aragora.config' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LEGACY_NAMES | _SLO_NAMES | {"DEFAULT_AGENT_LIST"})


__all__ = [
    # Main settings
    "Settings",
    "get_settings",
    "reset_settings",
    # Nested settings classes
    "AuthSettings",
    "RateLimitSettings",
    "APILimitSettings",
    "DebateSettings",
    "AgentSettings",
    "CacheSettings",
    "DatabaseSettings",
    "WebSocketSettings",
    "EloSettings",
    "BeliefSettings",
    "SSLSettings",
    "StorageSettings",
    "EvidenceSettings",
    "IntegrationSettings",
    # Stability markers
    "Stability",
    "FeatureStabilityInfo",
    "stability_marker",
    "get_feature_stability",
    "get_feature_info",
    "list_features_by_stability",
    "get_stability_badge",
    "get_stability_color",
    # Timeouts
    "Timeouts",
    # Performance SLOs
    "SLOConfig",
    "get_slo_config",
    "reset_slo_config",
    "check_latency_slo",
    "LatencySLO",
    "ThroughputSLO",
    "AvailabilitySLO",
    # Configuration Validator
    "validate_all",
    "validate_production",
    "get_missing_required_keys",
    "print_config_status",
    "ValidatorConfigurationError",
    # Feature flags
    "FeatureFlagRegistry",
    "FlagCategory",
    "FlagDefinition",
    "FlagStatus",
    "get_flag_registry",
    "reset_flag_registry",
    "is_enabled",
    "get_flag",
    # Derived defaults
    "DEFAULT_AGENT_LIST",
    # Constants
    "ALLOWED_AGENT_TYPES",
]
