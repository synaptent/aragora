"""
PostgreSQL Enterprise Connector.

Features:
- Incremental sync using transaction timestamps or custom columns
- LISTEN/NOTIFY for real-time change detection
- Table/view selection with schema support
- Connection pooling for performance
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from collections.abc import AsyncIterator

from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncItem,
    SyncState,
)
from aragora.connectors.enterprise.database.cdc import (
    ChangeEvent,
    CDCSourceType,
    CDCStreamManager,
    ChangeEventHandler,
)
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)

# Default columns to use for change tracking
DEFAULT_TIMESTAMP_COLUMNS = ["updated_at", "modified_at", "last_modified", "timestamp"]

# SQL identifier validation pattern (alphanumeric, underscores, and hyphens only)
import re

_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\-]*$")


def _validate_sql_identifier(name: str, identifier_type: str = "identifier") -> str:
    """
    Validate a SQL identifier to prevent SQL injection.

    Args:
        name: The identifier to validate (table name, schema, column)
        identifier_type: Description for error messages

    Returns:
        The validated identifier

    Raises:
        ValueError: If the identifier contains invalid characters
    """
    if not name:
        raise ValueError(f"SQL {identifier_type} cannot be empty")
    if len(name) > 63:
        raise ValueError(f"SQL {identifier_type} too long (max 63 chars for PostgreSQL)")
    if not _SAFE_IDENTIFIER_PATTERN.match(name):
        raise ValueError(
            f"Invalid SQL {identifier_type}: '{name}'. "
            "Only alphanumeric characters, underscores, and hyphens are allowed."
        )
    return name


class PostgreSQLConnector(EnterpriseConnector):
    """
    PostgreSQL connector for enterprise data sync.

    Supports:
    - Incremental sync using timestamp columns
    - Real-time updates via LISTEN/NOTIFY
    - Schema-qualified table access
    - Connection pooling
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "postgres",
        schema: str = "public",
        tables: list[str] | None = None,
        timestamp_column: str | None = None,
        primary_key_column: str = "id",
        content_columns: list[str] | None = None,
        notify_channel: str | None = None,
        pool_size: int = 5,
        **kwargs: Any,
    ) -> None:
        connector_id = f"postgres_{host}_{database}_{schema}"
        super().__init__(connector_id=connector_id, **kwargs)

        self.host = host
        self.port = port
        self.database = database
        self.schema = schema
        self.tables = tables or []
        self.timestamp_column = timestamp_column
        self.primary_key_column = primary_key_column
        self.content_columns = content_columns
        self.notify_channel = notify_channel
        self.pool_size = pool_size

        self._pool = None
        self._listener_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()  # For graceful shutdown of listener loop

        # CDC support
        self._cdc_manager: CDCStreamManager | None = None
        self._change_handlers: list[ChangeEventHandler] = []

    @property
    def cdc_manager(self) -> CDCStreamManager:
        """Get or create the CDC stream manager."""
        if self._cdc_manager is None:
            from aragora.connectors.enterprise.database.cdc import CompositeHandler

            handler = CompositeHandler(self._change_handlers)
            self._cdc_manager = CDCStreamManager(
                connector_id=self.connector_id,
                source_type=CDCSourceType.POSTGRESQL,
                handler=handler,
            )
        return self._cdc_manager

    def add_change_handler(self, handler: ChangeEventHandler) -> None:
        """Add a handler for change events."""
        self._change_handlers.append(handler)
        # Reset CDC manager to pick up new handler
        self._cdc_manager = None

    @property
    def source_type(self) -> SourceType:
        return SourceType.DATABASE

    @property
    def name(self) -> str:
        return f"PostgreSQL ({self.database}.{self.schema})"

    async def _get_pool(self) -> Any:
        """Get or create connection pool."""
        if self._pool is not None:
            return self._pool

        try:
            import asyncpg

            # Get credentials
            username = await self.credentials.get_credential("POSTGRES_USER") or "postgres"
            password = await self.credentials.get_credential("POSTGRES_PASSWORD") or ""

            self._pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=username,
                password=password,
                min_size=1,
                max_size=self.pool_size,
            )
            return self._pool

        except ImportError:
            logger.error("asyncpg not installed. Run: pip install asyncpg")
            raise

    async def _discover_tables(self) -> list[str]:
        """Discover tables in the schema."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = $1
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                self.schema,
            )
            return [row["table_name"] for row in rows]

    async def _get_table_columns(self, table: str) -> list[dict[str, Any]]:
        """Get column information for a table."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
                """,
                self.schema,
                table,
            )
            return [dict(row) for row in rows]

    def _find_timestamp_column(self, columns: list[dict[str, Any]]) -> str | None:
        """Find a suitable timestamp column for incremental sync."""
        if self.timestamp_column:
            return self.timestamp_column

        column_names = {col["column_name"].lower() for col in columns}
        for candidate in DEFAULT_TIMESTAMP_COLUMNS:
            if candidate in column_names:
                return candidate
        return None

    def _row_to_content(self, row: dict[str, Any], columns: list[str] | None = None) -> str:
        """Convert a row to text content for indexing."""
        if columns:
            filtered = {k: v for k, v in row.items() if k in columns}
        else:
            filtered = row

        # Convert to readable format
        parts = []
        for key, value in filtered.items():
            if value is not None:
                if isinstance(value, datetime):
                    value = value.isoformat()
                elif isinstance(value, (dict, list)):
                    value = json.dumps(value, default=str)
                parts.append(f"{key}: {value}")

        return "\n".join(parts)

    def _infer_domain(self, table: str) -> str:
        """Infer domain from table name."""
        table_lower = table.lower()

        if any(t in table_lower for t in ["user", "account", "profile", "auth"]):
            return "operational/users"
        elif any(t in table_lower for t in ["order", "invoice", "payment", "transaction"]):
            return "financial/transactions"
        elif any(t in table_lower for t in ["product", "inventory", "catalog"]):
            return "operational/products"
        elif any(t in table_lower for t in ["log", "audit", "event"]):
            return "operational/logs"
        elif any(t in table_lower for t in ["config", "setting", "preference"]):
            return "technical/configuration"
        elif any(t in table_lower for t in ["document", "file", "attachment"]):
            return "general/documents"

        return "general/database"

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Yield items to sync from PostgreSQL tables.

        Uses timestamp columns for incremental sync when available.
        """
        pool = await self._get_pool()
        import asyncpg

        # Get tables to sync
        tables = self.tables or await self._discover_tables()
        state.items_total = len(tables)

        for table in tables:
            try:
                # Validate identifiers to prevent SQL injection
                safe_schema = _validate_sql_identifier(self.schema, "schema")
                safe_table = _validate_sql_identifier(table, "table")
                safe_pk_column = _validate_sql_identifier(self.primary_key_column, "column")

                columns = await self._get_table_columns(table)
                ts_column = self._find_timestamp_column(columns)

                async with pool.acquire() as conn:
                    # Build query with validated identifiers
                    qualified_table = f'"{safe_schema}"."{safe_table}"'

                    if ts_column and state.last_item_timestamp:
                        # Incremental sync
                        safe_ts_column = _validate_sql_identifier(ts_column, "column")
                        query = f"""
                            SELECT * FROM {qualified_table}
                            WHERE "{safe_ts_column}" > $1
                            ORDER BY "{safe_ts_column}" ASC
                            LIMIT $2
                        """  # noqa: S608 -- table name interpolation, parameterized
                        rows = await conn.fetch(query, state.last_item_timestamp, batch_size)
                    else:
                        # Full sync with cursor-based pagination
                        if state.cursor and state.cursor.startswith(f"{table}:"):
                            last_id = state.cursor.split(":", 1)[1]
                            query = f"""
                                SELECT * FROM {qualified_table}
                                WHERE "{safe_pk_column}" > $1
                                ORDER BY "{safe_pk_column}" ASC
                                LIMIT $2
                            """  # noqa: S608 -- table name interpolation, parameterized
                            rows = await conn.fetch(query, last_id, batch_size)
                        else:
                            query = f"""
                                SELECT * FROM {qualified_table}
                                ORDER BY "{safe_pk_column}" ASC
                                LIMIT $1
                            """  # noqa: S608 -- table name interpolation, parameterized
                            rows = await conn.fetch(query, batch_size)

                    for row in rows:
                        row_dict = dict(row)
                        pk_value = row_dict.get(self.primary_key_column, "")

                        # Generate content
                        content = self._row_to_content(row_dict, self.content_columns)

                        # Get timestamp if available
                        updated_at = datetime.now(timezone.utc)
                        if ts_column and row_dict.get(ts_column):
                            ts_value = row_dict[ts_column]
                            if isinstance(ts_value, datetime):
                                updated_at = (
                                    ts_value.replace(tzinfo=timezone.utc)
                                    if ts_value.tzinfo is None
                                    else ts_value
                                )

                        # Create sync item
                        from aragora.connectors.enterprise.database.id_codec import (
                            generate_evidence_id,
                        )

                        item_id = generate_evidence_id("pg", self.database, table, pk_value)

                        yield SyncItem(
                            id=item_id,
                            content=content[:100000],
                            source_type="database",
                            source_id=f"postgresql://{self.host}:{self.port}/{self.database}/{self.schema}/{table}/{pk_value}",
                            title=f"{table} #{pk_value}",
                            url=f"postgresql://{self.host}/{self.database}/{table}?id={pk_value}",
                            updated_at=updated_at,
                            domain=self._infer_domain(table),
                            confidence=0.85,
                            metadata={
                                "database": self.database,
                                "schema": self.schema,
                                "table": table,
                                "primary_key": str(pk_value),
                                "columns": list(row_dict.keys()),
                            },
                        )

                        # Update cursor
                        state.cursor = f"{table}:{pk_value}"

            except (
                ValueError,
                RuntimeError,
                OSError,
                TypeError,
                KeyError,
                asyncpg.PostgresError,
                asyncpg.InterfaceError,
            ) as e:
                logger.warning("Failed to sync table %s (%s): %s", table, type(e).__name__, e)
                state.errors.append(f"{table}: sync failed")
                continue

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[Any]:
        """
        Search across indexed tables using full-text search.

        Requires tables to have tsvector columns for best results.
        """
        pool = await self._get_pool()
        import asyncpg

        results = []

        tables = self.tables or await self._discover_tables()

        async with pool.acquire() as conn:
            for table in tables[:5]:  # Limit to first 5 tables
                try:
                    # Validate identifiers to prevent SQL injection
                    safe_schema = _validate_sql_identifier(self.schema, "schema")
                    safe_table = _validate_sql_identifier(table, "table")
                    qualified_table = f'"{safe_schema}"."{safe_table}"'

                    # Try full-text search if available
                    fts_query = f"""
                        SELECT *, ts_rank(to_tsvector('english', coalesce(content::text, '')), plainto_tsquery('english', $1)) as rank
                        FROM {qualified_table}
                        WHERE to_tsvector('english', coalesce(content::text, '')) @@ plainto_tsquery('english', $1)
                        ORDER BY rank DESC
                        LIMIT $2
                    """  # noqa: S608 -- table name interpolation, parameterized

                    try:
                        rows = await conn.fetch(fts_query, query, limit)
                        for row in rows:
                            results.append(
                                {
                                    "table": table,
                                    "data": dict(row),
                                    "rank": row.get("rank", 0),
                                }
                            )
                    except (ValueError, asyncpg.PostgresError) as e:
                        # Fallback to ILIKE search (FTS may not be configured)
                        logger.debug("FTS query failed on %s, falling back to ILIKE: %s", table, e)
                        columns = await self._get_table_columns(table)
                        text_columns = [
                            c["column_name"]
                            for c in columns
                            if "char" in c["data_type"] or "text" in c["data_type"]
                        ]

                        if text_columns:
                            # Validate column names to prevent SQL injection
                            safe_columns = [
                                _validate_sql_identifier(col, "column") for col in text_columns[:3]
                            ]
                            conditions = " OR ".join(
                                [f'"{col}"::text ILIKE $1' for col in safe_columns]
                            )
                            fallback_query = f"""
                                SELECT * FROM {qualified_table}
                                WHERE {conditions}
                                LIMIT $2
                            """  # noqa: S608 -- table name interpolation, parameterized
                            rows = await conn.fetch(fallback_query, f"%{query}%", limit)
                            for row in rows:
                                results.append(
                                    {
                                        "table": table,
                                        "data": dict(row),
                                        "rank": 0.5,
                                    }
                                )

                except (ValueError, asyncpg.PostgresError, asyncpg.InterfaceError) as e:
                    logger.debug("Search failed on %s: %s", table, e)
                    continue

        return sorted(results, key=lambda x: x.get("rank", 0), reverse=True)[:limit]

    async def fetch(  # type: ignore[override]  # returns dict with row data instead of base Evidence type
        self, evidence_id: str
    ) -> dict[str, Any] | None:
        """Fetch a specific row by evidence ID."""
        from aragora.connectors.enterprise.database.id_codec import parse_evidence_id

        if not evidence_id.startswith("pg:"):
            return None

        parsed = parse_evidence_id(evidence_id)
        if not parsed:
            return None

        if parsed.get("is_legacy"):
            logger.debug("[%s] Cannot fetch legacy hash-based ID: %s", self.name, evidence_id)
            return None

        database = parsed["database"]
        table = parsed["table"]
        pk_value = parsed["pk_value"]

        if database != self.database:
            return None

        try:
            # Validate identifiers to prevent SQL injection
            safe_schema = _validate_sql_identifier(self.schema, "schema")
            safe_table = _validate_sql_identifier(table, "table")
            safe_pk_column = _validate_sql_identifier(self.primary_key_column, "column")

            pool = await self._get_pool()

            async with pool.acquire() as conn:
                query = (
                    f'SELECT * FROM "{safe_schema}"."{safe_table}" WHERE "{safe_pk_column}" = $1'  # noqa: S608 -- table/column name interpolation, parameterized
                )
                row = await conn.fetchrow(query, pk_value)

                if row:
                    row_dict = dict(row)
                    return {
                        "id": evidence_id,
                        "table": table,
                        "database": database,
                        "schema": self.schema,
                        "primary_key": pk_value,
                        "data": row_dict,
                        "content": self._row_to_content(row_dict, self.content_columns),
                    }

                return None

        except (ValueError, RuntimeError, OSError, KeyError) as e:
            logger.error("[%s] Fetch failed: %s", self.name, e)
            return None

    async def start_listener(self) -> None:
        """Start LISTEN/NOTIFY listener for real-time updates."""
        if not self.notify_channel:
            return

        pool = await self._get_pool()

        async def listener_loop() -> None:
            async with pool.acquire() as conn:
                await conn.add_listener(self.notify_channel, self._handle_notification)
                logger.info("[%s] Listening on channel: %s", self.name, self.notify_channel)

                # Keep connection alive until stop event is set
                while not self._stop_event.is_set():
                    try:
                        # Use wait with timeout for responsive shutdown
                        await asyncio.wait_for(self._stop_event.wait(), timeout=60.0)
                    except asyncio.TimeoutError:
                        pass  # Continue loop, check stop event again
                logger.info("[%s] Listener loop stopped gracefully", self.name)

        self._listener_task = asyncio.create_task(listener_loop())

    async def _handle_notification(
        self, connection: Any, pid: int, channel: str, payload: str
    ) -> None:
        """Handle NOTIFY message and emit ChangeEvent."""
        try:
            # Create unified ChangeEvent from NOTIFY payload
            event = ChangeEvent.from_postgres_notify(
                payload=payload,
                channel=channel,
                connector_id=self.connector_id,
                database=self.database,
                schema=self.schema,
            )

            logger.info(
                "[%s] CDC event: %s on %s", self.name, event.operation.value, event.qualified_table
            )

            # Process through CDC manager if handlers are configured
            if self._change_handlers:
                await self.cdc_manager.process_event(event)
            else:
                # Fallback to sync-based processing
                asyncio.create_task(self.sync(max_items=10))

        except (ValueError, KeyError, json.JSONDecodeError) as e:
            logger.warning("[%s] Notification handler error: %s", self.name, e)

    async def stop_listener(self) -> None:
        """Stop the LISTEN/NOTIFY listener gracefully."""
        # Signal the listener loop to stop
        self._stop_event.set()

        if self._listener_task:
            # Give the loop a chance to exit gracefully
            try:
                await asyncio.wait_for(self._listener_task, timeout=5.0)
            except asyncio.TimeoutError:
                # Force cancel if graceful shutdown times out
                self._listener_task.cancel()
                try:
                    await self._listener_task
                except asyncio.CancelledError:
                    logger.debug("[%s] Listener task cancelled during stop", self.name)
            self._listener_task = None

        # Reset stop event for potential restart
        self._stop_event.clear()

    async def close(self) -> None:
        """Close connection pool."""
        await self.stop_listener()
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def handle_webhook(self, payload: dict[str, Any]) -> bool:
        """Handle webhook for database changes (e.g., from triggers)."""
        table = payload.get("table")
        operation = payload.get("operation")

        if not table or not operation:
            return False

        # Create unified ChangeEvent from webhook payload
        event = ChangeEvent.from_postgres_notify(
            payload=json.dumps(payload),
            channel=f"webhook_{table}",
            connector_id=self.connector_id,
            database=self.database,
            schema=self.schema,
        )

        logger.info(
            "[%s] Webhook CDC event: %s on %s",
            self.name,
            event.operation.value,
            event.qualified_table,
        )

        # Process through CDC manager if handlers are configured
        if self._change_handlers:
            await self.cdc_manager.process_event(event)
        else:
            # Fallback to sync-based processing
            asyncio.create_task(self.sync(max_items=10))

        return True
