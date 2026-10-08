"""
Microsoft Teams event handling mixin.

Provides webhook verification, event parsing, and Adaptive Card
formatting for the TeamsConnector.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from aragora.connectors.chat.models import (
    BotCommand,
    ChatChannel,
    ChatMessage,
    ChatUser,
    InteractionType,
    MessageButton,
    UserInteraction,
    WebhookEvent,
)

logger = logging.getLogger(__name__)


class _TeamsConnectorProtocol(Protocol):
    """Protocol for methods expected by TeamsEventsMixin from the main connector."""

    app_id: str

    @property
    def platform_name(self) -> str: ...


class TeamsEventsMixin:
    """Mixin providing event handling and formatting for TeamsConnector."""

    def format_blocks(
        self,
        title: str | None = None,
        body: str | None = None,
        fields: list[tuple[str, str]] | None = None,
        actions: list[MessageButton] | None = None,
        **kwargs: Any,
    ) -> list[dict]:
        """Format content as Adaptive Card elements."""
        elements: list[dict] = []

        if title:
            elements.append(
                {
                    "type": "TextBlock",
                    "text": title,
                    "size": "Large",
                    "weight": "Bolder",
                }
            )

        if body:
            elements.append(
                {
                    "type": "TextBlock",
                    "text": body,
                    "wrap": True,
                }
            )

        if fields:
            fact_set = {
                "type": "FactSet",
                "facts": [{"title": label, "value": value} for label, value in fields],
            }
            elements.append(fact_set)

        if actions:
            action_set = {
                "type": "ActionSet",
                "actions": [
                    self.format_button(btn.text, btn.action_id, btn.value, btn.style)
                    for btn in actions
                ],
            }
            elements.append(action_set)

        return elements

    def format_button(
        self,
        text: str,
        action_id: str,
        value: str | None = None,
        style: str = "default",
        url: str | None = None,
    ) -> dict:
        """Format an Adaptive Card action button."""
        if url:
            return {
                "type": "Action.OpenUrl",
                "title": text,
                "url": url,
            }

        action = {
            "type": "Action.Submit",
            "title": text,
            "data": {
                "action": action_id,
                "value": value or action_id,
            },
        }

        if style == "danger":
            action["style"] = "destructive"
        elif style == "primary":
            action["style"] = "positive"

        return action

    def verify_webhook(
        self: _TeamsConnectorProtocol,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """
        Verify Bot Framework JWT token.

        Uses PyJWT to validate the token against Microsoft's public keys.
        SECURITY: Fails closed in production if PyJWT is not available.
        Uses centralized webhook_security module for production-safe bypass handling.
        """
        from aragora.connectors.chat.webhook_security import should_allow_unverified

        auth_header = headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("Missing or invalid Authorization header")
            return False

        # Use JWT verification if available
        try:
            from aragora.connectors.chat.jwt_verify import verify_teams_webhook, HAS_JWT

            if HAS_JWT:
                return verify_teams_webhook(auth_header, self.app_id)
            else:
                # SECURITY: Use centralized bypass check (ignores flag in production)
                if should_allow_unverified("teams"):
                    logger.warning(
                        "Teams webhook verification skipped - PyJWT not available (dev mode). "
                        "Install PyJWT for secure webhook validation: pip install PyJWT"
                    )
                    return True
                logger.error("Teams webhook rejected - PyJWT not available")
                return False
        except ImportError:
            if should_allow_unverified("teams"):
                logger.warning("Teams JWT verification module not available (dev mode)")
                return True
            logger.error("Teams webhook rejected - JWT verification module not available")
            return False

    def parse_webhook_event(
        self: _TeamsConnectorProtocol,
        headers: dict[str, str],
        body: bytes,
    ) -> WebhookEvent:
        """Parse Teams Bot Framework activity into WebhookEvent."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return WebhookEvent(
                platform=self.platform_name,
                event_type="error",
                raw_payload={},
            )

        activity_type = payload.get("type", "")
        service_url = payload.get("serviceUrl", "")

        # Parse user
        from_data = payload.get("from", {})
        user = ChatUser(
            id=from_data.get("id", ""),
            platform=self.platform_name,
            display_name=from_data.get("name"),
            metadata={"aadObjectId": from_data.get("aadObjectId")},
        )

        # Parse channel
        conversation = payload.get("conversation", {})
        channel = ChatChannel(
            id=conversation.get("id", ""),
            platform=self.platform_name,
            name=conversation.get("name"),
            is_private=conversation.get("isGroup") is False,
            team_id=conversation.get("tenantId"),
            metadata={"conversationType": conversation.get("conversationType")},
        )

        event = WebhookEvent(
            platform=self.platform_name,
            event_type=activity_type,
            raw_payload=payload,
            metadata={"service_url": service_url},
        )

        if activity_type == "message":
            # Regular message
            text = payload.get("text", "")

            # Check for command (bot mention)
            entities = payload.get("entities", [])
            is_mention = any(e.get("type") == "mention" for e in entities)

            if is_mention and text.strip().startswith("<at>"):
                # Extract command after mention
                import re

                clean_text = re.sub(r"<at>.*?</at>\s*", "", text).strip()
                parts = clean_text.split(maxsplit=1)

                event.command = BotCommand(
                    name=parts[0] if parts else "",
                    text=clean_text,
                    args=parts[1].split() if len(parts) > 1 else [],
                    user=user,
                    channel=channel,
                    platform=self.platform_name,
                    metadata={"service_url": service_url},
                )
            else:
                event.message = ChatMessage(
                    id=payload.get("id", ""),
                    platform=self.platform_name,
                    channel=channel,
                    author=user,
                    content=text,
                    thread_id=payload.get("replyToId"),
                    metadata={"service_url": service_url},
                )

        elif activity_type == "invoke":
            # Adaptive Card action
            action_data = payload.get("value", {})

            event.interaction = UserInteraction(
                id=payload.get("id", ""),
                interaction_type=InteractionType.BUTTON_CLICK,
                action_id=action_data.get("action", ""),
                value=action_data.get("value"),
                user=user,
                channel=channel,
                message_id=payload.get("replyToId"),
                platform=self.platform_name,
                metadata={"service_url": service_url},
            )

        return event
