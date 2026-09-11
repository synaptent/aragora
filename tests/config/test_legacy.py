"""Tests for aragora.config.legacy module.

Covers legacy config constants, backward-compatibility mappings,
deprecated database paths, helper functions, and edge cases.
"""

import os
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest


class TestAuthenticationConstants:
    """Test authentication-related configuration constants."""

    def test_token_ttl_default(self):
        """TOKEN_TTL_SECONDS defaults to 3600 (1 hour)."""
        from aragora.config.legacy import TOKEN_TTL_SECONDS

        assert TOKEN_TTL_SECONDS == 3600

    def test_shareable_link_ttl_default(self):
        """SHAREABLE_LINK_TTL defaults to 3600 (1 hour)."""
        from aragora.config.legacy import SHAREABLE_LINK_TTL

        assert SHAREABLE_LINK_TTL == 3600


class TestRateLimitConstants:
    """Test rate limiting configuration constants."""

    def test_default_rate_limit(self):
        """DEFAULT_RATE_LIMIT defaults to 60 requests per minute."""
        from aragora.config.legacy import DEFAULT_RATE_LIMIT

        assert DEFAULT_RATE_LIMIT == 60

    def test_ip_rate_limit(self):
        """IP_RATE_LIMIT defaults to 120."""
        from aragora.config.legacy import IP_RATE_LIMIT

        assert IP_RATE_LIMIT == 120


class TestDebateDefaults:
    """Test debate-related configuration defaults."""

    def test_default_rounds(self):
        """DEFAULT_ROUNDS defaults to 9."""
        from aragora.config.legacy import DEFAULT_ROUNDS

        assert DEFAULT_ROUNDS == 9

    def test_max_rounds(self):
        """MAX_ROUNDS defaults to 12."""
        from aragora.config.legacy import MAX_ROUNDS

        assert MAX_ROUNDS == 12

    def test_default_consensus(self):
        """DEFAULT_CONSENSUS defaults to 'judge'."""
        from aragora.config.legacy import DEFAULT_CONSENSUS

        assert DEFAULT_CONSENSUS == "judge"

    def test_debate_timeout(self):
        """DEBATE_TIMEOUT_SECONDS defaults to 900 (15 minutes)."""
        from aragora.config.legacy import DEBATE_TIMEOUT_SECONDS

        assert DEBATE_TIMEOUT_SECONDS == 900

    def test_agent_timeout(self):
        """AGENT_TIMEOUT_SECONDS defaults to 240 (4 minutes)."""
        from aragora.config.legacy import AGENT_TIMEOUT_SECONDS

        assert AGENT_TIMEOUT_SECONDS == 240


class TestAgentConstants:
    """Test agent-related configuration constants."""

    def test_allowed_agent_types_is_frozenset(self):
        """ALLOWED_AGENT_TYPES should be a frozenset (immutable)."""
        from aragora.config.legacy import ALLOWED_AGENT_TYPES

        assert isinstance(ALLOWED_AGENT_TYPES, frozenset)

    def test_allowed_agent_types_contains_core_agents(self):
        """ALLOWED_AGENT_TYPES includes key agent types."""
        from aragora.config.legacy import ALLOWED_AGENT_TYPES

        expected_agents = {
            "demo",
            "codex",
            "claude",
            "gemini",
            "grok",
            "anthropic-api",
            "openai-api",
            "mistral",
            "deepseek",
        }
        assert expected_agents.issubset(ALLOWED_AGENT_TYPES)

    def test_allowed_agent_types_contains_legacy_agents(self):
        """ALLOWED_AGENT_TYPES includes legacy agent identifiers."""
        from aragora.config.legacy import ALLOWED_AGENT_TYPES

        assert "mistral-api" in ALLOWED_AGENT_TYPES
        assert "codestral" in ALLOWED_AGENT_TYPES

    def test_default_agents_string(self):
        """DEFAULT_AGENTS is a comma-separated string of agent names."""
        from aragora.config.legacy import DEFAULT_AGENTS

        assert isinstance(DEFAULT_AGENTS, str)
        agents = DEFAULT_AGENTS.split(",")
        assert len(agents) >= 2
        assert "anthropic-api" in agents


