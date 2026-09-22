"""
Command registry and built-in commands for the bot framework.

Provides a decorator-based system for registering commands that can be
invoked from any supported platform.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, cast
from collections.abc import Callable, Coroutine

from aragora.bots.base import (
    CommandContext,
    CommandResult,
    Platform,
)

logger = logging.getLogger(__name__)


def _get_api_base(ctx: CommandContext) -> str:
    """Get API base URL from command context.

    Returns:
        API base URL from metadata

    Raises:
        ValueError: If api_base is not configured in context metadata
    """
    import os

    api_base = ctx.metadata.get("api_base", "")
    if not api_base:
        # Check environment as fallback
        api_base = os.environ.get("ARAGORA_API_BASE", "")
    if not api_base:
        env = os.environ.get("ARAGORA_ENV", "production").lower()
        if env in ("production", "prod", "live"):
            raise ValueError("api_base not configured. Set ARAGORA_API_BASE environment variable.")
        # Development fallback only
        api_base = "http://localhost:8080"
    return api_base


# Type alias for command handlers
CommandHandler = Callable[[CommandContext], Coroutine[Any, Any, CommandResult]]


@dataclass
class BotCommand:
    """Definition of a bot command."""

    name: str
    handler: CommandHandler
    description: str = ""
    usage: str = ""
    aliases: list[str] = field(default_factory=list)
    platforms: set[Platform] = field(default_factory=lambda: set(Platform))
    requires_args: bool = False
    min_args: int = 0
    max_args: int | None = None
    admin_only: bool = False
    rate_limit: int | None = None  # Max calls per minute per user
    cooldown: float = 0  # Seconds between invocations

    def __post_init__(self) -> None:
        if not self.usage and self.requires_args:
            self.usage = f"{self.name} <args>"

    def matches_platform(self, platform: Platform) -> bool:
        """Check if command is available on the given platform."""
        return platform in self.platforms

    def validate_args(self, args: list[str]) -> str | None:
        """Validate argument count. Returns error message if invalid."""
        if self.requires_args and len(args) < 1:
            return f"Command '{self.name}' requires arguments. Usage: {self.usage}"
        if len(args) < self.min_args:
            return f"Command '{self.name}' requires at least {self.min_args} argument(s)."
        if self.max_args is not None and len(args) > self.max_args:
            return f"Command '{self.name}' accepts at most {self.max_args} argument(s)."
        return None


class CommandRegistry:
    """Registry for bot commands."""

    def __init__(self) -> None:
        self._commands: dict[str, BotCommand] = {}
        self._aliases: dict[str, str] = {}  # alias -> command name
        self._cooldowns: dict[str, dict[str, float]] = {}  # command -> user_id -> timestamp

    def register(self, command: BotCommand) -> None:
        """Register a command."""
        if command.name in self._commands:
            logger.warning("Overwriting existing command: %s", command.name)

        self._commands[command.name] = command

        # Register aliases
        for alias in command.aliases:
            if alias in self._aliases:
                logger.warning(
                    "Alias '%s' already registered for '%s'", alias, self._aliases[alias]
                )
            self._aliases[alias] = command.name

        logger.debug("Registered command: %s", command.name)

    def unregister(self, name: str) -> bool:
        """Unregister a command by name."""
        if name not in self._commands:
            return False

        command = self._commands.pop(name)

        # Remove aliases
        for alias in command.aliases:
            self._aliases.pop(alias, None)

        return True

    def get(self, name: str) -> BotCommand | None:
        """Get a command by name or alias."""
        # Check direct name first
        if name in self._commands:
            return self._commands[name]

        # Check aliases
        if name in self._aliases:
            return self._commands.get(self._aliases[name])

        return None

    def list_for_platform(self, platform: Platform) -> list[BotCommand]:
        """Get all commands available on a platform."""
        return [cmd for cmd in self._commands.values() if cmd.matches_platform(platform)]

    def list_commands(self, platform: Platform | None = None) -> list[BotCommand]:
        """List all registered commands, optionally filtered by platform."""
        if platform is not None:
            return self.list_for_platform(platform)
        return list(self._commands.values())

    def _check_cooldown(self, command: BotCommand, user_id: str) -> float | None:
        """Check if user is on cooldown. Returns remaining seconds if so."""
        if command.cooldown <= 0:
            return None

        if command.name not in self._cooldowns:
            self._cooldowns[command.name] = {}

        user_cooldowns = self._cooldowns[command.name]
        import time

        now = time.time()

        if user_id in user_cooldowns:
            elapsed = now - user_cooldowns[user_id]
            if elapsed < command.cooldown:
                return command.cooldown - elapsed

        return None

    def _update_cooldown(self, command: BotCommand, user_id: str) -> None:
        """Update cooldown timestamp for a user."""
        if command.cooldown <= 0:
            return

        if command.name not in self._cooldowns:
            self._cooldowns[command.name] = {}

        import time

        self._cooldowns[command.name][user_id] = time.time()

    async def execute(self, ctx: CommandContext) -> CommandResult:
        """Execute a command from context."""
        if not ctx.args:
            return CommandResult.fail("No command specified")

        command_name = ctx.args[0].lower()
        command = self.get(command_name)

        if not command:
            return CommandResult.fail(
                f"Unknown command: {command_name}. Use 'help' to see available commands."
            )

        # Check platform availability
        if not command.matches_platform(ctx.platform):
            return CommandResult.fail(
                f"Command '{command_name}' is not available on {ctx.platform.value}."
            )

        # Check cooldown
        remaining = self._check_cooldown(command, ctx.user_id)
        if remaining is not None:
            return CommandResult.fail(
                f"Please wait {remaining:.1f} seconds before using '{command_name}' again."
            )

        # Validate arguments (excluding command name)
        args = ctx.args[1:]
        error = command.validate_args(args)
        if error:
            return CommandResult.fail(error)

        # Create new context with parsed args
        exec_ctx = CommandContext(
            message=ctx.message,
            user=ctx.user,
            channel=ctx.channel,
            platform=ctx.platform,
            args=args,
            raw_args=" ".join(args),
            metadata=ctx.metadata,
        )

        try:
            result = await command.handler(exec_ctx)
            self._update_cooldown(command, ctx.user_id)
            return result
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
            logger.error("Command '%s' failed: %s", command_name, e, exc_info=True)
            return CommandResult.fail("Command failed. Please try again.")

    def command(
        self,
        name: str,
        description: str = "",
        usage: str = "",
        aliases: list[str] | None = None,
        platforms: set[Platform] | None = None,
        requires_args: bool = False,
        min_args: int = 0,
        max_args: int | None = None,
        admin_only: bool = False,
        rate_limit: int | None = None,
        cooldown: float = 0,
    ) -> Callable[[CommandHandler], CommandHandler]:
        """Decorator to register a command handler."""

        def decorator(handler: CommandHandler) -> CommandHandler:
            cmd = BotCommand(
                name=name,
                handler=handler,
                description=description,
                usage=usage,
                aliases=aliases or [],
                platforms=platforms or set(Platform),
                requires_args=requires_args,
                min_args=min_args,
                max_args=max_args,
                admin_only=admin_only,
                rate_limit=rate_limit,
                cooldown=cooldown,
            )
            self.register(cmd)
            return handler

        return decorator


# Global default registry
_default_registry: CommandRegistry | None = None


def get_default_registry() -> CommandRegistry:
    """Get or create the default command registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = CommandRegistry()
        _register_builtin_commands(_default_registry)
    return _default_registry


