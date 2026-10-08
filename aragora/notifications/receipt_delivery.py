"""
Receipt Delivery Service.

Delivers decision receipts via multiple channels:
- Email (with PDF attachment)
- Slack (with rich Block Kit message)
- Webhook (JSON payload)

Usage:
    from aragora.notifications.receipt_delivery import (
        deliver_receipt,
        ReceiptDeliveryConfig,
    )

    # Deliver receipt via email
    await deliver_receipt(
        receipt=receipt,
        channels=["email"],
        recipients=["compliance@company.com"],
    )

    # Deliver via multiple channels
    await deliver_receipt(
        receipt=receipt,
        channels=["email", "slack", "webhook"],
        recipients=["team@company.com"],
        slack_channel="#compliance",
        webhook_url="https://hooks.example.com/receipts",
    )

    # Background delivery of a stored receipt on behalf of one org
    await deliver_receipt_for_org(
        org_id="org-123",
        receipt_id="rcpt-abc",
        channels=["slack"],
        recipients=[],
    )

``deliver_receipt_for_org`` is the entry point for tasks acting for a tenant:
it loads the receipt through the org-scoped store read, so another org's or an
unowned receipt is never sent, and records each delivery against that org.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any

from aragora.notifications.service import (
    EmailConfig,
    Notification,
    NotificationChannel,
    NotificationPriority,
    get_notification_service,
)

if TYPE_CHECKING:
    from aragora.gauntlet.receipt import DecisionReceipt

logger = logging.getLogger(__name__)

__all__ = [
    "deliver_receipt",
    "deliver_receipt_for_org",
    "ReceiptDeliveryConfig",
    "ReceiptDeliveryResult",
]


@dataclass
class ReceiptDeliveryConfig:
    """Configuration for receipt delivery."""

    # Email settings
    email_subject_template: str = "Decision Receipt: {verdict} - {receipt_id}"
    email_include_pdf: bool = True
    email_include_json: bool = False

    # Slack settings
    slack_include_summary: bool = True
    slack_include_download_link: bool = True

    # Webhook settings
    webhook_include_full_receipt: bool = True
    webhook_sign_payload: bool = True

    # General
    include_provenance: bool = True
    include_evidence: bool = False

    @classmethod
    def from_env(cls) -> ReceiptDeliveryConfig:
        """Create configuration from environment variables."""
        return cls(
            email_include_pdf=os.environ.get("ARAGORA_RECEIPT_EMAIL_PDF", "true").lower() == "true",
            email_include_json=os.environ.get("ARAGORA_RECEIPT_EMAIL_JSON", "false").lower()
            == "true",
            webhook_sign_payload=os.environ.get("ARAGORA_RECEIPT_WEBHOOK_SIGN", "true").lower()
            == "true",
        )


@dataclass
class ReceiptDeliveryResult:
    """Result of receipt delivery attempt."""

    success: bool
    channel: str
    recipient: str
    receipt_id: str
    error: str | None = None
    delivery_id: str | None = None
    delivered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Org that owns the delivered receipt, when delivered on an org's behalf.
    org_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "channel": self.channel,
            "recipient": self.recipient,
            "receipt_id": self.receipt_id,
            "error": self.error,
            "delivery_id": self.delivery_id,
            "delivered_at": self.delivered_at.isoformat(),
            "org_id": self.org_id,
        }


async def deliver_receipt(
    receipt: DecisionReceipt,
    channels: list[str],
    recipients: list[str],
    slack_channel: str | None = None,
    webhook_url: str | None = None,
    config: ReceiptDeliveryConfig | None = None,
    *,
    org_id: str | None = None,
) -> list[ReceiptDeliveryResult]:
    """
    Deliver a decision receipt to specified channels and recipients.

    Args:
        receipt: The DecisionReceipt to deliver
        channels: List of channels ("email", "slack", "webhook")
        recipients: List of email addresses or user IDs
        slack_channel: Slack channel for posting (optional)
        webhook_url: Webhook URL for delivery (optional)
        config: Delivery configuration (uses defaults if not provided)
        org_id: Org that owns the receipt; stamped on notifications and results

    Returns:
        List of ReceiptDeliveryResult for each delivery attempt
    """
    config = config or ReceiptDeliveryConfig.from_env()
    results: list[ReceiptDeliveryResult] = []

    for channel in channels:
        channel_lower = channel.lower()

        if channel_lower == "email":
            for recipient in recipients:
                result = await _deliver_via_email(receipt, recipient, config)
                results.append(result)

        elif channel_lower == "slack":
            target = slack_channel or os.environ.get("SLACK_DEFAULT_CHANNEL", "#receipts")
            result = await _deliver_via_slack(receipt, target, config, org_id=org_id)
            results.append(result)

        elif channel_lower == "webhook":
            if webhook_url:
                result = await _deliver_via_webhook(receipt, webhook_url, config)
                results.append(result)
            else:
                results.append(
                    ReceiptDeliveryResult(
                        success=False,
                        channel="webhook",
                        recipient="",
                        receipt_id=receipt.receipt_id,
                        error="No webhook URL provided",
                    )
                )

        else:
            logger.warning("Unknown delivery channel: %s", channel)
            results.append(
                ReceiptDeliveryResult(
                    success=False,
                    channel=channel,
                    recipient="",
                    receipt_id=receipt.receipt_id,
                    error=f"Unknown channel: {channel}",
                )
            )

    for result in results:
        result.org_id = org_id
    return results


async def deliver_receipt_for_org(
    org_id: str | None,
    receipt_id: str,
    channels: list[str],
    recipients: list[str],
    *,
    slack_channel: str | None = None,
    webhook_url: str | None = None,
    config: ReceiptDeliveryConfig | None = None,
    store: Any = None,
) -> list[ReceiptDeliveryResult]:
    """Deliver a stored receipt that ``org_id`` owns, recording each delivery for that org.

    The receipt is read with the org-scoped store lookup at run time. When the
    org is blank, or the receipt is missing, unowned or owned by another org,
    nothing is sent, nothing is recorded and an empty list is returned.

    Args:
        org_id: Org the task acts for
        receipt_id: Id of the stored receipt to deliver
        channels: List of channels ("email", "slack", "webhook")
        recipients: List of email addresses or user IDs
        slack_channel: Slack channel for posting (optional)
        webhook_url: Webhook URL for delivery (optional)
        config: Delivery configuration (uses defaults if not provided)
        store: Receipt store (defaults to the server receipt store)
    """
    acting_org = str(org_id or "").strip()
    if not acting_org or not receipt_id:
        logger.warning("Receipt delivery skipped: no org or receipt id given")
        return []

    if store is None:
        from aragora.storage.receipt_store import get_receipt_store

        store = get_receipt_store()
    stored = store.get_for_org(receipt_id, acting_org)
    if stored is None:
        logger.info("Receipt delivery skipped: receipt not found for the acting org")
        return []

    receipt = _decision_receipt_from_stored(stored)
    if receipt is None:
        return []

    results = await deliver_receipt(
        receipt,
        channels,
        recipients,
        slack_channel=slack_channel,
        webhook_url=webhook_url,
        config=config,
        org_id=acting_org,
    )
    _record_deliveries(results, acting_org)
    return results


def _decision_receipt_from_stored(stored: Any) -> DecisionReceipt | None:
    """Rebuild the gauntlet receipt for a stored row, pinned to the row's receipt id."""
    from aragora.gauntlet.receipt import DecisionReceipt

    data = dict(stored.data or {})
    data["receipt_id"] = stored.receipt_id
    try:
        return DecisionReceipt.from_dict(data)
    except (TypeError, ValueError, KeyError):
        # Older payloads may carry nested records the current dataclasses
        # reject; the delivery formats do not need them.
        for key in ("consensus_proof", "provenance_chain", "agent_responses"):
            data.pop(key, None)
    try:
        return DecisionReceipt.from_dict(data)
    except (TypeError, ValueError, KeyError) as exc:
        logger.warning(
            "Receipt %s cannot be delivered: unreadable payload (%s)", stored.receipt_id, exc
        )
        return None


