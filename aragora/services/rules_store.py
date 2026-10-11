"""
Persistent Storage for Routing Rules.

Provides SQLite-backed storage for inbox routing rules with:
- CRUD operations for rules
- Workspace-level isolation
- Rule statistics tracking
- Efficient querying by workspace/inbox
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from collections.abc import Generator

from aragora.config import resolve_db_path

logger = logging.getLogger(__name__)

# Default database location
DEFAULT_DB_PATH = resolve_db_path("rules.db")


class RulesStore:
    """
    SQLite-backed persistent storage for routing rules.

    Context-safe with connection pooling per context.
    """

    _conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
        "rules_store_conn", default=None
    )

    def __init__(self, db_path: str | None = None):
        """
        Initialize the rules store.

        Args:
            db_path: Path to SQLite database file. Defaults to ARAGORA_DATA_DIR/rules.db
        """
        self.db_path = resolve_db_path(db_path or DEFAULT_DB_PATH)
        self._connections: list[sqlite3.Connection] = []
        self._init_lock = threading.Lock()
        self._initialized = False

        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get context-local database connection."""
        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
            )
            conn.row_factory = sqlite3.Row
            # Enable foreign keys
            conn.execute("PRAGMA foreign_keys = ON")
            self._conn_var.set(conn)
            self._connections.append(conn)
        return conn

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager for database cursor with auto-commit."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:  # noqa: BLE001 - Intentional: rollback transaction before re-raising any error
            conn.rollback()
            raise
        finally:
            cursor.close()

    def _ensure_schema(self) -> None:
        """Create database schema if not exists."""
        if self._initialized:
            return

        with self._init_lock:
            if self._initialized:
                return

            with self._cursor() as cursor:
                # Routing rules table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS routing_rules (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        inbox_id TEXT,
                        conditions TEXT NOT NULL,
                        condition_logic TEXT NOT NULL DEFAULT 'AND',
                        actions TEXT NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 5,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        description TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        created_by TEXT,
                        stats TEXT DEFAULT '{}'
                    )
                """)

                # Indexes for efficient querying
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rules_workspace
                    ON routing_rules(workspace_id)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rules_inbox
                    ON routing_rules(inbox_id)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rules_enabled
                    ON routing_rules(enabled, priority)
                """)

                # Shared inboxes table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS shared_inboxes (
                        id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        description TEXT,
                        email_address TEXT,
                        connector_type TEXT,
                        team_members TEXT DEFAULT '[]',
                        admins TEXT DEFAULT '[]',
                        settings TEXT DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        created_by TEXT,
                        message_count INTEGER DEFAULT 0,
                        unread_count INTEGER DEFAULT 0
                    )
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_inboxes_workspace
                    ON shared_inboxes(workspace_id)
                """)

                # Inbox messages table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS inbox_messages (
                        id TEXT PRIMARY KEY,
                        inbox_id TEXT NOT NULL,
                        email_id TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        from_address TEXT NOT NULL,
                        to_addresses TEXT NOT NULL,
                        snippet TEXT,
                        received_at TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'open',
                        assigned_to TEXT,
                        assigned_at TEXT,
                        tags TEXT DEFAULT '[]',
                        priority TEXT,
                        notes TEXT DEFAULT '[]',
                        thread_id TEXT,
                        sla_deadline TEXT,
                        resolved_at TEXT,
                        resolved_by TEXT,
                        FOREIGN KEY (inbox_id) REFERENCES shared_inboxes(id)
                    )
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_messages_inbox
                    ON inbox_messages(inbox_id)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_messages_status
                    ON inbox_messages(status)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_messages_assigned
                    ON inbox_messages(assigned_to)
                """)

            self._initialized = True
            logger.info("[RulesStore] Initialized database at %s", self.db_path)

    # =========================================================================
    # Routing Rules CRUD
    # =========================================================================

    def create_rule(self, rule_data: dict[str, Any]) -> dict[str, Any]:
        """
        Create a new routing rule.

        Args:
            rule_data: Rule data including id, name, workspace_id, conditions, actions

        Returns:
            Created rule data
        """
        now = datetime.now(timezone.utc).isoformat()

        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO routing_rules (
                    id, name, workspace_id, inbox_id, conditions, condition_logic,
                    actions, priority, enabled, description, created_at, updated_at,
                    created_by, stats
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    rule_data["id"],
                    rule_data["name"],
                    rule_data["workspace_id"],
                    rule_data.get("inbox_id"),
                    json.dumps(rule_data.get("conditions", [])),
                    rule_data.get("condition_logic", "AND"),
                    json.dumps(rule_data.get("actions", [])),
                    rule_data.get("priority", 5),
                    1 if rule_data.get("enabled", True) else 0,
                    rule_data.get("description"),
                    rule_data.get("created_at", now),
                    rule_data.get("updated_at", now),
                    rule_data.get("created_by"),
                    json.dumps(rule_data.get("stats", {})),
                ),
            )

        logger.info("[RulesStore] Created rule %s: %s", rule_data["id"], rule_data["name"])
        return rule_data

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        """Get a rule by ID."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM routing_rules WHERE id = ?", (rule_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_rule(row)
        return None

    def update_rule(self, rule_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """
        Update a routing rule.

        Args:
            rule_id: Rule ID to update
            updates: Dictionary of fields to update

        Returns:
            Updated rule data or None if not found
        """
        existing = self.get_rule(rule_id)
        if not existing:
            return None

        # Merge updates
        for key, value in updates.items():
            existing[key] = value
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()

        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE routing_rules SET
                    name = ?,
                    conditions = ?,
                    condition_logic = ?,
                    actions = ?,
                    priority = ?,
                    enabled = ?,
                    description = ?,
                    updated_at = ?,
                    stats = ?
                WHERE id = ?
            """,
                (
                    existing["name"],
                    json.dumps(existing.get("conditions", [])),
                    existing.get("condition_logic", "AND"),
                    json.dumps(existing.get("actions", [])),
                    existing.get("priority", 5),
                    1 if existing.get("enabled", True) else 0,
                    existing.get("description"),
                    existing["updated_at"],
                    json.dumps(existing.get("stats", {})),
                    rule_id,
                ),
            )

        logger.info("[RulesStore] Updated rule %s", rule_id)
        return existing

    def delete_rule(self, rule_id: str) -> bool:
        """Delete a routing rule."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM routing_rules WHERE id = ?", (rule_id,))
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("[RulesStore] Deleted rule %s", rule_id)
        return deleted

    def list_rules(
        self,
        workspace_id: str | None = None,
        inbox_id: str | None = None,
        enabled_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List routing rules with optional filtering.

        Args:
            workspace_id: Filter by workspace
            inbox_id: Filter by inbox
            enabled_only: Only return enabled rules
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of rule dictionaries
        """
        conditions = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if inbox_id:
            conditions.append("(inbox_id = ? OR inbox_id IS NULL)")
            params.append(inbox_id)
        if enabled_only:
            conditions.append("enabled = 1")

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM routing_rules
                WHERE {where_clause}
                ORDER BY priority ASC, created_at DESC
                LIMIT ? OFFSET ?
            """,  # dynamic clause from internal state
                params,
            )
            rows = cursor.fetchall()

        return [self._row_to_rule(row) for row in rows]

    def count_rules(
        self,
        workspace_id: str | None = None,
        inbox_id: str | None = None,
        enabled_only: bool = False,
    ) -> int:
        """Count rules matching filter criteria."""
        conditions = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if inbox_id:
            conditions.append("(inbox_id = ? OR inbox_id IS NULL)")
            params.append(inbox_id)
        if enabled_only:
            conditions.append("enabled = 1")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._cursor() as cursor:
            cursor.execute(
                # dynamic clause from internal state
                f"SELECT COUNT(*) FROM routing_rules WHERE {where_clause}",
                params,
            )
            return cursor.fetchone()[0]

    def increment_rule_stats(
        self,
        rule_id: str,
        matched: int = 0,
        applied: int = 0,
    ) -> None:
        """Increment rule match/apply statistics."""
        rule = self.get_rule(rule_id)
        if not rule:
            return

        stats = rule.get("stats", {})
        stats["matched"] = stats.get("matched", 0) + matched
        stats["applied"] = stats.get("applied", 0) + applied
        stats["last_matched"] = datetime.now(timezone.utc).isoformat()

        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE routing_rules SET stats = ? WHERE id = ?",
                (json.dumps(stats), rule_id),
            )

    # =========================================================================
    # Shared Inboxes CRUD
    # =========================================================================

    def create_inbox(self, inbox_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new shared inbox."""
        now = datetime.now(timezone.utc).isoformat()

        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO shared_inboxes (
                    id, workspace_id, name, description, email_address, connector_type,
                    team_members, admins, settings, created_at, updated_at, created_by,
                    message_count, unread_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    inbox_data["id"],
                    inbox_data["workspace_id"],
                    inbox_data["name"],
                    inbox_data.get("description"),
                    inbox_data.get("email_address"),
                    inbox_data.get("connector_type"),
                    json.dumps(inbox_data.get("team_members", [])),
                    json.dumps(inbox_data.get("admins", [])),
                    json.dumps(inbox_data.get("settings", {})),
                    inbox_data.get("created_at", now),
                    inbox_data.get("updated_at", now),
                    inbox_data.get("created_by"),
                    inbox_data.get("message_count", 0),
                    inbox_data.get("unread_count", 0),
                ),
            )

        logger.info("[RulesStore] Created inbox %s: %s", inbox_data["id"], inbox_data["name"])
        return inbox_data

    def get_inbox(self, inbox_id: str) -> dict[str, Any] | None:
        """Get an inbox by ID."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM shared_inboxes WHERE id = ?", (inbox_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_inbox(row)
        return None

    def update_inbox(self, inbox_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update an inbox."""
        existing = self.get_inbox(inbox_id)
        if not existing:
            return None

        for key, value in updates.items():
            existing[key] = value
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()

        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE shared_inboxes SET
                    name = ?, description = ?, email_address = ?, connector_type = ?,
                    team_members = ?, admins = ?, settings = ?, updated_at = ?,
                    message_count = ?, unread_count = ?
                WHERE id = ?
            """,
                (
                    existing["name"],
                    existing.get("description"),
                    existing.get("email_address"),
                    existing.get("connector_type"),
                    json.dumps(existing.get("team_members", [])),
                    json.dumps(existing.get("admins", [])),
                    json.dumps(existing.get("settings", {})),
                    existing["updated_at"],
                    existing.get("message_count", 0),
                    existing.get("unread_count", 0),
                    inbox_id,
                ),
            )

        return existing

    def delete_inbox(self, inbox_id: str) -> bool:
        """Delete an inbox and its messages."""
        with self._cursor() as cursor:
            # Delete messages first
            cursor.execute("DELETE FROM inbox_messages WHERE inbox_id = ?", (inbox_id,))
            # Delete inbox
            cursor.execute("DELETE FROM shared_inboxes WHERE id = ?", (inbox_id,))
            return cursor.rowcount > 0

    def list_inboxes(
        self,
        workspace_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List inboxes with optional workspace filter."""
        if workspace_id:
            with self._cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM shared_inboxes
                    WHERE workspace_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """,
                    (workspace_id, limit, offset),
                )
                rows = cursor.fetchall()
        else:
            with self._cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM shared_inboxes ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
                rows = cursor.fetchall()

        return [self._row_to_inbox(row) for row in rows]

    # =========================================================================
    # Inbox Messages CRUD
    # =========================================================================

    def create_message(self, message_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new inbox message."""
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO inbox_messages (
                    id, inbox_id, email_id, subject, from_address, to_addresses,
                    snippet, received_at, status, assigned_to, assigned_at, tags,
                    priority, notes, thread_id, sla_deadline, resolved_at, resolved_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    message_data["id"],
                    message_data["inbox_id"],
                    message_data["email_id"],
                    message_data["subject"],
                    message_data["from_address"],
                    json.dumps(message_data.get("to_addresses", [])),
                    message_data.get("snippet", ""),
                    message_data["received_at"],
                    message_data.get("status", "open"),
                    message_data.get("assigned_to"),
                    message_data.get("assigned_at"),
                    json.dumps(message_data.get("tags", [])),
                    message_data.get("priority"),
                    json.dumps(message_data.get("notes", [])),
                    message_data.get("thread_id"),
                    message_data.get("sla_deadline"),
                    message_data.get("resolved_at"),
                    message_data.get("resolved_by"),
                ),
            )

            # Update inbox message count
            cursor.execute(
                "UPDATE shared_inboxes SET message_count = message_count + 1 WHERE id = ?",
                (message_data["inbox_id"],),
            )

        return message_data

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Get a message by ID."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM inbox_messages WHERE id = ?", (message_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_message(row)
        return None

    def update_message(self, message_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update a message."""
        existing = self.get_message(message_id)
        if not existing:
            return None

        for key, value in updates.items():
            existing[key] = value

        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE inbox_messages SET
                    status = ?, assigned_to = ?, assigned_at = ?, tags = ?,
                    priority = ?, notes = ?, sla_deadline = ?, resolved_at = ?, resolved_by = ?
                WHERE id = ?
            """,
                (
                    existing.get("status", "open"),
                    existing.get("assigned_to"),
                    existing.get("assigned_at"),
                    json.dumps(existing.get("tags", [])),
                    existing.get("priority"),
                    json.dumps(existing.get("notes", [])),
                    existing.get("sla_deadline"),
                    existing.get("resolved_at"),
                    existing.get("resolved_by"),
                    message_id,
                ),
            )

        return existing

    def list_messages(
        self,
        inbox_id: str,
        status: str | None = None,
        assigned_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List messages in an inbox with optional filtering."""
        conditions = ["inbox_id = ?"]
        params: list[Any] = [inbox_id]

        if status:
            conditions.append("status = ?")
            params.append(status)
        if assigned_to:
            conditions.append("assigned_to = ?")
            params.append(assigned_to)

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM inbox_messages
                WHERE {where_clause}
                ORDER BY received_at DESC
                LIMIT ? OFFSET ?
            """,  # dynamic clause from internal state
                params,
            )
            rows = cursor.fetchall()

        return [self._row_to_message(row) for row in rows]

    # =========================================================================
    # Row Conversion Helpers
    # =========================================================================

    def _row_to_rule(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a database row to a rule dictionary."""
        return {
            "id": row["id"],
            "name": row["name"],
            "workspace_id": row["workspace_id"],
            "inbox_id": row["inbox_id"],
            "conditions": json.loads(row["conditions"]),
            "condition_logic": row["condition_logic"],
            "actions": json.loads(row["actions"]),
            "priority": row["priority"],
            "enabled": bool(row["enabled"]),
            "description": row["description"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "created_by": row["created_by"],
            "stats": json.loads(row["stats"]) if row["stats"] else {},
        }

    def _row_to_inbox(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a database row to an inbox dictionary."""
        return {
            "id": row["id"],
            "workspace_id": row["workspace_id"],
            "name": row["name"],
            "description": row["description"],
            "email_address": row["email_address"],
            "connector_type": row["connector_type"],
            "team_members": json.loads(row["team_members"]) if row["team_members"] else [],
            "admins": json.loads(row["admins"]) if row["admins"] else [],
            "settings": json.loads(row["settings"]) if row["settings"] else {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "created_by": row["created_by"],
            "message_count": row["message_count"],
            "unread_count": row["unread_count"],
        }

    def _row_to_message(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a database row to a message dictionary."""
        return {
            "id": row["id"],
            "inbox_id": row["inbox_id"],
            "email_id": row["email_id"],
            "subject": row["subject"],
            "from_address": row["from_address"],
            "to_addresses": json.loads(row["to_addresses"]) if row["to_addresses"] else [],
            "snippet": row["snippet"],
            "received_at": row["received_at"],
            "status": row["status"],
            "assigned_to": row["assigned_to"],
            "assigned_at": row["assigned_at"],
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "priority": row["priority"],
            "notes": json.loads(row["notes"]) if row["notes"] else [],
            "thread_id": row["thread_id"],
            "sla_deadline": row["sla_deadline"],
            "resolved_at": row["resolved_at"],
            "resolved_by": row["resolved_by"],
        }

    # =========================================================================
    # Rule Matching
    # =========================================================================

    def get_matching_rules(
        self,
        inbox_id: str,
        email_data: dict[str, Any],
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Find all enabled rules that match the given email data.

        Args:
            inbox_id: The inbox to get rules for
            email_data: Email data with keys like:
                - from_address: Sender email address
                - to_addresses: List of recipient addresses
                - subject: Email subject line
                - snippet/body: Email body preview
                - priority: Email priority level
            workspace_id: Optional workspace filter

        Returns:
            List of matching rules sorted by priority (ascending)
        """
        # Get all enabled rules for this inbox/workspace
        rules = self.list_rules(
            workspace_id=workspace_id,
            inbox_id=inbox_id,
            enabled_only=True,
            limit=1000,
        )

        matching_rules = []
        for rule in rules:
            if self._evaluate_rule(rule, email_data):
                matching_rules.append(rule)
                # Increment stats
                self.increment_rule_stats(rule["id"], matched=1)

        return matching_rules

    def _evaluate_rule(self, rule: dict[str, Any], email_data: dict[str, Any]) -> bool:
        """
        Evaluate if a routing rule matches the given email data.

        Args:
            rule: Rule dictionary with conditions
            email_data: Email data to evaluate against

        Returns:
            True if the rule matches
        """
        import re

        conditions = rule.get("conditions", [])
        if not conditions:
            return False

        condition_logic = rule.get("condition_logic", "AND")
        results = []

        for condition in conditions:
            field = condition.get("field", "")
            operator = condition.get("operator", "")
            condition_value = condition.get("value", "").lower()

            # Extract the value to match against based on field
            value = ""
            if field == "from":
                value = (email_data.get("from_address") or "").lower()
            elif field == "to":
                to_addrs = email_data.get("to_addresses", [])
                if isinstance(to_addrs, list):
                    value = " ".join(to_addrs).lower()
                else:
                    value = str(to_addrs).lower()
            elif field == "subject":
                value = (email_data.get("subject") or "").lower()
            elif field == "body":
                value = (email_data.get("snippet") or email_data.get("body") or "").lower()
            elif field == "sender_domain":
                from_addr = email_data.get("from_address") or ""
                value = from_addr.split("@")[-1].lower() if "@" in from_addr else ""
            elif field == "priority":
                value = (email_data.get("priority") or "").lower()
            elif field == "labels":
                labels = email_data.get("labels", [])
                value = (
                    " ".join(labels).lower() if isinstance(labels, list) else str(labels).lower()
                )

            # Evaluate the condition
            matched = False
            if operator == "contains":
                matched = condition_value in value
            elif operator == "equals":
                matched = value == condition_value
            elif operator == "starts_with":
                matched = value.startswith(condition_value)
            elif operator == "ends_with":
                matched = value.endswith(condition_value)
            elif operator == "matches":
                try:
                    matched = bool(re.search(condition_value, value, re.IGNORECASE))
                except re.error:
                    matched = False
            elif operator == "greater_than":
                try:
                    matched = float(value) > float(condition_value)
                except (ValueError, TypeError):
                    matched = False
            elif operator == "less_than":
                try:
                    matched = float(value) < float(condition_value)
                except (ValueError, TypeError):
                    matched = False

            results.append(matched)

        # Apply condition logic
        if condition_logic == "AND":
            return all(results) if results else False
        else:  # OR
            return any(results) if results else False

    def close(self) -> None:
        """Close the current context's database connection."""
        conn = self._conn_var.get()
        if conn is not None:
            conn.close()
            self._conn_var.set(None)
            if conn in self._connections:
                self._connections.remove(conn)

    def close_all(self) -> None:
        """Close all tracked connections."""
        for conn in self._connections:
            try:
                conn.close()
            except OSError as exc:
                logger.debug("Failed to close connection: %s", exc)
        self._connections.clear()
        self._conn_var.set(None)


# Singleton instance for shared use
_default_store: RulesStore | None = None
_store_lock = threading.Lock()


def get_rules_store(db_path: str | None = None) -> RulesStore:
    """Get the default rules store instance."""
    global _default_store
    if _default_store is None:
        with _store_lock:
            if _default_store is None:
                _default_store = RulesStore(db_path)
    return _default_store
