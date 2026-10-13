"""Inbox email service integration methods (InboxServicesMixin).

Extracted from inbox_command.py to reduce file size.
Contains email fetching, prioritization, stats, and reprioritization.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.connectors.gmail import GmailConnector
    from aragora.server.handlers.inbox.inbox_command import EmailPrioritizer
    from aragora.services.sender_history import SenderHistoryService

logger = logging.getLogger(__name__)


class InboxServicesMixin:
    """Mixin providing inbox email service integration methods."""

    # Stub attributes expected from the composing class
    gmail_connector: GmailConnector | None
    prioritizer: EmailPrioritizer | None
    sender_history: SenderHistoryService | None

    async def _fetch_prioritized_emails(
        self,
        limit: int,
        offset: int,
        priority_filter: str | None,
        unread_only: bool,
    ) -> list[dict[str, Any]]:
        """Fetch and prioritize emails using the EmailPrioritizer service."""
        from .inbox_command import _email_cache

        # If no Gmail connector, return demo data
        if self.gmail_connector is None:
            return self._get_demo_emails(limit, offset, priority_filter)

        try:
            # Fetch emails from Gmail
            emails: list[Any] = []
            fetch_limit = limit + offset + 50  # Fetch extra for filtering

            # Use list_messages instead of sync_items for inbox fetching
            messages = await self.gmail_connector.list_messages(max_results=fetch_limit)
            for msg in messages:
                if len(emails) >= fetch_limit:
                    break
                emails.append(msg)

            if not emails:
                return []

            # Prioritize emails
            if self.prioritizer:
                results = await self.prioritizer.rank_inbox(emails, limit=fetch_limit)

                # Convert to response format
                prioritized = []
                for result in results:
                    # Find the original email
                    email_data = next(
                        (e for e in emails if getattr(e, "id", None) == result.email_id),
                        None,
                    )

                    entry = {
                        "id": result.email_id,
                        "from": (
                            getattr(email_data, "from_address", "unknown")
                            if email_data
                            else "unknown"
                        ),
                        "subject": (
                            getattr(email_data, "subject", "No subject")
                            if email_data
                            else "No subject"
                        ),
                        "snippet": getattr(email_data, "snippet", "")[:200] if email_data else "",
                        "priority": result.priority.name.lower(),
                        "confidence": result.confidence,
                        "reasoning": result.rationale,
                        "tier_used": result.tier_used.value,
                        "scores": {
                            "sender": result.sender_score,
                            "urgency": result.content_urgency_score,
                            "context": result.context_relevance_score,
                            "time_sensitivity": result.time_sensitivity_score,
                        },
                        "suggested_labels": result.suggested_labels,
                        "auto_archive": result.auto_archive,
                        "timestamp": (
                            getattr(email_data, "date", datetime.now(timezone.utc)).isoformat()
                            if email_data
                            else datetime.now(timezone.utc).isoformat()
                        ),
                        "unread": getattr(email_data, "unread", True) if email_data else True,
                    }

                    # Apply filters
                    if priority_filter and entry["priority"] != priority_filter.lower():
                        continue
                    if unread_only and not entry["unread"]:
                        continue

                    prioritized.append(entry)

                    # Cache for bulk operations
                    _email_cache[result.email_id] = entry

                # Apply pagination
                return prioritized[offset : offset + limit]
            else:
                # No prioritizer - return basic list
                return [
                    {
                        "id": getattr(e, "id", f"email_{i}"),
                        "from": getattr(e, "from_address", "unknown"),
                        "subject": getattr(e, "subject", "No subject"),
                        "snippet": getattr(e, "snippet", "")[:200],
                        "priority": "medium",
                        "confidence": 0.5,
                        "timestamp": getattr(e, "date", datetime.now(timezone.utc)).isoformat(),
                        "unread": getattr(e, "unread", True),
                    }
                    for i, e in enumerate(emails[offset : offset + limit])
                ]

        except (OSError, ConnectionError, RuntimeError, ValueError, AttributeError) as e:
            logger.warning("Failed to fetch from Gmail, using demo data: %s", e)
            return self._get_demo_emails(limit, offset, priority_filter)

    def _get_demo_emails(
        self,
        limit: int,
        offset: int,
        priority_filter: str | None,
    ) -> list[dict[str, Any]]:
        """Return demo email data when services aren't available."""
        from .inbox_command import _email_cache

        demo_emails = [
            {
                "id": "demo_1",
                "from": "ceo@company.com",
                "subject": "Q4 Strategy Review - Urgent Response Needed",
                "snippet": "Please review the attached strategy document and provide your feedback by EOD...",
                "priority": "critical",
                "confidence": 0.95,
                "reasoning": "VIP sender; deadline detected; reply expected",
                "tier_used": "tier_1_rules",
                "category": "Work",
                "timestamp": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "unread": True,
            },
            {
                "id": "demo_2",
                "from": "client@bigcorp.com",
                "subject": "Contract renewal discussion",
                "snippet": "Following up on our conversation about the contract renewal. Can we schedule a call?",
                "priority": "high",
                "confidence": 0.85,
                "reasoning": "Client sender; reply expected",
                "tier_used": "tier_1_rules",
                "category": "Work",
                "timestamp": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
                "unread": True,
            },
            {
                "id": "demo_3",
                "from": "notifications@github.com",
                "subject": "[aragora] PR #142: Fix memory leak in debate engine",
                "snippet": "A new pull request has been opened by contributor...",
                "priority": "medium",
                "confidence": 0.75,
                "reasoning": "Automated notification; work-related",
                "tier_used": "tier_1_rules",
                "category": "Updates",
                "timestamp": (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat(),
                "unread": True,
            },
            {
                "id": "demo_4",
                "from": "newsletter@techblog.com",
                "subject": "This week in AI: Top stories and insights",
                "snippet": "Unsubscribe | View in browser. This week's top AI stories include...",
                "priority": "defer",
                "confidence": 0.92,
                "reasoning": "Newsletter detected; auto-archive candidate",
                "tier_used": "tier_1_rules",
                "category": "Newsletter",
                "timestamp": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                "unread": False,
                "auto_archive": True,
            },
            {
                "id": "demo_5",
                "from": "team@company.com",
                "subject": "Weekly standup notes",
                "snippet": "Here are the notes from this week's standup meeting...",
                "priority": "low",
                "confidence": 0.8,
                "reasoning": "Internal sender; informational",
                "tier_used": "tier_1_rules",
                "category": "Work",
                "timestamp": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                "unread": False,
            },
        ]

        # Populate cache for bulk actions to work in demo mode
        for email in demo_emails:
            _email_cache[str(email["id"])] = email

        # Apply filters
        if priority_filter:
            demo_emails = [e for e in demo_emails if e["priority"] == priority_filter.lower()]

        return demo_emails[offset : offset + limit]

    async def _calculate_inbox_stats(
        self,
        emails: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Calculate inbox statistics from prioritized emails."""
        total = len(emails)

        # Count by priority
        priority_counts = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "defer": 0,
        }

        for email in emails:
            priority = email.get("priority", "medium").lower()
            if priority in priority_counts:
                priority_counts[priority] += 1

        # Count unread
        unread_count = sum(1 for e in emails if e.get("unread", False))

        return {
            "total": total,
            "unread": unread_count,
            "critical": priority_counts["critical"],
            "high": priority_counts["high"],
            "medium": priority_counts["medium"],
            "low": priority_counts["low"],
            "deferred": priority_counts["defer"],
            "actionRequired": priority_counts["critical"] + priority_counts["high"],
        }

    async def _get_sender_profile(self, email: str) -> dict[str, Any]:
        """Get sender profile information from SenderHistoryService."""
        if self.sender_history:
            try:
                stats = await self.sender_history.get_sender_stats(
                    user_id="default",
                    sender_email=email,
                )
                if stats:
                    avg_hours = (
                        stats.avg_response_time_minutes / 60.0
                        if stats.avg_response_time_minutes
                        else None
                    )
                    return {
                        "email": email,
                        "name": email.split("@")[0],
                        "isVip": stats.is_vip,
                        "isInternal": False,
                        "responseRate": stats.reply_rate,
                        "avgResponseTime": f"{avg_hours:.1f}h" if avg_hours else "N/A",
                        "totalEmails": stats.total_emails,
                        "lastContact": (
                            stats.last_email_date.strftime("%Y-%m-%d")
                            if stats.last_email_date
                            else "Never"
                        ),
                    }
            except (OSError, ConnectionError, RuntimeError, ValueError, AttributeError) as e:
                logger.warning("Failed to get sender stats: %s", e)

        # Check prioritizer config for VIP status
        is_vip = False
        if self.prioritizer:
            is_vip = email.lower() in {a.lower() for a in self.prioritizer.config.vip_addresses}
            domain = email.split("@")[-1] if "@" in email else ""
            is_vip = is_vip or domain.lower() in {
                d.lower() for d in self.prioritizer.config.vip_domains
            }

        # Return basic profile
        return {
            "email": email,
            "name": email.split("@")[0],
            "isVip": is_vip,
            "isInternal": False,
            "responseRate": 0.0,
            "avgResponseTime": "N/A",
            "totalEmails": 0,
            "lastContact": "Unknown",
        }

    async def _calculate_daily_digest(self) -> dict[str, Any]:
        """Calculate daily digest statistics."""
        from .inbox_command import _email_cache

        # Try to get real stats from sender history (if method exists)
        if self.sender_history and hasattr(self.sender_history, "get_daily_summary"):
            try:
                # hasattr check above confirms get_daily_summary exists at runtime
                get_summary_fn: Callable[..., Any] = getattr(
                    self.sender_history, "get_daily_summary"
                )
                today_stats: dict[str, Any] | None = await get_summary_fn(user_id="default")
                if today_stats:
                    return today_stats
            except (OSError, ConnectionError, RuntimeError, ValueError, AttributeError) as e:
                logger.debug("Daily summary not available: %s", e)

        # Use cached data stats
        emails_in_cache = list(_email_cache.values())
        critical_count = sum(1 for e in emails_in_cache if e.get("priority") == "critical")

        # Compute top senders from cache
        sender_counts: dict[str, int] = {}
        for email in emails_in_cache:
            sender = email.get("from", "unknown")
            sender_counts[sender] = sender_counts.get(sender, 0) + 1

        sender_list: list[dict[str, Any]] = [
            {"name": k, "count": v} for k, v in sender_counts.items()
        ]
        top_senders = sorted(
            sender_list,
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        # Compute category breakdown
        category_counts: dict[str, int] = {}
        for email in emails_in_cache:
            category = email.get("category", "General")
            category_counts[category] = category_counts.get(category, 0) + 1

        total = len(emails_in_cache) or 1  # Avoid division by zero
        category_breakdown = [
            {
                "category": cat,
                "count": count,
                "percentage": round(count / total * 100),
            }
            for cat, count in sorted(category_counts.items(), key=lambda x: -x[1])
        ]

        return {
            "emailsReceived": len(emails_in_cache),
            "emailsProcessed": len(emails_in_cache),
            "criticalHandled": critical_count,
            "timeSaved": f"{len(emails_in_cache) * 2} min",  # Estimate 2 min saved per email
            "topSenders": top_senders
            or [
                {"name": "team@company.com", "count": 0},
            ],
            "categoryBreakdown": category_breakdown
            or [
                {"category": "General", "count": 0, "percentage": 100},
            ],
        }

    async def _reprioritize_emails(
        self,
        email_ids: list[str] | None,
        force_tier: str | None = None,
    ) -> dict[str, Any]:
        """
        Reprioritize emails using AI.

        Uses batch operations to avoid N+1 query patterns:
        1. Batch fetch emails using gmail_connector.get_messages()
        2. Batch score using prioritizer.score_emails() (loads sender profiles once)
        """
        from aragora.services.email_prioritization import ScoringTier

        from .inbox_command import _email_cache

        if not self.prioritizer:
            return {
                "count": 0,
                "changes": [],
                "error": "Prioritizer not available",
            }

        # Get emails to reprioritize
        if email_ids:
            emails_to_process = [
                (eid, _email_cache.get(eid)) for eid in email_ids if eid in _email_cache
            ]
        else:
            emails_to_process = list(_email_cache.items())

        if not emails_to_process:
            return {"count": 0, "changes": []}

        # Map force_tier string to ScoringTier enum
        tier_map = {
            "tier_1_rules": ScoringTier.TIER_1_RULES,
            "tier_2_lightweight": ScoringTier.TIER_2_LIGHTWEIGHT,
            "tier_3_debate": ScoringTier.TIER_3_DEBATE,
        }
        scoring_tier = tier_map.get(force_tier) if force_tier else None

        changes: list[dict[str, Any]] = []
        processed_count = 0

        # Build map of email_id -> cached_email for quick lookup
        cache_map = {eid: cached for eid, cached in emails_to_process if cached}
        email_ids_to_fetch = list(cache_map.keys())

        if not email_ids_to_fetch:
            return {"count": 0, "changes": []}

        # Batch fetch emails from Gmail if connector available
        # This reduces N individual get_message() calls to 1 batch call
        email_messages = []
        if self.gmail_connector:
            try:
                email_messages = await self.gmail_connector.get_messages(email_ids_to_fetch)
            except (OSError, ConnectionError, RuntimeError, AttributeError) as e:
                logger.warning("Batch email fetch failed: %s", e)
                # Fall back to individual fetches on batch failure
                for eid in email_ids_to_fetch:
                    try:
                        msg = await self.gmail_connector.get_message(eid)
                        if msg:
                            email_messages.append(msg)
                    except (OSError, ConnectionError, RuntimeError, AttributeError) as fetch_err:
                        logger.debug("Could not fetch email %s: %s", eid, fetch_err)

        if not email_messages:
            # No Gmail connector or all fetches failed
            return {
                "count": len(email_ids_to_fetch),
                "changes": [],
                "tier_used": force_tier or "auto",
            }

        # Batch score all emails at once
        # This loads sender profiles in bulk (1-2 queries instead of N)
        try:
            results = await self.prioritizer.score_emails(email_messages, force_tier=scoring_tier)
        except (ValueError, RuntimeError, OSError, ConnectionError, AttributeError) as e:
            logger.warning("Batch scoring failed: %s", e)
            return {
                "count": 0,
                "changes": [],
                "error": "Batch scoring failed",
            }

        # Process results and update cache
        for email_msg, result in zip(email_messages, results):
            email_id = email_msg.id
            cached_email = cache_map.get(email_id)
            if not cached_email:
                processed_count += 1
                continue

            old_priority = cached_email.get("priority", "medium")
            old_confidence = cached_email.get("confidence", 0.5)

            new_priority = result.priority.name.lower()
            new_confidence = result.confidence

            # Update cache (get, modify, set pattern for TTL cache)
            updated_email = dict(cached_email)
            updated_email.update(
                {
                    "priority": new_priority,
                    "confidence": new_confidence,
                    "reasoning": result.rationale,
                    "tier_used": result.tier_used.value,
                    "scores": {
                        "sender": result.sender_score,
                        "urgency": result.content_urgency_score,
                        "context": result.context_relevance_score,
                        "time_sensitivity": result.time_sensitivity_score,
                    },
                    "suggested_labels": result.suggested_labels,
                    "auto_archive": result.auto_archive,
                }
            )
            _email_cache.set(email_id, updated_email)

            # Track if priority changed
            if old_priority != new_priority:
                changes.append(
                    {
                        "email_id": email_id,
                        "old_priority": old_priority,
                        "new_priority": new_priority,
                        "old_confidence": old_confidence,
                        "new_confidence": new_confidence,
                        "tier_used": result.tier_used.value,
                    }
                )

            processed_count += 1

        return {
            "count": processed_count,
            "changes": changes,
            "tier_used": force_tier or "auto",
        }
