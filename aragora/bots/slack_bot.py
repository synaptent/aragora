"""
Slack bot implementation for Aragora.

Provides Slack integration using the Bolt framework with slash commands
and interactions for running debates and gauntlet validations.

Environment Variables:
- SLACK_BOT_TOKEN - Required for bot authentication (xoxb-...)
- SLACK_APP_TOKEN - Required for Socket Mode (xapp-...)
- SLACK_SIGNING_SECRET - Required for webhook verification

Usage:
    from aragora.bots.slack_bot import run_slack_bot
    await run_slack_bot()
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable

from aragora.audit.unified import audit_action
from aragora.bots.base import (
    BotChannel,
    BotConfig,
    BotMessage,
    BotUser,
    CommandContext,
    CommandResult,
    Platform,
)
from aragora.bots.commands import get_default_registry

logger = logging.getLogger(__name__)

# Environment variables
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")

# API base for Aragora backend (validated at bot initialization, not import time)
# The BotClient base class validates api_base in __init__ and provides appropriate
# error messages for production environments.
API_BASE = os.environ.get("ARAGORA_API_BASE", "")


def _check_slack_available() -> tuple[bool, str | None]:
    """Check if slack_bolt is available."""
    try:
        from slack_bolt.async_app import AsyncApp  # noqa: F401

        return True, None
    except ImportError:
        return False, "slack_bolt is required. Install with: pip install slack-bolt"


class AragoraSlackBot:
    """Slack bot for Aragora platform integration."""

    def __init__(
        self,
        token: str,
        app_token: str | None = None,
        signing_secret: str | None = None,
    ):
        self.token = token
        self.app_token = app_token
        self.signing_secret = signing_secret
        self._app: Any | None = None
        self._handler: Any | None = None
        self.config = BotConfig(
            platform=Platform.SLACK,
            token=token,
            signing_secret=signing_secret,
            api_base=API_BASE,
        )
        self.registry = get_default_registry()

    async def setup(self) -> None:
        """Set up the Slack bot with event handlers."""
        available, error = _check_slack_available()
        if not available:
            raise RuntimeError(error)

        from slack_bolt.async_app import AsyncApp

        # Initialize app with appropriate mode
        if self.signing_secret:
            self._app = AsyncApp(
                token=self.token,
                signing_secret=self.signing_secret,
            )
        else:
            self._app = AsyncApp(token=self.token)

        # Register event handlers
        self._register_event_handlers()

        # Register slash commands
        self._register_slash_commands()

        logger.info("Slack bot setup complete")

    def _register_event_handlers(self) -> None:
        """Register Slack event handlers."""

        app = self._app
        if app is None:
            raise RuntimeError("Slack app is not initialized; call setup() first")

        @app.event("app_mention")
        async def handle_app_mention(event: dict[str, Any], say: Callable) -> None:
            """Handle @mentions of the bot."""
            await self._handle_mention(event, say)

        @app.event("message")
        async def handle_message(event: dict[str, Any], say: Callable) -> None:
            """Handle direct messages and channel messages."""
            # Skip bot messages and thread replies to avoid loops
            if event.get("bot_id") or event.get("subtype"):
                return

            # Only respond to DMs
            channel_type = event.get("channel_type", "")
            if channel_type == "im":
                await self._handle_dm(event, say)

    def _register_slash_commands(self) -> None:
        """Register Slack slash commands."""

        app = self._app
        if app is None:
            raise RuntimeError("Slack app is not initialized; call setup() first")

        @app.command("/aragora")
        async def handle_aragora_command(
            ack: Callable, body: dict[str, Any], respond: Callable
        ) -> None:
            """Handle /aragora command."""
            await ack()
            text = body.get("text", "").strip()
            parts = text.split(maxsplit=1)
            command = parts[0].lower() if parts else "help"
            args = parts[1] if len(parts) > 1 else ""
            await self._handle_slash_command(body, command, args, respond)

        @app.command("/debate")
        async def handle_debate_command(
            ack: Callable, body: dict[str, Any], respond: Callable
        ) -> None:
            """Handle /debate command."""
            await ack()
            topic = body.get("text", "").strip()
            await self._handle_slash_command(body, "debate", topic, respond)

        @app.command("/gauntlet")
        async def handle_gauntlet_command(
            ack: Callable, body: dict[str, Any], respond: Callable
        ) -> None:
            """Handle /gauntlet command."""
            await ack()
            statement = body.get("text", "").strip()
            await self._handle_slash_command(body, "gauntlet", statement, respond)

        @app.command("/aragora-status")
        async def handle_status_command(
            ack: Callable, body: dict[str, Any], respond: Callable
        ) -> None:
            """Handle /aragora-status command."""
            await ack()
            await self._handle_slash_command(body, "status", "", respond)

    async def _handle_slash_command(
        self,
        body: dict[str, Any],
        command: str,
        args: str,
        respond: Callable,
    ) -> None:
        """Handle a slash command."""
        ctx = self._create_context_from_body(body, command, args)
        ctx.args = [command] + (args.split() if args else [])
        ctx.raw_args = args

        # Audit slash command execution
        audit_action(
            user_id=body.get("user_id", "unknown"),
            action="slack_slash_command",
            resource_type="slack_bot",
            resource_id=body.get("channel_id", "unknown"),
            command=command,
            team_id=body.get("team_id"),
            channel_name=body.get("channel_name"),
        )

        result = await self.registry.execute(ctx)

        # Format response with Slack blocks if available
        blocks = self._result_to_blocks(result, command)
        await respond(
            text=result.message or result.error or "Command executed.",
            blocks=blocks,
            response_type="in_channel" if not result.ephemeral else "ephemeral",
        )

    async def _handle_dm(self, event: dict[str, Any], say: Callable) -> None:
        """Handle direct messages."""
        text = event.get("text", "").strip()

        if not text:
            await say("Hi! Use `help` to see available commands.")
            return

        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Audit DM command
        audit_action(
            user_id=event.get("user", "unknown"),
            action="slack_dm_command",
            resource_type="slack_bot",
            resource_id=event.get("channel", "unknown"),
            command=command,
            team_id=event.get("team"),
        )

        ctx = self._create_context_from_event(event, command, args)
        ctx.args = [command] + (args.split() if args else [])
        ctx.raw_args = args

        result = await self.registry.execute(ctx)

        blocks = self._result_to_blocks(result, command)
        if result.success:
            await say(
                text=result.message or "Done",
                blocks=blocks,
                thread_ts=event.get("thread_ts"),
            )
        else:
            await say(
                text=f"Error: {result.error}",
                thread_ts=event.get("thread_ts"),
            )

    async def _handle_mention(self, event: dict[str, Any], say: Callable) -> None:
        """Handle @mentions of the bot."""
        text = event.get("text", "").strip()

        # Remove bot mention from text (handles both <@BOTID> and <@BOTID|botname>)
        import re

        text = re.sub(r"<@[A-Z0-9]+(?:\|[^>]+)?>", "", text).strip()

        # Audit bot mention
        audit_action(
            user_id=event.get("user", "unknown"),
            action="slack_bot_mention",
            resource_type="slack_bot",
            resource_id=event.get("channel", "unknown"),
            team_id=event.get("team"),
            has_command=bool(text),
        )

        if not text:
            await say(
                'Hi! I\'m Aragora. Use `/aragora help` or `/debate "topic"` to get started.',
                thread_ts=event.get("ts"),
            )
            return

        # Try to parse as command
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        ctx = self._create_context_from_event(event, command, args)
        ctx.args = [command] + (args.split() if args else [])
        ctx.raw_args = args

        result = await self.registry.execute(ctx)

        if result.success:
            await say(
                text=result.message or "Command executed.",
                thread_ts=event.get("ts"),
            )
        else:
            await say(
                text=f"Error: {result.error}",
                thread_ts=event.get("ts"),
            )

    def _create_context_from_body(
        self,
        body: dict[str, Any],
        command: str,
        args: str,
    ) -> CommandContext:
        """Create CommandContext from Slack slash command body."""
        user = BotUser(
            id=body.get("user_id", "unknown"),
            username=body.get("user_name", "unknown"),
            platform=Platform.SLACK,
        )

        channel = BotChannel(
            id=body.get("channel_id", "unknown"),
            name=body.get("channel_name"),
            platform=Platform.SLACK,
        )

        message = BotMessage(
            id=body.get("trigger_id", "unknown"),
            text=f"/{command} {args}".strip(),
            user=user,
            channel=channel,
            timestamp=datetime.now(timezone.utc),
            platform=Platform.SLACK,
        )

        return CommandContext(
            message=message,
            user=user,
            channel=channel,
            platform=Platform.SLACK,
            metadata={
                "api_base": self.config.api_base,
                "team_id": body.get("team_id"),
                "enterprise_id": body.get("enterprise_id"),
                "response_url": body.get("response_url"),
            },
        )

    def _create_context_from_event(
        self,
        event: dict[str, Any],
        command: str,
        args: str,
    ) -> CommandContext:
        """Create CommandContext from Slack event."""
        user = BotUser(
            id=event.get("user", "unknown"),
            username=event.get("user", "unknown"),
            platform=Platform.SLACK,
        )

        channel = BotChannel(
            id=event.get("channel", "unknown"),
            is_dm=event.get("channel_type") == "im",
            platform=Platform.SLACK,
            thread_id=event.get("thread_ts"),
        )

        message = BotMessage(
            id=event.get("ts", "unknown"),
            text=event.get("text", ""),
            user=user,
            channel=channel,
            timestamp=datetime.now(timezone.utc),
            platform=Platform.SLACK,
            thread_id=event.get("thread_ts"),
        )

        return CommandContext(
            message=message,
            user=user,
            channel=channel,
            platform=Platform.SLACK,
            metadata={
                "api_base": self.config.api_base,
                "team": event.get("team"),
            },
        )

    def _result_to_blocks(
        self,
        result: CommandResult,
        command: str,
    ) -> list[dict[str, Any]] | None:
        """Convert CommandResult to Slack blocks."""
        if result.slack_blocks:
            return result.slack_blocks

        if not result.success:
            return None

        # Create default blocks for specific commands
        blocks: list[dict[str, Any]] = []

        if command == "debate" and result.data:
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "Debate Started", "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": result.message or "Debate started"},
                },
            ]
            if "debate_id" in result.data:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": f"Debate ID: `{result.data['debate_id']}`"}
                        ],
                    }
                )
            return blocks

        if command == "gauntlet" and result.data:
            passed = result.data.get("passed", False)
            emoji = ":white_check_mark:" if passed else ":x:"
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"Gauntlet Results {emoji}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": result.message or "Validation complete"},
                },
            ]
            if "score" in result.data:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": f"Score: *{result.data['score']:.1%}*"}
                        ],
                    }
                )
            return blocks

        if command == "help":
            return [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": result.message or "Help"},
                }
            ]

        return None

    async def run(self) -> None:
        """Run the Slack bot."""
        if not self._app:
            await self.setup()

        logger.info("Starting Slack bot...")

        # Use Socket Mode if app token is available
        if self.app_token:
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

            self._handler = AsyncSocketModeHandler(self._app, self.app_token)
            await self._handler.start_async()
        else:
            # Run as HTTP server for webhook-based events
            logger.info("Running Slack bot in HTTP mode (no app token)")
            logger.info("Configure event subscriptions to point to your server.")
            # The app can be mounted as an ASGI/WSGI app
            # For standalone, you would use: await self._app.start_async(port=3000)

    async def close(self) -> None:
        """Close the Slack bot connection."""
        if self._handler:
            await self._handler.close_async()

    def get_app(self) -> Any:
        """Get the underlying Slack Bolt app for custom integration."""
        return self._app


async def run_slack_bot(
    token: str | None = None,
    app_token: str | None = None,
    signing_secret: str | None = None,
) -> None:
    """Run the Aragora Slack bot.

    Args:
        token: Slack bot token (defaults to SLACK_BOT_TOKEN env var)
        app_token: Slack app token for Socket Mode (defaults to SLACK_APP_TOKEN env var)
        signing_secret: Slack signing secret (defaults to SLACK_SIGNING_SECRET env var)
    """
    token = token or SLACK_BOT_TOKEN
    app_token = app_token or SLACK_APP_TOKEN
    signing_secret = signing_secret or SLACK_SIGNING_SECRET

    if not token:
        raise ValueError("Slack bot token is required. Set SLACK_BOT_TOKEN env var.")

    bot = AragoraSlackBot(token, app_token, signing_secret)
    await bot.setup()
    await bot.run()


def create_slack_bot(
    token: str | None = None,
    app_token: str | None = None,
    signing_secret: str | None = None,
) -> AragoraSlackBot:
    """Create an Aragora Slack bot instance.

    Args:
        token: Slack bot token (defaults to SLACK_BOT_TOKEN env var)
        app_token: Slack app token for Socket Mode (defaults to SLACK_APP_TOKEN env var)
        signing_secret: Slack signing secret (defaults to SLACK_SIGNING_SECRET env var)

    Returns:
        Configured AragoraSlackBot instance (call .setup() and .run() to start)
    """
    token = token or SLACK_BOT_TOKEN
    app_token = app_token or SLACK_APP_TOKEN
    signing_secret = signing_secret or SLACK_SIGNING_SECRET

    if not token:
        raise ValueError("Slack bot token is required. Set SLACK_BOT_TOKEN env var.")

    return AragoraSlackBot(token, app_token, signing_secret)


__all__ = [
    "AragoraSlackBot",
    "run_slack_bot",
    "create_slack_bot",
]
