"""
Tests for production storage guards.

Tests cover:
- StorageMode and EnvironmentMode enums
- StorageGuardConfig dataclass
- Environment detection
- Storage mode detection
- Distributed store requirement enforcement
- Store config validation
"""

from __future__ import annotations

import dataclasses
import os
from unittest.mock import patch

import pytest

from aragora.storage.production_guards import (
    StorageMode,
    EnvironmentMode,
    StorageGuardConfig,
    DistributedStateError,
    get_config,
    get_environment,
    is_production_mode,
    get_storage_mode,
    require_distributed_store,
    validate_store_config,
)


# =============================================================================
# StorageMode Enum Tests
# =============================================================================


class TestStorageMode:
    """Tests for StorageMode enum."""

    def test_supabase_value(self):
        """Should have supabase value."""
        assert StorageMode.SUPABASE.value == "supabase"

    def test_postgres_value(self):
        """Should have postgres value."""
        assert StorageMode.POSTGRES.value == "postgres"

    def test_redis_value(self):
        """Should have redis value."""
        assert StorageMode.REDIS.value == "redis"

    def test_sqlite_value(self):
        """Should have sqlite value."""
        assert StorageMode.SQLITE.value == "sqlite"

    def test_file_value(self):
        """Should have file value."""
        assert StorageMode.FILE.value == "file"

    def test_memory_value(self):
        """Should have memory value."""
        assert StorageMode.MEMORY.value == "memory"

    def test_value_access(self):
        """Should have accessible value."""
        assert StorageMode.POSTGRES.value == "postgres"


# =============================================================================
# EnvironmentMode Enum Tests
# =============================================================================


class TestEnvironmentMode:
    """Tests for EnvironmentMode enum."""

    def test_production_value(self):
        """Should have production value."""
        assert EnvironmentMode.PRODUCTION.value == "production"

    def test_staging_value(self):
        """Should have staging value."""
        assert EnvironmentMode.STAGING.value == "staging"

    def test_development_value(self):
        """Should have development value."""
        assert EnvironmentMode.DEVELOPMENT.value == "development"

    def test_test_value(self):
        """Should have test value."""
        assert EnvironmentMode.TEST.value == "test"


# =============================================================================
# StorageGuardConfig Tests
# =============================================================================


class TestStorageGuardConfig:
    """Tests for StorageGuardConfig dataclass."""

    def test_default_require_distributed(self):
        """Should default require_distributed to True."""
        config = StorageGuardConfig()
        assert config.require_distributed is True

    def test_default_allowed_fallback_envs(self):
        """Should default to dev and test environments."""
        config = StorageGuardConfig()
        assert EnvironmentMode.DEVELOPMENT in config.allowed_fallback_envs
        assert EnvironmentMode.TEST in config.allowed_fallback_envs
        assert EnvironmentMode.PRODUCTION not in config.allowed_fallback_envs

    def test_default_fail_open_stores(self):
        """Should include cache, session, and workflow stores."""
        config = StorageGuardConfig()
        assert "cache_store" in config.fail_open_stores
        assert "session_store" in config.fail_open_stores
        assert "workflow_store" in config.fail_open_stores

    def test_custom_allowed_fallback_envs(self):
        """Should accept custom allowed_fallback_envs."""
        config = StorageGuardConfig(allowed_fallback_envs={EnvironmentMode.STAGING})
        assert EnvironmentMode.STAGING in config.allowed_fallback_envs
        assert EnvironmentMode.DEVELOPMENT not in config.allowed_fallback_envs

    def test_custom_fail_open_stores(self):
        """Should accept custom fail_open_stores."""
        config = StorageGuardConfig(fail_open_stores={"custom_store"})
        assert "custom_store" in config.fail_open_stores
        assert "cache_store" not in config.fail_open_stores

    def test_set_fields_declare_default_factories(self):
        """Set fields should use real default factories instead of a None default."""
        fields = {f.name: f for f in dataclasses.fields(StorageGuardConfig)}
        for name in ("allowed_fallback_envs", "fail_open_stores"):
            assert fields[name].default is dataclasses.MISSING
            assert fields[name].default_factory is not dataclasses.MISSING

    def test_default_sets_have_exact_contents(self):
        """Defaults should be exactly dev/test envs and the three fail-open stores."""
        config = StorageGuardConfig()
        assert config.allowed_fallback_envs == {
            EnvironmentMode.DEVELOPMENT,
            EnvironmentMode.TEST,
        }
        assert config.fail_open_stores == {"cache_store", "session_store", "workflow_store"}

    def test_default_sets_are_independent_per_instance(self):
        """Mutating one instance's defaults must not leak into other instances."""
        first = StorageGuardConfig()
        second = StorageGuardConfig()
        assert first.allowed_fallback_envs is not second.allowed_fallback_envs
        assert first.fail_open_stores is not second.fail_open_stores

        first.allowed_fallback_envs.add(EnvironmentMode.PRODUCTION)
        first.fail_open_stores.add("critical_store")

        assert EnvironmentMode.PRODUCTION not in second.allowed_fallback_envs
        assert "critical_store" not in second.fail_open_stores
        fresh = StorageGuardConfig()
        assert EnvironmentMode.PRODUCTION not in fresh.allowed_fallback_envs
        assert "critical_store" not in fresh.fail_open_stores

    def test_explicit_sets_are_kept_as_given(self):
        """Caller-provided sets, including empty ones, should be stored unchanged."""
        envs = {EnvironmentMode.STAGING}
        stores: set[str] = set()
        config = StorageGuardConfig(
            require_distributed=False,
            allowed_fallback_envs=envs,
            fail_open_stores=stores,
        )
        assert config.require_distributed is False
        assert config.allowed_fallback_envs is envs
        assert config.fail_open_stores is stores
        assert config.fail_open_stores == set()


