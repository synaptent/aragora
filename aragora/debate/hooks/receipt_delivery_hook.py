"""
Receipt Delivery Hook - Automatic receipt delivery after debates.

Provides automated delivery of decision receipts to subscribed channels
(Slack, Teams, email, webhooks) after debates complete.

Usage:
    from aragora.debate.hooks.receipt_delivery_hook import create_receipt_delivery_hook
    from aragora.debate.hooks import HookManager

    # Create and register the hook
    hook_manager = HookManager()
    delivery_hook = create_receipt_delivery_hook(org_id="org-123")
    hook_manager.register("post_debate", delivery_hook.on_post_debate)

    # Or use with Arena
    arena = Arena(env, agents, protocol)
    arena.hook_manager.register("post_debate", delivery_hook.on_post_debate)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aragora.runtime.connector_factory import create_connector

if TYPE_CHECKING:
    from aragora.debate.context import DebateContext
    from aragora.core_types import DebateResult

logger = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    """Result of a receipt delivery attempt."""

    channel_type: str
    channel_id: str
    workspace_id: str | None
    success: bool
    message_id: str | None = None
    error: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "channel_type": self.channel_type,
            "channel_id": self.channel_id,
            "workspace_id": self.workspace_id,
            "success": self.success,
            "message_id": self.message_id,
            "error": self.error,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
        }


class ReceiptDeliveryHook:
    """Hook for automatic receipt delivery after debates.

    Subscribes to POST_DEBATE events and delivers receipts to
    channels configured via the channel subscription store.
    """

    def __init__(
        self,
        org_id: str,
        min_confidence: float = 0.0,
        require_consensus: bool = False,
        enabled: bool = True,
    ):
        """Initialize the receipt delivery hook.

        Args:
            org_id: Organization ID to deliver receipts for
            min_confidence: Minimum confidence threshold for delivery (0.0-1.0)
            require_consensus: Only deliver if consensus was reached
            enabled: Whether the hook is enabled
        """
        self.org_id = org_id
        self.min_confidence = min_confidence
        self.require_consensus = require_consensus
        self.enabled = enabled
        self._delivery_history: list[DeliveryResult] = []

    async def on_post_debate(
        self,
        ctx: DebateContext,
        result: DebateResult,
    ) -> None:
        """Called after a debate completes.

        Delivers the decision receipt to all subscribed channels.

        Args:
            ctx: The debate context
            result: The debate result
        """
        if not self.enabled:
            logger.debug("Receipt delivery hook is disabled")
            return

        # Check confidence threshold
        confidence = getattr(result, "confidence", 0.0)
        if confidence < self.min_confidence:
            logger.debug(
                "Skipping delivery: confidence %s < threshold %s", confidence, self.min_confidence
            )
            return

        # Check consensus requirement
        if self.require_consensus and not getattr(result, "consensus_reached", False):
            logger.debug("Skipping delivery: consensus not reached")
            return

        # Get subscribed channels
        try:
            subscriptions = await self._get_receipt_subscriptions()
            if not subscriptions:
                logger.debug("No receipt subscriptions for org %s", self.org_id)
                return

            logger.info(
                "Delivering receipt for debate %s to %s channels",
                result.debate_id,
                len(subscriptions),
            )

            # Generate the receipt
            receipt = await self._generate_receipt(ctx, result)
            if not receipt:
                logger.error("Failed to generate receipt")
                return

            # Deliver to each channel
            delivery_tasks = []
            for sub in subscriptions:
                task = self._deliver_to_channel(receipt, sub)
                delivery_tasks.append(task)

            results = await asyncio.gather(*delivery_tasks, return_exceptions=True)

            # Log results
            success_count = sum(1 for r in results if isinstance(r, DeliveryResult) and r.success)
            logger.info(
                "Receipt delivery complete: %s/%s successful", success_count, len(subscriptions)
            )

        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
            logger.exception("Error in receipt delivery hook: %s", e)

    async def _get_receipt_subscriptions(self) -> list[Any]:
        """Get channels subscribed to receipt events."""
        try:
            from aragora.storage.channel_subscription_store import (
                EventType,
                get_channel_subscription_store,
            )

            store = get_channel_subscription_store()
            all_subs = store.get_by_org(self.org_id)

            # Filter for receipt subscriptions
            receipt_subs = [
                sub
                for sub in all_subs
                if sub.is_active
                and (EventType.RECEIPT in sub.event_types or "receipt" in sub.event_types)
            ]

            return receipt_subs

        except ImportError:
            logger.warning("Channel subscription store not available")
            return []
        except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
            logger.error("Failed to get subscriptions: %s", e)
            return []

    async def _generate_receipt(
        self,
        ctx: DebateContext,
        result: DebateResult,
    ) -> dict[str, Any] | None:
        """Generate a decision receipt from the debate result."""
        try:
            import hashlib

            from aragora.models.receipts.gauntlet import normalize_live_explainability

            # Build receipt data
            receipt_data = {
                "debate_id": getattr(result, "debate_id", getattr(result, "id", "")),
                "task": getattr(ctx, "task", getattr(result, "task", "")),
                "final_answer": getattr(result, "final_answer", ""),
                "confidence": getattr(result, "confidence", 0.0),
                "consensus_reached": getattr(result, "consensus_reached", False),
                "rounds_used": getattr(result, "rounds_used", 0),
                "participants": list(getattr(result, "participants", [])),
                "duration_seconds": getattr(result, "duration_seconds", 0.0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "org_id": self.org_id,
            }
            result_metadata = getattr(result, "metadata", {}) or {}
            live_explainability = normalize_live_explainability(
                result_metadata.get("live_explainability")
            )
            if live_explainability is not None:
                receipt_data["explainability"] = {"live_explainability": live_explainability}

            # Generate explainability data
            try:
                from aragora.explainability.builder import ExplanationBuilder

                builder = ExplanationBuilder()
                decision = await builder.build(result, ctx)
                explainability = receipt_data.get("explainability")
                existing_explainability = (
                    dict(explainability) if isinstance(explainability, dict) else {}
                )
                receipt_data["explainability"] = {
                    **existing_explainability,
                    "summary": builder.generate_summary(decision),
                    "evidence_chain": [e.to_dict() for e in decision.get_top_evidence(5)],
                    "vote_pivots": [v.to_dict() for v in decision.get_pivotal_votes()],
                    "confidence_attribution": [
                        c.to_dict() for c in decision.get_major_confidence_factors()
                    ],
                    "counterfactuals": [
                        c.to_dict() for c in decision.get_high_sensitivity_counterfactuals()
                    ],
                    "scores": {
                        "evidence_quality": decision.evidence_quality_score,
                        "agent_agreement": decision.agent_agreement_score,
                        "belief_stability": decision.belief_stability_score,
                    },
                }
            except (ImportError, RuntimeError, ValueError, TypeError) as e:
                logger.debug("Explainability not available: %s", e)

            # Generate content hash for integrity
            import json

            content_str = json.dumps(receipt_data, sort_keys=True, default=str)
            receipt_data["content_hash"] = hashlib.sha256(content_str.encode()).hexdigest()

            return receipt_data

        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError) as e:
            logger.error("Failed to generate receipt: %s", e)
            # Fallback to minimal receipt
            return {
                "debate_id": getattr(result, "debate_id", getattr(result, "id", "")),
                "task": getattr(ctx, "task", getattr(result, "task", "")),
                "final_answer": getattr(result, "final_answer", ""),
                "confidence": getattr(result, "confidence", 0.0),
                "consensus_reached": getattr(result, "consensus_reached", False),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def _deliver_to_channel(
        self,
        receipt: dict[str, Any],
        subscription: Any,
    ) -> DeliveryResult:
        """Deliver a receipt to a specific channel."""
        channel_type = subscription.channel_type
        if hasattr(channel_type, "value"):
            channel_type = channel_type.value

        channel_id = subscription.channel_id
        workspace_id = subscription.workspace_id

        try:
            if channel_type == "slack":
                result = await self._send_to_slack(receipt, channel_id, workspace_id)
            elif channel_type == "teams":
                result = await self._send_to_teams(receipt, channel_id, workspace_id)
            elif channel_type == "email":
                result = await self._send_to_email(receipt, channel_id)
            elif channel_type == "webhook":
                result = await self._send_to_webhook(receipt, channel_id)
            else:
                result = DeliveryResult(
                    channel_type=channel_type,
                    channel_id=channel_id,
                    workspace_id=workspace_id,
                    success=False,
                    error=f"Unsupported channel type: {channel_type}",
                )

            self._delivery_history.append(result)
            return result

        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
            logger.warning("Receipt delivery failed (%s): %s", channel_type, e)
            result = DeliveryResult(
                channel_type=channel_type,
                channel_id=channel_id,
                workspace_id=workspace_id,
                success=False,
                error=f"delivery_failed:{channel_type}",
            )
            self._delivery_history.append(result)
            return result

    async def _send_to_slack(
        self,
        receipt: dict[str, Any],
        channel_id: str,
        workspace_id: str | None,
    ) -> DeliveryResult:
        """Send receipt to Slack."""
        if not workspace_id:
            return DeliveryResult(
                channel_type="slack",
                channel_id=channel_id,
                workspace_id=workspace_id,
                success=False,
                error="workspace_id is required for Slack",
            )

        try:
            from aragora.storage.slack_workspace_store import get_slack_workspace_store

            store = get_slack_workspace_store()
            workspace = store.get(workspace_id)
            if not workspace:
                return DeliveryResult(
                    channel_type="slack",
                    channel_id=channel_id,
                    workspace_id=workspace_id,
                    success=False,
                    error=f"Slack workspace not found: {workspace_id}",
                )

            connector = create_connector(
                "slack_chat",
                token=workspace.access_token,
                signing_secret=workspace.signing_secret or "",
            )

            # Format receipt for Slack
            blocks = self._format_receipt_for_slack(receipt)

            result = await connector.send_message(
                channel_id=channel_id,
                text="Decision Receipt",
                blocks=blocks,
            )

            return DeliveryResult(
                channel_type="slack",
                channel_id=channel_id,
                workspace_id=workspace_id,
                success=True,
                message_id=result.timestamp,
            )

        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, ImportError) as e:
            logger.warning("Receipt delivery failed (slack): %s", e)
            return DeliveryResult(
                channel_type="slack",
                channel_id=channel_id,
                workspace_id=workspace_id,
                success=False,
                error="delivery_failed:slack",
            )

    async def _send_to_teams(
        self,
        receipt: dict[str, Any],
        channel_id: str,
        workspace_id: str | None,
    ) -> DeliveryResult:
        """Send receipt to Microsoft Teams."""
        if not workspace_id:
            return DeliveryResult(
                channel_type="teams",
                channel_id=channel_id,
                workspace_id=workspace_id,
                success=False,
                error="workspace_id (tenant_id) is required for Teams",
            )

        try:
            from aragora.storage.teams_workspace_store import get_teams_workspace_store

            store = get_teams_workspace_store()
            workspace = store.get(workspace_id)
            if not workspace:
                return DeliveryResult(
                    channel_type="teams",
                    channel_id=channel_id,
                    workspace_id=workspace_id,
                    success=False,
                    error=f"Teams workspace not found: {workspace_id}",
                )

            connector = create_connector(
                "teams_chat",
                app_id=workspace.bot_id,
                app_password="",
                service_url=workspace.service_url or "https://smba.trafficmanager.net/amer/",
            )

            # Format receipt for Teams
            card_body = self._format_receipt_for_teams(receipt)

            result = await connector.send_message(
                channel_id=channel_id,
                conversation_id=channel_id,
                text="Decision Receipt",
                blocks=card_body,
            )

            return DeliveryResult(
                channel_type="teams",
                channel_id=channel_id,
                workspace_id=workspace_id,
                success=True,
                message_id=result.message_id,
            )

        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, ImportError) as e:
            logger.warning("Receipt delivery failed (teams): %s", e)
            return DeliveryResult(
                channel_type="teams",
                channel_id=channel_id,
                workspace_id=workspace_id,
                success=False,
                error="delivery_failed:teams",
            )

    async def _send_to_email(
        self,
        receipt: dict[str, Any],
        email_address: str,
    ) -> DeliveryResult:
        """Send receipt via email."""
        try:
            import os
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            smtp_host = os.environ.get("SMTP_HOST", "localhost")
            smtp_port = int(os.environ.get("SMTP_PORT", "587"))
            smtp_user = os.environ.get("SMTP_USER", "")
            smtp_password = os.environ.get("SMTP_PASSWORD", "")
            from_email = os.environ.get("SMTP_FROM", "aragora@localhost")

            # Format email content
            html_content, plain_content = self._format_receipt_for_email(receipt)

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Decision Receipt: {receipt.get('task', 'Unknown')[:50]}"
            msg["From"] = from_email
            msg["To"] = email_address

            msg.attach(MIMEText(plain_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                if smtp_user and smtp_password:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                server.send_message(msg)

            return DeliveryResult(
                channel_type="email",
                channel_id=email_address,
                workspace_id=None,
                success=True,
            )

        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
            logger.warning("Receipt delivery failed (email): %s", e)
            return DeliveryResult(
                channel_type="email",
                channel_id=email_address,
                workspace_id=None,
                success=False,
                error="delivery_failed:email",
            )

    async def _send_to_webhook(
        self,
        receipt: dict[str, Any],
        webhook_url: str,
    ) -> DeliveryResult:
        """Send receipt to a webhook."""
        try:
            import httpx

            payload = {
                "type": "decision_receipt",
                "receipt": receipt,
                "org_id": self.org_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if 200 <= response.status_code < 300:
                    return DeliveryResult(
                        channel_type="webhook",
                        channel_id=webhook_url,
                        workspace_id=None,
                        success=True,
                    )
                return DeliveryResult(
                    channel_type="webhook",
                    channel_id=webhook_url,
                    workspace_id=None,
                    success=False,
                    error=f"HTTP {response.status_code}",
                )

        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
            logger.warning("Receipt delivery failed (webhook): %s", e)
            return DeliveryResult(
                channel_type="webhook",
                channel_id=webhook_url,
                workspace_id=None,
                success=False,
                error="delivery_failed:webhook",
            )

    def _format_receipt_for_slack(self, receipt: dict[str, Any]) -> list[dict[str, Any]]:
        """Format receipt as Slack blocks."""
        consensus_emoji = ":white_check_mark:" if receipt.get("consensus_reached") else ":x:"
        confidence_pct = int(receipt.get("confidence", 0) * 100)

        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Decision Receipt",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Task:* {receipt.get('task', 'N/A')}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Consensus:* {consensus_emoji}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Confidence:* {confidence_pct}%",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Rounds:* {receipt.get('rounds_used', 0)}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Debate ID:* `{receipt.get('debate_id', 'N/A')[:8]}`",
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Decision:*\n{receipt.get('final_answer', 'No decision recorded')[:500]}",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Generated at {receipt.get('timestamp', datetime.now(timezone.utc).isoformat())}",
                    }
                ],
            },
        ]

    def _format_receipt_for_teams(self, receipt: dict[str, Any]) -> list[dict[str, Any]]:
        """Format receipt as Teams Adaptive Card body."""
        consensus_text = "Yes" if receipt.get("consensus_reached") else "No"
        confidence_pct = int(receipt.get("confidence", 0) * 100)

        return [
            {
                "type": "TextBlock",
                "text": "Decision Receipt",
                "weight": "bolder",
                "size": "large",
            },
            {"type": "TextBlock", "text": receipt.get("task", "N/A"), "wrap": True},
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Consensus", "value": consensus_text},
                    {"title": "Confidence", "value": f"{confidence_pct}%"},
                    {"title": "Rounds", "value": str(receipt.get("rounds_used", 0))},
                    {"title": "Debate ID", "value": receipt.get("debate_id", "N/A")[:8]},
                ],
            },
            {
                "type": "TextBlock",
                "text": "Decision:",
                "weight": "bolder",
            },
            {
                "type": "TextBlock",
                "text": receipt.get("final_answer", "No decision recorded")[:500],
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": f"Generated at {receipt.get('timestamp', datetime.now(timezone.utc).isoformat())}",
                "isSubtle": True,
                "size": "small",
            },
        ]

    def _format_receipt_for_email(self, receipt: dict[str, Any]) -> tuple[str, str]:
        """Format receipt for email (returns HTML and plain text)."""
        consensus_text = "Yes" if receipt.get("consensus_reached") else "No"
        confidence_pct = int(receipt.get("confidence", 0) * 100)

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h1 style="color: #333;">Decision Receipt</h1>
            <p><strong>Task:</strong> {receipt.get("task", "N/A")}</p>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;"><strong>Consensus</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{consensus_text}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;"><strong>Confidence</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{confidence_pct}%</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;"><strong>Rounds</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{receipt.get("rounds_used", 0)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;"><strong>Debate ID</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{receipt.get("debate_id", "N/A")}</td>
                </tr>
            </table>
            <h2 style="color: #333;">Decision</h2>
            <p>{receipt.get("final_answer", "No decision recorded")}</p>
            <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
            <p style="color: #666; font-size: 12px;">
                Generated at {receipt.get("timestamp", datetime.now(timezone.utc).isoformat())}
            </p>
        </body>
        </html>
        """

        plain = f"""
Decision Receipt
================

Task: {receipt.get("task", "N/A")}

Consensus: {consensus_text}
Confidence: {confidence_pct}%
Rounds: {receipt.get("rounds_used", 0)}
Debate ID: {receipt.get("debate_id", "N/A")}

Decision:
{receipt.get("final_answer", "No decision recorded")}

Generated at {receipt.get("timestamp", datetime.now(timezone.utc).isoformat())}
        """

        return html.strip(), plain.strip()

    def get_delivery_history(self) -> list[DeliveryResult]:
        """Get the delivery history."""
        return self._delivery_history.copy()


def create_receipt_delivery_hook(
    org_id: str,
    min_confidence: float = 0.0,
    require_consensus: bool = False,
    enabled: bool = True,
) -> ReceiptDeliveryHook:
    """Factory function to create a receipt delivery hook.

    Args:
        org_id: Organization ID to deliver receipts for
        min_confidence: Minimum confidence threshold for delivery
        require_consensus: Only deliver if consensus was reached
        enabled: Whether the hook is enabled

    Returns:
        Configured ReceiptDeliveryHook instance
    """
    return ReceiptDeliveryHook(
        org_id=org_id,
        min_confidence=min_confidence,
        require_consensus=require_consensus,
        enabled=enabled,
    )


__all__ = ["ReceiptDeliveryHook", "DeliveryResult", "create_receipt_delivery_hook"]
