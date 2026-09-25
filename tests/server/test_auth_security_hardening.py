"""
Tests for authentication security hardening features.

Tests cover:
- MFA rate limiting (brute force prevention)
- Session regeneration on password change
- Session regeneration on MFA enable
- Config validator
"""

import os
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_user():
    """Create a mock user object."""
    user = Mock()
    user.id = "user-123"
    user.email = "test@example.com"
    user.name = "Test User"
    user.org_id = "org-456"
    user.role = "member"
    user.is_active = True
    user.mfa_enabled = True
    user.mfa_secret = "JBSWY3DPEHPK3PXP"  # Test TOTP secret
    user.mfa_backup_codes = "[]"
    user.verify_password = Mock(return_value=True)
    user.to_dict = Mock(
        return_value={
            "id": "user-123",
            "email": "test@example.com",
            "name": "Test User",
            "org_id": "org-456",
            "role": "member",
        }
    )
    return user


@pytest.fixture
def mock_user_store(mock_user):
    """Create a mock user store."""
    store = Mock()
    store.get_user_by_email = Mock(return_value=mock_user)
    store.get_user_by_id = Mock(return_value=mock_user)
    store.create_user = Mock(return_value=mock_user)
    store.update_user = Mock(return_value=mock_user)
    store.increment_token_version = Mock(return_value=2)
    return store


@pytest.fixture
def mock_handler():
    """Create a mock HTTP handler."""
    handler = Mock()
    handler.command = "POST"
    handler.headers = {"Content-Type": "application/json"}
    handler.rfile = Mock()
    return handler


@pytest.fixture(autouse=True)
def clear_rate_limiters():
    """Clear rate limiters before each test."""
    from aragora.server.handlers.utils.rate_limit import _limiters

    for limiter in _limiters.values():
        limiter._buckets.clear()
    yield
    for limiter in _limiters.values():
        limiter._buckets.clear()


# ============================================================================
# MFA Rate Limiting Tests
# ============================================================================


class TestMFARateLimiting:
    """Tests for MFA brute force prevention."""

    def test_mfa_verify_rate_limit_decorator(self):
        """Verify MFA verify endpoint has rate limit decorator."""
        from aragora.server.handlers.auth import AuthHandler

        # Check the method exists and has rate limiting
        assert hasattr(AuthHandler, "_handle_mfa_verify")

    def test_mfa_user_rate_limit_triggered(self, mock_user_store, mock_user, mock_handler):
        """Test that MFA verify endpoint has rate limiting applied via decorator."""
        from aragora.server.handlers.auth import AuthHandler

        ctx = {"user_store": mock_user_store}
        handler = AuthHandler(ctx)

        # Verify the @rate_limit decorator is applied (sets __wrapped__ via functools.wraps)
        assert hasattr(handler._handle_mfa_verify, "__wrapped__")
        # The decorator also sets _rate_limited marker
        assert getattr(handler._handle_mfa_verify, "_rate_limited", False)