class TestEloConstants:
    """Test ELO system configuration constants."""

    def test_elo_initial_rating(self):
        """ELO_INITIAL_RATING defaults to 1500."""
        from aragora.config.legacy import ELO_INITIAL_RATING

        assert ELO_INITIAL_RATING == 1500

    def test_elo_k_factor(self):
        """ELO_K_FACTOR defaults to 32."""
        from aragora.config.legacy import ELO_K_FACTOR

        assert ELO_K_FACTOR == 32

    def test_elo_calibration_min_count(self):
        """ELO_CALIBRATION_MIN_COUNT defaults to 10."""
        from aragora.config.legacy import ELO_CALIBRATION_MIN_COUNT

        assert ELO_CALIBRATION_MIN_COUNT == 10


class TestCacheTTLConstants:
    """Test cache TTL configuration constants."""

    def test_cache_ttl_leaderboard(self):
        """CACHE_TTL_LEADERBOARD defaults to 300 (5 min)."""
        from aragora.config.legacy import CACHE_TTL_LEADERBOARD

        assert CACHE_TTL_LEADERBOARD == 300

    def test_cache_ttl_embeddings_is_longest(self):
        """CACHE_TTL_EMBEDDINGS defaults to 3600 (1 hour) - longest TTL."""
        from aragora.config.legacy import CACHE_TTL_EMBEDDINGS

        assert CACHE_TTL_EMBEDDINGS == 3600

    def test_cache_ttl_meta_learning_is_short(self):
        """CACHE_TTL_META_LEARNING defaults to 60 (1 min) - short TTL."""
        from aragora.config.legacy import CACHE_TTL_META_LEARNING

        assert CACHE_TTL_META_LEARNING == 60

    def test_cache_ttl_analytics_memory(self):
        """CACHE_TTL_ANALYTICS_MEMORY defaults to 1800 (30 min)."""
        from aragora.config.legacy import CACHE_TTL_ANALYTICS_MEMORY

        assert CACHE_TTL_ANALYTICS_MEMORY == 1800


class TestLegacyDatabasePaths:
    """Test deprecated database path constants and mappings."""

    def test_db_names_dict_keys(self):
        """DB_NAMES contains expected database identifiers."""
        from aragora.config.legacy import DB_NAMES

        expected_keys = {
            "elo",
            "memory",
            "insights",
            "consensus",
            "calibration",
            "lab",
            "personas",
            "positions",
            "genesis",
            "blacklist",
        }
        assert set(DB_NAMES.keys()) == expected_keys

    def test_db_names_values_end_with_db(self):
        """All DB_NAMES values end with .db extension."""
        from aragora.config.legacy import DB_NAMES

        for key, value in DB_NAMES.items():
            assert value.endswith(".db"), f"DB_NAMES[{key!r}] = {value!r} missing .db extension"

    def test_legacy_db_elo_path_default(self):
        """DB_ELO_PATH defaults to 'agent_elo.db'."""
        from aragora.config.legacy import DB_ELO_PATH

        assert DB_ELO_PATH == "agent_elo.db"

    def test_legacy_db_memory_path_default(self):
        """DB_MEMORY_PATH defaults to 'continuum.db'."""
        from aragora.config.legacy import DB_MEMORY_PATH

        assert DB_MEMORY_PATH == "continuum.db"

    def test_legacy_db_path_defaults_mapping(self):
        """_DB_PATH_DEFAULTS maps constant names to (env_var, default) tuples."""
        from aragora.config.legacy import _DB_PATH_DEFAULTS

        assert "DB_ELO_PATH" in _DB_PATH_DEFAULTS
        env_var, default = _DB_PATH_DEFAULTS["DB_ELO_PATH"]
        assert env_var == "ARAGORA_DB_ELO"
        assert default == "agent_elo.db"

    def test_legacy_db_knowledge_path_is_path_object(self):
        """DB_KNOWLEDGE_PATH is a Path object, not a string."""
        from aragora.config.legacy import DB_KNOWLEDGE_PATH

        assert isinstance(DB_KNOWLEDGE_PATH, Path)


