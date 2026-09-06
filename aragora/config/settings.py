"""
Pydantic-based configuration settings for Aragora.

This module provides validated, type-safe configuration using Pydantic.
All settings can be overridden via environment variables with the ARAGORA_ prefix.

Usage:
    from aragora.config.settings import get_settings

    settings = get_settings()
    print(settings.database.timeout_seconds)
    print(settings.rate_limit.default_limit)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_nomic_dir() -> str:
    """Resolve default data dir for database files."""
    from aragora.persistence.db_config import get_default_data_dir

    return str(get_default_data_dir())


class AuthSettings(BaseSettings):
    """Authentication configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_")

    token_ttl: int = Field(default=3600, ge=60, le=86400, alias="ARAGORA_TOKEN_TTL")
    shareable_link_ttl: int = Field(
        default=3600, ge=60, le=604800, alias="ARAGORA_SHAREABLE_LINK_TTL"
    )
    # Rate limit tracking limits (prevent memory exhaustion)
    max_tracked_entries: int = Field(
        default=10000,
        ge=100,
        le=1000000,
        description="Max entries in rate limit tracking to prevent memory exhaustion",
    )
    max_revoked_tokens: int = Field(
        default=10000, ge=100, le=1000000, description="Max revoked tokens to store"
    )
    revoked_token_ttl: int = Field(
        default=86400, ge=3600, le=604800, description="How long to keep revoked tokens (seconds)"
    )
    rate_limit_window: int = Field(
        default=60, ge=10, le=3600, description="Rate limit window in seconds"
    )


class RateLimitSettings(BaseSettings):
    """Rate limiting configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_")

    default_limit: int = Field(default=60, ge=1, le=10000, alias="ARAGORA_RATE_LIMIT")
    ip_rate_limit: int = Field(default=120, ge=1, le=10000, alias="ARAGORA_IP_RATE_LIMIT")
    burst_multiplier: float = Field(default=2.0, ge=1.0, le=10.0, alias="ARAGORA_BURST_MULTIPLIER")

    # Redis configuration for persistent rate limiting
    redis_url: str | None = Field(default=None, alias="ARAGORA_REDIS_URL")
    redis_key_prefix: str = Field(default="aragora:ratelimit:", alias="ARAGORA_REDIS_KEY_PREFIX")
    redis_ttl_seconds: int = Field(default=120, ge=60, le=3600, alias="ARAGORA_REDIS_TTL")


class APILimitSettings(BaseSettings):
    """API limits configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_")

    max_api_limit: int = Field(default=100, ge=1, le=1000, alias="ARAGORA_MAX_API_LIMIT")
    default_pagination: int = Field(default=20, ge=1, le=100, alias="ARAGORA_DEFAULT_PAGINATION")
    max_content_length: int = Field(
        default=100 * 1024 * 1024, ge=1024, alias="ARAGORA_MAX_CONTENT_LENGTH"
    )
    max_question_length: int = Field(
        default=10000, ge=100, le=100000, alias="ARAGORA_MAX_QUESTION_LENGTH"
    )


