"""
Sender History Persistence Service.

Tracks sender reputation, response patterns, and history for improved
email prioritization. Uses SQLite for persistence with async support.

Features:
- Sender reputation scoring based on historical interactions
- Response time tracking (how quickly user responds to sender)
- Email frequency analysis
- VIP sender management
- Feedback-based learning

Usage:
    from aragora.services.sender_history import SenderHistoryService

    service = SenderHistoryService(db_path="sender_history.db")
    await service.initialize()

    # Record an interaction
    await service.record_interaction(
        user_id="user@example.com",
        sender_email="important@company.com",
        opened=True,
        replied=True,
        response_time_minutes=30,
    )

    # Get sender reputation
    reputation = await service.get_sender_reputation(
        user_id="user@example.com",
        sender_email="important@company.com",
    )
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SenderStats:
    """Statistics about a sender's emails."""

    sender_email: str
    total_emails: int = 0
    emails_opened: int = 0
    emails_replied: int = 0
    emails_archived: int = 0
    emails_deleted: int = 0
    avg_response_time_minutes: float | None = None
    last_email_date: datetime | None = None
    first_email_date: datetime | None = None
    is_vip: bool = False
    is_blocked: bool = False
    custom_priority_boost: float = 0.0
    tags: list[str] = field(default_factory=list)

    @property
    def open_rate(self) -> float:
        """Percentage of emails that were opened."""
        if self.total_emails == 0:
            return 0.0
        return self.emails_opened / self.total_emails

    @property
    def reply_rate(self) -> float:
        """Percentage of emails that received a reply."""
        if self.total_emails == 0:
            return 0.0
        return self.emails_replied / self.total_emails

    @property
    def engagement_score(self) -> float:
        """
        Combined engagement score (0-1).

        Weighted combination of:
        - Open rate (40%)
        - Reply rate (40%)
        - Recency boost (20%)
        """
        # Base engagement from open and reply rates
        engagement = (self.open_rate * 0.4) + (self.reply_rate * 0.4)

        # Recency boost - more recent senders get a bonus
        if self.last_email_date:
            days_since_last = (datetime.now() - self.last_email_date).days
            recency_boost = max(0, 0.2 - (days_since_last * 0.01))
            engagement += recency_boost

        return min(1.0, engagement + self.custom_priority_boost)


@dataclass
class SenderReputation:
    """Computed reputation for a sender."""

    sender_email: str
    reputation_score: float  # 0-1
    confidence: float  # 0-1, based on number of interactions
    priority_boost: float  # -0.5 to 0.5
    is_vip: bool
    is_blocked: bool
    category: str  # "vip", "important", "normal", "low_priority", "blocked"
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sender_email": self.sender_email,
            "reputation_score": self.reputation_score,
            "confidence": self.confidence,
            "priority_boost": self.priority_boost,
            "is_vip": self.is_vip,
            "is_blocked": self.is_blocked,
            "category": self.category,
            "reasons": self.reasons,
        }


