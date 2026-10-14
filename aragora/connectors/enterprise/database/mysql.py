"""
MySQL Enterprise Connector.

Features:
- Incremental sync using transaction timestamps or custom columns
- Binary log (binlog) CDC for real-time change detection
- Table/view selection with schema support
- Connection pooling for performance
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
import time
from typing import TYPE_CHECKING, Any
from collections.abc import AsyncIterator

if TYPE_CHECKING:
    from aragora.connectors.base import ConnectorHealth
    from pymysqlreplication import BinLogStreamReader

from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncItem,
    SyncState,
)
from aragora.connectors.enterprise.database.cdc import (
    CDCSourceType,
    CDCStreamManager,
    ChangeEvent,
    ChangeEventHandler,
    ChangeOperation,
)
from aragora.reasoning.provenance import SourceType

# Optional dependency for async MySQL - pre-declare for type checker
aiomysql: Any = None
_aiomysql_import_error: ImportError | None = None

try:
    import aiomysql  # type: ignore[no-redef]
except ImportError as exc:
    _aiomysql_import_error = exc

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
        name: The identifier to validate (table name, column)
        identifier_type: Description for error messages

    Returns:
        The validated identifier

    Raises:
        ValueError: If the identifier contains invalid characters
    """
    if not name:
        raise ValueError(f"SQL {identifier_type} cannot be empty")
    if len(name) > 64:
        raise ValueError(f"SQL {identifier_type} too long (max 64 chars for MySQL)")
    if not _SAFE_IDENTIFIER_PATTERN.match(name):
        raise ValueError(
            f"Invalid SQL {identifier_type}: '{name}'. "
            "Only alphanumeric characters, underscores, and hyphens are allowed."
        )
    return name