class DebateSettings(BaseSettings):
    """Debate configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_")

    default_rounds: int = Field(default=9, ge=1, le=20, alias="ARAGORA_DEFAULT_ROUNDS")
    max_rounds: int = Field(default=12, ge=1, le=50, alias="ARAGORA_MAX_ROUNDS")
    default_consensus: str = Field(default="judge", alias="ARAGORA_DEFAULT_CONSENSUS")
    timeout_seconds: int = Field(default=600, ge=30, le=7200, alias="ARAGORA_DEBATE_TIMEOUT")
    max_agents_per_debate: int = Field(
        default=20, ge=2, le=50, alias="ARAGORA_MAX_AGENTS_PER_DEBATE"
    )
    max_concurrent_debates: int = Field(
        default=10, ge=1, le=100, alias="ARAGORA_MAX_CONCURRENT_DEBATES"
    )
    user_event_queue_size: int = Field(
        default=10000, ge=100, le=100000, alias="ARAGORA_USER_EVENT_QUEUE_SIZE"
    )

    @field_validator("default_consensus")
    @classmethod
    def validate_consensus(cls, v: str) -> str:
        valid = {"unanimous", "majority", "supermajority", "hybrid", "judge"}
        if v.lower() not in valid:
            raise ValueError(f"Consensus must be one of {valid}")
        return v.lower()


class LoggingSettings(BaseSettings):
    """Logging configuration.

    Centralizes logging settings for the application. Integrates with
    aragora.logging_config for structured logging with tracing support.
    """

    model_config = SettingsConfigDict(env_prefix="ARAGORA_LOG_")

    level: str = Field(
        default="INFO",
        alias="ARAGORA_LOG_LEVEL",
        description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    format: str = Field(
        default="json",
        alias="ARAGORA_LOG_FORMAT",
        description="Log format (json or text)",
    )
    file: str = Field(
        default="",
        alias="ARAGORA_LOG_FILE",
        description="Optional file path for log output (empty for stdout only)",
    )
    max_bytes: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        ge=1024,
        le=1024 * 1024 * 1024,  # 1GB
        alias="ARAGORA_LOG_MAX_BYTES",
        description="Maximum log file size before rotation (bytes)",
    )
    backup_count: int = Field(
        default=5,
        ge=0,
        le=100,
        alias="ARAGORA_LOG_BACKUP_COUNT",
        description="Number of backup log files to keep",
    )
    include_source_location: bool = Field(
        default=False,
        alias="ARAGORA_LOG_SOURCE_LOCATION",
        description="Include file/line/function in log records",
    )
    sensitive_fields: str = Field(
        default="password,token,secret,api_key,authorization,cookie,session",
        alias="ARAGORA_LOG_SENSITIVE_FIELDS",
        description="Comma-separated list of field names to redact in logs",
    )

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"Log level must be one of {valid}")
        return upper

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        valid = {"json", "text"}
        lower = v.lower()
        if lower not in valid:
            raise ValueError(f"Log format must be one of {valid}")
        return lower

    def get_sensitive_fields(self) -> list[str]:
        """Get sensitive fields as a list."""
        return [f.strip() for f in self.sensitive_fields.split(",") if f.strip()]


class AgentSettings(BaseSettings):
    """Agent configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_")

    default_agents: str = Field(
        default="grok,anthropic-api,openai-api,deepseek,mistral,gemini,qwen,kimi",
        alias="ARAGORA_DEFAULT_AGENTS",
    )
    streaming_agents: str = Field(
        default="grok,anthropic-api,openai-api,mistral",
        alias="ARAGORA_STREAMING_AGENTS",
    )

    # Streaming configuration
    stream_buffer_size: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        ge=1024,
        le=100 * 1024 * 1024,  # 100MB max
        alias="ARAGORA_STREAM_BUFFER_SIZE",
        description="Maximum buffer size for streaming responses (bytes)",
    )
    stream_chunk_timeout: float = Field(
        default=180.0,  # Reduced from 300s - must be < agent_timeout to prevent zombie streams
        ge=5.0,
        le=600.0,
        alias="ARAGORA_STREAM_CHUNK_TIMEOUT",
        description="Timeout between stream chunks (seconds)",
    )

    # Context limits (for truncation)
    max_context_chars: int = Field(
        default=100000,
        ge=1000,
        le=1000000,
        alias="ARAGORA_MAX_CONTEXT_CHARS",
        description="Maximum characters for context/history",
    )
    max_message_chars: int = Field(
        default=50000,
        ge=1000,
        le=500000,
        alias="ARAGORA_MAX_MESSAGE_CHARS",
        description="Maximum characters per message",
    )

    # OpenRouter fallback configuration.
    #
    # Fallback is enabled by default so a missing/revoked direct provider key
    # does not block heterogeneous debates. The fallback still requires an
    # OPENROUTER_API_KEY from the configured secret provider. Set
    # ARAGORA_OPENROUTER_FALLBACK_ENABLED=false for explicit opt-out.
    openrouter_fallback_enabled: bool = Field(
        default=True,
        alias="ARAGORA_OPENROUTER_FALLBACK_ENABLED",
        description=(
            "Enable OpenRouter fallback on auth/quota/rate-limit errors "
            "(requires OPENROUTER_API_KEY from the configured secret provider)"
        ),
    )

    # Local LLM fallback configuration
    local_fallback_enabled: bool = Field(
        default=False,
        alias="ARAGORA_LOCAL_FALLBACK_ENABLED",
        description="Enable local LLM (Ollama/LM Studio) as fallback before OpenRouter",
    )
    local_fallback_priority: bool = Field(
        default=False,
        alias="ARAGORA_LOCAL_FALLBACK_PRIORITY",
        description="Prioritize local LLMs over cloud providers when available",
    )

    # Anthropic server-side refusal fallback (frontier-model-refresh,
    # 2026-09-04): Fable 5.1 / Opus 5 can retry a cyber-classifier refusal
    # against a fallback model server-side when the request carries
    # "fallbacks": "default" and the matching anthropic-beta header. Default
    # on; set ARAGORA_ANTHROPIC_REFUSAL_FALLBACK=false to opt out.
    anthropic_refusal_fallback: bool = Field(
        default=True,
        alias="ARAGORA_ANTHROPIC_REFUSAL_FALLBACK",
        description=(
            "Enable Anthropic server-side refusal fallback (fallbacks: default + "
            "anthropic-beta: server-side-fallback-2026-07-01) for Fable 5.1 / Opus 5"
        ),
    )

    # Default max_tokens cap for a STREAMED Anthropic call (frontier-model-
    # refresh, 2026-09-04). ``generate_stream`` takes no caller max_tokens, so
    # this is the only place that path's output ceiling can be set: the
    # payload gets min(catalog max_output_tokens, this). 64k is the shipped
    # default; lower it to cap per-streamed-call output spend without editing
    # the catalog. Non-streaming keeps its own 16k default.
    anthropic_stream_max_tokens: int = Field(
        default=64_000,
        ge=1,
        alias="ARAGORA_ANTHROPIC_STREAM_MAX_TOKENS",
        description=(
            "Default max_tokens cap for streamed Anthropic calls; the payload uses "
            "min(catalog max_output_tokens, this value)"
        ),
    )

    @property
    def default_agent_list(self) -> list[str]:
        """Get default agents as a list."""
        return [a.strip() for a in self.default_agents.split(",") if a.strip()]

    @property
    def streaming_agent_list(self) -> list[str]:
        """Get streaming-capable agents as a list."""
        return [a.strip() for a in self.streaming_agents.split(",") if a.strip()]


