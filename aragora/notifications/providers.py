"""
Notification providers.

Contains the abstract NotificationProvider base class and concrete
implementations for Slack, Email, and Webhook delivery channels.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html as html_module
import json
import logging
import smtplib
import time
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from aragora.exceptions import SlackNotificationError, WebhookDeliveryError

from .delivery_log import DeliveryLogEntry, get_delivery_log_store
from .models import (
    EmailConfig,
    Notification,
    NotificationChannel,
    NotificationResult,
    SlackConfig,
    WebhookEndpoint,
)

logger = logging.getLogger(__name__)


async def _log_delivery(
    notification: Notification,
    result: NotificationResult,
    latency_seconds: float,
) -> None:
    """Record a delivery attempt in the delivery log store."""
    try:
        store = get_delivery_log_store()
        entry = DeliveryLogEntry(
            notification_id=notification.id,
            channel=result.channel.value,
            recipient=result.recipient,
            status="delivered" if result.success else "failed",
            external_id=result.external_id or "",
            error=result.error or "",
            latency_ms=latency_seconds * 1000,
        )
        await store.log(entry)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.debug("Failed to log delivery entry: %s", exc)


__all__ = [
    "NotificationProvider",
    "SlackProvider",
    "EmailProvider",
    "WebhookProvider",
]


def _record_notification_metric(
    channel: str,
    severity: str,
    priority: str,
    success: bool,
    latency_seconds: float,
    error_type: str | None = None,
) -> None:
    """Record notification metrics (imported lazily to avoid circular imports)."""
    try:
        from aragora.observability.metrics import (
            record_notification_sent,
            record_notification_error,
        )

        record_notification_sent(channel, severity, priority, success, latency_seconds)
        if not success and error_type:
            record_notification_error(channel, error_type)
    except ImportError:
        pass  # Metrics not available


class NotificationProvider(ABC):
    """Abstract base class for notification providers."""

    @property
    @abstractmethod
    def channel(self) -> NotificationChannel:
        """Get the channel this provider handles."""
        ...

    @abstractmethod
    async def send(
        self,
        notification: Notification,
        recipient: str,
    ) -> NotificationResult:
        """Send a notification to a recipient."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the provider is properly configured."""
        ...