class TestGetApiKey:
    """Test get_api_key helper function."""

    def test_returns_env_value(self):
        """get_api_key returns value from environment variable."""
        from aragora.config.legacy import get_api_key

        with patch.dict(os.environ, {"TEST_API_KEY_LEGACY": "sk-test123"}):
            result = get_api_key("TEST_API_KEY_LEGACY")
            assert result == "sk-test123"

    def test_strips_whitespace(self):
        """get_api_key strips whitespace from values."""
        from aragora.config.legacy import get_api_key

        with patch.dict(os.environ, {"TEST_API_KEY_LEGACY": "  sk-test  "}):
            result = get_api_key("TEST_API_KEY_LEGACY")
            assert result == "sk-test"

    def test_skips_empty_values(self):
        """get_api_key skips empty/whitespace-only values."""
        from aragora.config.legacy import get_api_key

        with patch.dict(os.environ, {"EMPTY_KEY": "   ", "GOOD_KEY": "sk-good"}):
            result = get_api_key("EMPTY_KEY", "GOOD_KEY")
            assert result == "sk-good"

    def test_raises_when_required_and_missing(self):
        """get_api_key raises ValueError when required and not found."""
        from aragora.config.legacy import get_api_key

        env_clean = {
            k: v for k, v in os.environ.items() if k not in ("MISSING_KEY_A", "MISSING_KEY_B")
        }
        with patch.dict(os.environ, env_clean, clear=True):
            with pytest.raises(ValueError, match="MISSING_KEY_A or MISSING_KEY_B"):
                get_api_key("MISSING_KEY_A", "MISSING_KEY_B")

    def test_returns_none_when_not_required(self):
        """get_api_key returns None when not required and not found."""
        from aragora.config.legacy import get_api_key

        env_clean = {k: v for k, v in os.environ.items() if k != "OPTIONAL_MISSING_KEY"}
        with patch.dict(os.environ, env_clean, clear=True):
            result = get_api_key("OPTIONAL_MISSING_KEY", required=False)
            assert result is None

    def test_first_valid_key_wins(self):
        """get_api_key returns the first valid key when multiple provided."""
        from aragora.config.legacy import get_api_key

        with patch.dict(
            os.environ,
            {
                "FIRST_KEY_LEGACY": "first-value",
                "SECOND_KEY_LEGACY": "second-value",
            },
        ):
            result = get_api_key("FIRST_KEY_LEGACY", "SECOND_KEY_LEGACY")
            assert result == "first-value"

    def test_optional_probe_returns_mounted_key(self, tmp_path):
        from aragora.config.legacy import get_api_key
        from aragora.config.secrets import SecretManager, SecretsConfig

        secret_path = tmp_path / "OPENROUTER_API_KEY"
        secret_path.write_text("mounted-openrouter-key", encoding="utf-8")
        secret_path.chmod(0o600)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=True),
        ):
            assert get_api_key("OPENROUTER_API_KEY", required=False) == "mounted-openrouter-key"

    def test_required_alias_lookup_skips_missing_first_name(self, tmp_path):
        from aragora.config.legacy import get_api_key
        from aragora.config.secrets import SecretManager, SecretsConfig

        secret_path = tmp_path / "GOOGLE_API_KEY"
        secret_path.write_text("mounted-google-key", encoding="utf-8")
        secret_path.chmod(0o600)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=True),
        ):
            assert get_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY") == "mounted-google-key"

    def test_optional_probe_propagates_unsafe_mount(self):
        from aragora.config.legacy import get_api_key
        from aragora.config.secrets import SecretManager, SecretSourceError, SecretsConfig

        manager = SecretManager(SecretsConfig(secrets_dir="relative/secrets"))
        with patch("aragora.config.secrets._manager", manager):
            with pytest.raises(SecretSourceError):
                get_api_key("OPENROUTER_API_KEY", required=False)

    def test_required_strict_block_preserves_secret_error_contract(self):
        from aragora.config.legacy import get_api_key
        from aragora.config.secrets import SecretNotFoundError

        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", "OPENROUTER_API_KEY": "blocked-key"},
            clear=True,
        ):
            with pytest.raises(SecretNotFoundError):
                get_api_key("OPENROUTER_API_KEY")

    def test_strict_required_alias_uses_later_mounted_key(self, tmp_path):
        from aragora.config.legacy import get_api_key
        from aragora.config.secrets import SecretManager, SecretsConfig

        secret_path = tmp_path / "GOOGLE_API_KEY"
        secret_path.write_text("mounted-key", encoding="utf-8")
        secret_path.chmod(0o600)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(
                os.environ,
                {"ARAGORA_ENV": "production", "GEMINI_API_KEY": "blocked-key"},
                clear=True,
            ),
        ):
            assert get_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY") == "mounted-key"

    def test_optional_non_strict_probe_does_not_warn_for_env_key(self, caplog):
        from aragora.config.legacy import get_api_key

        with patch.dict(
            os.environ,
            {"ARAGORA_SECRETS_STRICT": "false", "OPENROUTER_API_KEY": "env-key"},
            clear=True,
        ):
            assert get_api_key("OPENROUTER_API_KEY", required=False) == "env-key"
        assert "Critical secret 'OPENROUTER_API_KEY' loaded" not in caplog.text

    def test_required_env_presence_falls_back_when_managed_getter_returns_none(self):
        from aragora.config.legacy import get_api_key

        with (
            patch.dict(
                os.environ,
                {"ARAGORA_SECRETS_STRICT": "false", "OPENAI_API_KEY": "env-key"},
                clear=True,
            ),
            patch("aragora.config.secrets.get_secret", return_value=None),
        ):
            assert get_api_key("OPENAI_API_KEY") == "env-key"

    def test_required_non_strict_env_key_keeps_security_warning(self, caplog):
        from aragora.config.legacy import get_api_key

        with patch.dict(
            os.environ,
            {"ARAGORA_SECRETS_STRICT": "false", "OPENROUTER_API_KEY": "env-key"},
            clear=True,
        ):
            assert get_api_key("OPENROUTER_API_KEY") == "env-key"
        assert "Critical secret 'OPENROUTER_API_KEY' loaded" in caplog.text

    def test_required_strict_missing_critical_key_raises_secret_error(self):
        from aragora.config.legacy import get_api_key
        from aragora.config.secrets import SecretNotFoundError

        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=True):
            with pytest.raises(SecretNotFoundError):
                get_api_key("OPENROUTER_API_KEY")


