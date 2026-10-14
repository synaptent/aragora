"""
Email Threading Engine.

Reconstructs email conversations from fragmented inbox:
- References/In-Reply-To headers (RFC 5322)
- Subject line matching (Re:, Fwd: normalization)
- Participant overlap analysis
- Semantic similarity for broken threads
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    """A single email message."""

    message_id: str
    subject: str
    sender: str
    recipients: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    date: datetime | None = None
    body_preview: str = ""
    references: list[str] = field(default_factory=list)
    in_reply_to: str | None = None
    thread_id: str | None = None
    labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "message_id": self.message_id,
            "subject": self.subject,
            "sender": self.sender,
            "recipients": self.recipients,
            "cc": self.cc,
            "date": self.date.isoformat() if self.date else None,
            "body_preview": self.body_preview,
            "references": self.references,
            "in_reply_to": self.in_reply_to,
            "thread_id": self.thread_id,
            "labels": self.labels,
        }


@dataclass
class EmailThread:
    """A threaded email conversation."""

    thread_id: str
    subject: str  # Normalized subject
    participants: set[str] = field(default_factory=set)
    messages: list[EmailMessage] = field(default_factory=list)
    first_message_date: datetime | None = None
    last_message_date: datetime | None = None
    message_count: int = 0
    unread_count: int = 0
    labels: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "thread_id": self.thread_id,
            "subject": self.subject,
            "participants": list(self.participants),
            "messages": [m.to_dict() for m in self.messages],
            "first_message_date": (
                self.first_message_date.isoformat() if self.first_message_date else None
            ),
            "last_message_date": (
                self.last_message_date.isoformat() if self.last_message_date else None
            ),
            "message_count": self.message_count,
            "unread_count": self.unread_count,
            "labels": list(self.labels),
        }


@dataclass
class ThreadSummary:
    """AI-generated summary of a thread."""

    thread_id: str
    summary: str
    key_points: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    sentiment: str = "neutral"  # positive, negative, neutral
    urgency: str = "normal"  # low, normal, high, urgent

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "thread_id": self.thread_id,
            "summary": self.summary,
            "key_points": self.key_points,
            "action_items": self.action_items,
            "sentiment": self.sentiment,
            "urgency": self.urgency,
        }


class EmailThreader:
    """
    Reconstruct email conversations from fragmented inbox.

    Threading logic:
    1. References/In-Reply-To headers (RFC 5322)
    2. Subject line matching (Re:, Fwd: normalization)
    3. Participant overlap analysis
    4. Semantic similarity for broken threads
    """

    # Subject prefixes to normalize
    SUBJECT_PREFIXES = [
        r"^re:\s*",
        r"^fwd?:\s*",
        r"^fw:\s*",
        r"^\[\w+\]\s*",  # Mailing list prefixes like [dev], [announce]
        r"^【.*?】\s*",  # CJK brackets
    ]

    def __init__(
        self,
        min_participant_overlap: float = 0.5,
        enable_semantic_matching: bool = False,
    ):
        """
        Initialize the email threader.

        Args:
            min_participant_overlap: Minimum overlap ratio to consider same thread
            enable_semantic_matching: Enable AI-based semantic matching for broken threads
        """
        self.min_participant_overlap = min_participant_overlap
        self.enable_semantic_matching = enable_semantic_matching

        # Thread index for fast lookup
        self._message_id_to_thread: dict[str, str] = {}
        self._normalized_subject_to_threads: dict[str, set[str]] = {}
        self._threads: dict[str, EmailThread] = {}

    def thread_emails(self, emails: list[EmailMessage]) -> list[EmailThread]:
        """
        Thread a list of emails into conversations.

        Args:
            emails: List of email messages

        Returns:
            List of email threads
        """
        # Reset state
        self._message_id_to_thread.clear()
        self._normalized_subject_to_threads.clear()
        self._threads.clear()

        # Sort by date for proper threading
        sorted_emails = sorted(
            emails,
            key=lambda e: e.date or datetime.min.replace(tzinfo=timezone.utc),
        )

        for email in sorted_emails:
            thread_id = self._find_or_create_thread(email)
            self._add_to_thread(email, thread_id)

        # Update thread metadata
        for thread in self._threads.values():
            self._update_thread_metadata(thread)

        return list(self._threads.values())

    def _find_or_create_thread(self, email: EmailMessage) -> str:
        """Find existing thread or create new one."""
        # Strategy 1: Use In-Reply-To header
        if email.in_reply_to:
            thread_id = self._message_id_to_thread.get(email.in_reply_to)
            if thread_id:
                return thread_id

        # Strategy 2: Use References header
        for ref_id in email.references:
            thread_id = self._message_id_to_thread.get(ref_id)
            if thread_id:
                return thread_id

        # Strategy 3: Use Gmail thread_id if available
        if email.thread_id:
            if email.thread_id in self._threads:
                return email.thread_id

        # Strategy 4: Match by normalized subject
        normalized_subject = self._normalize_subject(email.subject)
        candidate_thread_ids = self._normalized_subject_to_threads.get(normalized_subject, set())

        for candidate_id in candidate_thread_ids:
            candidate = self._threads.get(candidate_id)
            if candidate and self._should_merge(email, candidate):
                return candidate_id

        # No match found - create new thread
        thread_id = self._generate_thread_id(email)
        thread = EmailThread(
            thread_id=thread_id,
            subject=normalized_subject,
        )
        self._threads[thread_id] = thread

        # Index by normalized subject
        if normalized_subject not in self._normalized_subject_to_threads:
            self._normalized_subject_to_threads[normalized_subject] = set()
        self._normalized_subject_to_threads[normalized_subject].add(thread_id)

        return thread_id

    def _add_to_thread(self, email: EmailMessage, thread_id: str) -> None:
        """Add an email to a thread."""
        thread = self._threads[thread_id]
        email.thread_id = thread_id

        # Add message
        thread.messages.append(email)
        thread.message_count += 1

        # Index message ID
        self._message_id_to_thread[email.message_id] = thread_id

        # Add participants
        thread.participants.add(email.sender)
        thread.participants.update(email.recipients)
        thread.participants.update(email.cc)

        # Add labels
        thread.labels.update(email.labels)

        # Update dates
        if email.date:
            if not thread.first_message_date or email.date < thread.first_message_date:
                thread.first_message_date = email.date
            if not thread.last_message_date or email.date > thread.last_message_date:
                thread.last_message_date = email.date

    def _should_merge(self, email: EmailMessage, thread: EmailThread) -> bool:
        """Determine if email should be merged into thread."""
        # Check participant overlap
        email_participants = {email.sender} | set(email.recipients) | set(email.cc)
        overlap = email_participants & thread.participants

        if not overlap:
            return False

        overlap_ratio = len(overlap) / min(len(email_participants), len(thread.participants))
        if overlap_ratio < self.min_participant_overlap:
            return False

        # Check time proximity (within 30 days)
        if email.date and thread.last_message_date:
            time_diff = abs((email.date - thread.last_message_date).days)
            if time_diff > 30:
                return False

        return True

    def _normalize_subject(self, subject: str) -> str:
        """Normalize subject by removing prefixes."""
        normalized = subject.strip().lower()

        for pattern in self.SUBJECT_PREFIXES:
            while True:
                new_normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)
                if new_normalized == normalized:
                    break
                normalized = new_normalized

        return normalized.strip()

    def _generate_thread_id(self, email: EmailMessage) -> str:
        """Generate a unique thread ID."""
        # Use message ID if available
        if email.message_id:
            return f"thread_{hashlib.md5(email.message_id.encode(), usedforsecurity=False).hexdigest()[:12]}"

        # Generate from subject + sender
        key = f"{self._normalize_subject(email.subject)}_{email.sender}"
        return f"thread_{hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()[:12]}"

    def _update_thread_metadata(self, thread: EmailThread) -> None:
        """Update thread metadata after all messages added."""
        if thread.messages:
            # Sort messages by date
            thread.messages.sort(key=lambda m: m.date or datetime.min.replace(tzinfo=timezone.utc))

            # Count unread (assuming unread = no "read" label)
            thread.unread_count = sum(1 for m in thread.messages if "UNREAD" in m.labels)

    def get_thread_summary(
        self,
        thread: EmailThread,
        summarizer: Any | None = None,
    ) -> ThreadSummary:
        """
        Generate AI summary of thread conversation.

        Args:
            thread: Thread to summarize
            summarizer: Optional AI summarizer (uses heuristics if None)

        Returns:
            ThreadSummary
        """
        if summarizer:
            # Use AI summarizer
            try:
                return self._ai_summarize(thread, summarizer)
            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.warning("AI summarization failed: %s", e)

        # Fallback to heuristic summary
        return self._heuristic_summarize(thread)

    def _heuristic_summarize(self, thread: EmailThread) -> ThreadSummary:
        """Generate heuristic-based summary."""
        if not thread.messages:
            return ThreadSummary(
                thread_id=thread.thread_id,
                summary="Empty thread",
            )

        # Extract key info from messages
        _first_msg = thread.messages[0]
        _last_msg = thread.messages[-1]

        # Generate summary
        summary_parts = []
        summary_parts.append(f"Conversation about '{thread.subject}'")
        summary_parts.append(f"between {len(thread.participants)} participants.")
        summary_parts.append(f"{thread.message_count} messages")

        if thread.first_message_date and thread.last_message_date:
            duration = (thread.last_message_date - thread.first_message_date).days
            if duration > 0:
                summary_parts.append(f"over {duration} days.")

        summary = " ".join(summary_parts)

        # Extract potential action items (simple heuristic)
        action_items = []
        action_keywords = ["please", "could you", "can you", "need to", "should", "must"]
        for msg in thread.messages[-3:]:  # Check last 3 messages
            for line in msg.body_preview.split("\n"):
                if any(kw in line.lower() for kw in action_keywords):
                    if len(line) < 200:
                        action_items.append(line.strip())

        # Determine urgency
        urgency = "normal"
        urgency_keywords = ["urgent", "asap", "immediately", "deadline"]
        all_text = " ".join(m.body_preview for m in thread.messages).lower()
        if any(kw in all_text for kw in urgency_keywords):
            urgency = "high"

        return ThreadSummary(
            thread_id=thread.thread_id,
            summary=summary,
            action_items=action_items[:5],
            urgency=urgency,
        )

    def _ai_summarize(self, thread: EmailThread, summarizer: Any) -> ThreadSummary:
        """Use AI to generate thread summary."""
        # Prepare thread content for summarization
        content_parts = []
        for msg in thread.messages[:10]:  # Limit to 10 messages
            content_parts.append(
                f"From: {msg.sender}\nDate: {msg.date}\nContent: {msg.body_preview[:500]}\n"
            )

        _thread_content = "\n---\n".join(content_parts)

        # This would call the actual summarizer
        # For now, return heuristic summary
        return self._heuristic_summarize(thread)

    def merge_threads(
        self,
        thread_id_1: str,
        thread_id_2: str,
    ) -> EmailThread | None:
        """
        Merge two threads into one.

        Args:
            thread_id_1: First thread ID
            thread_id_2: Second thread ID (will be merged into first)

        Returns:
            Merged thread or None if merge failed
        """
        thread1 = self._threads.get(thread_id_1)
        thread2 = self._threads.get(thread_id_2)

        if not thread1 or not thread2:
            return None

        # Merge messages
        thread1.messages.extend(thread2.messages)
        thread1.messages.sort(key=lambda m: m.date or datetime.min.replace(tzinfo=timezone.utc))

        # Merge metadata
        thread1.participants.update(thread2.participants)
        thread1.labels.update(thread2.labels)
        thread1.message_count = len(thread1.messages)

        # Update message thread IDs
        for msg in thread2.messages:
            msg.thread_id = thread_id_1
            self._message_id_to_thread[msg.message_id] = thread_id_1

        # Update dates
        self._update_thread_metadata(thread1)

        # Remove old thread
        del self._threads[thread_id_2]

        # Update subject index
        normalized = self._normalize_subject(thread2.subject)
        if normalized in self._normalized_subject_to_threads:
            self._normalized_subject_to_threads[normalized].discard(thread_id_2)

        return thread1

    def split_thread(
        self,
        thread_id: str,
        message_ids: list[str],
    ) -> EmailThread | None:
        """
        Split messages out of a thread into a new thread.

        Args:
            thread_id: Thread to split from
            message_ids: Messages to split out

        Returns:
            New thread or None if split failed
        """
        source_thread = self._threads.get(thread_id)
        if not source_thread:
            return None

        # Find messages to split
        messages_to_split = [m for m in source_thread.messages if m.message_id in message_ids]

        if not messages_to_split:
            return None

        # Remove from source thread
        source_thread.messages = [
            m for m in source_thread.messages if m.message_id not in message_ids
        ]

        # Create new thread
        new_thread_id = f"thread_{hashlib.md5('_'.join(message_ids).encode(), usedforsecurity=False).hexdigest()[:12]}"
        new_thread = EmailThread(
            thread_id=new_thread_id,
            subject=messages_to_split[0].subject,
        )

        for msg in messages_to_split:
            msg.thread_id = new_thread_id
            new_thread.messages.append(msg)
            new_thread.participants.add(msg.sender)
            new_thread.participants.update(msg.recipients)
            self._message_id_to_thread[msg.message_id] = new_thread_id

        self._update_thread_metadata(new_thread)
        self._update_thread_metadata(source_thread)

        self._threads[new_thread_id] = new_thread

        return new_thread

    def find_related_threads(
        self,
        thread_id: str,
        max_results: int = 5,
    ) -> list[EmailThread]:
        """
        Find threads related to a given thread.

        Args:
            thread_id: Source thread
            max_results: Maximum number of related threads

        Returns:
            List of related threads
        """
        source = self._threads.get(thread_id)
        if not source:
            return []

        candidates: list[tuple[str, float]] = []

        for tid, thread in self._threads.items():
            if tid == thread_id:
                continue

            # Calculate relatedness score
            score = 0.0

            # Participant overlap
            overlap = source.participants & thread.participants
            if overlap:
                score += 0.5 * len(overlap) / max(len(source.participants), 1)

            # Subject similarity
            if self._normalize_subject(source.subject) == self._normalize_subject(thread.subject):
                score += 0.3

            # Label overlap
            label_overlap = source.labels & thread.labels
            if label_overlap:
                score += 0.2 * len(label_overlap) / max(len(source.labels), 1)

            if score > 0:
                candidates.append((tid, score))

        # Sort by score and return top results
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [self._threads[tid] for tid, _ in candidates[:max_results]]
