"""
Discord bot implementation for Aragora.

Provides Discord integration using discord.py with slash commands and
interactions for running debates and gauntlet validations.

Environment Variables:
- DISCORD_BOT_TOKEN - Required for bot authentication
- DISCORD_APPLICATION_ID - Required for slash commands

Usage:
    from aragora.bots.discord_bot import run_discord_bot
    await run_discord_bot()
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

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
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_APPLICATION_ID = os.environ.get("DISCORD_APPLICATION_ID", "")

# API base for Aragora backend (validated at bot initialization, not import time)
# The BotClient base class validates api_base in __init__ and provides appropriate
# error messages for production environments.
API_BASE = os.environ.get("ARAGORA_API_BASE", "")


def _check_discord_available() -> tuple[bool, str | None]:
    """Check if discord.py is available."""
    try:
        import discord  # noqa: F401

        return True, None
    except ImportError:
        return False, "discord.py is required. Install with: pip install discord.py"


class AragoraDiscordBot:
    """Discord bot for Aragora platform integration."""

    def __init__(self, token: str, application_id: str | None = None):
        self.token = token
        self.application_id = application_id
        self._client: Any | None = None
        self._tree: Any | None = None
        self.config = BotConfig(
            platform=Platform.DISCORD,
            token=token,
            app_id=application_id,
            api_base=API_BASE,
        )
        self.registry = get_default_registry()

    async def setup(self) -> None:
        """Set up the Discord bot with slash commands."""
        available, error = _check_discord_available()
        if not available:
            raise RuntimeError(error)

        import discord
        from discord import app_commands

        intents = discord.Intents.default()
        intents.message_content = True

        client = discord.Client(intents=intents)
        tree = app_commands.CommandTree(client)
        self._client = client
        self._tree = tree

        # Register event handlers
        @client.event
        async def on_ready():
            logger.info("Discord bot logged in as %s", client.user)
            # Sync slash commands
            if self.application_id:
                await tree.sync()
                logger.info("Discord slash commands synced")

        @client.event
        async def on_message(message: discord.Message):
            # Ignore bot messages
            if message.author.bot:
                return

            # Handle DMs or mentions
            if isinstance(message.channel, discord.DMChannel):
                await self._handle_dm(message)
            elif client.user and client.user.mentioned_in(message):
                await self._handle_mention(message)

        # Register slash commands
        self._register_slash_commands()

    def _register_slash_commands(self) -> None:
        """Register Discord slash commands."""
        import discord
        from discord import app_commands

        tree = self._tree
        if tree is None:
            raise RuntimeError("Discord command tree is not initialized; call setup() first")

        @tree.command(name="aragora", description="Aragora multi-agent debate commands")
        @app_commands.describe(
            command="The command to run (debate, gauntlet, status, help)",
            args="Arguments for the command",
        )
        async def aragora_command(
            interaction: discord.Interaction,
            command: str,
            args: str | None = None,
        ):
            await self._handle_slash_command(interaction, command, args or "")

        @tree.command(name="debate", description="Start a multi-agent debate on a topic")
        @app_commands.describe(topic="The topic to debate")
        async def debate_command(interaction: discord.Interaction, topic: str):
            await self._handle_slash_command(interaction, "debate", topic)

        @tree.command(name="gauntlet", description="Run adversarial stress-test validation")
        @app_commands.describe(statement="The statement to validate")
        async def gauntlet_command(interaction: discord.Interaction, statement: str):
            await self._handle_slash_command(interaction, "gauntlet", statement)

        @tree.command(name="status", description="Check Aragora system status")
        async def status_command(interaction: discord.Interaction):
            await self._handle_slash_command(interaction, "status", "")

    async def _handle_slash_command(
        self,
        interaction: Any,  # discord.Interaction
        command: str,
        args: str,
    ) -> None:
        """Handle a slash command."""

        # Create command context
        ctx = self._create_context_from_interaction(interaction, command, args)

        # Defer response for long-running commands
        if command in ("debate", "gauntlet"):
            await interaction.response.defer()

        # Execute command
        ctx.args = [command] + (args.split() if args else [])
        ctx.raw_args = args
        result = await self.registry.execute(ctx)

        # Send response
        if command in ("debate", "gauntlet"):
            await interaction.followup.send(
                content=result.message or result.error,
                embed=self._result_to_embed(result, command) if result.success else None,
            )
        else:
            await interaction.response.send_message(
                content=result.message or result.error,
                ephemeral=result.ephemeral,
            )

    async def _handle_dm(self, message: Any) -> None:
        """Handle direct messages."""
        text = message.content.strip()

        if not text:
            await message.reply("Hi! Use `help` to see available commands.")
            return

        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        ctx = self._create_context_from_message(message, command, args)
        ctx.args = [command] + (args.split() if args else [])
        ctx.raw_args = args

        result = await self.registry.execute(ctx)

        if result.success:
            embed = self._result_to_embed(result, command)
            if embed:
                await message.reply(content=result.message, embed=embed)
            else:
                await message.reply(result.message)
        else:
            await message.reply(f"Error: {result.error}")

    async def _handle_mention(self, message: Any) -> None:
        """Handle @mentions of the bot."""

        # Remove mention from text
        text = message.content
        if self._client and self._client.user:
            text = text.replace(f"<@{self._client.user.id}>", "").strip()
            text = text.replace(f"<@!{self._client.user.id}>", "").strip()

        if not text:
            await message.reply(
                'Hi! I\'m Aragora. Use `/aragora help` or `/debate "topic"` to get started.'
            )
            return

        # Try to parse as command
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        ctx = self._create_context_from_message(message, command, args)
        ctx.args = [command] + (args.split() if args else [])
        ctx.raw_args = args

        result = await self.registry.execute(ctx)

        if result.success:
            await message.reply(result.message or "Command executed.")
        else:
            await message.reply(f"Error: {result.error}")

    def _create_context_from_interaction(
        self,
        interaction: Any,  # discord.Interaction
        command: str,
        args: str,
    ) -> CommandContext:
        """Create CommandContext from Discord interaction."""
        user = BotUser(
            id=str(interaction.user.id),
            username=interaction.user.name,
            display_name=interaction.user.display_name,
            is_bot=interaction.user.bot,
            platform=Platform.DISCORD,
        )

        channel = BotChannel(
            id=str(interaction.channel_id) if interaction.channel_id else "unknown",
            name=getattr(interaction.channel, "name", None),
            is_dm=interaction.guild is None,
            platform=Platform.DISCORD,
        )

        message = BotMessage(
            id=str(interaction.id),
            text=f"/{command} {args}".strip(),
            user=user,
            channel=channel,
            timestamp=datetime.now(timezone.utc),
            platform=Platform.DISCORD,
        )

        return CommandContext(
            message=message,
            user=user,
            channel=channel,
            platform=Platform.DISCORD,
            metadata={
                "api_base": self.config.api_base,
                "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
            },
        )

    def _create_context_from_message(
        self,
        message: Any,  # discord.Message
        command: str,
        args: str,
    ) -> CommandContext:
        """Create CommandContext from Discord message."""
        user = BotUser(
            id=str(message.author.id),
            username=message.author.name,
            display_name=message.author.display_name,
            is_bot=message.author.bot,
            platform=Platform.DISCORD,
        )

        channel = BotChannel(
            id=str(message.channel.id),
            name=getattr(message.channel, "name", None),
            is_dm=not hasattr(message.channel, "guild"),
            platform=Platform.DISCORD,
        )

        bot_message = BotMessage(
            id=str(message.id),
            text=message.content,
            user=user,
            channel=channel,
            timestamp=message.created_at,
            platform=Platform.DISCORD,
        )

        return CommandContext(
            message=bot_message,
            user=user,
            channel=channel,
            platform=Platform.DISCORD,
            metadata={
                "api_base": self.config.api_base,
                "guild_id": str(message.guild.id) if message.guild else None,
            },
        )

    def _result_to_embed(self, result: CommandResult, command: str) -> Any | None:
        """Convert CommandResult to Discord embed."""
        import discord

        if not result.success:
            return None

        if result.discord_embed:
            return discord.Embed.from_dict(result.discord_embed)

        # Create default embed for specific commands
        if command == "debate" and result.data:
            embed = discord.Embed(
                title="Debate Started",
                description=result.message,
                color=discord.Color.green(),
            )
            if "debate_id" in result.data:
                embed.add_field(name="Debate ID", value=result.data["debate_id"], inline=True)
            return embed

        if command == "gauntlet" and result.data:
            passed = result.data.get("passed", False)
            embed = discord.Embed(
                title="Gauntlet Results",
                description=result.message,
                color=discord.Color.green() if passed else discord.Color.red(),
            )
            if "score" in result.data:
                embed.add_field(name="Score", value=f"{result.data['score']:.1%}", inline=True)
            return embed

        return None

    async def run(self) -> None:
        """Run the Discord bot."""
        if self._client is None:
            await self.setup()

        client = self._client
        if client is None:
            raise RuntimeError("Discord client initialization failed")

        logger.info("Starting Discord bot...")
        await client.start(self.token)

    async def close(self) -> None:
        """Close the Discord bot connection."""
        if self._client:
            await self._client.close()


async def run_discord_bot(
    token: str | None = None,
    application_id: str | None = None,
) -> None:
    """Run the Aragora Discord bot.

    Args:
        token: Discord bot token (defaults to DISCORD_BOT_TOKEN env var)
        application_id: Discord application ID (defaults to DISCORD_APPLICATION_ID env var)
    """
    token = token or DISCORD_BOT_TOKEN
    application_id = application_id or DISCORD_APPLICATION_ID

    if not token:
        raise ValueError("Discord bot token is required. Set DISCORD_BOT_TOKEN env var.")

    bot = AragoraDiscordBot(token, application_id)
    await bot.setup()
    await bot.run()


def create_discord_bot(
    token: str | None = None,
    application_id: str | None = None,
) -> AragoraDiscordBot:
    """Create an Aragora Discord bot instance.

    Args:
        token: Discord bot token (defaults to DISCORD_BOT_TOKEN env var)
        application_id: Discord application ID (defaults to DISCORD_APPLICATION_ID env var)

    Returns:
        Configured AragoraDiscordBot instance (call .setup() and .run() to start)
    """
    token = token or DISCORD_BOT_TOKEN
    application_id = application_id or DISCORD_APPLICATION_ID

    if not token:
        raise ValueError("Discord bot token is required. Set DISCORD_BOT_TOKEN env var.")

    return AragoraDiscordBot(token, application_id)


__all__ = [
    "AragoraDiscordBot",
    "run_discord_bot",
    "create_discord_bot",
]
