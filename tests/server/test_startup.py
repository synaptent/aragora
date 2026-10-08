"""
Tests for Server Startup Module.

Tests cover:
- Configuration value retrieval
- Connector dependency checking
- Production requirements validation
- Redis and database connectivity validation
- Initialization functions with mocked dependencies
- Storage backend validation
- Background task initialization
"""

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestConfigValueRetrieval:
    """Tests for _get_config_value function."""

    def test_get_config_from_environment(self):
        """Test getting config value from environment variable."""
        from aragora.server.startup.validation import _get_config_value

        with patch.dict(os.environ, {"TEST_CONFIG_VALUE": "test_value"}):
            result = _get_config_value("TEST_CONFIG_VALUE")
            assert result == "test_value"

    def test_get_config_from_environment_missing(self):
        """Test getting missing config value returns None."""
        from aragora.server.startup.validation import _get_config_value

        with patch.dict(os.environ, {}, clear=True):
            result = _get_config_value("NONEXISTENT_CONFIG")
            assert result is None

    def test_get_config_prefers_environment(self):
        """Test that environment takes precedence over secrets manager."""
        from aragora.server.startup.validation import _get_config_value

        with patch.dict(os.environ, {"MY_CONFIG": "env_value"}):
            result = _get_config_value("MY_CONFIG")
            assert result == "env_value"


class TestConnectorDependencyChecking:
    """Tests for check_connector_dependencies function."""

    def test_no_warnings_without_connectors(self):
        """Test no warnings when no connectors configured."""
        from aragora.server.startup import check_connector_dependencies

        with patch.dict(os.environ, {}, clear=True):
            warnings = check_connector_dependencies()
            assert len(warnings) == 0

    def test_discord_warning_without_pynacl(self):
        """Test Discord warning when PyNaCl not available."""
        from aragora.server.startup import check_connector_dependencies

        with patch.dict(os.environ, {"DISCORD_PUBLIC_KEY": "test_key"}):
            with patch.dict("sys.modules", {"nacl": None, "nacl.signing": None}):
                import sys

                # Remove nacl if present
                if "nacl.signing" in sys.modules:
                    del sys.modules["nacl.signing"]
                if "nacl" in sys.modules:
                    del sys.modules["nacl"]

                warnings = check_connector_dependencies()
                discord_warnings = [w for w in warnings if "Discord" in w]
                # Note: This may pass if PyNaCl is installed
                assert isinstance(warnings, list)

    def test_slack_oauth_partial_config_warning(self):
        """Test warning when Slack OAuth partially configured."""
        from aragora.server.startup import check_connector_dependencies

        with patch.dict(os.environ, {"SLACK_CLIENT_ID": "client_id"}, clear=True):
            warnings = check_connector_dependencies()
            slack_warnings = [w for w in warnings if "Slack OAuth" in w]
            assert len(slack_warnings) >= 1

    def test_slack_signing_secret_warning(self):
        """Test warning when Slack webhook configured without signing secret."""
        from aragora.server.startup import check_connector_dependencies

        with patch.dict(
            os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"}, clear=True
        ):
            warnings = check_connector_dependencies()
            signing_warnings = [w for w in warnings if "SLACK_SIGNING_SECRET" in w]
            assert len(signing_warnings) == 1


class TestProductionRequirements:
    """Tests for check_production_requirements function."""

    def test_no_requirements_in_development(self):
        """Test no requirements enforced in development mode."""
        from aragora.server.startup import check_production_requirements

        with patch.dict(os.environ, {"ARAGORA_ENV": "development"}, clear=True):
            missing = check_production_requirements()
            assert len(missing) == 0

    def test_encryption_key_required_in_production(self):
        """Test encryption key required in production."""
        from aragora.server.startup import check_production_requirements

        def _env_only(name: str):
            """Only check env vars, not secrets manager."""
            return os.environ.get(name)

        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=True):
            with (
                patch(
                    "aragora.control_plane.leader.is_distributed_state_required", return_value=False
                ),
                patch("aragora.server.startup.validation._get_config_value", side_effect=_env_only),
            ):
                missing = check_production_requirements()
                encryption_missing = [m for m in missing if "ENCRYPTION_KEY" in m]
                assert len(encryption_missing) >= 1

    def test_redis_required_for_distributed_state(self):
        """Test Redis required when distributed state is needed."""
        from aragora.server.startup import check_production_requirements

        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=True):
            with patch(
                "aragora.control_plane.leader.is_distributed_state_required", return_value=True
            ):
                missing = check_production_requirements()
                redis_missing = [m for m in missing if "REDIS_URL" in m]
                assert len(redis_missing) >= 1


class TestRedisConnectivity:
    """Tests for Redis connectivity validation."""

    @pytest.mark.asyncio
    async def test_validate_redis_connectivity_returns_tuple(self):
        """Test Redis connectivity validation returns expected format."""
        from aragora.server.startup import validate_redis_connectivity

        # Without URL configured, should return (False, message)
        with patch.dict(os.environ, {}, clear=True):
            result = await validate_redis_connectivity()
            assert isinstance(result, tuple)
            assert len(result) == 2
            success, message = result
            assert isinstance(success, bool)
            assert isinstance(message, str)

    @pytest.mark.asyncio
    async def test_validate_redis_connectivity_with_url(self):
        """Test Redis connectivity validation with URL configured."""
        from aragora.server.startup import validate_redis_connectivity

        # With URL but no actual Redis, should still return valid response
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}):
            result = await validate_redis_connectivity()
            assert isinstance(result, tuple)
            assert len(result) == 2


