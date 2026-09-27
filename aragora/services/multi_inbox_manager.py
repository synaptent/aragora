"""
Multi-Inbox Manager for Gmail.

Manages multiple Gmail accounts for unified inbox prioritization:
- Connect and authenticate multiple Gmail accounts
- Aggregate emails across accounts
- Cross-account sender intelligence
- Unified prioritization with account context

Usage:
    from aragora.services.multi_inbox_manager import (
        MultiInboxManager,
        InboxAccount,
    )

    manager = MultiInboxManager(user_id="user_123")

    # Add accounts
    await manager.add_account("personal", oauth_tokens_personal)
    await manager.add_account("work", oauth_tokens_work)

    # Get unified prioritized inbox
    emails = await manager.get_unified_inbox(limit=100)

    # Cross-account sender analysis
    importance = await manager.get_sender_importance("sender@example.com")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.connectors.enterprise.communication.gmail import GmailConnector
    from aragora.connectors.enterprise.communication.models import EmailMessage
    from aragora.services.email_prioritization import EmailPriorityResult

logger = logging.getLogger(__name__)


class AccountType(Enum):
    """Type of email account for context-aware prioritization."""

    PERSONAL = "personal"
    WORK = "work"
    BUSINESS = "business"
    SHARED = "shared"
    OTHER = "other"


@dataclass
class InboxAccount:
    """Represents a connected Gmail account."""

    account_id: str  # User-defined identifier (e.g., "personal", "work")
    email_address: str
    account_type: AccountType = AccountType.OTHER
    is_primary: bool = False

    # Connection state
    is_connected: bool = False
    last_sync: datetime | None = None
    sync_error: str | None = None

    # Account-specific settings
    priority_weight: float = 1.0  # Weight for this account in unified scoring
    auto_archive_labels: list[str] = field(default_factory=list)
    vip_override: bool = False  # VIPs from this account override others

    # Statistics
    total_emails: int = 0
    unread_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "account_id": self.account_id,
            "email_address": self.email_address,
            "account_type": self.account_type.value,
            "is_primary": self.is_primary,
            "is_connected": self.is_connected,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "sync_error": self.sync_error,
            "priority_weight": self.priority_weight,
            "total_emails": self.total_emails,
            "unread_count": self.unread_count,
        }


@dataclass
class UnifiedEmail:
    """Email with multi-account context."""

    email: EmailMessage
    account_id: str
    account_type: AccountType

    # Cross-account context
    sender_seen_in_accounts: list[str] = field(default_factory=list)
    sender_replied_from_accounts: list[str] = field(default_factory=list)
    is_cross_account_important: bool = False

    # Prioritization result
    priority_result: EmailPriorityResult | None = None
    unified_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.email.id,
            "account_id": self.account_id,
            "account_type": self.account_type.value,
            "subject": self.email.subject,
            "from_address": self.email.from_address,
            "date": self.email.date.isoformat() if self.email.date else None,
            "snippet": self.email.snippet if hasattr(self.email, "snippet") else "",
            "labels": self.email.labels,
            "is_read": self.email.is_read,
            "is_starred": self.email.is_starred,
            "sender_seen_in_accounts": self.sender_seen_in_accounts,
            "sender_replied_from_accounts": self.sender_replied_from_accounts,
            "is_cross_account_important": self.is_cross_account_important,
            "unified_score": self.unified_score,
            "priority": self.priority_result.priority.value if self.priority_result else None,
            "confidence": self.priority_result.confidence if self.priority_result else None,
        }


@dataclass
class CrossAccountSenderProfile:
    """Sender profile aggregated across all accounts."""

    sender_email: str

    # Presence across accounts
    seen_in_accounts: set[str] = field(default_factory=set)
    replied_from_accounts: set[str] = field(default_factory=set)
    starred_in_accounts: set[str] = field(default_factory=set)

    # Aggregate statistics
    total_emails_received: int = 0
    total_emails_opened: int = 0
    total_emails_replied: int = 0

    # Per-account breakdown
    account_stats: dict[str, dict[str, int]] = field(default_factory=dict)

    # Computed importance
    cross_account_importance: float = 0.0
    importance_reasons: list[str] = field(default_factory=list)

    @property
    def account_count(self) -> int:
        """Number of accounts this sender appears in."""
        return len(self.seen_in_accounts)

    @property
    def reply_rate(self) -> float:
        """Overall reply rate across all accounts."""
        if self.total_emails_received == 0:
            return 0.0
        return self.total_emails_replied / self.total_emails_received

    def compute_importance(self) -> float:
        """
        Compute cross-account importance score.

        Factors:
        - Multi-account presence (seen in multiple accounts = more important)
        - Reply patterns (replied from multiple accounts = very important)
        - Engagement across accounts
        """
        score = 0.0
        reasons = []

        # Multi-account presence bonus
        if self.account_count > 1:
            multi_account_bonus = min(0.3, self.account_count * 0.15)
            score += multi_account_bonus
            reasons.append(f"Seen in {self.account_count} accounts (+{multi_account_bonus:.2f})")

        # Replied from multiple accounts = very important
        if len(self.replied_from_accounts) > 1:
            reply_bonus = min(0.4, len(self.replied_from_accounts) * 0.2)
            score += reply_bonus
            reasons.append(
                f"Replied from {len(self.replied_from_accounts)} accounts (+{reply_bonus:.2f})"
            )
        elif len(self.replied_from_accounts) == 1:
            score += 0.15
            reasons.append("Replied from 1 account (+0.15)")

        # Starred in any account
        if self.starred_in_accounts:
            score += 0.1
            reasons.append(f"Starred in {len(self.starred_in_accounts)} accounts (+0.1)")

        # Overall engagement
        if self.reply_rate > 0.5:
            score += 0.1
            reasons.append(f"High reply rate ({self.reply_rate:.0%}) (+0.1)")

        self.cross_account_importance = min(1.0, score)
        self.importance_reasons = reasons

        return self.cross_account_importance


class MultiInboxManager:
    """
    Manager for multiple Gmail accounts with unified prioritization.
    """

    def __init__(
        self,
        user_id: str = "default",
        prioritizer: Any | None = None,
        sender_history: Any | None = None,
    ):
        """
        Initialize multi-inbox manager.

        Args:
            user_id: Owner user ID for multi-tenant isolation
            prioritizer: Email prioritizer instance
            sender_history: Sender history service instance
        """
        self.user_id = user_id
        self.prioritizer = prioritizer
        self.sender_history = sender_history

        # Connected accounts
        self._accounts: dict[str, InboxAccount] = {}
        self._connectors: dict[str, GmailConnector] = {}

        # Cross-account sender profiles
        self._sender_profiles: dict[str, CrossAccountSenderProfile] = {}

        # Locks for thread safety
        self._accounts_lock = asyncio.Lock()
        self._profiles_lock = asyncio.Lock()

    async def add_account(
        self,
        account_id: str,
        refresh_token: str,
        email_address: str | None = None,
        account_type: AccountType = AccountType.OTHER,
        is_primary: bool = False,
        priority_weight: float = 1.0,
    ) -> InboxAccount:
        """
        Add and connect a Gmail account.

        Args:
            account_id: User-defined identifier (e.g., "personal", "work")
            refresh_token: OAuth refresh token
            email_address: Email address (fetched if not provided)
            account_type: Type of account for context
            is_primary: Whether this is the primary account
            priority_weight: Weight for unified scoring

        Returns:
            Connected InboxAccount
        """
        from aragora.connectors.enterprise.communication.gmail import GmailConnector

        async with self._accounts_lock:
            # Create connector
            connector: GmailConnector = GmailConnector()

            # Authenticate
            success = await connector.authenticate(refresh_token=refresh_token)

            if not success:
                raise ValueError(f"Failed to authenticate account {account_id}")

            # Get email address if not provided
            if not email_address:
                try:
                    profile = await connector._api_request("/profile")
                    email_address = profile.get("emailAddress", f"{account_id}@unknown")
                except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                    logger.warning("Failed to get email address: %s", e)
                    email_address = f"{account_id}@unknown"

            # Create account record
            account = InboxAccount(
                account_id=account_id,
                email_address=email_address,
                account_type=account_type,
                is_primary=is_primary,
                is_connected=True,
                last_sync=None,
                priority_weight=priority_weight,
            )

            # If this is primary, unset others
            if is_primary:
                for existing in self._accounts.values():
                    existing.is_primary = False

            self._accounts[account_id] = account
            self._connectors[account_id] = connector

            logger.info("[MultiInbox] Added account %s: %s", account_id, email_address)

            return account

    async def remove_account(self, account_id: str) -> bool:
        """Remove a connected account."""
        async with self._accounts_lock:
            if account_id in self._accounts:
                del self._accounts[account_id]
                del self._connectors[account_id]
                logger.info("[MultiInbox] Removed account %s", account_id)
                return True
            return False

    def get_accounts(self) -> list[InboxAccount]:
        """Get all connected accounts."""
        return list(self._accounts.values())

    def get_account(self, account_id: str) -> InboxAccount | None:
        """Get a specific account."""
        return self._accounts.get(account_id)

    async def sync_account(
        self,
        account_id: str,
        max_messages: int = 100,
        labels: list[str] | None = None,
    ) -> int:
        """
        Sync messages from a specific account.

        Args:
            account_id: Account to sync
            max_messages: Maximum messages to fetch
            labels: Labels to filter (default: INBOX)

        Returns:
            Number of messages synced
        """
        if account_id not in self._connectors:
            raise ValueError(f"Account {account_id} not found")

        connector = self._connectors[account_id]
        account = self._accounts[account_id]

        try:
            # Fetch message IDs from INBOX
            message_ids, _ = await connector.list_messages(
                query="",
                max_results=max_messages,
            )

            # Fetch full messages
            messages = await connector.get_messages(
                message_ids=message_ids[:max_messages],
                format="full",
            )

            # Update account stats
            account.last_sync = datetime.now()
            account.total_emails = len(messages)
            account.sync_error = None

            # Update sender profiles with EmailMessage objects
            await self._update_sender_profiles(account_id, messages)

            logger.info("[MultiInbox] Synced %s messages from %s", len(messages), account_id)
            return len(messages)

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            account.sync_error = str(e)
            logger.error("[MultiInbox] Sync failed for %s: %s", account_id, e)
            raise

    async def sync_all_accounts(
        self,
        max_messages_per_account: int = 100,
    ) -> dict[str, int]:
        """
        Sync all connected accounts.

        Returns:
            Dict of account_id -> messages synced
        """
        results = {}

        # Sync accounts concurrently
        async def sync_one(account_id: str) -> tuple[str, int]:
            try:
                count = await self.sync_account(account_id, max_messages_per_account)
                return account_id, count
            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.error("[MultiInbox] Failed to sync %s: %s", account_id, e)
                return account_id, 0

        tasks = [sync_one(aid) for aid in self._accounts.keys()]
        sync_results = await asyncio.gather(*tasks)

        for account_id, count in sync_results:
            results[account_id] = count

        return results

    async def get_unified_inbox(
        self,
        limit: int = 50,
        include_read: bool = False,
        labels: list[str] | None = None,
    ) -> list[UnifiedEmail]:
        """
        Get unified, prioritized inbox across all accounts.

        Args:
            limit: Maximum emails to return
            include_read: Include read emails
            labels: Filter by labels

        Returns:
            List of UnifiedEmail sorted by priority
        """
        all_emails: list[UnifiedEmail] = []

        # Fetch from all accounts
        for account_id, connector in self._connectors.items():
            account = self._accounts[account_id]

            try:
                # Build query
                query_parts = []
                if not include_read:
                    query_parts.append("is:unread")
                if labels:
                    for label in labels:
                        query_parts.append(f"label:{label}")

                query = " ".join(query_parts)

                # Fetch message IDs
                message_ids, _ = await connector.list_messages(
                    query=query,
                    max_results=limit,
                )

                # Get full messages
                full_messages = await connector.get_messages(
                    message_ids=message_ids,
                    format="full",
                )

                for full_msg in full_messages:
                    if not full_msg:
                        continue

                    # Get cross-account context
                    sender = full_msg.from_address.lower()
                    sender_profile = await self.get_sender_profile(sender)

                    unified = UnifiedEmail(
                        email=full_msg,
                        account_id=account_id,
                        account_type=account.account_type,
                        sender_seen_in_accounts=(
                            list(sender_profile.seen_in_accounts) if sender_profile else []
                        ),
                        sender_replied_from_accounts=(
                            list(sender_profile.replied_from_accounts) if sender_profile else []
                        ),
                        is_cross_account_important=(
                            sender_profile.cross_account_importance > 0.3
                            if sender_profile
                            else False
                        ),
                    )

                    all_emails.append(unified)

            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.error("[MultiInbox] Failed to fetch from %s: %s", account_id, e)

        # Prioritize all emails
        all_emails = await self._prioritize_unified_emails(all_emails)

        # Sort by unified score
        all_emails.sort(key=lambda e: e.unified_score, reverse=True)

        return all_emails[:limit]

    async def _prioritize_unified_emails(
        self,
        emails: list[UnifiedEmail],
    ) -> list[UnifiedEmail]:
        """Prioritize emails with cross-account context."""
        if not self.prioritizer:
            # Simple scoring without prioritizer
            for email in emails:
                score = 0.5  # Base score

                # Cross-account bonus
                if email.is_cross_account_important:
                    score += 0.2

                # Account weight
                account = self._accounts.get(email.account_id)
                if account:
                    score *= account.priority_weight

                # Gmail signals
                if email.email.is_starred:
                    score += 0.15
                if email.email.is_important:
                    score += 0.1

                email.unified_score = min(1.0, score)

            return emails

        # Use prioritizer for each email
        for email in emails:
            try:
                result = await self.prioritizer.score_email(email.email)
                email.priority_result = result

                # Compute unified score
                base_score = result.score

                # Cross-account boost
                if email.is_cross_account_important:
                    base_score += 0.15

                # Account weight
                account = self._accounts.get(email.account_id)
                if account:
                    base_score *= account.priority_weight

                email.unified_score = min(1.0, base_score)

            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.warning("Failed to prioritize email %s: %s", email.email.id, e)
                email.unified_score = 0.5

        return emails

    async def get_sender_profile(
        self,
        sender_email: str,
    ) -> CrossAccountSenderProfile | None:
        """
        Get cross-account sender profile.

        Args:
            sender_email: Sender's email address

        Returns:
            CrossAccountSenderProfile or None
        """
        sender_key = sender_email.lower()

        async with self._profiles_lock:
            if sender_key in self._sender_profiles:
                return self._sender_profiles[sender_key]

        return None

    async def get_sender_importance(
        self,
        sender_email: str,
    ) -> dict[str, Any]:
        """
        Get sender importance analysis across all accounts.

        Args:
            sender_email: Sender's email address

        Returns:
            Dict with importance score and breakdown
        """
        profile = await self.get_sender_profile(sender_email.lower())

        if not profile:
            return {
                "sender_email": sender_email,
                "importance_score": 0.0,
                "account_count": 0,
                "is_known": False,
                "reasons": ["Sender not seen in any connected account"],
            }

        # Ensure importance is computed
        profile.compute_importance()

        return {
            "sender_email": sender_email,
            "importance_score": profile.cross_account_importance,
            "account_count": profile.account_count,
            "seen_in_accounts": list(profile.seen_in_accounts),
            "replied_from_accounts": list(profile.replied_from_accounts),
            "starred_in_accounts": list(profile.starred_in_accounts),
            "total_emails": profile.total_emails_received,
            "reply_rate": profile.reply_rate,
            "is_known": True,
            "reasons": profile.importance_reasons,
            "per_account_stats": profile.account_stats,
        }

    async def _update_sender_profiles(
        self,
        account_id: str,
        messages: list[Any],
    ) -> None:
        """Update sender profiles from synced messages."""
        async with self._profiles_lock:
            for msg in messages:
                # Extract sender
                sender = None
                if hasattr(msg, "from_address"):
                    sender = msg.from_address
                elif hasattr(msg, "metadata") and msg.metadata:
                    sender = msg.metadata.get("from", "")

                if not sender:
                    continue

                sender_key = sender.lower()

                # Get or create profile
                if sender_key not in self._sender_profiles:
                    self._sender_profiles[sender_key] = CrossAccountSenderProfile(
                        sender_email=sender_key,
                    )

                profile = self._sender_profiles[sender_key]

                # Update presence
                profile.seen_in_accounts.add(account_id)
                profile.total_emails_received += 1

                # Initialize per-account stats
                if account_id not in profile.account_stats:
                    profile.account_stats[account_id] = {
                        "received": 0,
                        "opened": 0,
                        "replied": 0,
                        "starred": 0,
                    }

                profile.account_stats[account_id]["received"] += 1

                # Check for starred
                labels: list[str] = []
                if hasattr(msg, "labels"):
                    labels = msg.labels or []
                elif hasattr(msg, "metadata") and msg.metadata:
                    labels = msg.metadata.get("labels", [])

                if "STARRED" in labels:
                    profile.starred_in_accounts.add(account_id)
                    profile.account_stats[account_id]["starred"] += 1

                # Recompute importance
                profile.compute_importance()

    async def record_action(
        self,
        account_id: str,
        email_id: str,
        sender_email: str,
        action: str,
    ) -> None:
        """
        Record a user action for learning.

        Args:
            account_id: Account where action occurred
            email_id: Email ID
            sender_email: Sender's email
            action: Action type (opened, replied, archived, deleted, starred)
        """
        sender_key = sender_email.lower()

        async with self._profiles_lock:
            if sender_key not in self._sender_profiles:
                self._sender_profiles[sender_key] = CrossAccountSenderProfile(
                    sender_email=sender_key,
                )

            profile = self._sender_profiles[sender_key]

            # Ensure account is tracked
            profile.seen_in_accounts.add(account_id)

            if account_id not in profile.account_stats:
                profile.account_stats[account_id] = {
                    "received": 0,
                    "opened": 0,
                    "replied": 0,
                    "starred": 0,
                }

            # Update based on action
            if action == "opened":
                profile.total_emails_opened += 1
                profile.account_stats[account_id]["opened"] += 1

            elif action == "replied":
                profile.total_emails_replied += 1
                profile.replied_from_accounts.add(account_id)
                profile.account_stats[account_id]["replied"] += 1

            elif action == "starred":
                profile.starred_in_accounts.add(account_id)
                profile.account_stats[account_id]["starred"] += 1

            # Recompute importance
            profile.compute_importance()

        # Also record in sender history if available
        if self.sender_history:
            try:
                await self.sender_history.record_interaction(
                    user_id=f"{self.user_id}:{account_id}",
                    sender_email=sender_email,
                    action=action,
                    email_id=email_id,
                )
            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.debug("Failed to record in sender history: %s", e)

    def get_stats(self) -> dict[str, Any]:
        """Get manager statistics."""
        return {
            "user_id": self.user_id,
            "account_count": len(self._accounts),
            "accounts": [a.to_dict() for a in self._accounts.values()],
            "known_senders": len(self._sender_profiles),
            "cross_account_senders": sum(
                1 for p in self._sender_profiles.values() if p.account_count > 1
            ),
        }


# Factory function
async def create_multi_inbox_manager(
    user_id: str = "default",
    accounts: list[dict[str, Any]] | None = None,
) -> MultiInboxManager:
    """
    Create and initialize a multi-inbox manager.

    Args:
        user_id: Owner user ID
        accounts: Optional list of account configs to add
            [{"account_id": "personal", "refresh_token": "...", "type": "personal"}, ...]

    Returns:
        Initialized MultiInboxManager
    """
    # Get prioritizer if available
    prioritizer = None
    try:
        from aragora.services.email_prioritization import EmailPrioritizer

        prioritizer = EmailPrioritizer()
    except ImportError:
        pass

    # Get sender history if available
    sender_history = None
    try:
        from aragora.services.sender_history import SenderHistoryService

        sender_history = SenderHistoryService()
        await sender_history.initialize()
    except ImportError:
        pass

    manager = MultiInboxManager(
        user_id=user_id,
        prioritizer=prioritizer,
        sender_history=sender_history,
    )

    # Add any initial accounts
    if accounts:
        for config in accounts:
            account_type = AccountType.OTHER
            if config.get("type"):
                try:
                    account_type = AccountType(config["type"])
                except ValueError as e:
                    logger.debug("multi_inbox_manager operation failed: %s", e)

            await manager.add_account(
                account_id=config["account_id"],
                refresh_token=config["refresh_token"],
                email_address=config.get("email_address"),
                account_type=account_type,
                is_primary=config.get("is_primary", False),
                priority_weight=config.get("priority_weight", 1.0),
            )

    return manager
