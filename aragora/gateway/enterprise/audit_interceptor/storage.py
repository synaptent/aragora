"""
Storage backends for the Audit Interceptor.

Contains:
- AuditStorage: Abstract base class for storage
- InMemoryAuditStorage: In-memory storage for development/testing
- PostgresAuditStorage: PostgreSQL storage for production
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from .models import AuditRecord

logger = logging.getLogger(__name__)


class AuditStorage(ABC):
    """
    Abstract base class for audit record storage.

    Implementations must provide thread-safe storage operations
    with support for hash chain integrity.
    """

    @abstractmethod
    async def store(self, record: AuditRecord) -> None:
        """
        Store an audit record.

        Args:
            record: The audit record to store
        """
        ...

    @abstractmethod
    async def get(self, record_id: str) -> AuditRecord | None:
        """
        Retrieve an audit record by ID.

        Args:
            record_id: The record ID

        Returns:
            The audit record or None if not found
        """
        ...

    @abstractmethod
    async def query(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        correlation_id: str | None = None,
        request_path: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[AuditRecord]:
        """
        Query audit records.

        Args:
            start_date: Filter records after this time
            end_date: Filter records before this time
            user_id: Filter by user ID
            org_id: Filter by organization ID
            correlation_id: Filter by correlation ID
            request_path: Filter by request path (prefix match)
            limit: Maximum records to return
            offset: Pagination offset

        Returns:
            List of matching audit records
        """
        ...

    @abstractmethod
    async def get_last_hash(self) -> str:
        """
        Get the hash of the most recent record for chain continuity.

        Returns:
            Hash of last record, or empty string if no records
        """
        ...

    @abstractmethod
    async def get_chain(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditRecord]:
        """
        Get records in chain order for verification.

        Args:
            start_date: Start of verification range
            end_date: End of verification range

        Returns:
            Records in timestamp order
        """
        ...

    @abstractmethod
    async def delete_before(self, cutoff: datetime) -> int:
        """
        Delete records before the cutoff date (retention policy).

        Args:
            cutoff: Delete records with timestamp before this

        Returns:
            Number of records deleted
        """
        ...

    @abstractmethod
    async def count(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """
        Count records in date range.

        Args:
            start_date: Start of range
            end_date: End of range

        Returns:
            Number of records
        """
        ...


class InMemoryAuditStorage(AuditStorage):
    """
    In-memory audit storage for development and testing.

    Not suitable for production as data is lost on restart.
    Thread-safe via asyncio lock.
    """

    def __init__(self, max_records: int = 100000) -> None:
        """
        Initialize in-memory storage.

        Args:
            max_records: Maximum records to keep (oldest evicted first)
        """
        self._records: dict[str, AuditRecord] = {}
        self._order: list[str] = []  # Ordered by timestamp
        self._max_records = max_records
        self._lock = asyncio.Lock()
        self._last_hash = ""

    async def store(self, record: AuditRecord) -> None:
        """Store a record."""
        async with self._lock:
            self._records[record.id] = record
            self._order.append(record.id)
            self._last_hash = record.record_hash

            # Evict old records if over limit
            while len(self._order) > self._max_records:
                old_id = self._order.pop(0)
                del self._records[old_id]

    async def get(self, record_id: str) -> AuditRecord | None:
        """Get a record by ID."""
        return self._records.get(record_id)

    async def query(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        correlation_id: str | None = None,
        request_path: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[AuditRecord]:
        """Query records with filters."""
        results = []
        for record_id in reversed(self._order):  # Most recent first
            record = self._records.get(record_id)
            if not record:
                continue

            # Apply filters
            if start_date and record.timestamp < start_date:
                continue
            if end_date and record.timestamp > end_date:
                continue
            if user_id and record.user_id != user_id:
                continue
            if org_id and record.org_id != org_id:
                continue
            if correlation_id and record.correlation_id != correlation_id:
                continue
            if request_path and not record.request_path.startswith(request_path):
                continue

            results.append(record)

        # Apply pagination
        return results[offset : offset + limit]

    async def get_last_hash(self) -> str:
        """Get last record hash."""
        return self._last_hash

    async def get_chain(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditRecord]:
        """Get records in chain order."""
        results = []
        for record_id in self._order:  # Oldest first (chain order)
            record = self._records.get(record_id)
            if not record:
                continue
            if start_date and record.timestamp < start_date:
                continue
            if end_date and record.timestamp > end_date:
                continue
            results.append(record)
        return results

    async def delete_before(self, cutoff: datetime) -> int:
        """Delete records before cutoff."""
        async with self._lock:
            deleted = 0
            new_order = []
            for record_id in self._order:
                record = self._records.get(record_id)
                if record and record.timestamp < cutoff:
                    del self._records[record_id]
                    deleted += 1
                else:
                    new_order.append(record_id)
            self._order = new_order
            return deleted

    async def count(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """Count records in range."""
        if not start_date and not end_date:
            return len(self._records)

        count = 0
        for record in self._records.values():
            if start_date and record.timestamp < start_date:
                continue
            if end_date and record.timestamp > end_date:
                continue
            count += 1
        return count


class PostgresAuditStorage(AuditStorage):
    """
    PostgreSQL audit storage for production deployments.

    Provides durable, scalable storage with full SQL query capabilities.
    Requires asyncpg or psycopg for async operations.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS gateway_audit_records (
        id TEXT PRIMARY KEY,
        correlation_id TEXT,
        timestamp TIMESTAMPTZ NOT NULL,
        request_method TEXT,
        request_path TEXT,
        request_headers JSONB DEFAULT '{}',
        request_body JSONB,
        request_body_hash TEXT,
        response_status INTEGER,
        response_headers JSONB DEFAULT '{}',
        response_body JSONB,
        response_body_hash TEXT,
        duration_ms FLOAT,
        user_id TEXT,
        org_id TEXT,
        ip_address TEXT,
        user_agent TEXT,
        record_hash TEXT NOT NULL,
        previous_hash TEXT,
        signature TEXT,
        metadata JSONB DEFAULT '{}',
        pii_fields_redacted TEXT[]
    );

    CREATE INDEX IF NOT EXISTS idx_gateway_audit_timestamp
        ON gateway_audit_records(timestamp);
    CREATE INDEX IF NOT EXISTS idx_gateway_audit_user
        ON gateway_audit_records(user_id);
    CREATE INDEX IF NOT EXISTS idx_gateway_audit_org
        ON gateway_audit_records(org_id);
    CREATE INDEX IF NOT EXISTS idx_gateway_audit_correlation
        ON gateway_audit_records(correlation_id);
    CREATE INDEX IF NOT EXISTS idx_gateway_audit_path
        ON gateway_audit_records(request_path);
    """

    def __init__(self, database_url: str | None = None) -> None:
        """
        Initialize PostgreSQL storage.

        Args:
            database_url: PostgreSQL connection URL. If None, reads from
                          DATABASE_URL or ARAGORA_POSTGRES_DSN environment.
        """
        self._database_url = (
            database_url or os.environ.get("DATABASE_URL") or os.environ.get("ARAGORA_POSTGRES_DSN")
        )
        if not self._database_url:
            raise ValueError("PostgreSQL URL required. Set DATABASE_URL or ARAGORA_POSTGRES_DSN.")
        self._pool: Any = None
        self._last_hash = ""

    async def _get_pool(self) -> Any:
        """Get or create connection pool."""
        if self._pool is None:
            try:
                import asyncpg

                self._pool = await asyncpg.create_pool(self._database_url, min_size=2, max_size=10)
                # Ensure schema exists
                async with self._pool.acquire() as conn:
                    await conn.execute(self.SCHEMA)
                    # Load last hash
                    row = await conn.fetchrow(
                        "SELECT record_hash FROM gateway_audit_records "
                        "ORDER BY timestamp DESC LIMIT 1"
                    )
                    if row:
                        self._last_hash = row["record_hash"]
            except ImportError:
                raise ImportError(
                    "asyncpg required for PostgresAuditStorage. Install with: pip install asyncpg"
                )
        return self._pool

    async def store(self, record: AuditRecord) -> None:
        """Store an audit record."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO gateway_audit_records (
                    id, correlation_id, timestamp, request_method, request_path,
                    request_headers, request_body, request_body_hash,
                    response_status, response_headers, response_body, response_body_hash,
                    duration_ms, user_id, org_id, ip_address, user_agent,
                    record_hash, previous_hash, signature, metadata, pii_fields_redacted
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    $13, $14, $15, $16, $17, $18, $19, $20, $21, $22
                )
                """,
                record.id,
                record.correlation_id,
                record.timestamp,
                record.request_method,
                record.request_path,
                json.dumps(record.request_headers),
                json.dumps(record.request_body) if record.request_body else None,
                record.request_body_hash,
                record.response_status,
                json.dumps(record.response_headers),
                json.dumps(record.response_body) if record.response_body else None,
                record.response_body_hash,
                record.duration_ms,
                record.user_id,
                record.org_id,
                record.ip_address,
                record.user_agent,
                record.record_hash,
                record.previous_hash,
                record.signature,
                json.dumps(record.metadata),
                record.pii_fields_redacted,
            )
            self._last_hash = record.record_hash

    async def get(self, record_id: str) -> AuditRecord | None:
        """Get a record by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM gateway_audit_records WHERE id = $1", record_id
            )
            if row:
                return self._row_to_record(row)
            return None

    async def query(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        correlation_id: str | None = None,
        request_path: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[AuditRecord]:
        """Query records with filters."""
        conditions = ["1=1"]
        params: list[Any] = []
        param_idx = 1

        if start_date:
            conditions.append(f"timestamp >= ${param_idx}")
            params.append(start_date)
            param_idx += 1
        if end_date:
            conditions.append(f"timestamp <= ${param_idx}")
            params.append(end_date)
            param_idx += 1
        if user_id:
            conditions.append(f"user_id = ${param_idx}")
            params.append(user_id)
            param_idx += 1
        if org_id:
            conditions.append(f"org_id = ${param_idx}")
            params.append(org_id)
            param_idx += 1
        if correlation_id:
            conditions.append(f"correlation_id = ${param_idx}")
            params.append(correlation_id)
            param_idx += 1
        if request_path:
            conditions.append(f"request_path LIKE ${param_idx}")
            params.append(f"{request_path}%")
            param_idx += 1

        params.extend([limit, offset])

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM gateway_audit_records
                WHERE {" AND ".join(conditions)}
                ORDER BY timestamp DESC
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
                """,  # dynamic clause from internal state
                *params,
            )
            return [self._row_to_record(row) for row in rows]

    async def get_last_hash(self) -> str:
        """Get last record hash."""
        return self._last_hash

    async def get_chain(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditRecord]:
        """Get records in chain order."""
        conditions = ["1=1"]
        params: list[Any] = []
        param_idx = 1

        if start_date:
            conditions.append(f"timestamp >= ${param_idx}")
            params.append(start_date)
            param_idx += 1
        if end_date:
            conditions.append(f"timestamp <= ${param_idx}")
            params.append(end_date)
            param_idx += 1

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM gateway_audit_records
                WHERE {" AND ".join(conditions)}
                ORDER BY timestamp ASC
                """,  # dynamic clause from internal state
                *params,
            )
            return [self._row_to_record(row) for row in rows]

    async def delete_before(self, cutoff: datetime) -> int:
        """Delete records before cutoff."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM gateway_audit_records WHERE timestamp < $1", cutoff
            )
            # Parse "DELETE N" result
            return int(result.split()[-1]) if result else 0

    async def count(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """Count records in range."""
        conditions = ["1=1"]
        params: list[Any] = []
        param_idx = 1

        if start_date:
            conditions.append(f"timestamp >= ${param_idx}")
            params.append(start_date)
            param_idx += 1
        if end_date:
            conditions.append(f"timestamp <= ${param_idx}")
            params.append(end_date)
            param_idx += 1

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) as count FROM gateway_audit_records
                WHERE {" AND ".join(conditions)}
                """,  # dynamic clause from internal state
                *params,
            )
            return row["count"] if row else 0

    def _row_to_record(self, row: Any) -> AuditRecord:
        """Convert a database row to an AuditRecord."""
        return AuditRecord(
            id=row["id"],
            correlation_id=row["correlation_id"] or "",
            timestamp=row["timestamp"],
            request_method=row["request_method"] or "",
            request_path=row["request_path"] or "",
            request_headers=json.loads(row["request_headers"]) if row["request_headers"] else {},
            request_body=json.loads(row["request_body"]) if row["request_body"] else None,
            request_body_hash=row["request_body_hash"] or "",
            response_status=row["response_status"] or 0,
            response_headers=json.loads(row["response_headers"]) if row["response_headers"] else {},
            response_body=json.loads(row["response_body"]) if row["response_body"] else None,
            response_body_hash=row["response_body_hash"] or "",
            duration_ms=row["duration_ms"] or 0.0,
            user_id=row["user_id"],
            org_id=row["org_id"],
            ip_address=row["ip_address"] or "",
            user_agent=row["user_agent"] or "",
            record_hash=row["record_hash"] or "",
            previous_hash=row["previous_hash"] or "",
            signature=row["signature"] or "",
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            pii_fields_redacted=row["pii_fields_redacted"] or [],
        )


__all__ = [
    "AuditStorage",
    "InMemoryAuditStorage",
    "PostgresAuditStorage",
]