class TestValidateDbPath:
    """Test validate_db_path security function."""

    def test_valid_path_within_base(self):
        """validate_db_path accepts paths within base directory."""
        from aragora.config.legacy import validate_db_path

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            result = validate_db_path("test.db", base_dir=base)
            assert result == (base / "test.db").resolve()

    def test_rejects_path_traversal(self):
        """validate_db_path rejects path traversal attempts."""
        from aragora.config.legacy import validate_db_path, ConfigurationError

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "subdir"
            base.mkdir()
            with pytest.raises(ConfigurationError, match="escapes data directory"):
                validate_db_path("../../etc/passwd", base_dir=base)


class TestResolveDbPath:
    """Test resolve_db_path function."""

    def test_memory_path_preserved(self):
        """resolve_db_path preserves ':memory:' SQLite path."""
        from aragora.config.legacy import resolve_db_path

        assert resolve_db_path(":memory:") == ":memory:"

    def test_file_uri_preserved(self):
        """resolve_db_path preserves 'file:...' SQLite URI paths."""
        from aragora.config.legacy import resolve_db_path

        assert resolve_db_path("file:test.db?mode=memory") == "file:test.db?mode=memory"

    def test_absolute_path_returned_as_is(self):
        """resolve_db_path returns absolute paths unchanged."""
        from aragora.config.legacy import resolve_db_path

        abs_path = "/tmp/test.db"
        assert resolve_db_path(abs_path) == abs_path

    def test_bare_filename_rooted_under_data_dir(self, tmp_path, monkeypatch):
        """Bare filenames should be rooted under DATA_DIR."""
        from aragora.config import legacy as legacy

        monkeypatch.setattr(legacy, "get_default_data_dir", lambda: tmp_path)
        resolved = Path(legacy.resolve_db_path("example.db"))
        assert resolved.resolve() == (tmp_path / "example.db").resolve()

    def test_subpath_rooted_under_data_dir(self, tmp_path, monkeypatch):
        """Relative subpaths should stay under DATA_DIR."""
        from aragora.config import legacy as legacy

        monkeypatch.setattr(legacy, "get_default_data_dir", lambda: tmp_path)
        resolved = Path(legacy.resolve_db_path("data/example.db"))
        assert resolved.resolve() == (tmp_path / "data" / "example.db").resolve()


