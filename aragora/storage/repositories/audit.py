"""
AuditRepository - Audit logging for billing and security compliance.

Extracted from UserStore for better modularity. Provides audit trail
for all significant actions in the system.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable


class AuditRepository:
    """
    Repository for audit logging operations.

    Provides a comprehensive audit trail for:
    - Subscription changes
    - User profile updates
    - Organization membership changes
    - Security events (login failures, lockouts)
    - Billing events (payments, invoices)
    """

    def __init__(
        self, transaction_fn: Callable[[], AbstractContextManager[sqlite3.Cursor]]
    ) -> None:
        """
        Initialize the audit repository.

        Args:
            transaction_fn: Function that returns a transaction context manager
                           with a cursor.
        """
        self._transaction = transaction_fn

    def log_event(
        self,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """
        Log an audit event.

        Args:
            action: Action performed (e.g., 'subscription.created', 'tier.changed')
            resource_type: Type of resource (e.g., 'subscription', 'user', 'organization')
            resource_id: ID of the affected resource
            user_id: User who performed the action
            org_id: Organization context
            old_value: Previous value (for changes)
            new_value: New value (for changes)
            metadata: Additional context
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            Audit log entry ID
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_log
                (timestamp, user_id, org_id, action, resource_type, resource_id,
                 old_value, new_value, metadata, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    user_id,
                    org_id,
                    action,
                    resource_type,
                    resource_id,
                    json.dumps(old_value) if old_value else None,
                    json.dumps(new_value) if new_value else None,
                    json.dumps(metadata or {}),
                    ip_address,
                    user_agent,
                ),
            )
            # lastrowid is guaranteed to be set after INSERT
            if cursor.lastrowid is None:
                raise RuntimeError("INSERT did not return a row ID")
            return cursor.lastrowid

    def get_log(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        Query audit log entries.

        Args:
            org_id: Filter by organization
            user_id: Filter by user
            action: Filter by action (supports prefix match with *)
            resource_type: Filter by resource type
            since: Filter entries after this time
            until: Filter entries before this time
            limit: Maximum entries to return
            offset: Pagination offset

        Returns:
            List of audit log entries
        """
        conditions: list[str] = []
        params: list[Any] = []

        if org_id:
            conditions.append("org_id = ?")
            params.append(org_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if action:
            if action.endswith("*"):
                conditions.append("action LIKE ?")
                params.append(action[:-1] + "%")
            else:
                conditions.append("action = ?")
                params.append(action)
        if resource_type:
            conditions.append("resource_type = ?")
            params.append(resource_type)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since.isoformat())
        if until:
            conditions.append("timestamp <= ?")
            params.append(until.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        with self._transaction() as cursor:
            query = f"""
                SELECT id, timestamp, user_id, org_id, action, resource_type,
                       resource_id, old_value, new_value, metadata, ip_address, user_agent
                FROM audit_log
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """  # nosec B608 - where_clause built from hardcoded conditions
            cursor.execute(query, params)
            return [
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "user_id": row[2],
                    "org_id": row[3],
                    "action": row[4],
                    "resource_type": row[5],
                    "resource_id": row[6],
                    "old_value": json.loads(row[7]) if row[7] else None,
                    "new_value": json.loads(row[8]) if row[8] else None,
                    "metadata": json.loads(row[9]) if row[9] else {},
                    "ip_address": row[10],
                    "user_agent": row[11],
                }
                for row in cursor.fetchall()
            ]

    def get_log_count(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> int:
        """Get count of audit log entries matching filters."""
        conditions: list[str] = []
        params: list[Any] = []

        if org_id:
            conditions.append("org_id = ?")
            params.append(org_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if action:
            if action.endswith("*"):
                conditions.append("action LIKE ?")
                params.append(action[:-1] + "%")
            else:
                conditions.append("action = ?")
                params.append(action)
        if resource_type:
            conditions.append("resource_type = ?")
            params.append(resource_type)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._transaction() as cursor:
            query = f"SELECT COUNT(*) FROM audit_log WHERE {where_clause}"  # nosec B608
            cursor.execute(query, params)
            return cursor.fetchone()[0]