class SlackProvider(NotificationProvider):
    """Slack notification provider."""

    def __init__(self, config: SlackConfig):
        self.config = config

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.SLACK

    def is_configured(self) -> bool:
        return bool(self.config.webhook_url or self.config.bot_token)

    async def send(
        self,
        notification: Notification,
        recipient: str,
    ) -> NotificationResult:
        """Send notification to Slack."""
        start_time = time.perf_counter()

        if not self.is_configured():
            latency = time.perf_counter() - start_time
            _record_notification_metric(
                "slack",
                notification.severity,
                notification.priority.value,
                False,
                latency,
                "not_configured",
            )
            return NotificationResult(
                success=False,
                channel=self.channel,
                recipient=recipient,
                notification_id=notification.id,
                error="Slack not configured",
            )

        try:
            # Build Slack message
            message = self._build_message(notification)

            if self.config.webhook_url:
                await self._send_webhook(message, recipient)
            elif self.config.bot_token:
                await self._send_api(message, recipient)

            latency = time.perf_counter() - start_time
            _record_notification_metric(
                "slack", notification.severity, notification.priority.value, True, latency
            )
            result = NotificationResult(
                success=True,
                channel=self.channel,
                recipient=recipient,
                notification_id=notification.id,
            )
            await _log_delivery(notification, result, latency)
            return result

        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.error("Failed to send Slack notification: %s", e)
            latency = time.perf_counter() - start_time
            error_type = "rate_limited" if "rate" in str(e).lower() else "delivery_error"
            _record_notification_metric(
                "slack",
                notification.severity,
                notification.priority.value,
                False,
                latency,
                error_type,
            )
            result = NotificationResult(
                success=False,
                channel=self.channel,
                recipient=recipient,
                notification_id=notification.id,
                error="Slack notification delivery failed",
            )
            await _log_delivery(notification, result, latency)
            return result

    def _build_message(self, notification: Notification) -> dict:
        """Build Slack message payload."""
        # Map severity to color
        colors = {
            "info": "#2196F3",
            "warning": "#FF9800",
            "error": "#F44336",
            "critical": "#B71C1C",
        }
        color = colors.get(notification.severity, "#9E9E9E")

        # Build attachment
        attachment = {
            "color": color,
            "title": notification.title,
            "text": notification.message,
            "ts": int(notification.created_at.timestamp()),
        }

        # Add fields
        fields = []
        if notification.severity:
            fields.append(
                {
                    "title": "Severity",
                    "value": notification.severity.upper(),
                    "short": True,
                }
            )
        if notification.resource_type:
            fields.append(
                {
                    "title": "Resource",
                    "value": f"{notification.resource_type}/{notification.resource_id}",
                    "short": True,
                }
            )

        if fields:
            attachment["fields"] = fields

        # Add action button
        if notification.action_url:
            attachment["actions"] = [
                {
                    "type": "button",
                    "text": notification.action_label or "View Details",
                    "url": notification.action_url,
                }
            ]

        return {
            "username": self.config.username,
            "icon_emoji": self.config.icon_emoji,
            "attachments": [attachment],
        }

    async def _send_webhook(self, message: dict, channel: str) -> None:
        """Send via webhook URL."""
        import aiohttp

        from aragora.http_client import WEBHOOK_TIMEOUT
        from aragora.security.ssrf_protection import validate_url

        # SSRF protection: validate webhook URL before making outbound request
        url_check = validate_url(self.config.webhook_url)
        if not url_check.is_safe:
            raise SlackNotificationError(
                f"SSRF blocked: {url_check.error}",
            )

        # Add channel to message
        if channel.startswith("#") or channel.startswith("@"):
            message["channel"] = channel

        async with aiohttp.ClientSession(timeout=WEBHOOK_TIMEOUT) as session:
            async with session.post(
                self.config.webhook_url,
                json=message,
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    raise SlackNotificationError(
                        f"Slack webhook failed: {text}",
                        status_code=response.status,
                    )

    async def _send_api(self, message: dict, channel: str) -> None:
        """Send via Slack API."""
        import aiohttp

        from aragora.http_client import DEFAULT_TIMEOUT

        message["channel"] = channel

        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.post(
                "https://slack.com/api/chat.postMessage",
                json=message,
                headers={"Authorization": f"Bearer {self.config.bot_token}"},
            ) as response:
                data = await response.json()
                if not data.get("ok"):
                    raise SlackNotificationError(
                        f"Slack API error: {data.get('error')}",
                        error_code=data.get("error"),
                    )


class EmailProvider(NotificationProvider):
    """Email notification provider."""

    def __init__(self, config: EmailConfig):
        self.config = config

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.EMAIL

    def is_configured(self) -> bool:
        return bool(self.config.smtp_host)

    async def send(
        self,
        notification: Notification,
        recipient: str,
    ) -> NotificationResult:
        """Send email notification."""
        start_time = time.perf_counter()

        if not self.is_configured():
            latency = time.perf_counter() - start_time
            _record_notification_metric(
                "email",
                notification.severity,
                notification.priority.value,
                False,
                latency,
                "not_configured",
            )
            return NotificationResult(
                success=False,
                channel=self.channel,
                recipient=recipient,
                notification_id=notification.id,
                error="Email not configured",
            )

        try:
            # Run SMTP in thread pool (it's blocking)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._send_email,
                notification,
                recipient,
            )

            latency = time.perf_counter() - start_time
            _record_notification_metric(
                "email", notification.severity, notification.priority.value, True, latency
            )
            result = NotificationResult(
                success=True,
                channel=self.channel,
                recipient=recipient,
                notification_id=notification.id,
            )
            await _log_delivery(notification, result, latency)
            return result

        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.error("Failed to send email notification: %s", e)
            latency = time.perf_counter() - start_time
            error_type = "connection_error" if "connection" in str(e).lower() else "delivery_error"
            _record_notification_metric(
                "email",
                notification.severity,
                notification.priority.value,
                False,
                latency,
                error_type,
            )
            result = NotificationResult(
                success=False,
                channel=self.channel,
                recipient=recipient,
                notification_id=notification.id,
                error="Email notification delivery failed",
            )
            await _log_delivery(notification, result, latency)
            return result

    def _send_email(self, notification: Notification, recipient: str) -> None:
        """Send email via SMTP."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{notification.severity.upper()}] {notification.title}"
        msg["From"] = f"{self.config.from_name} <{self.config.from_address}>"
        msg["To"] = recipient

        # Plain text version
        text = f"{notification.title}\n\n{notification.message}"
        if notification.action_url:
            text += f"\n\nView details: {notification.action_url}"

        # HTML version
        html = self._build_html(notification)

        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        # Send
        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
            if self.config.use_tls:
                server.starttls()
            if self.config.smtp_user and self.config.smtp_password:
                server.login(self.config.smtp_user, self.config.smtp_password)
            server.send_message(msg)

    def _build_html(self, notification: Notification) -> str:
        """Build HTML email content."""
        colors = {
            "info": "#2196F3",
            "warning": "#FF9800",
            "error": "#F44336",
            "critical": "#B71C1C",
        }
        color = colors.get(notification.severity, "#9E9E9E")

        safe_title = html_module.escape(notification.title)
        safe_message = html_module.escape(notification.message)

        action_html = ""
        if notification.action_url:
            safe_action_url = html_module.escape(notification.action_url)
            safe_action_label = html_module.escape(notification.action_label or "View Details")
            action_html = f"""
            <p style="margin-top: 20px;">
                <a href="{safe_action_url}"
                   style="background-color: {color}; color: white; padding: 10px 20px;
                          text-decoration: none; border-radius: 4px;">
                    {safe_action_label}
                </a>
            </p>
            """

        safe_resource_type = html_module.escape(notification.resource_type or "")
        safe_resource_id = html_module.escape(notification.resource_id or "")

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: {
            color
        }; color: white; padding: 15px; border-radius: 4px 4px 0 0; }}
                .content {{ background-color: #f5f5f5; padding: 20px; border-radius: 0 0 4px 4px; }}
                .meta {{ color: #666; font-size: 0.9em; margin-top: 15px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin: 0;">{safe_title}</h2>
                </div>
                <div class="content">
                    <p>{safe_message}</p>
                    {action_html}
                    <div class="meta">
                        <p>Severity: {notification.severity.upper()}</p>
                        {
            f"<p>Resource: {safe_resource_type}/{safe_resource_id}</p>"
            if notification.resource_type
            else ""
        }
                    </div>
                </div>
            </div>
        </body>
        </html>
        """