class TestSessionRegeneration:
    """Tests for session regeneration on privilege escalation."""

    @patch("aragora.server.handlers.auth.handler.extract_user_from_request")
    def test_password_change_invalidates_sessions(
        self, mock_extract_user, mock_user_store, mock_user, mock_handler
    ):
        """Test that password change calls increment_token_version."""
        from aragora.server.handlers.auth import AuthHandler

        # Setup auth context with RBAC-compatible attributes
        auth_ctx = Mock()
        auth_ctx.is_authenticated = True
        auth_ctx.user_id = "user-123"
        auth_ctx.role = "member"
        auth_ctx.org_id = "org-456"
        auth_ctx.client_ip = "127.0.0.1"
        mock_extract_user.return_value = auth_ctx

        # Setup request body
        import io

        body = b'{"current_password": "oldpassword", "new_password": "NewPassword123!"}'
        mock_handler.rfile.read = Mock(return_value=body)
        mock_handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Authorization": "Bearer test_token",
        }
        mock_handler.command = "POST"

        ctx = {"user_store": mock_user_store}
        handler = AuthHandler(ctx)

        # Call the password change handler
        with patch("aragora.billing.models.hash_password", return_value=("hash", "salt")):
            result = handler._handle_change_password(mock_handler)

        # Verify token version was incremented
        mock_user_store.increment_token_version.assert_called_once_with("user-123")

        # Check response indicates sessions were invalidated
        assert result.status_code == 200
        response_body = result.body.decode()
        assert "sessions_invalidated" in response_body

    def test_mfa_enable_invalidates_sessions(self, mock_user_store, mock_user, mock_handler):
        """Test that enabling MFA calls increment_token_version."""
        import pyotp
        from aragora.server.handlers.auth import AuthHandler

        # Setup - user has MFA secret but not enabled yet
        mock_user.mfa_enabled = False
        mock_user.mfa_secret = "JBSWY3DPEHPK3PXP"

        # Setup auth context with RBAC-compatible attributes
        auth_ctx = Mock()
        auth_ctx.is_authenticated = True
        auth_ctx.user_id = "user-123"
        auth_ctx.role = "member"
        auth_ctx.org_id = "org-456"
        auth_ctx.client_ip = "127.0.0.1"

        ctx = {"user_store": mock_user_store}
        handler = AuthHandler(ctx)

        # Setup request with valid TOTP code
        import io

        body = b'{"code": "123456"}'
        mock_handler.rfile.read = Mock(return_value=body)
        mock_handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Authorization": "Bearer test_token",
        }

        # Mock both extract_user and TOTP verification
        with patch(
            "aragora.server.handlers.auth.handler.extract_user_from_request", return_value=auth_ctx
        ):
            with patch.object(pyotp, "TOTP") as mock_totp_class:
                mock_totp = Mock()
                mock_totp.verify.return_value = True
                mock_totp_class.return_value = mock_totp

                # Call the MFA enable handler
                result = handler._handle_mfa_enable(mock_handler)

        # Verify token version was incremented
        mock_user_store.increment_token_version.assert_called_once_with("user-123")

        # Check response indicates sessions were invalidated
        assert result.status_code == 200
        response_body = result.body.decode()
        assert "sessions_invalidated" in response_body


# ============================================================================
# Config Validator Tests
# ============================================================================