# =============================================================================
# get_environment Tests
# =============================================================================


class TestGetEnvironment:
    """Tests for get_environment function."""

    def test_production_env(self):
        """Should detect production environment."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=False):
            assert get_environment() == EnvironmentMode.PRODUCTION

    def test_prod_alias(self):
        """Should detect prod as production."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "prod"}, clear=False):
            assert get_environment() == EnvironmentMode.PRODUCTION

    def test_staging_env(self):
        """Should detect staging environment."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "staging"}, clear=False):
            assert get_environment() == EnvironmentMode.STAGING

    def test_stage_alias(self):
        """Should detect stage as staging."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "stage"}, clear=False):
            assert get_environment() == EnvironmentMode.STAGING

    def test_development_env(self):
        """Should detect development environment."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "development"}, clear=False):
            assert get_environment() == EnvironmentMode.DEVELOPMENT

    def test_dev_alias(self):
        """Should detect dev as development."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "dev"}, clear=False):
            assert get_environment() == EnvironmentMode.DEVELOPMENT

    def test_test_env(self):
        """Should detect test environment."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "test"}, clear=False):
            assert get_environment() == EnvironmentMode.TEST

    def test_testing_alias(self):
        """Should detect testing as test."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "testing"}, clear=False):
            assert get_environment() == EnvironmentMode.TEST

    def test_default_to_development(self):
        """Should default to development."""
        env = os.environ.copy()
        env.pop("ARAGORA_ENV", None)
        with patch.dict(os.environ, env, clear=True):
            assert get_environment() == EnvironmentMode.DEVELOPMENT

    def test_unknown_env_treated_as_development(self):
        """Should treat unknown env as development."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "unknown"}, clear=False):
            assert get_environment() == EnvironmentMode.DEVELOPMENT

    def test_case_insensitive(self):
        """Should be case insensitive."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "PRODUCTION"}, clear=False):
            assert get_environment() == EnvironmentMode.PRODUCTION


# =============================================================================
# is_production_mode Tests
# =============================================================================


class TestIsProductionMode:
    """Tests for is_production_mode function."""

    def test_production_is_production_mode(self):
        """Should return True for production."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=False):
            assert is_production_mode() is True

    def test_staging_is_production_mode(self):
        """Should return True for staging."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "staging"}, clear=False):
            assert is_production_mode() is True

    def test_development_is_not_production_mode(self):
        """Should return False for development."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "development"}, clear=False):
            assert is_production_mode() is False

    def test_test_is_not_production_mode(self):
        """Should return False for test."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "test"}, clear=False):
            assert is_production_mode() is False


