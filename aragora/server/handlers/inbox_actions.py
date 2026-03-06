"""Inbox email action execution methods (InboxActionsMixin).

Extracted from inbox_command.py to reduce file size.
Contains action dispatch, individual action handlers, and filter logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.rbac.decorators import require_permission

if TYPE_CHECKING:
    from aragora.connectors.gmail import GmailConnector
    from aragora.server.handlers.inbox_command import EmailPrioritizer

logger = logging.getLogger(__name__)


class InboxActionsMixin:
    """Mixin providing inbox email action execution methods."""

    # Stub attributes expected from the composing class
    prioritizer: EmailPrioritizer | None
    gmail_connector: GmailConnector | None

    async def _execute_action(
        self,
        action: str,
        email_ids: list[str],
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Execute action on emails using Gmail connector."""
        results = []
        for email_id in email_ids:
            try:
                result = await self._perform_action(action, email_id, params)
                results.append(
                    {
                        "emailId": email_id,
                        "success": True,
                        "result": result,
                    }
                )

                # Record action for learning
                # Note: We pass email=None since we only have a dict representation,
                # not an EmailMessage object. The method handles None gracefully.
                if self.prioritizer:
                    await self.prioritizer.record_user_action(
                        email_id=email_id,
                        action=action,
                        email=None,
                    )

            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                RuntimeError,
                OSError,
                ConnectionError,
            ) as e:
                logger.warning("Action %s failed for %s: %s", action, email_id, e)
                results.append(
                    {
                        "emailId": email_id,
                        "success": False,
                        "error": "Action failed",
                    }
                )
        return results

    def _sanitize_action_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Sanitize action-specific parameters based on the action type.

        Enforces length bounds and format validation on parameters that will
        be passed to downstream services (Gmail API, etc.).
        """
        from .inbox_command import (
            ALLOWED_SNOOZE_DURATIONS,
            MAX_REPLY_BODY_LENGTH,
            _sanitize_string_param,
            _validate_email_address,
        )

        sanitized: dict[str, Any] = {}

        if action == "snooze":
            duration = params.get("duration", "1d")
            if isinstance(duration, str) and duration.strip() in ALLOWED_SNOOZE_DURATIONS:
                sanitized["duration"] = duration.strip()
            else:
                sanitized["duration"] = "1d"  # Safe default

        elif action == "reply":
            body = params.get("body", "")
            sanitized["body"] = _sanitize_string_param(body, MAX_REPLY_BODY_LENGTH)

        elif action == "forward":
            to = params.get("to", "")
            validated_to = _validate_email_address(to)
            sanitized["to"] = validated_to if validated_to else ""

        elif action in ("mark_vip", "block"):
            sender = params.get("sender", "")
            if sender:
                validated_sender = _validate_email_address(sender)
                if validated_sender:
                    sanitized["sender"] = validated_sender

        # For actions without specific params (archive, spam, mark_important, delete),
        # return empty dict to avoid passing through unvalidated data
        return sanitized

    async def _perform_action(
        self,
        action: str,
        email_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Perform a single action on an email."""
        action_handlers = {
            "archive": self._archive_email,
            "snooze": self._snooze_email,
            "reply": self._create_reply_draft,
            "forward": self._create_forward_draft,
            "spam": self._mark_spam,
            "mark_important": self._mark_important,
            "mark_vip": self._mark_sender_vip,
            "block": self._block_sender,
            "delete": self._delete_email,
        }

        handler = action_handlers.get(action)
        if not handler:
            raise ValueError(f"Unknown action: {action}")

        return await handler(email_id, params)

    async def _archive_email(self, email_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Archive an email via Gmail API."""
        if self.gmail_connector and hasattr(self.gmail_connector, "archive_message"):
            try:
                # hasattr check above confirms archive_message exists at runtime
                archive_fn: Callable[[str], Any] = self.gmail_connector.archive_message
                await archive_fn(email_id)
                logger.info("Archived email %s", email_id)
                return {"archived": True}
            except (OSError, ConnectionError, RuntimeError, AttributeError) as e:
                logger.warning("Gmail archive failed: %s", e)

        # Fallback to demo mode
        logger.info("[Demo] Archiving email %s", email_id)
        return {"archived": True, "demo": True}

    async def _snooze_email(self, email_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Snooze an email."""
        duration = params.get("duration", "1d")
        # Parse duration to snooze until time
        duration_map = {
            "1h": timedelta(hours=1),
            "3h": timedelta(hours=3),
            "1d": timedelta(days=1),
            "3d": timedelta(days=3),
            "1w": timedelta(weeks=1),
        }
        delta = duration_map.get(duration, timedelta(days=1))
        snooze_until = datetime.now(timezone.utc) + delta

        if self.gmail_connector and hasattr(self.gmail_connector, "snooze_message"):
            try:
                await self.gmail_connector.snooze_message(email_id, snooze_until)
                logger.info("Snoozed email %s until %s", email_id, snooze_until)
                return {"snoozed": True, "until": snooze_until.isoformat()}
            except (OSError, ConnectionError, RuntimeError, AttributeError) as e:
                logger.warning("Gmail snooze failed: %s", e)

        logger.info("[Demo] Snoozing email %s for %s", email_id, duration)
        return {"snoozed": True, "until": snooze_until.isoformat(), "demo": True}

    async def _create_reply_draft(self, email_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Create a reply draft."""
        body = params.get("body", "")

        if self.gmail_connector and hasattr(self.gmail_connector, "create_draft"):
            try:
                draft_id = await self.gmail_connector.create_draft(
                    in_reply_to=email_id,
                    body=body,
                )
                logger.info("Created reply draft for %s", email_id)
                return {"draftId": draft_id}
            except (OSError, ConnectionError, RuntimeError, AttributeError) as e:
                logger.warning("Gmail draft creation failed: %s", e)

        logger.info("[Demo] Creating reply draft for %s", email_id)
        return {"draftId": f"draft_{email_id}", "demo": True}

    async def _create_forward_draft(self, email_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Create a forward draft."""
        to = params.get("to", "")

        if self.gmail_connector and hasattr(self.gmail_connector, "create_forward_draft"):
            try:
                draft_id = await self.gmail_connector.create_forward_draft(
                    message_id=email_id,
                    to=to,
                )
                logger.info("Created forward draft for %s", email_id)
                return {"draftId": draft_id}
            except (OSError, ConnectionError, RuntimeError, AttributeError) as e:
                logger.warning("Gmail forward draft failed: %s", e)

        logger.info("[Demo] Creating forward draft for %s", email_id)
        return {"draftId": f"draft_fwd_{email_id}", "demo": True}

    async def _mark_spam(self, email_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Mark email as spam."""
        if self.gmail_connector and hasattr(self.gmail_connector, "mark_spam"):
            try:
                await self.gmail_connector.mark_spam(email_id)
                logger.info("Marked %s as spam", email_id)
                return {"spam": True}
            except (OSError, ConnectionError, RuntimeError, AttributeError) as e:
                logger.warning("Gmail mark spam failed: %s", e)

        logger.info("[Demo] Marking %s as spam", email_id)
        return {"spam": True, "demo": True}

    async def _mark_important(self, email_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Mark email as important."""
        if self.gmail_connector and hasattr(self.gmail_connector, "modify_labels"):
            try:
                await self.gmail_connector.modify_labels(
                    email_id,
                    add_labels=["IMPORTANT"],
                )
                logger.info("Marked %s as important", email_id)
                return {"important": True}
            except (OSError, ConnectionError, RuntimeError, AttributeError) as e:
                logger.warning("Gmail modify labels failed: %s", e)

        logger.info("[Demo] Marking %s as important", email_id)
        return {"important": True, "demo": True}

    async def _mark_sender_vip(self, email_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Mark sender as VIP."""
        from .inbox_command import _email_cache

        email_data = _email_cache.get(email_id)
        sender = email_data.get("from") if email_data else params.get("sender")

        if sender and self.prioritizer:
            # Add to VIP list in config
            self.prioritizer.config.vip_addresses.add(sender)
            logger.info("Marked sender %s as VIP", sender)
            return {"vip": True, "sender": sender}

        logger.info("[Demo] Marking sender of %s as VIP", email_id)
        return {"vip": True, "demo": True}

    async def _block_sender(self, email_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Block sender."""
        from .inbox_command import _email_cache

        email_data = _email_cache.get(email_id)
        sender = email_data.get("from") if email_data else params.get("sender")

        if sender and self.prioritizer:
            # Add to auto-archive list
            self.prioritizer.config.auto_archive_senders.add(sender)
            logger.info("Blocked sender %s", sender)
            return {"blocked": True, "sender": sender}

        logger.info("[Demo] Blocking sender of %s", email_id)
        return {"blocked": True, "demo": True}

    @require_permission("inbox:delete")
    async def _delete_email(self, email_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Delete email."""
        if self.gmail_connector and hasattr(self.gmail_connector, "trash_message"):
            try:
                await self.gmail_connector.trash_message(email_id)
                logger.info("Deleted email %s", email_id)
                return {"deleted": True}
            except (OSError, ConnectionError, RuntimeError, AttributeError) as e:
                logger.warning("Gmail delete failed: %s", e)

        logger.info("[Demo] Deleting email %s", email_id)
        return {"deleted": True, "demo": True}

    async def _get_emails_by_filter(self, filter_type: str) -> list[str]:
        """Get email IDs matching filter from cache.

        The filter_type is expected to have been validated against
        ALLOWED_BULK_FILTERS before calling this method.
        """
        from .inbox_command import ALLOWED_BULK_FILTERS, _email_cache

        if filter_type not in ALLOWED_BULK_FILTERS:
            logger.warning("Unexpected filter_type in _get_emails_by_filter: %s", filter_type)
            return []

        filter_map: dict[str, list[str] | Callable[[dict[str, Any]], bool] | None] = {
            "low": ["low", "defer"],
            "deferred": ["defer"],
            "spam": ["spam"],
            "read": lambda e: not e.get("unread", True),
            "all": None,
        }

        matching_ids = []
        filter_value = filter_map.get(filter_type)

        for email_id, email_data in _email_cache.items():
            if filter_value is None:
                matching_ids.append(email_id)
            elif callable(filter_value):
                if filter_value(email_data):
                    matching_ids.append(email_id)
            elif isinstance(filter_value, list):
                if email_data.get("priority") in filter_value:
                    matching_ids.append(email_id)

        return matching_ids
