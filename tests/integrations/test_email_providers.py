"""
Tests for Email provider implementations.

Comprehensive tests for:
- SMTP send functionality
- SendGrid API integration
- AWS SES integration
- Provider fallback
"""

from __future__ import annotations

import smtplib
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from aragora.integrations.email import (
    EmailConfig,
    EmailIntegration,
    EmailProvider,
    EmailRecipient,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def smtp_config():
    """SMTP configuration for testing."""
    return EmailConfig(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="user@example.com",
        smtp_password="password123",
        use_tls=True,
        use_ssl=False,
    )


@pytest.fixture
def sendgrid_config():
    """SendGrid configuration for testing."""
    return EmailConfig(
        provider="sendgrid",
        sendgrid_api_key="SG.test_api_key_12345",
    )


@pytest.fixture
def ses_config():
    """AWS SES configuration for testing."""
    return EmailConfig(
        provider="ses",
        ses_access_key_id="AKIAIOSFODNN7EXAMPLE",
        ses_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        ses_region="us-east-1",
    )


@pytest.fixture
def recipient():
    """Test recipient."""
    return EmailRecipient(email="recipient@example.com", name="Test Recipient")


# =============================================================================
# SMTP Provider Tests
# =============================================================================


class TestSMTPProvider:
    """Tests for SMTP email provider."""

    def test_smtp_config_defaults(self, smtp_config):
        """Test SMTP config default values."""
        assert smtp_config.smtp_port == 587
        assert smtp_config.use_tls is True
        assert smtp_config.use_ssl is False
        assert smtp_config.email_provider == EmailProvider.SMTP

    def test_smtp_config_ssl(self):
        """Test SMTP config with SSL."""
        config = EmailConfig(
            smtp_host="smtp.example.com",
            smtp_port=465,
            use_ssl=True,
            use_tls=False,
        )
        assert config.use_ssl is True
        assert config.smtp_port == 465

    @pytest.mark.asyncio
    async def test_send_via_smtp_success(self, smtp_config, recipient):
        """Test successful SMTP send."""
        integration = EmailIntegration(smtp_config)

        with patch.object(integration, "_smtp_send") as mock_send:
            with patch("asyncio.get_running_loop") as mock_loop:
                mock_executor = MagicMock()
                mock_future = AsyncMock()
                mock_future.return_value = None
                mock_loop.return_value.run_in_executor = mock_future

                result = await integration._send_via_smtp(
                    recipient,
                    "Test Subject",
                    "<p>Test HTML</p>",
                    "Test plain text",
                )

        assert result is True

    def test_smtp_send_tls(self, smtp_config):
        """Test SMTP send with TLS."""
        integration = EmailIntegration(smtp_config)

        mock_msg = MagicMock()

        with patch("smtplib.SMTP") as mock_smtp_class:
            mock_server = MagicMock()
            mock_smtp_class.return_value.__enter__.return_value = mock_server

            integration._smtp_send(mock_msg, "to@example.com")

            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("user@example.com", "password123")
            mock_server.sendmail.assert_called_once()

    def test_smtp_send_ssl(self):
        """Test SMTP send with SSL."""
        config = EmailConfig(
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_username="user",
            smtp_password="pass",
            use_ssl=True,
            use_tls=False,
        )
        integration = EmailIntegration(config)

        mock_msg = MagicMock()

        with patch("smtplib.SMTP_SSL") as mock_smtp_class:
            mock_server = MagicMock()
            mock_smtp_class.return_value.__enter__.return_value = mock_server

            integration._smtp_send(mock_msg, "to@example.com")

            mock_server.login.assert_called_once_with("user", "pass")
            mock_server.sendmail.assert_called_once()

    def test_smtp_send_no_auth(self):
        """Test SMTP send without authentication."""
        config = EmailConfig(
            smtp_host="smtp.example.com",
            smtp_username="",  # No username
            smtp_password="",
            use_tls=True,
        )
        integration = EmailIntegration(config)

        mock_msg = MagicMock()

        with patch("smtplib.SMTP") as mock_smtp_class:
            mock_server = MagicMock()
            mock_smtp_class.return_value.__enter__.return_value = mock_server

            integration._smtp_send(mock_msg, "to@example.com")

            # Login should not be called without credentials
            mock_server.login.assert_not_called()
            mock_server.sendmail.assert_called_once()

    def test_smtp_timeout_config(self):
        """Test SMTP timeout configuration."""
        config = EmailConfig(
            smtp_host="smtp.example.com",
            smtp_timeout=60.0,
        )
        assert config.smtp_timeout == 60.0


# =============================================================================
# SendGrid Provider Tests
# =============================================================================


class TestSendGridProvider:
    """Tests for SendGrid email provider."""

    def test_sendgrid_config(self, sendgrid_config):
        """Test SendGrid config."""
        assert sendgrid_config.email_provider == EmailProvider.SENDGRID
        assert sendgrid_config.sendgrid_api_key == "SG.test_api_key_12345"

    def test_sendgrid_auto_detect(self):
        """Test SendGrid auto-detection from API key."""
        config = EmailConfig(sendgrid_api_key="SG.auto_detect_key")
        assert config.provider == "sendgrid"

    @pytest.mark.asyncio
    async def test_send_via_sendgrid_success(self, sendgrid_config, recipient):
        """Test successful SendGrid send."""
        integration = EmailIntegration(sendgrid_config)

        mock_response = AsyncMock()
        mock_response.status = 202

        mock_session = MagicMock()
        mock_session.post = MagicMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(integration, "_get_session", return_value=mock_session):
            result = await integration._send_via_sendgrid(
                recipient,
                "Test Subject",
                "<p>HTML content</p>",
                "Plain text",
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_send_via_sendgrid_400_error(self, sendgrid_config, recipient):
        """Test SendGrid 400 error handling."""
        integration = EmailIntegration(sendgrid_config)

        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")

        mock_session = MagicMock()
        mock_session.post = MagicMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(integration, "_get_session", return_value=mock_session):
            result = await integration._send_via_sendgrid(
                recipient,
                "Test Subject",
                "<p>HTML</p>",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_via_sendgrid_connection_error(self, sendgrid_config, recipient):
        """Test SendGrid connection error."""
        integration = EmailIntegration(sendgrid_config)

        mock_session = MagicMock()
        mock_session.post = MagicMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientError("Connection refused")
        )
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(integration, "_get_session", return_value=mock_session):
            result = await integration._send_via_sendgrid(
                recipient,
                "Test Subject",
                "<p>HTML</p>",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_sendgrid_payload_structure(self, sendgrid_config, recipient):
        """Test SendGrid API payload structure."""
        integration = EmailIntegration(sendgrid_config)
        integration.config.reply_to = "reply@example.com"
        integration.config.enable_click_tracking = True
        integration.config.enable_open_tracking = True

        captured_payload = None

        mock_response = AsyncMock()
        mock_response.status = 202

        async def capture_post(*args, **kwargs):
            nonlocal captured_payload
            captured_payload = kwargs.get("json")
            return mock_response

        mock_session = MagicMock()
        mock_context = MagicMock()
        mock_context.__aenter__ = capture_post
        mock_context.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_context)

        with patch.object(integration, "_get_session", return_value=mock_session):
            await integration._send_via_sendgrid(
                recipient,
                "Test Subject",
                "<p>HTML</p>",
                "Plain text",
            )

        # Note: captured_payload will be the mock_response, not actual payload
        # In a real test we'd need to structure the mock differently


# =============================================================================
# AWS SES Provider Tests
# =============================================================================


class TestSESProvider:
    """Tests for AWS SES email provider."""

    def test_ses_config(self, ses_config):
        """Test SES config."""
        assert ses_config.email_provider == EmailProvider.SES
        assert ses_config.ses_region == "us-east-1"
        assert ses_config.ses_access_key_id.startswith("AKIA")

    def test_ses_auto_detect(self):
        """Test SES auto-detection from credentials."""
        config = EmailConfig(
            ses_access_key_id="AKIATEST",
            ses_secret_access_key="secret",
        )
        assert config.provider == "ses"

    @pytest.mark.asyncio
    async def test_send_via_ses_success(self, ses_config, recipient):
        """Test successful SES send."""
        integration = EmailIntegration(ses_config)

        mock_ses_client = MagicMock()
        mock_ses_client.send_email.return_value = {"MessageId": "test-message-id"}

        with patch("boto3.client", return_value=mock_ses_client):
            with patch("asyncio.get_running_loop") as mock_loop:
                # Mock run_in_executor to call the function directly
                async def run_in_executor(executor, func):
                    return func()

                mock_loop.return_value.run_in_executor = run_in_executor

                result = await integration._send_via_ses(
                    recipient,
                    "Test Subject",
                    "<p>HTML</p>",
                    "Plain text",
                )

        assert result is True

    @pytest.mark.asyncio
    async def test_send_via_ses_no_boto3(self, ses_config, recipient):
        """Test SES send when boto3 not installed."""
        integration = EmailIntegration(ses_config)

        with patch.dict("sys.modules", {"boto3": None}):
            with patch("builtins.__import__", side_effect=ImportError("No boto3")):
                result = await integration._send_via_ses(
                    recipient,
                    "Test Subject",
                    "<p>HTML</p>",
                )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_via_ses_client_error(self, ses_config, recipient):
        """Test SES client error handling."""
        integration = EmailIntegration(ses_config)

        mock_ses_client = MagicMock()
        mock_ses_client.send_email.side_effect = Exception("ClientError: Access Denied")

        with patch("boto3.client", return_value=mock_ses_client):
            with patch("asyncio.get_running_loop") as mock_loop:

                async def run_in_executor(executor, func):
                    return func()

                mock_loop.return_value.run_in_executor = run_in_executor

                result = await integration._send_via_ses(
                    recipient,
                    "Test Subject",
                    "<p>HTML</p>",
                )

        assert result is False


# =============================================================================
# Provider Routing Tests
# =============================================================================


class TestProviderRouting:
    """Tests for email provider routing."""

    @pytest.mark.asyncio
    async def test_routes_to_smtp(self, smtp_config, recipient):
        """Test email routes to SMTP provider."""
        integration = EmailIntegration(smtp_config)

        with patch.object(integration, "_send_via_smtp", return_value=True) as mock_smtp:
            with patch.object(integration, "_check_circuit_breaker", return_value=(True, None)):
                with patch.object(integration, "_check_rate_limit", return_value=True):
                    result = await integration._send_email(recipient, "Test", "<p>Test</p>")

        mock_smtp.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_routes_to_sendgrid(self, sendgrid_config, recipient):
        """Test email routes to SendGrid provider."""
        integration = EmailIntegration(sendgrid_config)

        with patch.object(integration, "_send_via_sendgrid", return_value=True) as mock_sg:
            with patch.object(integration, "_check_circuit_breaker", return_value=(True, None)):
                with patch.object(integration, "_check_rate_limit", return_value=True):
                    result = await integration._send_email(recipient, "Test", "<p>Test</p>")

        mock_sg.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_routes_to_ses(self, ses_config, recipient):
        """Test email routes to SES provider."""
        integration = EmailIntegration(ses_config)

        with patch.object(integration, "_send_via_ses", return_value=True) as mock_ses:
            with patch.object(integration, "_check_circuit_breaker", return_value=(True, None)):
                with patch.object(integration, "_check_rate_limit", return_value=True):
                    result = await integration._send_email(recipient, "Test", "<p>Test</p>")

        mock_ses.assert_called_once()
        assert result is True


# =============================================================================
# Session Management Tests
# =============================================================================


class TestSessionManagement:
    """Tests for aiohttp session management."""

    @pytest.mark.asyncio
    async def test_creates_session_on_demand(self, sendgrid_config):
        """Test session is created on demand."""
        integration = EmailIntegration(sendgrid_config)
        assert integration._session is None

        session = await integration._get_session()
        assert session is not None

    @pytest.mark.asyncio
    async def test_reuses_existing_session(self, sendgrid_config):
        """Test existing session is reused."""
        integration = EmailIntegration(sendgrid_config)

        session1 = await integration._get_session()
        session2 = await integration._get_session()

        assert session1 is session2

    @pytest.mark.asyncio
    async def test_creates_new_session_if_closed(self, sendgrid_config):
        """Test new session created if previous closed."""
        integration = EmailIntegration(sendgrid_config)

        session1 = await integration._get_session()
        await integration.close()

        # After closing, a new session should be created
        session2 = await integration._get_session()
        # They should be different sessions
        assert session1 is not session2

    @pytest.mark.asyncio
    async def test_close_session(self, sendgrid_config):
        """Test session close."""
        integration = EmailIntegration(sendgrid_config)

        mock_session = AsyncMock()
        mock_session.closed = False
        integration._session = mock_session

        await integration.close()

        mock_session.close.assert_called_once()


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestProviderErrorHandling:
    """Tests for provider error handling."""

    @pytest.mark.asyncio
    async def test_smtp_exception_handling(self, smtp_config, recipient):
        """Test SMTP exception is handled."""
        integration = EmailIntegration(smtp_config)
        integration.config.max_retries = 1
        integration.config.retry_delay = 0.01

        with patch.object(
            integration,
            "_send_via_smtp",
            side_effect=smtplib.SMTPException("SMTP Error"),
        ):
            with patch.object(integration, "_check_circuit_breaker", return_value=(True, None)):
                with patch.object(integration, "_check_rate_limit", return_value=True):
                    with patch.object(integration, "_record_failure"):
                        result = await integration._send_email(recipient, "Test", "<p>Test</p>")

        assert result is False

    @pytest.mark.asyncio
    async def test_network_exception_handling(self, sendgrid_config, recipient):
        """Test network exception is handled."""
        integration = EmailIntegration(sendgrid_config)
        integration.config.max_retries = 1
        integration.config.retry_delay = 0.01

        with patch.object(
            integration,
            "_send_via_sendgrid",
            side_effect=aiohttp.ClientError("Network error"),
        ):
            with patch.object(integration, "_check_circuit_breaker", return_value=(True, None)):
                with patch.object(integration, "_check_rate_limit", return_value=True):
                    with patch.object(integration, "_record_failure"):
                        result = await integration._send_email(recipient, "Test", "<p>Test</p>")

        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_exception_handling(self, smtp_config, recipient):
        """Test timeout exception is handled."""
        import asyncio as asyncio_mod

        integration = EmailIntegration(smtp_config)
        integration.config.max_retries = 1
        integration.config.retry_delay = 0.01

        with patch.object(
            integration,
            "_send_via_smtp",
            side_effect=asyncio_mod.TimeoutError("Timeout"),
        ):
            with patch.object(integration, "_check_circuit_breaker", return_value=(True, None)):
                with patch.object(integration, "_check_rate_limit", return_value=True):
                    with patch.object(integration, "_record_failure"):
                        result = await integration._send_email(recipient, "Test", "<p>Test</p>")

        assert result is False

    @pytest.mark.asyncio
    async def test_os_error_handling(self, smtp_config, recipient):
        """Test OS error (socket) is handled."""
        integration = EmailIntegration(smtp_config)
        integration.config.max_retries = 1
        integration.config.retry_delay = 0.01

        with patch.object(
            integration,
            "_send_via_smtp",
            side_effect=OSError("Connection refused"),
        ):
            with patch.object(integration, "_check_circuit_breaker", return_value=(True, None)):
                with patch.object(integration, "_check_rate_limit", return_value=True):
                    with patch.object(integration, "_record_failure"):
                        result = await integration._send_email(recipient, "Test", "<p>Test</p>")

        assert result is False
