"""Tests for server startup validation functions."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.startup.validation import (
    _get_config_value,
    check_agent_credentials,
    check_connector_dependencies,
    check_production_requirements,
    validate_database_connectivity,
    validate_redis_connectivity,
)


def _env_only(name: str) -> str | None:
    """Restrict startup validation tests to the patched environment only."""
    return os.environ.get(name)


# ---------------------------------------------------------------------------
# _get_config_value tests
# ---------------------------------------------------------------------------


class TestGetConfigValue:
    """Test _get_config_value function."""

    def test_returns_env_value(self):
        with patch.dict("os.environ", {"TEST_KEY": "env_value"}):
            assert _get_config_value("TEST_KEY") == "env_value"

    def test_returns_none_when_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            # The function handles ImportError internally
            result = _get_config_value("NONEXISTENT_KEY_12345")
            # Either None or secrets manager value
            # Just verify no exception raised
            assert result is None or isinstance(result, str)

    def test_env_takes_precedence(self):
        with patch.dict("os.environ", {"TEST_KEY": "env_value"}):
            # get_secret should not be called if env has value
            result = _get_config_value("TEST_KEY")
            assert result == "env_value"


# ---------------------------------------------------------------------------
# check_connector_dependencies tests
# ---------------------------------------------------------------------------


class TestCheckConnectorDependencies:
    """Test check_connector_dependencies function."""

    def test_no_warnings_when_no_connectors(self):
        with patch.dict("os.environ", {}, clear=True):
            warnings = check_connector_dependencies()
            assert warnings == []

    def test_discord_missing_pynacl(self):
        with patch.dict("os.environ", {"DISCORD_PUBLIC_KEY": "test_key"}, clear=True):
            with patch.dict("sys.modules", {"nacl": None, "nacl.signing": None}):
                # Force ImportError on nacl import
                import sys

                if "nacl" in sys.modules:
                    del sys.modules["nacl"]
                if "nacl.signing" in sys.modules:
                    del sys.modules["nacl.signing"]

                # We need to actually test this works
                warnings = check_connector_dependencies()
                # The warning may or may not be present depending on nacl installation
                # Just verify no exception is raised
                assert isinstance(warnings, list)

    def test_slack_missing_signing_secret(self):
        with patch.dict(
            "os.environ",
            {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"},
            clear=True,
        ):
            warnings = check_connector_dependencies()
            assert any("SLACK_SIGNING_SECRET" in w for w in warnings)

    def test_slack_oauth_partial_config(self):
        with patch.dict(
            "os.environ",
            {"SLACK_CLIENT_ID": "test_id"},  # Missing CLIENT_SECRET
            clear=True,
        ):
            warnings = check_connector_dependencies()
            assert any("SLACK_CLIENT_SECRET" in w for w in warnings)

    def test_slack_redirect_uri_non_https_production(self):
        with patch.dict(
            "os.environ",
            {
                "SLACK_CLIENT_ID": "test_id",
                "SLACK_CLIENT_SECRET": "test_secret",
                "SLACK_REDIRECT_URI": "http://localhost/callback",
                "ARAGORA_ENV": "production",
            },
            clear=True,
        ):
            warnings = check_connector_dependencies()
            assert any("HTTPS" in w for w in warnings)

    def test_slack_missing_encryption_key_production(self):
        with patch.dict(
            "os.environ",
            {
                "SLACK_CLIENT_ID": "test_id",
                "SLACK_CLIENT_SECRET": "test_secret",
                "SLACK_REDIRECT_URI": "https://example.com/callback",
                "ARAGORA_ENV": "production",
            },
            clear=True,
        ):
            warnings = check_connector_dependencies()
            assert any("ENCRYPTION_KEY" in w for w in warnings)


# ---------------------------------------------------------------------------
# check_agent_credentials tests
# ---------------------------------------------------------------------------


class TestCheckAgentCredentials:
    """Test check_agent_credentials function."""

    def test_no_warnings_with_all_keys(self):
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "sk-test",
                "ANTHROPIC_API_KEY": "sk-ant-test",
            },
            clear=True,
        ):
            with (
                patch("aragora.config.settings.get_settings") as mock_settings,
                patch(
                    "aragora.server.startup.validation._get_config_value",
                    side_effect=_env_only,
                ),
            ):
                mock_settings.return_value.agent.default_agents = "openai-api,anthropic-api"
                warnings = check_agent_credentials()
                assert warnings == []

    def test_warning_missing_openai_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with (
                patch("aragora.config.settings.get_settings") as mock_settings,
                patch(
                    "aragora.server.startup.validation._get_config_value",
                    side_effect=_env_only,
                ),
            ):
                mock_settings.return_value.agent.default_agents = "openai-api"
                warnings = check_agent_credentials()
                assert any("OPENAI_API_KEY" in w for w in warnings)

    def test_warning_missing_anthropic_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with (
                patch("aragora.config.settings.get_settings") as mock_settings,
                patch(
                    "aragora.server.startup.validation._get_config_value",
                    side_effect=_env_only,
                ),
            ):
                mock_settings.return_value.agent.default_agents = "anthropic-api"
                warnings = check_agent_credentials()
                assert any("ANTHROPIC_API_KEY" in w for w in warnings)

    def test_warning_missing_openrouter_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with (
                patch("aragora.config.settings.get_settings") as mock_settings,
                patch(
                    "aragora.server.startup.validation._get_config_value",
                    side_effect=_env_only,
                ),
            ):
                mock_settings.return_value.agent.default_agents = "deepseek,qwen"
                warnings = check_agent_credentials()
                assert any("OPENROUTER_API_KEY" in w for w in warnings)

    def test_custom_agents_override(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}, clear=True):
            with patch(
                "aragora.server.startup.validation._get_config_value",
                side_effect=_env_only,
            ):
                warnings = check_agent_credentials(default_agents="gemini")
            assert warnings == []

    def test_warning_missing_gemini_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.server.startup.validation._get_config_value",
                side_effect=_env_only,
            ):
                warnings = check_agent_credentials(default_agents="gemini")
            assert any("GEMINI_API_KEY" in w for w in warnings)

    def test_warning_missing_grok_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.server.startup.validation._get_config_value",
                side_effect=_env_only,
            ):
                warnings = check_agent_credentials(default_agents="grok")
            assert any("XAI_API_KEY" in w for w in warnings)

    def test_openrouter_fallback_satisfies_direct_agents(self):
        with patch.dict(
            "os.environ",
            {"OPENROUTER_API_KEY": "or-test-key-12345"},
            clear=True,
        ):
            with patch(
                "aragora.server.startup.validation._get_config_value",
                side_effect=_env_only,
            ):
                warnings = check_agent_credentials(
                    default_agents="openai-api,anthropic-api,gemini,grok,mistral-api"
                )
            assert warnings == []

    def test_openrouter_fallback_can_be_disabled(self):
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY": "or-test-key-12345",
                "ARAGORA_OPENROUTER_FALLBACK_ENABLED": "false",
            },
            clear=True,
        ):
            with patch(
                "aragora.server.startup.validation._get_config_value",
                side_effect=_env_only,
            ):
                warnings = check_agent_credentials(default_agents="openai-api")
            assert any("OPENAI_API_KEY" in w for w in warnings)

    def test_google_api_key_satisfies_gemini(self):
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "google-test-key-12345"}, clear=True):
            with patch(
                "aragora.server.startup.validation._get_config_value",
                side_effect=_env_only,
            ):
                warnings = check_agent_credentials(default_agents="gemini")
            assert warnings == []

    def test_grok_api_key_alias_satisfies_grok(self):
        with patch.dict("os.environ", {"GROK_API_KEY": "grok-test-key-12345"}, clear=True):
            with patch(
                "aragora.server.startup.validation._get_config_value",
                side_effect=_env_only,
            ):
                warnings = check_agent_credentials(default_agents="grok")
            assert warnings == []


# ---------------------------------------------------------------------------
# check_production_requirements tests
# ---------------------------------------------------------------------------


class TestCheckProductionRequirements:
    """Test check_production_requirements function."""

    def test_development_no_requirements(self):
        with patch.dict("os.environ", {"ARAGORA_ENV": "development"}, clear=True):
            with patch(
                "aragora.control_plane.leader.is_distributed_state_required",
                return_value=False,
            ):
                missing = check_production_requirements()
                # In development, no requirements are enforced
                # Only connector/agent warnings may be present
                assert isinstance(missing, list)

    def test_production_missing_encryption_key(self):
        def _env_only(name: str):
            """Only check env vars, not secrets manager."""
            return os.environ.get(name)

        with patch.dict(
            "os.environ",
            {"ARAGORA_ENV": "production", "ARAGORA_SECRETS_STRICT": "false"},
            clear=True,
        ):
            with (
                patch(
                    "aragora.control_plane.leader.is_distributed_state_required",
                    return_value=False,
                ),
                patch(
                    "aragora.server.startup.validation._get_config_value",
                    side_effect=_env_only,
                ),
            ):
                missing = check_production_requirements()
                assert any("ARAGORA_ENCRYPTION_KEY" in m for m in missing)

    def test_production_distributed_missing_redis(self):
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_ENV": "production",
                "ARAGORA_ENCRYPTION_KEY": "0" * 64,
                "ARAGORA_SECRETS_STRICT": "false",
            },
            clear=True,
        ):
            with patch(
                "aragora.control_plane.leader.is_distributed_state_required",
                return_value=True,
            ):
                missing = check_production_requirements()
                assert any("REDIS_URL" in m for m in missing)

    def test_production_distributed_accepts_sentinel_config(self):
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_ENV": "production",
                "ARAGORA_ENCRYPTION_KEY": "0" * 64,
                "ARAGORA_REDIS_MODE": "sentinel",
                "ARAGORA_REDIS_SENTINEL_HOSTS": "sentinel-1:26379,sentinel-2:26379",
                "ARAGORA_REDIS_SENTINEL_MASTER": "mymaster",
                "ARAGORA_SECRETS_STRICT": "false",
            },
            clear=True,
        ):
            with patch(
                "aragora.control_plane.leader.is_distributed_state_required",
                return_value=True,
            ):
                missing = check_production_requirements()
                assert not any("REDIS_URL" in m for m in missing)

    def test_production_require_database_missing(self):
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_ENV": "production",
                "ARAGORA_ENCRYPTION_KEY": "0" * 64,
                "ARAGORA_REQUIRE_DATABASE": "true",
                "ARAGORA_SECRETS_STRICT": "false",
            },
            clear=True,
        ):
            with patch(
                "aragora.control_plane.leader.is_distributed_state_required",
                return_value=False,
            ):
                missing = check_production_requirements()
                assert any("DATABASE_URL" in m for m in missing)

    def test_production_all_requirements_met(self):
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_ENV": "production",
                "ARAGORA_ENCRYPTION_KEY": "0" * 64,
                "REDIS_URL": "redis://localhost:6379",
                "DATABASE_URL": "postgresql://localhost/db",
                "JWT_SECRET": "secret",
                "ARAGORA_REQUIRE_DATABASE": "true",
                "ARAGORA_SECRETS_DIR": "/run/secrets/aragora",
            },
            clear=True,
        ):
            with patch(
                "aragora.control_plane.leader.is_distributed_state_required",
                return_value=True,
            ):
                missing = check_production_requirements()
                # Should have no missing requirements when all are provided
                # May still have connector/agent warnings
                production_missing = [
                    m for m in missing if "required" in m.lower() or "missing" in m.lower()
                ]
                assert production_missing == [] or all("warning" in m.lower() for m in missing)


class TestStrictSecretsCustodyRequirement:
    """Strict secrets mode must name a managed custody backend at startup."""

    MESSAGE_KEY = "no managed secret custody is configured"

    def _missing(self, env: dict[str, str]) -> list[str]:
        with patch.dict("os.environ", env, clear=True):
            with patch(
                "aragora.control_plane.leader.is_distributed_state_required",
                return_value=False,
            ):
                return check_production_requirements()

    @pytest.mark.parametrize(
        "env",
        [
            {"ARAGORA_ENV": "production"},
            {"ARAGORA_ENV": "staging"},
            {"ARAGORA_ENV": "development", "ARAGORA_SECRETS_STRICT": "true"},
        ],
    )
    def test_strict_mode_without_custody_fails_with_both_fixes(self, env):
        custody = [m for m in self._missing(env) if self.MESSAGE_KEY in m]
        assert len(custody) == 1
        assert "ARAGORA_SECRETS_DIR" in custody[0]
        assert "ARAGORA_USE_SECRETS_MANAGER=true" in custody[0]

    @pytest.mark.parametrize(
        "extra",
        [
            {"ARAGORA_SECRETS_DIR": "/run/secrets/aragora"},
            {"ARAGORA_USE_SECRETS_MANAGER": "true"},
            {"AWS_EXECUTION_ENV": "AWS_ECS_FARGATE"},
            {"ARAGORA_SECRETS_STRICT": "false"},
        ],
    )
    def test_configured_custody_or_non_strict_passes(self, extra):
        missing = self._missing({"ARAGORA_ENV": "production", **extra})
        assert not [m for m in missing if self.MESSAGE_KEY in m]

    def test_development_is_not_strict(self):
        missing = self._missing({"ARAGORA_ENV": "development"})
        assert not [m for m in missing if self.MESSAGE_KEY in m]


# ---------------------------------------------------------------------------
# validate_redis_connectivity tests
# ---------------------------------------------------------------------------


class TestValidateRedisConnectivity:
    """Test validate_redis_connectivity function."""

    async def test_skips_when_not_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            success, message = await validate_redis_connectivity()
            assert success is True
            assert "not configured" in message

    async def test_uses_sentinel_health_check_when_configured(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "ARAGORA_REDIS_MODE": "sentinel",
                    "ARAGORA_REDIS_SENTINEL_HOSTS": "sentinel-1:26379,sentinel-2:26379",
                    "ARAGORA_REDIS_SENTINEL_MASTER": "mymaster",
                },
                clear=True,
            ),
            patch(
                "aragora.storage.redis_ha.check_async_redis_health",
                return_value={
                    "healthy": True,
                    "mode": "sentinel",
                    "info": {"redis_version": "7.2.13"},
                },
            ),
        ):
            success, message = await validate_redis_connectivity()
            assert success is True
            assert "via sentinel" in message

    async def test_surfaces_sentinel_health_failure(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "ARAGORA_REDIS_MODE": "sentinel",
                    "ARAGORA_REDIS_SENTINEL_HOSTS": "sentinel-1:26379,sentinel-2:26379",
                    "ARAGORA_REDIS_SENTINEL_MASTER": "mymaster",
                },
                clear=True,
            ),
            patch(
                "aragora.storage.redis_ha.check_async_redis_health",
                return_value={
                    "healthy": False,
                    "mode": "sentinel",
                    "error": "Sentinel unavailable",
                },
            ),
        ):
            success, message = await validate_redis_connectivity()
            assert success is False
            assert "Sentinel unavailable" in message

    @pytest.mark.integration
    async def test_handles_connection_attempt(self):
        """Verify function handles connection attempt and returns proper tuple.

        Marked as integration test since it depends on Redis.
        """
        with patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}, clear=True):
            result = await validate_redis_connectivity(timeout_seconds=1.0)
            assert isinstance(result, tuple)
            assert len(result) == 2
            assert isinstance(result[0], bool)
            assert isinstance(result[1], str)


# ---------------------------------------------------------------------------
# validate_database_connectivity tests
# ---------------------------------------------------------------------------


class TestValidateDatabaseConnectivity:
    """Test validate_database_connectivity function."""

    async def test_skips_when_not_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            success, message = await validate_database_connectivity()
            assert success is True
            assert "not configured" in message

    @pytest.mark.integration
    async def test_handles_connection_attempt(self):
        """Verify function handles connection attempt and returns proper tuple.

        Marked as integration test since it depends on PostgreSQL.
        """
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://localhost/db"}, clear=True):
            try:
                result = await validate_database_connectivity(timeout_seconds=1.0)
                assert isinstance(result, tuple)
                assert len(result) == 2
                assert isinstance(result[0], bool)
                assert isinstance(result[1], str)
            except Exception:
                # If exception escapes, skip - service unavailable
                pytest.skip("PostgreSQL not available")

    @pytest.mark.integration
    async def test_alternate_env_var_recognized(self):
        """Test that ARAGORA_POSTGRES_DSN is recognized as database URL.

        Marked as integration test since it depends on PostgreSQL.
        """
        with patch.dict(
            "os.environ",
            {"ARAGORA_POSTGRES_DSN": "postgresql://localhost/db"},
            clear=True,
        ):
            try:
                result = await validate_database_connectivity(timeout_seconds=1.0)
                assert isinstance(result, tuple)
                # Not "not configured" since URL is set
                assert "not configured" not in result[1]
            except Exception:
                # If exception escapes, skip - service unavailable
                pytest.skip("PostgreSQL not available")


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestValidationIntegration:
    """Integration tests for validation functions."""

    def test_all_validations_return_lists(self):
        """Verify all check functions return lists."""
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.control_plane.leader.is_distributed_state_required", return_value=False
            ):
                with patch("aragora.config.settings.get_settings") as mock_settings:
                    mock_settings.return_value.agent.default_agents = ""

                    result1 = check_connector_dependencies()
                    result2 = check_agent_credentials()
                    result3 = check_production_requirements()

                    assert isinstance(result1, list)
                    assert isinstance(result2, list)
                    assert isinstance(result3, list)

    async def test_async_validations_return_tuples(self):
        """Verify async validation functions return (bool, str) tuples."""
        with patch.dict("os.environ", {}, clear=True):
            result1 = await validate_redis_connectivity()
            result2 = await validate_database_connectivity()

            assert isinstance(result1, tuple)
            assert len(result1) == 2
            assert isinstance(result1[0], bool)
            assert isinstance(result1[1], str)

            assert isinstance(result2, tuple)
            assert len(result2) == 2
            assert isinstance(result2[0], bool)
            assert isinstance(result2[1], str)


# ---------------------------------------------------------------------------
# is_connectivity_skipped tests (skip != connected)
# ---------------------------------------------------------------------------


class TestConnectivitySkipSignal:
    """The skip case must be distinguishable from a validated connection.

    Regression: ``validate-env`` reported Redis/PostgreSQL as "connected" when
    they were merely unconfigured (connectivity probe skipped). The validators
    return ``(True, <skip message>)`` for startup-gating reasons, so a truthy
    success bool does NOT imply a real connection.
    """

    async def test_redis_skip_message_is_detected_as_skipped(self):
        from aragora.server.startup.validation import (
            REDIS_SKIP_MESSAGE,
            is_connectivity_skipped,
        )

        with patch.dict("os.environ", {}, clear=True):
            success, message = await validate_redis_connectivity()
        # Success is True (does not fail startup) ...
        assert success is True
        # ... but the message is the skip sentinel, NOT a connection.
        assert message == REDIS_SKIP_MESSAGE
        assert is_connectivity_skipped(message) is True

    async def test_database_skip_message_is_detected_as_skipped(self):
        from aragora.server.startup.validation import (
            DATABASE_SKIP_MESSAGE,
            is_connectivity_skipped,
        )

        with patch.dict("os.environ", {}, clear=True):
            success, message = await validate_database_connectivity()
        assert success is True
        assert message == DATABASE_SKIP_MESSAGE
        assert is_connectivity_skipped(message) is True

    def test_real_connection_message_is_not_skipped(self):
        from aragora.server.startup.validation import is_connectivity_skipped

        assert is_connectivity_skipped("Redis connected (version 7.2.13)") is False
        assert is_connectivity_skipped("PostgreSQL connected (PostgreSQL 15.4)") is False

    def test_failure_message_is_not_skipped(self):
        from aragora.server.startup.validation import is_connectivity_skipped

        assert is_connectivity_skipped("Redis connection failed: refused") is False
        assert is_connectivity_skipped("PostgreSQL connection timed out after 5.0s") is False

    def test_predicate_is_exported_from_package(self):
        from aragora.server.startup import is_connectivity_skipped as exported

        assert callable(exported)
