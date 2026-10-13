"""
Microsoft Teams integration for aragora debates.

Posts debate summaries, consensus alerts, and error notifications to Teams channels
using Incoming Webhooks with Adaptive Cards for rich formatting.

Requires:
    TEAMS_WEBHOOK_URL environment variable

Usage:
    teams = TeamsIntegration(TeamsConfig(
        webhook_url="https://xxx.webhook.office.com/webhookb2/..."
    ))
    await teams.post_debate_summary(debate_result)
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp

from aragora.core import DebateResult
from aragora.http_client import DEFAULT_TIMEOUT

try:
    from aragora.observability.tracing import build_trace_headers
except ImportError:

    def build_trace_headers() -> dict[str, str]:
        return {}


try:
    from aragora.resilience.registry import get_circuit_breaker
except ImportError:
    get_circuit_breaker = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass
class TeamsConfig:
    """Configuration for Microsoft Teams integration."""

    webhook_url: str = ""
    bot_name: str = "Aragora"

    # Notification settings
    notify_on_consensus: bool = True
    notify_on_debate_end: bool = True
    notify_on_error: bool = True
    notify_on_leaderboard: bool = False

    # Minimum confidence for consensus alerts
    min_consensus_confidence: float = 0.7

    # Rate limiting
    max_messages_per_minute: int = 10

    # Colors for adaptive cards
    accent_color: str = "good"  # "good", "warning", "attention"

    def __post_init__(self) -> None:
        if not self.webhook_url:
            self.webhook_url = os.environ.get("TEAMS_WEBHOOK_URL", "")
        if not self.webhook_url:
            logger.warning("Teams webhook URL not configured")


@dataclass
class AdaptiveCard:
    """Microsoft Teams Adaptive Card."""

    title: str
    body: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    accent_color: str = "good"

    def to_payload(self) -> dict[str, Any]:
        """Convert to Teams message card payload."""
        card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "size": "Large",
                    "weight": "Bolder",
                    "text": self.title,
                    "wrap": True,
                },
                *self.body,
            ],
        }

        if self.actions:
            card["actions"] = self.actions

        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card,
                }
            ],
        }


class TeamsIntegration:
    """
    Microsoft Teams integration for posting debate events.

    Uses Incoming Webhooks with Adaptive Cards for rich message formatting.

    Usage:
        teams = TeamsIntegration(TeamsConfig(
            webhook_url="https://xxx.webhook.office.com/webhookb2/..."
        ))

        # Post debate summary
        await teams.post_debate_summary(debate_result)

        # Post consensus alert
        await teams.send_consensus_alert(debate_id, answer="...", confidence=0.85)

        # Post error notification
        await teams.send_error_alert(debate_id, error="...")
    """

    def __init__(self, config: TeamsConfig | None = None):
        self.config = config or TeamsConfig()
        self._session: aiohttp.ClientSession | None = None
        self._message_count = 0
        self._last_reset = datetime.now()
        self._circuit_breaker = (
            get_circuit_breaker("teams_api", provider="teams")
            if get_circuit_breaker is not None
            else None
        )

    @property
    def is_configured(self) -> bool:
        """Check if Teams integration is configured."""
        return bool(self.config.webhook_url)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with timeout protection."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits."""
        now = datetime.now()
        elapsed = (now - self._last_reset).total_seconds()

        if elapsed >= 60:
            self._message_count = 0
            self._last_reset = now

        if self._message_count >= self.config.max_messages_per_minute:
            logger.warning("Teams rate limit reached, skipping message")
            return False

        self._message_count += 1
        return True

    async def _send_card(self, card: AdaptiveCard, max_retries: int = 3) -> bool:
        """Send an adaptive card to Teams with retry logic.

        Args:
            card: The adaptive card to send
            max_retries: Maximum number of retry attempts (default: 3)

        Returns:
            True if message was sent successfully
        """
        if not self.is_configured:
            logger.warning("Teams webhook not configured, skipping message")
            return False

        if not self._check_rate_limit():
            return False

        # Check circuit breaker before attempting
        if self._circuit_breaker is not None and not self._circuit_breaker.can_proceed():
            remaining = self._circuit_breaker.cooldown_remaining()
            logger.warning("Teams circuit breaker open, retry in %.1fs", remaining)
            return False

        session = await self._get_session()
        payload = card.to_payload()
        headers = build_trace_headers()

        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                async with session.post(
                    self.config.webhook_url,
                    json=payload,
                    headers=headers if headers else None,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        if self._circuit_breaker is not None:
                            self._circuit_breaker.record_success()
                        logger.debug("Teams message sent successfully")
                        return True
                    elif response.status == 429:
                        # Rate limited by Teams - respect Retry-After header
                        retry_after = int(response.headers.get("Retry-After", "5"))
                        logger.warning("Teams rate limited, retrying after %ss", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    elif response.status >= 500:
                        # Server error - retry with backoff
                        text = await response.text()
                        logger.warning(
                            "Teams server error (attempt %s): %s - %s",
                            attempt + 1,
                            response.status,
                            text,
                        )
                        if self._circuit_breaker is not None:
                            self._circuit_breaker.record_failure()
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                        return False
                    else:
                        # Client error - don't retry
                        text = await response.text()
                        logger.error("Teams API error: %s - %s", response.status, text)
                        return False

            except aiohttp.ClientError as e:
                last_error = e
                logger.warning("Teams connection error (attempt %s): %s", attempt + 1, e)
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
                    continue
            except asyncio.TimeoutError:
                last_error = asyncio.TimeoutError()
                logger.warning("Teams request timed out (attempt %s)", attempt + 1)
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
                    continue

        logger.error("Teams message failed after %s attempts: %s", max_retries, last_error)
        return False

    async def verify_webhook(self) -> bool:
        """Verify Teams webhook connectivity by sending a test card."""
        if not self.is_configured:
            return False

        card = AdaptiveCard(
            title="Aragora integration test",
            body=[
                {
                    "type": "TextBlock",
                    "text": "Connection verified.",
                    "wrap": True,
                }
            ],
            accent_color=self.config.accent_color,
        )
        return await self._send_card(card)

    async def post_debate_summary(self, result: DebateResult) -> bool:
        """Post a debate summary to Teams.

        Args:
            result: The debate result to summarize

        Returns:
            True if message was sent successfully
        """
        if not self.config.notify_on_debate_end:
            return False

        # Build adaptive card body
        body = []

        # Question
        body.append(
            {
                "type": "TextBlock",
                "text": f"**Question:** {result.task}",
                "wrap": True,
            }
        )

        # Answer
        if result.final_answer:
            body.append(
                {
                    "type": "TextBlock",
                    "text": f"**Answer:** {result.final_answer}",
                    "wrap": True,
                }
            )

        # Statistics
        rounds_used = (
            result.rounds_used or getattr(result, "total_rounds", 0) or result.rounds_completed
        )
        confidence = result.confidence or getattr(result, "consensus_confidence", 0.0)
        agents: list[str] = []
        for attr in ("participants", "participating_agents", "agents", "agents_involved"):
            value = getattr(result, attr, None)
            if value:
                agents = list(value)
                break

        stats_text = f"Rounds: {rounds_used}"
        if confidence:
            stats_text += f" | Confidence: {confidence:.0%}"
        if agents:
            stats_text += f" | Agents: {len(agents)}"

        body.append(
            {
                "type": "TextBlock",
                "text": stats_text,
                "size": "Small",
                "color": "Accent",
            }
        )

        # Agents column set
        if agents:
            agent_list = ", ".join(agents[:5])
            if len(agents) > 5:
                agent_list += f" +{len(agents) - 5} more"
            body.append(
                {
                    "type": "TextBlock",
                    "text": f"*Participants: {agent_list}*",
                    "size": "Small",
                    "isSubtle": True,
                    "wrap": True,
                }
            )

        card = AdaptiveCard(
            title=f"Debate Complete: {result.debate_id[:8]}",
            body=body,
            actions=[
                {
                    "type": "Action.OpenUrl",
                    "title": "View Details",
                    "url": f"https://aragora.ai/debate/{result.debate_id}",
                }
            ],
        )

        return await self._send_card(card)

    async def send_consensus_alert(
        self,
        debate_id: str,
        answer: str,
        confidence: float,
        agents: list[str] | None = None,
    ) -> bool:
        """Send a consensus reached alert.

        Args:
            debate_id: ID of the debate
            answer: The consensus answer
            confidence: Confidence level (0-1)
            agents: List of participating agents

        Returns:
            True if message was sent successfully
        """
        if not self.config.notify_on_consensus:
            return False

        if confidence < self.config.min_consensus_confidence:
            return False

        body: list[dict[str, Any]] = [
            {
                "type": "TextBlock",
                "text": f"**Consensus:** {answer[:500]}{'...' if len(answer) > 500 else ''}",
                "wrap": True,
            },
            {
                "type": "ColumnSet",
                "columns": [
                    {
                        "type": "Column",
                        "width": "auto",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": f"Confidence: **{confidence:.0%}**",
                                "color": "Good" if confidence >= 0.8 else "Warning",
                            }
                        ],
                    },
                ],
            },
        ]

        if agents:
            body.append(
                {
                    "type": "TextBlock",
                    "text": f"*Agreement from: {', '.join(agents[:5])}*",
                    "size": "Small",
                    "isSubtle": True,
                }
            )

        card = AdaptiveCard(
            title="Consensus Reached",
            body=body,
            accent_color="good",
            actions=[
                {
                    "type": "Action.OpenUrl",
                    "title": "View Debate",
                    "url": f"https://aragora.ai/debate/{debate_id}",
                }
            ],
        )

        return await self._send_card(card)

    async def send_error_alert(
        self,
        debate_id: str,
        error: str,
        phase: str | None = None,
    ) -> bool:
        """Send an error notification.

        Args:
            debate_id: ID of the debate
            error: Error message
            phase: Current phase when error occurred

        Returns:
            True if message was sent successfully
        """
        if not self.config.notify_on_error:
            return False

        body = [
            {
                "type": "TextBlock",
                "text": f"**Error:** {error}",
                "color": "Attention",
                "wrap": True,
            },
        ]

        if phase:
            body.append(
                {
                    "type": "TextBlock",
                    "text": f"*Phase: {phase}*",
                    "size": "Small",
                    "isSubtle": True,
                }
            )

        body.append(
            {
                "type": "TextBlock",
                "text": f"Debate ID: {debate_id}",
                "size": "Small",
                "isSubtle": True,
            }
        )

        card = AdaptiveCard(
            title="Debate Error",
            body=body,
            accent_color="attention",
        )

        return await self._send_card(card)

    async def send_leaderboard_update(
        self,
        rankings: list[dict[str, Any]],
        domain: str | None = None,
    ) -> bool:
        """Send a leaderboard update.

        Args:
            rankings: List of agent rankings with name, elo, wins, losses
            domain: Optional domain for domain-specific rankings

        Returns:
            True if message was sent successfully
        """
        if not self.config.notify_on_leaderboard:
            return False

        title = f"Leaderboard Update{f' ({domain})' if domain else ''}"

        # Build ranking rows
        body = []
        for i, agent in enumerate(rankings[:10], 1):
            medal = {1: "1", 2: "2", 3: "3"}.get(i, str(i))
            body.append(
                {
                    "type": "TextBlock",
                    "text": f"{medal}. **{agent['name']}** - ELO: {agent.get('elo', 1500):.0f} ({agent.get('wins', 0)}W/{agent.get('losses', 0)}L)",
                    "spacing": "Small",
                }
            )

        card = AdaptiveCard(
            title=title,
            body=body,
            actions=[
                {
                    "type": "Action.OpenUrl",
                    "title": "Full Leaderboard",
                    "url": "https://aragora.ai/leaderboard",
                }
            ],
        )

        return await self._send_card(card)

    async def __aenter__(self) -> TeamsIntegration:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