class CacheSettings(BaseSettings):
    """Cache TTL configuration (all values in seconds)."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_CACHE_")

    # Leaderboard & Rankings
    leaderboard: int = Field(default=300, ge=1, alias="ARAGORA_CACHE_LEADERBOARD")
    rankings: int = Field(default=300, ge=1, alias="ARAGORA_CACHE_LB_RANKINGS")
    matches: int = Field(default=120, ge=1, alias="ARAGORA_CACHE_LB_MATCHES")
    reputation: int = Field(default=300, ge=1, alias="ARAGORA_CACHE_LB_REPUTATION")
    recent_matches: int = Field(default=120, ge=1, alias="ARAGORA_CACHE_RECENT_MATCHES")

    # Agent Data
    agent_profile: int = Field(default=600, ge=1, alias="ARAGORA_CACHE_AGENT_PROFILE")
    agent_h2h: int = Field(default=600, ge=1, alias="ARAGORA_CACHE_AGENT_H2H")

    # Analytics
    analytics: int = Field(default=600, ge=1, alias="ARAGORA_CACHE_ANALYTICS")

    # Consensus
    consensus: int = Field(default=240, ge=1, alias="ARAGORA_CACHE_CONSENSUS")

    # Memory & Learning
    replays_list: int = Field(default=120, ge=1, alias="ARAGORA_CACHE_REPLAYS_LIST")

    # Generic tiers
    method_default: int = Field(default=300, ge=1, alias="ARAGORA_CACHE_METHOD")
    query_default: int = Field(default=60, ge=1, alias="ARAGORA_CACHE_QUERY")

    # Embeddings (expensive)
    embeddings: int = Field(default=3600, ge=60, alias="ARAGORA_CACHE_EMBEDDINGS")


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_DB_")

    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0, alias="ARAGORA_DB_TIMEOUT")
    mode: str = Field(default="legacy", alias="ARAGORA_DB_MODE")
    nomic_dir: str = Field(
        default_factory=_default_nomic_dir,
        alias="ARAGORA_DATA_DIR",
        validation_alias=AliasChoices("ARAGORA_DATA_DIR", "ARAGORA_NOMIC_DIR"),
    )

    # PostgreSQL configuration
    url: str | None = Field(default=None, alias="DATABASE_URL")
    backend: str = Field(default="sqlite", alias="ARAGORA_DB_BACKEND")
    # Pool size should accommodate max_concurrent_debates * 2 (read + write)
    # Default: 20 base + 15 overflow = 35 total connections
    pool_size: int = Field(default=20, ge=1, le=100, alias="ARAGORA_DB_POOL_SIZE")
    pool_max_overflow: int = Field(default=15, ge=0, le=100, alias="ARAGORA_DB_POOL_OVERFLOW")
    # Connection timeout (seconds) - how long to wait for a connection from pool
    pool_timeout: float = Field(default=30.0, ge=1.0, le=300.0, alias="ARAGORA_DB_POOL_TIMEOUT")
    # Command timeout (seconds) - max time for any single query
    command_timeout: float = Field(
        default=60.0, ge=1.0, le=600.0, alias="ARAGORA_DB_COMMAND_TIMEOUT"
    )
    # Statement timeout (seconds) - max time before PostgreSQL cancels query
    statement_timeout: int = Field(default=60, ge=1, le=600, alias="ARAGORA_DB_STATEMENT_TIMEOUT")
    # Idle connection recycling (seconds) - recycle connections older than this
    pool_recycle: int = Field(default=1800, ge=60, le=7200, alias="ARAGORA_DB_POOL_RECYCLE")

    # Legacy paths (for backwards compatibility)
    elo_path: str = Field(default="agent_elo.db", alias="ARAGORA_DB_ELO")
    memory_path: str = Field(default="continuum.db", alias="ARAGORA_DB_MEMORY")
    insights_path: str = Field(default="aragora_insights.db", alias="ARAGORA_DB_INSIGHTS")
    consensus_path: str = Field(default="consensus_memory.db", alias="ARAGORA_DB_CONSENSUS")
    personas_path: str = Field(default="agent_personas.db", alias="ARAGORA_DB_PERSONAS")
    positions_path: str = Field(default="grounded_positions.db", alias="ARAGORA_DB_POSITIONS")
    genesis_path: str = Field(default="genesis.db", alias="ARAGORA_DB_GENESIS")

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        valid = {"legacy", "consolidated"}
        if v.lower() not in valid:
            raise ValueError(f"Database mode must be one of {valid}")
        return v.lower()

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, v: str) -> str:
        valid = {"sqlite", "postgresql", "postgres", "supabase", "auto"}
        if v.lower() not in valid:
            raise ValueError(f"Database backend must be one of {valid}")
        return v.lower()

    @property
    def nomic_path(self) -> Path:
        """Get nomic directory as Path."""
        return Path(self.nomic_dir)

    @property
    def is_postgresql(self) -> bool:
        """Check if PostgreSQL backend is configured."""
        return self.backend == "postgresql" and self.url is not None


class SupabaseSettings(BaseSettings):
    """Supabase configuration for preferred persistent storage.

    Supabase is the preferred backend for all persistent data storage.
    When configured, it takes precedence over self-hosted PostgreSQL.

    Environment Variables:
        SUPABASE_URL: Supabase project URL (e.g., https://xxx.supabase.co)
        SUPABASE_KEY: Supabase service role API key
        SUPABASE_DB_PASSWORD: Database password for direct PostgreSQL access
        SUPABASE_POSTGRES_DSN: Explicit PostgreSQL connection string (optional)
    """

    model_config = SettingsConfigDict(env_prefix="SUPABASE_")

    url: str | None = Field(default=None, alias="SUPABASE_URL")
    key: str | None = Field(default=None, alias="SUPABASE_KEY")
    db_password: str | None = Field(default=None, alias="SUPABASE_DB_PASSWORD")
    postgres_dsn: str | None = Field(default=None, alias="SUPABASE_POSTGRES_DSN")

    # Pool settings for Supabase PostgreSQL connections
    pool_size: int = Field(default=10, ge=1, le=50, alias="SUPABASE_POOL_SIZE")
    pool_max_overflow: int = Field(default=5, ge=0, le=20, alias="SUPABASE_POOL_OVERFLOW")

    @property
    def is_configured(self) -> bool:
        """Check if Supabase is properly configured for database access."""
        return bool(self.url and (self.db_password or self.postgres_dsn))

    @property
    def is_api_only(self) -> bool:
        """Check if only API access is configured (no direct DB access)."""
        return bool(self.url and self.key and not self.db_password and not self.postgres_dsn)


class WebSocketSettings(BaseSettings):
    """WebSocket configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_WS_")

    max_message_size: int = Field(
        default=64 * 1024, ge=1024, le=10 * 1024 * 1024, alias="ARAGORA_WS_MAX_MESSAGE_SIZE"
    )
    heartbeat_interval: int = Field(default=30, ge=5, le=300, alias="ARAGORA_WS_HEARTBEAT")


class EloSettings(BaseSettings):
    """ELO rating system configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_ELO_")

    initial_rating: int = Field(default=1500, ge=100, le=3000, alias="ARAGORA_ELO_INITIAL")
    k_factor: int = Field(default=32, ge=1, le=100, alias="ARAGORA_ELO_K_FACTOR")
    calibration_min_count: int = Field(
        default=10, ge=1, le=100, alias="ARAGORA_ELO_CALIBRATION_MIN_COUNT"
    )


class BeliefSettings(BaseSettings):
    """Belief network configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_BELIEF_")

    max_iterations: int = Field(default=100, ge=10, le=1000, alias="ARAGORA_BELIEF_MAX_ITERATIONS")
    convergence_threshold: float = Field(
        default=0.001, ge=0.0001, le=0.1, alias="ARAGORA_BELIEF_CONVERGENCE_THRESHOLD"
    )


class SSLSettings(BaseSettings):
    """SSL/TLS configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_SSL_")

    enabled: bool = Field(default=False, alias="ARAGORA_SSL_ENABLED")
    cert_path: str = Field(default="", alias="ARAGORA_SSL_CERT")
    key_path: str = Field(default="", alias="ARAGORA_SSL_KEY")

    @field_validator("cert_path", "key_path")
    @classmethod
    def validate_ssl_paths(cls, v: str, info: Any) -> str:
        # Only validate if SSL is being enabled
        # Can't check enabled here since it's validated after
        return v


class SecuritySettings(BaseSettings):
    """Security configuration for SOC 2 compliance.

    SOC 2 Controls:
        CC5-01: Enforce MFA for administrative access
        CC6-01: Encryption at rest for sensitive data
    """

    model_config = SettingsConfigDict(env_prefix="ARAGORA_SECURITY_")

    # MFA Enforcement (SOC 2 CC5-01, GitHub #275)
    admin_mfa_required: bool = Field(
        default=True,
        description="Require MFA for admin/owner users (SOC 2 CC5-01)",
        validation_alias=AliasChoices(
            "ARAGORA_ENFORCE_ADMIN_MFA",
            "ARAGORA_SECURITY_ADMIN_MFA_REQUIRED",
        ),
    )
    admin_mfa_grace_period_days: int = Field(
        default=7,
        ge=0,
        le=30,
        description="Grace period (days) for new admins before MFA is enforced",
        validation_alias=AliasChoices(
            "ARAGORA_SECURITY_MFA_GRACE_PERIOD_DAYS",
            "ARAGORA_MFA_GRACE_PERIOD_DAYS",
        ),
    )

    # Encryption at rest (SOC 2 CC6-01)
    encryption_enabled: bool = Field(
        default=True,
        alias="ARAGORA_SECURITY_ENCRYPTION_ENABLED",
        description="Enable encryption at rest for sensitive data",
    )
    key_rotation_interval_days: int = Field(
        default=90,
        ge=30,
        le=365,
        alias="ARAGORA_SECURITY_KEY_ROTATION_DAYS",
        description="Days between automatic key rotations",
    )

    # Session security
    max_session_duration_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        alias="ARAGORA_SECURITY_MAX_SESSION_HOURS",
        description="Maximum session duration before re-authentication",
    )
    session_idle_timeout_minutes: int = Field(
        default=30,
        ge=5,
        le=480,
        alias="ARAGORA_SECURITY_IDLE_TIMEOUT_MINUTES",
        description="Session timeout after inactivity",
    )

    # Password policy
    min_password_length: int = Field(
        default=12,
        ge=8,
        le=128,
        alias="ARAGORA_SECURITY_MIN_PASSWORD_LENGTH",
        description="Minimum password length",
    )
    require_password_complexity: bool = Field(
        default=True,
        alias="ARAGORA_SECURITY_REQUIRE_COMPLEXITY",
        description="Require uppercase, lowercase, number, and special character",
    )


class SSOSettings(BaseSettings):
    """SSO/SAML/OIDC configuration for enterprise authentication."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_SSO_")

    # Enable/disable SSO
    enabled: bool = Field(default=False, alias="ARAGORA_SSO_ENABLED")

    # Provider type: saml, oidc, azure_ad, okta, google
    provider_type: str = Field(default="oidc", alias="ARAGORA_SSO_PROVIDER_TYPE")

    # Common settings
    callback_url: str = Field(default="", alias="ARAGORA_SSO_CALLBACK_URL")
    entity_id: str = Field(default="", alias="ARAGORA_SSO_ENTITY_ID")

    # OIDC settings
    client_id: str = Field(default="", alias="ARAGORA_SSO_CLIENT_ID")
    client_secret: str = Field(default="", alias="ARAGORA_SSO_CLIENT_SECRET")
    issuer_url: str = Field(default="", alias="ARAGORA_SSO_ISSUER_URL")
    authorization_endpoint: str | None = Field(default=None, alias="ARAGORA_SSO_AUTH_ENDPOINT")
    token_endpoint: str | None = Field(default=None, alias="ARAGORA_SSO_TOKEN_ENDPOINT")
    userinfo_endpoint: str | None = Field(default=None, alias="ARAGORA_SSO_USERINFO_ENDPOINT")
    jwks_uri: str | None = Field(default=None, alias="ARAGORA_SSO_JWKS_URI")
    scopes: list[str] = Field(default=["openid", "email", "profile"], alias="ARAGORA_SSO_SCOPES")

    # SAML settings
    idp_entity_id: str = Field(default="", alias="ARAGORA_SSO_IDP_ENTITY_ID")
    idp_sso_url: str = Field(default="", alias="ARAGORA_SSO_IDP_SSO_URL")
    idp_slo_url: str | None = Field(default=None, alias="ARAGORA_SSO_IDP_SLO_URL")
    idp_certificate: str | None = Field(default=None, alias="ARAGORA_SSO_IDP_CERTIFICATE")
    sp_private_key: str | None = Field(default=None, alias="ARAGORA_SSO_SP_PRIVATE_KEY")
    sp_certificate: str | None = Field(default=None, alias="ARAGORA_SSO_SP_CERTIFICATE")

    # Domain restrictions (comma-separated list of allowed email domains)
    allowed_domains_str: str = Field(default="", alias="ARAGORA_SSO_ALLOWED_DOMAINS")

    # Auto-provision users on first login
    auto_provision: bool = Field(default=True, alias="ARAGORA_SSO_AUTO_PROVISION")

    # Session duration in seconds (default: 8 hours)
    session_duration: int = Field(
        default=28800, ge=300, le=604800, alias="ARAGORA_SSO_SESSION_DURATION"
    )

    @field_validator("provider_type")
    @classmethod
    def validate_provider_type(cls, v: str) -> str:
        valid = {"saml", "oidc", "azure_ad", "okta", "google", "github"}
        if v.lower() not in valid:
            raise ValueError(f"SSO provider_type must be one of {valid}")
        return v.lower()

    @field_validator("sp_certificate", "sp_private_key", "idp_certificate")
    @classmethod
    def validate_pem_format(cls, v: str | None) -> str | None:
        """Validate that certificates/keys are in PEM format."""
        if v is None or v == "":
            return v
        # Check for PEM header
        if not v.strip().startswith("-----BEGIN"):
            raise ValueError("Certificate/key must be in PEM format (starting with -----BEGIN...)")
        return v

    @property
    def allowed_domains(self) -> list[str]:
        """Get allowed domains as a list."""
        if not self.allowed_domains_str:
            return []
        return [d.strip().lower() for d in self.allowed_domains_str.split(",") if d.strip()]