# =============================================================================
# get_storage_mode Tests
# =============================================================================


class TestGetStorageMode:
    """Tests for get_storage_mode function."""

    def test_returns_none_when_not_set(self):
        """Should return None when not configured."""
        env = os.environ.copy()
        env.pop("ARAGORA_STORAGE_MODE", None)
        with patch.dict(os.environ, env, clear=True):
            assert get_storage_mode() is None

    def test_returns_postgres_mode(self):
        """Should return postgres mode."""
        with patch.dict(os.environ, {"ARAGORA_STORAGE_MODE": "postgres"}, clear=False):
            assert get_storage_mode() == StorageMode.POSTGRES

    def test_returns_supabase_mode(self):
        """Should return supabase mode."""
        with patch.dict(os.environ, {"ARAGORA_STORAGE_MODE": "supabase"}, clear=False):
            assert get_storage_mode() == StorageMode.SUPABASE

    def test_returns_redis_mode(self):
        """Should return redis mode."""
        with patch.dict(os.environ, {"ARAGORA_STORAGE_MODE": "redis"}, clear=False):
            assert get_storage_mode() == StorageMode.REDIS

    def test_returns_sqlite_mode(self):
        """Should return sqlite mode."""
        with patch.dict(os.environ, {"ARAGORA_STORAGE_MODE": "sqlite"}, clear=False):
            assert get_storage_mode() == StorageMode.SQLITE

    def test_case_insensitive(self):
        """Should be case insensitive."""
        with patch.dict(os.environ, {"ARAGORA_STORAGE_MODE": "POSTGRES"}, clear=False):
            assert get_storage_mode() == StorageMode.POSTGRES

    def test_returns_none_for_invalid(self):
        """Should return None for invalid mode."""
        with patch.dict(os.environ, {"ARAGORA_STORAGE_MODE": "invalid"}, clear=False):
            assert get_storage_mode() is None


# =============================================================================
# DistributedStateError Tests
# =============================================================================


class TestDistributedStateError:
    """Tests for DistributedStateError exception."""

    def test_error_message(self):
        """Should include store name and reason in message."""
        error = DistributedStateError("my_store", "PostgreSQL unavailable")
        assert "my_store" in str(error)
        assert "PostgreSQL unavailable" in str(error)

    def test_error_attributes(self):
        """Should store attributes."""
        error = DistributedStateError("my_store", "reason")
        assert error.store_name == "my_store"
        assert error.reason == "reason"

    def test_includes_env_var_hint(self):
        """Should include env var hint in message."""
        error = DistributedStateError("my_store", "reason")
        assert "ARAGORA_REQUIRE_DISTRIBUTED" in str(error)


# =============================================================================
# require_distributed_store Tests
# =============================================================================


