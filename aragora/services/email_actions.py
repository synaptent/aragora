"""
Unified Email Actions Service.

Provides a high-level interface for email actions across providers:
- Send, reply, forward emails
- Archive, trash, snooze messages
- Label/folder management
- Batch operations
- Action logging for compliance

Supports:
- Gmail (via GmailConnector)
- Outlook (via OutlookConnector)

All actions are logged for audit trail and compliance.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, cast

logger = logging.getLogger(__name__)


class EmailActionConnector(Protocol):
    """Protocol for email connectors that support action operations.

    This protocol defines the interface for email connectors used by
    EmailActionsService. Both GmailConnector and OutlookConnector
    implement this interface through their respective mixins.
    """

    async def send_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        html_body: str | None = None,
    ) -> dict[str, Any]: ...

    async def reply_to_message(
        self,
        original_message_id: str,
        body: str,
        cc: list[str] | None = None,
        html_body: str | None = None,
    ) -> dict[str, Any]: ...

    async def archive_message(self, message_id: str) -> dict[str, Any]: ...

    async def trash_message(self, message_id: str) -> dict[str, Any]: ...

    async def snooze_message(self, message_id: str, snooze_until: datetime) -> dict[str, Any]: ...

    async def mark_as_read(self, message_id: str) -> dict[str, Any]: ...

    async def star_message(self, message_id: str) -> dict[str, Any]: ...

    async def add_label(self, message_id: str, label_id: str) -> dict[str, Any]: ...

    async def move_to_folder(self, message_id: str, folder: str) -> dict[str, Any]: ...

    async def batch_archive(self, message_ids: list[str]) -> dict[str, Any]: ...


class EmailProvider(str, Enum):
    """Supported email providers."""

    GMAIL = "gmail"
    OUTLOOK = "outlook"


class ActionType(str, Enum):
    """Types of email actions."""

    SEND = "send"
    REPLY = "reply"
    FORWARD = "forward"
    ARCHIVE = "archive"
    TRASH = "trash"
    UNTRASH = "untrash"
    SNOOZE = "snooze"
    UNSNOOZE = "unsnooze"
    MARK_READ = "mark_read"
    MARK_UNREAD = "mark_unread"
    STAR = "star"
    IGNORE = "ignore"
    UNSTAR = "unstar"
    MARK_IMPORTANT = "mark_important"
    MARK_NOT_IMPORTANT = "mark_not_important"
    MOVE_TO_FOLDER = "move_to_folder"
    ADD_LABEL = "add_label"
    REMOVE_LABEL = "remove_label"
    BATCH_ARCHIVE = "batch_archive"
    BATCH_TRASH = "batch_trash"
    BATCH_MODIFY = "batch_modify"


class ActionStatus(str, Enum):
    """Status of an action."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ActionLog:
    """Log entry for an email action."""

    id: str
    user_id: str
    action_type: ActionType
    provider: EmailProvider
    message_ids: list[str]
    status: ActionStatus
    timestamp: datetime
    details: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "userId": self.user_id,
            "actionType": self.action_type.value,
            "provider": self.provider.value,
            "messageIds": self.message_ids,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "errorMessage": self.error_message,
            "durationMs": self.duration_ms,
        }


@dataclass
class SendEmailRequest:
    """Request to send an email."""

    to: list[str]
    subject: str
    body: str
    cc: list[str] | None = None
    bcc: list[str] | None = None
    reply_to: str | None = None
    html_body: str | None = None
    attachments: list[dict[str, Any]] | None = None


@dataclass
class SnoozeRequest:
    """Request to snooze an email."""

    message_id: str
    snooze_until: datetime
    restore_to_inbox: bool = True


@dataclass
class ActionResult:
    """Result of an email action."""

    success: bool
    action_type: ActionType
    message_ids: list[str]
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "actionType": self.action_type.value,
            "messageIds": self.message_ids,
            "details": self.details,
            "error": self.error,
        }


