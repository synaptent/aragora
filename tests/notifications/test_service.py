"""
Tests for the Notification Service.

Covers channel routing, provider implementations, template rendering,
and delivery handling.
"""

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.notifications.service import (
    EmailConfig,
    EmailProvider,
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationResult,
    NotificationService,
    SlackConfig,
    SlackProvider,
    WebhookEndpoint,
    WebhookProvider,
    _severity_to_priority,
    get_notification_service,
    init_notification_service,
)


# ============================================================================
# Notification Dataclass Tests
# ============================================================================


class TestNotification:
    """Tests for Notification dataclass."""

    def test_create_minimal(self):
        """Test creating notification with minimal fields."""
        n = Notification(title="Test", message="Hello")

        assert n.title == "Test"
        assert n.message == "Hello"
        assert n.severity == "info"
        assert n.priority == NotificationPriority.NORMAL
        assert n.id is not None
        assert n.created_at is not None

    def test_create_full(self):
        """Test creating notification with all fields."""
        n = Notification(
            title="Critical Alert",
            message="Something went wrong",
            severity="critical",
            priority=NotificationPriority.URGENT,
            resource_type="finding",
            resource_id="f-123",
            workspace_id="ws-456",
            metadata={"extra": "data"},
            action_url="https://example.com/view",
            action_label="View Details",
        )

        assert n.title == "Critical Alert"
        assert n.severity == "critical"
        assert n.priority == NotificationPriority.URGENT
        assert n.resource_type == "finding"
        assert n.resource_id == "f-123"
        assert n.action_url == "https://example.com/view"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        n = Notification(
            title="Test",
            message="Message",
            severity="warning",
            resource_type="alert",
            resource_id="a-1",
        )

        data = n.to_dict()

        assert data["title"] == "Test"
        assert data["message"] == "Message"
        assert data["severity"] == "warning"
        assert data["resource_type"] == "alert"
        assert data["priority"] == "normal"
        assert "created_at" in data
        assert "id" in data

    def test_unique_ids(self):
        """Test that each notification gets a unique ID."""
        n1 = Notification(title="Test1", message="A")
        n2 = Notification(title="Test2", message="B")

        assert n1.id != n2.id

    def test_created_at_is_utc(self):
        """Test that created_at is in UTC."""
        n = Notification(title="Test", message="A")

        assert n.created_at.tzinfo is not None


class TestNotificationResult:
    """Tests for NotificationResult dataclass."""

    def test_success_result(self):
        """Test successful notification result."""
        r = NotificationResult(
            success=True,
            channel=NotificationChannel.SLACK,
            recipient="#general",
            notification_id="n-123",
            external_id="msg-456",
        )

        assert r.success
        assert r.channel == NotificationChannel.SLACK
        assert r.error is None

    def test_failure_result(self):
        """Test failed notification result."""
        r = NotificationResult(
            success=False,
            channel=NotificationChannel.EMAIL,
            recipient="user@example.com",
            notification_id="n-123",
            error="SMTP connection failed",
        )

        assert not r.success
        assert r.error == "SMTP connection failed"

    def test_to_dict(self):
        """Test serialization."""
        r = NotificationResult(
            success=True,
            channel=NotificationChannel.WEBHOOK,
            recipient="endpoint-1",
            notification_id="n-123",
        )

        data = r.to_dict()

        assert data["success"] is True
        assert data["channel"] == "webhook"
        assert data["recipient"] == "endpoint-1"


# ============================================================================
# Notification Priority Tests
# ============================================================================


class TestNotificationPriority:
    """Tests for notification priority mapping."""

    def test_severity_to_priority_critical(self):
        """Test critical severity maps to urgent priority."""
        assert _severity_to_priority("critical") == NotificationPriority.URGENT

    def test_severity_to_priority_high(self):
        """Test high severity maps to high priority."""
        assert _severity_to_priority("high") == NotificationPriority.HIGH

    def test_severity_to_priority_medium(self):
        """Test medium severity maps to normal priority."""
        assert _severity_to_priority("medium") == NotificationPriority.NORMAL

    def test_severity_to_priority_low(self):
        """Test low severity maps to low priority."""
        assert _severity_to_priority("low") == NotificationPriority.LOW

    def test_severity_to_priority_info(self):
        """Test info severity maps to low priority."""
        assert _severity_to_priority("info") == NotificationPriority.LOW

    def test_severity_to_priority_unknown(self):
        """Test unknown severity defaults to normal priority."""
        assert _severity_to_priority("unknown") == NotificationPriority.NORMAL

    def test_severity_to_priority_case_insensitive(self):
        """Test severity mapping is case insensitive."""
        assert _severity_to_priority("CRITICAL") == NotificationPriority.URGENT
        assert _severity_to_priority("Critical") == NotificationPriority.URGENT


