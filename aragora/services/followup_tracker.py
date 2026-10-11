"""
Follow-Up Tracker Service.

Tracks emails awaiting replies and helps users stay on top of conversations:
- Detect sent emails that haven't received replies
- Track expected response times based on sender history
- Remind users of pending follow-ups
- Auto-detect when replies are received

Usage:
    from aragora.services.followup_tracker import FollowUpTracker

    tracker = FollowUpTracker(gmail_connector=connector)

    # Mark email as awaiting reply
    await tracker.mark_awaiting_reply(email_id, expected_by=datetime.now() + timedelta(days=3))

    # Get all pending follow-ups
    pending = await tracker.get_pending_followups(user_id)

    # Auto-detect from sent folder
    awaiting = await tracker.auto_detect_sent_emails()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.connectors.enterprise.communication.gmail import GmailConnector

logger = logging.getLogger(__name__)


class FollowUpStatus(str, Enum):
    """Status of a follow-up item."""

    AWAITING = "awaiting"  # Waiting for reply
    OVERDUE = "overdue"  # Past expected response date
    RECEIVED = "received"  # Reply received
    RESOLVED = "resolved"  # Manually marked as resolved
    CANCELLED = "cancelled"  # No longer tracking


class FollowUpPriority(str, Enum):
    """Priority level for follow-ups."""

    URGENT = "urgent"  # Needs immediate attention
    HIGH = "high"  # Important, check soon
    NORMAL = "normal"  # Standard follow-up
    LOW = "low"  # Can wait


@dataclass
class FollowUpItem:
    """A tracked follow-up item."""

    id: str
    email_id: str
    thread_id: str
    subject: str
    recipient: str
    sent_at: datetime
    status: FollowUpStatus = FollowUpStatus.AWAITING
    expected_by: datetime | None = None
    priority: FollowUpPriority = FollowUpPriority.NORMAL
    notes: str = ""
    reminder_count: int = 0
    last_reminder: datetime | None = None
    reply_received_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def days_waiting(self) -> int:
        """Days since email was sent."""
        return (datetime.now() - self.sent_at).days

    @property
    def is_overdue(self) -> bool:
        """Check if follow-up is overdue."""
        if self.expected_by:
            return datetime.now() > self.expected_by
        return False

    @property
    def days_overdue(self) -> int:
        """Days past expected response date."""
        if self.expected_by and self.is_overdue:
            return (datetime.now() - self.expected_by).days
        return 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "email_id": self.email_id,
            "thread_id": self.thread_id,
            "subject": self.subject,
            "recipient": self.recipient,
            "sent_at": self.sent_at.isoformat(),
            "status": self.status.value,
            "expected_by": self.expected_by.isoformat() if self.expected_by else None,
            "priority": self.priority.value,
            "notes": self.notes,
            "days_waiting": self.days_waiting,
            "is_overdue": self.is_overdue,
            "days_overdue": self.days_overdue,
            "reminder_count": self.reminder_count,
        }


@dataclass
class FollowUpStats:
    """Statistics about follow-ups."""

    total_pending: int = 0
    overdue_count: int = 0
    urgent_count: int = 0
    avg_wait_days: float = 0.0
    resolved_this_week: int = 0
    top_recipients: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_pending": self.total_pending,
            "overdue_count": self.overdue_count,
            "urgent_count": self.urgent_count,
            "avg_wait_days": round(self.avg_wait_days, 1),
            "resolved_this_week": self.resolved_this_week,
            "top_recipients": self.top_recipients,
        }


class FollowUpTracker:
    """
    Service for tracking email follow-ups.

    Helps users track sent emails that need responses
    and manages reminders for pending follow-ups.
    """

    def __init__(
        self,
        gmail_connector: GmailConnector | None = None,
        default_followup_days: int = 3,
        auto_detect_threshold_days: int = 2,
    ):
        self.gmail = gmail_connector
        self.default_followup_days = default_followup_days
        self.auto_detect_threshold_days = auto_detect_threshold_days

        # In-memory storage (would be persisted in production)
        self._followups: dict[str, FollowUpItem] = {}
        self._by_thread: dict[str, set[str]] = {}  # thread_id -> followup_ids
        self._by_recipient: dict[str, set[str]] = {}  # recipient -> followup_ids

    async def mark_awaiting_reply(
        self,
        email_id: str,
        thread_id: str,
        subject: str,
        recipient: str,
        sent_at: datetime | None = None,
        expected_by: datetime | None = None,
        priority: FollowUpPriority = FollowUpPriority.NORMAL,
        notes: str = "",
    ) -> FollowUpItem:
        """
        Mark an email as awaiting a reply.

        Args:
            email_id: Sent email ID
            thread_id: Thread ID for tracking replies
            subject: Email subject
            recipient: Primary recipient email
            sent_at: When email was sent
            expected_by: Expected response date
            priority: Follow-up priority
            notes: Optional notes

        Returns:
            Created follow-up item
        """
        # Generate ID
        followup_id = f"fu_{email_id}_{datetime.now().timestamp()}"

        # Default dates
        if sent_at is None:
            sent_at = datetime.now()
        if expected_by is None:
            expected_by = sent_at + timedelta(days=self.default_followup_days)

        item = FollowUpItem(
            id=followup_id,
            email_id=email_id,
            thread_id=thread_id,
            subject=subject,
            recipient=recipient,
            sent_at=sent_at,
            expected_by=expected_by,
            priority=priority,
            notes=notes,
        )

        # Store
        self._followups[followup_id] = item

        # Index by thread
        if thread_id not in self._by_thread:
            self._by_thread[thread_id] = set()
        self._by_thread[thread_id].add(followup_id)

        # Index by recipient
        recipient_lower = recipient.lower()
        if recipient_lower not in self._by_recipient:
            self._by_recipient[recipient_lower] = set()
        self._by_recipient[recipient_lower].add(followup_id)

        logger.info("Created follow-up %s for email to %s", followup_id, recipient)
        return item

    async def get_pending_followups(
        self,
        user_id: str = "default",
        include_resolved: bool = False,
        sort_by: str = "expected_by",
        only_ids: set[str] | None = None,
    ) -> list[FollowUpItem]:
        """
        Get all pending follow-ups for a user.

        Args:
            user_id: User ID
            include_resolved: Include resolved items
            sort_by: Sort field (expected_by, sent_at, priority)
            only_ids: If given, only these follow-ups are returned and refreshed

        Returns:
            List of follow-up items
        """
        items = list(self._followups.values())
        if only_ids is not None:
            items = [i for i in items if i.id in only_ids]

        # Filter by status
        if not include_resolved:
            items = [
                i for i in items if i.status in [FollowUpStatus.AWAITING, FollowUpStatus.OVERDUE]
            ]

        # Update overdue status
        for item in items:
            if item.status == FollowUpStatus.AWAITING and item.is_overdue:
                item.status = FollowUpStatus.OVERDUE
                item.updated_at = datetime.now()

        # Sort
        if sort_by == "expected_by":
            items.sort(key=lambda x: x.expected_by or datetime.max)
        elif sort_by == "sent_at":
            items.sort(key=lambda x: x.sent_at, reverse=True)
        elif sort_by == "priority":
            priority_order = {
                FollowUpPriority.URGENT: 0,
                FollowUpPriority.HIGH: 1,
                FollowUpPriority.NORMAL: 2,
                FollowUpPriority.LOW: 3,
            }
            items.sort(key=lambda x: priority_order.get(x.priority, 99))

        return items

    async def check_for_replies(
        self, thread_ids: list[str] | None = None, only_ids: set[str] | None = None
    ) -> list[FollowUpItem]:
        """
        Check if replies have been received for tracked threads.

        Args:
            thread_ids: Specific threads to check, or all if None
            only_ids: If given, only these follow-ups are checked and updated

        Returns:
            List of items that received replies
        """
        if not self.gmail:
            logger.warning("No Gmail connector - cannot check for replies")
            return []

        received_replies = []
        threads_to_check = thread_ids or list(self._by_thread.keys())

        for thread_id in threads_to_check:
            if thread_id not in self._by_thread:
                continue

            try:
                # Get thread messages
                thread = await self.gmail.get_thread(thread_id)
                messages = thread.messages

                if len(messages) <= 1:
                    continue  # No replies yet

                # Check for new messages after our sent email
                followup_ids = self._by_thread[thread_id]
                for followup_id in followup_ids:
                    if only_ids is not None and followup_id not in only_ids:
                        continue
                    item = self._followups.get(followup_id)
                    if not item or item.status not in [
                        FollowUpStatus.AWAITING,
                        FollowUpStatus.OVERDUE,
                    ]:
                        continue

                    # Look for replies after sent_at
                    for msg in messages:
                        msg_date = msg.date if msg.date else datetime.now()
                        msg_from = (msg.from_address or "").lower()

                        # Check if this is a reply (from recipient, after our send)
                        if msg_date > item.sent_at and item.recipient.lower() in msg_from:
                            item.status = FollowUpStatus.RECEIVED
                            item.reply_received_at = msg_date
                            item.updated_at = datetime.now()
                            received_replies.append(item)
                            logger.info("Reply received for follow-up %s", followup_id)
                            break

            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.error("Error checking thread %s: %s", thread_id, e)

        return received_replies

    async def auto_detect_sent_emails(
        self,
        days_back: int = 7,
        exclude_recipients: set[str] | None = None,
    ) -> list[FollowUpItem]:
        """
        Auto-detect sent emails that might need follow-up tracking.

        Args:
            days_back: How many days to look back
            exclude_recipients: Recipients to exclude (e.g., noreply addresses)

        Returns:
            List of newly created follow-up items
        """
        if not self.gmail:
            logger.warning("No Gmail connector - cannot auto-detect")
            return []

        exclude = exclude_recipients or set()
        exclude.update(["noreply", "no-reply", "mailer-daemon", "postmaster"])

        created = []
        since = datetime.now() - timedelta(days=days_back)

        try:
            # Get sent messages
            message_ids, _ = await self.gmail.list_messages(
                query=f"after:{since.strftime('%Y/%m/%d')}",
                label_ids=["SENT"],
                max_results=100,
            )

            for msg_id in message_ids:
                try:
                    msg = await self.gmail.get_message(msg_id)
                    thread_id = msg.thread_id

                    # Skip if already tracking this thread
                    if thread_id in self._by_thread:
                        continue

                    # Get recipient
                    to_addresses = msg.to_addresses or []
                    if not to_addresses:
                        continue

                    recipient = to_addresses[0]

                    # Skip excluded recipients
                    if any(exc in recipient.lower() for exc in exclude):
                        continue

                    # Check if thread has replies
                    thread = await self.gmail.get_thread(thread_id)
                    messages = thread.messages

                    # Only track if no reply yet and sent > threshold days ago
                    sent_date = msg.date
                    if (
                        len(messages) == 1
                        and (datetime.now() - sent_date).days >= self.auto_detect_threshold_days
                    ):
                        item = await self.mark_awaiting_reply(
                            email_id=msg_id,
                            thread_id=thread_id,
                            subject=msg.subject or "(no subject)",
                            recipient=recipient,
                            sent_at=sent_date,
                        )
                        created.append(item)

                except (ValueError, KeyError, TypeError) as e:
                    logger.debug("Error processing message %s: %s", msg_id, e)

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.error("Error auto-detecting sent emails: %s", e)

        logger.info("Auto-detected %s emails needing follow-up", len(created))
        return created

    async def resolve_followup(
        self,
        followup_id: str,
        status: FollowUpStatus = FollowUpStatus.RESOLVED,
        notes: str = "",
    ) -> FollowUpItem | None:
        """
        Mark a follow-up as resolved.

        Args:
            followup_id: Follow-up ID
            status: Resolution status
            notes: Resolution notes

        Returns:
            Updated follow-up item
        """
        item = self._followups.get(followup_id)
        if not item:
            return None

        item.status = status
        item.notes = notes if notes else item.notes
        item.updated_at = datetime.now()

        return item

    async def update_priority(
        self,
        followup_id: str,
        priority: FollowUpPriority,
    ) -> FollowUpItem | None:
        """Update follow-up priority."""
        item = self._followups.get(followup_id)
        if not item:
            return None

        item.priority = priority
        item.updated_at = datetime.now()
        return item

    async def update_expected_date(
        self,
        followup_id: str,
        expected_by: datetime,
    ) -> FollowUpItem | None:
        """Update expected response date."""
        item = self._followups.get(followup_id)
        if not item:
            return None

        item.expected_by = expected_by
        item.updated_at = datetime.now()

        # Update status if no longer overdue
        if item.status == FollowUpStatus.OVERDUE and not item.is_overdue:
            item.status = FollowUpStatus.AWAITING

        return item

    async def record_reminder_sent(self, followup_id: str) -> FollowUpItem | None:
        """Record that a reminder was sent for this follow-up."""
        item = self._followups.get(followup_id)
        if not item:
            return None

        item.reminder_count += 1
        item.last_reminder = datetime.now()
        item.updated_at = datetime.now()
        return item

    def get_stats(self) -> FollowUpStats:
        """Get follow-up statistics."""
        items = list(self._followups.values())
        pending = [
            i for i in items if i.status in [FollowUpStatus.AWAITING, FollowUpStatus.OVERDUE]
        ]
        overdue = [i for i in pending if i.is_overdue]
        urgent = [i for i in pending if i.priority == FollowUpPriority.URGENT]

        # Average wait days
        total_days = sum(i.days_waiting for i in pending)
        avg_wait = total_days / len(pending) if pending else 0

        # Resolved this week
        week_ago = datetime.now() - timedelta(days=7)
        resolved_week = [
            i
            for i in items
            if i.status in [FollowUpStatus.RESOLVED, FollowUpStatus.RECEIVED]
            and i.updated_at >= week_ago
        ]

        # Top recipients
        recipient_counts: dict[str, int] = {}
        for item in pending:
            recipient = item.recipient.lower()
            recipient_counts[recipient] = recipient_counts.get(recipient, 0) + 1

        top_recipients = [
            {"recipient": r, "count": c}
            for r, c in sorted(recipient_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

        return FollowUpStats(
            total_pending=len(pending),
            overdue_count=len(overdue),
            urgent_count=len(urgent),
            avg_wait_days=avg_wait,
            resolved_this_week=len(resolved_week),
            top_recipients=top_recipients,
        )

    async def get_followups_by_recipient(self, recipient: str) -> list[FollowUpItem]:
        """Get all follow-ups for a specific recipient."""
        recipient_lower = recipient.lower()
        followup_ids = self._by_recipient.get(recipient_lower, set())
        return [self._followups[fid] for fid in followup_ids if fid in self._followups]

    async def get_overdue_followups(self) -> list[FollowUpItem]:
        """Get all overdue follow-ups."""
        return [
            item
            for item in self._followups.values()
            if item.status == FollowUpStatus.OVERDUE
            or (item.status == FollowUpStatus.AWAITING and item.is_overdue)
        ]

    async def get_followups_due_soon(self, days: int = 1) -> list[FollowUpItem]:
        """Get follow-ups due within the specified days."""
        threshold = datetime.now() + timedelta(days=days)
        return [
            item
            for item in self._followups.values()
            if item.status == FollowUpStatus.AWAITING
            and item.expected_by
            and item.expected_by <= threshold
            and not item.is_overdue
        ]
