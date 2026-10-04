"""
Microsoft Teams Bot main handler.

Contains the TeamsBot class for processing Bot Framework activities and
the TeamsHandler class for HTTP request routing.

Endpoints:
- POST /api/v1/bots/teams/messages - Handle incoming Bot Framework activities
- GET /api/v1/bots/teams/status - Bot status
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from collections.abc import Callable

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.server.handlers.bots.base import BotHandlerMixin
from aragora.server.handlers.secure import SecureHandler
from aragora.server.handlers.utils.auth_mixins import SecureEndpointMixin
from aragora.server.handlers.utils.rate_limit import rate_limit

# Import from teams_utils for shared state and utilities
from aragora.server.handlers.bots.teams_utils import (
    _active_debates,
    _check_botframework_available,
    _check_connector_available,
    _conversation_references,
    _store_conversation_reference,
    _verify_teams_token,
    get_conversation_reference,
)

logger = logging.getLogger(__name__)

# =============================================================================
# RBAC Permission constants for Teams bot
# =============================================================================
PERM_TEAMS_MESSAGES_READ = "teams:messages:read"
PERM_TEAMS_MESSAGES_SEND = "teams:messages:send"
PERM_TEAMS_DEBATES_CREATE = "teams:debates:create"
PERM_TEAMS_DEBATES_VOTE = "teams:debates:vote"
PERM_TEAMS_CARDS_RESPOND = "teams:cards:respond"
PERM_TEAMS_ADMIN = "teams:admin"

# RBAC imports - optional dependency
check_permission: Callable[..., Any] | None
extract_user_from_request: Callable[..., Any] | None
AuthorizationContext: type[Any] | None
UserAuthContext: type[Any] | None

try:
    from aragora.billing.auth.context import (
        UserAuthContext as _UserAuthCtx,
        extract_user_from_request as _extract_user,
    )
    from aragora.rbac.checker import check_permission as _check_perm  # noqa: F401
    from aragora.rbac.models import AuthorizationContext as _AuthCtx  # noqa: F401

    check_permission = _check_perm
    extract_user_from_request = _extract_user
    AuthorizationContext = _AuthCtx
    UserAuthContext = _UserAuthCtx
    RBAC_AVAILABLE = True
except (ImportError, AttributeError):
    RBAC_AVAILABLE = False
    check_permission = None
    extract_user_from_request = None
    AuthorizationContext = None
    UserAuthContext = None

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

# Environment variables
TEAMS_APP_ID = os.environ.get("TEAMS_APP_ID") or os.environ.get("MS_APP_ID")
TEAMS_APP_PASSWORD = os.environ.get("TEAMS_APP_PASSWORD")
TEAMS_TENANT_ID = os.environ.get("TEAMS_TENANT_ID")

if not TEAMS_APP_ID:
    logger.debug(
        "TEAMS_APP_ID (or MS_APP_ID) not configured - "
        "Bot Framework JWT validation will reject all requests"
    )
if not TEAMS_APP_PASSWORD:
    logger.debug("TEAMS_APP_PASSWORD not configured - Teams bot authentication disabled")

# Agent display names for UI
AGENT_DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude",
    "gpt4": "GPT-4",
    "gemini": "Gemini",
    "mistral": "Mistral",
    "deepseek": "DeepSeek",
    "grok": "Grok",
    "qwen": "Qwen",
    "kimi": "Kimi",
    "anthropic-api": "Claude",
    "openai-api": "GPT-4",
}

# Command pattern for parsing @mentions
MENTION_PATTERN = re.compile(r"<at>.*?</at>\s*", re.IGNORECASE)


class TeamsBot:
    """Microsoft Teams Bot for handling Bot Framework activities.

    Processes incoming activities from the Bot Framework Service and routes
    them to appropriate handlers. Supports:

    - Message activities: Regular messages and @mention commands
    - Invoke activities: Adaptive Card actions (votes, summaries, view details),
      compose extensions, and task module interactions
    - Conversation updates: Bot added/removed, member join/leave
    - Message reactions: Reaction added/removed tracking
    - Installation updates: App install/uninstall events

    The bot uses the TeamsConnector from ``aragora.connectors.chat.teams`` for
    sending replies and Adaptive Cards, and stores conversation references
    for proactive messaging support.
    """

    def __init__(self, app_id: str | None = None, app_password: str | None = None):
        """Initialize the Teams bot.

        Args:
            app_id: Bot application ID (defaults to TEAMS_APP_ID env var).
            app_password: Bot application password (defaults to TEAMS_APP_PASSWORD).
        """
        # Use package-level values so tests can patch aragora.server.handlers.bots.teams.*
        from aragora.server.handlers.bots import teams as teams_module

        self.app_id = app_id or teams_module.TEAMS_APP_ID or ""
        self.app_password = app_password or teams_module.TEAMS_APP_PASSWORD or ""
        self._connector: Any | None = None

        # Import event processor and card actions lazily
        self._event_processor: Any | None = None
        self._card_actions: Any | None = None

    # =========================================================================
    # Delegation methods to event processor and card actions
    # These maintain backward compatibility for tests that patch bot methods
    # =========================================================================

    async def _handle_message(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Handle a Teams message activity."""
        text = activity.get("text", "") or ""
        conversation = activity.get("conversation", {})
        conversation_id = conversation.get("id", "")
        conversation_type = conversation.get("conversationType", "")
        from_user = activity.get("from", {})
        user_id = from_user.get("id", "")
        service_url = activity.get("serviceUrl", "")

        # RBAC: allow early exit when permission denied
        perm_error = self._check_permission(activity, PERM_TEAMS_MESSAGES_READ)
        if perm_error:
            message = perm_error.get("message", "Permission denied")
            if "permission" not in str(message).lower():
                message = f"Permission denied: {message}"
            await self._send_reply(activity, message)
            return {}

        await self._send_typing(activity)

        entities = activity.get("entities", [])
        is_mention = any(e.get("type") == "mention" for e in entities)
        is_personal = conversation_type == "personal"

        if is_mention or is_personal:
            clean_text = MENTION_PATTERN.sub("", text).strip() if is_mention else text.strip()
            parts = clean_text.split(maxsplit=1)
            command = parts[0].lower() if parts else ""
            args = parts[1] if len(parts) > 1 else ""

            known_commands = {
                "debate",
                "ask",
                "status",
                "help",
                "leaderboard",
                "agents",
                "vote",
            }
            if is_personal and command and command not in known_commands:
                args = clean_text
                command = "debate"

            return await self._handle_command(
                command=command,
                args=args,
                conversation_id=conversation_id,
                user_id=user_id,
                service_url=service_url,
                activity=activity,
            )

        await self._send_reply(
            activity,
            "I received your message. Mention me with a command like "
            "'@Aragora debate <topic>' to start a debate.",
        )
        return {}

    async def _handle_invoke(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Route invoke activity to card/compose handlers."""
        invoke_name = activity.get("name", "")
        value = activity.get("value", {})
        from_user = activity.get("from", {})
        user_id = from_user.get("id", "")

        if invoke_name == "adaptiveCard/action" or not invoke_name:
            return await self._handle_card_action(activity, value=value, user_id=user_id)
        if invoke_name == "composeExtension/submitAction":
            return await self._handle_compose_extension_submit(
                activity, value=value, user_id=user_id
            )
        if invoke_name == "composeExtension/query":
            return await self._handle_compose_extension_query(
                activity, value=value, user_id=user_id
            )
        if invoke_name in ("composeExtension/fetchTask", "task/fetch"):
            return await self._handle_task_module_fetch(activity, value=value, user_id=user_id)
        if invoke_name == "task/submit":
            return await self._handle_task_module_submit(activity, value=value, user_id=user_id)

        return {"status": 200, "body": {"statusCode": 200, "type": "message", "value": "OK"}}

    async def _handle_conversation_update(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Delegate to event processor."""
        return await self._get_event_processor()._handle_conversation_update(activity)

    async def _handle_message_reaction(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Delegate to event processor."""
        return await self._get_event_processor()._handle_message_reaction(activity)

    async def _handle_installation_update(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Delegate to event processor."""
        return await self._get_event_processor()._handle_installation_update(activity)

    async def _handle_command(
        self,
        command: str,
        args: str,
        conversation_id: str,
        user_id: str,
        service_url: str,
        activity: dict[str, Any],
    ) -> dict[str, Any]:
        """Route a bot command to the appropriate handler."""
        thread_id = activity.get("replyToId")

        if command in ("debate", "ask"):
            return await self._cmd_debate(
                topic=args,
                conversation_id=conversation_id,
                user_id=user_id,
                service_url=service_url,
                thread_id=thread_id,
                activity=activity,
            )
        if command == "status":
            return await self._cmd_status(activity)
        if command == "help":
            return await self._cmd_help(activity)
        if command == "leaderboard":
            return await self._cmd_leaderboard(activity)
        if command == "agents":
            return await self._cmd_agents(activity)
        if command == "vote":
            return await self._cmd_vote(args, activity)
        return await self._cmd_unknown(command, activity)

    async def _cmd_debate(
        self,
        topic: str,
        conversation_id: str,
        user_id: str,
        service_url: str,
        thread_id: str | None,
        activity: dict[str, Any],
    ) -> dict[str, Any]:
        """Delegate to event processor (with RBAC pre-check)."""
        # RBAC: Check permission before delegating
        perm_error = self._check_permission(activity, PERM_TEAMS_DEBATES_CREATE)
        if perm_error:
            await self._send_reply(
                activity,
                perm_error.get("message", "Permission denied"),
            )
            return {}
        return await self._get_event_processor()._cmd_debate(
            topic,
            conversation_id,
            user_id,
            service_url,
            thread_id,
            activity,
        )

    async def _cmd_status(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Delegate to event processor."""
        return await self._get_event_processor()._cmd_status(activity)

    async def _cmd_help(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Delegate to event processor."""
        return await self._get_event_processor()._cmd_help(activity)

    async def _cmd_leaderboard(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Delegate to event processor."""
        return await self._get_event_processor()._cmd_leaderboard(activity)

    async def _cmd_agents(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Delegate to event processor."""
        return await self._get_event_processor()._cmd_agents(activity)

    async def _cmd_vote(self, args: str, activity: dict[str, Any]) -> dict[str, Any]:
        """Delegate to event processor."""
        return await self._get_event_processor()._cmd_vote(args, activity)

    async def _cmd_unknown(self, command: str, activity: dict[str, Any]) -> dict[str, Any]:
        """Delegate to event processor."""
        return await self._get_event_processor()._cmd_unknown(command, activity)

    async def _handle_card_action(
        self,
        activity: dict[str, Any],
        *,
        value: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Delegate to card actions handler."""
        if value is None:
            value = activity.get("value", {})
        if user_id is None:
            user_id = activity.get("from", {}).get("id", "")
        return await self._get_card_actions()._handle_card_action(value, user_id, activity)

    async def _handle_vote(
        self,
        debate_id: str,
        agent: str,
        user_id: str,
        activity: dict[str, Any],
    ) -> dict[str, Any]:
        """Delegate vote handling to card actions."""
        return await self._get_card_actions()._handle_vote(debate_id, agent, user_id, activity)

    async def _handle_summary(self, debate_id: str, activity: dict[str, Any]) -> dict[str, Any]:
        """Delegate summary handling to card actions."""
        return await self._get_card_actions()._handle_summary(debate_id, activity)

    async def _handle_task_module_fetch(
        self,
        activity: dict[str, Any],
        *,
        value: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Delegate to card actions handler."""
        if value is None:
            value = activity.get("value", {})
        if user_id is None:
            user_id = activity.get("from", {}).get("id", "")
        return await self._get_card_actions()._handle_task_module_fetch(value, user_id, activity)

    async def _handle_task_module_submit(
        self,
        activity: dict[str, Any],
        *,
        value: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Delegate to card actions handler."""
        if value is None:
            value = activity.get("value", {})
        if user_id is None:
            user_id = activity.get("from", {}).get("id", "")
        return await self._get_card_actions()._handle_task_module_submit(value, user_id, activity)

    async def _handle_compose_extension_submit(
        self,
        activity: dict[str, Any],
        *,
        value: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Delegate compose extension submit handling to card actions."""
        if value is None:
            value = activity.get("value", {})
        if user_id is None:
            user_id = activity.get("from", {}).get("id", "")
        return await self._get_card_actions()._handle_compose_extension_submit(
            value, user_id, activity
        )

    async def _handle_compose_extension_query(
        self,
        activity: dict[str, Any],
        *,
        value: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Delegate compose extension query handling to card actions."""
        if value is None:
            value = activity.get("value", {})
        if user_id is None:
            user_id = activity.get("from", {}).get("id", "")
        return await self._get_card_actions()._handle_compose_extension_query(
            value, user_id, activity
        )

    async def _send_typing(self, activity: dict[str, Any]) -> None:
        """Send typing indicator."""
        await self.send_typing(activity)

    async def _send_reply(self, activity: dict[str, Any], text: str) -> None:
        """Send a reply message."""
        await self.send_reply(activity, text)

    async def _get_connector(self) -> Any:
        """Lazily get the Teams connector for sending messages."""
        if self._connector is None:
            try:
                from aragora.connectors.chat.teams import TeamsConnector

                self._connector = TeamsConnector(
                    app_id=self.app_id,
                    app_password=self.app_password,
                )
            except ImportError:
                logger.warning("Teams connector not available")
                return None
        return self._connector

    def _get_event_processor(self) -> Any:
        """Get the event processor for handling activities."""
        if self._event_processor is None:
            from aragora.server.handlers.bots.teams.events import TeamsEventProcessor

            self._event_processor = TeamsEventProcessor(self)
        return self._event_processor

    def _get_card_actions(self) -> Any:
        """Get the card actions handler."""
        if self._card_actions is None:
            from aragora.server.handlers.bots.teams.cards import TeamsCardActions

            self._card_actions = TeamsCardActions(self)
        return self._card_actions

    # =========================================================================
    # RBAC Helper Methods
    # =========================================================================

    def _get_auth_context_from_activity(self, activity: dict[str, Any]) -> Any | None:
        """Build an authorization context from a Bot Framework activity."""
        if not RBAC_AVAILABLE or AuthorizationContext is None:
            return None

        try:
            from_user = activity.get("from", {})
            conversation = activity.get("conversation", {})

            user_id = from_user.get("id", "")
            user_aad_id = from_user.get("aadObjectId", "")
            tenant_id = conversation.get("tenantId", "")

            effective_user_id = user_aad_id or user_id
            if not effective_user_id:
                return None

            return AuthorizationContext(
                user_id=f"teams:{effective_user_id}",
                org_id=tenant_id if tenant_id else None,
                roles={"teams_user"},
            )
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.debug("Could not build auth context from activity: %s", e)
            return None

    def _check_permission(
        self,
        activity: dict[str, Any],
        permission_key: str,
        resource_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Check if the user in the activity has a specific permission."""
        if not RBAC_AVAILABLE or check_permission is None:
            if rbac_fail_closed():
                return {
                    "error": "Service unavailable: access control module not loaded",
                    "status": 503,
                }
            return None

        context = self._get_auth_context_from_activity(activity)
        if context is None:
            logger.debug("Could not build auth context for permission check")
            return None

        try:
            decision = check_permission(context, permission_key, resource_id)
            if not decision.allowed:
                logger.warning(
                    "Permission denied: %s for user %s, reason: %s",
                    permission_key,
                    context.user_id,
                    decision.reason,
                )
                return {
                    "error": "permission_denied",
                    "message": "Permission denied",
                    "permission": permission_key,
                }
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.warning("RBAC check failed: %s", e)
            return None

        return None

    def _validate_tenant(
        self,
        activity: dict[str, Any],
        expected_tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Validate that the activity comes from an expected tenant."""
        conversation = activity.get("conversation", {})
        activity_tenant_id = conversation.get("tenantId", "")

        required_tenant = expected_tenant_id or TEAMS_TENANT_ID

        if not required_tenant:
            return None

        if activity_tenant_id != required_tenant:
            logger.warning(
                "Tenant validation failed: activity from %s, expected %s",
                activity_tenant_id,
                required_tenant,
            )
            return {
                "error": "tenant_denied",
                "message": "Request from unauthorized tenant",
            }

        return None

    # =========================================================================
    # Activity entry point
    # =========================================================================

    async def process_activity(self, activity: dict[str, Any], auth_header: str) -> dict[str, Any]:
        """Process an incoming Bot Framework activity.

        This is the main entry point for all Teams bot interactions. It verifies
        the authentication token, stores the conversation reference for proactive
        messaging, and routes the activity to the appropriate handler.

        Args:
            activity: The Bot Framework activity payload.
            auth_header: Authorization header for token verification.

        Returns:
            Response dict (empty for most activities, invoke response for
            card actions).

        Raises:
            ValueError: If authentication token is invalid.
        """
        activity_type = activity.get("type", "")
        activity_id = activity.get("id", "")

        logger.debug("Processing Teams activity: type=%s, id=%s", activity_type, activity_id)

        # Verify token (look up via package module so tests can patch
        # aragora.server.handlers.bots.teams._verify_teams_token)
        from aragora.server.handlers.bots import teams as _teams_pkg

        _pkg_verify = getattr(_teams_pkg, "_verify_teams_token", _verify_teams_token)
        if self.app_id and not await _pkg_verify(auth_header, self.app_id):
            logger.warning("Teams activity rejected - invalid token")
            raise ValueError("Invalid authentication token")

        # Validate tenant for multi-tenant security
        tenant_error = self._validate_tenant(activity)
        if tenant_error:
            logger.warning("Teams activity rejected - tenant validation failed")
            return {
                "status": 403,
                "body": tenant_error,
            }

        # Store conversation reference for proactive messaging
        _store_conversation_reference(activity)

        # Route by activity type - methods can be patched on the bot for testing
        activity_type = activity.get("type", "")

        if activity_type == "message":
            return await self._handle_message(activity)
        elif activity_type == "invoke":
            return await self._handle_invoke(activity)
        elif activity_type == "conversationUpdate":
            return await self._handle_conversation_update(activity)
        elif activity_type == "messageReaction":
            return await self._handle_message_reaction(activity)
        elif activity_type == "installationUpdate":
            return await self._handle_installation_update(activity)
        else:
            logger.debug("Unhandled activity type: %s", activity_type)
            return {}

    # =========================================================================
    # Message sending utilities (used by event processor and card actions)
    # =========================================================================

    async def send_typing(self, activity: dict[str, Any]) -> None:
        """Send typing indicator to show the bot is processing."""
        connector = await self._get_connector()
        if not connector:
            return

        try:
            conversation = activity.get("conversation", {})
            service_url = activity.get("serviceUrl", "")

            await connector.send_typing_indicator(
                channel_id=conversation.get("id", ""),
                service_url=service_url,
            )
        except (RuntimeError, OSError, ValueError, AttributeError) as e:
            logger.debug("Typing indicator failed (non-critical): %s", e)

    async def send_reply(self, activity: dict[str, Any], text: str) -> None:
        """Send a text reply to an activity."""
        connector = await self._get_connector()
        if not connector:
            logger.warning("Cannot send reply - connector not available")
            return

        try:
            conversation = activity.get("conversation", {})
            service_url = activity.get("serviceUrl", "")

            await connector.send_message(
                channel_id=conversation.get("id", ""),
                text=text,
                service_url=service_url,
                thread_id=activity.get("replyToId"),
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.error("Failed to send Teams reply: %s", e)

    async def send_card(
        self, activity: dict[str, Any], card: dict[str, Any], fallback_text: str
    ) -> None:
        """Send an Adaptive Card reply to an activity."""
        connector = await self._get_connector()
        if not connector:
            logger.warning("Cannot send card - connector not available")
            return

        try:
            conversation = activity.get("conversation", {})
            service_url = activity.get("serviceUrl", "")
            conversation_id = conversation.get("id", "")

            token = await connector._get_access_token()

            card_activity: dict[str, Any] = {
                "type": "message",
                "text": fallback_text,
                "attachments": [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": card,
                    }
                ],
            }

            thread_id = activity.get("replyToId")
            if thread_id:
                card_activity["replyToId"] = thread_id

            await connector._http_request(
                method="POST",
                url=f"{service_url}/v3/conversations/{conversation_id}/activities",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=card_activity,
                operation="send_card",
            )

        except (RuntimeError, OSError, ValueError, AttributeError, KeyError) as e:
            logger.error("Failed to send Teams card: %s", e)

    async def send_proactive_message(
        self,
        conversation_id: str,
        text: str | None = None,
        card: dict[str, Any] | None = None,
        fallback_text: str = "",
    ) -> bool:
        """Send a proactive message to a conversation."""
        ref = get_conversation_reference(conversation_id)
        if not ref:
            logger.warning("No conversation reference for %s", conversation_id)
            return False

        connector = await self._get_connector()
        if not connector:
            logger.warning("Cannot send proactive message - connector not available")
            return False

        try:
            service_url = ref.get("service_url", "")

            if card:
                token = await connector._get_access_token()
                proactive_activity: dict[str, Any] = {
                    "type": "message",
                    "text": fallback_text or text or "",
                    "attachments": [
                        {
                            "contentType": "application/vnd.microsoft.card.adaptive",
                            "content": card,
                        }
                    ],
                }

                await connector._http_request(
                    method="POST",
                    url=f"{service_url}/v3/conversations/{conversation_id}/activities",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=proactive_activity,
                    operation="proactive_card",
                )
                return True

            elif text:
                await connector.send_message(
                    channel_id=conversation_id,
                    text=text,
                    service_url=service_url,
                )
                return True

            else:
                logger.warning("No text or card provided for proactive message")
                return False

        except (RuntimeError, OSError, ValueError, AttributeError, KeyError) as e:
            logger.error("Failed to send proactive message: %s", e)
            return False


class TeamsHandler(SecureEndpointMixin, BotHandlerMixin, SecureHandler):  # type: ignore[misc]
    """Handler for Microsoft Teams Bot endpoints.

    Uses BotHandlerMixin for shared auth/status patterns.
    Uses SecureEndpointMixin for RBAC permission checks on management endpoints.

    RBAC Protected:
    - bots.read - required for status endpoint
    - bots:manage - required for management endpoints (configure, install, uninstall)
    """

    bot_platform = "teams"

    ROUTES = [
        "/api/v1/bots/teams/messages",
        "/api/v1/bots/teams/status",
        "/api/v1/teams",
        "/api/v1/teams/debates/send",
    ]

    DYNAMIC_ROUTES = [
        "/api/v1/teams/{team_id}",
        "/api/v1/teams/{team_id}/members",
        "/api/v1/teams/{team_id}/members/{user_id}",
        "/api/v1/teams/{team_id}/stats",
    ]

    def __init__(self, ctx: dict | None = None):
        super().__init__(ctx or {})
        self._bot: TeamsBot | None = None
        self._bot_initialized = False

    def _is_bot_enabled(self) -> bool:
        """Check if Teams bot is configured."""
        # Use package-level values so tests can patch aragora.server.handlers.bots.teams.*
        from aragora.server.handlers.bots import teams as teams_module

        return bool(teams_module.TEAMS_APP_ID and teams_module.TEAMS_APP_PASSWORD)

    def _get_platform_config_status(self) -> dict[str, Any]:
        """Return Teams-specific config fields for status response."""
        from aragora.server.handlers.bots import teams as teams_module

        sdk_available, sdk_error = _check_botframework_available()
        connector_available, connector_error = _check_connector_available()

        return {
            "app_id_configured": bool(teams_module.TEAMS_APP_ID),
            "password_configured": bool(teams_module.TEAMS_APP_PASSWORD),
            "tenant_id_configured": bool(teams_module.TEAMS_TENANT_ID),
            "sdk_available": sdk_available,
            "sdk_error": sdk_error,
            "connector_available": connector_available,
            "connector_error": connector_error,
            "active_debates": len(_active_debates),
            "conversation_references": len(_conversation_references),
            "features": {
                "adaptive_cards": True,
                "voting": True,
                "threading": True,
                "proactive_messaging": True,
                "compose_extensions": True,
                "task_modules": True,
                "link_unfurling": True,
            },
        }

    async def _ensure_bot(self) -> TeamsBot | None:
        """Lazily initialize the Teams bot."""
        if self._bot_initialized:
            return self._bot

        self._bot_initialized = True

        from aragora.server.handlers.bots import teams as teams_module

        if not teams_module.TEAMS_APP_ID or not teams_module.TEAMS_APP_PASSWORD:
            logger.warning("Teams credentials not configured")
            return None

        self._bot = TeamsBot(
            app_id=teams_module.TEAMS_APP_ID,
            app_password=teams_module.TEAMS_APP_PASSWORD,
        )
        logger.info("Teams bot initialized")
        return self._bot

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    @rate_limit(requests_per_minute=30, limiter_name="teams_status")
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route Teams requests with RBAC for status endpoint."""
        if path == "/api/v1/bots/teams/status":
            return await self.handle_status_request(handler)
        if path == "/api/v1/teams" and getattr(handler, "command", "GET") == "GET":
            return await self.handle_with_auth(
                handler, self.bots_read_permission, self._list_teams_not_implemented
            )

        return None

    async def _list_teams_not_implemented(self, auth_context: Any = None) -> HandlerResult:
        return error_response("Listing teams is not implemented", 501, code="not_implemented")

    @handle_errors("teams creation")
    @rate_limit(requests_per_minute=60, limiter_name="teams_messages")
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if path == "/api/v1/bots/teams/messages":
            return await self._handle_messages(handler)

        return None

    async def _handle_messages(self, handler: Any) -> HandlerResult:
        """Handle incoming Bot Framework messages."""
        bot = await self._ensure_bot()
        if not bot:
            return json_response(
                {
                    "error": "Teams bot not configured",
                    "details": "Set TEAMS_APP_ID and TEAMS_APP_PASSWORD environment variables",
                },
                status=503,
            )

        try:
            body = self._read_request_body(handler)
            activity, err = self._parse_json_body(body, "Teams message")
            if err:
                return err

            if not activity:
                return error_response("Empty activity", 400)
            activity_type = activity.get("type")
            if not isinstance(activity_type, str) or not activity_type.strip():
                return error_response("Teams activity must include a non-empty 'type' field", 400)

            auth_header = handler.headers.get("Authorization", "")

            try:
                response = await bot.process_activity(activity, auth_header)

                if activity.get("type") == "invoke" and response:
                    status_code = response.get("status", 200)
                    return json_response(response.get("body", {}), status=status_code)

                return json_response({}, status=200)

            except ValueError as auth_error:
                logger.warning("Teams auth failed: %s", auth_error)
                self._audit_webhook_auth_failure("auth_token", str(auth_error))
                return error_response("Unauthorized", 401)
            except (RuntimeError, OSError, AttributeError) as process_error:
                logger.exception("Teams activity processing error: %s", process_error)
                return error_response("Internal processing error", 500)

        except (json.JSONDecodeError, ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            return self._handle_webhook_exception(e, "Teams message", return_200_on_error=False)


__all__ = [
    "TeamsHandler",
    "TeamsBot",
    "TEAMS_APP_ID",
    "TEAMS_APP_PASSWORD",
    "TEAMS_TENANT_ID",
    "AGENT_DISPLAY_NAMES",
    "MENTION_PATTERN",
    "PERM_TEAMS_MESSAGES_READ",
    "PERM_TEAMS_MESSAGES_SEND",
    "PERM_TEAMS_DEBATES_CREATE",
    "PERM_TEAMS_DEBATES_VOTE",
    "PERM_TEAMS_CARDS_RESPOND",
    "PERM_TEAMS_ADMIN",
]