def command(
    name: str,
    description: str = "",
    **kwargs: Any,
) -> Callable[[CommandHandler], CommandHandler]:
    """Shorthand decorator using the default registry."""
    return get_default_registry().command(name, description, **kwargs)


# ---------------------------------------------------------------------------
# Debate routing helpers (used by builtin commands)
# ---------------------------------------------------------------------------


def _register_debate_origin_best_effort(debate_id: str, ctx: CommandContext, topic: str) -> None:
    """Register debate origin for bidirectional routing (best-effort)."""
    try:
        from aragora.server.debate_origin import register_debate_origin

        register_debate_origin(
            debate_id=debate_id,
            platform=ctx.platform.value,
            channel_id=ctx.channel_id,
            user_id=ctx.user_id,
            thread_id=ctx.thread_id,
            metadata={"topic": topic, "source": ctx.platform.value},
        )
    except (ImportError, RuntimeError, ValueError, TypeError) as exc:
        logger.debug("Failed to register debate origin: %s", exc)


def _format_debate_success(
    mode_label: str, topic: str, debate_id: str, api_base: str
) -> CommandResult:
    """Format a successful debate start response."""
    return CommandResult.ok(
        f"{mode_label} started on: **{topic}**\n"
        f"Debate ID: `{debate_id}`\n"
        f"View at: {api_base.replace('http://', 'https://')}/debate/{debate_id}",
        data={"debate_id": debate_id},
    )


