"""
Microsoft Teams bot implementation for Aragora.

Provides Teams integration using the Bot Framework SDK for running debates
and gauntlet validations directly from Teams channels and chats.

Environment Variables:
- TEAMS_APP_ID - Required for bot authentication
- TEAMS_APP_PASSWORD - Required for bot authentication

Usage:
    from aragora.bots.teams_bot import create_teams_bot
    bot = create_teams_bot()
    # Use with Bot Framework adapter
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from aragora.config import DEFAULT_ROUNDS

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
from aragora.server.handlers.bots.teams_cards import (
    create_debate_card,
    create_consensus_card,
    create_leaderboard_card,
    create_help_card,
    create_error_card,
)

logger = logging.getLogger(__name__)

# Environment variables
TEAMS_APP_ID = os.environ.get("TEAMS_APP_ID", "")
TEAMS_APP_PASSWORD = os.environ.get("TEAMS_APP_PASSWORD", "")

# API base for Aragora backend (validated at bot initialization, not import time)
# The BotClient base class validates api_base in __init__ and provides appropriate
# error messages for production environments.
API_BASE = os.environ.get("ARAGORA_API_BASE", "")


def _check_botframework_available() -> tuple[bool, str | None]:
    """Check if Bot Framework SDK is available."""
    try:
        from botbuilder.core import TurnContext  # noqa: F401
        from botbuilder.schema import Activity  # noqa: F401

        return True, None
    except ImportError:
        return False, (
            "botbuilder-core is required. Install with: "
            "pip install botbuilder-core botbuilder-schema"
        )


class AragoraTeamsBot:
    """Microsoft Teams bot for Aragora platform integration.

    This bot handles:
    - Slash commands in channels and chats
    - Adaptive card interactions for voting
    - File attachments for gauntlet validation
    - Thread-based conversation tracking
    """

    def __init__(
        self,
        app_id: str,
        app_password: str,
    ):
        self.app_id = app_id
        self.app_password = app_password
        self._adapter: Any | None = None
        self.config = BotConfig(
            platform=Platform.TEAMS,
            token=app_password,
            app_id=app_id,
            api_base=API_BASE,
        )
        self.registry = get_default_registry()

    async def setup(self) -> None:
        """Set up the Teams bot with Bot Framework adapter."""
        available, error = _check_botframework_available()
        if not available:
            raise RuntimeError(error)

        from botbuilder.core import (
            BotFrameworkAdapter,
            BotFrameworkAdapterSettings,
        )

        settings = BotFrameworkAdapterSettings(
            app_id=self.app_id,
            app_password=self.app_password,
        )
        self._adapter = BotFrameworkAdapter(settings)

        logger.info("Teams bot adapter initialized")

    def get_adapter(self) -> Any:
        """Get the Bot Framework adapter for use with web server."""
        if not self._adapter:
            raise RuntimeError("Bot not set up. Call setup() first.")
        return self._adapter

    async def on_turn(self, turn_context: Any) -> None:
        """Handle incoming activities from Teams.

        This is the main entry point called by the Bot Framework adapter.
        """
        from botbuilder.schema import ActivityTypes

        activity = turn_context.activity

        if activity.type == ActivityTypes.message:
            await self._handle_message(turn_context)
        elif activity.type == ActivityTypes.invoke:
            await self._handle_invoke(turn_context)
        elif activity.type == ActivityTypes.conversation_update:
            await self._handle_conversation_update(turn_context)
        else:
            logger.debug("Unhandled activity type: %s", activity.type)

    async def _handle_message(self, turn_context: Any) -> None:
        """Handle incoming message activities."""
        activity = turn_context.activity
        text = (activity.text or "").strip()

        # Remove bot mention from text
        if activity.entities:
            for entity in activity.entities:
                if entity.type == "mention" and entity.mentioned:
                    mention_text = entity.text or ""
                    text = text.replace(mention_text, "").strip()

        if not text:
            await turn_context.send_activity(
                'Hi! I\'m Aragora. Try `/aragora help` or `/aragora debate "topic"` to get started.'
            )
            return

        # Parse command
        if text.startswith("/aragora "):
            text = text[9:].strip()  # Remove /aragora prefix
        elif text.startswith("/"):
            # Other slash command - extract command name
            parts = text[1:].split(maxsplit=1)
            text = " ".join(parts)

        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Create context and execute
        ctx = self._create_context(turn_context, command, args)
        result = await self.registry.execute(ctx)

        # Send response
        if result.success:
            if result.teams_card:
                await self._send_adaptive_card(turn_context, result.teams_card)
            else:
                card = self._result_to_card(result, command)
                if card:
                    await self._send_adaptive_card(turn_context, card)
                else:
                    await turn_context.send_activity(result.message or "Command executed.")
        else:
            await turn_context.send_activity(f"Error: {result.error}")

    async def _handle_invoke(self, turn_context: Any) -> None:
        """Handle invoke activities (card actions, etc.)."""
        from botbuilder.schema import InvokeResponse

        activity = turn_context.activity
        invoke_name = activity.name

        if invoke_name == "adaptiveCard/action":
            # Handle adaptive card action
            data = activity.value or {}
            action = data.get("action", "")

            if action.startswith("vote_"):
                response = await self._handle_vote(turn_context, data)
            else:
                response = {"status": "ok", "message": "Action received"}

            await turn_context.send_activity(
                type="invokeResponse",
                value=InvokeResponse(status=200, body=response),
            )
        else:
            logger.debug("Unhandled invoke: %s", invoke_name)

    async def _handle_conversation_update(self, turn_context: Any) -> None:
        """Handle conversation update activities (bot added, etc.)."""
        activity = turn_context.activity

        if activity.members_added:
            for member in activity.members_added:
                if member.id != activity.recipient.id:
                    continue  # Not the bot

                # Bot was added - send welcome message
                await turn_context.send_activity(
                    "Hello! I'm Aragora, a multi-agent debate system. "
                    "Use `/aragora help` to see available commands, or try "
                    '`/aragora debate "your topic"` to start a debate.'
                )

    async def _handle_vote(
        self,
        turn_context: Any,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle vote action from adaptive card."""
        action = data.get("action", "")
        parts = action.split("_")

        if len(parts) >= 3:
            debate_id = parts[1]
            vote = parts[2]
            user_id = turn_context.activity.from_property.id

            # Record vote
            try:
                from aragora.storage.debate_storage import get_debates_db

                db = get_debates_db()
                if db and hasattr(db, "record_vote"):
                    db.record_vote(
                        debate_id=debate_id,
                        voter_id=f"teams:{user_id}",
                        vote=vote,
                        source="teams",
                    )
            except (ImportError, OSError, ValueError, RuntimeError, TypeError) as e:
                logger.warning("Failed to record vote: %s", e)

            emoji = "thumbsup" if vote == "agree" else "thumbsdown"
            return {"status": "ok", "message": f":{emoji}: Your vote has been recorded!"}

        return {"status": "ok", "message": "Vote received"}

    def _create_context(
        self,
        turn_context: Any,
        command: str,
        args: str,
    ) -> CommandContext:
        """Create CommandContext from Teams turn context."""
        activity = turn_context.activity
        from_user = activity.from_property

        user = BotUser(
            id=from_user.id or "unknown",
            username=from_user.name or "unknown",
            display_name=from_user.name,
            platform=Platform.TEAMS,
        )

        channel = BotChannel(
            id=activity.channel_id or activity.conversation.id or "unknown",
            name=(
                activity.channel_data.get("channel", {}).get("name")
                if activity.channel_data
                else None
            ),
            is_dm=activity.conversation.conversation_type == "personal",
            platform=Platform.TEAMS,
        )

        message = BotMessage(
            id=activity.id or "unknown",
            text=f"/{command} {args}".strip(),
            user=user,
            channel=channel,
            timestamp=datetime.now(timezone.utc),
            platform=Platform.TEAMS,
        )

        return CommandContext(
            message=message,
            user=user,
            channel=channel,
            platform=Platform.TEAMS,
            args=[command] + (args.split() if args else []),
            raw_args=args,
            metadata={
                "api_base": self.config.api_base,
                "tenant_id": (
                    activity.channel_data.get("tenant", {}).get("id")
                    if activity.channel_data
                    else None
                ),
                "team_id": (
                    activity.channel_data.get("team", {}).get("id")
                    if activity.channel_data
                    else None
                ),
            },
        )

    async def _send_adaptive_card(
        self,
        turn_context: Any,
        card: dict[str, Any],
    ) -> None:
        """Send an adaptive card to the conversation."""
        from botbuilder.schema import Attachment, Activity, ActivityTypes

        attachment = Attachment(
            content_type="application/vnd.microsoft.card.adaptive",
            content=card,
        )

        activity = Activity(
            type=ActivityTypes.message,
            attachments=[attachment],
        )

        await turn_context.send_activity(activity)

    def _result_to_card(
        self,
        result: CommandResult,
        command: str,
    ) -> dict[str, Any] | None:
        """Convert CommandResult to Teams adaptive card using template functions."""
        if not result.success:
            return create_error_card(
                title="Command Failed",
                message=result.error or "An unexpected error occurred",
                retry_action={"action": "retry", "command": command},
            )

        if command == "debate" and result.data:
            debate_id = result.data.get("debate_id", "")
            topic = result.data.get("topic", result.message or "Debate in progress")
            agents = result.data.get("agents", ["claude", "gpt-4", "gemini"])
            return create_debate_card(
                debate_id=debate_id,
                topic=topic,
                agents=agents,
                progress=0,
                current_round=1,
                total_rounds=result.data.get("rounds", DEFAULT_ROUNDS),
                status="in_progress",
            )

        if command == "consensus" and result.data:
            return create_consensus_card(
                debate_id=result.data.get("debate_id", ""),
                topic=result.data.get("topic", ""),
                consensus_type=result.data.get("consensus_type", "majority"),
                final_answer=result.data.get("final_answer", result.message or ""),
                confidence=result.data.get("confidence", 0.8),
                supporting_agents=result.data.get("supporting_agents", []),
                dissenting_agents=result.data.get("dissenting_agents"),
                key_points=result.data.get("key_points"),
            )

        if command == "leaderboard" and result.data:
            standings = result.data.get("standings", [])
            period = result.data.get("period", "all_time")
            return create_leaderboard_card(standings=standings, period=period)

        if command == "gauntlet" and result.data:
            passed = result.data.get("passed", False)
            score = result.data.get("score", 0)
            color = "Good" if passed else "Attention"

            return {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "Gauntlet Results",
                        "weight": "Bolder",
                        "size": "Large",
                        "color": color,
                    },
                    {
                        "type": "TextBlock",
                        "text": result.message or "Validation complete",
                        "wrap": True,
                    },
                    {
                        "type": "FactSet",
                        "facts": [
                            {"title": "Status", "value": "PASSED" if passed else "FAILED"},
                            {"title": "Score", "value": f"{score:.1%}"},
                        ],
                    },
                ],
            }

        if command == "help":
            return create_help_card()

        return None


def create_teams_bot(
    app_id: str | None = None,
    app_password: str | None = None,
) -> AragoraTeamsBot:
    """Create an Aragora Teams bot instance.

    Args:
        app_id: Teams app ID (defaults to TEAMS_APP_ID env var)
        app_password: Teams app password (defaults to TEAMS_APP_PASSWORD env var)

    Returns:
        Configured AragoraTeamsBot instance (call .setup() to initialize)
    """
    app_id = app_id or TEAMS_APP_ID
    app_password = app_password or TEAMS_APP_PASSWORD

    if not app_id or not app_password:
        raise ValueError(
            "Teams credentials required. Set TEAMS_APP_ID and TEAMS_APP_PASSWORD env vars."
        )

    return AragoraTeamsBot(app_id, app_password)


__all__ = [
    "AragoraTeamsBot",
    "create_teams_bot",
]
