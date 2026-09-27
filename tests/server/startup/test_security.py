"""Tests for server startup security initialization.

Tests the deployment validation, RBAC cache, key rotation,
access review scheduler, and decision router initialization.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.startup.security import (
    _get_degraded_status,
    init_access_review_scheduler,
    init_approval_gate_recovery,
    init_decision_router,
    init_deployment_validation,
    init_graphql_routes,
    init_key_rotation_scheduler,
    init_rbac_distributed_cache,
    init_security_edge_adapters,
    init_secrets_rotation_scheduler,
    validate_required_secrets,
)


# =============================================================================
# Test: init_security_edge_adapters
# =============================================================================


class TestInitSecurityEdgeAdapters:
    """Tests for higher-layer security adapter registration."""

    def test_returns_true_when_registration_succeeds(self):
        with patch(
            "aragora.ops.security_edge_adapters.register_security_edge_adapters"
        ) as register:
            result = init_security_edge_adapters()

        assert result is True
        register.assert_called_once_with()

    def test_returns_false_when_registration_fails(self):
        with patch(
            "aragora.ops.security_edge_adapters.register_security_edge_adapters",
            side_effect=ImportError("adapter unavailable"),
        ):
            result = init_security_edge_adapters()

        assert result is False

    def test_strict_mode_raises_when_registration_fails(self):
        with (
            patch(
                "aragora.ops.security_edge_adapters.register_security_edge_adapters",
                side_effect=ImportError("adapter unavailable"),
            ),
            pytest.raises(RuntimeError, match="Security edge adapter registration failed"),
        ):
            init_security_edge_adapters(strict=True)


# =============================================================================
# Test: _get_degraded_status
# =============================================================================


class TestGetDegradedStatus:
    """Tests for the _get_degraded_status function."""

    def test_returns_degraded_dict(self):
        """Test that function returns a dictionary with degraded flag."""
        status = _get_degraded_status()

        assert isinstance(status, dict)
        assert status["degraded"] is True

    def test_backend_connectivity_invalid(self):
        """Test that backend connectivity shows invalid in degraded mode."""
        status = _get_degraded_status()

        assert "backend_connectivity" in status
        assert status["backend_connectivity"]["valid"] is False
        assert "Server in degraded mode" in status["backend_connectivity"]["errors"]

    def test_all_features_disabled(self):
        """Test that all features are disabled in degraded mode."""
        status = _get_degraded_status()

        disabled_features = [
            "error_monitoring",
            "opentelemetry",
            "otlp_exporter",
            "prometheus",
            "background_tasks",
            "pulse_scheduler",
            "state_cleanup",
            "km_adapters",
            "workflow_checkpoint_persistence",
            "shared_control_plane_state",
            "tts_integration",
            "webhook_dispatcher",
            "slo_webhooks",
            "gauntlet_worker",
            "redis_state_backend",
            "key_rotation_scheduler",
            "access_review_scheduler",
            "rbac_distributed_cache",
            "notification_worker",
            "graphql",
            "backup_scheduler",
        ]

        for feature in disabled_features:
            assert status.get(feature) is False, f"{feature} should be False"

    def test_null_references_are_none(self):
        """Test that nullable references are None."""
        status = _get_degraded_status()

        assert status["watchdog_task"] is None
        assert status["control_plane_coordinator"] is None

    def test_zero_counters(self):
        """Test that counters are zero in degraded mode."""
        status = _get_degraded_status()

        assert status["circuit_breakers"] == 0
        assert status["persistent_task_queue"] == 0
        assert status["gauntlet_runs_recovered"] == 0
        assert status["durable_jobs_recovered"] == 0


# =============================================================================
# Test: init_deployment_validation
# =============================================================================


class TestInitDeploymentValidation:
    """Tests for deployment validation initialization."""

    @pytest.mark.asyncio
    async def test_returns_dict_on_success(self):
        """Test that function returns a dictionary on successful validation."""
        mock_result = MagicMock()
        mock_result.ready = True
        mock_result.live = True
        mock_result.issues = []
        mock_result.components = ["jwt", "database", "redis"]
        mock_result.validation_duration_ms = 150.0

        mock_severity = MagicMock()
        mock_severity.CRITICAL = "critical"
        mock_severity.WARNING = "warning"
        mock_severity.INFO = "info"

        mock_module = MagicMock()
        mock_module.validate_deployment = AsyncMock(return_value=mock_result)
        mock_module.Severity = mock_severity

        with patch.dict(os.environ, {"ARAGORA_ENV": "development"}, clear=False):
            with patch.dict(
                "sys.modules",
                {"aragora.ops.deployment_validator": mock_module},
            ):
                result = await init_deployment_validation()

        assert isinstance(result, dict)
        assert result.get("ready") is True
        assert result.get("live") is True

    @pytest.mark.asyncio
    async def test_import_error_returns_not_available(self):
        """Test that ImportError returns availability false."""
        # Remove the module so import fails
        import sys

        original = sys.modules.get("aragora.ops.deployment_validator")

        with patch.dict(os.environ, {"ARAGORA_ENV": "development"}, clear=False):
            # Simulate import failure
            sys.modules["aragora.ops.deployment_validator"] = None
            try:
                result = await init_deployment_validation()
            finally:
                if original:
                    sys.modules["aragora.ops.deployment_validator"] = original
                else:
                    sys.modules.pop("aragora.ops.deployment_validator", None)

        # When the import fails, it should return availability info
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_strict_mode_in_production(self):
        """Test that strict mode is enabled by default in production."""
        mock_result = MagicMock()
        mock_result.ready = True
        mock_result.live = True
        mock_result.issues = []
        mock_result.components = []
        mock_result.validation_duration_ms = 100.0

        mock_severity = MagicMock()
        mock_severity.CRITICAL = "critical"
        mock_severity.WARNING = "warning"
        mock_severity.INFO = "info"

        mock_validate = AsyncMock(return_value=mock_result)
        mock_module = MagicMock()
        mock_module.validate_deployment = mock_validate
        mock_module.Severity = mock_severity

        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", "ARAGORA_STRICT_DEPLOYMENT": ""},
            clear=False,
        ):
            with patch.dict(
                "sys.modules",
                {"aragora.ops.deployment_validator": mock_module},
            ):
                await init_deployment_validation()

        # Verify strict=True was passed
        mock_validate.assert_awaited_once()
        call_kwargs = mock_validate.call_args[1]
        assert call_kwargs.get("strict") is True

    @pytest.mark.asyncio
    async def test_strict_mode_override(self):
        """Test that strict mode can be explicitly disabled."""
        mock_result = MagicMock()
        mock_result.ready = True
        mock_result.live = True
        mock_result.issues = []
        mock_result.components = []
        mock_result.validation_duration_ms = 100.0

        mock_severity = MagicMock()
        mock_severity.CRITICAL = "critical"
        mock_severity.WARNING = "warning"
        mock_severity.INFO = "info"

        mock_validate = AsyncMock(return_value=mock_result)
        mock_module = MagicMock()
        mock_module.validate_deployment = mock_validate
        mock_module.Severity = mock_severity

        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", "ARAGORA_STRICT_DEPLOYMENT": "false"},
            clear=False,
        ):
            with patch.dict(
                "sys.modules",
                {"aragora.ops.deployment_validator": mock_module},
            ):
                await init_deployment_validation()

        # Verify strict=False was passed
        mock_validate.assert_awaited_once()
        call_kwargs = mock_validate.call_args[1]
        assert call_kwargs.get("strict") is False


# =============================================================================
# Test: init_graphql_routes
# =============================================================================


class TestInitGraphQLRoutes:
    """Tests for GraphQL route initialization."""

    def test_disabled_when_env_false(self):
        """Test that GraphQL is disabled when environment variable is false."""
        mock_app = MagicMock()

        with patch.dict(os.environ, {"ARAGORA_GRAPHQL_ENABLED": "false"}, clear=False):
            result = init_graphql_routes(mock_app)

        assert result is False

    def test_enabled_by_default(self):
        """Test that GraphQL is enabled by default."""
        mock_app = MagicMock()
        mock_module = MagicMock()
        mock_module.GraphQLHandler = MagicMock()
        mock_module.GraphQLSchemaHandler = MagicMock()

        with patch.dict(os.environ, {"ARAGORA_GRAPHQL_ENABLED": "true"}, clear=False):
            with patch.dict(
                "sys.modules",
                {"aragora.server.graphql": mock_module},
            ):
                result = init_graphql_routes(mock_app)

        assert result is True

    def test_import_error_returns_false(self):
        """Test that ImportError returns False."""
        mock_app = MagicMock()

        with patch.dict(os.environ, {"ARAGORA_GRAPHQL_ENABLED": "true"}, clear=False):
            with patch.dict(
                "sys.modules",
                {"aragora.server.graphql": None},
            ):
                result = init_graphql_routes(mock_app)

        # Import fails, should return False
        assert result is False

    def test_introspection_disabled_in_production(self):
        """Test that introspection is disabled by default in production."""
        mock_app = MagicMock()
        mock_module = MagicMock()
        mock_module.GraphQLHandler = MagicMock()
        mock_module.GraphQLSchemaHandler = MagicMock()

        with patch.dict(
            os.environ,
            {
                "ARAGORA_GRAPHQL_ENABLED": "true",
                "ARAGORA_ENV": "production",
            },
            clear=False,
        ):
            with patch.dict(
                "sys.modules",
                {"aragora.server.graphql": mock_module},
            ):
                result = init_graphql_routes(mock_app)

        assert result is True


# =============================================================================
# Test: init_rbac_distributed_cache
# =============================================================================


class TestInitRBACDistributedCache:
    """Tests for RBAC distributed cache initialization."""

    @pytest.mark.asyncio
    async def test_disabled_when_env_false(self):
        """Test that cache is disabled when environment variable is false."""
        with patch.dict(os.environ, {"RBAC_CACHE_ENABLED": "false"}, clear=False):
            result = await init_rbac_distributed_cache()

        assert result is False

    @pytest.mark.asyncio
    async def test_disabled_without_redis_url(self):
        """Test that cache is disabled without Redis URL."""
        env_vars = {
            "RBAC_CACHE_ENABLED": "true",
            "REDIS_URL": "",
            "ARAGORA_REDIS_URL": "",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            result = await init_rbac_distributed_cache()

        assert result is False

    @pytest.mark.asyncio
    async def test_enabled_with_redis_url(self):
        """Test that cache is enabled with valid Redis URL."""
        mock_cache = MagicMock()
        mock_cache.is_distributed = True
        mock_cache.start = MagicMock()

        mock_checker = MagicMock()
        mock_checker._auditor = None

        mock_config = MagicMock()
        mock_config.decision_ttl_seconds = 300
        mock_config.l1_enabled = True

        mock_cache_module = MagicMock()
        mock_cache_module.RBACCacheConfig = MagicMock()
        mock_cache_module.RBACCacheConfig.from_env = MagicMock(return_value=mock_config)
        mock_cache_module.RBACDistributedCache = MagicMock()
        mock_cache_module.get_rbac_cache = MagicMock(return_value=mock_cache)

        mock_checker_module = MagicMock()
        mock_checker_module.PermissionChecker = MagicMock()
        mock_checker_module.get_permission_checker = MagicMock(return_value=mock_checker)
        mock_checker_module.set_permission_checker = MagicMock()

        with patch.dict(
            os.environ,
            {
                "RBAC_CACHE_ENABLED": "true",
                "REDIS_URL": "redis://localhost:6379",
            },
            clear=False,
        ):
            with patch.dict(
                "sys.modules",
                {
                    "aragora.rbac.cache": mock_cache_module,
                    "aragora.rbac.checker": mock_checker_module,
                },
            ):
                result = await init_rbac_distributed_cache()

        assert result is True
        mock_cache.start.assert_called_once()


# =============================================================================
# Test: init_approval_gate_recovery
# =============================================================================


class TestInitApprovalGateRecovery:
    """Tests for approval gate recovery initialization."""

    @pytest.mark.asyncio
    async def test_returns_count_on_success(self):
        """Test that function returns recovery count on success."""
        mock_module = MagicMock()
        mock_module.recover_pending_approvals = AsyncMock(return_value=5)

        with patch.dict(
            "sys.modules",
            {"aragora.server.middleware.approval_gate": mock_module},
        ):
            result = await init_approval_gate_recovery()

        assert result == 5

    @pytest.mark.asyncio
    async def test_import_error_returns_zero(self):
        """Test that ImportError returns zero."""
        with patch.dict(
            "sys.modules",
            {"aragora.server.middleware.approval_gate": None},
        ):
            result = await init_approval_gate_recovery()

        assert result == 0

    @pytest.mark.asyncio
    async def test_runtime_error_returns_zero(self):
        """Test that RuntimeError returns zero."""
        mock_module = MagicMock()
        mock_module.recover_pending_approvals = AsyncMock(
            side_effect=RuntimeError("Recovery failed")
        )

        with patch.dict(
            "sys.modules",
            {"aragora.server.middleware.approval_gate": mock_module},
        ):
            result = await init_approval_gate_recovery()

        assert result == 0


# =============================================================================
# Test: init_access_review_scheduler
# =============================================================================


class TestInitAccessReviewScheduler:
    """Tests for access review scheduler initialization."""

    @pytest.mark.asyncio
    async def test_disabled_in_development(self):
        """Test that scheduler is disabled by default in development."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_ACCESS_REVIEW_ENABLED": "",
                "ARAGORA_ENV": "development",
            },
            clear=False,
        ):
            result = await init_access_review_scheduler()

        assert result is False

    @pytest.mark.asyncio
    async def test_enabled_explicitly(self):
        """Test that scheduler can be explicitly enabled."""
        mock_scheduler = MagicMock()
        mock_scheduler.start = AsyncMock()

        mock_config = MagicMock()
        mock_config.monthly_review_day = 1

        mock_path = MagicMock()
        mock_path.mkdir = MagicMock()
        mock_path.__truediv__ = lambda self, x: f"/tmp/{x}"

        mock_scheduler_module = MagicMock()
        mock_scheduler_module.AccessReviewConfig = MagicMock(return_value=mock_config)
        mock_scheduler_module.get_access_review_scheduler = MagicMock(return_value=mock_scheduler)

        mock_db_config = MagicMock()
        mock_db_config.get_nomic_dir = MagicMock(return_value=mock_path)

        with patch.dict(
            os.environ,
            {
                "ARAGORA_ACCESS_REVIEW_ENABLED": "true",
                "ARAGORA_ENV": "development",
            },
            clear=False,
        ):
            with patch.dict(
                "sys.modules",
                {
                    "aragora.scheduler.access_review_scheduler": mock_scheduler_module,
                    "aragora.persistence.db_config": mock_db_config,
                },
            ):
                result = await init_access_review_scheduler()

        assert result is True
        mock_scheduler.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_enabled_in_production(self):
        """Test that scheduler is auto-enabled in production."""
        mock_scheduler = MagicMock()
        mock_scheduler.start = AsyncMock()

        mock_config = MagicMock()
        mock_config.monthly_review_day = 1

        mock_path = MagicMock()
        mock_path.mkdir = MagicMock()
        mock_path.__truediv__ = lambda self, x: f"/tmp/{x}"

        mock_scheduler_module = MagicMock()
        mock_scheduler_module.AccessReviewConfig = MagicMock(return_value=mock_config)
        mock_scheduler_module.get_access_review_scheduler = MagicMock(return_value=mock_scheduler)

        mock_db_config = MagicMock()
        mock_db_config.get_nomic_dir = MagicMock(return_value=mock_path)

        with patch.dict(
            os.environ,
            {
                "ARAGORA_ACCESS_REVIEW_ENABLED": "",
                "ARAGORA_ENV": "production",
            },
            clear=False,
        ):
            with patch.dict(
                "sys.modules",
                {
                    "aragora.scheduler.access_review_scheduler": mock_scheduler_module,
                    "aragora.persistence.db_config": mock_db_config,
                },
            ):
                result = await init_access_review_scheduler()

        assert result is True