class MySQLConnector(EnterpriseConnector):
    """
    MySQL connector for enterprise data sync.

    Supports:
    - Incremental sync using timestamp columns
    - Real-time updates via binlog CDC (requires mysql-replication)
    - Schema-qualified table access
    - Connection pooling
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        database: str = "mysql",
        tables: list[str] | None = None,
        timestamp_column: str | None = None,
        primary_key_column: str = "id",
        content_columns: list[str] | None = None,
        enable_binlog_cdc: bool = False,
        server_id: int = 100,  # For binlog replication
        pool_size: int = 5,
        **kwargs: Any,
    ):
        connector_id = f"mysql_{host}_{database}"
        super().__init__(connector_id=connector_id, **kwargs)

        self.host = host
        self.port = port
        self.database = database
        self.tables = tables or []
        self.timestamp_column = timestamp_column
        self.primary_key_column = primary_key_column
        self.content_columns = content_columns
        self.enable_binlog_cdc = enable_binlog_cdc
        self.server_id = server_id
        self.pool_size = pool_size

        self._pool: Any = None
        self._binlog_stream: BinLogStreamReader | None = None
        self._cdc_task: asyncio.Task[None] | None = None

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
                source_type=CDCSourceType.MYSQL,
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
        return f"MySQL ({self.database})"

    async def _get_pool(self) -> Any:
        """Get or create connection pool."""
        if self._pool is not None:
            return self._pool

        if aiomysql is None:
            logger.error("aiomysql not installed. Run: pip install aiomysql")
            raise ImportError("aiomysql not installed. Run: pip install aiomysql") from (
                _aiomysql_import_error
            )

        # Get credentials
        username = await self.credentials.get_credential("MYSQL_USER") or "root"
        password = await self.credentials.get_credential("MYSQL_PASSWORD") or ""

        self._pool = await aiomysql.create_pool(
            host=self.host,
            port=self.port,
            db=self.database,
            user=username,
            password=password,
            minsize=1,
            maxsize=self.pool_size,
            autocommit=True,
        )
        return self._pool

    async def _discover_tables(self) -> list[str]:
        """Discover tables in the database."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """,
                    (self.database,),
                )
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def _get_table_columns(self, table: str) -> list[dict[str, Any]]:
        """Get column information for a table."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (self.database, table),
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "column_name": row[0],
                        "data_type": row[1],
                        "is_nullable": row[2],
                    }
                    for row in rows
                ]

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

        parts = []
        for key, value in filtered.items():
            if value is not None:
                if isinstance(value, datetime):
                    value = value.isoformat()
                elif isinstance(value, (dict, list)):
                    value = json.dumps(value, default=str)
                parts.append(f"{key}: {value}")

        return "\n".join(parts)

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Sync items from MySQL tables.

        Supports incremental sync using timestamp columns.

        Args:
            state: Current sync state with cursor
            batch_size: Number of items per batch (unused in MySQL connector,
                       kept for API compatibility)
        """
        pool = await self._get_pool()

        tables = self.tables or await self._discover_tables()
        last_sync = state.last_sync_at

        for table in tables:
            # Validate table name to prevent SQL injection
            safe_table = _validate_sql_identifier(table, "table")

            columns = await self._get_table_columns(table)
            ts_column = self._find_timestamp_column(columns)

            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    if ts_column and last_sync:
                        safe_ts_column = _validate_sql_identifier(ts_column, "column")
                        query = f"""
                            SELECT * FROM `{safe_table}`
                            WHERE `{safe_ts_column}` > %s
                            ORDER BY `{safe_ts_column}`
                        """  # table name interpolation, parameterized
                        await cursor.execute(query, (last_sync,))
                    else:
                        # table name interpolation, parameterized
                        query = f"SELECT * FROM `{safe_table}`"
                        await cursor.execute(query)

                    async for row in cursor:
                        row_dict = dict(row)
                        pk_value = row_dict.get(self.primary_key_column)
                        content = self._row_to_content(row_dict, self.content_columns)

                        from aragora.connectors.enterprise.database.id_codec import (
                            generate_evidence_id,
                        )

                        item_id = generate_evidence_id("mysql", self.database, table, pk_value)

                        yield SyncItem(
                            id=item_id,
                            content=content,
                            source_type="mysql",
                            source_id=f"{self.database}.{table}",
                            metadata={
                                "source": "mysql",
                                "database": self.database,
                                "table": table,
                                "primary_key": pk_value,
                                "row_data": row_dict,
                            },
                            updated_at=row_dict.get(ts_column) if ts_column else None,
                        )

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> list:
        """
        Search across indexed tables using LIKE queries.

        For full-text search, tables should have FULLTEXT indexes.
        """
        import aiomysql

        pool = await self._get_pool()
        results: list[dict[str, Any]] = []

        tables = self.tables or await self._discover_tables()

        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                for table in tables[:5]:  # Limit to first 5 tables
                    try:
                        # Validate table name to prevent SQL injection
                        safe_table = _validate_sql_identifier(table, "table")

                        columns = await self._get_table_columns(table)
                        text_columns = [
                            c["column_name"]
                            for c in columns
                            if "char" in c["data_type"].lower() or "text" in c["data_type"].lower()
                        ]

                        if text_columns:
                            # Validate column names to prevent SQL injection
                            safe_columns = [
                                _validate_sql_identifier(col, "column") for col in text_columns[:3]
                            ]
                            conditions = " OR ".join([f"`{col}` LIKE %s" for col in safe_columns])
                            search_query = f"""
                                SELECT * FROM `{safe_table}`
                                WHERE {conditions}
                                LIMIT %s
                            """  # table name interpolation, parameterized
                            params = [f"%{query}%"] * len(safe_columns) + [limit]
                            await cursor.execute(search_query, params)
                            rows = await cursor.fetchall()

                            for row in rows:
                                results.append(
                                    {
                                        "table": table,
                                        "data": dict(row),
                                        "rank": 0.5,
                                    }
                                )

                    except (ValueError, RuntimeError, OSError):
                        logger.exception("Search failed on %s", table)
                        raise

        return sorted(results, key=lambda x: float(x.get("rank") or 0), reverse=True)[:limit]

    async def fetch(self, evidence_id: str) -> Any:
        """Fetch a specific row by evidence ID."""
        from aragora.connectors.enterprise.database.id_codec import parse_evidence_id

        if not evidence_id.startswith("mysql:"):
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
            safe_table = _validate_sql_identifier(table, "table")
            safe_pk_column = _validate_sql_identifier(self.primary_key_column, "column")

            pool = await self._get_pool()

            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # table/column name interpolation, parameterized
                    query = f"SELECT * FROM `{safe_table}` WHERE `{safe_pk_column}` = %s"
                    await cursor.execute(query, (pk_value,))
                    columns = [desc[0] for desc in cursor.description]
                    row = await cursor.fetchone()

                    if row:
                        row_dict = dict(zip(columns, row))
                        return {
                            "id": evidence_id,
                            "table": table,
                            "database": database,
                            "primary_key": pk_value,
                            "data": row_dict,
                            "content": self._row_to_content(row_dict, self.content_columns),
                        }

                    return None

        except (ValueError, RuntimeError, OSError, KeyError):
            logger.exception("[%s] Fetch failed", self.name)
            raise

    async def start_binlog_cdc(self) -> None:
        """
        Start CDC using MySQL binary log.

        Requires mysql-replication package and binlog enabled on server.
        """
        if not self.enable_binlog_cdc:
            logger.warning("Binlog CDC not enabled for this connector")
            return

        try:
            from pymysqlreplication import BinLogStreamReader
            from pymysqlreplication.row_event import (
                DeleteRowsEvent,
                UpdateRowsEvent,
                WriteRowsEvent,
            )

            username = await self.credentials.get_credential("MYSQL_USER") or "root"
            password = await self.credentials.get_credential("MYSQL_PASSWORD") or ""

            mysql_settings = {
                "host": self.host,
                "port": self.port,
                "user": username,
                "passwd": password,
            }

            self._binlog_stream = BinLogStreamReader(
                connection_settings=mysql_settings,
                server_id=self.server_id,
                blocking=True,
                only_events=[WriteRowsEvent, UpdateRowsEvent, DeleteRowsEvent],
                only_schemas=[self.database] if self.database else None,
                only_tables=self.tables if self.tables else None,
                resume_stream=True,
            )

            logger.info("[MySQL CDC] Started binlog stream for %s", self.database)

            self._cdc_task = asyncio.create_task(self._process_binlog_events())

        except ImportError:
            logger.error("mysql-replication not installed. Run: pip install mysql-replication")
            raise

    async def _process_binlog_events(self) -> None:
        """Process binlog events and emit ChangeEvents."""
        from pymysqlreplication.row_event import (
            DeleteRowsEvent,
            UpdateRowsEvent,
            WriteRowsEvent,
        )

        try:
            if self._binlog_stream is None:
                return
            for binlog_event in self._binlog_stream:
                # Map binlog event to ChangeOperation
                if isinstance(binlog_event, WriteRowsEvent):
                    operation = ChangeOperation.INSERT
                elif isinstance(binlog_event, UpdateRowsEvent):
                    operation = ChangeOperation.UPDATE
                elif isinstance(binlog_event, DeleteRowsEvent):
                    operation = ChangeOperation.DELETE
                else:
                    continue

                for row in binlog_event.rows:
                    # Extract data based on event type
                    if operation == ChangeOperation.UPDATE:
                        data = row.get("after_values", {})
                        old_data = row.get("before_values", {})
                    elif operation == ChangeOperation.DELETE:
                        data = None
                        old_data = row.get("values", {})
                    else:  # INSERT
                        data = row.get("values", {})
                        old_data = None

                    # Create ChangeEvent
                    event = ChangeEvent(
                        id="",
                        source_type=CDCSourceType.MYSQL,
                        connector_id=self.connector_id,
                        operation=operation,
                        timestamp=datetime.now(timezone.utc),
                        database=binlog_event.schema,
                        table=binlog_event.table,
                        data=data,
                        old_data=old_data,
                        primary_key={"id": data.get("id") if data else old_data.get("id")},
                    )

                    # Process through CDC manager
                    await self.cdc_manager.process_event(event)

        except (ValueError, RuntimeError, OSError, ConnectionError) as e:
            logger.error("[MySQL CDC] Binlog processing error: %s", e)
            raise
        finally:
            if self._binlog_stream:
                self._binlog_stream.close()

    async def stop_binlog_cdc(self) -> None:
        """Stop binlog CDC stream."""
        if self._cdc_task:
            self._cdc_task.cancel()
            try:
                await self._cdc_task
            except asyncio.CancelledError:
                logger.debug("[MySQL CDC] Binlog CDC task cancelled")

        if self._binlog_stream:
            self._binlog_stream.close()
            self._binlog_stream = None

        logger.info("[MySQL CDC] Stopped binlog stream for %s", self.database)

    async def close(self) -> None:
        """Close connections and cleanup resources."""
        await self.stop_binlog_cdc()

        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    async def health_check(self, timeout: float = 5.0) -> ConnectorHealth:
        """
        Check MySQL connection health.

        Args:
            timeout: Maximum time to wait for health check

        Returns:
            ConnectorHealth with status details
        """
        from aragora.connectors.base import ConnectorHealth

        start_time = time.time()

        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    await cursor.fetchone()

            latency_ms = (time.time() - start_time) * 1000

            return ConnectorHealth(
                name=self.name,
                is_available=True,
                is_configured=True,
                is_healthy=True,
                latency_ms=latency_ms,
                last_check=datetime.now(timezone.utc),
                metadata={
                    "database": self.database,
                    "host": self.host,
                    "binlog_cdc_enabled": self.enable_binlog_cdc,
                },
            )
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("MySQL health check failed: %s", e)
            latency_ms = (time.time() - start_time) * 1000

            return ConnectorHealth(
                name=self.name,
                is_available=self.is_available,
                is_configured=self.is_configured,
                is_healthy=False,
                latency_ms=latency_ms,
                error="Health check failed",
                last_check=datetime.now(timezone.utc),
                metadata={
                    "database": self.database,
                },
            )
