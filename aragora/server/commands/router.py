"""
Command router for dispatching slash commands.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from .models import CommandContext, CommandResult, CommandError
from .registry import CommandRegistry, get_command_registry

logger = logging.getLogger(__name__)


class CommandRouter:
    """
    Routes incoming commands to their handlers.

    Handles:
    - Command lookup (including aliases)
    - Permission checking
    - Rate limiting
    - Error handling
    - Audit logging
    """

    def __init__(self, registry: CommandRegistry | None = None) -> None:
        self.registry = registry or get_command_registry()
        self._rate_limits: dict[str, list[float]] = defaultdict(list)  # user_id -> timestamps

    async def route(self, ctx: CommandContext) -> CommandResult:
        """
        Route a command to its handler.

        Args:
            ctx: Command context with name, args, user info, etc.

        Returns:
            CommandResult from the handler or error result.
        """
        command_name = ctx.command_name.lower().lstrip("/")

        # Check if command exists
        definition = self.registry.get_command(command_name)
        if not definition:
            return self._unknown_command_result(command_name, ctx.platform)

        # Check platform support
        if ctx.platform not in definition.platforms:
            return CommandResult.error(
                f"Command `/{command_name}` is not available on {ctx.platform}.",
                ephemeral=True,
            )

        # Check rate limit
        if not self._check_rate_limit(ctx.user_id, definition.rate_limit):
            return CommandResult.error(
                f"Rate limit exceeded. Please wait before using `/{command_name}` again.",
                ephemeral=True,
            )

        # Get handler
        handler = self.registry.get_handler(command_name)
        if not handler:
            logger.error("Handler not found for registered command: %s", command_name)
            return CommandResult.error("Command handler not found.", ephemeral=True)

        # Execute handler
        try:
            start_time = time.time()
            result = await handler(ctx)
            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                "Command executed: /%s by %s on %s in %.1fms - success=%s",
                command_name,
                ctx.user_id,
                ctx.platform,
                duration_ms,
                result.success,
            )

            return result

        except CommandError as e:
            logger.warning("Command error in /%s: %s", command_name, e.message)
            return e.to_result()

        except Exception as e:  # noqa: BLE001 - Top-level command handler: must catch all errors to return error result
            logger.exception("Unexpected error in command /%s", command_name)
            return CommandResult.error(
                f"An error occurred while executing the command: {e!s}",
                ephemeral=True,
            )

    def _check_rate_limit(self, user_id: str, limit: int) -> bool:
        """
        Check if user is within rate limit.

        Args:
            user_id: User identifier.
            limit: Max calls per minute.

        Returns:
            True if within limit, False if exceeded.
        """
        now = time.time()
        window_start = now - 60  # 1 minute window

        # Clean old entries
        self._rate_limits[user_id] = [ts for ts in self._rate_limits[user_id] if ts > window_start]

        # Check limit
        if len(self._rate_limits[user_id]) >= limit:
            return False

        # Record this call
        self._rate_limits[user_id].append(now)
        return True

    def _unknown_command_result(self, command_name: str, platform: str) -> CommandResult:
        """Generate result for unknown command with suggestions."""
        # Get similar commands for suggestions
        all_commands = self.registry.list_commands(platform=platform)
        suggestions = []
        for cmd in all_commands[:5]:  # Top 5 suggestions
            if command_name[:2] == cmd.name[:2]:  # Simple prefix match
                suggestions.append(cmd.name)

        message = f"Unknown command: `/{command_name}`"
        if suggestions:
            message += f"\n\nDid you mean: {', '.join(f'`/{s}`' for s in suggestions)}"
        message += "\n\nUse `/help` to see available commands."

        return CommandResult.error(message, ephemeral=True)


def parse_command_text(text: str) -> tuple[str, list[str]]:
    """
    Parse command text into name and arguments.

    Args:
        text: Raw command text (e.g., "/debate start topic here")

    Returns:
        Tuple of (command_name, args_list)
    """
    text = text.strip()
    if text.startswith("/"):
        text = text[1:]

    parts = text.split(maxsplit=1)
    if not parts:
        return "", []

    command_name = parts[0].lower()
    args_text = parts[1] if len(parts) > 1 else ""

    # Parse args (simple space-separated, respecting quotes)
    args = []
    if args_text:
        in_quote = False
        current_arg: list[str] = []
        for char in args_text:
            if char == '"' and (not current_arg or current_arg[-1] != "\\"):
                in_quote = not in_quote
            elif char == " " and not in_quote:
                if current_arg:
                    args.append("".join(current_arg))
                    current_arg = []
            else:
                current_arg.append(char)
        if current_arg:
            args.append("".join(current_arg))

    return command_name, args