async def _route_via_decision_router(
    ctx: CommandContext,
    topic: str,
    api_base: str,
    decision_integrity: dict[str, Any] | None,
    mode_label: str,
) -> CommandResult | None:
    """Attempt to route debate via DecisionRouter.

    Returns a ``CommandResult`` on success or failure, or ``None`` if the
    router is unavailable and the caller should fall back to HTTP.
    """
    from aragora.core.decision_models import (
        DecisionConfig,
        DecisionRequest,
        RequestContext,
        ResponseChannel,
    )
    from aragora.core import get_decision_router
    from aragora.core.decision_router import DecisionRouter
    from aragora.core.decision_types import DecisionType, InputSource

    platform_to_source: dict[Platform, InputSource] = {
        Platform.DISCORD: InputSource.DISCORD,
        Platform.TEAMS: InputSource.TEAMS,
        Platform.SLACK: InputSource.SLACK,
        Platform.TELEGRAM: InputSource.TELEGRAM,
        Platform.WHATSAPP: InputSource.WHATSAPP,
    }
    source = platform_to_source.get(ctx.platform, InputSource.HTTP_API)

    response_channel = ResponseChannel(
        platform=ctx.platform.value,
        channel_id=ctx.channel_id,
        user_id=ctx.user_id,
        thread_id=ctx.thread_id,
    )

    request_context = RequestContext(
        user_id=ctx.user_id,
        session_id=f"{ctx.platform.value}:{ctx.channel_id}",
    )

    config = None
    if decision_integrity is not None:
        config = DecisionConfig(decision_integrity=decision_integrity)

    request_kwargs: dict[str, Any] = {
        "content": topic,
        "decision_type": DecisionType.DEBATE,
        "source": source,
        "response_channels": [response_channel],
        "context": request_context,
        "attachments": ctx.message.attachments or [],
    }
    if config is not None:
        request_kwargs["config"] = config

    request = DecisionRequest(**request_kwargs)  # type: ignore[arg-type]

    _register_debate_origin_best_effort(request.request_id, ctx, topic)

    router_factory = cast(Callable[[], DecisionRouter], get_decision_router)
    router = router_factory()
    result = await router.route(request)

    if result.request_id and result.request_id != request.request_id:
        _register_debate_origin_best_effort(result.request_id, ctx, topic)

    debate_id = ""
    if result.debate_result and hasattr(result.debate_result, "debate_id"):
        debate_id = str(result.debate_result.debate_id)

    if debate_id:
        return _format_debate_success(mode_label, topic, debate_id, api_base)
    return CommandResult.fail(result.error or "Failed to start debate via router")