def _record_deliveries(results: list[ReceiptDeliveryResult], org_id: str) -> None:
    from aragora.server.handlers.utils.receipt_delivery_history import record_receipt_delivery

    for result in results:
        record_receipt_delivery(
            receipt_id=result.receipt_id,
            channel_type=result.channel,
            channel_id=result.recipient,
            workspace_id=None,
            status="success" if result.success else "failed",
            org_id=org_id,
            result={"message_id": result.delivery_id},
            error=result.error,
        )


async def _deliver_via_email(
    receipt: DecisionReceipt,
    recipient: str,
    config: ReceiptDeliveryConfig,
) -> ReceiptDeliveryResult:
    """Deliver receipt via email with optional PDF attachment."""
    import smtplib
    import uuid

    try:
        email_config = EmailConfig.from_env()

        # Build email
        msg = MIMEMultipart("mixed")
        msg["Subject"] = config.email_subject_template.format(
            verdict=receipt.verdict,
            receipt_id=receipt.receipt_id[:12],
        )
        msg["From"] = f"{email_config.from_name} <{email_config.from_address}>"
        msg["To"] = recipient
        msg["X-Receipt-ID"] = receipt.receipt_id

        # HTML body
        html_body = _build_email_html(receipt, config)
        html_part = MIMEText(html_body, "html", "utf-8")
        msg.attach(html_part)

        # PDF attachment
        if config.email_include_pdf:
            try:
                pdf_data = receipt.to_pdf()
                pdf_attachment = MIMEApplication(pdf_data, _subtype="pdf")
                pdf_attachment.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=f"receipt-{receipt.receipt_id[:12]}.pdf",
                )
                msg.attach(pdf_attachment)
            except (ImportError, RuntimeError) as e:
                logger.warning("PDF generation failed, skipping attachment: %s", e)

        # JSON attachment
        if config.email_include_json:
            json_data = receipt.to_json().encode("utf-8")
            json_attachment = MIMEApplication(json_data, _subtype="json")
            json_attachment.add_header(
                "Content-Disposition",
                "attachment",
                filename=f"receipt-{receipt.receipt_id[:12]}.json",
            )
            msg.attach(json_attachment)

        # Send via SMTP
        if email_config.smtp_host and email_config.smtp_host != "localhost":
            with smtplib.SMTP(email_config.smtp_host, email_config.smtp_port) as server:
                if email_config.use_tls:
                    server.starttls()
                if email_config.smtp_user and email_config.smtp_password:
                    server.login(email_config.smtp_user, email_config.smtp_password)
                server.send_message(msg)
        else:
            # Log email for local development
            logger.info("[DEV] Would send receipt email to %s: %s", recipient, msg["Subject"])

        delivery_id = str(uuid.uuid4())
        logger.info("Receipt %s delivered via email to %s", receipt.receipt_id, recipient)

        return ReceiptDeliveryResult(
            success=True,
            channel="email",
            recipient=recipient,
            receipt_id=receipt.receipt_id,
            delivery_id=delivery_id,
        )

    except (smtplib.SMTPException, OSError, ConnectionError) as e:
        logger.error("Email delivery failed for %s: %s", recipient, e)
        return ReceiptDeliveryResult(
            success=False,
            channel="email",
            recipient=recipient,
            receipt_id=receipt.receipt_id,
            error="Email delivery failed",
        )