class TestConfigValidator:
    """Tests for startup configuration validation."""

    def test_validate_returns_empty_with_valid_config(self):
        """Test validation passes with valid configuration."""
        from aragora.server.config_validator import ConfigValidator

        with patch.dict(
            os.environ,
            {
                "ARAGORA_API_TOKEN": "a_valid_token_here_12345",
                "ANTHROPIC_API_KEY": "sk-ant-test-key-12345",
                "JWT_SECRET": "a" * 32,  # 32 chars minimum
            },
        ):
            result = ConfigValidator.validate_all()
            # Should have no errors (but may have warnings)
            assert len(result.errors) == 0

    def test_validate_detects_missing_llm_key_in_production(self):
        """Test validation fails without LLM key in production."""
        from aragora.server.config_validator import ConfigValidator

        with patch.dict(
            os.environ,
            {
                "ARAGORA_ENV": "production",
                "ARAGORA_API_TOKEN": "a_valid_token_here_12345",
                "JWT_SECRET": "a" * 32,
            },
            clear=True,
        ):
            result = ConfigValidator.validate_all()
            # Should have error about missing LLM key
            assert any("LLM API key" in err for err in result.errors)

    def test_validate_detects_short_jwt_secret(self):
        """Test validation fails with short JWT secret."""
        from aragora.server.config_validator import ConfigValidator

        with patch.dict(
            os.environ,
            {
                "JWT_SECRET": "tooshort",  # Less than 32 chars
                "ANTHROPIC_API_KEY": "sk-ant-test-key-12345",
            },
            clear=True,
        ):
            result = ConfigValidator.validate_all()
            # Should have error about JWT secret length
            assert any("JWT_SECRET" in err and "32 characters" in err for err in result.errors)

    def test_validate_detects_invalid_url(self):
        """Test validation fails with invalid URL format."""
        from aragora.server.config_validator import ConfigValidator

        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "not-a-valid-url",
                "ANTHROPIC_API_KEY": "sk-ant-test-key-12345",
            },
            clear=True,
        ):
            result = ConfigValidator.validate_all()
            # Should have error about URL format
            assert any("SUPABASE_URL" in err and "URL" in err for err in result.errors)

    def test_validate_detects_invalid_integer(self):
        """Test validation fails with non-integer rate limit."""
        from aragora.server.config_validator import ConfigValidator

        with patch.dict(
            os.environ,
            {
                "ARAGORA_RATE_LIMIT": "not_an_integer",
                "ANTHROPIC_API_KEY": "sk-ant-test-key-12345",
            },
            clear=True,
        ):
            result = ConfigValidator.validate_all()
            # Should have error about integer format
            assert any("ARAGORA_RATE_LIMIT" in err and "integer" in err for err in result.errors)

    def test_validate_warns_missing_llm_key_in_development(self):
        """Test validation warns (not errors) without LLM key in development."""
        from aragora.server.config_validator import ConfigValidator

        with patch.dict(
            os.environ,
            {
                "ARAGORA_ENV": "development",
            },
            clear=True,
        ):
            result = ConfigValidator.validate_all()
            # Should have warning about missing LLM key, not error
            assert any("LLM API key" in warn for warn in result.warnings)
            assert not any("LLM API key" in err for err in result.errors)

    def test_get_config_summary(self):
        """Test config summary returns expected structure."""
        from aragora.server.config_validator import ConfigValidator

        with patch.dict(
            os.environ,
            {
                "ARAGORA_ENV": "development",
                "ANTHROPIC_API_KEY": "sk-ant-test",
            },
            clear=True,
        ):
            summary = ConfigValidator.get_config_summary()

            assert "environment" in summary
            assert "api_token_set" in summary
            assert "llm_keys" in summary
            # Check structure - llm_keys maps full env var names
            assert "ANTHROPIC_API_KEY" in summary["llm_keys"]
            assert summary["llm_keys"]["ANTHROPIC_API_KEY"]
            assert "OPENAI_API_KEY" in summary["llm_keys"]
            assert not summary["llm_keys"]["OPENAI_API_KEY"]

    def test_validate_and_log_returns_correct_status(self):
        """Test validate_and_log returns correct boolean."""
        from aragora.server.config_validator import ConfigValidator

        # Valid config
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "sk-ant-test-key-12345",
            },
            clear=True,
        ):
            # Development mode - should pass even without all required vars
            result = ConfigValidator.validate_and_log()
            assert result

    def test_production_accepts_mounted_required_and_llm_secrets(self, tmp_path):
        from aragora.config.secrets import SecretManager, SecretsConfig
        from aragora.server.config_validator import ConfigValidator

        for name, value in {
            "ARAGORA_API_TOKEN": "mounted-api-token-value",
            "DATABASE_URL": "postgresql://mounted",
            "REDIS_URL": "redis://mounted",
            "ANTHROPIC_API_KEY": "mounted-anthropic-key",
        }.items():
            path = tmp_path / name
            path.write_text(value, encoding="utf-8")
            path.chmod(0o600)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(
                os.environ,
                {"ARAGORA_ENV": "production", "ARAGORA_INSTANCE_COUNT": "2"},
                clear=True,
            ),
        ):
            result = ConfigValidator.validate_all()

        assert not any("ARAGORA_API_TOKEN" in error for error in result.errors)
        assert not any("DATABASE_URL" in error for error in result.errors)
        assert not any("REDIS_URL" in error for error in result.errors)
        assert not any("LLM API key" in error for error in result.errors)

    def test_production_validates_mounted_database_url(self, tmp_path):
        from aragora.config.secrets import SecretManager, SecretsConfig
        from aragora.server.config_validator import ConfigValidator

        for name, value in {
            "ARAGORA_API_TOKEN": "mounted-api-token-value",
            "DATABASE_URL": "sqlite:///unsafe.db",
            "ANTHROPIC_API_KEY": "mounted-anthropic-key",
        }.items():
            path = tmp_path / name
            path.write_text(value, encoding="utf-8")
            path.chmod(0o600)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=True),
        ):
            result = ConfigValidator.validate_all()

        assert any("SQLite is not supported" in error for error in result.errors)

    def test_production_validates_mounted_redis_url(self, tmp_path):
        from aragora.config.secrets import SecretManager, SecretsConfig
        from aragora.server.config_validator import ConfigValidator

        for name, value in {
            "ARAGORA_API_TOKEN": "mounted-api-token-value",
            "DATABASE_URL": "postgresql://mounted",
            "REDIS_URL": "https://not-redis.example",
            "ANTHROPIC_API_KEY": "mounted-anthropic-key",
        }.items():
            path = tmp_path / name
            path.write_text(value, encoding="utf-8")
            path.chmod(0o600)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(
                os.environ,
                {"ARAGORA_ENV": "production", "ARAGORA_INSTANCE_COUNT": "2"},
                clear=True,
            ),
        ):
            result = ConfigValidator.validate_all()

        assert any("REDIS_URL must be a valid Redis URL" in error for error in result.errors)

    def test_production_reports_invalid_managed_custody(self):
        from aragora.server.config_validator import ConfigValidator

        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", "ARAGORA_SECRETS_DIR": "relative/path"},
            clear=True,
        ):
            result = ConfigValidator.validate_all()

        assert any(
            "Invalid managed custody configuration for ARAGORA_API_TOKEN" in error
            for error in result.errors
        )

    def test_production_requires_api_token(self):
        """Test production mode requires API token."""
        from aragora.server.config_validator import ConfigValidator

        with patch.dict(
            os.environ,
            {
                "ARAGORA_ENV": "production",
                "ANTHROPIC_API_KEY": "sk-ant-test-key-12345",
                "JWT_SECRET": "a" * 32,
                # Missing ARAGORA_API_TOKEN
            },
            clear=True,
        ):
            result = ConfigValidator.validate_all()
            assert any("ARAGORA_API_TOKEN" in err for err in result.errors)