class EmailActionsService:
    """
    Unified service for email actions across providers.

    Features:
    - Provider-agnostic interface
    - Action logging for compliance
    - Snooze scheduling
    - Batch operations
    - Error handling with retries

    Example:
        ```python
        service = EmailActionsService()

        # Archive a message
        result = await service.archive(
            provider="gmail",
            user_id="user123",
            message_id="msg456",
        )

        # Snooze until tomorrow
        result = await service.snooze(
            provider="gmail",
            user_id="user123",
            message_id="msg456",
            snooze_until=datetime.now() + timedelta(days=1),
        )

        # Send an email
        result = await service.send(
            provider="gmail",
            user_id="user123",
            request=SendEmailRequest(
                to=["recipient@example.com"],
                subject="Hello",
                body="World",
            ),
        )
        ```
    """

    def __init__(self):
        """Initialize the email actions service."""
        self._action_logs: list[ActionLog] = []
        self._snoozed_messages: dict[str, SnoozeRequest] = {}
        self._connectors: dict[str, EmailActionConnector] = {}
        self._action_counter = 0
        self._lock = asyncio.Lock()

    def _generate_action_id(self) -> str:
        """Generate a unique action ID."""
        self._action_counter += 1
        return (
            f"action_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{self._action_counter}"
        )

    async def _get_connector(
        self,
        provider: str | EmailProvider,
        user_id: str,
    ) -> EmailActionConnector:
        """Get or create a connector for the provider.

        In production, this would look up the user's OAuth tokens
        and return a properly authenticated connector.
        """
        provider_str = provider.value if isinstance(provider, EmailProvider) else provider
        key = f"{provider_str}:{user_id}"

        if key not in self._connectors:
            if provider_str == "gmail":
                from aragora.connectors.enterprise.communication.gmail import GmailConnector
                from aragora.storage.gmail_token_store import get_gmail_token_store

                # GmailConnector uses mixins to implement abstract methods from EnterpriseConnector.
                # The type checker cannot verify this statically, so we cast to the Protocol.
                connector = cast(EmailActionConnector, GmailConnector())
                token_store = get_gmail_token_store()
                state = await token_store.get(user_id)
                if state is None or not state.refresh_token:
                    raise RuntimeError(f"Gmail connector not authenticated for user: {user_id}")
                setattr(connector, "_access_token", state.access_token or None)
                setattr(connector, "_refresh_token", state.refresh_token or None)
                setattr(connector, "_token_expiry", state.token_expiry)
                self._connectors[key] = connector
            elif provider_str == "outlook":
                from aragora.connectors.enterprise.communication.outlook import OutlookConnector

                # OutlookConnector implements EnterpriseConnector directly.
                # Cast to Protocol for consistent typing.
                outlook_connector = cast(EmailActionConnector, OutlookConnector())
                self._connectors[key] = outlook_connector
            else:
                raise ValueError(f"Unsupported provider: {provider}")

        return self._connectors[key]

    async def _log_action(
        self,
        user_id: str,
        action_type: ActionType,
        provider: str | EmailProvider,
        message_ids: list[str],
        status: ActionStatus,
        details: dict[str, Any] | None = None,
        error_message: str | None = None,
        duration_ms: float | None = None,
    ) -> ActionLog:
        """Log an action for audit trail."""
        provider_enum = EmailProvider(provider) if isinstance(provider, str) else provider

        log = ActionLog(
            id=self._generate_action_id(),
            user_id=user_id,
            action_type=action_type,
            provider=provider_enum,
            message_ids=message_ids,
            status=status,
            timestamp=datetime.now(timezone.utc),
            details=details or {},
            error_message=error_message,
            duration_ms=duration_ms,
        )

        async with self._lock:
            self._action_logs.append(log)
            # Keep only last 10000 logs in memory
            if len(self._action_logs) > 10000:
                self._action_logs = self._action_logs[-10000:]

        logger.info(
            "[EmailActions] %s by %s: %s message(s), status=%s",
            action_type.value,
            user_id,
            len(message_ids),
            status.value,
        )

        return log

    # =========================================================================
    # Send Actions
    # =========================================================================

    async def send(
        self,
        provider: str | EmailProvider,
        user_id: str,
        request: SendEmailRequest,
    ) -> ActionResult:
        """Send an email.

        Args:
            provider: Email provider (gmail, outlook)
            user_id: User ID for connector lookup
            request: Send email request

        Returns:
            ActionResult with sent message details
        """
        start_time = datetime.now(timezone.utc)

        try:
            connector = await self._get_connector(provider, user_id)

            result = await connector.send_message(
                to=request.to,
                subject=request.subject,
                body=request.body,
                cc=request.cc,
                bcc=request.bcc,
                reply_to=request.reply_to,
                html_body=request.html_body,
            )

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.SEND,
                provider=provider,
                message_ids=[result.get("message_id", "")],
                status=ActionStatus.SUCCESS,
                details={
                    "to": request.to,
                    "subject": request.subject,
                    "thread_id": result.get("thread_id"),
                },
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=True,
                action_type=ActionType.SEND,
                message_ids=[result.get("message_id", "")],
                details=result,
            )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.warning("Email send failed: %s", e)

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.SEND,
                provider=provider,
                message_ids=[],
                status=ActionStatus.FAILED,
                error_message=str(e),
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=False,
                action_type=ActionType.SEND,
                message_ids=[],
                error="Send failed",
            )

    async def reply(
        self,
        provider: str | EmailProvider,
        user_id: str,
        message_id: str,
        body: str,
        cc: list[str] | None = None,
        html_body: str | None = None,
    ) -> ActionResult:
        """Reply to an email.

        Args:
            provider: Email provider
            user_id: User ID
            message_id: Original message ID to reply to
            body: Reply body
            cc: Additional CC recipients
            html_body: HTML body

        Returns:
            ActionResult with reply details
        """
        start_time = datetime.now(timezone.utc)

        try:
            connector = await self._get_connector(provider, user_id)

            result = await connector.reply_to_message(
                original_message_id=message_id,
                body=body,
                cc=cc,
                html_body=html_body,
            )

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.REPLY,
                provider=provider,
                message_ids=[message_id, result.get("message_id", "")],
                status=ActionStatus.SUCCESS,
                details={
                    "in_reply_to": message_id,
                    "thread_id": result.get("thread_id"),
                },
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=True,
                action_type=ActionType.REPLY,
                message_ids=[result.get("message_id", "")],
                details=result,
            )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.warning("Email reply failed: %s", e)

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.REPLY,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.FAILED,
                error_message=str(e),
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=False,
                action_type=ActionType.REPLY,
                message_ids=[message_id],
                error="Reply failed",
            )

    # =========================================================================
    # Archive/Trash Actions
    # =========================================================================

    async def archive(
        self,
        provider: str | EmailProvider,
        user_id: str,
        message_id: str,
    ) -> ActionResult:
        """Archive a message.

        Args:
            provider: Email provider
            user_id: User ID
            message_id: Message to archive

        Returns:
            ActionResult
        """
        start_time = datetime.now(timezone.utc)

        try:
            connector = await self._get_connector(provider, user_id)
            result = await connector.archive_message(message_id)

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.ARCHIVE,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.SUCCESS,
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=True,
                action_type=ActionType.ARCHIVE,
                message_ids=[message_id],
                details=result,
            )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.warning("Email archive failed: %s", e)

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.ARCHIVE,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.FAILED,
                error_message=str(e),
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=False,
                action_type=ActionType.ARCHIVE,
                message_ids=[message_id],
                error="Archive failed",
            )

    async def trash(
        self,
        provider: str | EmailProvider,
        user_id: str,
        message_id: str,
    ) -> ActionResult:
        """Move a message to trash.

        Args:
            provider: Email provider
            user_id: User ID
            message_id: Message to trash

        Returns:
            ActionResult
        """
        start_time = datetime.now(timezone.utc)

        try:
            connector = await self._get_connector(provider, user_id)
            result = await connector.trash_message(message_id)

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.TRASH,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.SUCCESS,
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=True,
                action_type=ActionType.TRASH,
                message_ids=[message_id],
                details=result,
            )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.warning("Email trash failed: %s", e)

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.TRASH,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.FAILED,
                error_message=str(e),
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=False,
                action_type=ActionType.TRASH,
                message_ids=[message_id],
                error="Trash failed",
            )

    # =========================================================================
    # Snooze Actions
    # =========================================================================

    async def snooze(
        self,
        provider: str | EmailProvider,
        user_id: str,
        message_id: str,
        snooze_until: datetime,
    ) -> ActionResult:
        """Snooze a message until a specific time.

        Args:
            provider: Email provider
            user_id: User ID
            message_id: Message to snooze
            snooze_until: When to restore the message

        Returns:
            ActionResult
        """
        start_time = datetime.now(timezone.utc)

        try:
            connector = await self._get_connector(provider, user_id)
            result = await connector.snooze_message(message_id, snooze_until)

            # Store snooze for scheduler
            snooze_key = f"{provider}:{user_id}:{message_id}"
            self._snoozed_messages[snooze_key] = SnoozeRequest(
                message_id=message_id,
                snooze_until=snooze_until,
            )

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.SNOOZE,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.SUCCESS,
                details={"snooze_until": snooze_until.isoformat()},
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=True,
                action_type=ActionType.SNOOZE,
                message_ids=[message_id],
                details=result,
            )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.warning("Email snooze failed: %s", e)

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.SNOOZE,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.FAILED,
                error_message=str(e),
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=False,
                action_type=ActionType.SNOOZE,
                message_ids=[message_id],
                error="Snooze failed",
            )

    # =========================================================================
    # Label/Folder Actions
    # =========================================================================

    async def mark_read(
        self,
        provider: str | EmailProvider,
        user_id: str,
        message_id: str,
    ) -> ActionResult:
        """Mark a message as read."""
        start_time = datetime.now(timezone.utc)

        try:
            connector = await self._get_connector(provider, user_id)
            result = await connector.mark_as_read(message_id)

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.MARK_READ,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.SUCCESS,
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=True,
                action_type=ActionType.MARK_READ,
                message_ids=[message_id],
                details=result,
            )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.warning("Email mark_read failed: %s", e)

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.MARK_READ,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.FAILED,
                error_message=str(e),
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=False,
                action_type=ActionType.MARK_READ,
                message_ids=[message_id],
                error="Mark read failed",
            )

    async def star(
        self,
        provider: str | EmailProvider,
        user_id: str,
        message_id: str,
    ) -> ActionResult:
        """Star a message."""
        start_time = datetime.now(timezone.utc)

        try:
            connector = await self._get_connector(provider, user_id)
            result = await connector.star_message(message_id)

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.STAR,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.SUCCESS,
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=True,
                action_type=ActionType.STAR,
                message_ids=[message_id],
                details=result,
            )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.warning("Email star failed: %s", e)

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.STAR,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.FAILED,
                error_message=str(e),
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=False,
                action_type=ActionType.STAR,
                message_ids=[message_id],
                error="Star failed",
            )

    async def add_label(
        self,
        provider: str | EmailProvider,
        user_id: str,
        message_id: str,
        label_id: str,
    ) -> ActionResult:
        """Add a provider label to a message.

        This is currently implemented for Gmail connectors that expose
        ``add_label(message_id, label_id)`` on the connector instance.
        """
        start_time = datetime.now(timezone.utc)

        try:
            connector = await self._get_connector(provider, user_id)
            add_label = getattr(connector, "add_label", None)
            if not callable(add_label):
                raise ValueError(f"Provider does not support label actions: {provider}")
            result = await add_label(message_id, label_id)

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.ADD_LABEL,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.SUCCESS,
                details={"label_id": label_id},
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=True,
                action_type=ActionType.ADD_LABEL,
                message_ids=[message_id],
                details=result,
            )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.warning("Email add_label failed: %s", e)

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.ADD_LABEL,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.FAILED,
                details={"label_id": label_id},
                error_message=str(e),
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=False,
                action_type=ActionType.ADD_LABEL,
                message_ids=[message_id],
                error="Add label failed",
            )

    async def ignore(
        self,
        provider: str | EmailProvider,
        user_id: str,
        message_id: str,
    ) -> ActionResult:
        """Record a deliberate no-op action for inbox triage.

        This is used by the inbox trust wedge when the debated decision is to
        leave the message unchanged after approval.
        """
        start_time = datetime.now(timezone.utc)
        duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

        await self._log_action(
            user_id=user_id,
            action_type=ActionType.IGNORE,
            provider=provider,
            message_ids=[message_id],
            status=ActionStatus.SUCCESS,
            details={"no_op": True},
            duration_ms=duration_ms,
        )

        return ActionResult(
            success=True,
            action_type=ActionType.IGNORE,
            message_ids=[message_id],
            details={"ignored": True},
        )

    async def move_to_folder(
        self,
        provider: str | EmailProvider,
        user_id: str,
        message_id: str,
        folder: str,
    ) -> ActionResult:
        """Move a message to a folder."""
        start_time = datetime.now(timezone.utc)

        try:
            connector = await self._get_connector(provider, user_id)
            result = await connector.move_to_folder(message_id, folder)

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.MOVE_TO_FOLDER,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.SUCCESS,
                details={"folder": folder},
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=True,
                action_type=ActionType.MOVE_TO_FOLDER,
                message_ids=[message_id],
                details=result,
            )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.warning("Email move_to_folder failed: %s", e)

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.MOVE_TO_FOLDER,
                provider=provider,
                message_ids=[message_id],
                status=ActionStatus.FAILED,
                error_message=str(e),
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=False,
                action_type=ActionType.MOVE_TO_FOLDER,
                message_ids=[message_id],
                error="Move to folder failed",
            )

    # =========================================================================
    # Batch Actions
    # =========================================================================

    async def batch_archive(
        self,
        provider: str | EmailProvider,
        user_id: str,
        message_ids: list[str],
    ) -> ActionResult:
        """Archive multiple messages."""
        start_time = datetime.now(timezone.utc)

        try:
            connector = await self._get_connector(provider, user_id)
            result = await connector.batch_archive(message_ids)

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.BATCH_ARCHIVE,
                provider=provider,
                message_ids=message_ids,
                status=ActionStatus.SUCCESS,
                details={"count": len(message_ids)},
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=True,
                action_type=ActionType.BATCH_ARCHIVE,
                message_ids=message_ids,
                details=result,
            )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.warning("Email batch_archive failed: %s", e)

            await self._log_action(
                user_id=user_id,
                action_type=ActionType.BATCH_ARCHIVE,
                provider=provider,
                message_ids=message_ids,
                status=ActionStatus.FAILED,
                error_message=str(e),
                duration_ms=duration_ms,
            )

            return ActionResult(
                success=False,
                action_type=ActionType.BATCH_ARCHIVE,
                message_ids=message_ids,
                error="Batch archive failed",
            )

    # =========================================================================
    # Action Logs
    # =========================================================================

    async def get_action_logs(
        self,
        user_id: str | None = None,
        action_type: ActionType | None = None,
        provider: EmailProvider | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ActionLog]:
        """Get action logs with optional filtering.

        Args:
            user_id: Filter by user
            action_type: Filter by action type
            provider: Filter by provider
            since: Filter by timestamp
            limit: Max results

        Returns:
            List of ActionLog entries
        """
        async with self._lock:
            logs = self._action_logs.copy()

        # Apply filters
        if user_id:
            logs = [log for log in logs if log.user_id == user_id]
        if action_type:
            logs = [log for log in logs if log.action_type == action_type]
        if provider:
            logs = [log for log in logs if log.provider == provider]
        if since:
            logs = [log for log in logs if log.timestamp >= since]

        # Sort by timestamp descending and limit
        logs.sort(key=lambda x: x.timestamp, reverse=True)
        return logs[:limit]

    async def export_action_logs(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        """Export action logs for compliance.

        Args:
            user_id: User to export logs for
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of log entries as dictionaries
        """
        logs = await self.get_action_logs(
            user_id=user_id,
            since=start_date,
            limit=100000,  # High limit for export
        )

        # Filter by end date
        logs = [log for log in logs if log.timestamp <= end_date]

        return [log.to_dict() for log in logs]


# Global service instance
_email_actions_service: EmailActionsService | None = None


def get_email_actions_service() -> EmailActionsService:
    """Get or create the email actions service singleton."""
    global _email_actions_service
    if _email_actions_service is None:
        _email_actions_service = EmailActionsService()
    return _email_actions_service


__all__ = [
    "EmailActionsService",
    "get_email_actions_service",
    "ActionType",
    "ActionStatus",
    "ActionLog",
    "ActionResult",
    "SendEmailRequest",
    "SnoozeRequest",
    "EmailProvider",
]
