"""
Email Persistence Store.

Provides SQLite-backed persistence for email management:
- User email configurations (VIP domains, settings)
- Shared inbox definitions
- Shared inbox messages with assignments
- Routing rules for message distribution
- Prioritization decision audit trail

Usage:
    from aragora.storage.email_store import get_email_store

    store = get_email_store()
    store.save_user_config(user_id, workspace_id, config)
    config = store.get_user_config(user_id, workspace_id)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, cast

from aragora.persistence.db_config import get_default_data_dir

DATA_DIR = get_default_data_dir()
from aragora.storage.base_store import SQLiteStore
from aragora.storage.schema import SchemaManager

logger = logging.getLogger(__name__)


class EmailStore(SQLiteStore):
    """
    SQLite-backed store for email management data.

    Stores:
    - User email prioritization configurations
    - Shared inbox definitions
    - Shared inbox messages and assignments
    - Routing rules
    - Prioritization decision audit trail
    """

    SCHEMA_NAME = "email_store"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        -- User email prioritization configurations
        CREATE TABLE IF NOT EXISTS email_configs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            config_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_email_configs_user_workspace
            ON email_configs(user_id, workspace_id);
        CREATE INDEX IF NOT EXISTS idx_email_configs_workspace
            ON email_configs(workspace_id);

        -- Shared inbox definitions
        CREATE TABLE IF NOT EXISTS shared_inboxes (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            email_address TEXT,
            members_json TEXT NOT NULL DEFAULT '[]',
            settings_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_shared_inboxes_workspace
            ON shared_inboxes(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_shared_inboxes_email
            ON shared_inboxes(email_address);

        -- Shared inbox messages
        CREATE TABLE IF NOT EXISTS shared_inbox_messages (
            id TEXT PRIMARY KEY,
            inbox_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            external_id TEXT,
            subject TEXT,
            from_address TEXT,
            snippet TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT DEFAULT 'normal',
            assigned_to TEXT,
            tags_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            received_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (inbox_id) REFERENCES shared_inboxes(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_messages_inbox ON shared_inbox_messages(inbox_id);
        CREATE INDEX IF NOT EXISTS idx_messages_workspace ON shared_inbox_messages(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_messages_status ON shared_inbox_messages(status);
        CREATE INDEX IF NOT EXISTS idx_messages_assigned ON shared_inbox_messages(assigned_to);
        CREATE INDEX IF NOT EXISTS idx_messages_external ON shared_inbox_messages(external_id);

        -- Routing rules for message distribution
        CREATE TABLE IF NOT EXISTS routing_rules (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            inbox_id TEXT,
            name TEXT NOT NULL,
            description TEXT,
            priority INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            conditions_json TEXT NOT NULL,
            actions_json TEXT NOT NULL,
            match_count INTEGER NOT NULL DEFAULT 0,
            last_matched_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_rules_workspace ON routing_rules(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_rules_inbox ON routing_rules(inbox_id);
        CREATE INDEX IF NOT EXISTS idx_rules_enabled ON routing_rules(enabled);
        CREATE INDEX IF NOT EXISTS idx_rules_priority ON routing_rules(priority DESC);

        -- Prioritization decision audit trail
        CREATE TABLE IF NOT EXISTS prioritization_decisions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            email_id TEXT NOT NULL,
            tier_used INTEGER NOT NULL,
            priority TEXT NOT NULL,
            confidence REAL NOT NULL,
            score REAL NOT NULL,
            rationale TEXT,
            factors_json TEXT,
            context_boosts_json TEXT,
            user_feedback INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_decisions_user ON prioritization_decisions(user_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_workspace ON prioritization_decisions(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_email ON prioritization_decisions(email_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_feedback ON prioritization_decisions(user_feedback);
        CREATE INDEX IF NOT EXISTS idx_decisions_created ON prioritization_decisions(created_at);

        -- VIP senders (separate table for efficient lookup)
        CREATE TABLE IF NOT EXISTS vip_senders (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            sender_email TEXT NOT NULL,
            sender_name TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_vip_user_sender
            ON vip_senders(user_id, workspace_id, sender_email);
        CREATE INDEX IF NOT EXISTS idx_vip_workspace ON vip_senders(workspace_id);
    """

    def register_migrations(self, manager: SchemaManager) -> None:
        """Register schema migrations for future versions."""
        # Future migrations will be registered here
        pass

    # =========================================================================
    # User Email Configurations
    # =========================================================================

    def save_user_config(
        self,
        user_id: str,
        workspace_id: str,
        config: dict[str, Any],
    ) -> str:
        """Save user email prioritization configuration.

        Args:
            user_id: User identifier
            workspace_id: Workspace/organization identifier
            config: Configuration dictionary containing:
                - vip_domains: List of VIP domains
                - vip_addresses: List of VIP email addresses
                - internal_domains: List of internal domains
                - auto_archive_senders: List of senders to auto-archive
                - tier_1_threshold: Score threshold for tier 1
                - tier_2_threshold: Score threshold for tier 2
                - enable_slack_context: Whether to use Slack context
                - enable_calendar_context: Whether to use calendar context

        Returns:
            Config ID
        """

        config_id = f"cfg_{user_id}_{workspace_id}"
        now = datetime.now(timezone.utc).isoformat()

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO email_configs (id, user_id, workspace_id, config_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, workspace_id) DO UPDATE SET
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (config_id, user_id, workspace_id, json.dumps(config), now),
            )

        logger.debug("[EmailStore] Saved config for user=%s, workspace=%s", user_id, workspace_id)
        return config_id

    def get_user_config(
        self,
        user_id: str,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        """Get user email prioritization configuration.

        Args:
            user_id: User identifier
            workspace_id: Workspace identifier

        Returns:
            Configuration dictionary or None if not found
        """
        row = self.fetch_one(
            "SELECT config_json FROM email_configs WHERE user_id = ? AND workspace_id = ?",
            (user_id, workspace_id),
        )
        if row:
            return json.loads(row[0])
        return None

    def delete_user_config(self, user_id: str, workspace_id: str) -> bool:
        """Delete user email configuration.

        Returns:
            True if a config was deleted
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM email_configs WHERE user_id = ? AND workspace_id = ?",
                (user_id, workspace_id),
            )
            return cursor.rowcount > 0

    def list_workspace_configs(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all email configs in a workspace.

        Returns:
            List of config dicts with user_id and config
        """
        rows = self.fetch_all(
            "SELECT user_id, config_json, updated_at FROM email_configs WHERE workspace_id = ?",
            (workspace_id,),
        )
        return [
            {
                "user_id": row[0],
                "config": json.loads(row[1]),
                "updated_at": row[2],
            }
            for row in rows
        ]

    # =========================================================================
    # VIP Senders
    # =========================================================================

    def add_vip_sender(
        self,
        user_id: str,
        workspace_id: str,
        sender_email: str,
        sender_name: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Add a VIP sender.

        Returns:
            VIP sender ID
        """
        import uuid

        vip_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO vip_senders (id, user_id, workspace_id, sender_email, sender_name, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, workspace_id, sender_email) DO UPDATE SET
                    sender_name = excluded.sender_name,
                    notes = excluded.notes
                """,
                (vip_id, user_id, workspace_id, sender_email.lower(), sender_name, notes, now),
            )

        return vip_id

    def remove_vip_sender(
        self,
        user_id: str,
        workspace_id: str,
        sender_email: str,
    ) -> bool:
        """Remove a VIP sender.

        Returns:
            True if a sender was removed
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM vip_senders WHERE user_id = ? AND workspace_id = ? AND sender_email = ?",
                (user_id, workspace_id, sender_email.lower()),
            )
            return cursor.rowcount > 0

    def get_vip_senders(
        self,
        user_id: str,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Get all VIP senders for a user.

        Returns:
            List of VIP sender dicts
        """
        rows = self.fetch_all(
            "SELECT sender_email, sender_name, notes, created_at FROM vip_senders WHERE user_id = ? AND workspace_id = ?",
            (user_id, workspace_id),
        )
        return [
            {
                "sender_email": row[0],
                "sender_name": row[1],
                "notes": row[2],
                "created_at": row[3],
            }
            for row in rows
        ]

    def is_vip_sender(
        self,
        user_id: str,
        workspace_id: str,
        sender_email: str,
    ) -> bool:
        """Check if a sender is VIP."""
        return (
            self.exists(
                "vip_senders",
                "sender_email",
                sender_email.lower(),
            )
            and self.fetch_one(
                "SELECT 1 FROM vip_senders WHERE user_id = ? AND workspace_id = ? AND sender_email = ?",
                (user_id, workspace_id, sender_email.lower()),
            )
            is not None
        )

    # =========================================================================
    # Shared Inboxes
    # =========================================================================

    def create_shared_inbox(
        self,
        inbox_id: str,
        workspace_id: str,
        name: str,
        description: str | None = None,
        email_address: str | None = None,
        members: list[str] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> str:
        """Create a shared inbox.

        Returns:
            Inbox ID
        """
        now = datetime.now(timezone.utc).isoformat()

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO shared_inboxes
                    (id, workspace_id, name, description, email_address, members_json, settings_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inbox_id,
                    workspace_id,
                    name,
                    description,
                    email_address,
                    json.dumps(members or []),
                    json.dumps(settings or {}),
                    now,
                    now,
                ),
            )

        logger.info("[EmailStore] Created shared inbox: %s", inbox_id)
        return inbox_id

    def get_shared_inbox(self, inbox_id: str) -> dict[str, Any] | None:
        """Get a shared inbox by ID."""
        row = self.fetch_one(
            "SELECT * FROM shared_inboxes WHERE id = ?",
            (inbox_id,),
        )
        if row:
            return {
                "id": row[0],
                "workspace_id": row[1],
                "name": row[2],
                "description": row[3],
                "email_address": row[4],
                "members": json.loads(row[5]),
                "settings": json.loads(row[6]),
                "created_at": row[7],
                "updated_at": row[8],
            }
        return None

    def list_shared_inboxes(
        self,
        workspace_id: str,
        member_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List shared inboxes in a workspace.

        Args:
            workspace_id: Workspace to filter by
            member_id: Optional member ID to filter by (returns inboxes they belong to)
        """
        if member_id:
            # SQLite JSON contains - check if member_id is in members array
            rows = self.fetch_all(
                """
                SELECT * FROM shared_inboxes
                WHERE workspace_id = ? AND members_json LIKE ?
                ORDER BY created_at DESC
                """,
                (workspace_id, f'%"{member_id}"%'),
            )
        else:
            rows = self.fetch_all(
                "SELECT * FROM shared_inboxes WHERE workspace_id = ? ORDER BY created_at DESC",
                (workspace_id,),
            )

        return [
            {
                "id": row[0],
                "workspace_id": row[1],
                "name": row[2],
                "description": row[3],
                "email_address": row[4],
                "members": json.loads(row[5]),
                "settings": json.loads(row[6]),
                "created_at": row[7],
                "updated_at": row[8],
            }
            for row in rows
        ]

    def update_shared_inbox(
        self,
        inbox_id: str,
        **updates: Any,
    ) -> bool:
        """Update a shared inbox.

        Supported fields: name, description, email_address, members, settings
        """
        allowed_fields = {"name", "description", "email_address", "members", "settings"}
        set_clauses = []
        params = []

        for field, value in updates.items():
            if field not in allowed_fields:
                continue
            if field in ("members", "settings"):
                set_clauses.append(f"{field}_json = ?")
                params.append(json.dumps(value))
            else:
                set_clauses.append(f"{field} = ?")
                params.append(value)

        if not set_clauses:
            return False

        set_clauses.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(inbox_id)

        with self.connection() as conn:
            cursor = conn.execute(
                f"UPDATE shared_inboxes SET {', '.join(set_clauses)} WHERE id = ?",  # noqa: S608 -- dynamic clause from internal state
                params,
            )
            return cursor.rowcount > 0

    def delete_shared_inbox(self, inbox_id: str) -> bool:
        """Delete a shared inbox and all its messages."""
        with self.connection() as conn:
            # Messages are deleted via CASCADE
            cursor = conn.execute("DELETE FROM shared_inboxes WHERE id = ?", (inbox_id,))
            return cursor.rowcount > 0

    # =========================================================================
    # Shared Inbox Messages
    # =========================================================================

    def save_message(
        self,
        message_id: str,
        inbox_id: str,
        workspace_id: str,
        subject: str | None = None,
        from_address: str | None = None,
        snippet: str | None = None,
        status: str = "open",
        priority: str = "normal",
        assigned_to: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        external_id: str | None = None,
        received_at: str | None = None,
    ) -> str:
        """Save or update a message in a shared inbox."""
        now = datetime.now(timezone.utc).isoformat()

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO shared_inbox_messages
                    (id, inbox_id, workspace_id, external_id, subject, from_address, snippet,
                     status, priority, assigned_to, tags_json, metadata_json, received_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    subject = excluded.subject,
                    from_address = excluded.from_address,
                    snippet = excluded.snippet,
                    status = excluded.status,
                    priority = excluded.priority,
                    assigned_to = excluded.assigned_to,
                    tags_json = excluded.tags_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    message_id,
                    inbox_id,
                    workspace_id,
                    external_id,
                    subject,
                    from_address,
                    snippet,
                    status,
                    priority,
                    assigned_to,
                    json.dumps(tags or []),
                    json.dumps(metadata or {}),
                    received_at or now,
                    now,
                    now,
                ),
            )

        return message_id

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Get a message by ID."""
        row = self.fetch_one(
            "SELECT * FROM shared_inbox_messages WHERE id = ?",
            (message_id,),
        )
        if row:
            return self._row_to_message(row)
        return None

    def _row_to_message(self, row: tuple) -> dict[str, Any]:
        """Convert a database row to a message dict."""
        return {
            "id": row[0],
            "inbox_id": row[1],
            "workspace_id": row[2],
            "external_id": row[3],
            "subject": row[4],
            "from_address": row[5],
            "snippet": row[6],
            "status": row[7],
            "priority": row[8],
            "assigned_to": row[9],
            "tags": json.loads(row[10]) if row[10] else [],
            "metadata": json.loads(row[11]) if row[11] else {},
            "received_at": row[12],
            "created_at": row[13],
            "updated_at": row[14],
        }

    def list_inbox_messages(
        self,
        inbox_id: str,
        status: str | None = None,
        assigned_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List messages in a shared inbox."""
        conditions = ["inbox_id = ?"]
        params: list[Any] = [inbox_id]

        if status:
            conditions.append("status = ?")
            params.append(status)
        if assigned_to:
            conditions.append("assigned_to = ?")
            params.append(assigned_to)

        params.extend([limit, offset])

        rows = self.fetch_all(
            f"""
            SELECT * FROM shared_inbox_messages
            WHERE {" AND ".join(conditions)}
            ORDER BY received_at DESC
            LIMIT ? OFFSET ?
            """,  # noqa: S608 -- dynamic clause from internal state
            tuple(params),
        )

        return [self._row_to_message(row) for row in rows]

    def update_message_status(
        self,
        message_id: str,
        status: str,
        assigned_to: str | None = None,
    ) -> bool:
        """Update message status and optionally assignee."""
        now = datetime.now(timezone.utc).isoformat()

        with self.connection() as conn:
            if assigned_to is not None:
                cursor = conn.execute(
                    "UPDATE shared_inbox_messages SET status = ?, assigned_to = ?, updated_at = ? WHERE id = ?",
                    (status, assigned_to, now, message_id),
                )
            else:
                cursor = conn.execute(
                    "UPDATE shared_inbox_messages SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, message_id),
                )
            return cursor.rowcount > 0

    def add_message_tag(self, message_id: str, tag: str) -> bool:
        """Add a tag to a message."""
        msg = self.get_message(message_id)
        if not msg:
            return False

        tags = msg.get("tags", [])
        if tag not in tags:
            tags.append(tag)
            with self.connection() as conn:
                conn.execute(
                    "UPDATE shared_inbox_messages SET tags_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(tags), datetime.now(timezone.utc).isoformat(), message_id),
                )
        return True

    def get_inbox_stats(self, inbox_id: str) -> dict[str, Any]:
        """Get statistics for a shared inbox."""
        stats_row = self.fetch_one(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open_count,
                SUM(CASE WHEN status = 'assigned' THEN 1 ELSE 0 END) as assigned_count,
                SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_count,
                SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) as resolved_count
            FROM shared_inbox_messages WHERE inbox_id = ?
            """,
            (inbox_id,),
        )

        stats = cast(tuple[Any, ...], stats_row)
        return {
            "total": stats[0] or 0,
            "open": stats[1] or 0,
            "assigned": stats[2] or 0,
            "in_progress": stats[3] or 0,
            "resolved": stats[4] or 0,
        }

    # =========================================================================
    # Full-Text Search (FTS5)
    # =========================================================================

    def _ensure_fts_table(self) -> None:
        """Initialize FTS5 virtual table if not already done."""
        # Check if already initialized by checking if table exists
        check = self.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shared_inbox_messages_fts'"
        )
        if check:
            return

        with self.connection() as conn:
            # Create standalone FTS5 virtual table (not content-sync to avoid complexity)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS shared_inbox_messages_fts USING fts5(
                    message_id,
                    inbox_id,
                    subject,
                    from_address,
                    snippet
                )
                """)

            # Check if we need to populate from existing data
            existing = conn.execute("SELECT COUNT(*) FROM shared_inbox_messages_fts").fetchone()
            msg_count = conn.execute("SELECT COUNT(*) FROM shared_inbox_messages").fetchone()

            if existing[0] == 0 and msg_count[0] > 0:
                # Populate from existing messages
                conn.execute("""
                    INSERT INTO shared_inbox_messages_fts(message_id, inbox_id, subject, from_address, snippet)
                    SELECT id, inbox_id, subject, from_address, snippet
                    FROM shared_inbox_messages
                    """)
                logger.info(
                    "[EmailStore] Populated FTS5 index with %s existing messages", msg_count[0]
                )

        logger.info("[EmailStore] FTS5 full-text search initialized")

    def index_message_for_search(self, message_id: str) -> None:
        """Index or re-index a message for full-text search."""
        self._ensure_fts_table()

        msg = self.get_message(message_id)
        if not msg:
            return

        with self.connection() as conn:
            # Delete existing FTS entry
            conn.execute(
                "DELETE FROM shared_inbox_messages_fts WHERE message_id = ?",
                (message_id,),
            )

            # Insert new FTS entry
            conn.execute(
                """
                INSERT INTO shared_inbox_messages_fts(message_id, inbox_id, subject, from_address, snippet)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, msg["inbox_id"], msg["subject"], msg["from_address"], msg["snippet"]),
            )

    def search_messages(
        self,
        inbox_id: str,
        query: str,
        status: str | None = None,
        assigned_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Full-text search for messages in a shared inbox.

        Args:
            inbox_id: Inbox to search in
            query: Search query (supports FTS5 syntax: AND, OR, NOT, "phrase")
            status: Optional status filter
            assigned_to: Optional assignee filter
            limit: Maximum results to return
            offset: Pagination offset

        Returns:
            List of message dicts with search ranking
        """
        self._ensure_fts_table()

        if not query or not query.strip():
            return self.list_inbox_messages(inbox_id, status, assigned_to, limit, offset)

        # Build the query with filters
        conditions = ["fts.inbox_id = ?"]
        params: list[Any] = [inbox_id]

        # Add status filter
        if status:
            conditions.append("m.status = ?")
            params.append(status)

        # Add assignee filter
        if assigned_to:
            conditions.append("m.assigned_to = ?")
            params.append(assigned_to)

        # Escape special FTS5 characters in user query
        safe_query = self._escape_fts_query(query)

        params.extend([safe_query, limit, offset])
        where_clause = " AND ".join(conditions)

        rows = self.fetch_all(
            f"""
            SELECT m.*, fts.rank
            FROM shared_inbox_messages_fts fts
            JOIN shared_inbox_messages m ON fts.message_id = m.id
            WHERE {where_clause}
                AND shared_inbox_messages_fts MATCH ?
            ORDER BY fts.rank
            LIMIT ? OFFSET ?
            """,  # nosec B608 - where_clause built from hardcoded conditions  # noqa: S608
            tuple(params),
        )

        results = []
        for row in rows:
            msg = self._row_to_message(row[:15])
            msg["search_rank"] = row[15] if len(row) > 15 else 0
            results.append(msg)

        return results

    def search_messages_with_snippets(
        self,
        inbox_id: str,
        query: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Search messages and return highlighted snippets.

        Args:
            inbox_id: Inbox to search in
            query: Search query
            limit: Maximum results to return

        Returns:
            List of dicts with message_id, subject, snippet_highlight, rank
        """
        self._ensure_fts_table()

        if not query or not query.strip():
            return []

        safe_query = self._escape_fts_query(query)

        rows = self.fetch_all(
            """
            SELECT
                fts.message_id,
                m.subject,
                m.from_address,
                m.status,
                snippet(shared_inbox_messages_fts, 4, '<mark>', '</mark>', '...', 32) as snippet_highlight,
                fts.rank
            FROM shared_inbox_messages_fts fts
            JOIN shared_inbox_messages m ON fts.message_id = m.id
            WHERE fts.inbox_id = ?
                AND shared_inbox_messages_fts MATCH ?
            ORDER BY fts.rank
            LIMIT ?
            """,
            (inbox_id, safe_query, limit),
        )

        return [
            {
                "message_id": row[0],
                "subject": row[1],
                "from_address": row[2],
                "status": row[3],
                "snippet_highlight": row[4],
                "rank": row[5],
            }
            for row in rows
        ]

    def _escape_fts_query(self, query: str) -> str:
        """
        Escape special FTS5 characters in user query.

        Wraps terms in quotes to treat them as literals, avoiding FTS5 syntax issues.
        """
        # FTS5 special chars: * ^ : ( ) { } [ ] - ! . @
        # The dot is a column selector, @ is for column filtering
        dangerous = ["*", "^", ":", "(", ")", "{", "}", "[", "]", "-", "!", ".", "@"]

        result = query

        # Remove dangerous characters first
        for char in dangerous:
            result = result.replace(char, " ")

        # Collapse multiple spaces and split into terms
        terms = result.split()

        # Quote each term to make it literal
        quoted_terms = [f'"{term}"' for term in terms if term]

        return " ".join(quoted_terms)

    # =========================================================================
    # Routing Rules
    # =========================================================================

    def create_routing_rule(
        self,
        rule_id: str,
        workspace_id: str,
        name: str,
        conditions: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        description: str | None = None,
        inbox_id: str | None = None,
        priority: int = 0,
        enabled: bool = True,
    ) -> str:
        """Create a routing rule."""
        now = datetime.now(timezone.utc).isoformat()

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO routing_rules
                    (id, workspace_id, inbox_id, name, description, priority, enabled,
                     conditions_json, actions_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    workspace_id,
                    inbox_id,
                    name,
                    description,
                    priority,
                    1 if enabled else 0,
                    json.dumps(conditions),
                    json.dumps(actions),
                    now,
                    now,
                ),
            )

        logger.info("[EmailStore] Created routing rule: %s", rule_id)
        return rule_id

    def get_routing_rule(self, rule_id: str) -> dict[str, Any] | None:
        """Get a routing rule by ID."""
        row = self.fetch_one("SELECT * FROM routing_rules WHERE id = ?", (rule_id,))
        if row:
            return self._row_to_rule(row)
        return None

    def _row_to_rule(self, row: tuple) -> dict[str, Any]:
        """Convert a database row to a rule dict."""
        return {
            "id": row[0],
            "workspace_id": row[1],
            "inbox_id": row[2],
            "name": row[3],
            "description": row[4],
            "priority": row[5],
            "enabled": bool(row[6]),
            "conditions": json.loads(row[7]),
            "actions": json.loads(row[8]),
            "match_count": row[9],
            "last_matched_at": row[10],
            "created_at": row[11],
            "updated_at": row[12],
        }

    def list_routing_rules(
        self,
        workspace_id: str,
        inbox_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List routing rules for a workspace."""
        conditions = ["workspace_id = ?"]
        params: list[Any] = [workspace_id]

        if inbox_id:
            conditions.append("(inbox_id = ? OR inbox_id IS NULL)")
            params.append(inbox_id)
        if enabled_only:
            conditions.append("enabled = 1")

        rows = self.fetch_all(
            f"""
            SELECT * FROM routing_rules
            WHERE {" AND ".join(conditions)}
            ORDER BY priority DESC, created_at ASC
            """,  # noqa: S608 -- dynamic clause from internal state
            tuple(params),
        )

        return [self._row_to_rule(row) for row in rows]

    def update_routing_rule(self, rule_id: str, **updates: Any) -> bool:
        """Update a routing rule."""
        allowed_fields = {
            "name",
            "description",
            "priority",
            "enabled",
            "conditions",
            "actions",
            "inbox_id",
        }
        set_clauses: list[str] = []
        params: list[Any] = []

        for field, value in updates.items():
            if field not in allowed_fields:
                continue
            if field in ("conditions", "actions"):
                set_clauses.append(f"{field}_json = ?")
                params.append(json.dumps(value))
            elif field == "enabled":
                set_clauses.append(f"{field} = ?")
                params.append(1 if value else 0)
            else:
                set_clauses.append(f"{field} = ?")
                params.append(value)

        if not set_clauses:
            return False

        set_clauses.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(rule_id)

        with self.connection() as conn:
            cursor = conn.execute(
                f"UPDATE routing_rules SET {', '.join(set_clauses)} WHERE id = ?",  # noqa: S608 -- dynamic clause from internal state
                params,
            )
            return cursor.rowcount > 0

    def delete_routing_rule(self, rule_id: str) -> bool:
        """Delete a routing rule."""
        return self.delete_by_id("routing_rules", "id", rule_id)

    def increment_rule_match_count(self, rule_id: str) -> None:
        """Increment the match count for a routing rule."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                "UPDATE routing_rules SET match_count = match_count + 1, last_matched_at = ? WHERE id = ?",
                (now, rule_id),
            )

    # =========================================================================
    # Prioritization Decision Audit Trail
    # =========================================================================

    def record_prioritization_decision(
        self,
        decision_id: str,
        user_id: str,
        workspace_id: str,
        email_id: str,
        tier_used: int,
        priority: str,
        confidence: float,
        score: float,
        rationale: str | None = None,
        factors: dict[str, float] | None = None,
        context_boosts: dict[str, float] | None = None,
    ) -> str:
        """Record a prioritization decision for audit trail."""
        now = datetime.now(timezone.utc).isoformat()

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO prioritization_decisions
                    (id, user_id, workspace_id, email_id, tier_used, priority, confidence, score,
                     rationale, factors_json, context_boosts_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    user_id,
                    workspace_id,
                    email_id,
                    tier_used,
                    priority,
                    confidence,
                    score,
                    rationale,
                    json.dumps(factors) if factors else None,
                    json.dumps(context_boosts) if context_boosts else None,
                    now,
                ),
            )

        return decision_id

    def record_user_feedback(
        self,
        email_id: str,
        user_id: str,
        workspace_id: str,
        is_correct: bool,
    ) -> bool:
        """Record user feedback on a prioritization decision."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE prioritization_decisions
                SET user_feedback = ?
                WHERE id = (
                    SELECT id
                    FROM prioritization_decisions
                    WHERE email_id = ? AND user_id = ? AND workspace_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                )
                """,
                (1 if is_correct else 0, email_id, user_id, workspace_id),
            )
            return cursor.rowcount > 0

    def get_feedback_stats(
        self,
        user_id: str,
        workspace_id: str,
        days: int = 30,
    ) -> dict[str, Any]:
        """Get feedback statistics for learning improvements."""
        rows = self.fetch_all(
            """
            SELECT
                tier_used,
                priority,
                COUNT(*) as total,
                SUM(CASE WHEN user_feedback = 1 THEN 1 ELSE 0 END) as correct,
                SUM(CASE WHEN user_feedback = 0 THEN 1 ELSE 0 END) as incorrect
            FROM prioritization_decisions
            WHERE user_id = ? AND workspace_id = ?
                AND created_at > datetime('now', ? || ' days')
                AND user_feedback IS NOT NULL
            GROUP BY tier_used, priority
            """,
            (user_id, workspace_id, f"-{days}"),
        )

        stats: dict[str, Any] = {
            "by_tier": {},
            "by_priority": {},
            "total_feedback": 0,
            "accuracy": 0.0,
        }
        total_correct = 0
        total_feedback = 0

        for row in rows:
            tier = row[0]
            priority = row[1]
            total = row[2]
            correct = row[3] or 0
            _incorrect = row[4] or 0  # noqa: F841

            if tier not in stats["by_tier"]:
                stats["by_tier"][tier] = {"total": 0, "correct": 0}
            stats["by_tier"][tier]["total"] += total
            stats["by_tier"][tier]["correct"] += correct

            if priority not in stats["by_priority"]:
                stats["by_priority"][priority] = {"total": 0, "correct": 0}
            stats["by_priority"][priority]["total"] += total
            stats["by_priority"][priority]["correct"] += correct

            total_correct += correct
            total_feedback += total

        stats["total_feedback"] = total_feedback
        stats["accuracy"] = total_correct / total_feedback if total_feedback > 0 else 0.0

        return stats


# =============================================================================
# Singleton Instance
# =============================================================================

_email_store: EmailStore | None = None


def get_email_store(db_path: str | None = None) -> EmailStore:
    """Get or create the email store singleton.

    Args:
        db_path: Optional path to database file. Defaults to aragora data dir.

    Returns:
        EmailStore instance
    """
    global _email_store

    if _email_store is None:
        if db_path is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            db_path = str(DATA_DIR / "email_store.db")

        _email_store = EmailStore(db_path)
        logger.info("[EmailStore] Initialized at %s", db_path)

    return _email_store


def reset_email_store() -> None:
    """Reset the email store singleton (for testing)."""
    global _email_store
    _email_store = None


__all__ = ["EmailStore", "get_email_store", "reset_email_store"]