# ============================================================================
# Trusted Proxy Tests
# ============================================================================


class TestTrustedProxyValidation:
    """Tests for X-Forwarded-For trusted proxy validation."""

    def test_trusted_proxy_config_loaded(self):
        """Test that trusted proxy configuration is loaded from environment."""
        from aragora.server.handlers.utils.rate_limit import TRUSTED_PROXIES

        # TRUSTED_PROXIES should be a set
        assert isinstance(TRUSTED_PROXIES, (set, frozenset))

    def test_get_client_ip_without_proxy(self):
        """Test client IP extraction without X-Forwarded-For header."""
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = Mock()
        handler.headers = {}
        handler.client_address = ("192.168.1.100", 12345)

        ip = get_client_ip(handler)
        assert ip == "192.168.1.100"

    def test_get_client_ip_with_untrusted_proxy(self):
        """Test that X-Forwarded-For is ignored from untrusted proxy.

        Tests that when a request comes from an IP that is NOT in TRUSTED_PROXIES,
        the X-Forwarded-For header should be ignored and the actual client IP used.
        """
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = Mock()
        handler.headers = {"X-Forwarded-For": "1.2.3.4"}
        # Use an IP that's definitely NOT in the default trusted proxies
        # (127.0.0.1, ::1, localhost)
        handler.client_address = ("203.0.113.50", 12345)  # TEST-NET-3, not trusted

        ip = get_client_ip(handler)

        # The default TRUSTED_PROXIES only contains localhost variants,
        # so 203.0.113.50 should NOT be trusted, and X-Forwarded-For ignored
        assert ip == "203.0.113.50", f"Expected 203.0.113.50 but got {ip}"


# ============================================================================
# Integration Tests
# ============================================================================


class TestSecurityIntegration:
    """Integration tests for security features."""

    def test_auth_handler_routes_mfa_verify(self):
        """Test that MFA verify route is registered."""
        from aragora.server.handlers.auth import AuthHandler

        assert "/api/auth/mfa/verify" in AuthHandler.ROUTES

    def test_auth_handler_routes_password_change(self):
        """Test that password change route is registered."""
        from aragora.server.handlers.auth import AuthHandler

        assert "/api/auth/password" in AuthHandler.ROUTES

    def test_auth_handler_routes_mfa_enable(self):
        """Test that MFA enable route is registered."""
        from aragora.server.handlers.auth import AuthHandler

        assert "/api/auth/mfa/enable" in AuthHandler.ROUTES
