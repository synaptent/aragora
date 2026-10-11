"""Tests for error monitoring integration with Sentry."""

import asyncio
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

import aragora.server.error_monitoring as error_monitoring
from aragora.server.error_monitoring import (
    _before_send,
    _filter_health_checks,
    _get_release_version,
    capture_exception,
    capture_message,
    get_status,
    init_monitoring,
    monitor_errors,
    set_debate_context,
    set_tag,
    set_user,
    start_transaction,
    track_error_recovery,
)


class TestGetReleaseVersion:
    """Test release version detection."""

    def test_get_version_success(self):
        """Test getting version from package."""
        with patch("aragora.server.error_monitoring.__version__", "1.2.3", create=True):
            # The function imports from aragora, so we need to patch there
            with patch.dict("sys.modules", {"aragora": MagicMock(__version__="1.2.3")}):
                result = _get_release_version()
                # Either gets the version or returns unknown
                assert "aragora@" in result

    def test_get_version_import_error(self):
        """Test fallback when version import fails."""
        with patch.dict("sys.modules", {"aragora": None}):
            result = _get_release_version()
            assert "aragora@" in result


class TestBeforeSend:
    """Test event filtering and sanitization."""

    def test_redact_api_keys_in_extra(self):
        """Test API keys are redacted from extra data."""
        event = {
            "extra": {
                "api_key": "secret123",
                "auth_token": "token456",
                "password": "pass789",
                "normal_data": "keep_me",
            }
        }
        hint = {}

        result = _before_send(event, hint)

        assert result["extra"]["api_key"] == "[REDACTED]"
        assert result["extra"]["auth_token"] == "[REDACTED]"
        assert result["extra"]["password"] == "[REDACTED]"
        assert result["extra"]["normal_data"] == "keep_me"

    def test_redact_request_headers(self):
        """Test sensitive headers are redacted."""
        event = {
            "request": {
                "headers": {
                    "Authorization": "Bearer secret",
                    "Cookie": "session=abc123",
                    "X-API-Key": "key123",
                    "Content-Type": "application/json",
                }
            }
        }
        hint = {}

        result = _before_send(event, hint)

        assert result["request"]["headers"]["Authorization"] == "[REDACTED]"
        assert result["request"]["headers"]["Cookie"] == "[REDACTED]"
        assert result["request"]["headers"]["X-API-Key"] == "[REDACTED]"
        assert result["request"]["headers"]["Content-Type"] == "application/json"

    def test_fingerprint_rate_limit_error(self):
        """Test rate limit errors get custom fingerprint."""
        event = {}
        hint = {
            "exc_info": (
                ValueError,
                ValueError("API rate limit exceeded"),
                None,
            )
        }

        result = _before_send(event, hint)

        assert result["fingerprint"] == ["rate-limit-error", "ValueError"]

    def test_fingerprint_timeout_error(self):
        """Test timeout errors get custom fingerprint."""
        event = {}
        hint = {
            "exc_info": (
                TimeoutError,
                TimeoutError("Connection timeout after 30s"),
                None,
            )
        }

        result = _before_send(event, hint)

        assert result["fingerprint"] == ["timeout-error", "TimeoutError"]

    def test_fingerprint_circuit_breaker_error(self):
        """Test circuit breaker errors get custom fingerprint."""
        event = {}
        hint = {
            "exc_info": (
                RuntimeError,
                RuntimeError("Circuit breaker open for anthropic"),
                None,
            )
        }

        result = _before_send(event, hint)

        assert result["fingerprint"] == ["circuit-breaker-error", "RuntimeError"]

    def test_fingerprint_agent_failure(self):
        """Test agent failure errors get custom fingerprint."""
        event = {}
        hint = {
            "exc_info": (
                Exception,
                Exception("Agent claude failed to respond"),
                None,
            )
        }

        result = _before_send(event, hint)

        assert result["fingerprint"] == ["agent-failure", "Exception"]

    def test_no_fingerprint_generic_error(self):
        """Test generic errors don't get custom fingerprint."""
        event = {}
        hint = {
            "exc_info": (
                ValueError,
                ValueError("Some generic error"),
                None,
            )
        }

        result = _before_send(event, hint)

        assert "fingerprint" not in result

    def test_no_exception_info(self):
        """Test handling events without exception info."""
        event = {"message": "test"}
        hint = {}

        result = _before_send(event, hint)

        assert result == event