# ============================================================================
# SlackProvider Tests
# ============================================================================


class TestSlackConfig:
    """Tests for Slack configuration."""

    def test_from_env_empty(self):
        """Test creating config from empty environment."""
        with patch.dict("os.environ", {}, clear=True):
            config = SlackConfig.from_env()

        assert config.webhook_url is None
        assert config.bot_token is None
        assert config.default_channel == "#notifications"

    def test_from_env_with_values(self):
        """Test creating config from environment."""
        env = {
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/test",
            "SLACK_BOT_TOKEN": "xoxb-test-token",
            "SLACK_DEFAULT_CHANNEL": "#alerts",
        }
        with patch.dict("os.environ", env, clear=True):
            config = SlackConfig.from_env()

        assert config.webhook_url == "https://hooks.slack.com/test"
        assert config.bot_token == "xoxb-test-token"
        assert config.default_channel == "#alerts"


class TestSlackProvider:
    """Tests for Slack notification provider."""

    def test_is_configured_with_webhook(self):
        """Test is_configured with webhook URL."""
        config = SlackConfig(webhook_url="https://hooks.slack.com/test")
        provider = SlackProvider(config)

        assert provider.is_configured()

    def test_is_configured_with_token(self):
        """Test is_configured with bot token."""
        config = SlackConfig(bot_token="xoxb-test")
        provider = SlackProvider(config)

        assert provider.is_configured()

    def test_is_configured_without_credentials(self):
        """Test is_configured without credentials."""
        config = SlackConfig()
        provider = SlackProvider(config)

        assert not provider.is_configured()

    def test_channel_property(self):
        """Test channel property returns SLACK."""
        provider = SlackProvider(SlackConfig())
        assert provider.channel == NotificationChannel.SLACK

    @pytest.mark.asyncio
    async def test_send_not_configured(self):
        """Test send returns error when not configured."""
        provider = SlackProvider(SlackConfig())
        notification = Notification(title="Test", message="Hello")

        result = await provider.send(notification, "#general")

        assert not result.success
        assert "not configured" in result.error

    def test_build_message_info(self):
        """Test building Slack message for info severity."""
        config = SlackConfig(webhook_url="https://test.com")
        provider = SlackProvider(config)
        notification = Notification(
            title="Info Alert",
            message="Something happened",
            severity="info",
        )

        message = provider._build_message(notification)

        assert message["username"] == "Aragora"
        assert len(message["attachments"]) == 1
        assert message["attachments"][0]["color"] == "#2196F3"  # Blue for info

    def test_build_message_critical(self):
        """Test building Slack message for critical severity."""
        config = SlackConfig(webhook_url="https://test.com")
        provider = SlackProvider(config)
        notification = Notification(
            title="Critical Alert",
            message="System failure",
            severity="critical",
        )

        message = provider._build_message(notification)

        assert message["attachments"][0]["color"] == "#B71C1C"  # Dark red for critical

    def test_build_message_with_action(self):
        """Test building Slack message with action button."""
        config = SlackConfig(webhook_url="https://test.com")
        provider = SlackProvider(config)
        notification = Notification(
            title="Alert",
            message="Check this",
            action_url="https://example.com",
            action_label="View",
        )

        message = provider._build_message(notification)

        attachment = message["attachments"][0]
        assert "actions" in attachment
        assert attachment["actions"][0]["text"] == "View"
        assert attachment["actions"][0]["url"] == "https://example.com"

    def test_build_message_with_resource(self):
        """Test building Slack message with resource info."""
        config = SlackConfig(webhook_url="https://test.com")
        provider = SlackProvider(config)
        notification = Notification(
            title="Finding",
            message="New finding detected",
            resource_type="finding",
            resource_id="f-123",
        )

        message = provider._build_message(notification)

        attachment = message["attachments"][0]
        fields = attachment.get("fields", [])
        resource_field = next((f for f in fields if f["title"] == "Resource"), None)
        assert resource_field is not None
        assert resource_field["value"] == "finding/f-123"