class StorageSettings(BaseSettings):
    """Storage configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_")

    storage_dir: str = Field(default=".aragora", alias="ARAGORA_STORAGE_DIR")
    max_log_bytes: int = Field(default=100 * 1024, ge=1024, alias="ARAGORA_MAX_LOG_BYTES")


class EvidenceSettings(BaseSettings):
    """Evidence collection configuration.

    URL Fetching Security:
        By default, URL fetching is restricted to a curated allowlist of trusted
        domains to prevent SSRF attacks. This can be customized:

        - `url_fetch_all_enabled`: When True, allows fetching from ANY URL
          (still blocked: private IPs, localhost, non-HTTP schemes).
          Use only in trusted environments.

        - `additional_allowed_domains`: Extend the default allowlist with
          custom domains (comma-separated).

    Examples:
        # Allow all URLs (trusted environment)
        ARAGORA_URL_FETCH_ALL_ENABLED=true

        # Add custom domains to allowlist
        ARAGORA_URL_ALLOWED_DOMAINS=internal-docs.company.com,wiki.company.com
    """

    model_config = SettingsConfigDict(env_prefix="ARAGORA_")

    max_snippets_per_connector: int = Field(
        default=3, ge=1, le=20, alias="ARAGORA_MAX_SNIPPETS_CONNECTOR"
    )
    max_total_snippets: int = Field(default=8, ge=1, le=50, alias="ARAGORA_MAX_TOTAL_SNIPPETS")
    snippet_max_length: int = Field(
        default=1000, ge=100, le=10000, alias="ARAGORA_SNIPPET_MAX_LENGTH"
    )

    # URL Fetching Security Settings
    url_fetch_all_enabled: bool = Field(
        default=False,
        alias="ARAGORA_URL_FETCH_ALL_ENABLED",
        description="When enabled, allows fetching from any URL (with basic safety checks). "
        "Use only in trusted environments.",
    )
    additional_allowed_domains_str: str = Field(
        default="",
        alias="ARAGORA_URL_ALLOWED_DOMAINS",
        description="Comma-separated list of additional domains to allow for URL fetching.",
    )

    @property
    def additional_allowed_domains(self) -> list[str]:
        """Get additional allowed domains as a list."""
        if not self.additional_allowed_domains_str:
            return []
        return [
            d.strip().lower() for d in self.additional_allowed_domains_str.split(",") if d.strip()
        ]


class FeatureSettings(BaseSettings):
    """Feature flags configuration for gating experimental features."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_FEATURE_")

    # Stable features (enabled by default)
    standard_debates: bool = Field(default=True, alias="ARAGORA_FEATURE_STANDARD_DEBATES")
    fork_visualizer: bool = Field(default=True, alias="ARAGORA_FEATURE_FORK_VISUALIZER")
    plugin_marketplace: bool = Field(default=True, alias="ARAGORA_FEATURE_PLUGIN_MARKETPLACE")
    pulse_scheduler: bool = Field(default=True, alias="ARAGORA_FEATURE_PULSE_SCHEDULER")
    agent_recommender: bool = Field(default=True, alias="ARAGORA_FEATURE_AGENT_RECOMMENDER")

    # Stable features (graduated from beta)
    batch_debates: bool = Field(default=True, alias="ARAGORA_FEATURE_BATCH_DEBATES")
    evidence_explorer: bool = Field(default=True, alias="ARAGORA_FEATURE_EVIDENCE_EXPLORER")
    graph_debates: bool = Field(default=True, alias="ARAGORA_FEATURE_GRAPH_DEBATES")
    matrix_debates: bool = Field(default=True, alias="ARAGORA_FEATURE_MATRIX_DEBATES")
    formal_verification: bool = Field(default=True, alias="ARAGORA_FEATURE_FORMAL_VERIFICATION")
    memory_explorer: bool = Field(default=True, alias="ARAGORA_FEATURE_MEMORY_EXPLORER")
    tournament_mode: bool = Field(default=True, alias="ARAGORA_FEATURE_TOURNAMENT_MODE")

    # Deprecated features
    cli_agents: bool = Field(default=False, alias="ARAGORA_FEATURE_CLI_AGENTS")
    agent_bridge: bool = Field(
        default=False,
        alias="ARAGORA_FEATURE_AGENT_BRIDGE",
        description="Enable the experimental read-only Agent Bridge API and UI surface.",
    )
    agent_bridge_write: bool = Field(
        default=False,
        alias="ARAGORA_FEATURE_AGENT_BRIDGE_WRITE",
        description=(
            "Enable operator-local Agent Bridge write endpoints that can spawn or resume "
            "local model harness processes."
        ),
    )

    # Demo mode - when enabled, endpoints return mock data instead of requiring backend services
    # This is useful for frontend development and demos without full backend setup
    demo_mode: bool = Field(
        default=False,
        alias="ARAGORA_DEMO_MODE",
        description="Enable demo mode with mock data for frontend development and demos",
    )

    def is_enabled(self, feature: str) -> bool:
        """Check if a feature is enabled by name."""
        attr = feature.lower().replace("-", "_")
        return getattr(self, attr, False)


