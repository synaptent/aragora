"""Comprehensive tests for aragora.config.settings module.

Tests all 18+ Pydantic Settings classes, default values, validators,
environment variable overrides, computed properties, and caching behavior.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from aragora.config.settings import (
    ALLOWED_AGENT_TYPES,
    AgentSettings,
    APILimitSettings,
    AuthSettings,
    BeliefSettings,
    CacheSettings,
    ConcurrencySettings,
    ConsensusSettings,
    DatabaseSettings,
    DebateSettings,
    EloSettings,
    EvidenceSettings,
    FeatureSettings,
    IntegrationSettings,
    LoggingSettings,
    MemoryTierSettings,
    ProviderRateLimitSettings,
    RateLimitSettings,
    SecuritySettings,
    Settings,
    SSOSettings,
    SSLSettings,
    StorageSettings,
    SupabaseSettings,
    WebSocketSettings,
    get_settings,
    reset_settings,
)


# ---------------------------------------------------------------------------
# Helper: build a clean env dict that strips all ARAGORA_* and SUPABASE_* keys
# so that the real environment does not pollute tests.
# ---------------------------------------------------------------------------


def _clean_env() -> dict[str, str]:
    """Return a copy of os.environ with all ARAGORA_/SUPABASE_/DATABASE_ keys removed."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("ARAGORA_")
        and not k.startswith("SUPABASE_")
        and not k.startswith("DATABASE_")
    }


# ===== AuthSettings =====


class TestAuthSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = AuthSettings()
        assert s.token_ttl == 3600
        assert s.shareable_link_ttl == 3600
        assert s.max_tracked_entries == 10000
        assert s.max_revoked_tokens == 10000
        assert s.revoked_token_ttl == 86400
        assert s.rate_limit_window == 60

    def test_env_override(self):
        env = {**_clean_env(), "ARAGORA_TOKEN_TTL": "120"}
        with patch.dict(os.environ, env, clear=True):
            s = AuthSettings()
        assert s.token_ttl == 120

    def test_token_ttl_below_minimum(self):
        env = {**_clean_env(), "ARAGORA_TOKEN_TTL": "10"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError):
                AuthSettings()


# ===== RateLimitSettings =====


class TestRateLimitSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = RateLimitSettings()
        assert s.default_limit == 60
        assert s.ip_rate_limit == 120
        assert s.burst_multiplier == 2.0
        assert s.redis_url is None
        assert s.redis_key_prefix == "aragora:ratelimit:"
        assert s.redis_ttl_seconds == 120

    def test_env_override(self):
        env = {**_clean_env(), "ARAGORA_RATE_LIMIT": "200", "ARAGORA_BURST_MULTIPLIER": "3.5"}
        with patch.dict(os.environ, env, clear=True):
            s = RateLimitSettings()
        assert s.default_limit == 200
        assert s.burst_multiplier == 3.5


# ===== APILimitSettings =====


class TestAPILimitSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = APILimitSettings()
        assert s.max_api_limit == 100
        assert s.default_pagination == 20
        assert s.max_content_length == 100 * 1024 * 1024
        assert s.max_question_length == 10000


# ===== DebateSettings =====


class TestDebateSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = DebateSettings()
        assert s.default_rounds == 9
        assert s.max_rounds == 12
        assert s.default_consensus == "judge"
        assert s.timeout_seconds == 600
        assert s.max_agents_per_debate == 20
        assert s.max_concurrent_debates == 10
        assert s.user_event_queue_size == 10000

    def test_consensus_validator_valid(self):
        env = {**_clean_env(), "ARAGORA_DEFAULT_CONSENSUS": "Majority"}
        with patch.dict(os.environ, env, clear=True):
            s = DebateSettings()
        assert s.default_consensus == "majority"

    def test_consensus_validator_all_valid_values(self):
        for value in ("unanimous", "majority", "supermajority", "hybrid", "judge"):
            env = {**_clean_env(), "ARAGORA_DEFAULT_CONSENSUS": value}
            with patch.dict(os.environ, env, clear=True):
                s = DebateSettings()
            assert s.default_consensus == value

    def test_consensus_validator_invalid(self):
        env = {**_clean_env(), "ARAGORA_DEFAULT_CONSENSUS": "random"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="Consensus must be one of"):
                DebateSettings()


