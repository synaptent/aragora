"""PostgreSQL-backed unified inbox store."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from aragora.storage.unified_inbox._serializers import _json_loads, _utc_now
from aragora.storage.unified_inbox.base import UnifiedInboxStoreBackend

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)


class PostgresUnifiedInboxStore(UnifiedInboxStoreBackend):
    """PostgreSQL-backed unified inbox store."""

    SCHEMA_NAME = "unified_inbox"
    SCHEMA_VERSION = 1
    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS unified_inbox_accounts (
            tenant_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            email_address TEXT NOT NULL,
            display_name TEXT NOT NULL,
            status TEXT NOT NULL,
            connected_at TIMESTAMPTZ,
            last_sync TIMESTAMPTZ,
            total_messages INTEGER DEFAULT 0,
            unread_count INTEGER DEFAULT 0,
            sync_errors INTEGER DEFAULT 0,
            metadata_json TEXT,
            PRIMARY KEY (tenant_id, account_id)
        );

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
            received_at TIMESTAMPTZ,
            snippet TEXT,
            body_preview TEXT,
            is_read BOOLEAN DEFAULT FALSE,
            is_starred BOOLEAN DEFAULT FALSE,
            has_attachments BOOLEAN DEFAULT FALSE,
            labels_json TEXT,
            thread_id TEXT,
            priority_score DOUBLE PRECISION,
            priority_tier TEXT,
            priority_reasons_json TEXT,
            triage_action TEXT,
            triage_rationale TEXT,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            PRIMARY KEY (tenant_id, message_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unified_inbox_messages_external
            ON unified_inbox_messages(tenant_id, account_id, external_id);

        CREATE TABLE IF NOT EXISTS unified_inbox_triage_results (
            tenant_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            recommended_action TEXT,
            confidence DOUBLE PRECISION,
            rationale TEXT,
            suggested_response TEXT,
            delegate_to TEXT,
            schedule_for TIMESTAMPTZ,
            agents_json TEXT,
            debate_summary TEXT,
            created_at TIMESTAMPTZ,
            PRIMARY KEY (tenant_id, message_id)
        );

        CREATE INDEX IF NOT EXISTS idx_unified_inbox_accounts_tenant
            ON unified_inbox_accounts(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_unified_inbox_messages_tenant
            ON unified_inbox_messages(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_unified_inbox_messages_account
            ON unified_inbox_messages(account_id);
        CREATE INDEX IF NOT EXISTS idx_unified_inbox_messages_priority
            ON unified_inbox_messages(priority_tier);
        CREATE INDEX IF NOT EXISTS idx_unified_inbox_messages_received
            ON unified_inbox_messages(received_at);
    """

    def __init__(self, pool: Pool):
        from aragora.storage.postgres_store import PostgresStore

        class _Store(PostgresStore):
            SCHEMA_NAME = PostgresUnifiedInboxStore.SCHEMA_NAME
            SCHEMA_VERSION = PostgresUnifiedInboxStore.SCHEMA_VERSION
            INITIAL_SCHEMA = PostgresUnifiedInboxStore.INITIAL_SCHEMA

        self._store = _Store(pool)
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        await self._store.initialize()
        self._initialized = True
        logger.debug("PostgresUnifiedInboxStore schema initialized")

    async def save_account(self, tenant_id: str, account: dict[str, Any]) -> None:
        await self._store.execute(
            """
            INSERT INTO unified_inbox_accounts
            (tenant_id, account_id, provider, email_address, display_name, status,
             connected_at, last_sync, total_messages, unread_count, sync_errors, metadata_json)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (tenant_id, account_id) DO UPDATE SET
                provider = EXCLUDED.provider,
                email_address = EXCLUDED.email_address,
                display_name = EXCLUDED.display_name,
                status = EXCLUDED.status,
                connected_at = EXCLUDED.connected_at,
                last_sync = EXCLUDED.last_sync,
                total_messages = EXCLUDED.total_messages,
                unread_count = EXCLUDED.unread_count,
                sync_errors = EXCLUDED.sync_errors,
                metadata_json = EXCLUDED.metadata_json
        """,
            tenant_id,
            account["id"],
            account["provider"],
            account.get("email_address", ""),
            account.get("display_name", ""),
            account.get("status", "pending"),
            account.get("connected_at"),
            account.get("last_sync"),
            int(account.get("total_messages", 0)),
            int(account.get("unread_count", 0)),
            int(account.get("sync_errors", 0)),
            json.dumps(account.get("metadata") or {}),
        )

    async def get_account(self, tenant_id: str, account_id: str) -> dict[str, Any] | None:
        row = await self._store.fetch_one(
            """
            SELECT tenant_id, account_id, provider, email_address, display_name, status,
                   connected_at, last_sync, total_messages, unread_count, sync_errors, metadata_json
            FROM unified_inbox_accounts
            WHERE tenant_id = $1 AND account_id = $2
        """,
            tenant_id,
            account_id,
        )
        if not row:
            return None
        return self._row_to_account(row)

    async def list_accounts(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = await self._store.fetch_all(
            """
            SELECT tenant_id, account_id, provider, email_address, display_name, status,
                   connected_at, last_sync, total_messages, unread_count, sync_errors, metadata_json
            FROM unified_inbox_accounts
            WHERE tenant_id = $1
            ORDER BY connected_at DESC
        """,
            tenant_id,
        )
        return [self._row_to_account(row) for row in rows]

    async def delete_account(self, tenant_id: str, account_id: str) -> bool:
        rows = await self._store.fetch_all(
            """
            SELECT message_id FROM unified_inbox_messages
            WHERE tenant_id = $1 AND account_id = $2
        """,
            tenant_id,
            account_id,
        )
        if rows:
            await self._store.executemany(
                """
                DELETE FROM unified_inbox_triage_results
                WHERE tenant_id = $1 AND message_id = $2
            """,
                [(tenant_id, row["message_id"]) for row in rows],
            )
        await self._store.execute(
            """
            DELETE FROM unified_inbox_messages
            WHERE tenant_id = $1 AND account_id = $2
        """,
            tenant_id,
            account_id,
        )
        result = await self._store.execute(
            """
            DELETE FROM unified_inbox_accounts
            WHERE tenant_id = $1 AND account_id = $2
        """,
            tenant_id,
            account_id,
        )
        return result != "DELETE 0"

    async def update_account_fields(
        self, tenant_id: str, account_id: str, updates: dict[str, Any]
    ) -> None:
        if not updates:
            return
        fields = []
        values: list[Any] = []
        idx = 1
        for key, value in updates.items():
            if key == "metadata":
                key = "metadata_json"
                value = json.dumps(value or {})
            fields.append(f"{key} = ${idx}")
            values.append(value)
            idx += 1
        values.extend([tenant_id, account_id])
        sql = f"""
            UPDATE unified_inbox_accounts
            SET {", ".join(fields)}
            WHERE tenant_id = ${idx} AND account_id = ${idx + 1}
        """  # dynamic clause from internal state
        await self._store.execute(sql, *values)

    async def increment_account_counts(
        self,
        tenant_id: str,
        account_id: str,
        total_delta: int = 0,
        unread_delta: int = 0,
        sync_error_delta: int = 0,
    ) -> None:
        await self._store.execute(
            """
            UPDATE unified_inbox_accounts
            SET total_messages = GREATEST(0, total_messages + $1),
                unread_count = GREATEST(0, unread_count + $2),
                sync_errors = GREATEST(0, sync_errors + $3)
            WHERE tenant_id = $4 AND account_id = $5
        """,
            total_delta,
            unread_delta,
            sync_error_delta,
            tenant_id,
            account_id,
        )

    async def save_message(self, tenant_id: str, message: dict[str, Any]) -> tuple[str, bool]:
        row = await self._store.fetch_one(
            """
            SELECT message_id, is_read
            FROM unified_inbox_messages
            WHERE tenant_id = $1 AND account_id = $2 AND external_id = $3
        """,
            tenant_id,
            message["account_id"],
            message["external_id"],
        )
        is_read = bool(message.get("is_read"))
        if row:
            message_id = row["message_id"]
            old_read = bool(row["is_read"])
            await self._store.execute(
                """
                UPDATE unified_inbox_messages
                SET subject = $1, sender_email = $2, sender_name = $3, recipients_json = $4,
                    cc_json = $5, received_at = $6, snippet = $7, body_preview = $8,
                    is_read = $9, is_starred = $10, has_attachments = $11, labels_json = $12,
                    thread_id = $13, priority_score = $14, priority_tier = $15,
                    priority_reasons_json = $16, triage_action = $17, triage_rationale = $18,
                    updated_at = $19
                WHERE tenant_id = $20 AND message_id = $21
            """,
                message.get("subject"),
                message.get("sender_email"),
                message.get("sender_name"),
                json.dumps(message.get("recipients") or []),
                json.dumps(message.get("cc") or []),
                message.get("received_at") or _utc_now(),
                message.get("snippet"),
                message.get("body_preview"),
                is_read,
                bool(message.get("is_starred")),
                bool(message.get("has_attachments")),
                json.dumps(message.get("labels") or []),
                message.get("thread_id"),
                float(message.get("priority_score") or 0.0),
                message.get("priority_tier"),
                json.dumps(message.get("priority_reasons") or []),
                message.get("triage_action"),
                message.get("triage_rationale"),
                _utc_now(),
                tenant_id,
                message_id,
            )
            if old_read != is_read:
                delta = -1 if is_read else 1
                await self.increment_account_counts(
                    tenant_id, message["account_id"], unread_delta=delta
                )
            return message_id, False

        message_id = message["id"]
        await self._store.execute(
            """
            INSERT INTO unified_inbox_messages
            (tenant_id, message_id, account_id, provider, external_id, subject, sender_email,
             sender_name, recipients_json, cc_json, received_at, snippet, body_preview, is_read,
             is_starred, has_attachments, labels_json, thread_id, priority_score, priority_tier,
             priority_reasons_json, triage_action, triage_rationale, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                    $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25)
        """,
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
            message.get("received_at") or _utc_now(),
            message.get("snippet"),
            message.get("body_preview"),
            is_read,
            bool(message.get("is_starred")),
            bool(message.get("has_attachments")),
            json.dumps(message.get("labels") or []),
            message.get("thread_id"),
            float(message.get("priority_score") or 0.0),
            message.get("priority_tier"),
            json.dumps(message.get("priority_reasons") or []),
            message.get("triage_action"),
            message.get("triage_rationale"),
            _utc_now(),
            _utc_now(),
        )
        await self.increment_account_counts(
            tenant_id,
            message["account_id"],
            total_delta=1,
            unread_delta=0 if is_read else 1,
        )
        return message_id, True

    async def get_message(self, tenant_id: str, message_id: str) -> dict[str, Any] | None:
        row = await self._store.fetch_one(
            """
            SELECT tenant_id, message_id, account_id, provider, external_id, subject,
                   sender_email, sender_name, recipients_json, cc_json, received_at,
                   snippet, body_preview, is_read, is_starred, has_attachments, labels_json,
                   thread_id, priority_score, priority_tier, priority_reasons_json,
                   triage_action, triage_rationale
            FROM unified_inbox_messages
            WHERE tenant_id = $1 AND message_id = $2
        """,
            tenant_id,
            message_id,
        )
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
        clauses = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        idx = 2
        if priority_tier:
            clauses.append(f"priority_tier = ${idx}")
            params.append(priority_tier)
            idx += 1
        if account_id:
            clauses.append(f"account_id = ${idx}")
            params.append(account_id)
            idx += 1
        if unread_only:
            clauses.append("is_read = FALSE")
        if search:
            clauses.append(
                f"(LOWER(subject) LIKE ${idx} OR LOWER(sender_email) LIKE ${idx} OR LOWER(snippet) LIKE ${idx})"
            )
            params.append(f"%{search.lower()}%")
            idx += 1

        where_clause = " AND ".join(clauses)
        total_row = await self._store.fetch_one(
            # dynamic clause from internal state
            f"SELECT COUNT(*) AS total FROM unified_inbox_messages WHERE {where_clause}",
            *params,
        )
        total = int(total_row["total"]) if total_row else 0

        limit_clause = ""
        if limit is not None:
            limit_clause = f" LIMIT {limit} OFFSET {offset}"

        rows = await self._store.fetch_all(
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
            *params,
        )
        return [self._row_to_message(row) for row in rows], total

    async def delete_message(self, tenant_id: str, message_id: str) -> bool:
        row = await self._store.fetch_one(
            """
            SELECT account_id, is_read
            FROM unified_inbox_messages
            WHERE tenant_id = $1 AND message_id = $2
        """,
            tenant_id,
            message_id,
        )
        if not row:
            return False
        account_id = row["account_id"]
        is_read = bool(row["is_read"])
        await self._store.execute(
            """
            DELETE FROM unified_inbox_triage_results
            WHERE tenant_id = $1 AND message_id = $2
        """,
            tenant_id,
            message_id,
        )
        result = await self._store.execute(
            """
            DELETE FROM unified_inbox_messages
            WHERE tenant_id = $1 AND message_id = $2
        """,
            tenant_id,
            message_id,
        )
        if result != "DELETE 0":
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
        row = await self._store.fetch_one(
            """
            SELECT account_id, is_read
            FROM unified_inbox_messages
            WHERE tenant_id = $1 AND message_id = $2
        """,
            tenant_id,
            message_id,
        )
        if not row:
            return False
        account_id = row["account_id"]
        old_read = bool(row["is_read"])
        updates = []
        params: list[Any] = []
        idx = 1
        if is_read is not None:
            updates.append(f"is_read = ${idx}")
            params.append(is_read)
            idx += 1
        if is_starred is not None:
            updates.append(f"is_starred = ${idx}")
            params.append(is_starred)
            idx += 1
        if not updates:
            return True
        updates.append(f"updated_at = ${idx}")
        params.append(_utc_now())
        params.extend([tenant_id, message_id])
        await self._store.execute(
            f"""
            UPDATE unified_inbox_messages
            SET {", ".join(updates)}
            WHERE tenant_id = ${idx + 1} AND message_id = ${idx + 2}
        """,  # dynamic clause from internal state
            *params,
        )
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
        await self._store.execute(
            """
            UPDATE unified_inbox_messages
            SET triage_action = $1, triage_rationale = $2, updated_at = $3
            WHERE tenant_id = $4 AND message_id = $5
        """,
            triage_action,
            triage_rationale,
            _utc_now(),
            tenant_id,
            message_id,
        )

    async def save_triage_result(self, tenant_id: str, triage: dict[str, Any]) -> None:
        await self._store.execute(
            """
            INSERT INTO unified_inbox_triage_results
            (tenant_id, message_id, recommended_action, confidence, rationale,
             suggested_response, delegate_to, schedule_for, agents_json, debate_summary, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (tenant_id, message_id) DO UPDATE SET
                recommended_action = EXCLUDED.recommended_action,
                confidence = EXCLUDED.confidence,
                rationale = EXCLUDED.rationale,
                suggested_response = EXCLUDED.suggested_response,
                delegate_to = EXCLUDED.delegate_to,
                schedule_for = EXCLUDED.schedule_for,
                agents_json = EXCLUDED.agents_json,
                debate_summary = EXCLUDED.debate_summary,
                created_at = EXCLUDED.created_at
        """,
            tenant_id,
            triage["message_id"],
            triage.get("recommended_action"),
            triage.get("confidence"),
            triage.get("rationale"),
            triage.get("suggested_response"),
            triage.get("delegate_to"),
            triage.get("schedule_for"),
            json.dumps(triage.get("agents_involved") or []),
            triage.get("debate_summary"),
            triage.get("created_at") or _utc_now(),
        )

    async def get_triage_result(self, tenant_id: str, message_id: str) -> dict[str, Any] | None:
        row = await self._store.fetch_one(
            """
            SELECT tenant_id, message_id, recommended_action, confidence, rationale,
                   suggested_response, delegate_to, schedule_for, agents_json,
                   debate_summary, created_at
            FROM unified_inbox_triage_results
            WHERE tenant_id = $1 AND message_id = $2
        """,
            tenant_id,
            message_id,
        )
        if not row:
            return None
        return self._row_to_triage(row)

    def _row_to_account(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["account_id"],
            "provider": row["provider"],
            "email_address": row["email_address"],
            "display_name": row["display_name"],
            "status": row["status"],
            "connected_at": row["connected_at"],
            "last_sync": row["last_sync"],
            "total_messages": int(row["total_messages"] or 0),
            "unread_count": int(row["unread_count"] or 0),
            "sync_errors": int(row["sync_errors"] or 0),
            "metadata": _json_loads(row["metadata_json"], {}),
        }

    def _row_to_message(self, row: Any) -> dict[str, Any]:
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
            "received_at": row["received_at"] or _utc_now(),
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

    def _row_to_triage(self, row: Any) -> dict[str, Any]:
        return {
            "message_id": row["message_id"],
            "recommended_action": row["recommended_action"],
            "confidence": float(row["confidence"] or 0.0),
            "rationale": row["rationale"],
            "suggested_response": row["suggested_response"],
            "delegate_to": row["delegate_to"],
            "schedule_for": row["schedule_for"],
            "agents_involved": _json_loads(row["agents_json"], []),
            "debate_summary": row["debate_summary"],
            "created_at": row["created_at"],
        }