async def _route_via_http_api(
    ctx: CommandContext,
    topic: str,
    api_base: str,
    mode_label: str,
) -> CommandResult:
    """Route debate via HTTP API fallback."""
    from aragora.observability.http_client_pool import get_http_pool

    try:
        pool = get_http_pool()
        async with pool.get_session("aragora") as client:
            from aragora.config import DEFAULT_AGENTS, DEFAULT_ROUNDS

            resp = await client.post(
                f"{api_base}/api/debate",
                json={
                    "question": topic,
                    "agents": DEFAULT_AGENTS,
                    "rounds": DEFAULT_ROUNDS,
                    "metadata": {
                        "source": ctx.platform.value,
                        "channel_id": ctx.channel_id,
                        "user_id": ctx.user_id,
                        "thread_id": ctx.thread_id,
                    },
                },
                timeout=30,
            )
            data = resp.json()

            if resp.status_code == 200 and data.get("success"):
                debate_id = data.get("debate_id")
                return _format_debate_success(mode_label, topic, debate_id, api_base)
            error = data.get("error", "Unknown error")
            return CommandResult.fail(f"Failed to start debate: {error}")

    except asyncio.TimeoutError:
        return CommandResult.fail("Request timed out. Please try again.")
    except OSError as e:
        logger.error("Failed to start debate: %s", e)
        return CommandResult.fail("Failed to start debate. Please try again.")


async def _run_debate(
    ctx: CommandContext,
    *,
    decision_integrity: dict[str, Any] | None = None,
    require_integrity: bool = False,
    mode_label: str = "Debate",
    topic_override: str | None = None,
) -> CommandResult:
    """Run a debate via DecisionRouter (primary) or HTTP API (fallback)."""
    topic = topic_override if topic_override is not None else ctx.raw_args
    if not topic:
        return CommandResult.fail("Please provide a debate topic.")

    try:
        api_base = _get_api_base(ctx)
    except ValueError as e:
        return CommandResult.fail(f"Configuration error: {e}")

    # Primary path: DecisionRouter
    try:
        result = await _route_via_decision_router(
            ctx, topic, api_base, decision_integrity, mode_label
        )
        if result is not None:
            return result
    except ImportError:
        logger.debug("DecisionRouter not available, falling back to HTTP")
        if require_integrity:
            return CommandResult.fail("Decision integrity is unavailable without DecisionRouter.")
    except (ValueError, RuntimeError, OSError) as e:
        logger.warning("DecisionRouter failed, falling back to HTTP: %s", e)
        if require_integrity:
            return CommandResult.fail("Decision integrity failed to start.")

    # Fallback: HTTP API
    return await _route_via_http_api(ctx, topic, api_base, mode_label)


# ---------------------------------------------------------------------------
# Built-in command registration
# ---------------------------------------------------------------------------