class MemoryTierSettings(BaseSettings):
    """Memory tier configuration for ContinuumMemory."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_MEMORY_")

    # Fast tier (immediate patterns)
    fast_max_items: int = Field(default=1000, ge=100, le=10000, alias="ARAGORA_MEMORY_FAST_MAX")
    fast_half_life_hours: float = Field(
        default=1.0, ge=0.5, le=24.0, alias="ARAGORA_MEMORY_FAST_TTL"
    )

    # Medium tier (tactical learning)
    medium_max_items: int = Field(default=5000, ge=500, le=50000, alias="ARAGORA_MEMORY_MEDIUM_MAX")
    medium_half_life_hours: float = Field(
        default=24.0, ge=1.0, le=168.0, alias="ARAGORA_MEMORY_MEDIUM_TTL"
    )

    # Slow tier (strategic learning)
    slow_max_items: int = Field(default=10000, ge=1000, le=100000, alias="ARAGORA_MEMORY_SLOW_MAX")
    slow_half_life_hours: float = Field(
        default=168.0, ge=24.0, le=720.0, alias="ARAGORA_MEMORY_SLOW_TTL"
    )

    # Glacial tier (foundational knowledge)
    glacial_max_items: int = Field(
        default=50000, ge=5000, le=500000, alias="ARAGORA_MEMORY_GLACIAL_MAX"
    )
    glacial_half_life_hours: float = Field(
        default=720.0, ge=168.0, le=8760.0, alias="ARAGORA_MEMORY_GLACIAL_TTL"
    )

    # Consolidation thresholds
    promotion_cooldown_hours: float = Field(
        default=1.0, ge=0.1, le=24.0, alias="ARAGORA_MEMORY_PROMOTION_COOLDOWN"
    )
    consolidation_threshold: float = Field(
        default=3.0, ge=1.0, le=10.0, alias="ARAGORA_MEMORY_CONSOLIDATION_THRESHOLD"
    )
    retention_multiplier: float = Field(
        default=2.0, ge=1.0, le=5.0, alias="ARAGORA_MEMORY_RETENTION_MULTIPLIER"
    )


class ConsensusSettings(BaseSettings):
    """Consensus detection thresholds."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_CONSENSUS_")

    # Similarity threshold for semantic convergence
    similarity_threshold: float = Field(
        default=0.85, ge=0.5, le=1.0, alias="ARAGORA_CONSENSUS_SIMILARITY"
    )
    # Minimum vote ratio for consensus
    min_vote_ratio: float = Field(default=0.6, ge=0.5, le=1.0, alias="ARAGORA_CONSENSUS_MIN_VOTES")
    # Early exit threshold (high confidence)
    early_exit_threshold: float = Field(
        default=0.95, ge=0.8, le=1.0, alias="ARAGORA_CONSENSUS_EARLY_EXIT"
    )
    # Supermajority threshold
    supermajority_threshold: float = Field(
        default=0.67, ge=0.5, le=1.0, alias="ARAGORA_CONSENSUS_SUPERMAJORITY"
    )


