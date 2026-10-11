"""SQLite-backed unified inbox store."""

from __future__ import annotations

import contextvars
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from aragora.config import resolve_db_path
from aragora.storage.unified_inbox._serializers import (
    _format_dt,
    _json_loads,
    _parse_dt,
    _utc_now,
)
from aragora.storage.unified_inbox.base import UnifiedInboxStoreBackend

logger = logging.getLogger(__name__)

DEFAULT_DB_NAME = "unified_inbox.db"


class SQLiteUnifiedInboxStore(UnifiedInboxStoreBackend):
    """SQLite-backed unified inbox store."""

    def __init__(self, db_path: Path | str):
        try:
            from aragora.storage.production_guards import (
                require_distributed_store,
                StorageMode,
            )

            require_distributed_store(
                "unified_inbox_store",
                StorageMode.SQLITE,
                "Unified inbox store using SQLite - use PostgreSQL for multi-instance deployments",
            )
        except ImportError:
            pass

        self.db_path = Path(resolve_db_path(db_path))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"unifiedinbox_conn_{id(self)}", default=None
        )
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self._init_schema()
        logger.info("SQLiteUnifiedInboxStore initialized: %s", self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._conn_var.set(conn)
            with self._connections_lock:
                self._connections.add(conn)
        return conn

    def _init_schema(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS unified_inbox_accounts (
                tenant_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                email_address TEXT NOT NULL,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL,
                connected_at TEXT,
                last_sync TEXT,
                total_messages INTEGER DEFAULT 0,
                unread_count INTEGER DEFAULT 0,
                sync_errors INTEGER DEFAULT 0,
                metadata_json TEXT,
                PRIMARY KEY (tenant_id, account_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS unified_inbox_messages (
                tenant_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                external_id TEXT NOT NULL,
                subject TEXT,
                sender_email TEXT,
                sender_name TEXT,
                recipients_json TEXT,
                cc_json TEXT,
                received_at TEXT,
                snippet TEXT,
                body_preview TEXT,
                is_read INTEGER DEFAULT 0,
                is_starred INTEGER DEFAULT 0,
                has_attachments INTEGER DEFAULT 0,
                labels_json TEXT,
                thread_id TEXT,
                priority_score REAL,
                priority_tier TEXT,
                priority_reasons_json TEXT,
                triage_action TEXT,
                triage_rationale TEXT,
                created_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (tenant_id, message_id)
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unified_inbox_messages_external
            ON unified_inbox_messages(tenant_id, account_id, external_id)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS unified_inbox_triage_results (
                tenant_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                recommended_action TEXT,
                confidence REAL,
                rationale TEXT,
                suggested_response TEXT,
                delegate_to TEXT,
                schedule_for TEXT,
                agents_json TEXT,
                debate_summary TEXT,
                created_at TEXT,
                PRIMARY KEY (tenant_id, message_id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_unified_inbox_accounts_tenant ON unified_inbox_accounts(tenant_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_unified_inbox_messages_tenant ON unified_inbox_messages(tenant_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_unified_inbox_messages_account ON unified_inbox_messages(account_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_unified_inbox_messages_priority ON unified_inbox_messages(priority_tier)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_unified_inbox_messages_received ON unified_inbox_messages(received_at)"
        )
        conn.commit()
        conn.close()

    async def save_account(self, tenant_id: str, account: dict[str, Any]) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO unified_inbox_accounts
            (tenant_id, account_id, provider, email_address, display_name, status,
             connected_at, last_sync, total_messages, unread_count, sync_errors, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                tenant_id,
                account["id"],
                account["provider"],
                account.get("email_address", ""),
                account.get("display_name", ""),
                account.get("status", "pending"),
                _format_dt(account.get("connected_at")),
                _format_dt(account.get("last_sync")),
                int(account.get("total_messages", 0)),
                int(account.get("unread_count", 0)),
                int(account.get("sync_errors", 0)),
                json.dumps(account.get("metadata") or {}),
            ),
        )
        conn.commit()

    async def get_account(self, tenant_id: str, account_id: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT tenant_id, account_id, provider, email_address, display_name, status,
                   connected_at, last_sync, total_messages, unread_count, sync_errors, metadata_json
            FROM unified_inbox_accounts
            WHERE tenant_id = ? AND account_id = ?
        """,
            (tenant_id, account_id),
        ).fetchone()
        if not row:
            return None
        return self._row_to_account(row)

    async def list_accounts(self, tenant_id: str) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT tenant_id, account_id, provider, email_address, display_name, status,
                   connected_at, last_sync, total_messages, unread_count, sync_errors, metadata_json
            FROM unified_inbox_accounts
            WHERE tenant_id = ?
            ORDER BY connected_at DESC
        """,
            (tenant_id,),
        ).fetchall()
        return [self._row_to_account(row) for row in rows]

    async def delete_account(self, tenant_id: str, account_id: str) -> bool:
        conn = self._get_conn()
        message_ids = [
            row[0]
            for row in conn.execute(
                "SELECT message_id FROM unified_inbox_messages WHERE tenant_id = ? AND account_id = ?",
                (tenant_id, account_id),
            ).fetchall()
        ]
        if message_ids:
            conn.executemany(
                "DELETE FROM unified_inbox_triage_results WHERE tenant_id = ? AND message_id = ?",
                [(tenant_id, message_id) for message_id in message_ids],
            )
        conn.execute(
            "DELETE FROM unified_inbox_messages WHERE tenant_id = ? AND account_id = ?",
            (tenant_id, account_id),
        )
        cursor = conn.execute(
            "DELETE FROM unified_inbox_accounts WHERE tenant_id = ? AND account_id = ?",
            (tenant_id, account_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    async def update_account_fields(
        self, tenant_id: str, account_id: str, updates: dict[str, Any]
    ) -> None:
        if not updates:
            return
        fields = []
        params: list[Any] = []
        for key, value in updates.items():
            if key in ("connected_at", "last_sync"):
                value = _format_dt(value)
            if key == "metadata":
                value = json.dumps(value or {})
                key = "metadata_json"
            fields.append(f"{key} = ?")
            params.append(value)
        params.extend([tenant_id, account_id])
        sql = f"""
            UPDATE unified_inbox_accounts
            SET {", ".join(fields)}
            WHERE tenant_id = ? AND account_id = ?
        """  # dynamic clause from internal state
        conn = self._get_conn()
        conn.execute(sql, tuple(params))
        conn.commit()

    async def increment_account_counts(
        self,
        tenant_id: str,
        account_id: str,
        total_delta: int = 0,
        unread_delta: int = 0,
        sync_error_delta: int = 0,
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            UPDATE unified_inbox_accounts
            SET total_messages = MAX(0, total_messages + ?),
                unread_count = MAX(0, unread_count + ?),
                sync_errors = MAX(0, sync_errors + ?)
            WHERE tenant_id = ? AND account_id = ?
        """,
            (total_delta, unread_delta, sync_error_delta, tenant_id, account_id),
        )
        conn.commit()

    async def save_message(self, tenant_id: str, message: dict[str, Any]) -> tuple[str, bool]:
        conn = self._get_conn()
        existing = conn.execute(
            """
            SELECT message_id, is_read FROM unified_inbox_messages
            WHERE tenant_id = ? AND account_id = ? AND external_id = ?
        """,
            (tenant_id, message["account_id"], message["external_id"]),
        ).fetchone()

        received_at_str = _format_dt(message.get("received_at")) or _format_dt(_utc_now())
        created_at = _format_dt(message.get("created_at") or _utc_now())
        updated_at = _format_dt(_utc_now())
        is_read = 1 if message.get("is_read") else 0
        is_starred = 1 if message.get("is_starred") else 0
        has_attachments = 1 if message.get("has_attachments") else 0

        if existing:
            message_id = existing["message_id"]
            old_read = bool(existing["is_read"])
            conn.execute(
                """
                UPDATE unified_inbox_messages
                SET subject = ?, sender_email = ?, sender_name = ?, recipients_json = ?,
                    cc_json = ?, received_at = ?, snippet = ?, body_preview = ?, is_read = ?,
                    is_starred = ?, has_attachments = ?, labels_json = ?, thread_id = ?,
                    priority_score = ?, priority_tier = ?, priority_reasons_json = ?,
                    triage_action = ?, triage_rationale = ?, updated_at = ?
                WHERE tenant_id = ? AND message_id = ?
            """,
                (
                    message.get("subject"),
                    message.get("sender_email"),
                    message.get("sender_name"),
                    json.dumps(message.get("recipients") or []),
                    json.dumps(message.get("cc") or []),
                    received_at_str,
                    message.get("snippet"),
                    message.get("body_preview"),
                    is_read,
                    is_starred,
                    has_attachments,
                    json.dumps(message.get("labels") or []),
                    message.get("thread_id"),
                    float(message.get("priority_score") or 0.0),
                    message.get("priority_tier"),
                    json.dumps(message.get("priority_reasons") or []),
                    message.get("triage_action"),
                    message.get("triage_rationale"),
                    updated_at,
                    tenant_id,
                    message_id,
                ),
            )
            if old_read != bool(is_read):
                delta = -1 if is_read else 1
                await self.increment_account_counts(
                    tenant_id, message["account_id"], unread_delta=delta
                )
            conn.commit()
            return message_id, False

        message_id = message["id"]
        conn.execute(
            """
            INSERT INTO unified_inbox_messages
            (tenant_id, message_id, account_id, provider, external_id, subject, sender_email,
             sender_name, recipients_json, cc_json, received_at, snippet, body_preview,
             is_read, is_starred, has_attachments, labels_json, thread_id, priority_score,
             priority_tier, priority_reasons_json, triage_action, triage_rationale,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                tenant_id,
                message_id,
                message["account_id"],
                message["provider"],
                message["external_id"],
                message.get("subject"),
                message.get("sender_email"),
                message.get("sender_name"),
                json.dumps(message.get("recipients") or []),
                json.dumps(message.get("cc") or []),
                received_at_str,
                message.get("snippet"),
                message.get("body_preview"),
                is_read,
                is_starred,
                has_attachments,
                json.dumps(message.get("labels") or []),
                message.get("thread_id"),
                float(message.get("priority_score") or 0.0),
                message.get("priority_tier"),
                json.dumps(message.get("priority_reasons") or []),
                message.get("triage_action"),
                message.get("triage_rationale"),
                created_at,
                updated_at,
            ),
        )
        conn.commit()
        await self.increment_account_counts(
            tenant_id,
            message["account_id"],
            total_delta=1,
            unread_delta=0 if is_read else 1,
        )
        return message_id, True

    async def get_message(self, tenant_id: str, message_id: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT tenant_id, message_id, account_id, provider, external_id, subject,
                   sender_email, sender_name, recipients_json, cc_json, received_at,
                   snippet, body_preview, is_read, is_starred, has_attachments, labels_json,
                   thread_id, priority_score, priority_tier, priority_reasons_json,
                   triage_action, triage_rationale
            FROM unified_inbox_messages
            WHERE tenant_id = ? AND message_id = ?
        """,
            (tenant_id, message_id),
        ).fetchone()
        if not row:
            return None
        return self._row_to_message(row)

    async def list_messages(
        self,
        tenant_id: str,
        limit: int | None = None,
        offset: int = 0,
        priority_tier: str | None = None,
        account_id: str | None = None,
        unread_only: bool = False,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses = ["tenant_id = ?"]
        params: list[Any] = [tenant_id]
        if priority_tier:
            clauses.append("priority_tier = ?")
            params.append(priority_tier)
        if account_id:
            clauses.append("account_id = ?")
            params.append(account_id)
        if unread_only:
            clauses.append("is_read = 0")
        if search:
            clauses.append(
                "(LOWER(subject) LIKE ? OR LOWER(sender_email) LIKE ? OR LOWER(snippet) LIKE ?)"
            )
            search_value = f"%{search.lower()}%"
            params.extend([search_value, search_value, search_value])

        where_clause = " AND ".join(clauses)
        conn = self._get_conn()
        total_row = conn.execute(
            # dynamic clause from internal state
            f"SELECT COUNT(*) AS total FROM unified_inbox_messages WHERE {where_clause}",
            tuple(params),
        ).fetchone()
        total = int(total_row[0]) if total_row else 0

        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        rows = conn.execute(
            f"""
            SELECT tenant_id, message_id, account_id, provider, external_id, subject,
                   sender_email, sender_name, recipients_json, cc_json, received_at,
                   snippet, body_preview, is_read, is_starred, has_attachments, labels_json,
                   thread_id, priority_score, priority_tier, priority_reasons_json,
                   triage_action, triage_rationale
            FROM unified_inbox_messages
            WHERE {where_clause}
            ORDER BY priority_score DESC, received_at DESC
            {limit_clause}
        """,  # dynamic clause from internal state
            tuple(params),
        ).fetchall()
        return [self._row_to_message(row) for row in rows], total

    async def delete_message(self, tenant_id: str, message_id: str) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT account_id, is_read
            FROM unified_inbox_messages
            WHERE tenant_id = ? AND message_id = ?
        """,
            (tenant_id, message_id),
        ).fetchone()
        if not row:
            return False
        account_id = row["account_id"]
        is_read = bool(row["is_read"])
        conn.execute(
            "DELETE FROM unified_inbox_triage_results WHERE tenant_id = ? AND message_id = ?",
            (tenant_id, message_id),
        )
        cursor = conn.execute(
            "DELETE FROM unified_inbox_messages WHERE tenant_id = ? AND message_id = ?",
            (tenant_id, message_id),
        )
        conn.commit()
        if cursor.rowcount > 0:
            await self.increment_account_counts(
                tenant_id,
                account_id,
                total_delta=-1,
                unread_delta=0 if is_read else -1,
            )
            return True
        return False

    async def update_message_flags(
        self,
        tenant_id: str,
        message_id: str,
        is_read: bool | None = None,
        is_starred: bool | None = None,
    ) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT account_id, is_read
            FROM unified_inbox_messages
            WHERE tenant_id = ? AND message_id = ?
        """,
            (tenant_id, message_id),
        ).fetchone()
        if not row:
            return False
        account_id = row["account_id"]
        old_read = bool(row["is_read"])
        updates = []
        params: list[Any] = []
        if is_read is not None:
            updates.append("is_read = ?")
            params.append(1 if is_read else 0)
        if is_starred is not None:
            updates.append("is_starred = ?")
            params.append(1 if is_starred else 0)
        if not updates:
            return True
        updates.append("updated_at = ?")
        params.append(_format_dt(_utc_now()))
        params.extend([tenant_id, message_id])
        conn.execute(
            f"""
            UPDATE unified_inbox_messages
            SET {", ".join(updates)}
            WHERE tenant_id = ? AND message_id = ?
        """,  # dynamic clause from internal state
            tuple(params),
        )
        conn.commit()
        new_read = is_read if is_read is not None else old_read
        if old_read != new_read:
            delta = -1 if new_read else 1
            await self.increment_account_counts(tenant_id, account_id, unread_delta=delta)
        return True

    async def update_message_triage(
        self,
        tenant_id: str,
        message_id: str,
        triage_action: str | None,
        triage_rationale: str | None,
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            UPDATE unified_inbox_messages
            SET triage_action = ?, triage_rationale = ?, updated_at = ?
            WHERE tenant_id = ? AND message_id = ?
        """,
            (triage_action, triage_rationale, _format_dt(_utc_now()), tenant_id, message_id),
        )
        conn.commit()

    async def save_triage_result(self, tenant_id: str, triage: dict[str, Any]) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO unified_inbox_triage_results
            (tenant_id, message_id, recommended_action, confidence, rationale,
             suggested_response, delegate_to, schedule_for, agents_json, debate_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                tenant_id,
                triage["message_id"],
                triage.get("recommended_action"),
                triage.get("confidence"),
                triage.get("rationale"),
                triage.get("suggested_response"),
                triage.get("delegate_to"),
                _format_dt(triage.get("schedule_for")),
                json.dumps(triage.get("agents_involved") or []),
                triage.get("debate_summary"),
                _format_dt(triage.get("created_at") or _utc_now()),
            ),
        )
        conn.commit()

    async def get_triage_result(self, tenant_id: str, message_id: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT tenant_id, message_id, recommended_action, confidence, rationale,
                   suggested_response, delegate_to, schedule_for, agents_json,
                   debate_summary, created_at
            FROM unified_inbox_triage_results
            WHERE tenant_id = ? AND message_id = ?
        """,
            (tenant_id, message_id),
        ).fetchone()
        if not row:
            return None
        return self._row_to_triage(row)

    def _row_to_account(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["account_id"],
            "provider": row["provider"],
            "email_address": row["email_address"],
            "display_name": row["display_name"],
            "status": row["status"],
            "connected_at": _parse_dt(row["connected_at"]),
            "last_sync": _parse_dt(row["last_sync"]),
            "total_messages": int(row["total_messages"] or 0),
            "unread_count": int(row["unread_count"] or 0),
            "sync_errors": int(row["sync_errors"] or 0),
            "metadata": _json_loads(row["metadata_json"], {}),
        }

    def _row_to_message(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["message_id"],
            "account_id": row["account_id"],
            "provider": row["provider"],
            "external_id": row["external_id"],
            "subject": row["subject"] or "",
            "sender_email": row["sender_email"] or "",
            "sender_name": row["sender_name"] or "",
            "recipients": _json_loads(row["recipients_json"], []),
            "cc": _json_loads(row["cc_json"], []),
            "received_at": _parse_dt(row["received_at"]) or _utc_now(),
            "snippet": row["snippet"] or "",
            "body_preview": row["body_preview"] or "",
            "is_read": bool(row["is_read"]),
            "is_starred": bool(row["is_starred"]),
            "has_attachments": bool(row["has_attachments"]),
            "labels": _json_loads(row["labels_json"], []),
            "thread_id": row["thread_id"],
            "priority_score": float(row["priority_score"] or 0.0),
            "priority_tier": row["priority_tier"] or "medium",
            "priority_reasons": _json_loads(row["priority_reasons_json"], []),
            "triage_action": row["triage_action"],
            "triage_rationale": row["triage_rationale"],
        }

    def _row_to_triage(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "message_id": row["message_id"],
            "recommended_action": row["recommended_action"],
            "confidence": float(row["confidence"] or 0.0),
            "rationale": row["rationale"],
            "suggested_response": row["suggested_response"],
            "delegate_to": row["delegate_to"],
            "schedule_for": _parse_dt(row["schedule_for"]),
            "agents_involved": _json_loads(row["agents_json"], []),
            "debate_summary": row["debate_summary"],
            "created_at": _parse_dt(row["created_at"]),
        }