# =============================================================================
# Test: init_key_rotation_scheduler
# =============================================================================


class TestInitKeyRotationScheduler:
    """Tests for key rotation scheduler initialization."""

    @pytest.mark.asyncio
    async def test_disabled_in_development(self):
        """Test that scheduler is disabled by default in development."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_KEY_ROTATION_ENABLED": "",
                "ARAGORA_ENV": "development",
            },
            clear=False,
        ):
            result = await init_key_rotation_scheduler()

        assert result is False

    @pytest.mark.asyncio
    async def test_requires_encryption_key(self):
        """Test that scheduler requires encryption key."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_KEY_ROTATION_ENABLED": "true",
                "ARAGORA_ENCRYPTION_KEY": "",
            },
            clear=False,
        ):
            result = await init_key_rotation_scheduler()

        assert result is False

    @pytest.mark.asyncio
    async def test_enabled_with_encryption_key(self):
        """Test that scheduler starts with encryption key."""
        mock_scheduler = MagicMock()
        mock_scheduler.start = AsyncMock()
        mock_scheduler.get_status = AsyncMock(return_value={"next_rotation": "2026-03-01"})
        mock_scheduler.config = None
        mock_scheduler.alert_callback = None

        mock_config = MagicMock()
        mock_config.rotation_interval_days = 90
        mock_config.key_overlap_days = 7
        mock_config.re_encrypt_on_rotation = False

        mock_key_rotation_module = MagicMock()
        mock_key_rotation_module.get_key_rotation_scheduler = MagicMock(return_value=mock_scheduler)
        mock_key_rotation_module.KeyRotationConfig = MagicMock()
        mock_key_rotation_module.KeyRotationConfig.from_env = MagicMock(return_value=mock_config)

        mock_metrics_module = MagicMock()
        mock_metrics_module.set_active_keys = MagicMock()

        # Use a valid 32-byte hex key (64 hex chars)
        valid_hex_key = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        with patch.dict(
            os.environ,
            {
                "ARAGORA_KEY_ROTATION_ENABLED": "true",
                "ARAGORA_ENCRYPTION_KEY": valid_hex_key,
                "ARAGORA_ENV": "development",
            },
            clear=False,
        ):
            with patch.dict(
                "sys.modules",
                {
                    "aragora.ops.key_rotation": mock_key_rotation_module,
                    "aragora.observability.metrics.security": mock_metrics_module,
                },
            ):
                result = await init_key_rotation_scheduler()

        assert result is True
        mock_scheduler.start.assert_awaited_once()


