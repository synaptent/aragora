"""
UsageRepository - Usage tracking and rate limiting operations.

Extracted from UserStore for better modularity. Manages debate usage
counting, usage events, and monthly reset operations.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from contextlib import AbstractContextManager
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.billing.models import Organization

logger = logging.getLogger(__name__)


class UsageRepository:
    """
    Repository for usage tracking operations.

    This class manages:
    - Debate usage counting per organization
    - Usage event recording for analytics
    - Monthly usage resets
    - Usage summary generation
    """

    # Explicit columns for SELECT queries - prevents SELECT * data exposure
    _USAGE_EVENT_COLUMNS = "id, org_id, event_type, count, metadata, created_at"

    def __init__(
        self,
        transaction_fn: Callable[[], AbstractContextManager[sqlite3.Cursor]],
        get_org_fn: Callable[[str], Organization | None] | None = None,
    ) -> None:
        """
        Initialize the usage repository.

        Args:
            transaction_fn: Function that returns a transaction context manager.
            get_org_fn: Optional function to get organization by ID (for summary).
        """
        self._transaction = transaction_fn
        self._get_org = get_org_fn

    def increment(self, org_id: str, count: int = 1) -> int:
        """
        Increment debate usage for an organization.

        Args:
            org_id: Organization ID
            count: Number of debates to add

        Returns:
            New total debates used this month
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE organizations
                SET debates_used_this_month = debates_used_this_month + ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (count, datetime.now(timezone.utc).isoformat(), org_id),
            )
            cursor.execute(
                "SELECT debates_used_this_month FROM organizations WHERE id = ?",
                (org_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def record_event(
        self,
        org_id: str,
        event_type: str,
        count: int = 1,
        metadata: dict | None = None,
    ) -> None:
        """
        Record a usage event for analytics.

        Args:
            org_id: Organization ID
            event_type: Type of event (e.g., 'debate', 'api_call')
            count: Count for the event
            metadata: Optional additional data
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO usage_events (org_id, event_type, count, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    org_id,
                    event_type,
                    count,
                    json.dumps(metadata or {}),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def reset_all_monthly(self) -> int:
        """
        Reset monthly usage for all organizations.

        Returns:
            Number of organizations reset
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE organizations
                SET debates_used_this_month = 0,
                    billing_cycle_start = ?,
                    updated_at = ?
                """,
                (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
            )
            return cursor.rowcount

    def reset_org(self, org_id: str) -> bool:
        """
        Reset monthly usage for a specific organization.

        Args:
            org_id: Organization ID

        Returns:
            True if reset was successful
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE organizations
                SET debates_used_this_month = 0,
                    billing_cycle_start = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    org_id,
                ),
            )
            return cursor.rowcount > 0

    def get_summary(self, org_id: str) -> dict[str, Any]:
        """
        Get usage summary for an organization.

        Args:
            org_id: Organization ID

        Returns:
            Dict with usage details, or empty dict if org not found
        """
        if self._get_org is None:
            # Fall back to raw query if no org getter provided
            with self._transaction() as cursor:
                cursor.execute(
                    """
                    SELECT tier, debates_used_this_month, billing_cycle_start
                    FROM organizations WHERE id = ?
                    """,
                    (org_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return {}
                return {
                    "org_id": org_id,
                    "tier": row[0],
                    "debates_used": row[1],
                    "billing_cycle_start": row[2],
                }

        org = self._get_org(org_id)
        if not org:
            return {}

        return {
            "org_id": org_id,
            "tier": org.tier.value,
            "debates_used": org.debates_used_this_month,
            "debates_limit": org.limits.debates_per_month,
            "debates_remaining": org.debates_remaining,
            "is_at_limit": org.is_at_limit,
            "billing_cycle_start": org.billing_cycle_start.isoformat(),
        }

    def get_events(
        self,
        org_id: str,
        event_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get usage events for an organization.

        Args:
            org_id: Organization ID
            event_type: Optional filter by event type
            since: Optional filter by date
            limit: Maximum number of events to return

        Returns:
            List of usage event dicts
        """
        # column name interpolation, parameterized
        query = f"SELECT {self._USAGE_EVENT_COLUMNS} FROM usage_events WHERE org_id = ?"
        params: list[Any] = [org_id]

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        if since:
            query += " AND created_at >= ?"
            params.append(since.isoformat())

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._transaction() as cursor:
            cursor.execute(query, params)
            return [
                {
                    "id": row["id"],
                    "org_id": row["org_id"],
                    "event_type": row["event_type"],
                    "count": row["count"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "created_at": row["created_at"],
                }
                for row in cursor.fetchall()
            ]

    def get_totals_by_type(
        self,
        org_id: str,
        since: datetime | None = None,
    ) -> dict[str, int]:
        """
        Get total counts grouped by event type.

        Args:
            org_id: Organization ID
            since: Optional filter by date

        Returns:
            Dict mapping event_type to total count
        """
        query = """
            SELECT event_type, SUM(count) as total
            FROM usage_events
            WHERE org_id = ?
        """
        params: list[Any] = [org_id]

        if since:
            query += " AND created_at >= ?"
            params.append(since.isoformat())

        query += " GROUP BY event_type"

        with self._transaction() as cursor:
            cursor.execute(query, params)
            return {row["event_type"]: row["total"] for row in cursor.fetchall()}