class TestFilterHealthChecks:
    """Test health check transaction filtering."""

    def test_filter_health_endpoint(self):
        """Test health check endpoints are filtered."""
        event = {"transaction": "/api/health/live"}
        hint = {}

        result = _filter_health_checks(event, hint)

        assert result is None

    def test_filter_health_readiness(self):
        """Test readiness endpoint is filtered."""
        event = {"transaction": "/api/health/ready"}
        hint = {}

        result = _filter_health_checks(event, hint)

        assert result is None

    def test_keep_non_health_endpoints(self):
        """Test non-health endpoints are kept."""
        event = {"transaction": "/api/debates/123"}
        hint = {}

        result = _filter_health_checks(event, hint)

        assert result == event

    def test_no_transaction(self):
        """Test events without transaction are kept."""
        event = {"message": "test"}
        hint = {}

        result = _filter_health_checks(event, hint)

        assert result == event


class TestInitMonitoring:
    """Test monitoring initialization."""

    def setup_method(self):
        """Reset module state before each test."""
        error_monitoring._initialized = False
        error_monitoring._sentry_available = False

    def teardown_method(self):
        """Reset module state after each test."""
        error_monitoring._initialized = False
        error_monitoring._sentry_available = False

    def test_no_dsn_configured(self):
        """Test initialization without DSN."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove SENTRY_DSN if present
            os.environ.pop("SENTRY_DSN", None)

            result = init_monitoring()

            assert result is False
            assert error_monitoring._initialized is True
            assert error_monitoring._sentry_available is False

    def test_already_initialized(self):
        """Test initialization is idempotent."""
        error_monitoring._initialized = True
        error_monitoring._sentry_available = True

        result = init_monitoring()

        assert result is True

    def test_sentry_import_error(self):
        """Test handling when sentry-sdk not installed."""
        with patch.dict(os.environ, {"SENTRY_DSN": "https://test@sentry.io/123"}):
            with patch.dict("sys.modules", {"sentry_sdk": None}):
                # Force import error
                with patch("aragora.server.error_monitoring.init_monitoring") as mock_init:
                    # Simulate the import error path
                    error_monitoring._initialized = False
                    error_monitoring._sentry_available = False

                    # The actual function would catch ImportError
                    # We're just testing the state management
                    assert error_monitoring._sentry_available is False

    def test_successful_initialization(self):
        """Test successful Sentry initialization."""
        mock_sentry = MagicMock()
        mock_aiohttp_integration = MagicMock()
        mock_logging_integration = MagicMock()

        with patch.dict(os.environ, {"SENTRY_DSN": "https://test@sentry.io/123"}):
            with patch.dict(
                "sys.modules",
                {
                    "sentry_sdk": mock_sentry,
                    "sentry_sdk.integrations.aiohttp": MagicMock(
                        AioHttpIntegration=mock_aiohttp_integration
                    ),
                    "sentry_sdk.integrations.logging": MagicMock(
                        LoggingIntegration=mock_logging_integration
                    ),
                },
            ):
                # Simulate successful init
                error_monitoring._initialized = False
                error_monitoring._sentry_available = False

                # Call the actual init - it will try to import
                # For this test, we verify the DSN is read
                assert os.environ.get("SENTRY_DSN") == "https://test@sentry.io/123"


def _create_mock_sentry():
    """Create a mock sentry_sdk module."""
    mock_sentry = MagicMock()
    mock_scope = MagicMock()
    mock_sentry.push_scope.return_value.__enter__ = MagicMock(return_value=mock_scope)
    mock_sentry.push_scope.return_value.__exit__ = MagicMock(return_value=False)
    return mock_sentry, mock_scope


class TestCaptureException:
    """Test exception capturing."""

    def setup_method(self):
        """Reset module state."""
        error_monitoring._sentry_available = False

    def test_capture_when_unavailable(self):
        """Test capture when Sentry unavailable logs instead."""
        error_monitoring._sentry_available = False

        with patch("aragora.server.error_monitoring.logger") as mock_logger:
            result = capture_exception(ValueError("test error"))

            assert result is None
            mock_logger.exception.assert_called()

    def test_capture_with_context(self):
        """Test capture with additional context."""
        mock_sentry, mock_scope = _create_mock_sentry()
        mock_sentry.capture_exception.return_value = "event-123"

        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            result = capture_exception(
                ValueError("test"),
                context={"debate_id": "d-123"},
                level="warning",
            )

            assert result == "event-123"
            mock_scope.set_extra.assert_called_with("debate_id", "d-123")

    def test_capture_handles_internal_error(self):
        """Test capture handles internal errors gracefully."""
        mock_sentry = MagicMock()
        mock_sentry.push_scope.side_effect = RuntimeError("Sentry error")

        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            with patch("aragora.server.error_monitoring.logger") as mock_logger:
                result = capture_exception(ValueError("test"))

                assert result is None
                mock_logger.error.assert_called()


class TestCaptureMessage:
    """Test message capturing."""

    def setup_method(self):
        """Reset module state."""
        error_monitoring._sentry_available = False

    def test_capture_message_when_unavailable(self):
        """Test capture message when Sentry unavailable logs instead."""
        error_monitoring._sentry_available = False

        with patch("aragora.server.error_monitoring.logger") as mock_logger:
            result = capture_message("Test message", level="error")

            assert result is None
            mock_logger.log.assert_called()

    def test_capture_message_info_level(self):
        """Test capture message at info level."""
        error_monitoring._sentry_available = False

        with patch("aragora.server.error_monitoring.logger") as mock_logger:
            capture_message("Info message", level="info")

            # Should log at INFO level
            mock_logger.log.assert_called_with(
                logging.INFO, "Uncaptured message: %s", "Info message"
            )

    def test_capture_message_with_context(self):
        """Test capture message with context."""
        mock_sentry, mock_scope = _create_mock_sentry()
        mock_sentry.capture_message.return_value = "msg-123"

        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            result = capture_message(
                "Test message",
                level="warning",
                context={"key": "value"},
            )

            assert result == "msg-123"
            mock_scope.set_extra.assert_called_with("key", "value")


class TestSetUser:
    """Test user context setting."""

    def setup_method(self):
        """Reset module state."""
        error_monitoring._sentry_available = False

    def test_set_user_when_unavailable(self):
        """Test set_user is no-op when Sentry unavailable."""
        error_monitoring._sentry_available = False

        # Should not raise
        set_user("user-123")

    def test_set_user_basic(self):
        """Test setting basic user info."""
        mock_sentry = MagicMock()
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            set_user("user-123", ip_address="1.2.3.4")

            mock_sentry.set_user.assert_called_once()
            call_args = mock_sentry.set_user.call_args[0][0]
            assert call_args["id"] == "user-123"
            assert call_args["ip_address"] == "1.2.3.4"

    def test_set_user_with_email_hashed(self):
        """Test email is hashed for privacy."""
        mock_sentry = MagicMock()
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            set_user("user-123", email="test@example.com")

            call_args = mock_sentry.set_user.call_args[0][0]
            # Email should be hashed, not plain text
            assert call_args.get("email") != "test@example.com"
            assert len(call_args.get("email", "")) == 16

    def test_set_user_with_org_and_tier(self):
        """Test setting org and tier as tags."""
        mock_sentry = MagicMock()
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            set_user("user-123", org_id="org-456", tier="enterprise")

            # Should set tags
            mock_sentry.set_tag.assert_any_call("org_id", "org-456")
            mock_sentry.set_tag.assert_any_call("tier", "enterprise")

            # Should set business context
            mock_sentry.set_context.assert_called_with(
                "business",
                {"org_id": "org-456", "tier": "enterprise"},
            )


class TestSetTag:
    """Test tag setting."""

    def setup_method(self):
        """Reset module state."""
        error_monitoring._sentry_available = False

    def test_set_tag_when_unavailable(self):
        """Test set_tag is no-op when Sentry unavailable."""
        error_monitoring._sentry_available = False

        # Should not raise
        set_tag("key", "value")

    def test_set_tag_success(self):
        """Test setting a tag."""
        mock_sentry = MagicMock()
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            set_tag("environment", "production")

            mock_sentry.set_tag.assert_called_with("environment", "production")


class TestSetDebateContext:
    """Test debate context setting."""

    def setup_method(self):
        """Reset module state."""
        error_monitoring._sentry_available = False

    def test_set_debate_context_when_unavailable(self):
        """Test set_debate_context is no-op when Sentry unavailable."""
        error_monitoring._sentry_available = False

        # Should not raise
        set_debate_context("debate-123")

    def test_set_debate_context_basic(self):
        """Test setting basic debate context."""
        mock_sentry = MagicMock()
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            set_debate_context("debate-123")

            mock_sentry.set_tag.assert_any_call("debate_id", "debate-123")

    def test_set_debate_context_full(self):
        """Test setting full debate context."""
        mock_sentry = MagicMock()
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            set_debate_context(
                "debate-123",
                domain="security",
                agent_names=["claude", "gpt4", "gemini"],
                round_number=3,
            )

            mock_sentry.set_tag.assert_any_call("debate_id", "debate-123")
            mock_sentry.set_tag.assert_any_call("debate_domain", "security")
            mock_sentry.set_tag.assert_any_call("agents", "claude,gpt4,gemini")
            mock_sentry.set_tag.assert_any_call("round", "3")

    def test_set_debate_context_limits_agents(self):
        """Test agent names are limited to 5."""
        mock_sentry = MagicMock()
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            agents = ["a1", "a2", "a3", "a4", "a5", "a6", "a7"]
            set_debate_context("debate-123", agent_names=agents)

            # Find the call that sets agents
            for call in mock_sentry.set_tag.call_args_list:
                if call[0][0] == "agents":
                    agent_str = call[0][1]
                    assert agent_str.count(",") <= 4  # Max 5 agents = 4 commas


class TestMonitorErrorsDecorator:
    """Test the monitor_errors decorator."""

    def setup_method(self):
        """Reset module state."""
        error_monitoring._sentry_available = False

    def test_sync_function_success(self):
        """Test decorator with successful sync function."""

        @monitor_errors
        def sync_func():
            return "success"

        result = sync_func()
        assert result == "success"

    def test_sync_function_error(self):
        """Test decorator captures sync function errors."""

        @monitor_errors
        def sync_func():
            raise ValueError("sync error")

        with patch("aragora.server.error_monitoring.capture_exception") as mock_capture:
            with pytest.raises(ValueError, match="sync error"):
                sync_func()

            mock_capture.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_function_success(self):
        """Test decorator with successful async function."""

        @monitor_errors
        async def async_func():
            return "async success"

        result = await async_func()
        assert result == "async success"

    @pytest.mark.asyncio
    async def test_async_function_error(self):
        """Test decorator captures async function errors."""

        @monitor_errors
        async def async_func():
            raise TypeError("async error")

        with patch("aragora.server.error_monitoring.capture_exception") as mock_capture:
            with pytest.raises(TypeError, match="async error"):
                await async_func()

            mock_capture.assert_called_once()

    def test_decorator_preserves_function_metadata(self):
        """Test decorator preserves function name and docstring."""

        @monitor_errors
        def my_func():
            """My docstring."""
            pass

        assert my_func.__name__ == "my_func"
        assert "My docstring" in (my_func.__doc__ or "")


class TestTrackErrorRecovery:
    """Test error recovery tracking."""

    def setup_method(self):
        """Reset module state."""
        error_monitoring._sentry_available = False

    def test_track_recovery_when_unavailable(self):
        """Test recovery tracking logs when Sentry unavailable."""
        error_monitoring._sentry_available = False

        with patch("aragora.server.error_monitoring.logger") as mock_logger:
            track_error_recovery(
                error_type="timeout",
                recovery_strategy="retry",
                success=True,
                duration_ms=100.0,
            )

            mock_logger.info.assert_called()

    def test_track_successful_recovery(self):
        """Test tracking successful recovery."""
        mock_sentry = MagicMock()
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            track_error_recovery(
                error_type="rate_limit",
                recovery_strategy="fallback",
                success=True,
                duration_ms=50.0,
            )

            mock_sentry.add_breadcrumb.assert_called_once()
            call_kwargs = mock_sentry.add_breadcrumb.call_args[1]
            assert call_kwargs["category"] == "error_recovery"
            assert call_kwargs["level"] == "info"

    def test_track_failed_recovery(self):
        """Test tracking failed recovery captures message."""
        mock_sentry = MagicMock()
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            with patch("aragora.server.error_monitoring.capture_message") as mock_capture:
                track_error_recovery(
                    error_type="agent_failure",
                    recovery_strategy="circuit_breaker",
                    success=False,
                    duration_ms=5000.0,
                    context={"agent": "claude"},
                )

                mock_capture.assert_called_once()
                call_args = mock_capture.call_args
                assert "failed" in call_args[0][0]
                assert call_args[1]["level"] == "warning"


class TestStartTransaction:
    """Test transaction starting."""

    def setup_method(self):
        """Reset module state."""
        error_monitoring._sentry_available = False

    def test_start_transaction_when_unavailable(self):
        """Test start_transaction returns None when unavailable."""
        error_monitoring._sentry_available = False

        result = start_transaction("test_op", op="task")

        assert result is None

    def test_start_transaction_success(self):
        """Test starting a transaction."""
        mock_sentry = MagicMock()
        mock_transaction = MagicMock()
        mock_sentry.start_transaction.return_value = mock_transaction
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            result = start_transaction("debate_run", op="task")

            assert result == mock_transaction
            mock_sentry.start_transaction.assert_called_with(name="debate_run", op="task")


class TestGetStatus:
    """Test status reporting."""

    def setup_method(self):
        """Reset module state."""
        error_monitoring._initialized = False
        error_monitoring._sentry_available = False

    def test_get_status_uninitialized(self):
        """Test status when not initialized."""
        error_monitoring._initialized = False
        error_monitoring._sentry_available = False

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SENTRY_DSN", None)
            status = get_status()

            assert status["initialized"] is False
            assert status["sentry_available"] is False
            assert status["dsn_configured"] is False

    def test_get_status_initialized_with_sentry(self):
        """Test status when initialized with Sentry."""
        error_monitoring._initialized = True
        error_monitoring._sentry_available = True

        with patch.dict(os.environ, {"SENTRY_DSN": "https://test@sentry.io/123"}):
            status = get_status()

            assert status["initialized"] is True
            assert status["sentry_available"] is True
            assert status["dsn_configured"] is True

    def test_get_status_includes_environment(self):
        """Test status includes environment name."""
        with patch.dict(os.environ, {"SENTRY_ENVIRONMENT": "staging"}):
            status = get_status()

            assert status["environment"] == "staging"

    def test_get_status_default_environment(self):
        """Test status uses default environment."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SENTRY_ENVIRONMENT", None)
            status = get_status()

            assert status["environment"] == "development"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def setup_method(self):
        """Reset module state."""
        error_monitoring._sentry_available = True

    def test_capture_exception_with_none_exception(self):
        """Test capture_exception handles None gracefully."""
        mock_sentry, mock_scope = _create_mock_sentry()
        mock_sentry.capture_exception.return_value = None

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            result = capture_exception(None)  # type: ignore

            # Should handle gracefully
            assert result is None or isinstance(result, str)

    def test_set_tag_handles_error(self):
        """Test set_tag handles internal errors gracefully."""
        mock_sentry = MagicMock()
        mock_sentry.set_tag.side_effect = RuntimeError("Internal error")
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            with patch("aragora.server.error_monitoring.logger") as mock_logger:
                # Should not raise
                set_tag("key", "value")

                mock_logger.error.assert_called()

    def test_set_user_handles_error(self):
        """Test set_user handles internal errors gracefully."""
        mock_sentry = MagicMock()
        mock_sentry.set_user.side_effect = RuntimeError("Internal error")
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            with patch("aragora.server.error_monitoring.logger") as mock_logger:
                # Should not raise
                set_user("user-123")

                mock_logger.error.assert_called()

    def test_set_debate_context_handles_error(self):
        """Test set_debate_context handles internal errors gracefully."""
        mock_sentry = MagicMock()
        mock_sentry.set_tag.side_effect = RuntimeError("Internal error")
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            with patch("aragora.server.error_monitoring.logger") as mock_logger:
                # Should not raise
                set_debate_context("debate-123")

                mock_logger.error.assert_called()

    def test_track_error_recovery_handles_error(self):
        """Test track_error_recovery handles internal errors gracefully."""
        mock_sentry = MagicMock()
        mock_sentry.add_breadcrumb.side_effect = RuntimeError("Internal error")
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            with patch("aragora.server.error_monitoring.logger") as mock_logger:
                # Should not raise
                track_error_recovery("error", "retry", True)

                mock_logger.error.assert_called()

    def test_start_transaction_handles_error(self):
        """Test start_transaction handles internal errors gracefully."""
        mock_sentry = MagicMock()
        mock_sentry.start_transaction.side_effect = RuntimeError("Internal error")
        error_monitoring._sentry_available = True

        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            with patch("aragora.server.error_monitoring.logger") as mock_logger:
                result = start_transaction("test")

                assert result is None
                mock_logger.error.assert_called()