class WebhookProvider(NotificationProvider):
    """Webhook notification provider."""

    def __init__(self):
        self.endpoints: dict[str, WebhookEndpoint] = {}

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.WEBHOOK

    def is_configured(self) -> bool:
        return len(self.endpoints) > 0

    def add_endpoint(self, endpoint: WebhookEndpoint) -> None:
        """Register a webhook endpoint."""
        self.endpoints[endpoint.id] = endpoint

    def remove_endpoint(self, endpoint_id: str) -> bool:
        """Remove a webhook endpoint."""
        if endpoint_id in self.endpoints:
            del self.endpoints[endpoint_id]
            return True
        return False

    async def send(
        self,
        notification: Notification,
        recipient: str,  # endpoint_id
    ) -> NotificationResult:
        """Send notification to webhook endpoint."""
        start_time = time.perf_counter()

        endpoint = self.endpoints.get(recipient)
        if not endpoint:
            latency = time.perf_counter() - start_time
            _record_notification_metric(
                "webhook",
                notification.severity,
                notification.priority.value,
                False,
                latency,
                "endpoint_not_found",
            )
            return NotificationResult(
                success=False,
                channel=self.channel,
                recipient=recipient,
                notification_id=notification.id,
                error=f"Webhook endpoint not found: {recipient}",
            )

        if not endpoint.enabled:
            latency = time.perf_counter() - start_time
            _record_notification_metric(
                "webhook",
                notification.severity,
                notification.priority.value,
                False,
                latency,
                "endpoint_disabled",
            )
            return NotificationResult(
                success=False,
                channel=self.channel,
                recipient=recipient,
                notification_id=notification.id,
                error="Webhook endpoint is disabled",
            )

        try:
            import aiohttp

            from aragora.security.ssrf_protection import validate_url

            # SSRF protection: validate endpoint URL before making outbound request
            url_check = validate_url(endpoint.url)
            if not url_check.is_safe:
                raise WebhookDeliveryError(
                    webhook_url=endpoint.url,
                    status_code=0,
                    message=f"SSRF blocked: {url_check.error}",
                )

            payload = notification.to_dict()
            body = json.dumps(payload)

            headers = {
                "Content-Type": "application/json",
                **endpoint.headers,
            }

            # Add signature if secret is configured
            if endpoint.secret:
                signature = hmac.new(
                    endpoint.secret.encode(),
                    body.encode(),
                    hashlib.sha256,
                ).hexdigest()
                headers["X-Aragora-Signature"] = f"sha256={signature}"

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(
                    endpoint.url,
                    data=body,
                    headers=headers,
                ) as response:
                    if response.status >= 400:
                        text = await response.text()
                        raise WebhookDeliveryError(
                            webhook_url=endpoint.url,
                            status_code=response.status,
                            message=text,
                        )

            latency = time.perf_counter() - start_time
            _record_notification_metric(
                "webhook", notification.severity, notification.priority.value, True, latency
            )
            result = NotificationResult(
                success=True,
                channel=self.channel,
                recipient=recipient,
                notification_id=notification.id,
            )
            await _log_delivery(notification, result, latency)
            return result

        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.error("Failed to send webhook notification: %s", e)
            latency = time.perf_counter() - start_time
            error_type = "timeout" if "timeout" in str(e).lower() else "delivery_error"
            _record_notification_metric(
                "webhook",
                notification.severity,
                notification.priority.value,
                False,
                latency,
                error_type,
            )
            result = NotificationResult(
                success=False,
                channel=self.channel,
                recipient=recipient,
                notification_id=notification.id,
                error="Webhook notification delivery failed",
            )
            await _log_delivery(notification, result, latency)
            return result

    async def send_to_matching(
        self,
        notification: Notification,
        event_type: str,
    ) -> list[NotificationResult]:
        """Send to all endpoints matching the event type."""
        results = []
        for endpoint in self.endpoints.values():
            if endpoint.matches_event(event_type):
                result = await self.send(notification, endpoint.id)
                results.append(result)
        return results