def _register_builtin_commands(registry: CommandRegistry) -> None:
    """Register built-in commands."""

    @registry.command(
        "help",
        description="Show available commands",
        usage="help [command]",
        aliases=["?", "commands"],
    )
    async def cmd_help(ctx: CommandContext) -> CommandResult:
        """Show help for commands."""
        if ctx.args:
            cmd_name = ctx.args[0].lower()
            cmd = registry.get(cmd_name)
            if not cmd:
                return CommandResult.fail(f"Unknown command: {cmd_name}")

            message = f"**{cmd.name}**\n"
            if cmd.description:
                message += f"{cmd.description}\n"
            if cmd.usage:
                message += f"Usage: `{cmd.usage}`\n"
            if cmd.aliases:
                message += f"Aliases: {', '.join(cmd.aliases)}\n"

            return CommandResult.ok(message)

        commands = registry.list_for_platform(ctx.platform)
        if not commands:
            return CommandResult.ok("No commands available.")

        lines = ["**Available Commands:**"]
        for cmd in sorted(commands, key=lambda c: c.name):
            desc = f" - {cmd.description}" if cmd.description else ""
            lines.append(f"- `{cmd.name}`{desc}")

        return CommandResult.ok("\n".join(lines))

    @registry.command(
        "status",
        description="Check Aragora system status",
        aliases=["ping", "health"],
    )
    async def cmd_status(ctx: CommandContext) -> CommandResult:
        """Check system health status."""
        from aragora.observability.http_client_pool import get_http_pool

        try:
            api_base = _get_api_base(ctx)
        except ValueError as e:
            return CommandResult.fail(f"Configuration error: {e}")

        try:
            pool = get_http_pool()
            async with pool.get_session("aragora") as client:
                resp = await client.get(f"{api_base}/healthz", timeout=5)
                if resp.status_code == 200:
                    return CommandResult.ok("Aragora is online and healthy.")
                else:
                    return CommandResult.ok(f"Aragora returned status {resp.status_code}")
        except asyncio.TimeoutError:
            return CommandResult.fail("Health check timed out.")
        except OSError as e:
            logger.error("Health check failed: %s", e)
            return CommandResult.fail("Health check failed. Please try again.")

    @registry.command(
        "debate",
        description="Start a multi-agent debate",
        usage="debate <topic>",
        requires_args=True,
        min_args=1,
        cooldown=30,
    )
    async def cmd_debate(ctx: CommandContext) -> CommandResult:
        """Start a multi-agent debate on a topic via DecisionRouter."""
        return await _run_debate(ctx)

    @registry.command(
        "plan",
        description="Debate with an implementation plan",
        usage="plan <topic>",
        requires_args=True,
        min_args=1,
        cooldown=30,
    )
    async def cmd_plan(ctx: CommandContext) -> CommandResult:
        """Start a debate and generate an implementation plan."""
        return await _run_debate(
            ctx,
            decision_integrity={
                "include_receipt": True,
                "include_plan": True,
                "include_context": False,
                "plan_strategy": "single_task",
                "notify_origin": True,
                "requested_by": f"{ctx.platform.value}:{ctx.user_id}",
            },
            require_integrity=True,
            mode_label="Decision plan",
        )

    @registry.command(
        "implement",
        description="Debate with an implementation plan + context snapshot",
        usage="implement <topic>",
        requires_args=True,
        min_args=1,
        cooldown=30,
    )
    async def cmd_implement(ctx: CommandContext) -> CommandResult:
        """Start a debate and generate an implementation plan with context snapshot."""
        from aragora.pipeline.decision_integrity_utils import extract_execution_overrides

        cleaned_topic, overrides = extract_execution_overrides(ctx.raw_args)
        return await _run_debate(
            ctx,
            decision_integrity={
                "include_receipt": True,
                "include_plan": True,
                "include_context": True,
                "plan_strategy": "single_task",
                "notify_origin": True,
                "execution_mode": "execute",
                "execution_engine": "hybrid",
                "requested_by": f"{ctx.platform.value}:{ctx.user_id}",
                **overrides,
            },
            require_integrity=True,
            mode_label="Implementation plan",
            topic_override=cleaned_topic,
        )

    @registry.command(
        "gauntlet",
        description="Run adversarial stress-test validation",
        usage="gauntlet <statement or decision>",
        requires_args=True,
        min_args=1,
        cooldown=60,
    )
    async def cmd_gauntlet(ctx: CommandContext) -> CommandResult:
        """Run gauntlet validation on a statement."""
        from aragora.observability.http_client_pool import get_http_pool

        statement = ctx.raw_args
        if not statement:
            return CommandResult.fail("Please provide a statement to validate.")

        try:
            api_base = _get_api_base(ctx)
        except ValueError as e:
            return CommandResult.fail(f"Configuration error: {e}")

        try:
            pool = get_http_pool()
            async with pool.get_session("aragora") as client:
                resp = await client.post(
                    f"{api_base}/api/gauntlet/run",
                    json={
                        "statement": statement,
                        "intensity": "medium",
                        "metadata": {
                            "source": ctx.platform.value,
                            "channel_id": ctx.channel_id,
                            "user_id": ctx.user_id,
                        },
                    },
                    timeout=60,
                )
                data = resp.json()

                if resp.status_code == 200:
                    run_id = data.get("run_id")
                    return CommandResult.ok(
                        f"Gauntlet started for: **{statement[:100]}{'...' if len(statement) > 100 else ''}**\n"
                        f"Run ID: `{run_id}`\n"
                        f"Results will be posted when ready."
                    )
                else:
                    error = data.get("error", "Unknown error")
                    return CommandResult.fail(f"Failed to start gauntlet: {error}")

        except asyncio.TimeoutError:
            return CommandResult.fail("Request timed out. Please try again.")
        except OSError as e:
            logger.error("Failed to start gauntlet: %s", e)
            return CommandResult.fail("Failed to start gauntlet. Please try again.")