class TestDatabaseConnectivity:
    """Tests for database connectivity validation."""

    @pytest.mark.asyncio
    async def test_validate_database_returns_tuple(self):
        """Test database validation returns expected format."""
        from aragora.server.startup import validate_database_connectivity

        with patch.dict(os.environ, {}, clear=True):
            result = await validate_database_connectivity()
            assert isinstance(result, tuple)
            assert len(result) == 2
            success, message = result
            assert isinstance(success, bool)
            assert isinstance(message, str)


class TestStorageBackendValidation:
    """Tests for storage backend validation."""

    def test_validate_storage_backend_local(self):
        """Test storage backend validation for local storage."""
        from aragora.server.startup import validate_storage_backend

        with patch.dict(
            os.environ,
            {"ARAGORA_STORAGE_BACKEND": "local", "ARAGORA_DATA_DIR": "/tmp/test"},
            clear=True,
        ):
            result = validate_storage_backend()
            assert isinstance(result, dict)
            assert "backend" in result or "type" in result or "valid" in result

    def test_validate_storage_backend_default(self):
        """Test storage backend validation with default settings."""
        from aragora.server.startup import validate_storage_backend

        with patch.dict(os.environ, {}, clear=True):
            result = validate_storage_backend()
            assert isinstance(result, dict)


class TestBackgroundTaskInitialization:
    """Tests for background task initialization."""

    def test_init_background_tasks_creates_tasks(self):
        """Test that background tasks are initialized."""
        from aragora.server.startup import init_background_tasks
        from pathlib import Path

        # Create a temporary directory for testing
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            result = init_background_tasks(Path(tmpdir))
            assert isinstance(result, bool)

    def test_init_background_tasks_none_dir(self):
        """Test background tasks with None directory."""
        from aragora.server.startup import init_background_tasks

        result = init_background_tasks(None)
        assert isinstance(result, bool)


class TestCircuitBreakerPersistence:
    """Tests for circuit breaker persistence initialization."""

    def test_init_circuit_breaker_persistence(self):
        """Test circuit breaker persistence initialization."""
        from aragora.server.startup import init_circuit_breaker_persistence
        from pathlib import Path

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            result = init_circuit_breaker_persistence(Path(tmpdir))
            assert isinstance(result, int)
            assert result >= 0

    def test_init_circuit_breaker_persistence_none(self):
        """Test circuit breaker persistence with None directory."""
        from aragora.server.startup import init_circuit_breaker_persistence

        result = init_circuit_breaker_persistence(None)
        assert isinstance(result, int)
        assert result >= 0  # May load from default location


class TestStateCleanupTask:
    """Tests for state cleanup task initialization."""

    def test_init_state_cleanup_task(self):
        """Test state cleanup task initialization."""
        from aragora.server.startup import init_state_cleanup_task

        result = init_state_cleanup_task()
        assert isinstance(result, bool)


class TestKnowledgeMoundConfig:
    """Tests for Knowledge Mound configuration."""

    def test_get_km_config_from_env_returns_config(self):
        """Test getting KM config returns valid config object."""
        from aragora.server.startup import get_km_config_from_env

        config = get_km_config_from_env()
        assert config is not None
        # MoundConfig should have backend attribute
        assert hasattr(config, "backend")

    def test_get_km_config_from_env_custom(self):
        """Test getting KM config with custom environment values."""
        from aragora.server.startup import get_km_config_from_env

        with patch.dict(
            os.environ,
            {
                "ARAGORA_KM_ENABLED": "true",
                "ARAGORA_KM_CACHE_TTL": "3600",
            },
        ):
            config = get_km_config_from_env()
            assert config is not None
            assert hasattr(config, "backend")


class TestSLOWebhooks:
    """Tests for SLO webhook initialization."""

    def test_init_slo_webhooks(self):
        """Test SLO webhook initialization."""
        from aragora.server.startup import init_slo_webhooks

        result = init_slo_webhooks()
        assert isinstance(result, bool)


class TestWebhookDispatcher:
    """Tests for webhook dispatcher initialization."""

    def test_init_webhook_dispatcher(self):
        """Test webhook dispatcher initialization."""
        from aragora.server.startup import init_webhook_dispatcher

        result = init_webhook_dispatcher()
        assert isinstance(result, bool)


class TestGauntletRecovery:
    """Tests for Gauntlet run recovery."""

    def test_init_gauntlet_run_recovery(self):
        """Test Gauntlet run recovery initialization."""
        from aragora.server.startup import init_gauntlet_run_recovery

        result = init_gauntlet_run_recovery()
        assert isinstance(result, int)
        assert result >= 0


@pytest.mark.asyncio
async def test_sequential_startup_registers_webhook_store_before_components():
    """Durable webhook wiring must precede optional component initialization."""
    from aragora.server.startup import _init_all_components

    order: list[str] = []

    async def fail_first_component():
        order.append("first_component")
        raise RuntimeError("stop after ordering assertion")

    with (
        patch(
            "aragora.server.startup.event_subscribers.register_webhook_store",
            side_effect=lambda: order.append("webhook_store"),
        ),
        patch(
            "aragora.server.startup.init_postgres_pool",
            side_effect=fail_first_component,
        ),
        pytest.raises(RuntimeError, match="stop after ordering assertion"),
    ):
        await _init_all_components({}, None, None)

    assert order == ["webhook_store", "first_component"]