class IntegrationSettings(BaseSettings):
    """Cross-pollination and integration feature configuration."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_INTEGRATION_")

    # RLM Training - collect trajectories from debate outcomes
    rlm_training_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_RLM_TRAINING",
        description="Enable RLM training data collection from debates",
    )

    # Knowledge Mound Integration
    knowledge_mound_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KNOWLEDGE_MOUND",
        description="Enable Knowledge Mound retrieval and ingestion",
    )
    knowledge_ingestion_threshold: float = Field(
        default=0.85,
        ge=0.5,
        le=1.0,
        alias="ARAGORA_INTEGRATION_KNOWLEDGE_THRESHOLD",
        description="Minimum confidence for debate outcome ingestion into Knowledge Mound",
    )

    # Cross-Subscriber Event System
    cross_subscribers_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_CROSS_SUBSCRIBERS",
        description="Enable cross-subsystem event subscribers",
    )
    arena_event_bridge_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_ARENA_BRIDGE",
        description="Enable Arena event bridge to cross-subscribers",
    )

    # Revalidation Scheduler
    auto_revalidation_enabled: bool = Field(
        default=False,
        alias="ARAGORA_INTEGRATION_AUTO_REVALIDATION",
        description="Enable automatic knowledge revalidation via debates",
    )
    revalidation_staleness_threshold: float = Field(
        default=0.7,
        ge=0.1,
        le=1.0,
        alias="ARAGORA_INTEGRATION_REVALIDATION_THRESHOLD",
        description="Staleness threshold to trigger revalidation",
    )
    revalidation_check_interval: int = Field(
        default=3600,
        ge=60,
        le=86400,
        alias="ARAGORA_INTEGRATION_REVALIDATION_INTERVAL",
        description="Revalidation check interval in seconds",
    )

    # Evidence Bridge
    evidence_bridge_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_EVIDENCE_BRIDGE",
        description="Enable evidence-provenance bridge for claim tracking",
    )
    evidence_auto_register: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_EVIDENCE_AUTO_REGISTER",
        description="Automatically register evidence during debates",
    )

    # Vertical tool audit bridge
    vertical_tool_audit_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_VERTICAL_TOOL_AUDIT",
        description="Enable Knowledge Mound ingestion for vertical tool invocations",
    )

    # KM Bidirectional Handler Flags
    # Inbound handlers (subsystem → KM)
    km_memory_to_mound_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_MEMORY_TO_MOUND",
        description="Enable memory → KM handler (stores high-importance memories)",
    )
    km_belief_to_mound_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_BELIEF_TO_MOUND",
        description="Enable belief → KM handler (stores converged beliefs)",
    )
    km_elo_to_mound_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_ELO_TO_MOUND",
        description="Enable ELO → KM handler (stores agent expertise)",
    )
    km_rlm_to_mound_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_RLM_TO_MOUND",
        description="Enable RLM → KM handler (stores compression patterns)",
    )
    km_insight_to_mound_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_INSIGHT_TO_MOUND",
        description="Enable insight → KM handler (stores high-confidence insights)",
    )
    km_flip_to_mound_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_FLIP_TO_MOUND",
        description="Enable flip → KM handler (stores flip events)",
    )
    km_provenance_to_mound_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_PROVENANCE_TO_MOUND",
        description="Enable provenance → KM handler (stores verified chains)",
    )

    # Outbound handlers (KM → subsystem)
    km_mound_to_memory_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_MOUND_TO_MEMORY",
        description="Enable KM → memory handler (pre-warms cache)",
    )
    km_mound_to_belief_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_MOUND_TO_BELIEF",
        description="Enable KM → belief handler (initializes priors)",
    )
    km_mound_to_rlm_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_MOUND_TO_RLM",
        description="Enable KM → RLM handler (updates compression priorities)",
    )
    km_mound_to_team_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_MOUND_TO_TEAM",
        description="Enable KM → team selection handler (queries domain experts)",
    )
    km_mound_to_trickster_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_MOUND_TO_TRICKSTER",
        description="Enable KM → Trickster handler (queries flip history)",
    )
    km_culture_to_debate_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_CULTURE_TO_DEBATE",
        description="Enable culture → debate handler (informs protocol)",
    )
    km_staleness_to_debate_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_STALENESS_TO_DEBATE",
        description="Enable staleness → debate handler (injects warnings)",
    )
    km_mound_to_provenance_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_KM_MOUND_TO_PROVENANCE",
        description="Enable KM → provenance handler (queries verification history)",
    )

    def is_km_handler_enabled(self, handler_name: str) -> bool:
        """Check if a specific KM handler is enabled.

        Args:
            handler_name: The handler name (e.g., 'memory_to_mound', 'mound_to_belief')

        Returns:
            True if the handler is enabled
        """
        attr_name = f"km_{handler_name}_enabled"
        return getattr(self, attr_name, True)

    # Event batching configuration
    event_batch_size: int = Field(
        default=10,
        ge=1,
        le=1000,
        alias="ARAGORA_INTEGRATION_EVENT_BATCH_SIZE",
        description="Number of events to batch before auto-flush (1-1000)",
    )
    event_batch_timeout_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        alias="ARAGORA_INTEGRATION_EVENT_BATCH_TIMEOUT",
        description="Maximum time (seconds) to hold events before flush (0.1-60)",
    )
    event_batching_enabled: bool = Field(
        default=True,
        alias="ARAGORA_INTEGRATION_EVENT_BATCHING",
        description="Enable event batching for high-volume event types",
    )


class ConcurrencySettings(BaseSettings):
    """Debate phase concurrency configuration.

    Controls how many parallel API calls are made during each debate phase.
    Lower values reduce API rate limit pressure; higher values increase speed.

    Environment Variables:
        ARAGORA_MAX_CONCURRENT_PROPOSALS: Max parallel proposal generations
        ARAGORA_MAX_CONCURRENT_CRITIQUES: Max parallel critique generations
        ARAGORA_MAX_CONCURRENT_REVISIONS: Max parallel revision generations
        ARAGORA_MAX_CONCURRENT_STREAMING: Max parallel streaming connections
        ARAGORA_PROPOSAL_STAGGER_SECONDS: Legacy stagger delay (0 = use semaphore)
        ARAGORA_AGENT_TIMEOUT_SECONDS: Timeout per agent call
        ARAGORA_HEARTBEAT_INTERVAL_SECONDS: Heartbeat interval for long operations
    """

    model_config = SettingsConfigDict(env_prefix="ARAGORA_")

    # Phase concurrency limits
    max_concurrent_proposals: int = Field(
        default=10,
        ge=1,
        le=50,
        alias="ARAGORA_MAX_CONCURRENT_PROPOSALS",
        description="Maximum parallel proposal generations",
    )
    max_concurrent_critiques: int = Field(
        default=20,
        ge=1,
        le=100,
        alias="ARAGORA_MAX_CONCURRENT_CRITIQUES",
        description="Maximum parallel critique generations",
    )
    max_concurrent_revisions: int = Field(
        default=10,
        ge=1,
        le=50,
        alias="ARAGORA_MAX_CONCURRENT_REVISIONS",
        description="Maximum parallel revision generations",
    )
    max_concurrent_streaming: int = Field(
        default=3,
        ge=1,
        le=20,
        alias="ARAGORA_MAX_CONCURRENT_STREAMING",
        description="Maximum parallel streaming connections",
    )

    # Timeouts
    agent_timeout_seconds: int = Field(
        default=240,
        ge=30,
        le=1200,
        alias="ARAGORA_AGENT_TIMEOUT",
        description="Timeout per agent call in seconds",
    )
    heartbeat_interval_seconds: int = Field(
        default=15,
        ge=5,
        le=120,
        alias="ARAGORA_HEARTBEAT_INTERVAL",
        description="Heartbeat interval for long operations",
    )

    # Legacy stagger mode (0 = disabled, use semaphore instead)
    proposal_stagger_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=30.0,
        alias="ARAGORA_PROPOSAL_STAGGER_SECONDS",
        description="Legacy stagger delay between proposals (0 = use semaphore)",
    )


class ProviderRateLimitSettings(BaseSettings):
    """Provider-specific rate limits (requests per minute)."""

    model_config = SettingsConfigDict(env_prefix="ARAGORA_PROVIDER_")

    # Rate limits in requests per minute
    anthropic_rpm: int = Field(default=1000, ge=1, le=10000, alias="ARAGORA_PROVIDER_ANTHROPIC_RPM")
    openai_rpm: int = Field(default=500, ge=1, le=10000, alias="ARAGORA_PROVIDER_OPENAI_RPM")
    mistral_rpm: int = Field(default=300, ge=1, le=10000, alias="ARAGORA_PROVIDER_MISTRAL_RPM")
    gemini_rpm: int = Field(default=60, ge=1, le=10000, alias="ARAGORA_PROVIDER_GEMINI_RPM")
    grok_rpm: int = Field(default=500, ge=1, le=10000, alias="ARAGORA_PROVIDER_GROK_RPM")
    deepseek_rpm: int = Field(default=200, ge=1, le=10000, alias="ARAGORA_PROVIDER_DEEPSEEK_RPM")
    openrouter_rpm: int = Field(
        default=500, ge=1, le=10000, alias="ARAGORA_PROVIDER_OPENROUTER_RPM"
    )

    # Tokens per minute (optional, 0 = no limit)
    anthropic_tpm: int = Field(
        default=100000, ge=0, le=1000000, alias="ARAGORA_PROVIDER_ANTHROPIC_TPM"
    )
    openai_tpm: int = Field(default=90000, ge=0, le=1000000, alias="ARAGORA_PROVIDER_OPENAI_TPM")
    mistral_tpm: int = Field(default=50000, ge=0, le=1000000, alias="ARAGORA_PROVIDER_MISTRAL_TPM")
    gemini_tpm: int = Field(default=30000, ge=0, le=1000000, alias="ARAGORA_PROVIDER_GEMINI_TPM")
    grok_tpm: int = Field(default=100000, ge=0, le=1000000, alias="ARAGORA_PROVIDER_GROK_TPM")

    def get_rpm(self, provider: str) -> int:
        """Get RPM limit for a provider."""
        attr = f"{provider.lower().replace('-', '_')}_rpm"
        return getattr(self, attr, 100)

    def get_tpm(self, provider: str) -> int:
        """Get TPM limit for a provider."""
        attr = f"{provider.lower().replace('-', '_')}_tpm"
        return getattr(self, attr, 0)


class Settings(BaseSettings):
    """
    Main settings class aggregating all configuration sections.

    Access nested settings via properties:
        settings = get_settings()
        settings.database.timeout_seconds
        settings.rate_limit.default_limit
        settings.debate.max_rounds
    """

    model_config = SettingsConfigDict(
        env_prefix="ARAGORA_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Nested settings (loaded lazily on first access)
    _auth: AuthSettings | None = None
    _rate_limit: RateLimitSettings | None = None
    _api_limit: APILimitSettings | None = None
    _debate: DebateSettings | None = None
    _logging: LoggingSettings | None = None
    _agent: AgentSettings | None = None
    _cache: CacheSettings | None = None
    _database: DatabaseSettings | None = None
    _websocket: WebSocketSettings | None = None
    _elo: EloSettings | None = None
    _belief: BeliefSettings | None = None
    _ssl: SSLSettings | None = None
    _security: SecuritySettings | None = None
    _storage: StorageSettings | None = None
    _evidence: EvidenceSettings | None = None
    _sso: SSOSettings | None = None
    _features: FeatureSettings | None = None
    _memory_tier: MemoryTierSettings | None = None
    _consensus: ConsensusSettings | None = None
    _provider_rate_limit: ProviderRateLimitSettings | None = None
    _integration: IntegrationSettings | None = None
    _concurrency: ConcurrencySettings | None = None

    @property
    def auth(self) -> AuthSettings:
        if self._auth is None:
            self._auth = AuthSettings()
        return self._auth

    @property
    def rate_limit(self) -> RateLimitSettings:
        if self._rate_limit is None:
            self._rate_limit = RateLimitSettings()
        return self._rate_limit

    @property
    def api_limit(self) -> APILimitSettings:
        if self._api_limit is None:
            self._api_limit = APILimitSettings()
        return self._api_limit

    @property
    def debate(self) -> DebateSettings:
        if self._debate is None:
            self._debate = DebateSettings()
        return self._debate

    @property
    def logging(self) -> LoggingSettings:
        if self._logging is None:
            self._logging = LoggingSettings()
        return self._logging

    @property
    def agent(self) -> AgentSettings:
        if self._agent is None:
            self._agent = AgentSettings()
        return self._agent

    @property
    def cache(self) -> CacheSettings:
        if self._cache is None:
            self._cache = CacheSettings()
        return self._cache

    @property
    def database(self) -> DatabaseSettings:
        if self._database is None:
            self._database = DatabaseSettings()
        return self._database

    @property
    def websocket(self) -> WebSocketSettings:
        if self._websocket is None:
            self._websocket = WebSocketSettings()
        return self._websocket

    @property
    def elo(self) -> EloSettings:
        if self._elo is None:
            self._elo = EloSettings()
        return self._elo

    @property
    def belief(self) -> BeliefSettings:
        if self._belief is None:
            self._belief = BeliefSettings()
        return self._belief

    @property
    def ssl(self) -> SSLSettings:
        if self._ssl is None:
            self._ssl = SSLSettings()
        return self._ssl

    @property
    def security(self) -> SecuritySettings:
        if self._security is None:
            self._security = SecuritySettings()
        return self._security

    @property
    def storage(self) -> StorageSettings:
        if self._storage is None:
            self._storage = StorageSettings()
        return self._storage

    @property
    def evidence(self) -> EvidenceSettings:
        if self._evidence is None:
            self._evidence = EvidenceSettings()
        return self._evidence

    @property
    def sso(self) -> SSOSettings:
        if self._sso is None:
            self._sso = SSOSettings()
        return self._sso

    @property
    def features(self) -> FeatureSettings:
        if self._features is None:
            self._features = FeatureSettings()
        return self._features

    @property
    def memory_tier(self) -> MemoryTierSettings:
        if self._memory_tier is None:
            self._memory_tier = MemoryTierSettings()
        return self._memory_tier

    @property
    def consensus(self) -> ConsensusSettings:
        if self._consensus is None:
            self._consensus = ConsensusSettings()
        return self._consensus

    @property
    def provider_rate_limit(self) -> ProviderRateLimitSettings:
        if self._provider_rate_limit is None:
            self._provider_rate_limit = ProviderRateLimitSettings()
        return self._provider_rate_limit

    @property
    def integration(self) -> IntegrationSettings:
        if self._integration is None:
            self._integration = IntegrationSettings()
        return self._integration

    @property
    def concurrency(self) -> ConcurrencySettings:
        if self._concurrency is None:
            self._concurrency = ConcurrencySettings()
        return self._concurrency


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure the same settings instance is returned
    throughout the application lifecycle.

    Returns:
        Settings instance with all configuration loaded from environment.
    """
    try:
        from aragora.config.secrets import hydrate_env_from_secrets

        # Ensure Secrets Manager values populate env before settings load.
        hydrate_env_from_secrets(overwrite=True)
    except (ImportError, OSError, RuntimeError):
        logging.getLogger(__name__).debug(
            "Secrets hydration unavailable, using env directly", exc_info=True
        )
    return Settings()


def reset_settings() -> None:
    """
    Reset the cached settings instance.

    Useful for testing or when environment variables change.
    """
    get_settings.cache_clear()


# Valid agent types (allowlist for security)
ALLOWED_AGENT_TYPES: frozenset[str] = frozenset(
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
        "mistral-api",
        # API-based (via OpenRouter)
        "deepseek",
        "deepseek-r1",
        "llama",
        "mistral",
        "qwen",
        "qwen-max",
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