def _build_email_html(
    receipt: DecisionReceipt,
    config: ReceiptDeliveryConfig,
) -> str:
    """Build HTML email body for receipt."""
    verdict_color = {
        "PASS": "#22c55e",
        "CONDITIONAL": "#f59e0b",
        "FAIL": "#ef4444",
    }.get(receipt.verdict.upper(), "#6b7280")

    risk_summary = receipt.risk_summary or {}

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .header .verdict {{ font-size: 36px; font-weight: bold; margin-top: 10px; }}
        .content {{ background: #f9fafb; padding: 30px; border: 1px solid #e5e7eb; border-top: none; }}
        .section {{ margin-bottom: 25px; }}
        .section h2 {{ font-size: 16px; color: #6b7280; text-transform: uppercase; margin-bottom: 10px; }}
        .metric {{ display: inline-block; padding: 8px 16px; margin: 4px; border-radius: 6px; background: white; border: 1px solid #e5e7eb; }}
        .metric-label {{ font-size: 12px; color: #6b7280; }}
        .metric-value {{ font-size: 20px; font-weight: bold; }}
        .critical {{ color: #dc2626; }}
        .high {{ color: #ea580c; }}
        .medium {{ color: #ca8a04; }}
        .low {{ color: #16a34a; }}
        .footer {{ padding: 20px; text-align: center; color: #6b7280; font-size: 12px; }}
        .receipt-id {{ font-family: monospace; background: #e5e7eb; padding: 4px 8px; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Decision Receipt</h1>
        <div class="verdict" style="color: {verdict_color};">{receipt.verdict}</div>
    </div>
    <div class="content">
        <div class="section">
            <h2>Receipt Details</h2>
            <p><strong>Receipt ID:</strong> <span class="receipt-id">{receipt.receipt_id}</span></p>
            <p><strong>Timestamp:</strong> {receipt.timestamp}</p>
            <p><strong>Confidence:</strong> {receipt.confidence:.1%}</p>
            <p><strong>Robustness Score:</strong> {receipt.robustness_score:.1%}</p>
        </div>
        <div class="section">
            <h2>Risk Summary</h2>
            <div class="metric">
                <div class="metric-label">Critical</div>
                <div class="metric-value critical">{risk_summary.get("critical", 0)}</div>
            </div>
            <div class="metric">
                <div class="metric-label">High</div>
                <div class="metric-value high">{risk_summary.get("high", 0)}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Medium</div>
                <div class="metric-value medium">{risk_summary.get("medium", 0)}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Low</div>
                <div class="metric-value low">{risk_summary.get("low", 0)}</div>
            </div>
        </div>
"""

    if receipt.consensus_proof and config.include_provenance:
        consensus = receipt.consensus_proof
        html += f"""
        <div class="section">
            <h2>Consensus</h2>
            <p><strong>Reached:</strong> {"Yes" if consensus.reached else "No"}</p>
            <p><strong>Supporting Agents:</strong> {", ".join(consensus.supporting_agents)}</p>
            <p><strong>Dissenting Agents:</strong> {", ".join(consensus.dissenting_agents) or "None"}</p>
        </div>
"""

    html += """
    </div>
    <div class="footer">
        <p>This receipt was cryptographically signed and timestamped.</p>
        <p>Verify at: <a href="https://aragora.ai/verify">aragora.ai/verify</a></p>
    </div>
</body>
</html>
"""
    return html


async def _deliver_via_slack(
    receipt: DecisionReceipt,
    channel: str,
    config: ReceiptDeliveryConfig,
    *,
    org_id: str | None = None,
) -> ReceiptDeliveryResult:
    """Deliver receipt via Slack with rich Block Kit message."""
    try:
        service = get_notification_service()

        # Build notification
        verdict_emoji = {
            "PASS": ":white_check_mark:",
            "CONDITIONAL": ":warning:",
            "FAIL": ":x:",
        }.get(receipt.verdict.upper(), ":grey_question:")

        risk_summary = receipt.risk_summary or {}

        message = (
            f"*Decision Receipt*\n"
            f"Verdict: {verdict_emoji} *{receipt.verdict}*\n"
            f"Confidence: {receipt.confidence:.1%}\n"
            f"Findings: {risk_summary.get('critical', 0)} critical, "
            f"{risk_summary.get('high', 0)} high, "
            f"{risk_summary.get('medium', 0)} medium, "
            f"{risk_summary.get('low', 0)} low\n"
            f"Receipt ID: `{receipt.receipt_id[:12]}...`"
        )

        notification = Notification(
            title=f"Decision Receipt: {receipt.verdict}",
            message=message,
            severity="info" if receipt.verdict == "PASS" else "warning",
            priority=NotificationPriority.NORMAL,
            resource_type="receipt",
            resource_id=receipt.receipt_id,
            org_id=org_id,
            metadata={
                "verdict": receipt.verdict,
                "confidence": receipt.confidence,
                "risk_summary": risk_summary,
            },
        )

        results = await service.notify(
            notification=notification,
            channels=[NotificationChannel.SLACK],
            recipients={NotificationChannel.SLACK: [channel]},
        )

        if results and results[0].success:
            return ReceiptDeliveryResult(
                success=True,
                channel="slack",
                recipient=channel,
                receipt_id=receipt.receipt_id,
                delivery_id=results[0].external_id,
            )
        else:
            error = results[0].error if results else "Unknown error"
            return ReceiptDeliveryResult(
                success=False,
                channel="slack",
                recipient=channel,
                receipt_id=receipt.receipt_id,
                error=error,
            )

    except (ImportError, RuntimeError, ValueError) as e:
        logger.error("Slack delivery failed: %s", e)
        return ReceiptDeliveryResult(
            success=False,
            channel="slack",
            recipient=channel,
            receipt_id=receipt.receipt_id,
            error="Slack delivery failed",
        )


async def _deliver_via_webhook(
    receipt: DecisionReceipt,
    webhook_url: str,
    config: ReceiptDeliveryConfig,
) -> ReceiptDeliveryResult:
    """Deliver receipt via webhook."""
    import hashlib
    import hmac
    import json
    import uuid

    try:
        import aiohttp

        from aragora.security.ssrf_protection import validate_url

        # SSRF protection: validate webhook URL before making outbound request
        url_check = validate_url(webhook_url)
        if not url_check.is_safe:
            logger.warning("SSRF blocked for receipt webhook: %s", url_check.error)
            return ReceiptDeliveryResult(
                success=False,
                channel="webhook",
                recipient=webhook_url,
                receipt_id=receipt.receipt_id,
                error=f"URL validation failed: {url_check.error}",
            )

        # Build payload
        if config.webhook_include_full_receipt:
            payload = receipt.to_dict()
        else:
            payload = {
                "receipt_id": receipt.receipt_id,
                "verdict": receipt.verdict,
                "confidence": receipt.confidence,
                "timestamp": receipt.timestamp,
                "risk_summary": receipt.risk_summary,
            }

        payload_json = json.dumps(payload)
        headers = {"Content-Type": "application/json"}

        # Sign payload if configured
        if config.webhook_sign_payload:
            secret = os.environ.get("ARAGORA_WEBHOOK_SECRET", "")
            if secret:
                signature = hmac.new(
                    secret.encode(),
                    payload_json.encode(),
                    hashlib.sha256,
                ).hexdigest()
                headers["X-Aragora-Signature"] = f"sha256={signature}"

        # Send webhook
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                data=payload_json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status in (200, 201, 202, 204):
                    delivery_id = str(uuid.uuid4())
                    logger.info(
                        "Receipt %s delivered via webhook to %s", receipt.receipt_id, webhook_url
                    )
                    return ReceiptDeliveryResult(
                        success=True,
                        channel="webhook",
                        recipient=webhook_url,
                        receipt_id=receipt.receipt_id,
                        delivery_id=delivery_id,
                    )
                else:
                    error = f"Webhook returned status {response.status}"
                    return ReceiptDeliveryResult(
                        success=False,
                        channel="webhook",
                        recipient=webhook_url,
                        receipt_id=receipt.receipt_id,
                        error=error,
                    )

    except ImportError:
        logger.error("aiohttp not installed, webhook delivery unavailable")
        return ReceiptDeliveryResult(
            success=False,
            channel="webhook",
            recipient=webhook_url,
            receipt_id=receipt.receipt_id,
            error="aiohttp not installed",
        )
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        logger.error("Webhook delivery failed: %s", e)
        return ReceiptDeliveryResult(
            success=False,
            channel="webhook",
            recipient=webhook_url,
            receipt_id=receipt.receipt_id,
            error="Webhook delivery failed",
        )


# Import asyncio for type hints
import asyncio