# ===== LoggingSettings =====


class TestLoggingSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = LoggingSettings()
        assert s.level == "INFO"
        assert s.format == "json"
        assert s.file == ""
        assert s.max_bytes == 10 * 1024 * 1024
        assert s.backup_count == 5
        assert s.include_source_location is False

    def test_level_validator_normalises_case(self):
        env = {**_clean_env(), "ARAGORA_LOG_LEVEL": "debug"}
        with patch.dict(os.environ, env, clear=True):
            s = LoggingSettings()
        assert s.level == "DEBUG"

    def test_level_validator_invalid(self):
        env = {**_clean_env(), "ARAGORA_LOG_LEVEL": "TRACE"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="Log level must be one of"):
                LoggingSettings()

    def test_format_validator_normalises_case(self):
        env = {**_clean_env(), "ARAGORA_LOG_FORMAT": "TEXT"}
        with patch.dict(os.environ, env, clear=True):
            s = LoggingSettings()
        assert s.format == "text"

    def test_format_validator_invalid(self):
        env = {**_clean_env(), "ARAGORA_LOG_FORMAT": "yaml"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="Log format must be one of"):
                LoggingSettings()

    def test_get_sensitive_fields(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = LoggingSettings()
        fields = s.get_sensitive_fields()
        assert "password" in fields
        assert "api_key" in fields
        assert len(fields) == 7


# ===== AgentSettings =====


class TestAgentSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = AgentSettings()
        assert "grok" in s.default_agents
        assert s.openrouter_fallback_enabled is True
        assert s.local_fallback_enabled is False
        assert s.stream_buffer_size == 10 * 1024 * 1024
        assert s.stream_chunk_timeout == 180.0

    def test_default_agent_list_property(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = AgentSettings()
        agents = s.default_agent_list
        assert isinstance(agents, list)
        assert "grok" in agents
        assert "anthropic-api" in agents

    def test_streaming_agent_list_property(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = AgentSettings()
        agents = s.streaming_agent_list
        assert "mistral" in agents


# ===== CacheSettings =====


class TestCacheSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = CacheSettings()
        assert s.leaderboard == 300
        assert s.rankings == 300
        assert s.embeddings == 3600
        assert s.query_default == 60


# ===== DatabaseSettings =====


class TestDatabaseSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = DatabaseSettings()
        assert s.timeout_seconds == 30.0
        assert s.mode == "legacy"
        assert s.backend == "sqlite"
        assert s.url is None
        assert s.pool_size == 20

    def test_mode_validator_normalises(self):
        env = {**_clean_env(), "ARAGORA_DB_MODE": "CONSOLIDATED"}
        with patch.dict(os.environ, env, clear=True):
            s = DatabaseSettings()
        assert s.mode == "consolidated"

    def test_mode_validator_invalid(self):
        env = {**_clean_env(), "ARAGORA_DB_MODE": "sharded"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="Database mode must be one of"):
                DatabaseSettings()

    def test_backend_validator_valid(self):
        for backend in ("sqlite", "postgresql", "supabase", "auto"):
            env = {**_clean_env(), "ARAGORA_DB_BACKEND": backend}
            with patch.dict(os.environ, env, clear=True):
                s = DatabaseSettings()
            assert s.backend == backend

    @pytest.mark.parametrize("spelling", ["postgres", "postgresql", "POSTGRES", "PostgreSQL"])
    def test_backend_validator_normalises_postgres_alias(self, spelling):
        env = {**_clean_env(), "ARAGORA_DB_BACKEND": spelling}
        with patch.dict(os.environ, env, clear=True):
            s = DatabaseSettings()
        assert s.backend == "postgresql"

    def test_backend_validator_invalid(self):
        env = {**_clean_env(), "ARAGORA_DB_BACKEND": "mysql"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="Database backend must be one of"):
                DatabaseSettings()

    def test_nomic_path_property(self, tmp_path, monkeypatch):
        with patch.dict(os.environ, _clean_env(), clear=True):
            monkeypatch.chdir(tmp_path)
            s = DatabaseSettings()
        assert s.nomic_path == Path(".nomic")

    @pytest.mark.parametrize("spelling", ["postgres", "postgresql"])
    def test_is_postgresql_property(self, spelling):
        env = {
            **_clean_env(),
            "ARAGORA_DB_BACKEND": spelling,
            "DATABASE_URL": "postgresql://localhost/test",
        }
        with patch.dict(os.environ, env, clear=True):
            s = DatabaseSettings()
        assert s.is_postgresql is True

    @pytest.mark.parametrize("spelling", ["postgres", "postgresql"])
    def test_is_postgresql_false_without_url(self, spelling):
        env = {**_clean_env(), "ARAGORA_DB_BACKEND": spelling}
        with patch.dict(os.environ, env, clear=True):
            s = DatabaseSettings()
        assert s.is_postgresql is False

    def test_is_postgresql_false_for_sqlite_with_url(self):
        env = {
            **_clean_env(),
            "ARAGORA_DB_BACKEND": "sqlite",
            "DATABASE_URL": "postgresql://localhost/test",
        }
        with patch.dict(os.environ, env, clear=True):
            s = DatabaseSettings()
        assert s.backend == "sqlite"
        assert s.is_postgresql is False


# ===== SupabaseSettings =====


class TestSupabaseSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = SupabaseSettings()
        assert s.url is None
        assert s.key is None
        assert s.pool_size == 10
        assert s.is_configured is False

    def test_is_configured(self):
        env = {
            **_clean_env(),
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_DB_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=True):
            s = SupabaseSettings()
        assert s.is_configured is True

    def test_is_api_only(self):
        env = {
            **_clean_env(),
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_KEY": "key123",
        }
        with patch.dict(os.environ, env, clear=True):
            s = SupabaseSettings()
        assert s.is_api_only is True
        assert s.is_configured is False


# ===== WebSocketSettings =====


class TestWebSocketSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = WebSocketSettings()
        assert s.max_message_size == 64 * 1024
        assert s.heartbeat_interval == 30


# ===== EloSettings =====


class TestEloSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = EloSettings()
        assert s.initial_rating == 1500
        assert s.k_factor == 32
        assert s.calibration_min_count == 10


# ===== BeliefSettings =====


class TestBeliefSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = BeliefSettings()
        assert s.max_iterations == 100
        assert s.convergence_threshold == 0.001


# ===== SSLSettings =====


class TestSSLSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = SSLSettings()
        assert s.enabled is False
        assert s.cert_path == ""
        assert s.key_path == ""


# ===== SecuritySettings =====


class TestSecuritySettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = SecuritySettings()
        assert s.admin_mfa_required is True
        assert s.admin_mfa_grace_period_days == 7
        assert s.encryption_enabled is True
        assert s.key_rotation_interval_days == 90
        assert s.max_session_duration_hours == 24
        assert s.session_idle_timeout_minutes == 30
        assert s.min_password_length == 12
        assert s.require_password_complexity is True

    def test_env_override(self):
        env = {**_clean_env(), "ARAGORA_SECURITY_MIN_PASSWORD_LENGTH": "16"}
        with patch.dict(os.environ, env, clear=True):
            s = SecuritySettings()
        assert s.min_password_length == 16


# ===== SSOSettings =====


class TestSSOSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = SSOSettings()
        assert s.enabled is False
        assert s.provider_type == "oidc"
        assert s.auto_provision is True
        assert s.session_duration == 28800
        assert s.scopes == ["openid", "email", "profile"]

    def test_provider_type_validator_valid(self):
        for pt in ("saml", "oidc", "azure_ad", "okta", "google", "github"):
            env = {**_clean_env(), "ARAGORA_SSO_PROVIDER_TYPE": pt}
            with patch.dict(os.environ, env, clear=True):
                s = SSOSettings()
            assert s.provider_type == pt

    def test_provider_type_validator_invalid(self):
        env = {**_clean_env(), "ARAGORA_SSO_PROVIDER_TYPE": "facebook"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="SSO provider_type must be one of"):
                SSOSettings()

    def test_pem_validator_valid(self):
        pem = "-----BEGIN CERTIFICATE-----\ndata\n-----END CERTIFICATE-----"
        env = {**_clean_env(), "ARAGORA_SSO_IDP_CERTIFICATE": pem}
        with patch.dict(os.environ, env, clear=True):
            s = SSOSettings()
        assert s.idp_certificate == pem

    def test_pem_validator_invalid(self):
        env = {**_clean_env(), "ARAGORA_SSO_IDP_CERTIFICATE": "not-a-pem"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="PEM format"):
                SSOSettings()

    def test_allowed_domains_property(self):
        env = {**_clean_env(), "ARAGORA_SSO_ALLOWED_DOMAINS": "example.com, test.org"}
        with patch.dict(os.environ, env, clear=True):
            s = SSOSettings()
        assert s.allowed_domains == ["example.com", "test.org"]

    def test_allowed_domains_empty(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = SSOSettings()
        assert s.allowed_domains == []


# ===== StorageSettings =====


class TestStorageSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = StorageSettings()
        assert s.storage_dir == ".aragora"
        assert s.max_log_bytes == 100 * 1024


# ===== EvidenceSettings =====


class TestEvidenceSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = EvidenceSettings()
        assert s.max_snippets_per_connector == 3
        assert s.max_total_snippets == 8
        assert s.url_fetch_all_enabled is False

    def test_additional_allowed_domains(self):
        env = {**_clean_env(), "ARAGORA_URL_ALLOWED_DOMAINS": "foo.com, bar.org"}
        with patch.dict(os.environ, env, clear=True):
            s = EvidenceSettings()
        assert s.additional_allowed_domains == ["foo.com", "bar.org"]


# ===== FeatureSettings =====


class TestFeatureSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = FeatureSettings()
        assert s.standard_debates is True
        assert s.agent_bridge is False
        assert s.cli_agents is False  # deprecated

    def test_agent_bridge_env_override(self):
        env = {**_clean_env(), "ARAGORA_FEATURE_AGENT_BRIDGE": "true"}
        with patch.dict(os.environ, env, clear=True):
            s = FeatureSettings()
        assert s.agent_bridge is True

    def test_is_enabled(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = FeatureSettings()
        assert s.is_enabled("standard_debates") is True
        assert s.is_enabled("agent_bridge") is False
        assert s.is_enabled("cli_agents") is False
        assert s.is_enabled("nonexistent-feature") is False


# ===== MemoryTierSettings =====


class TestMemoryTierSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = MemoryTierSettings()
        assert s.fast_max_items == 1000
        assert s.medium_max_items == 5000
        assert s.slow_max_items == 10000
        assert s.glacial_max_items == 50000
        assert s.promotion_cooldown_hours == 1.0
        assert s.consolidation_threshold == 3.0
        assert s.retention_multiplier == 2.0


# ===== ConsensusSettings =====


class TestConsensusSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = ConsensusSettings()
        assert s.similarity_threshold == 0.85
        assert s.min_vote_ratio == 0.6
        assert s.early_exit_threshold == 0.95
        assert s.supermajority_threshold == 0.67


# ===== IntegrationSettings =====


class TestIntegrationSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = IntegrationSettings()
        assert s.rlm_training_enabled is True
        assert s.knowledge_mound_enabled is True
        assert s.auto_revalidation_enabled is False
        assert s.event_batch_size == 10

    def test_is_km_handler_enabled(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = IntegrationSettings()
        assert s.is_km_handler_enabled("memory_to_mound") is True
        assert s.is_km_handler_enabled("mound_to_belief") is True
        # Unknown handler defaults to True
        assert s.is_km_handler_enabled("nonexistent") is True


# ===== ConcurrencySettings =====


class TestConcurrencySettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = ConcurrencySettings()
        assert s.max_concurrent_proposals == 10
        assert s.max_concurrent_critiques == 20
        assert s.max_concurrent_revisions == 10
        assert s.max_concurrent_streaming == 3
        assert s.agent_timeout_seconds == 240
        assert s.heartbeat_interval_seconds == 15
        assert s.proposal_stagger_seconds == 0.0


# ===== ProviderRateLimitSettings =====


class TestProviderRateLimitSettings:
    def test_defaults(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = ProviderRateLimitSettings()
        assert s.anthropic_rpm == 1000
        assert s.openai_rpm == 500
        assert s.gemini_rpm == 60

    def test_get_rpm(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = ProviderRateLimitSettings()
        assert s.get_rpm("anthropic") == 1000
        assert s.get_rpm("openai") == 500
        # Unknown provider returns default 100
        assert s.get_rpm("unknown") == 100

    def test_get_tpm(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = ProviderRateLimitSettings()
        assert s.get_tpm("anthropic") == 100000
        assert s.get_tpm("unknown") == 0


# ===== Main Settings (aggregator) =====


class TestSettings:
    def test_lazy_properties(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = Settings()
        # Each property should return the correct type
        assert isinstance(s.auth, AuthSettings)
        assert isinstance(s.rate_limit, RateLimitSettings)
        assert isinstance(s.api_limit, APILimitSettings)
        assert isinstance(s.debate, DebateSettings)
        assert isinstance(s.logging, LoggingSettings)
        assert isinstance(s.agent, AgentSettings)
        assert isinstance(s.cache, CacheSettings)
        assert isinstance(s.database, DatabaseSettings)
        assert isinstance(s.websocket, WebSocketSettings)
        assert isinstance(s.elo, EloSettings)
        assert isinstance(s.belief, BeliefSettings)
        assert isinstance(s.ssl, SSLSettings)
        assert isinstance(s.security, SecuritySettings)
        assert isinstance(s.storage, StorageSettings)
        assert isinstance(s.evidence, EvidenceSettings)
        assert isinstance(s.sso, SSOSettings)
        assert isinstance(s.features, FeatureSettings)
        assert isinstance(s.memory_tier, MemoryTierSettings)
        assert isinstance(s.consensus, ConsensusSettings)
        assert isinstance(s.provider_rate_limit, ProviderRateLimitSettings)
        assert isinstance(s.integration, IntegrationSettings)
        assert isinstance(s.concurrency, ConcurrencySettings)

    def test_lazy_caching(self):
        """The same sub-settings instance should be returned on repeated access."""
        with patch.dict(os.environ, _clean_env(), clear=True):
            s = Settings()
        assert s.auth is s.auth
        assert s.debate is s.debate


# ===== get_settings / reset_settings =====


class TestGetSettings:
    def test_caching(self):
        reset_settings()
        with patch.dict(os.environ, _clean_env(), clear=True):
            s1 = get_settings()
            s2 = get_settings()
        assert s1 is s2
        reset_settings()

    def test_reset_clears_cache(self):
        reset_settings()
        with patch.dict(os.environ, _clean_env(), clear=True):
            s1 = get_settings()
        reset_settings()
        with patch.dict(os.environ, _clean_env(), clear=True):
            s2 = get_settings()
        assert s1 is not s2
        reset_settings()


# ===== ALLOWED_AGENT_TYPES =====


class TestAllowedAgentTypes:
    def test_is_frozenset(self):
        assert isinstance(ALLOWED_AGENT_TYPES, frozenset)

    def test_contains_core_agents(self):
        for agent in ("claude", "grok", "anthropic-api", "openai-api", "deepseek", "mistral"):
            assert agent in ALLOWED_AGENT_TYPES