class TestRequireDistributedStore:
    """Tests for require_distributed_store function."""

    def test_allows_fallback_in_development(self):
        """Should allow fallback in development."""
        # Clear cached config
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_ENV": "development"}, clear=False):
            # Should not raise
            require_distributed_store("test_store", StorageMode.SQLITE)

    def test_allows_fallback_in_test(self):
        """Should allow fallback in test environment."""
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_ENV": "test"}, clear=False):
            # Should not raise
            require_distributed_store("test_store", StorageMode.SQLITE)

    def test_allows_fail_open_stores_in_production(self):
        """Should allow fail-open stores in production."""
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=False):
            # Should not raise for cache_store
            require_distributed_store("cache_store", StorageMode.SQLITE)

    def test_raises_for_sqlite_in_production(self):
        """Should raise for SQLite in production."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": "production",
            "ARAGORA_REQUIRE_DISTRIBUTED": "true",
            "PYTEST_CURRENT_TEST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(DistributedStateError) as exc_info:
                require_distributed_store("critical_store", StorageMode.SQLITE, "test reason")
            assert exc_info.value.store_name == "critical_store"

    def test_raises_for_file_in_production(self):
        """Should raise for file storage in production."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": "production",
            "ARAGORA_REQUIRE_DISTRIBUTED": "true",
            "PYTEST_CURRENT_TEST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(DistributedStateError):
                require_distributed_store("test_store", StorageMode.FILE)

    def test_raises_for_memory_in_production(self):
        """Should raise for memory storage in production."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": "production",
            "ARAGORA_REQUIRE_DISTRIBUTED": "true",
            "PYTEST_CURRENT_TEST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(DistributedStateError):
                require_distributed_store("test_store", StorageMode.MEMORY)

    @pytest.mark.parametrize("env_name", ["development", "test"])
    def test_default_config_allows_fallback_without_pytest_override(self, env_name):
        """Default allowed envs should permit local fallback on their own."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": env_name,
            "ARAGORA_REQUIRE_DISTRIBUTED": "true",
            "PYTEST_CURRENT_TEST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            require_distributed_store("critical_store", StorageMode.SQLITE)

    def test_default_config_rejects_fallback_in_staging(self):
        """Staging is not a default fallback environment."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": "staging",
            "ARAGORA_REQUIRE_DISTRIBUTED": "true",
            "PYTEST_CURRENT_TEST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(DistributedStateError):
                require_distributed_store("critical_store", StorageMode.SQLITE)

    @pytest.mark.parametrize("store_name", ["cache_store", "session_store", "workflow_store"])
    def test_default_fail_open_stores_allowed_in_production(self, store_name):
        """Default fail-open stores should fall back in production without the pytest override."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": "production",
            "ARAGORA_REQUIRE_DISTRIBUTED": "true",
            "PYTEST_CURRENT_TEST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            require_distributed_store(store_name, StorageMode.SQLITE)

    def test_mutated_standalone_config_does_not_relax_global_guard(self):
        """Mutating a separate config instance must not change the global decision."""
        import aragora.storage.production_guards as guards

        guards._config = None
        standalone = StorageGuardConfig()
        standalone.allowed_fallback_envs.add(EnvironmentMode.PRODUCTION)
        standalone.fail_open_stores.add("critical_store")

        env = {
            "ARAGORA_ENV": "production",
            "ARAGORA_REQUIRE_DISTRIBUTED": "true",
            "PYTEST_CURRENT_TEST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(DistributedStateError):
                require_distributed_store("critical_store", StorageMode.SQLITE)

    def test_allows_postgres_in_production(self):
        """Should allow PostgreSQL in production."""
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=False):
            # Should not raise
            require_distributed_store("test_store", StorageMode.POSTGRES)

    def test_allows_supabase_in_production(self):
        """Should allow Supabase in production."""
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=False):
            # Should not raise
            require_distributed_store("test_store", StorageMode.SUPABASE)

    def test_allows_redis_in_production(self):
        """Should allow Redis in production."""
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=False):
            # Should not raise
            require_distributed_store("test_store", StorageMode.REDIS)

    def test_respects_require_distributed_false(self):
        """Should allow fallback when REQUIRE_DISTRIBUTED=false."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": "production",
            "ARAGORA_REQUIRE_DISTRIBUTED": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            # Should not raise even in production
            require_distributed_store("test_store", StorageMode.SQLITE)

    def test_respects_legacy_env_var(self):
        """Should respect legacy ARAGORA_REQUIRE_DISTRIBUTED_STATE."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": "production",
            "ARAGORA_REQUIRE_DISTRIBUTED_STATE": "false",
        }
        # Remove the new var if present
        env_clean = {k: v for k, v in os.environ.items() if k != "ARAGORA_REQUIRE_DISTRIBUTED"}
        env_clean.update(env)

        with patch.dict(os.environ, env_clean, clear=True):
            # Should not raise
            require_distributed_store("test_store", StorageMode.SQLITE)


# =============================================================================
# validate_store_config Tests
# =============================================================================