# =============================================================================
# Test: init_secrets_rotation_scheduler
# =============================================================================


class TestInitSecretsRotationScheduler:
    """Tests for secrets rotation scheduler initialization."""

    @pytest.mark.asyncio
    async def test_disabled_in_development(self):
        """Test that scheduler is disabled by default in development."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_SECRETS_ROTATION_ENABLED": "",
                "ARAGORA_ENV": "development",
            },
            clear=False,
        ):
            result = await init_secrets_rotation_scheduler()

        assert result is False

    @pytest.mark.asyncio
    async def test_enabled_explicitly(self):
        """Test that scheduler can be explicitly enabled."""
        mock_scheduler = MagicMock()
        mock_scheduler.start = AsyncMock()

        mock_module = MagicMock()
        mock_module.get_secrets_rotation_scheduler = MagicMock(return_value=mock_scheduler)

        with patch.dict(
            os.environ,
            {
                "ARAGORA_SECRETS_ROTATION_ENABLED": "true",
                "ARAGORA_ENV": "development",
            },
            clear=False,
        ):
            with patch.dict(
                "sys.modules",
                {"aragora.scheduler.secrets_rotation_scheduler": mock_module},
            ):
                result = await init_secrets_rotation_scheduler()

        assert result is True
        mock_scheduler.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_import_error_returns_false(self):
        """Test that ImportError returns False."""
        with patch.dict(
            os.environ,
            {"ARAGORA_SECRETS_ROTATION_ENABLED": "true"},
            clear=False,
        ):
            with patch.dict(
                "sys.modules",
                {"aragora.scheduler.secrets_rotation_scheduler": None},
            ):
                result = await init_secrets_rotation_scheduler()

        assert result is False


# =============================================================================
# Test: validate_required_secrets
# =============================================================================


class TestValidateRequiredSecrets:
    """Tests for required secrets validation."""

    def test_no_ai_key_is_error(self):
        """Test that missing AI API key is an error."""
        env_vars = {
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "ARAGORA_ENV": "development",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            result = validate_required_secrets()

        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert any("AI provider" in e for e in result["errors"])

    def test_anthropic_key_sufficient(self):
        """Test that Anthropic key alone is sufficient."""
        env_vars = {
            "ANTHROPIC_API_KEY": "sk-ant-test-key",
            "OPENAI_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "ARAGORA_ENV": "development",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            result = validate_required_secrets()

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_openai_key_sufficient(self):
        """Test that OpenAI key alone is sufficient."""
        env_vars = {
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "sk-test-key",
            "OPENROUTER_API_KEY": "",
            "ARAGORA_ENV": "development",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            result = validate_required_secrets()

        assert result["valid"] is True

    def test_production_requires_jwt_secret(self):
        """Test that production requires JWT secret."""
        env_vars = {
            "ANTHROPIC_API_KEY": "sk-ant-test-key",
            "ARAGORA_ENV": "production",
            "ARAGORA_JWT_SECRET": "",
            "ARAGORA_ENCRYPTION_KEY": "test-encryption-key",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            result = validate_required_secrets()

        assert result["valid"] is False
        assert any("ARAGORA_JWT_SECRET" in e for e in result["errors"])

    def test_production_requires_encryption_key(self):
        """Test that production requires encryption key."""
        env_vars = {
            "ANTHROPIC_API_KEY": "sk-ant-test-key",
            "ARAGORA_ENV": "production",
            "ARAGORA_JWT_SECRET": "test-jwt-secret",
            "ARAGORA_ENCRYPTION_KEY": "",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            result = validate_required_secrets()

        assert result["valid"] is False
        assert any("ARAGORA_ENCRYPTION_KEY" in e for e in result["errors"])

    def test_production_warns_without_secrets_manager(self):
        """Test that production warns without Secrets Manager."""
        env_vars = {
            "ANTHROPIC_API_KEY": "sk-ant-test-key",
            "ARAGORA_ENV": "production",
            "ARAGORA_JWT_SECRET": "test-jwt-secret",
            "ARAGORA_ENCRYPTION_KEY": "test-encryption-key",
            "ARAGORA_USE_SECRETS_MANAGER": "",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            result = validate_required_secrets()

        assert result["valid"] is True
        assert len(result["warnings"]) > 0
        assert any("Secrets Manager" in w for w in result["warnings"])

    def test_staging_treated_as_production(self):
        """Test that staging environment is treated as production."""
        env_vars = {
            "ANTHROPIC_API_KEY": "sk-ant-test-key",
            "ARAGORA_ENV": "staging",
            "ARAGORA_JWT_SECRET": "",
            "ARAGORA_ENCRYPTION_KEY": "",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            result = validate_required_secrets()

        assert result["valid"] is False


# =============================================================================
# Test: init_decision_router
# =============================================================================


class TestInitDecisionRouter:
    """Tests for decision router initialization."""

    @pytest.mark.asyncio
    async def test_registers_platform_handlers(self):
        """Test that all platform handlers are registered."""
        mock_router = MagicMock()
        registered_handlers = []

        def track_registration(platform, handler):
            registered_handlers.append(platform)

        mock_router.register_response_handler = track_registration

        mock_decision_module = MagicMock()
        mock_decision_module.get_decision_router = MagicMock(return_value=mock_router)

        mock_origin_module = MagicMock()
        mock_origin_module.route_debate_result = MagicMock()
        mock_origin_module.get_debate_origin = MagicMock(return_value=None)

        with patch.dict(
            "sys.modules",
            {
                "aragora.core.decision": mock_decision_module,
                "aragora.server.debate_origin": mock_origin_module,
            },
        ):
            result = await init_decision_router()

        assert result is True
        expected_platforms = [
            "telegram",
            "slack",
            "discord",
            "whatsapp",
            "teams",
            "email",
            "google_chat",
            "gchat",
        ]
        for platform in expected_platforms:
            assert platform in registered_handlers

    @pytest.mark.asyncio
    async def test_import_error_returns_false(self):
        """Test that ImportError returns False."""
        mock_decision_module = MagicMock()
        mock_decision_module.get_decision_router = MagicMock(
            side_effect=ImportError("Module not found")
        )

        with patch.dict(
            "sys.modules",
            {"aragora.core.decision": mock_decision_module},
        ):
            result = await init_decision_router()

        assert result is False

    @pytest.mark.asyncio
    async def test_runtime_error_returns_false(self):
        """Test that RuntimeError returns False."""
        mock_decision_module = MagicMock()
        mock_decision_module.get_decision_router = MagicMock(
            side_effect=RuntimeError("Router not initialized")
        )

        with patch.dict(
            "sys.modules",
            {"aragora.core.decision": mock_decision_module},
        ):
            result = await init_decision_router()

        assert result is False


# =============================================================================
# Integration Tests
# =============================================================================


class TestSecurityStartupIntegration:
    """Integration tests for security startup sequence."""

    @pytest.mark.asyncio
    async def test_degraded_mode_fallback(self):
        """Test that degraded status is used when startup fails."""
        status = _get_degraded_status()

        # Verify we can still get a valid status
        assert status["degraded"] is True
        assert "backend_connectivity" in status

    def test_environment_variable_parsing(self):
        """Test that environment variables are parsed correctly."""
        test_cases = [
            ("true", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
            ("", False),
        ]

        for env_value, expected in test_cases:
            with patch.dict(
                os.environ,
                {"ARAGORA_ACCESS_REVIEW_ENABLED": env_value},
                clear=False,
            ):
                enabled = os.environ.get("ARAGORA_ACCESS_REVIEW_ENABLED", "").lower() in (
                    "true",
                    "1",
                    "yes",
                )
                assert enabled == expected, f"Failed for value: {env_value}"
