"""
Slack integration for aragora debates.

Posts debate summaries, consensus alerts, and error notifications to Slack channels.
Uses Slack's Block Kit for rich message formatting.
"""

from __future__ import annotations

import logging
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
class SlackConfig:
    """Configuration for Slack integration."""

    webhook_url: str
    channel: str = "#debates"
    bot_name: str = "Aragora"
    icon_emoji: str = ":speech_balloon:"

    # Notification settings
    notify_on_consensus: bool = True
    notify_on_debate_end: bool = True
    notify_on_error: bool = True

    # Minimum confidence for consensus alerts
    min_consensus_confidence: float = 0.7

    # Rate limiting
    max_messages_per_minute: int = 10

    def __post_init__(self) -> None:
        if not self.webhook_url:
            raise ValueError("Slack webhook URL is required")


@dataclass
class SlackMessage:
    """A Slack message with optional blocks."""

    text: str
    blocks: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self, config: SlackConfig) -> dict[str, Any]:
        """Convert to Slack webhook payload."""
        payload: dict[str, Any] = {
            "text": self.text,
            "username": config.bot_name,
            "icon_emoji": config.icon_emoji,
        }
        if self.blocks:
            payload["blocks"] = self.blocks
        if self.attachments:
            payload["attachments"] = self.attachments
        return payload


