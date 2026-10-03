"""
Cross-Channel Context Service.

Integrates signals from multiple communication channels to provide
unified context for email prioritization and other AI-powered features.

Supported Channels:
- Slack: Recent activity, channel urgency, user presence
- Google Drive: Recent document activity, shared file context
- Google Calendar: Upcoming meetings, availability
- GitHub: Recent commits, PR activity

Usage:
    from aragora.services.cross_channel_context import (
        CrossChannelContextService,
        ChannelContext,
    )

    service = CrossChannelContextService(
        slack_connector=slack,
        gmail_connector=gmail,
        drive_connector=drive,
    )

    # Get unified context for a user
    context = await service.get_user_context(user_email)

    # Get context relevant to an email
    email_context = await service.get_email_context(email_message)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.connectors.enterprise.collaboration.slack import SlackConnector
    from aragora.connectors.enterprise.communication.gmail import GmailConnector
    from aragora.connectors.enterprise.communication.models import EmailMessage
    from aragora.knowledge.mound import KnowledgeMound
    from aragora.storage.integration_store import IntegrationStoreBackend

logger = logging.getLogger(__name__)


@dataclass
class SlackActivitySignal:
    """Signal from Slack activity."""

    user_email: str
    is_online: bool = False
    active_channels: list[str] = field(default_factory=list)
    recent_mentions: int = 0
    urgent_threads: list[str] = field(default_factory=list)
    last_activity: datetime | None = None
    activity_score: float = 0.0


@dataclass
class DriveActivitySignal:
    """Signal from Google Drive activity."""

    user_email: str
    recently_edited_files: list[str] = field(default_factory=list)
    recently_viewed_files: list[str] = field(default_factory=list)
    shared_with_me_recent: list[str] = field(default_factory=list)
    activity_score: float = 0.0


@dataclass
class CalendarSignal:
    """Signal from Google Calendar."""

    user_email: str
    upcoming_meetings: list[dict[str, Any]] = field(default_factory=list)
    busy_periods: list[tuple[datetime, datetime]] = field(default_factory=list)
    next_free_slot: datetime | None = None
    meeting_density_score: float = 0.0  # 0=free, 1=back-to-back meetings


@dataclass
class ChannelContext:
    """Unified context from all channels."""

    user_email: str
    timestamp: datetime = field(default_factory=datetime.now)

    # Channel-specific signals
    slack: SlackActivitySignal | None = None
    drive: DriveActivitySignal | None = None
    calendar: CalendarSignal | None = None

    # Derived signals
    overall_activity_score: float = 0.0
    is_likely_busy: bool = False
    suggested_response_window: str | None = None

    # Related entities
    active_projects: list[str] = field(default_factory=list)
    active_contacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "user_email": self.user_email,
            "timestamp": self.timestamp.isoformat(),
            "overall_activity_score": self.overall_activity_score,
            "is_likely_busy": self.is_likely_busy,
            "suggested_response_window": self.suggested_response_window,
            "active_projects": self.active_projects,
            "active_contacts": self.active_contacts,
            "slack": (
                {
                    "is_online": self.slack.is_online if self.slack else False,
                    "active_channels": self.slack.active_channels if self.slack else [],
                    "recent_mentions": self.slack.recent_mentions if self.slack else 0,
                    "activity_score": self.slack.activity_score if self.slack else 0.0,
                }
                if self.slack
                else None
            ),
            "drive": (
                {
                    "recently_edited_count": (
                        len(self.drive.recently_edited_files) if self.drive else 0
                    ),
                    "activity_score": self.drive.activity_score if self.drive else 0.0,
                }
                if self.drive
                else None
            ),
            "calendar": (
                {
                    "upcoming_meetings_count": (
                        len(self.calendar.upcoming_meetings) if self.calendar else 0
                    ),
                    "meeting_density": (
                        self.calendar.meeting_density_score if self.calendar else 0.0
                    ),
                }
                if self.calendar
                else None
            ),
        }


@dataclass
class EmailContextBoost:
    """Context-based priority boosts for an email."""

    email_id: str

    # Boost scores (0-1, applied as multipliers)
    slack_activity_boost: float = 0.0
    drive_relevance_boost: float = 0.0
    calendar_urgency_boost: float = 0.0

    # Explanations
    slack_reason: str | None = None
    drive_reason: str | None = None
    calendar_reason: str | None = None

    # Related context
    related_slack_channels: list[str] = field(default_factory=list)
    related_drive_files: list[str] = field(default_factory=list)
    related_meetings: list[str] = field(default_factory=list)

    @property
    def total_boost(self) -> float:
        """Total combined boost."""
        return self.slack_activity_boost + self.drive_relevance_boost + self.calendar_urgency_boost


class CrossChannelContextService:
    """
    Service for gathering cross-channel context.

    Integrates multiple communication platforms to provide
    unified context for AI-powered features like email prioritization.
    """

    def __init__(
        self,
        slack_connector: SlackConnector | None = None,
        gmail_connector: GmailConnector | None = None,
        knowledge_mound: KnowledgeMound | None = None,
        integration_store: IntegrationStoreBackend | None = None,
        cache_ttl_seconds: int = 300,  # 5 minute cache
        user_id: str = "default",  # Multi-tenant owner
    ):
        """
        Initialize cross-channel context service.

        Args:
            slack_connector: Slack connector for activity signals
            gmail_connector: Gmail connector for email context
            knowledge_mound: KM for historical context
            integration_store: Store for persisting user ID mappings
            cache_ttl_seconds: Cache TTL for context data
            user_id: Owner ID for multi-tenant isolation
        """
        self.slack = slack_connector
        self.gmail = gmail_connector
        self.mound = knowledge_mound
        self._store = integration_store
        self.cache_ttl = cache_ttl_seconds
        self._user_id = user_id

        # Context cache (ephemeral, performance only)
        self._context_cache: dict[str, tuple[datetime, ChannelContext]] = {}

        # Email-user mapping for Slack correlation (in-memory cache, backed by store)
        self._email_to_slack_id: dict[str, str] = {}

    async def get_user_context(
        self,
        user_email: str,
        force_refresh: bool = False,
    ) -> ChannelContext:
        """
        Get unified context for a user across all channels.

        Args:
            user_email: User's email address
            force_refresh: Force refresh even if cached

        Returns:
            ChannelContext with unified signals
        """
        # Check cache
        if not force_refresh and user_email in self._context_cache:
            cached_time, cached_context = self._context_cache[user_email]
            if (datetime.now() - cached_time).total_seconds() < self.cache_ttl:
                return cached_context

        # Gather signals concurrently
        tasks = []

        if self.slack:
            tasks.append(self._get_slack_signal(user_email))
        else:
            # Create a no-op coroutine when no Slack connector
            async def _noop():
                return None

            tasks.append(_noop())

        # More connectors would be added here (Drive, Calendar)
        # For now, we'll stub them

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build context
        context = ChannelContext(user_email=user_email)

        # Process Slack signal
        if results and not isinstance(results[0], (Exception, BaseException)) and results[0]:
            slack_result = results[0]
            if isinstance(slack_result, SlackActivitySignal):
                context.slack = slack_result

        # Calculate derived signals
        context = self._calculate_derived_signals(context)

        # Cache result
        self._context_cache[user_email] = (datetime.now(), context)

        return context

    async def get_email_context(
        self,
        email: EmailMessage,
    ) -> EmailContextBoost:
        """
        Get context-based priority boosts for an email.

        Args:
            email: Email message to contextualize

        Returns:
            EmailContextBoost with boost scores and reasons
        """
        boost = EmailContextBoost(email_id=email.id)

        # Get sender context
        sender_context = await self.get_user_context(email.from_address)

        # Slack activity boost
        if sender_context.slack and sender_context.slack.is_online:
            boost.slack_activity_boost = 0.15
            boost.slack_reason = "Sender is currently active on Slack"

            # Check for urgent thread correlation
            if sender_context.slack.urgent_threads:
                boost.slack_activity_boost += 0.1
                boost.slack_reason += (
                    f" with {len(sender_context.slack.urgent_threads)} urgent threads"
                )

            boost.related_slack_channels = sender_context.slack.active_channels[:3]

        # Additional context from email content
        await self._analyze_email_content_context(email, boost, sender_context)

        return boost

    async def get_sender_slack_activity(
        self,
        sender_email: str,
        lookback_hours: int = 24,
    ) -> SlackActivitySignal | None:
        """
        Get recent Slack activity for an email sender.

        Args:
            sender_email: Sender's email address
            lookback_hours: Hours to look back for activity

        Returns:
            SlackActivitySignal or None if not found
        """
        if not self.slack:
            return None

        return await self._get_slack_signal(sender_email, lookback_hours)

    async def _get_slack_signal(
        self,
        user_email: str,
        lookback_hours: int = 24,
    ) -> SlackActivitySignal | None:
        """Get Slack activity signal for a user."""
        if not self.slack:
            return None

        signal = SlackActivitySignal(user_email=user_email)

        try:
            # Get Slack user ID from email
            slack_user_id = await self._resolve_slack_user(user_email)
            if not slack_user_id:
                return signal

            # Get user presence
            try:
                presence = await self.slack.get_user_presence(slack_user_id)
                signal.is_online = presence.get("presence") == "active"
                signal.activity_score += 0.2 if signal.is_online else 0.0
            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.debug("Failed to get Slack presence: %s", e)

            # Get recent messages from user
            try:
                datetime.now() - timedelta(hours=lookback_hours)
                messages = await self.slack.search_messages(
                    query=f"from:<@{slack_user_id}>",
                    count=20,
                )

                if messages:
                    # Extract active channels
                    channel_ids = set()
                    for msg in messages:
                        if "channel" in msg:
                            channel_ids.add(msg["channel"])

                    signal.active_channels = list(channel_ids)[:5]
                    signal.activity_score += min(0.3, len(channel_ids) * 0.1)

                    # Count urgent thread indicators
                    urgent_count = sum(
                        1
                        for msg in messages
                        if any(
                            kw in msg.get("text", "").lower()
                            for kw in ["urgent", "asap", "blocker", "critical"]
                        )
                    )
                    if urgent_count > 0:
                        signal.urgent_threads = [
                            timestamp
                            for message in messages[:urgent_count]
                            if isinstance((timestamp := message.get("ts")), str)
                        ]
                        signal.activity_score += min(0.2, urgent_count * 0.05)

            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.debug("Failed to search Slack messages: %s", e)

            # Get mentions of this user
            try:
                mentions = await self.slack.search_messages(
                    query=f"<@{slack_user_id}>",
                    count=10,
                )
                signal.recent_mentions = len(mentions) if mentions else 0
                signal.activity_score += min(0.2, signal.recent_mentions * 0.02)
            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.debug("Failed to search Slack mentions: %s", e)

            signal.activity_score = min(1.0, signal.activity_score)
            signal.last_activity = datetime.now()

            return signal

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.warning("Failed to get Slack signal for %s: %s", user_email, e)
            return signal

    async def _resolve_slack_user(self, email: str) -> str | None:
        """Resolve email address to Slack user ID."""
        # Check in-memory cache first
        if email in self._email_to_slack_id:
            return self._email_to_slack_id[email]

        # Check persistent store
        if self._store:
            try:
                mapping = await self._store.get_user_mapping(email, "slack", self._user_id)
                if mapping:
                    # Populate in-memory cache
                    self._email_to_slack_id[email] = mapping.platform_user_id
                    return mapping.platform_user_id
            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.debug("Failed to load mapping from store: %s", e)

        if not self.slack:
            return None

        try:
            # Try to find user by email via Slack API
            user = await self.slack.get_user_by_email(email)
            if user and "id" in user:
                slack_user_id = user["id"]
                display_name = user.get("real_name") or user.get("name")

                # Cache in memory
                self._email_to_slack_id[email] = slack_user_id

                # Persist to store
                if self._store:
                    try:
                        from aragora.storage.integration_store import UserIdMapping

                        mapping = UserIdMapping(
                            email=email,
                            platform="slack",
                            platform_user_id=slack_user_id,
                            display_name=display_name,
                            user_id=self._user_id,
                        )
                        await self._store.save_user_mapping(mapping)
                        logger.debug("Persisted Slack mapping: %s -> %s", email, slack_user_id)
                    except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                        logger.debug("Failed to persist mapping: %s", e)

                return slack_user_id
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.debug("Failed to resolve Slack user for %s: %s", email, e)

        return None

    async def _analyze_email_content_context(
        self,
        email: EmailMessage,
        boost: EmailContextBoost,
        sender_context: ChannelContext,
    ) -> None:
        """
        Analyze email content for cross-channel context matches.

        Updates boost in place.
        """
        if not self.mound:
            return

        # Extract key terms from email
        text = f"{email.subject} {email.body_text or ''}"
        words = set(text.lower().split())

        # Remove common words
        stopwords = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "and",
            "or",
            "but",
            "if",
            "then",
            "else",
            "when",
            "where",
            "which",
            "who",
            "whom",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "me",
            "him",
            "her",
            "us",
            "them",
            "my",
            "your",
            "his",
            "its",
            "our",
            "their",
            "for",
            "to",
            "from",
            "with",
            "at",
            "by",
            "on",
            "in",
            "of",
            "about",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "under",
            "again",
            "further",
            "once",
            "here",
            "there",
            "all",
            "each",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "no",
            "nor",
            "not",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
            "just",
        }
        keywords = words - stopwords

        # Query knowledge mound for related content
        try:
            query = " ".join(list(keywords)[:10])
            results = await self.mound.query(query, limit=5)

            if results and hasattr(results, "items") and results.items:
                # Check for Slack-related knowledge
                for item in results.items:
                    if hasattr(item, "metadata"):
                        source = item.metadata.get("source_type", "")
                        if "slack" in source.lower():
                            boost.drive_relevance_boost += 0.05
                            boost.drive_reason = "Related to recent Slack discussion"
                        elif "drive" in source.lower() or "document" in source.lower():
                            boost.drive_relevance_boost += 0.1
                            boost.drive_reason = f"Related to recent document: {item.metadata.get('title', 'Unknown')}"

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.debug("Failed to query knowledge mound: %s", e)

    def _calculate_derived_signals(self, context: ChannelContext) -> ChannelContext:
        """Calculate derived signals from raw channel data."""
        scores = []

        if context.slack:
            scores.append(context.slack.activity_score)

        if context.drive:
            scores.append(context.drive.activity_score)

        if context.calendar:
            scores.append(context.calendar.meeting_density_score)

        if scores:
            context.overall_activity_score = sum(scores) / len(scores)

        # Determine if user is likely busy
        context.is_likely_busy = (
            context.calendar and context.calendar.meeting_density_score > 0.7
        ) or context.overall_activity_score > 0.8

        # Suggest response window
        if context.is_likely_busy:
            context.suggested_response_window = "Evening or next morning"
        elif context.slack and context.slack.is_online:
            context.suggested_response_window = "Now - user is active"
        else:
            context.suggested_response_window = "Within business hours"

        return context

    def clear_cache(self, user_email: str | None = None) -> None:
        """
        Clear context cache.

        Args:
            user_email: Specific user to clear, or None for all
        """
        if user_email:
            self._context_cache.pop(user_email, None)
        else:
            self._context_cache.clear()

    async def load_mappings_from_store(self) -> int:
        """
        Load all user ID mappings from persistent store into memory cache.

        Call this on startup for faster lookups.

        Returns:
            Number of mappings loaded
        """
        if not self._store:
            return 0

        try:
            mappings = await self._store.list_user_mappings(platform="slack", user_id=self._user_id)
            for mapping in mappings:
                self._email_to_slack_id[mapping.email] = mapping.platform_user_id

            logger.info("Loaded %s Slack user mappings from store", len(mappings))
            return len(mappings)
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.warning("Failed to load mappings from store: %s", e)
            return 0


# Factory function for easy instantiation
async def create_context_service(
    slack_token: str | None = None,
    knowledge_mound: KnowledgeMound | None = None,
    user_id: str = "default",
    load_mappings: bool = True,
) -> CrossChannelContextService:
    """
    Create a configured cross-channel context service.

    Args:
        slack_token: Slack bot token
        knowledge_mound: Knowledge Mound instance
        user_id: Owner ID for multi-tenant isolation
        load_mappings: Whether to preload user ID mappings from store

    Returns:
        Configured CrossChannelContextService
    """
    slack_connector = None

    if slack_token:
        from aragora.connectors.enterprise.collaboration.slack import SlackConnector

        slack_connector = SlackConnector()
        await slack_connector.authenticate(token=slack_token)

    # Get integration store for persistent mappings
    try:
        from aragora.storage.integration_store import get_integration_store

        integration_store = get_integration_store()
    except (ImportError, ModuleNotFoundError) as e:
        logger.debug("Integration store module not available: %s", e)
        integration_store = None
    except (RuntimeError, ConnectionError) as e:
        logger.warning("Integration store unavailable: %s", e)
        integration_store = None
    except (ValueError, TypeError, OSError) as e:
        logger.exception("Unexpected error getting integration store: %s", e)
        integration_store = None

    service = CrossChannelContextService(
        slack_connector=slack_connector,
        knowledge_mound=knowledge_mound,
        integration_store=integration_store,
        user_id=user_id,
    )

    # Preload mappings from store
    if load_mappings:
        await service.load_mappings_from_store()

    return service
