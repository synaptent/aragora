"""
Billing Notifications for Aragora.

Handles payment failure notifications, trial expiration warnings, and dunning emails.

Environment Variables:
    ARAGORA_SMTP_HOST: SMTP server host
    ARAGORA_SMTP_PORT: SMTP server port (default: 587)
    ARAGORA_SMTP_USER: SMTP username
    ARAGORA_SMTP_PASSWORD: SMTP password
    ARAGORA_SMTP_FROM: From email address
    ARAGORA_NOTIFICATION_WEBHOOK: Optional webhook URL for notifications
"""

from __future__ import annotations

import html
import json
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from aragora.billing.models import SubscriptionTier

logger = logging.getLogger(__name__)

# SMTP Configuration
SMTP_HOST = os.environ.get("ARAGORA_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("ARAGORA_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("ARAGORA_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("ARAGORA_SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("ARAGORA_SMTP_FROM", "billing@aragora.ai")

# Webhook for external notification systems (Slack, etc.)
NOTIFICATION_WEBHOOK = os.environ.get("ARAGORA_NOTIFICATION_WEBHOOK", "")


@dataclass
class NotificationResult:
    """Result of sending a notification."""

    success: bool
    method: str  # "email", "webhook", "log"
    error: str | None = None


class BillingNotifier:
    """
    Handles billing notifications for payment failures and trial expiration.

    Supports multiple notification channels:
    - Email via SMTP
    - Webhook (for Slack, Discord, etc.)
    - Logging fallback
    """

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        smtp_from: str | None = None,
        webhook_url: str | None = None,
    ):
        self.smtp_host = smtp_host or SMTP_HOST
        self.smtp_port = smtp_port or SMTP_PORT
        self.smtp_user = smtp_user or SMTP_USER
        self.smtp_password = smtp_password or SMTP_PASSWORD
        self.smtp_from = smtp_from or SMTP_FROM
        self.webhook_url = webhook_url or NOTIFICATION_WEBHOOK

    def _is_smtp_configured(self) -> bool:
        """Check if SMTP is configured."""
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    def _send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> NotificationResult:
        """Send email via SMTP."""
        if not self._is_smtp_configured():
            return NotificationResult(
                success=False,
                method="email",
                error="SMTP not configured",
            )

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.smtp_from
            msg["To"] = to_email

            # Add text and HTML parts
            if text_body:
                msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            # Create secure connection
            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_from, to_email, msg.as_string())

            logger.info("Sent billing email to %s: %s", to_email, subject)
            return NotificationResult(success=True, method="email")

        except (smtplib.SMTPException, OSError, ConnectionError, TimeoutError, ssl.SSLError) as e:
            logger.error("Failed to send email to %s: %s", to_email, e)
            return NotificationResult(success=False, method="email", error="Email delivery failed")

    def _send_webhook(self, payload: dict) -> NotificationResult:
        """Send notification via webhook."""
        if not self.webhook_url:
            return NotificationResult(
                success=False,
                method="webhook",
                error="Webhook not configured",
            )

        try:
            data = json.dumps(payload).encode("utf-8")
            req = Request(  # noqa: S310 -- config webhook URL
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as response:  # noqa: S310 -- config webhook URL
                response.read()

            logger.info("Sent webhook notification: %s", payload.get("event"))
            return NotificationResult(success=True, method="webhook")

        except URLError as e:
            logger.error("Failed to send webhook: %s", e)
            return NotificationResult(
                success=False, method="webhook", error="Webhook delivery failed"
            )

    def notify_payment_failed(
        self,
        org_id: str,
        org_name: str,
        email: str,
        attempt_count: int = 1,
        invoice_url: str | None = None,
        days_until_downgrade: int = 7,
    ) -> NotificationResult:
        """
        Send payment failure notification.

        Args:
            org_id: Organization ID
            org_name: Organization name
            email: Email address to notify
            attempt_count: Number of failed payment attempts
            invoice_url: URL to the failed invoice
            days_until_downgrade: Days until subscription downgrade (default 7)

        Returns:
            NotificationResult indicating success/failure
        """
        subject = "[Aragora] Payment Failed - Action Required"

        # Determine urgency based on attempt count
        if attempt_count >= 3:
            urgency = "URGENT"
            urgency_message = (
                "This is your final notice. Your subscription will be suspended "
                "if payment is not received within 48 hours."
            )
        elif attempt_count >= 2:
            urgency = "IMPORTANT"
            urgency_message = (
                "This is a follow-up notice. Please update your payment method "
                "to avoid service interruption."
            )
        else:
            urgency = "NOTICE"
            urgency_message = (
                "We were unable to process your payment. Please update your payment information."
            )

        safe_org_name = html.escape(org_name)
        safe_invoice_url = html.escape(invoice_url) if invoice_url else None

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Monaco', 'Menlo', monospace; background: #0a0a0a; color: #00ff00; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; border: 1px solid #00ff00; padding: 20px; }}
        .header {{ font-size: 18px; margin-bottom: 20px; }}
        .urgency {{ color: {"#ff6600" if urgency != "NOTICE" else "#00ff00"}; font-weight: bold; }}
        .message {{ margin: 20px 0; line-height: 1.6; }}
        .button {{ display: inline-block; padding: 10px 20px; background: #00ff00; color: #0a0a0a; text-decoration: none; margin-top: 20px; }}
        .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">[ARAGORA BILLING]</div>
        <div class="urgency">{urgency}: Payment Failed</div>
        <div class="message">
            <p>Hi {safe_org_name},</p>
            <p>{urgency_message}</p>
            <p><strong>Organization:</strong> {safe_org_name}</p>
            <p><strong>Attempt:</strong> {attempt_count} of 3</p>
            {'<p><a href="' + safe_invoice_url + '" class="button">UPDATE PAYMENT</a></p>' if safe_invoice_url else ""}
        </div>
        <div class="footer">
            <p>If you believe this is an error, please contact support@aragora.ai</p>
            <p>— Aragora Billing System</p>
        </div>
    </div>
</body>
</html>
"""

        text_body = f"""
[ARAGORA BILLING]

{urgency}: Payment Failed

Hi {org_name},

{urgency_message}

Organization: {org_name}
Attempt: {attempt_count} of 3

{"Update your payment here: " + invoice_url if invoice_url else "Please log in to update your payment method."}

If you believe this is an error, please contact support@aragora.ai

— Aragora Billing System
"""

        # Try to send email first
        result = self._send_email(email, subject, html_body, text_body)
        if result.success:
            return result

        # Fall back to webhook
        webhook_result = self._send_webhook(
            {
                "event": "payment_failed",
                "org_id": org_id,
                "org_name": org_name,
                "email": email,
                "attempt_count": attempt_count,
                "urgency": urgency,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        if webhook_result.success:
            return webhook_result

        # Log as final fallback
        logger.warning(
            "PAYMENT_FAILED: org=%s name=%s email=%s attempt=%s urgency=%s",
            org_id,
            org_name,
            email,
            attempt_count,
            urgency,
        )
        return NotificationResult(success=True, method="log")

    def notify_trial_ending(
        self,
        org_id: str,
        org_name: str,
        email: str,
        days_remaining: int,
        trial_end: datetime,
    ) -> NotificationResult:
        """
        Send trial expiration warning notification.

        Args:
            org_id: Organization ID
            org_name: Organization name
            email: Email address to notify
            days_remaining: Days until trial expires
            trial_end: Trial end datetime

        Returns:
            NotificationResult indicating success/failure
        """
        if days_remaining <= 1:
            subject = "[Aragora] Your Trial Ends Tomorrow!"
            urgency = "URGENT"
        elif days_remaining <= 3:
            subject = f"[Aragora] Your Trial Ends in {days_remaining} Days"
            urgency = "REMINDER"
        else:
            subject = f"[Aragora] {days_remaining} Days Left in Your Trial"
            urgency = "INFO"

        safe_org_name = html.escape(org_name)

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Monaco', 'Menlo', monospace; background: #0a0a0a; color: #00ff00; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; border: 1px solid #00ffff; padding: 20px; }}
        .header {{ font-size: 18px; margin-bottom: 20px; color: #00ffff; }}
        .highlight {{ color: #00ffff; font-size: 24px; margin: 20px 0; }}
        .message {{ margin: 20px 0; line-height: 1.6; }}
        .button {{ display: inline-block; padding: 10px 20px; background: #00ffff; color: #0a0a0a; text-decoration: none; margin-top: 20px; }}
        .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">[ARAGORA TRIAL]</div>
        <div class="highlight">{days_remaining} Days Remaining</div>
        <div class="message">
            <p>Hi {safe_org_name},</p>
            <p>Your Aragora trial will end on {trial_end.strftime("%B %d, %Y")}.</p>
            <p>Upgrade now to keep access to:</p>
            <ul>
                <li>Unlimited AI debates</li>
                <li>Advanced analytics</li>
                <li>Team collaboration</li>
                <li>API access</li>
            </ul>
            <p><a href="https://aragora.ai/pricing" class="button">UPGRADE NOW</a></p>
        </div>
        <div class="footer">
            <p>Questions? Contact us at support@aragora.ai</p>
            <p>— Aragora Team</p>
        </div>
    </div>
</body>
</html>
"""

        text_body = f"""
[ARAGORA TRIAL]

{days_remaining} Days Remaining

Hi {org_name},

Your Aragora trial will end on {trial_end.strftime("%B %d, %Y")}.

Upgrade now to keep access to:
- Unlimited AI debates
- Advanced analytics
- Team collaboration
- API access

Upgrade at: https://aragora.ai/pricing

Questions? Contact us at support@aragora.ai

— Aragora Team
"""

        # Try to send email first
        result = self._send_email(email, subject, html_body, text_body)
        if result.success:
            return result

        # Fall back to webhook
        webhook_result = self._send_webhook(
            {
                "event": "trial_ending",
                "org_id": org_id,
                "org_name": org_name,
                "email": email,
                "days_remaining": days_remaining,
                "trial_end": trial_end.isoformat(),
                "urgency": urgency,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        if webhook_result.success:
            return webhook_result

        # Log as final fallback
        logger.info(
            "TRIAL_ENDING: org=%s name=%s email=%s days_remaining=%s",
            org_id,
            org_name,
            email,
            days_remaining,
        )
        return NotificationResult(success=True, method="log")

    def notify_subscription_canceled(
        self,
        org_id: str,
        org_name: str,
        email: str,
        reason: str | None = None,
    ) -> NotificationResult:
        """
        Send subscription cancellation confirmation.

        Args:
            org_id: Organization ID
            org_name: Organization name
            email: Email address to notify
            reason: Optional cancellation reason

        Returns:
            NotificationResult indicating success/failure
        """
        subject = "[Aragora] Subscription Canceled - We're Sorry to See You Go"

        safe_org_name = html.escape(org_name)

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Monaco', 'Menlo', monospace; background: #0a0a0a; color: #00ff00; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; border: 1px solid #ff6600; padding: 20px; }}
        .header {{ font-size: 18px; margin-bottom: 20px; color: #ff6600; }}
        .message {{ margin: 20px 0; line-height: 1.6; }}
        .button {{ display: inline-block; padding: 10px 20px; background: #00ff00; color: #0a0a0a; text-decoration: none; margin-top: 20px; }}
        .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">[ARAGORA]</div>
        <div class="message">
            <p>Hi {safe_org_name},</p>
            <p>Your Aragora subscription has been canceled.</p>
            <p>Your access will continue until the end of your current billing period.</p>
            <p>Changed your mind? You can reactivate anytime:</p>
            <p><a href="https://aragora.ai/billing" class="button">REACTIVATE</a></p>
            <p>We'd love to hear your feedback. What could we have done better?</p>
        </div>
        <div class="footer">
            <p>— Aragora Team</p>
        </div>
    </div>
</body>
</html>
"""

        text_body = f"""
[ARAGORA]

Hi {org_name},

Your Aragora subscription has been canceled.

Your access will continue until the end of your current billing period.

Changed your mind? You can reactivate anytime at https://aragora.ai/billing

We'd love to hear your feedback. What could we have done better?

— Aragora Team
"""

        # Try to send email
        result = self._send_email(email, subject, html_body, text_body)
        if result.success:
            return result

        # Fall back to webhook
        webhook_result = self._send_webhook(
            {
                "event": "subscription_canceled",
                "org_id": org_id,
                "org_name": org_name,
                "email": email,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        if webhook_result.success:
            return webhook_result

        # Log as final fallback
        logger.info(
            "SUBSCRIPTION_CANCELED: org=%s name=%s email=%s reason=%s",
            org_id,
            org_name,
            email,
            reason,
        )
        return NotificationResult(success=True, method="log")

    def notify_downgraded(
        self,
        org_id: str,
        org_name: str,
        email: str,
        previous_tier: SubscriptionTier,
        invoice_url: str | None = None,
    ) -> NotificationResult:
        """
        Send subscription downgrade notification due to payment failure.

        Args:
            org_id: Organization ID
            org_name: Organization name
            email: Email address to notify
            previous_tier: The tier the organization was downgraded from
            invoice_url: Optional URL to the unpaid invoice

        Returns:
            NotificationResult indicating success/failure
        """
        subject = "[Aragora] Your Subscription Has Been Downgraded"

        safe_org_name = html.escape(org_name)
        safe_invoice_url = html.escape(invoice_url) if invoice_url else None

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Monaco', 'Menlo', monospace; background: #0a0a0a; color: #00ff00; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; border: 1px solid #ff0000; padding: 20px; }}
        .header {{ font-size: 18px; margin-bottom: 20px; color: #ff0000; }}
        .message {{ margin: 20px 0; line-height: 1.6; }}
        .button {{ display: inline-block; padding: 10px 20px; background: #00ff00; color: #0a0a0a; text-decoration: none; margin-top: 20px; }}
        .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">[ARAGORA BILLING]</div>
        <div class="message">
            <p>Hi {safe_org_name},</p>
            <p>Due to unresolved payment issues, your Aragora subscription has been downgraded from <strong>{previous_tier.value.upper()}</strong> to <strong>FREE</strong>.</p>
            <p>Your access to premium features has been suspended. To restore your subscription:</p>
            <ol>
                <li>Update your payment method</li>
                <li>Pay any outstanding invoices</li>
                <li>Upgrade your plan</li>
            </ol>
            {'<p><a href="' + safe_invoice_url + '" class="button">PAY NOW</a></p>' if safe_invoice_url else '<p><a href="https://aragora.ai/billing" class="button">UPDATE PAYMENT</a></p>'}
        </div>
        <div class="footer">
            <p>Need help? Contact support@aragora.ai</p>
            <p>— Aragora Billing System</p>
        </div>
    </div>
</body>
</html>
"""

        text_body = f"""
[ARAGORA BILLING]

Hi {org_name},

Due to unresolved payment issues, your Aragora subscription has been downgraded from {previous_tier.value.upper()} to FREE.

Your access to premium features has been suspended. To restore your subscription:
1. Update your payment method
2. Pay any outstanding invoices
3. Upgrade your plan

{"Pay now: " + invoice_url if invoice_url else "Update payment at: https://aragora.ai/billing"}

Need help? Contact support@aragora.ai

— Aragora Billing System
"""

        # Try to send email first
        result = self._send_email(email, subject, html_body, text_body)
        if result.success:
            return result

        # Fall back to webhook
        webhook_result = self._send_webhook(
            {
                "event": "subscription_downgraded",
                "org_id": org_id,
                "org_name": org_name,
                "email": email,
                "previous_tier": previous_tier.value,
                "new_tier": "free",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        if webhook_result.success:
            return webhook_result

        # Log as final fallback
        logger.warning(
            "SUBSCRIPTION_DOWNGRADED: org=%s name=%s email=%s previous_tier=%s",
            org_id,
            org_name,
            email,
            previous_tier.value,
        )
        return NotificationResult(success=True, method="log")

    def notify_budget_alert(
        self,
        tenant_id: str,
        email: str,
        alert_level: str,
        current_spend: str,
        budget_limit: str,
        percent_used: float,
        org_name: str | None = None,
    ) -> NotificationResult:
        """
        Send budget alert notification.

        Args:
            tenant_id: Tenant identifier
            email: Email address to notify
            alert_level: Alert level (info, warning, critical, exceeded)
            current_spend: Current spend amount (formatted string)
            budget_limit: Monthly budget limit (formatted string)
            percent_used: Percentage of budget used
            org_name: Optional organization name

        Returns:
            NotificationResult indicating success/failure
        """
        display_name = html.escape(org_name or tenant_id)

        # Customize messaging based on alert level
        level_config = {
            "info": {
                "emoji": "ℹ️",
                "title": "Budget Update",
                "urgency": "For your information",
                "color": "#3498db",
            },
            "warning": {
                "emoji": "⚠️",
                "title": "Budget Warning",
                "urgency": "Please review your usage",
                "color": "#f39c12",
            },
            "critical": {
                "emoji": "🚨",
                "title": "Critical Budget Alert",
                "urgency": "Immediate attention required",
                "color": "#e74c3c",
            },
            "exceeded": {
                "emoji": "🛑",
                "title": "Budget Exceeded",
                "urgency": "Budget limit exceeded",
                "color": "#c0392b",
            },
        }

        config = level_config.get(alert_level, level_config["warning"])

        subject = f"{config['emoji']} Aragora {config['title']}: {percent_used:.0f}% of Budget Used"

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: {config["color"]}; color: white; padding: 20px; text-align: center;">
                <h1 style="margin: 0;">{config["emoji"]} {config["title"]}</h1>
            </div>

            <div style="padding: 30px; background: #f9f9f9;">
                <p>Hi,</p>

                <p>This is an automated alert for <strong>{display_name}</strong>.</p>

                <div style="background: white; border-radius: 8px; padding: 20px; margin: 20px 0; border-left: 4px solid {config["color"]};">
                    <h3 style="margin-top: 0;">{config["urgency"]}</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee;"><strong>Current Spend:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee; text-align: right;">{current_spend}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee;"><strong>Monthly Budget:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee; text-align: right;">{budget_limit}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Usage:</strong></td>
                            <td style="padding: 8px 0; text-align: right; font-size: 1.2em; color: {config["color"]};">{percent_used:.1f}%</td>
                        </tr>
                    </table>
                </div>

                <p>
                    <a href="https://aragora.ai/dashboard/billing" style="display: inline-block; background: {config["color"]}; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px;">
                        View Billing Dashboard
                    </a>
                </p>

                <p style="color: #666; font-size: 0.9em;">
                    You can adjust your budget alerts in your billing settings.
                </p>
            </div>

            <div style="padding: 20px; text-align: center; color: #999; font-size: 0.8em;">
                <p>Aragora - Multi-Agent Debate Platform</p>
            </div>
        </body>
        </html>
        """

        text_body = f"""
{config["title"]} - {config["urgency"]}

Organization: {display_name}
Current Spend: {current_spend}
Monthly Budget: {budget_limit}
Usage: {percent_used:.1f}%

View your billing dashboard: https://aragora.ai/dashboard/billing

You can adjust your budget alerts in your billing settings.
        """

        # Try to send email first
        result = self._send_email(email, subject, html_body, text_body)
        if result.success:
            return result

        # Fall back to webhook
        webhook_result = self._send_webhook(
            {
                "event": "budget_alert",
                "tenant_id": tenant_id,
                "org_name": org_name,
                "email": email,
                "alert_level": alert_level,
                "current_spend": current_spend,
                "budget_limit": budget_limit,
                "percent_used": percent_used,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        if webhook_result.success:
            return webhook_result

        # Log as final fallback
        logger.warning(
            "BUDGET_ALERT: tenant=%s email=%s level=%s spend=%s budget=%s percent=%.1f%%",
            tenant_id,
            email,
            alert_level,
            current_spend,
            budget_limit,
            percent_used,
        )
        return NotificationResult(success=True, method="log")

    def notify_forecast_overage(
        self,
        org_id: str,
        email: str,
        org_name: str,
        budget_name: str,
        current_spent: float,
        budget_limit: float,
        projected_date: datetime,
        projected_amount: float,
    ) -> NotificationResult:
        """
        Send forecast overage alert when projected spending will exceed budget.

        Args:
            org_id: Organization identifier
            email: Email address to notify
            org_name: Organization name
            budget_name: Name of the budget
            current_spent: Current spent amount in USD
            budget_limit: Budget limit in USD
            projected_date: Date when budget will be exceeded
            projected_amount: Projected total spend

        Returns:
            NotificationResult indicating success/failure
        """
        days_until = (projected_date - datetime.now(timezone.utc)).days
        overage_amount = projected_amount - budget_limit

        safe_org_name = html.escape(org_name)
        safe_budget_name = html.escape(budget_name)

        subject = f"⚠️ Aragora Budget Forecast: Will Exceed {budget_name} in {days_until} days"

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #f39c12; color: white; padding: 20px; text-align: center;">
                <h1 style="margin: 0;">⚠️ Budget Forecast Alert</h1>
            </div>

            <div style="padding: 30px; background: #f9f9f9;">
                <p>Hi,</p>

                <p>Based on your current usage patterns, we project that <strong>{safe_org_name}</strong>
                will exceed the <strong>{safe_budget_name}</strong> budget.</p>

                <div style="background: white; border-radius: 8px; padding: 20px; margin: 20px 0; border-left: 4px solid #f39c12;">
                    <h3 style="margin-top: 0;">Forecast Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee;"><strong>Current Spend:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee; text-align: right;">${current_spent:,.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee;"><strong>Budget Limit:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee; text-align: right;">${budget_limit:,.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee;"><strong>Projected Total:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee; text-align: right; color: #e74c3c;">${projected_amount:,.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee;"><strong>Projected Overage:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee; text-align: right; color: #e74c3c;">${overage_amount:,.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Expected Exceed Date:</strong></td>
                            <td style="padding: 8px 0; text-align: right;">{projected_date.strftime("%B %d, %Y")}</td>
                        </tr>
                    </table>
                </div>

                <p><strong>What you can do:</strong></p>
                <ul>
                    <li>Review your usage in the billing dashboard</li>
                    <li>Increase your budget limit if needed</li>
                    <li>Enable overage billing to avoid service interruption</li>
                </ul>

                <p>
                    <a href="https://aragora.ai/dashboard/billing" style="display: inline-block; background: #f39c12; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px;">
                        View Billing Dashboard
                    </a>
                </p>
            </div>

            <div style="padding: 20px; text-align: center; color: #999; font-size: 0.8em;">
                <p>Aragora - Multi-Agent Debate Platform</p>
            </div>
        </body>
        </html>
        """

        text_body = f"""
Budget Forecast Alert

Organization: {org_name}
Budget: {budget_name}

Based on your current usage patterns, we project that your budget will be exceeded.

Current Spend: ${current_spent:,.2f}
Budget Limit: ${budget_limit:,.2f}
Projected Total: ${projected_amount:,.2f}
Projected Overage: ${overage_amount:,.2f}
Expected Exceed Date: {projected_date.strftime("%B %d, %Y")}

What you can do:
- Review your usage in the billing dashboard
- Increase your budget limit if needed
- Enable overage billing to avoid service interruption

View your billing dashboard: https://aragora.ai/dashboard/billing
        """

        # Try to send email first
        result = self._send_email(email, subject, html_body, text_body)
        if result.success:
            return result

        # Fall back to webhook
        webhook_result = self._send_webhook(
            {
                "event": "forecast_overage",
                "org_id": org_id,
                "org_name": org_name,
                "email": email,
                "budget_name": budget_name,
                "current_spent": current_spent,
                "budget_limit": budget_limit,
                "projected_date": projected_date.isoformat(),
                "projected_amount": projected_amount,
                "overage_amount": overage_amount,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        if webhook_result.success:
            return webhook_result

        # Log as final fallback
        logger.warning(
            "FORECAST_OVERAGE: org=%s email=%s budget=%s projected=$%.2f limit=$%.2f",
            org_id,
            email,
            budget_name,
            projected_amount,
            budget_limit,
        )
        return NotificationResult(success=True, method="log")

    def notify_credit_expiring(
        self,
        org_id: str,
        email: str,
        org_name: str,
        expiring_amount_cents: int,
        expiration_date: datetime,
        days_until: int,
    ) -> NotificationResult:
        """
        Send credit expiration notification.

        Args:
            org_id: Organization identifier
            email: Email address to notify
            org_name: Organization name
            expiring_amount_cents: Amount of credits expiring in cents
            expiration_date: When credits expire
            days_until: Days until expiration

        Returns:
            NotificationResult indicating success/failure
        """
        expiring_usd = expiring_amount_cents / 100

        safe_org_name = html.escape(org_name)

        subject = f"💰 Aragora Credits Expiring: ${expiring_usd:.2f} in {days_until} days"

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #9b59b6; color: white; padding: 20px; text-align: center;">
                <h1 style="margin: 0;">💰 Credits Expiring Soon</h1>
            </div>

            <div style="padding: 30px; background: #f9f9f9;">
                <p>Hi,</p>

                <p>This is a reminder that <strong>{safe_org_name}</strong> has credits that will expire soon.</p>

                <div style="background: white; border-radius: 8px; padding: 20px; margin: 20px 0; border-left: 4px solid #9b59b6;">
                    <h3 style="margin-top: 0;">Credit Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee;"><strong>Expiring Amount:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee; text-align: right; font-size: 1.2em; color: #9b59b6;">${expiring_usd:,.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee;"><strong>Expiration Date:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #eee; text-align: right;">{expiration_date.strftime("%B %d, %Y")}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Days Remaining:</strong></td>
                            <td style="padding: 8px 0; text-align: right;">{days_until} days</td>
                        </tr>
                    </table>
                </div>

                <p>Use your credits before they expire by running debates or using the API.</p>

                <p>
                    <a href="https://aragora.ai/dashboard/debates/new" style="display: inline-block; background: #9b59b6; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px;">
                        Start a Debate
                    </a>
                </p>
            </div>

            <div style="padding: 20px; text-align: center; color: #999; font-size: 0.8em;">
                <p>Aragora - Multi-Agent Debate Platform</p>
            </div>
        </body>
        </html>
        """

        text_body = f"""
Credits Expiring Soon

Organization: {org_name}

Expiring Amount: ${expiring_usd:,.2f}
Expiration Date: {expiration_date.strftime("%B %d, %Y")}
Days Remaining: {days_until} days

Use your credits before they expire by running debates or using the API.

Start a debate: https://aragora.ai/dashboard/debates/new
        """

        # Try to send email first
        result = self._send_email(email, subject, html_body, text_body)
        if result.success:
            return result

        # Fall back to webhook
        webhook_result = self._send_webhook(
            {
                "event": "credit_expiring",
                "org_id": org_id,
                "org_name": org_name,
                "email": email,
                "expiring_amount_cents": expiring_amount_cents,
                "expiring_amount_usd": expiring_usd,
                "expiration_date": expiration_date.isoformat(),
                "days_until": days_until,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        if webhook_result.success:
            return webhook_result

        # Log as final fallback
        logger.warning(
            "CREDIT_EXPIRING: org=%s email=%s amount=$%.2f expires=%s",
            org_id,
            email,
            expiring_usd,
            expiration_date.date(),
        )
        return NotificationResult(success=True, method="log")


# Default notifier instance
_default_notifier: BillingNotifier | None = None


def get_billing_notifier() -> BillingNotifier:
    """Get the default billing notifier instance."""
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = BillingNotifier()
    return _default_notifier


__all__ = [
    "BillingNotifier",
    "NotificationResult",
    "get_billing_notifier",
]