class TestConfigurationError:
    """Test ConfigurationError exception class."""

    def test_is_exception(self):
        """ConfigurationError is a proper Exception subclass."""
        from aragora.config.legacy import ConfigurationError

        assert issubclass(ConfigurationError, Exception)

    def test_can_be_raised_and_caught(self):
        """ConfigurationError can be raised with a message."""
        from aragora.config.legacy import ConfigurationError

        with pytest.raises(ConfigurationError, match="test error"):
            raise ConfigurationError("test error")


class TestValidateConfiguration:
    """Test validate_configuration function."""

    def test_returns_dict_with_expected_keys(self):
        """validate_configuration returns dict with valid, errors, warnings, config_summary."""
        from aragora.config.legacy import validate_configuration

        result = validate_configuration()
        assert "valid" in result
        assert "errors" in result
        assert "warnings" in result
        assert "config_summary" in result

    def test_config_summary_has_expected_fields(self):
        """Config summary includes key configuration values."""
        from aragora.config.legacy import validate_configuration

        result = validate_configuration()
        summary = result["config_summary"]
        assert "rate_limit" in summary
        assert "debate_timeout" in summary
        assert "max_rounds" in summary
        assert "ssl_enabled" in summary
        assert "api_providers" in summary


class TestDatabaseConstants:
    """Test database-related constants."""

    def test_db_timeout_default(self):
        """DB_TIMEOUT_SECONDS defaults to 30.0."""
        from aragora.config.legacy import DB_TIMEOUT_SECONDS

        assert DB_TIMEOUT_SECONDS == 30.0

    def test_db_mode_default(self):
        """DB_MODE defaults to 'consolidated'."""
        from aragora.config.legacy import DB_MODE

        assert DB_MODE == "consolidated"


class TestWebSocketConstants:
    """Test WebSocket configuration constants."""

    def test_ws_max_message_size(self):
        """WS_MAX_MESSAGE_SIZE defaults to 64KB."""
        from aragora.config.legacy import WS_MAX_MESSAGE_SIZE

        assert WS_MAX_MESSAGE_SIZE == 64 * 1024

    def test_ws_heartbeat_interval(self):
        """WS_HEARTBEAT_INTERVAL defaults to 30 seconds."""
        from aragora.config.legacy import WS_HEARTBEAT_INTERVAL

        assert WS_HEARTBEAT_INTERVAL == 30


class TestSSLConstants:
    """Test SSL/TLS configuration constants."""

    def test_ssl_disabled_by_default(self):
        """SSL_ENABLED defaults to False."""
        from aragora.config.legacy import SSL_ENABLED

        assert SSL_ENABLED is False


class TestModuleExports:
    """Test that __all__ exports are accessible."""

    def test_all_exports_importable(self):
        """Every name in __all__ should be importable from the module."""
        import aragora.config.legacy as legacy_mod

        for name in legacy_mod.__all__:
            assert hasattr(legacy_mod, name), f"{name} listed in __all__ but not found in module"
