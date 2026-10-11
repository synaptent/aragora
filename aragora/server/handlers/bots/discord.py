"""
Discord Interactions endpoint handler.

Handles Discord's HTTP-based Interactions API for slash commands
when not using the gateway (WebSocket) connection.

Endpoints:
- POST /api/bots/discord/interactions - Handle Discord interactions

Environment Variables:
- DISCORD_APPLICATION_ID - Required for interaction verification
- DISCORD_PUBLIC_KEY - Required for Ed25519 signature verification

Security (Phase 3.1):
- Ed25519 signature verification on all incoming interactions
- Replay attack protection via timestamp freshness checking (5-minute window)
- Fails closed in production: rejects requests when public key or PyNaCl missing
- Uses centralized webhook_security module for environment-aware behavior
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.server.handlers.bots.base import BotHandlerMixin
from aragora.server.handlers.secure import SecureHandler
from aragora.server.handlers.utils.rate_limit import rate_limit

# RBAC imports - optional dependency
try:
    from aragora.rbac.checker import check_permission
    from aragora.rbac.models import AuthorizationContext

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

logger = logging.getLogger(__name__)

# Environment variables - None defaults make misconfiguration explicit
DISCORD_APPLICATION_ID = os.environ.get("DISCORD_APPLICATION_ID")
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY")

# Maximum age of request timestamp before it is considered a replay (seconds)
_MAX_TIMESTAMP_AGE = 300  # 5 minutes, matching Discord's recommendation

# PyNaCl availability flag - checked once at import time for logging
_NACL_AVAILABLE = False
try:
    from nacl.signing import VerifyKey  # noqa: F401
    from nacl.exceptions import BadSignatureError  # noqa: F401

    _NACL_AVAILABLE = True
except ImportError:
    pass

# Log at debug level for unconfigured optional integrations
if not DISCORD_PUBLIC_KEY:
    logger.debug("DISCORD_PUBLIC_KEY not configured - signature verification disabled")
if not _NACL_AVAILABLE:
    logger.debug(
        "PyNaCl not installed - Discord Ed25519 signature verification unavailable. "
        "Install with: pip install pynacl"
    )


def _should_allow_unverified() -> bool:
    """Check if unverified Discord webhooks should be allowed.

    Uses the centralized webhook_security module for environment-aware behavior.
    In production: always returns False (fail closed).
    In development: returns True only with explicit ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS.
    """
    try:
        from aragora.connectors.chat.webhook_security import should_allow_unverified

        return should_allow_unverified("discord")
    except ImportError:
        # If webhook_security module is not available, fail closed
        logger.warning("webhook_security module not available, failing closed")
        return False


def _verify_discord_signature(
    signature: str,
    timestamp: str,
    body: bytes,
) -> bool:
    """Verify Discord request signature using Ed25519.

    Security properties:
    - Validates the request was signed by Discord using the application's public key
    - Rejects requests with timestamps older than 5 minutes (replay protection)
    - Fails closed in production when public key or PyNaCl is missing
    - Permits unverified requests only in dev mode with explicit opt-in

    See: https://discord.com/developers/docs/interactions/receiving-and-responding

    Args:
        signature: Value of X-Signature-Ed25519 header (hex-encoded).
        timestamp: Value of X-Signature-Timestamp header.
        body: Raw request body bytes.

    Returns:
        True if the signature is valid, False otherwise.
    """
    # --- Check: Public key configured ---
    if not DISCORD_PUBLIC_KEY:
        if _should_allow_unverified():
            logger.warning(
                "DISCORD_PUBLIC_KEY not configured, allowing unverified request (dev mode)"
            )
            return True
        logger.warning("DISCORD_PUBLIC_KEY not configured, rejecting request")
        return False

    # --- Check: Required headers present ---
    if not signature or not timestamp:
        logger.warning(
            "Missing required Discord signature headers: signature=%s, timestamp=%s",
            "present" if signature else "missing",
            "present" if timestamp else "missing",
        )
        return False

    # --- Check: Replay protection via timestamp freshness ---
    try:
        request_time = int(timestamp)
        current_time = int(time.time())
        if abs(current_time - request_time) > _MAX_TIMESTAMP_AGE:
            logger.warning(
                "Discord request timestamp too old: request_time=%s, current_time=%s, delta=%ss > %ss",
                request_time,
                current_time,
                abs(current_time - request_time),
                _MAX_TIMESTAMP_AGE,
            )
            return False
    except (ValueError, OverflowError):
        logger.warning("Invalid Discord timestamp format: %r", timestamp)
        return False

    # --- Check: PyNaCl available ---
    if not _NACL_AVAILABLE:
        if _should_allow_unverified():
            logger.warning(
                "PyNaCl not installed, allowing unverified request (dev mode). "
                "Install with: pip install pynacl"
            )
            return True
        logger.warning("PyNaCl not installed, rejecting request")
        return False

    # --- Verify Ed25519 signature ---
    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
    except ImportError:
        # Should not happen since _NACL_AVAILABLE was True, but handle gracefully
        logger.error("PyNaCl import failed despite _NACL_AVAILABLE=True")
        return False

    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        message = timestamp.encode("utf-8") + body
        verify_key.verify(message, bytes.fromhex(signature))
        return True
    except BadSignatureError:
        logger.warning("Discord Ed25519 signature verification failed: bad signature")
        return False
    except (ValueError, TypeError) as e:
        # ValueError: invalid hex in signature or public key
        # TypeError: unexpected argument types
        logger.warning("Discord signature verification error (invalid format): %s", e)
        return False
    except (RuntimeError, OSError, AttributeError) as e:
        logger.exception("Unexpected Discord signature verification error: %s", e)
        return False


class DiscordHandler(BotHandlerMixin, SecureHandler):
    """Handler for Discord Interactions API endpoints.

    Uses BotHandlerMixin for shared auth/status patterns.

    RBAC Protected:
    - bots.read - required for status endpoint

    Note: Webhook endpoints are authenticated via Discord's Ed25519 signature,
    not RBAC, since they are called by Discord servers directly.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    # ------------------------------------------------------------------
    # RBAC helper
    # ------------------------------------------------------------------

    def _check_bot_permission(
        self, permission: str, *, user_id: str = "", context: dict | None = None
    ) -> None:
        """Check RBAC permission if available.

        Args:
            permission: The permission string to check (e.g. "debates:create").
            user_id: Platform-qualified user id (e.g. "discord:12345").
            context: Optional dict that may carry an ``auth_context`` key.

        Raises:
            PermissionError: When RBAC is available and the check fails.
        """
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                raise PermissionError("Service unavailable: access control module not loaded")
            return
        auth_ctx = (context or {}).get("auth_context")
        if auth_ctx is None and user_id:
            auth_ctx = AuthorizationContext(
                user_id=user_id,
                roles={"bot_user"},
            )
        if auth_ctx:
            check_permission(auth_ctx, permission)

    # BotHandlerMixin configuration
    bot_platform = "discord"

    ROUTES = [
        "/api/v1/bots/discord/interactions",
        "/api/v1/bots/discord/status",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    def _is_bot_enabled(self) -> bool:
        """Check if Discord bot is configured."""
        return bool(DISCORD_APPLICATION_ID)

    def _get_platform_config_status(self) -> dict[str, Any]:
        """Return Discord-specific config fields for status response."""
        return {
            "application_id_configured": bool(DISCORD_APPLICATION_ID),
            "public_key_configured": bool(DISCORD_PUBLIC_KEY),
        }

    @rate_limit(requests_per_minute=30)
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route Discord requests with RBAC for status endpoint."""
        if path == "/api/v1/bots/discord/status":
            # Use BotHandlerMixin's RBAC-protected status handler
            return await self.handle_status_request(handler)

        return None

    @handle_errors("discord creation")
    @rate_limit(requests_per_minute=30)
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if path == "/api/v1/bots/discord/interactions":
            return await self._handle_interactions(handler)

        return None

    async def _handle_interactions(self, handler: Any) -> HandlerResult:
        """Handle Discord interaction webhooks.

        This endpoint receives interactions from Discord when using the
        HTTP-based Interactions API instead of the gateway.
        """
        try:
            # Get signature headers
            signature = handler.headers.get("X-Signature-Ed25519", "")
            timestamp = handler.headers.get("X-Signature-Timestamp", "")

            # Read body
            body = self._read_request_body(handler)

            # Verify signature
            if not _verify_discord_signature(signature, timestamp, body):
                logger.warning("Discord signature verification failed")
                self._audit_webhook_auth_failure("signature")
                return error_response("Invalid signature", 401)

            # Parse interaction
            interaction, err = self._parse_json_body(body, "Discord interaction")
            if err:
                return err
            if interaction is None:
                return error_response("Discord interaction body must be a JSON object", 400)

            interaction_type = interaction.get("type")
            if isinstance(interaction_type, bool) or not isinstance(interaction_type, int):
                return error_response(
                    "Discord interaction body must include an integer 'type' field",
                    400,
                )

            # Handle PING (type 1) - required for URL verification
            if interaction_type == 1:
                logger.info("Discord PING received, responding with PONG")
                return json_response({"type": 1})

            # Handle APPLICATION_COMMAND (type 2)
            if interaction_type == 2:
                return await self._handle_application_command(interaction)

            # Handle MESSAGE_COMPONENT (type 3) - buttons, selects, etc.
            if interaction_type == 3:
                return self._handle_message_component(interaction)

            # Handle MODAL_SUBMIT (type 5)
            if interaction_type == 5:
                return self._handle_modal_submit(interaction)

            # Unknown interaction type
            logger.warning("Unknown Discord interaction type: %s", interaction_type)
            return json_response(
                {
                    "type": 4,  # CHANNEL_MESSAGE_WITH_SOURCE
                    "data": {
                        "content": "Unknown interaction type",
                        "flags": 64,  # Ephemeral
                    },
                }
            )

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in Discord interaction: %s", e)
            return error_response("Invalid JSON payload", 400)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Data error in Discord interaction: %s", e)
            return json_response(
                {
                    "type": 4,
                    "data": {
                        "content": "Sorry, an error occurred while processing your request.",
                        "flags": 64,
                    },
                }
            )
        except (RuntimeError, OSError, AttributeError) as e:
            logger.exception("Unexpected Discord interaction error: %s", e)
            return json_response(
                {
                    "type": 4,
                    "data": {
                        "content": "An unexpected error occurred",
                        "flags": 64,
                    },
                }
            )

    async def _handle_application_command(self, interaction: dict[str, Any]) -> HandlerResult:
        """Handle slash command interactions."""
        data = interaction.get("data", {})
        command_name = data.get("name", "")
        options = data.get("options", [])

        user = interaction.get("user") or interaction.get("member", {}).get("user", {})
        user_id = user.get("id", "unknown")
        username = user.get("username", "unknown")

        logger.info("Discord command from %s: %s", username, command_name)

        # Parse options into args
        args = {}
        for opt in options:
            args[opt["name"]] = opt.get("value", "")

        # Route commands
        if command_name == "aragora":
            subcommand = args.get("command", "help")
            subargs = args.get("args", "")
            return await self._execute_command(subcommand, subargs, user_id, interaction)

        if command_name == "debate":
            # RBAC: check debate creation permission
            try:
                self._check_bot_permission("debates:create", user_id=f"discord:{user_id}")
            except PermissionError as exc:
                logger.warning("RBAC denied debates:create for discord:%s: %s", user_id, exc)
                return json_response(
                    {
                        "type": 4,
                        "data": {
                            "content": "Permission denied: you cannot start debates.",
                            "flags": 64,
                        },
                    }
                )
            topic = args.get("topic", "")
            return await self._execute_command("debate", topic, user_id, interaction)

        if command_name == "gauntlet":
            # RBAC: check gauntlet permission
            try:
                self._check_bot_permission("gauntlet:run", user_id=f"discord:{user_id}")
            except PermissionError as exc:
                logger.warning("RBAC denied gauntlet:run for discord:%s: %s", user_id, exc)
                return json_response(
                    {
                        "type": 4,
                        "data": {
                            "content": "Permission denied: you cannot run gauntlet.",
                            "flags": 64,
                        },
                    }
                )
            statement = args.get("statement", "")
            return await self._execute_command("gauntlet", statement, user_id, interaction)

        if command_name == "status":
            return await self._execute_command("status", "", user_id, interaction)

        # Unknown command
        return json_response(
            {
                "type": 4,
                "data": {
                    "content": f"Unknown command: {command_name}",
                    "flags": 64,
                },
            }
        )

    async def _execute_command(
        self,
        command: str,
        args: str,
        user_id: str,
        interaction: dict[str, Any],
    ) -> HandlerResult:
        """Execute a command and return Discord response."""
        from datetime import datetime, timezone
        from aragora.bots.base import (
            BotChannel,
            BotMessage,
            BotUser,
            CommandContext,
            Platform,
        )
        from aragora.bots.commands import get_default_registry

        registry = get_default_registry()

        # Build context
        user_data = interaction.get("user") or interaction.get("member", {}).get("user", {})
        user = BotUser(
            id=user_data.get("id", "unknown"),
            username=user_data.get("username", "unknown"),
            display_name=user_data.get("global_name"),
            platform=Platform.DISCORD,
        )

        channel = BotChannel(
            id=interaction.get("channel_id", "unknown"),
            platform=Platform.DISCORD,
        )

        message = BotMessage(
            id=interaction.get("id", "unknown"),
            text=f"/{command} {args}".strip(),
            user=user,
            channel=channel,
            timestamp=datetime.now(timezone.utc),
            platform=Platform.DISCORD,
        )

        ctx = CommandContext(
            message=message,
            user=user,
            channel=channel,
            platform=Platform.DISCORD,
            args=[command] + (args.split() if args else []),
            raw_args=args,
            metadata={
                "api_base": os.environ.get("ARAGORA_API_BASE", "http://localhost:8080"),
                "interaction_id": interaction.get("id"),
                "guild_id": interaction.get("guild_id"),
            },
        )

        # Execute command
        result = await registry.execute(ctx)

        # Build response
        if result.success:
            response_data: dict[str, Any] = {
                "content": result.message or "Command executed",
            }

            if result.discord_embed:
                response_data["embeds"] = [result.discord_embed]

            if result.ephemeral:
                response_data["flags"] = 64

            return json_response(
                {
                    "type": 4,  # CHANNEL_MESSAGE_WITH_SOURCE
                    "data": response_data,
                }
            )
        else:
            return json_response(
                {
                    "type": 4,
                    "data": {
                        "content": f"Error: {result.error}",
                        "flags": 64,
                    },
                }
            )

    def _handle_message_component(self, interaction: dict[str, Any]) -> HandlerResult:
        """Handle button/select interactions."""
        data = interaction.get("data", {})
        custom_id = data.get("custom_id", "")

        user = interaction.get("user") or interaction.get("member", {}).get("user", {})
        user_id = user.get("id", "unknown")

        logger.info("Discord component interaction from %s: %s", user_id, custom_id)

        # Parse custom_id (e.g., "vote_debateid_agree")
        if custom_id.startswith("vote_"):
            # RBAC: check vote permission
            try:
                self._check_bot_permission("votes:record", user_id=f"discord:{user_id}")
            except PermissionError as exc:
                logger.warning("RBAC denied votes:record for discord:%s: %s", user_id, exc)
                return json_response(
                    {
                        "type": 4,
                        "data": {
                            "content": "Permission denied: you cannot vote.",
                            "flags": 64,
                        },
                    }
                )

            parts = custom_id.split("_")
            if len(parts) >= 3:
                debate_id = parts[1]
                vote = parts[2]

                # Record vote
                try:
                    from aragora.server.storage import get_debates_db

                    db = get_debates_db()
                    if db and hasattr(db, "record_vote"):
                        db.record_vote(
                            debate_id=debate_id,
                            voter_id=f"discord:{user_id}",
                            vote=vote,
                            source="discord",
                        )
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning("Failed to record vote due to data error: %s", e)
                except (RuntimeError, OSError, AttributeError) as e:
                    logger.exception("Unexpected error recording vote: %s", e)

                emoji = "thumbsup" if vote == "agree" else "thumbsdown"
                return json_response(
                    {
                        "type": 4,
                        "data": {
                            "content": f":{emoji}: Your vote has been recorded!",
                            "flags": 64,
                        },
                    }
                )

        # Unknown component
        return json_response(
            {
                "type": 4,
                "data": {
                    "content": "Interaction received",
                    "flags": 64,
                },
            }
        )

    def _handle_modal_submit(self, interaction: dict[str, Any]) -> HandlerResult:
        """Handle modal submission interactions."""
        data = interaction.get("data", {})
        custom_id = data.get("custom_id", "")

        logger.info("Discord modal submit: %s", custom_id)

        return json_response(
            {
                "type": 4,
                "data": {
                    "content": "Form submitted",
                    "flags": 64,
                },
            }
        )


__all__ = ["DiscordHandler"]