class SenderHistoryService:
    """
    Service for tracking and persisting sender history.

    Uses SQLite for local persistence with async-friendly operations.
    """

    def __init__(
        self,
        db_path: str | None = None,
        cache_ttl_seconds: int = 300,
    ):
        """
        Initialize sender history service.

        Args:
            db_path: Path to SQLite database. If None, uses in-memory DB.
            cache_ttl_seconds: TTL for in-memory cache
        """
        self.db_path = db_path or ":memory:"
        self.cache_ttl = cache_ttl_seconds
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

        # In-memory cache for fast lookups
        self._reputation_cache: dict[str, tuple[datetime, SenderReputation]] = {}

        # Domain-level cache for faster bulk processing
        # Stores aggregate domain stats: {user:domain -> (timestamp, avg_reputation, sender_count)}
        self._domain_cache: dict[str, tuple[datetime, float, int]] = {}

    async def initialize(self) -> None:
        """Initialize database schema."""
        async with self._lock:
            self._connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level="DEFERRED",
            )
            self._connection.row_factory = sqlite3.Row

            # Create tables
            self._connection.executescript("""
                -- Sender statistics table
                CREATE TABLE IF NOT EXISTS sender_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    sender_email TEXT NOT NULL,
                    total_emails INTEGER DEFAULT 0,
                    emails_opened INTEGER DEFAULT 0,
                    emails_replied INTEGER DEFAULT 0,
                    emails_archived INTEGER DEFAULT 0,
                    emails_deleted INTEGER DEFAULT 0,
                    total_response_time_minutes INTEGER DEFAULT 0,
                    response_count INTEGER DEFAULT 0,
                    first_email_date TEXT,
                    last_email_date TEXT,
                    is_vip INTEGER DEFAULT 0,
                    is_blocked INTEGER DEFAULT 0,
                    custom_priority_boost REAL DEFAULT 0.0,
                    tags TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, sender_email)
                );

                -- Interaction log for detailed tracking
                CREATE TABLE IF NOT EXISTS interaction_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    sender_email TEXT NOT NULL,
                    email_id TEXT,
                    action TEXT NOT NULL,  -- 'received', 'opened', 'replied', 'archived', 'deleted', 'starred'
                    response_time_minutes INTEGER,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                -- Feedback log for learning
                CREATE TABLE IF NOT EXISTS priority_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    email_id TEXT NOT NULL,
                    sender_email TEXT NOT NULL,
                    predicted_priority TEXT NOT NULL,
                    actual_priority TEXT,
                    is_correct INTEGER,
                    feedback_type TEXT,  -- 'explicit', 'implicit'
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                -- Indexes for fast lookups
                CREATE INDEX IF NOT EXISTS idx_sender_stats_user ON sender_stats(user_id);
                CREATE INDEX IF NOT EXISTS idx_sender_stats_sender ON sender_stats(sender_email);
                CREATE INDEX IF NOT EXISTS idx_interaction_log_user ON interaction_log(user_id);
                CREATE INDEX IF NOT EXISTS idx_interaction_log_sender ON interaction_log(sender_email);
                CREATE INDEX IF NOT EXISTS idx_priority_feedback_user ON priority_feedback(user_id);
                """)
            self._connection.commit()
            logger.info("[sender-history] Initialized database at %s", self.db_path)

    def _require_connection(self) -> sqlite3.Connection:
        """Return the initialized database connection."""
        if self._connection is None:
            raise RuntimeError("Sender history database is not initialized")
        return self._connection

    async def close(self) -> None:
        """Close database connection."""
        async with self._lock:
            if self._connection:
                self._connection.close()
                self._connection = None

    async def record_interaction(
        self,
        user_id: str,
        sender_email: str,
        action: str,
        email_id: str | None = None,
        response_time_minutes: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Record an interaction with a sender.

        Args:
            user_id: User identifier
            sender_email: Sender's email address
            action: Type of action (received, opened, replied, archived, deleted, starred)
            email_id: Optional email identifier
            response_time_minutes: Time to respond (for reply actions)
            metadata: Additional metadata
        """
        import json

        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()

            # Insert interaction log
            cursor.execute(
                """
                INSERT INTO interaction_log
                (user_id, sender_email, email_id, action, response_time_minutes, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    sender_email.lower(),
                    email_id,
                    action,
                    response_time_minutes,
                    json.dumps(metadata or {}),
                ),
            )

            # Update sender stats
            now = datetime.now().isoformat()

            # Upsert sender stats
            cursor.execute(
                """
                INSERT INTO sender_stats (user_id, sender_email, first_email_date, last_email_date, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, sender_email) DO UPDATE SET
                    last_email_date = ?,
                    updated_at = ?
                """,
                (user_id, sender_email.lower(), now, now, now, now, now),
            )

            # Update specific counters based on action
            if action == "received":
                cursor.execute(
                    """
                    UPDATE sender_stats
                    SET total_emails = total_emails + 1
                    WHERE user_id = ? AND sender_email = ?
                    """,
                    (user_id, sender_email.lower()),
                )
            elif action == "opened":
                cursor.execute(
                    """
                    UPDATE sender_stats
                    SET emails_opened = emails_opened + 1
                    WHERE user_id = ? AND sender_email = ?
                    """,
                    (user_id, sender_email.lower()),
                )
            elif action == "replied":
                if response_time_minutes is not None:
                    cursor.execute(
                        """
                        UPDATE sender_stats
                        SET emails_replied = emails_replied + 1,
                            total_response_time_minutes = total_response_time_minutes + ?,
                            response_count = response_count + 1
                        WHERE user_id = ? AND sender_email = ?
                        """,
                        (response_time_minutes, user_id, sender_email.lower()),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE sender_stats
                        SET emails_replied = emails_replied + 1
                        WHERE user_id = ? AND sender_email = ?
                        """,
                        (user_id, sender_email.lower()),
                    )
            elif action == "archived":
                cursor.execute(
                    """
                    UPDATE sender_stats
                    SET emails_archived = emails_archived + 1
                    WHERE user_id = ? AND sender_email = ?
                    """,
                    (user_id, sender_email.lower()),
                )
            elif action == "deleted":
                cursor.execute(
                    """
                    UPDATE sender_stats
                    SET emails_deleted = emails_deleted + 1
                    WHERE user_id = ? AND sender_email = ?
                    """,
                    (user_id, sender_email.lower()),
                )

            connection.commit()

            # Invalidate cache
            cache_key = f"{user_id}:{sender_email.lower()}"
            self._reputation_cache.pop(cache_key, None)

    async def get_sender_stats(
        self,
        user_id: str,
        sender_email: str,
    ) -> SenderStats | None:
        """
        Get statistics for a sender.

        Args:
            user_id: User identifier
            sender_email: Sender's email address

        Returns:
            SenderStats or None if not found
        """
        import json

        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT *
                FROM sender_stats
                WHERE user_id = ? AND sender_email = ?
                """,
                (user_id, sender_email.lower()),
            )

            row = cursor.fetchone()
            if not row:
                return None

            # Calculate average response time
            avg_response_time = None
            if row["response_count"] > 0:
                avg_response_time = row["total_response_time_minutes"] / row["response_count"]

            return SenderStats(
                sender_email=row["sender_email"],
                total_emails=row["total_emails"],
                emails_opened=row["emails_opened"],
                emails_replied=row["emails_replied"],
                emails_archived=row["emails_archived"],
                emails_deleted=row["emails_deleted"],
                avg_response_time_minutes=avg_response_time,
                last_email_date=(
                    datetime.fromisoformat(row["last_email_date"])
                    if row["last_email_date"]
                    else None
                ),
                first_email_date=(
                    datetime.fromisoformat(row["first_email_date"])
                    if row["first_email_date"]
                    else None
                ),
                is_vip=bool(row["is_vip"]),
                is_blocked=bool(row["is_blocked"]),
                custom_priority_boost=row["custom_priority_boost"],
                tags=json.loads(row["tags"]) if row["tags"] else [],
            )

    async def get_sender_reputation(
        self,
        user_id: str,
        sender_email: str,
    ) -> SenderReputation:
        """
        Get computed reputation for a sender.

        Args:
            user_id: User identifier
            sender_email: Sender's email address

        Returns:
            SenderReputation with computed scores
        """
        cache_key = f"{user_id}:{sender_email.lower()}"

        # Check cache
        if cache_key in self._reputation_cache:
            cached_time, cached_rep = self._reputation_cache[cache_key]
            if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                return cached_rep

        # Get stats
        stats = await self.get_sender_stats(user_id, sender_email)

        if not stats:
            # Unknown sender - return neutral reputation
            reputation = SenderReputation(
                sender_email=sender_email.lower(),
                reputation_score=0.5,
                confidence=0.0,
                priority_boost=0.0,
                is_vip=False,
                is_blocked=False,
                category="unknown",
                reasons=["No interaction history"],
            )
            self._reputation_cache[cache_key] = (datetime.now(), reputation)
            return reputation

        # Blocked senders
        if stats.is_blocked:
            reputation = SenderReputation(
                sender_email=sender_email.lower(),
                reputation_score=0.0,
                confidence=1.0,
                priority_boost=-0.5,
                is_vip=False,
                is_blocked=True,
                category="blocked",
                reasons=["Sender is blocked"],
            )
            self._reputation_cache[cache_key] = (datetime.now(), reputation)
            return reputation

        # Calculate reputation score
        reasons = []

        # Base engagement score
        engagement = stats.engagement_score
        reasons.append(f"Engagement score: {engagement:.2f}")

        # VIP bonus
        if stats.is_vip:
            engagement = min(1.0, engagement + 0.3)
            reasons.append("VIP sender (+0.3)")

        # Response time bonus
        if stats.avg_response_time_minutes is not None:
            if stats.avg_response_time_minutes < 30:
                engagement = min(1.0, engagement + 0.1)
                reasons.append("Fast responder (+0.1)")
            elif stats.avg_response_time_minutes > 1440:  # 24 hours
                engagement = max(0, engagement - 0.05)
                reasons.append("Slow responder (-0.05)")

        # Delete rate penalty
        if stats.total_emails > 5:
            delete_rate = stats.emails_deleted / stats.total_emails
            if delete_rate > 0.5:
                engagement = max(0, engagement - 0.15)
                reasons.append(f"High delete rate ({delete_rate:.0%}) (-0.15)")

        # Custom boost
        if stats.custom_priority_boost != 0:
            engagement = max(0, min(1.0, engagement + stats.custom_priority_boost))
            reasons.append(f"Custom boost: {stats.custom_priority_boost:+.2f}")

        # Calculate confidence based on number of interactions
        confidence = min(1.0, stats.total_emails / 20)

        # Calculate priority boost
        priority_boost = (engagement - 0.5) * 0.5  # Maps 0-1 engagement to -0.25 to 0.25

        # Determine category
        if stats.is_vip:
            category = "vip"
        elif engagement > 0.7:
            category = "important"
        elif engagement > 0.4:
            category = "normal"
        else:
            category = "low_priority"

        reputation = SenderReputation(
            sender_email=sender_email.lower(),
            reputation_score=engagement,
            confidence=confidence,
            priority_boost=priority_boost,
            is_vip=stats.is_vip,
            is_blocked=False,
            category=category,
            reasons=reasons,
        )

        # Cache result
        self._reputation_cache[cache_key] = (datetime.now(), reputation)

        # Update domain cache
        await self._update_domain_cache(user_id, sender_email, reputation.reputation_score)

        return reputation

    async def _update_domain_cache(
        self,
        user_id: str,
        sender_email: str,
        reputation_score: float,
    ) -> None:
        """Update domain-level cache with new reputation data."""
        try:
            domain = sender_email.lower().split("@")[-1] if "@" in sender_email else sender_email
            domain_key = f"{user_id}:{domain}"

            if domain_key in self._domain_cache:
                cached_time, avg_rep, count = self._domain_cache[domain_key]
                # Running average
                new_avg = (avg_rep * count + reputation_score) / (count + 1)
                self._domain_cache[domain_key] = (datetime.now(), new_avg, count + 1)
            else:
                self._domain_cache[domain_key] = (datetime.now(), reputation_score, 1)
        except (ValueError, KeyError, TypeError) as e:
            logger.debug("Failed to update domain reputation cache: %s", e)

    async def get_domain_reputation(
        self,
        user_id: str,
        domain: str,
    ) -> tuple[float, int] | None:
        """
        Get aggregate reputation for a domain.

        Args:
            user_id: User identifier
            domain: Email domain (e.g., "company.com")

        Returns:
            Tuple of (average_reputation_score, sender_count) or None if unknown
        """
        domain_key = f"{user_id}:{domain.lower()}"

        # Check cache first
        if domain_key in self._domain_cache:
            cached_time, avg_rep, count = self._domain_cache[domain_key]
            if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                return (avg_rep, count)

        # Query database for domain stats
        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT
                    COUNT(*) as sender_count,
                    AVG(total_emails) as avg_interactions,
                    AVG(CAST(emails_opened AS FLOAT) / NULLIF(total_emails, 0)) as avg_open_rate,
                    AVG(CAST(emails_replied AS FLOAT) / NULLIF(total_emails, 0)) as avg_reply_rate
                FROM sender_stats
                WHERE user_id = ? AND sender_email LIKE ?
                """,
                (user_id, f"%@{domain.lower()}"),
            )
            row = cursor.fetchone()

            if row and row["sender_count"] > 0:
                # Calculate reputation from aggregate stats
                avg_open = row["avg_open_rate"] or 0
                avg_reply = row["avg_reply_rate"] or 0
                # Simple formula: weighted average of open and reply rates
                avg_rep = 0.5 + (avg_open * 0.3 + avg_reply * 0.5) * 0.5
                count = row["sender_count"]

                # Cache result
                self._domain_cache[domain_key] = (datetime.now(), avg_rep, count)
                return (avg_rep, count)

        return None

    async def get_batch_reputations(
        self,
        user_id: str,
        sender_emails: list[str],
    ) -> dict[str, SenderReputation]:
        """
        Get reputations for multiple senders efficiently.

        Uses caching and batch queries to minimize database hits.

        Args:
            user_id: User identifier
            sender_emails: List of sender email addresses

        Returns:
            Dict mapping email addresses to SenderReputation objects
        """
        results: dict[str, SenderReputation] = {}
        uncached_emails: list[str] = []

        # Check cache first
        for email in sender_emails:
            cache_key = f"{user_id}:{email.lower()}"
            if cache_key in self._reputation_cache:
                cached_time, cached_rep = self._reputation_cache[cache_key]
                if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                    results[email.lower()] = cached_rep
                    continue
            uncached_emails.append(email)

        # Fetch uncached emails individually (could be optimized with batch query)
        for email in uncached_emails:
            rep = await self.get_sender_reputation(user_id, email)
            results[email.lower()] = rep

        return results

    async def set_vip(
        self,
        user_id: str,
        sender_email: str,
        is_vip: bool = True,
    ) -> None:
        """
        Set or unset a sender as VIP.

        Args:
            user_id: User identifier
            sender_email: Sender's email address
            is_vip: Whether sender should be VIP
        """
        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()
            now = datetime.now().isoformat()

            cursor.execute(
                """
                INSERT INTO sender_stats (user_id, sender_email, is_vip, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, sender_email) DO UPDATE SET
                    is_vip = ?,
                    updated_at = ?
                """,
                (user_id, sender_email.lower(), int(is_vip), now, int(is_vip), now),
            )
            connection.commit()

            # Invalidate cache
            cache_key = f"{user_id}:{sender_email.lower()}"
            self._reputation_cache.pop(cache_key, None)

    async def set_blocked(
        self,
        user_id: str,
        sender_email: str,
        is_blocked: bool = True,
    ) -> None:
        """
        Block or unblock a sender.

        Args:
            user_id: User identifier
            sender_email: Sender's email address
            is_blocked: Whether sender should be blocked
        """
        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()
            now = datetime.now().isoformat()

            cursor.execute(
                """
                INSERT INTO sender_stats (user_id, sender_email, is_blocked, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, sender_email) DO UPDATE SET
                    is_blocked = ?,
                    updated_at = ?
                """,
                (user_id, sender_email.lower(), int(is_blocked), now, int(is_blocked), now),
            )
            connection.commit()

            # Invalidate cache
            cache_key = f"{user_id}:{sender_email.lower()}"
            self._reputation_cache.pop(cache_key, None)

    async def get_vip_senders(self, user_id: str) -> list[str]:
        """
        Get list of VIP senders for a user.

        Args:
            user_id: User identifier

        Returns:
            List of VIP sender email addresses
        """
        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT sender_email
                FROM sender_stats
                WHERE user_id = ? AND is_vip = 1
                ORDER BY sender_email
                """,
                (user_id,),
            )

            return [row[0] for row in cursor.fetchall()]

    async def is_blocked(self, user_id: str, sender_email: str) -> bool:
        """
        Quick check if a sender is blocked.

        Uses cache for fast lookups during email prioritization.

        Args:
            user_id: User identifier
            sender_email: Sender's email address

        Returns:
            True if sender is blocked, False otherwise
        """
        cache_key = f"{user_id}:{sender_email.lower()}"

        # Check cache first
        if cache_key in self._reputation_cache:
            cached_time, cached_rep = self._reputation_cache[cache_key]
            if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                return cached_rep.is_blocked

        # Query database directly for speed
        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT is_blocked
                FROM sender_stats
                WHERE user_id = ? AND sender_email = ?
                """,
                (user_id, sender_email.lower()),
            )

            row = cursor.fetchone()
            return bool(row["is_blocked"]) if row else False

    async def get_blocked_senders(self, user_id: str) -> list[str]:
        """
        Get list of blocked senders for a user.

        Args:
            user_id: User identifier

        Returns:
            List of blocked sender email addresses
        """
        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT sender_email
                FROM sender_stats
                WHERE user_id = ? AND is_blocked = 1
                ORDER BY sender_email
                """,
                (user_id,),
            )

            return [row[0] for row in cursor.fetchall()]

    async def record_priority_feedback(
        self,
        user_id: str,
        email_id: str,
        sender_email: str,
        predicted_priority: str,
        actual_priority: str | None = None,
        is_correct: bool | None = None,
        feedback_type: str = "explicit",
    ) -> None:
        """
        Record feedback on priority prediction.

        Args:
            user_id: User identifier
            email_id: Email identifier
            sender_email: Sender's email address
            predicted_priority: What we predicted
            actual_priority: What user indicated it should be
            is_correct: Whether prediction was correct
            feedback_type: Type of feedback (explicit user feedback or implicit from actions)
        """
        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO priority_feedback
                (user_id, email_id, sender_email, predicted_priority, actual_priority, is_correct, feedback_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    email_id,
                    sender_email.lower(),
                    predicted_priority,
                    actual_priority,
                    int(is_correct) if is_correct is not None else None,
                    feedback_type,
                ),
            )
            connection.commit()

    async def get_prediction_accuracy(
        self,
        user_id: str,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Get prediction accuracy statistics for a user.

        Args:
            user_id: User identifier
            days: Number of days to look back

        Returns:
            Dict with accuracy statistics
        """
        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

            cursor.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct,
                    SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) as incorrect,
                    SUM(CASE WHEN is_correct IS NULL THEN 1 ELSE 0 END) as unknown
                FROM priority_feedback
                WHERE user_id = ? AND created_at >= ?
                """,
                (user_id, cutoff),
            )

            row = cursor.fetchone()
            total = row["total"] or 0
            correct = row["correct"] or 0

            accuracy = correct / total if total > 0 else None

            return {
                "total_feedback": total,
                "correct": correct,
                "incorrect": row["incorrect"] or 0,
                "unknown": row["unknown"] or 0,
                "accuracy": accuracy,
                "days": days,
            }

    async def get_top_senders(
        self,
        user_id: str,
        limit: int = 20,
        order_by: str = "engagement",
    ) -> list[SenderStats]:
        """
        Get top senders by various criteria.

        Args:
            user_id: User identifier
            limit: Maximum number of results
            order_by: Sort order (engagement, total_emails, reply_rate)

        Returns:
            List of SenderStats
        """
        async with self._lock:
            if not self._connection:
                await self.initialize()
            connection = self._require_connection()

            cursor = connection.cursor()

            if order_by == "total_emails":
                order_clause = "total_emails DESC"
            elif order_by == "reply_rate":
                order_clause = "CAST(emails_replied AS REAL) / NULLIF(total_emails, 0) DESC"
            else:  # engagement
                order_clause = """
                    (CAST(emails_opened AS REAL) / NULLIF(total_emails, 0) * 0.4 +
                     CAST(emails_replied AS REAL) / NULLIF(total_emails, 0) * 0.4) DESC
                """

            cursor.execute(
                f"""
                SELECT *
                FROM sender_stats
                WHERE user_id = ? AND total_emails > 0
                ORDER BY {order_clause}
                LIMIT ?
                """,  # noqa: S608 -- dynamic clause from internal state
                (user_id, limit),
            )

            import json

            results = []
            for row in cursor.fetchall():
                avg_response_time = None
                if row["response_count"] > 0:
                    avg_response_time = row["total_response_time_minutes"] / row["response_count"]

                results.append(
                    SenderStats(
                        sender_email=row["sender_email"],
                        total_emails=row["total_emails"],
                        emails_opened=row["emails_opened"],
                        emails_replied=row["emails_replied"],
                        emails_archived=row["emails_archived"],
                        emails_deleted=row["emails_deleted"],
                        avg_response_time_minutes=avg_response_time,
                        last_email_date=(
                            datetime.fromisoformat(row["last_email_date"])
                            if row["last_email_date"]
                            else None
                        ),
                        first_email_date=(
                            datetime.fromisoformat(row["first_email_date"])
                            if row["first_email_date"]
                            else None
                        ),
                        is_vip=bool(row["is_vip"]),
                        is_blocked=bool(row["is_blocked"]),
                        custom_priority_boost=row["custom_priority_boost"],
                        tags=json.loads(row["tags"]) if row["tags"] else [],
                    )
                )

            return results


# Convenience function for creating service
async def create_sender_history_service(
    db_path: str | None = None,
) -> SenderHistoryService:
    """
    Create and initialize a sender history service.

    Args:
        db_path: Path to SQLite database

    Returns:
        Initialized SenderHistoryService
    """
    service = SenderHistoryService(db_path=db_path)
    await service.initialize()
    return service