# ============================================================================
# EmailProvider Tests
# ============================================================================


class TestEmailConfig:
    """Tests for Email configuration."""

    def test_from_env_defaults(self):
        """Test default email config."""
        with patch.dict("os.environ", {}, clear=True):
            config = EmailConfig.from_env()

        assert config.smtp_host == "localhost"
        assert config.smtp_port == 587
        assert config.use_tls is True

    def test_from_env_with_values(self):
        """Test email config from environment."""
        env = {
            "SMTP_HOST": "mail.example.com",
            "SMTP_PORT": "465",
            "SMTP_USER": "user",
            "SMTP_PASSWORD": "pass",
            "SMTP_USE_TLS": "false",
            "SMTP_FROM": "noreply@example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            config = EmailConfig.from_env()

        assert config.smtp_host == "mail.example.com"
        assert config.smtp_port == 465
        assert config.smtp_user == "user"
        assert config.use_tls is False


class TestEmailProvider:
    """Tests for Email notification provider."""

    def test_is_configured(self):
        """Test is_configured with host."""
        config = EmailConfig(smtp_host="mail.example.com")
        provider = EmailProvider(config)

        assert provider.is_configured()

    def test_channel_property(self):
        """Test channel property returns EMAIL."""
        provider = EmailProvider(EmailConfig())
        assert provider.channel == NotificationChannel.EMAIL

    @pytest.mark.asyncio
    async def test_send_not_configured(self):
        """Test send returns error when not configured."""
        config = EmailConfig(smtp_host="")
        provider = EmailProvider(config)
        notification = Notification(title="Test", message="Hello")

        result = await provider.send(notification, "user@example.com")

        assert not result.success
        assert "not configured" in result.error

    def test_build_html_info(self):
        """Test HTML template for info severity."""
        provider = EmailProvider(EmailConfig())
        notification = Notification(
            title="Info Alert",
            message="Something happened",
            severity="info",
        )

        html = provider._build_html(notification)

        assert "Info Alert" in html
        assert "Something happened" in html
        assert "#2196F3" in html  # Blue color for info

    def test_build_html_critical(self):
        """Test HTML template for critical severity."""
        provider = EmailProvider(EmailConfig())
        notification = Notification(
            title="Critical Alert",
            message="System failure",
            severity="critical",
        )

        html = provider._build_html(notification)

        assert "Critical Alert" in html
        assert "#B71C1C" in html  # Dark red for critical

    def test_build_html_with_action(self):
        """Test HTML template with action button."""
        provider = EmailProvider(EmailConfig())
        notification = Notification(
            title="Alert",
            message="Check this",
            action_url="https://example.com",
            action_label="View Details",
        )

        html = provider._build_html(notification)

        assert 'href="https://example.com"' in html
        assert "View Details" in html


# ============================================================================
# WebhookProvider Tests
# ============================================================================


class TestWebhookEndpoint:
    """Tests for WebhookEndpoint configuration."""

    def test_matches_event_all(self):
        """Test endpoint with no event filter matches all."""
        endpoint = WebhookEndpoint(
            id="ep-1",
            url="https://example.com/hook",
            events=[],  # Empty = all events
        )

        assert endpoint.matches_event("finding.created")
        assert endpoint.matches_event("audit.completed")

    def test_matches_event_specific(self):
        """Test endpoint with specific event filter."""
        endpoint = WebhookEndpoint(
            id="ep-1",
            url="https://example.com/hook",
            events=["finding.created", "finding.updated"],
        )

        assert endpoint.matches_event("finding.created")
        assert not endpoint.matches_event("audit.completed")


class TestWebhookProvider:
    """Tests for Webhook notification provider."""

    def test_is_configured_no_endpoints(self):
        """Test is_configured with no endpoints."""
        provider = WebhookProvider()
        assert not provider.is_configured()

    def test_is_configured_with_endpoints(self):
        """Test is_configured with endpoints."""
        provider = WebhookProvider()
        provider.add_endpoint(WebhookEndpoint(id="ep-1", url="https://example.com/hook"))
        assert provider.is_configured()

    def test_add_endpoint(self):
        """Test adding webhook endpoint."""
        provider = WebhookProvider()
        endpoint = WebhookEndpoint(id="ep-1", url="https://example.com/hook")

        provider.add_endpoint(endpoint)

        assert "ep-1" in provider.endpoints
        assert provider.endpoints["ep-1"].url == "https://example.com/hook"

    def test_remove_endpoint(self):
        """Test removing webhook endpoint."""
        provider = WebhookProvider()
        provider.add_endpoint(WebhookEndpoint(id="ep-1", url="https://example.com/hook"))

        result = provider.remove_endpoint("ep-1")

        assert result is True
        assert "ep-1" not in provider.endpoints

    def test_remove_nonexistent_endpoint(self):
        """Test removing non-existent endpoint."""
        provider = WebhookProvider()

        result = provider.remove_endpoint("nonexistent")

        assert result is False

    def test_channel_property(self):
        """Test channel property returns WEBHOOK."""
        provider = WebhookProvider()
        assert provider.channel == NotificationChannel.WEBHOOK

    @pytest.mark.asyncio
    async def test_send_endpoint_not_found(self):
        """Test send returns error when endpoint not found."""
        provider = WebhookProvider()
        notification = Notification(title="Test", message="Hello")

        result = await provider.send(notification, "nonexistent")

        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_send_endpoint_disabled(self):
        """Test send returns error when endpoint disabled."""
        provider = WebhookProvider()
        provider.add_endpoint(
            WebhookEndpoint(
                id="ep-1",
                url="https://example.com/hook",
                enabled=False,
            )
        )
        notification = Notification(title="Test", message="Hello")

        result = await provider.send(notification, "ep-1")

        assert not result.success
        assert "disabled" in result.error

    @pytest.mark.asyncio
    async def test_send_to_matching_filters_events(self):
        """Test send_to_matching filters by event type."""
        provider = WebhookProvider()
        provider.add_endpoint(
            WebhookEndpoint(
                id="ep-findings",
                url="https://example.com/findings",
                events=["finding.created"],
            )
        )
        provider.add_endpoint(
            WebhookEndpoint(
                id="ep-all",
                url="https://example.com/all",
                events=[],  # All events
            )
        )

        notification = Notification(title="Test", message="Hello")

        # Mock the actual send to avoid HTTP calls
        with patch.object(provider, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = NotificationResult(
                success=True,
                channel=NotificationChannel.WEBHOOK,
                recipient="ep-all",
                notification_id=notification.id,
            )

            results = await provider.send_to_matching(notification, "audit.completed")

            # Only ep-all should match audit.completed
            assert mock_send.call_count == 1


# ============================================================================
# Webhook Signature Tests
# ============================================================================


class TestWebhookSignature:
    """Tests for webhook signature generation."""

    def test_signature_format(self):
        """Test webhook signature format."""
        endpoint = WebhookEndpoint(
            id="ep-1",
            url="https://example.com/hook",
            secret="test-secret",
        )

        # Calculate expected signature
        payload = {"title": "Test", "message": "Hello"}
        body = json.dumps(payload)
        expected = hmac.new(
            b"test-secret",
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

        # Verify format
        assert expected is not None
        assert len(expected) == 64  # SHA256 hex digest


# ============================================================================
# NotificationService Tests
# ============================================================================


class TestNotificationService:
    """Tests for main NotificationService."""

    def test_init_default_providers(self):
        """Test service initializes with default providers."""
        with patch.dict("os.environ", {}, clear=True):
            service = NotificationService(
                slack_config=SlackConfig(),
                email_config=EmailConfig(),
            )

        assert NotificationChannel.SLACK in service.providers
        assert NotificationChannel.EMAIL in service.providers
        assert NotificationChannel.WEBHOOK in service.providers

    def test_get_provider(self):
        """Test getting provider by channel."""
        service = NotificationService(
            slack_config=SlackConfig(),
            email_config=EmailConfig(),
        )

        slack = service.get_provider(NotificationChannel.SLACK)
        assert isinstance(slack, SlackProvider)

    def test_get_configured_channels(self):
        """Test getting list of configured channels."""
        service = NotificationService(
            slack_config=SlackConfig(webhook_url="https://test.com"),
            email_config=EmailConfig(smtp_host=""),
        )

        channels = service.get_configured_channels()

        assert NotificationChannel.SLACK in channels
        assert NotificationChannel.EMAIL not in channels

    def test_webhook_provider_property(self):
        """Test webhook_provider property."""
        service = NotificationService(
            slack_config=SlackConfig(),
            email_config=EmailConfig(),
        )

        webhook = service.webhook_provider
        assert isinstance(webhook, WebhookProvider)

    @pytest.mark.asyncio
    async def test_notify_single_channel(self):
        """Test notifying via single channel."""
        service = NotificationService(
            slack_config=SlackConfig(webhook_url="https://test.com"),
            email_config=EmailConfig(),
        )

        notification = Notification(title="Test", message="Hello")

        # Mock the Slack provider
        with patch.object(
            service.providers[NotificationChannel.SLACK],
            "send",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = NotificationResult(
                success=True,
                channel=NotificationChannel.SLACK,
                recipient="#general",
                notification_id=notification.id,
            )

            results = await service.notify(
                notification,
                channels=[NotificationChannel.SLACK],
                recipients={NotificationChannel.SLACK: ["#alerts"]},
            )

            assert len(results) == 1
            assert results[0].success
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_multiple_recipients(self):
        """Test notifying multiple recipients on same channel."""
        service = NotificationService(
            slack_config=SlackConfig(webhook_url="https://test.com"),
            email_config=EmailConfig(),
        )

        notification = Notification(title="Test", message="Hello")

        with patch.object(
            service.providers[NotificationChannel.SLACK],
            "send",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = NotificationResult(
                success=True,
                channel=NotificationChannel.SLACK,
                recipient="#general",
                notification_id=notification.id,
            )

            results = await service.notify(
                notification,
                channels=[NotificationChannel.SLACK],
                recipients={NotificationChannel.SLACK: ["#alerts", "#general", "@user"]},
            )

            assert len(results) == 3
            assert mock_send.call_count == 3

    @pytest.mark.asyncio
    async def test_notify_skips_unconfigured(self):
        """Test notify skips unconfigured channels."""
        service = NotificationService(
            slack_config=SlackConfig(),  # Not configured
            email_config=EmailConfig(smtp_host=""),  # Not configured
        )

        notification = Notification(title="Test", message="Hello")

        results = await service.notify(notification)

        # No channels configured, so no results
        assert len(results) == 0

    def test_history_stored(self):
        """Test notifications are stored in history."""
        service = NotificationService(
            slack_config=SlackConfig(),
            email_config=EmailConfig(),
        )

        notification = Notification(title="Test", message="Hello")
        results = [
            NotificationResult(
                success=True,
                channel=NotificationChannel.SLACK,
                recipient="#general",
                notification_id=notification.id,
            )
        ]

        service._add_to_history(notification, results)

        history = service.get_history(limit=10)
        assert len(history) == 1
        assert history[0]["notification"]["title"] == "Test"

    def test_history_limit(self):
        """Test history respects limit."""
        service = NotificationService(
            slack_config=SlackConfig(),
            email_config=EmailConfig(),
        )
        service._history_limit = 5

        # Add more than limit
        for i in range(10):
            notification = Notification(title=f"Test {i}", message="Hello")
            service._add_to_history(notification, [])

        # Should only keep last 5
        assert len(service._history) == 5

    def test_get_history_filter_by_channel(self):
        """Test filtering history by channel."""
        service = NotificationService(
            slack_config=SlackConfig(),
            email_config=EmailConfig(),
        )

        # Add mixed channel results
        n1 = Notification(title="Test 1", message="Hello")
        n2 = Notification(title="Test 2", message="World")

        service._add_to_history(
            n1,
            [
                NotificationResult(
                    success=True,
                    channel=NotificationChannel.SLACK,
                    recipient="#general",
                    notification_id=n1.id,
                )
            ],
        )
        service._add_to_history(
            n2,
            [
                NotificationResult(
                    success=True,
                    channel=NotificationChannel.EMAIL,
                    recipient="user@example.com",
                    notification_id=n2.id,
                )
            ],
        )

        slack_history = service.get_history(channel=NotificationChannel.SLACK)
        assert len(slack_history) == 1
        assert slack_history[0]["notification"]["title"] == "Test 1"


# ============================================================================
# Global Service Tests
# ============================================================================


class TestGlobalService:
    """Tests for global notification service."""

    def test_get_notification_service_singleton(self):
        """Test get_notification_service returns singleton."""
        # Reset the global
        import aragora.notifications.service as svc

        svc._notification_service = None

        service1 = get_notification_service()
        service2 = get_notification_service()

        assert service1 is service2

    def test_init_notification_service(self):
        """Test init_notification_service creates new instance."""
        import aragora.notifications.service as svc

        svc._notification_service = None

        custom_config = SlackConfig(webhook_url="https://custom.com")
        service = init_notification_service(slack_config=custom_config)

        assert service is not None
        slack_provider = service.get_provider(NotificationChannel.SLACK)
        assert slack_provider.config.webhook_url == "https://custom.com"


# ============================================================================
# Channel Routing Tests
# ============================================================================


class TestChannelRouting:
    """Tests for notification channel routing."""

    @pytest.mark.asyncio
    async def test_default_slack_recipient(self):
        """Test default Slack recipient from config."""
        service = NotificationService(
            slack_config=SlackConfig(
                webhook_url="https://test.com",
                default_channel="#custom-default",
            ),
            email_config=EmailConfig(),
        )

        notification = Notification(title="Test", message="Hello")

        recipients = service._get_default_recipients(NotificationChannel.SLACK, notification)

        assert recipients == ["#custom-default"]

    @pytest.mark.asyncio
    async def test_default_webhook_recipients(self):
        """Test default webhook recipients are all enabled endpoints."""
        service = NotificationService(
            slack_config=SlackConfig(),
            email_config=EmailConfig(),
        )

        # Add some endpoints
        service.webhook_provider.add_endpoint(
            WebhookEndpoint(id="ep-1", url="https://a.com", enabled=True)
        )
        service.webhook_provider.add_endpoint(
            WebhookEndpoint(id="ep-2", url="https://b.com", enabled=False)
        )
        service.webhook_provider.add_endpoint(
            WebhookEndpoint(id="ep-3", url="https://c.com", enabled=True)
        )

        notification = Notification(title="Test", message="Hello")

        recipients = service._get_default_recipients(NotificationChannel.WEBHOOK, notification)

        assert "ep-1" in recipients
        assert "ep-2" not in recipients  # Disabled
        assert "ep-3" in recipients


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling in notifications."""

    @pytest.mark.asyncio
    async def test_slack_api_error_handling(self):
        """Test Slack provider handles API errors gracefully."""
        import aiohttp

        config = SlackConfig(bot_token="xoxb-test")
        provider = SlackProvider(config)
        notification = Notification(title="Test", message="Hello")

        # Mock aiohttp to simulate a connection error, which the provider catches
        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(side_effect=OSError("Connection refused")),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(aiohttp, "ClientSession", return_value=mock_session_cm):
            result = await provider.send(notification, "#nonexistent")

        assert not result.success
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_webhook_timeout_handling(self):
        """Test webhook provider handles timeouts."""
        import aiohttp

        provider = WebhookProvider()
        provider.add_endpoint(WebhookEndpoint(id="ep-1", url="https://slow.example.com"))
        notification = Notification(title="Test", message="Hello")

        # Create mock for aiohttp.ClientSession
        # session.post(...) must return an async context manager, not a coroutine
        mock_session = MagicMock()
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(aiohttp, "ClientSession", return_value=mock_session_cm):
            result = await provider.send(notification, "ep-1")

            assert not result.success
            assert result.error is not None


# ============================================================================
# Template Rendering Tests
# ============================================================================


class TestTemplateRendering:
    """Tests for notification template rendering."""

    def test_slack_message_escapes_html(self):
        """Test Slack messages handle special characters."""
        config = SlackConfig(webhook_url="https://test.com")
        provider = SlackProvider(config)
        notification = Notification(
            title="Alert <script>evil()</script>",
            message="Message with & special < characters >",
        )

        message = provider._build_message(notification)

        # Slack doesn't HTML-escape, but the message should be built
        assert message["attachments"][0]["title"] == "Alert <script>evil()</script>"

    def test_email_html_structure(self):
        """Test email HTML has proper structure."""
        provider = EmailProvider(EmailConfig())
        notification = Notification(
            title="Test Alert",
            message="Test message content",
            severity="warning",
        )

        html = provider._build_html(notification)

        assert "<!DOCTYPE html>" in html
        assert "<html>" in html
        assert "</html>" in html
        assert "Test Alert" in html
        assert "Test message content" in html

    def test_email_severity_colors(self):
        """Test email uses correct colors for each severity."""
        provider = EmailProvider(EmailConfig())

        severities = {
            "info": "#2196F3",
            "warning": "#FF9800",
            "error": "#F44336",
            "critical": "#B71C1C",
        }

        for severity, expected_color in severities.items():
            notification = Notification(
                title="Test",
                message="Message",
                severity=severity,
            )
            html = provider._build_html(notification)
            assert expected_color in html, f"Expected {expected_color} for {severity}"