class TestValidateStoreConfig:
    """Tests for validate_store_config function."""

    def test_prefers_supabase(self):
        """Should prefer Supabase when available."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {"ARAGORA_ENV": "development"}
        with patch.dict(os.environ, env, clear=False):
            mode = validate_store_config(
                "test_store",
                supabase_dsn="postgresql://supabase",
                postgres_url="postgresql://other",
            )
            assert mode == StorageMode.SUPABASE

    def test_falls_back_to_postgres(self):
        """Should fall back to PostgreSQL."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {"ARAGORA_ENV": "development"}
        with patch.dict(os.environ, env, clear=False):
            mode = validate_store_config(
                "test_store",
                postgres_url="postgresql://localhost",
            )
            assert mode == StorageMode.POSTGRES

    def test_falls_back_to_redis(self):
        """Should fall back to Redis."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {"ARAGORA_ENV": "development"}
        with patch.dict(os.environ, env, clear=False):
            mode = validate_store_config(
                "test_store",
                redis_url="redis://localhost",
            )
            assert mode == StorageMode.REDIS

    def test_falls_back_to_sqlite_in_development(self):
        """Should fall back to SQLite in development."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {"ARAGORA_ENV": "development"}
        with patch.dict(os.environ, env, clear=False):
            mode = validate_store_config("test_store")
            assert mode == StorageMode.SQLITE

    def test_raises_in_production_without_distributed(self):
        """Should raise in production without distributed backend."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": "production",
            "ARAGORA_REQUIRE_DISTRIBUTED": "true",
            "PYTEST_CURRENT_TEST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(DistributedStateError):
                validate_store_config("critical_store")

    def test_respects_explicit_mode(self):
        """Should respect explicitly configured mode."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": "development",
            "ARAGORA_STORAGE_MODE": "redis",
        }
        with patch.dict(os.environ, env, clear=False):
            mode = validate_store_config(
                "test_store",
                supabase_dsn="postgresql://supabase",  # Would normally be preferred
            )
            assert mode == StorageMode.REDIS

    def test_custom_fallback_mode(self):
        """Should use custom fallback mode."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {"ARAGORA_ENV": "development"}
        with patch.dict(os.environ, env, clear=False):
            mode = validate_store_config(
                "test_store",
                fallback_mode=StorageMode.FILE,
            )
            assert mode == StorageMode.FILE


# =============================================================================
# get_config Tests
# =============================================================================


class TestGetConfig:
    """Tests for get_config function."""

    def test_returns_config(self):
        """Should return StorageGuardConfig."""
        import aragora.storage.production_guards as guards

        guards._config = None

        config = get_config()
        assert isinstance(config, StorageGuardConfig)

    def test_caches_config(self):
        """Should cache config singleton."""
        import aragora.storage.production_guards as guards

        guards._config = None

        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_reads_require_distributed_true(self):
        """Should read ARAGORA_REQUIRE_DISTRIBUTED=true."""
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_REQUIRE_DISTRIBUTED": "true"}, clear=False):
            config = get_config()
            assert config.require_distributed is True

    def test_reads_require_distributed_false(self):
        """Should read ARAGORA_REQUIRE_DISTRIBUTED=false."""
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_REQUIRE_DISTRIBUTED": "false"}, clear=False):
            config = get_config()
            assert config.require_distributed is False

    def test_accepts_1_as_true(self):
        """Should accept '1' as true."""
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_REQUIRE_DISTRIBUTED": "1"}, clear=False):
            config = get_config()
            assert config.require_distributed is True

    def test_accepts_yes_as_true(self):
        """Should accept 'yes' as true."""
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_REQUIRE_DISTRIBUTED": "yes"}, clear=False):
            config = get_config()
            assert config.require_distributed is True


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_env_vars(self):
        """Should handle empty env vars."""
        import aragora.storage.production_guards as guards

        guards._config = None

        env = {
            "ARAGORA_ENV": "",
            "ARAGORA_STORAGE_MODE": "",
        }
        with patch.dict(os.environ, env, clear=False):
            env_mode = get_environment()
            storage_mode = get_storage_mode()
            # Empty string treated as development
            assert env_mode == EnvironmentMode.DEVELOPMENT
            assert storage_mode is None

    def test_whitespace_handling(self):
        """Should handle whitespace in env vars."""
        import aragora.storage.production_guards as guards

        guards._config = None

        with patch.dict(os.environ, {"ARAGORA_ENV": " production "}, clear=False):
            # Note: Current implementation doesn't strip whitespace
            # This tests current behavior
            env = get_environment()
            # " production " != "production", so treated as unknown -> development
            assert env == EnvironmentMode.DEVELOPMENT