class SlackIntegration:
    """
    Slack integration for posting debate events.

    Usage:
        slack = SlackIntegration(SlackConfig(
            webhook_url="https://hooks.slack.com/services/...",
            channel="#debates"
        ))

        # Post debate summary
        await slack.post_debate_summary(debate_result)

        # Post consensus alert
        await slack.send_consensus_alert(debate_id, confidence=0.85)
    """

    def __init__(self, config: SlackConfig):
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._message_count = 0
        self._last_reset = datetime.now()
        self._circuit_breaker = (
            get_circuit_breaker("slack_api", provider="slack")
            if get_circuit_breaker is not None
            else None
        )

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
            logger.warning("Slack rate limit reached, skipping message")
            return False

        self._message_count += 1
        return True

    async def _send_message(self, message: SlackMessage, max_retries: int = 3) -> bool:
        """Send a message to Slack with retry logic and circuit breaker.

        Args:
            message: The message to send
            max_retries: Maximum number of retry attempts (default: 3)

        Returns:
            True if message was sent successfully
        """
        if not self._check_rate_limit():
            return False

        # Check circuit breaker before attempting
        if self._circuit_breaker is not None and not self._circuit_breaker.can_proceed():
            remaining = self._circuit_breaker.cooldown_remaining()
            logger.warning("Slack circuit breaker open, retry in %.1fs", remaining)
            return False

        import asyncio

        session = await self._get_session()
        payload = message.to_payload(self.config)
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
                        logger.debug("Slack message sent successfully")
                        if self._circuit_breaker is not None:
                            self._circuit_breaker.record_success()
                        return True
                    elif response.status == 429:
                        # Rate limited by Slack - respect Retry-After header
                        retry_after = int(response.headers.get("Retry-After", "5"))
                        logger.warning("Slack rate limited, retrying after %ss", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    elif response.status >= 500:
                        # Server error - retry with backoff
                        text = await response.text()
                        logger.warning(
                            "Slack server error (attempt %s): %s - %s",
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
                        logger.error("Slack API error: %s - %s", response.status, text)
                        return False

            except aiohttp.ClientError as e:
                last_error = e
                logger.warning("Slack connection error (attempt %s): %s", attempt + 1, e)
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
                    continue
            except asyncio.TimeoutError:
                last_error = asyncio.TimeoutError()
                logger.warning("Slack request timed out (attempt %s)", attempt + 1)
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
                    continue
            except (ValueError, TypeError, KeyError) as e:
                # Payload construction or data format error -- not retryable
                last_error = e
                logger.error(
                    "Slack payload error (attempt %s): %s: %s", attempt + 1, type(e).__name__, e
                )
                break
            except OSError as e:
                # Low-level network/socket error -- retryable
                last_error = e
                logger.warning(
                    "Slack network error (attempt %s): %s: %s", attempt + 1, type(e).__name__, e
                )
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
                    continue

        logger.error("Slack message failed after %s attempts: %s", max_retries, last_error)
        return False

    async def verify_webhook(self) -> bool:
        """Verify Slack webhook connectivity by sending a test message."""
        if not self.config.webhook_url:
            return False

        message = SlackMessage(text="Aragora integration test")
        return await self._send_message(message)

    async def post_debate_summary(self, result: DebateResult) -> bool:
        """Post a debate summary to Slack.

        Args:
            result: The debate result to summarize

        Returns:
            True if message was sent successfully
        """
        if not self.config.notify_on_debate_end:
            return True

        # Build blocks for rich formatting
        blocks = self._build_debate_summary_blocks(result)

        # Fallback text
        consensus_text = "reached" if result.consensus_reached else "not reached"
        text = f"Debate completed: {result.task[:50]}... - Consensus {consensus_text}"

        message = SlackMessage(text=text, blocks=blocks)
        return await self._send_message(message)

    def _build_debate_summary_blocks(self, result: DebateResult) -> list[dict[str, Any]]:
        """Build Block Kit blocks for debate summary."""
        blocks: list[dict[str, Any]] = []

        # Header
        status_emoji = ":white_check_mark:" if result.consensus_reached else ":x:"
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{status_emoji} Debate Completed",
                    "emoji": True,
                },
            }
        )

        # Task description
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Task:* {result.task}"}}
        )

        # Divider
        blocks.append({"type": "divider"})

        # Results section
        consensus_status = "Reached" if result.consensus_reached else "Not Reached"
        winner_text = result.winner or "No clear winner"
        confidence = getattr(result, "confidence", 0.0)

        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Consensus:*\n{consensus_status}"},
                    {"type": "mrkdwn", "text": f"*Winner:*\n{winner_text}"},
                    {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
                    {"type": "mrkdwn", "text": f"*Rounds:*\n{result.rounds_used}"},
                ],
            }
        )

        # Final answer preview if consensus reached
        if result.consensus_reached and result.final_answer:
            preview = result.final_answer[:500]
            if len(result.final_answer) > 500:
                preview += "..."

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Final Proposal:*\n```{preview}```"},
                }
            )

        # Context footer
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":robot_face: Aragora AI Debate System | {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
                    }
                ],
            }
        )

        return blocks

    async def send_consensus_alert(
        self,
        debate_id: str,
        confidence: float,
        winner: str | None = None,
        task: str | None = None,
    ) -> bool:
        """Send a consensus reached notification.

        Args:
            debate_id: ID of the debate
            confidence: Consensus confidence score
            winner: Winning agent name
            task: Task description

        Returns:
            True if message was sent successfully
        """
        if not self.config.notify_on_consensus:
            return True

        if confidence < self.config.min_consensus_confidence:
            logger.debug(
                "Skipping consensus alert: confidence %s < %s",
                confidence,
                self.config.min_consensus_confidence,
            )
            return True

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": ":tada: Consensus Reached!", "emoji": True},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Debate:*\n{debate_id[:8]}..."},
                    {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
                ],
            },
        ]

        if winner:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Winning Position:* {winner}"},
                }
            )

        if task:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Task: _{task[:100]}{'...' if len(task) > 100 else ''}_",
                        }
                    ],
                }
            )

        text = f"Consensus reached in debate {debate_id[:8]}... with {confidence:.0%} confidence"
        message = SlackMessage(text=text, blocks=blocks)
        return await self._send_message(message)

    async def send_error_alert(
        self,
        error_type: str,
        error_message: str,
        debate_id: str | None = None,
        severity: str = "warning",
    ) -> bool:
        """Send an error notification.

        Args:
            error_type: Type of error
            error_message: Error details
            debate_id: Optional debate ID
            severity: One of "info", "warning", "error", "critical"

        Returns:
            True if message was sent successfully
        """
        if not self.config.notify_on_error:
            return True

        severity_emojis = {
            "info": ":information_source:",
            "warning": ":warning:",
            "error": ":x:",
            "critical": ":rotating_light:",
        }
        emoji = severity_emojis.get(severity, ":warning:")

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} {error_type}", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{error_message[:1000]}```"},
            },
        ]

        if debate_id:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"Debate: `{debate_id}`"}],
                }
            )

        text = f"{error_type}: {error_message[:100]}"
        message = SlackMessage(text=text, blocks=blocks)
        return await self._send_message(message)

    async def send_leaderboard_update(
        self,
        rankings: list[dict[str, Any]],
        top_n: int = 5,
    ) -> bool:
        """Send a leaderboard update.

        Args:
            rankings: List of agent rankings with name, elo, wins, etc.
            top_n: Number of top agents to show

        Returns:
            True if message was sent successfully
        """
        top_agents = rankings[:top_n]

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":trophy: Agent Leaderboard Update",
                    "emoji": True,
                },
            }
        ]

        for i, agent in enumerate(top_agents):
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"#{i + 1}"
            name = agent.get("name", "Unknown")
            elo = agent.get("elo", 1500)
            wins = agent.get("wins", 0)

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{medal} *{name}* - ELO: {elo:.0f} | Wins: {wins}",
                    },
                }
            )

        text = f"Leaderboard update: {top_agents[0].get('name', 'Unknown') if top_agents else 'No agents'} leads"
        message = SlackMessage(text=text, blocks=blocks)
        return await self._send_message(message)

    async def post_debate_with_voting(
        self,
        debate_id: str,
        task: str,
        agents: list[str],
        current_round: int,
        total_rounds: int,
        thread_ts: str | None = None,
    ) -> str | None:
        """Post a debate message with interactive voting buttons.

        Args:
            debate_id: Unique debate identifier
            task: The debate task/question
            agents: List of participating agent names
            current_round: Current round number
            total_rounds: Total number of rounds
            thread_ts: Optional thread timestamp for threaded replies

        Returns:
            Message timestamp (ts) for threading, or None on failure
        """
        blocks = self._build_debate_with_voting_blocks(
            debate_id, task, agents, current_round, total_rounds
        )

        text = f"Active debate: {task[:50]}..."
        message = SlackMessage(text=text, blocks=blocks)

        # Note: For interactive messages, you need Slack Bot API, not webhooks
        # This is a simplified version using webhooks
        success = await self._send_message(message)
        return debate_id if success else None

    def _build_debate_with_voting_blocks(
        self,
        debate_id: str,
        task: str,
        agents: list[str],
        current_round: int,
        total_rounds: int,
    ) -> list[dict[str, Any]]:
        """Build Block Kit blocks for debate with voting."""
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":speech_balloon: Active Debate",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Task:* {task}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Agents:*\n{', '.join(agents)}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Progress:*\nRound {current_round}/{total_rounds}",
                    },
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Cast your vote:* Your vote will be counted in the final consensus.",
                },
            },
        ]

        # Add voting buttons for each agent (max 5 due to Slack limits)
        buttons = []
        for i, agent in enumerate(agents[:5]):
            btn: dict[str, Any] = {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": f"Vote {agent}",
                    "emoji": True,
                },
                "action_id": f"vote_{debate_id}_{agent}",
                "value": f'{{"debate_id":"{debate_id}","agent":"{agent}"}}',
            }
            if i == 0:
                btn["style"] = "primary"
            buttons.append(btn)

        blocks.append(
            {
                "type": "actions",
                "elements": buttons,
            }
        )

        # Add view/provenance buttons
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": ":mag: View Summary",
                            "emoji": True,
                        },
                        "action_id": f"summary_{debate_id}",
                        "value": debate_id,
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": ":lock: Audit Trail",
                            "emoji": True,
                        },
                        "action_id": f"provenance_{debate_id}",
                        "value": debate_id,
                    },
                ],
            }
        )

        # Footer
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":robot_face: Aragora | Debate `{debate_id[:8]}...` | {datetime.now().strftime('%H:%M UTC')}",
                    },
                ],
            }
        )

        return blocks

    async def update_debate_progress(
        self,
        debate_id: str,
        current_round: int,
        total_rounds: int,
        latest_argument: str | None = None,
        agent_name: str | None = None,
    ) -> bool:
        """Update debate progress in Slack thread.

        Args:
            debate_id: Debate identifier
            current_round: Current round number
            total_rounds: Total rounds
            latest_argument: Preview of latest argument
            agent_name: Name of agent who made the argument

        Returns:
            True if update was sent successfully
        """
        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":arrows_counterclockwise: *Round {current_round}/{total_rounds}*",
                },
            },
        ]

        if agent_name and latest_argument:
            preview = latest_argument[:200]
            if len(latest_argument) > 200:
                preview += "..."
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{agent_name}:*\n_{preview}_",
                    },
                }
            )

        text = f"Round {current_round}/{total_rounds}"
        message = SlackMessage(text=text, blocks=blocks)
        return await self._send_message(message)

    async def post_consensus_with_votes(
        self,
        debate_id: str,
        result: DebateResult,
        user_votes: dict[str, int],
    ) -> bool:
        """Post consensus result including user votes from Slack.

        Args:
            debate_id: Debate identifier
            result: The debate result
            user_votes: Dict of agent -> vote count from Slack users

        Returns:
            True if message was sent successfully
        """
        blocks = self._build_consensus_with_votes_blocks(debate_id, result, user_votes)

        status = "reached" if result.consensus_reached else "not reached"
        text = f"Debate completed: Consensus {status}"

        message = SlackMessage(text=text, blocks=blocks)
        return await self._send_message(message)

    def _build_consensus_with_votes_blocks(
        self,
        debate_id: str,
        result: DebateResult,
        user_votes: dict[str, int],
    ) -> list[dict[str, Any]]:
        """Build consensus result blocks with user vote counts."""
        status_emoji = ":white_check_mark:" if result.consensus_reached else ":x:"
        status_text = "Consensus Reached" if result.consensus_reached else "No Consensus"

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{status_emoji} {status_text}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Task:* {result.task}",
                },
            },
        ]

        # Results
        confidence = getattr(result, "confidence", 0.0)
        fields = [
            {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
            {"type": "mrkdwn", "text": f"*Rounds:*\n{result.rounds_used}"},
        ]

        if result.winner:
            fields.append({"type": "mrkdwn", "text": f"*Winner:*\n{result.winner}"})

        blocks.append(
            {
                "type": "section",
                "fields": fields,
            }
        )

        # User votes section
        if user_votes:
            total_votes = sum(user_votes.values())
            vote_lines = []
            for agent, count in sorted(user_votes.items(), key=lambda x: -x[1]):
                pct = (count / total_votes * 100) if total_votes > 0 else 0
                vote_lines.append(
                    f"• {agent}: {count} vote{'s' if count != 1 else ''} ({pct:.0f}%)"
                )

            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*:busts_in_silhouette: User Votes ({total_votes} total):*\n"
                        + "\n".join(vote_lines),
                    },
                }
            )

        # Final answer preview
        if result.consensus_reached and result.final_answer:
            preview = result.final_answer[:400]
            if len(result.final_answer) > 400:
                preview += "..."

            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Final Decision:*\n```{preview}```",
                    },
                }
            )

        # Action buttons
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": ":page_facing_up: Full Report",
                            "emoji": True,
                        },
                        "url": f"https://aragora.ai/debate/{debate_id}",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": ":lock: Audit Trail",
                            "emoji": True,
                        },
                        "url": f"https://aragora.ai/debates/provenance?debate={debate_id}",
                    },
                ],
            }
        )

        # Footer
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":robot_face: Aragora Control Plane | {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
                    },
                ],
            }
        )

        return blocks


__all__ = [
    "SlackConfig",
    "SlackMessage",
    "SlackIntegration",
]
