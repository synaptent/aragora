"""
SQL Server Enterprise Connector.

Features:
- Incremental sync using transaction timestamps or custom columns
- Change Data Capture (CDC) for real-time change detection
- Change Tracking for lightweight change detection
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
from aragora.connectors.base import ConnectorHealth
from aragora.connectors.enterprise.database.cdc import (
    CDCSourceType,
    CDCStreamManager,
    ChangeEvent,
    ChangeEventHandler,
    ChangeOperation,
)
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)

_MAX_PAGES = 1000  # Safety cap for pagination loops

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
    if len(name) > 128:
        raise ValueError(f"SQL {identifier_type} too long (max 128 chars)")
    if not _SAFE_IDENTIFIER_PATTERN.match(name):
        raise ValueError(
            f"Invalid SQL {identifier_type}: '{name}'. "
            "Only alphanumeric characters, underscores, and hyphens are allowed."
        )
    return name


class SQLServerConnector(EnterpriseConnector):
    """
    SQL Server connector for enterprise data sync.

    Supports:
    - Incremental sync using timestamp columns
    - Real-time updates via SQL Server CDC (Change Data Capture)
    - Change Tracking for simpler scenarios
    - Schema-qualified table access
    - Connection pooling
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 1433,
        database: str = "master",
        schema: str = "dbo",
        tables: list[str] | None = None,
        timestamp_column: str | None = None,
        primary_key_column: str = "id",
        content_columns: list[str] | None = None,
        use_cdc: bool = False,  # Use SQL Server CDC
        use_change_tracking: bool = False,  # Use Change Tracking
        poll_interval_seconds: int = 5,
        pool_size: int = 5,
        **kwargs: Any,
    ):
        connector_id = f"sqlserver_{host}_{database}_{schema}"
        super().__init__(connector_id=connector_id, **kwargs)

        self.host = host
        self.port = port
        self.database = database
        self.schema = schema
        self.tables = tables or []
        self.timestamp_column = timestamp_column
        self.primary_key_column = primary_key_column
        self.content_columns = content_columns
        self.use_cdc = use_cdc
        self.use_change_tracking = use_change_tracking
        self.poll_interval_seconds = poll_interval_seconds
        self.pool_size = pool_size

        self._pool = None
        self._cdc_task: asyncio.Task[None] | None = None
        self._last_lsn: bytes | None = None  # Last processed LSN for CDC

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
                source_type=CDCSourceType.SQLSERVER,
                handler=handler,
            )
        return self._cdc_manager

    def add_change_handler(self, handler: ChangeEventHandler) -> None:
        """Add a handler for change events."""
        self._change_handlers.append(handler)
        self._cdc_manager = None

    @property
    def source_type(self) -> SourceType:
        return SourceType.DATABASE

    @property
    def name(self) -> str:
        return f"SQL Server ({self.database}.{self.schema})"

    async def _get_pool(self) -> Any:
        """Get or create connection pool."""
        if self._pool is not None:
            return self._pool

        try:
            import aioodbc

            # Get credentials
            username = await self.credentials.get_credential("SQLSERVER_USER") or "sa"
            password = await self.credentials.get_credential("SQLSERVER_PASSWORD") or ""

            # Build connection string
            dsn = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={self.host},{self.port};"
                f"DATABASE={self.database};"
                f"UID={username};"
                f"PWD={password}"
            )

            self._pool = await aioodbc.create_pool(
                dsn=dsn,
                minsize=1,
                maxsize=self.pool_size,
            )
            return self._pool

        except ImportError as exc:
            logger.error("aioodbc not installed. Run: pip install aioodbc")
            raise RuntimeError(
                "aioodbc is required for the SQL Server connector. "
                "Install with: pip install aioodbc"
            ) from exc

    async def _discover_tables(self) -> list[str]:
        """Discover tables in the schema."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT TABLE_NAME
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = ?
                    AND TABLE_TYPE = 'BASE TABLE'
                    ORDER BY TABLE_NAME
                    """,
                    self.schema,
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
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                    ORDER BY ORDINAL_POSITION
                    """,
                    self.schema,
                    table,
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

    async def sync_items(self, state: SyncState, batch_size: int = 100) -> AsyncIterator[SyncItem]:
        """
        Sync items from SQL Server tables.

        Supports incremental sync using timestamp columns.
        """
        pool = await self._get_pool()

        tables = self.tables or await self._discover_tables()
        last_sync = state.last_sync_at

        for table in tables:
            # Validate identifiers to prevent SQL injection
            safe_schema = _validate_sql_identifier(self.schema, "schema")
            safe_table = _validate_sql_identifier(table, "table")

            columns = await self._get_table_columns(table)
            ts_column = self._find_timestamp_column(columns)

            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    if ts_column and last_sync:
                        safe_ts_column = _validate_sql_identifier(ts_column, "column")
                        query = f"""
                            SELECT * FROM [{safe_schema}].[{safe_table}]
                            WHERE [{safe_ts_column}] > ?
                            ORDER BY [{safe_ts_column}]
                        """  # table name interpolation, parameterized
                        await cursor.execute(query, last_sync)
                    else:
                        # table name interpolation, parameterized
                        query = f"SELECT * FROM [{safe_schema}].[{safe_table}]"
                        await cursor.execute(query)

                    # Get column names
                    col_names = [desc[0] for desc in cursor.description]

                    async for row in cursor:
                        row_dict = dict(zip(col_names, row))
                        pk_value = row_dict.get(self.primary_key_column)
                        content = self._row_to_content(row_dict, self.content_columns)

                        from aragora.connectors.enterprise.database.id_codec import (
                            generate_evidence_id,
                        )

                        item_id = generate_evidence_id("mssql", self.database, table, pk_value)

                        yield SyncItem(
                            id=item_id,
                            content=content,
                            source_type="sqlserver",
                            source_id=f"{self.database}.{self.schema}.{table}",
                            metadata={
                                "source": "sqlserver",
                                "database": self.database,
                                "schema": self.schema,
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

        For full-text search, tables should have full-text indexes.
        """
        pool = await self._get_pool()
        results: list[dict[str, Any]] = []

        tables = self.tables or await self._discover_tables()

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                for table in tables[:5]:  # Limit to first 5 tables
                    try:
                        # Validate identifiers to prevent SQL injection
                        safe_schema = _validate_sql_identifier(self.schema, "schema")
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
                            qualified_table = f"[{safe_schema}].[{safe_table}]"
                            conditions = " OR ".join([f"[{col}] LIKE ?" for col in safe_columns])
                            search_query = f"""
                                SELECT TOP (?) * FROM {qualified_table}
                                WHERE {conditions}
                            """  # table name interpolation, parameterized
                            params = [limit] + [f"%{query}%"] * len(safe_columns)
                            await cursor.execute(search_query, *params)
                            rows = await cursor.fetchall()

                            # Get column names from cursor description
                            col_names = (
                                [desc[0] for desc in cursor.description]
                                if cursor.description
                                else []
                            )

                            for row in rows:
                                row_dict = dict(zip(col_names, row)) if col_names else {}
                                results.append(
                                    {
                                        "table": table,
                                        "data": row_dict,
                                        "rank": 0.5,
                                    }
                                )

                    except (OSError, ConnectionError, ValueError, KeyError) as exc:
                        logger.exception("Search failed on %s", table)
                        raise RuntimeError(f"SQL Server search failed for table {table!r}") from exc

        return sorted(results, key=lambda x: float(x.get("rank") or 0), reverse=True)[:limit]

    async def fetch(self, evidence_id: str) -> Any:
        """Fetch a specific row by evidence ID."""
        from aragora.connectors.enterprise.database.id_codec import parse_evidence_id

        if not evidence_id.startswith("mssql:"):
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
                async with conn.cursor() as cursor:
                    query = (
                        # table/column name interpolation, parameterized
                        f"SELECT * FROM [{safe_schema}].[{safe_table}] WHERE [{safe_pk_column}] = ?"
                    )
                    await cursor.execute(query, pk_value)
                    col_names = [desc[0] for desc in cursor.description]
                    row = await cursor.fetchone()

                    if row:
                        row_dict = dict(zip(col_names, row))
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

        except (OSError, ConnectionError, ValueError, KeyError) as exc:
            logger.exception("[%s] Fetch failed", self.name)
            raise RuntimeError(f"SQL Server fetch failed for evidence ID {evidence_id!r}") from exc

    async def _check_cdc_enabled(self, table: str) -> bool:
        """Check if CDC is enabled for a table."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM cdc.change_tables
                    WHERE source_object_id = OBJECT_ID(?)
                    """,
                    f"{self.schema}.{table}",
                )
                row = await cursor.fetchone()
                return row[0] > 0 if row else False

    async def start_cdc_polling(self) -> None:
        """
        Start CDC polling for change detection.

        Requires CDC to be enabled on the database and tables:
        EXEC sys.sp_cdc_enable_db;
        EXEC sys.sp_cdc_enable_table @source_schema = 'dbo', @source_name = 'mytable', ...;
        """
        if not self.use_cdc:
            logger.warning("CDC not enabled for this connector")
            return

        logger.info("[SQL Server CDC] Starting CDC polling for %s", self.database)
        self._cdc_task = asyncio.create_task(self._poll_cdc_changes())

    async def _poll_cdc_changes(self) -> None:
        """Poll CDC tables for changes."""
        pool = await self._get_pool()
        tables = self.tables or await self._discover_tables()

        # Filter to CDC-enabled tables
        cdc_tables = []
        for table in tables:
            if await self._check_cdc_enabled(table):
                cdc_tables.append(table)
            else:
                logger.debug("[SQL Server CDC] Table %s not CDC-enabled, skipping", table)

        if not cdc_tables:
            logger.warning("[SQL Server CDC] No CDC-enabled tables found")
            return

        try:
            for _page in range(_MAX_PAGES):
                for table in cdc_tables:
                    await self._process_table_cdc_changes(pool, table)

                await asyncio.sleep(self.poll_interval_seconds)
            else:
                logger.warning("[SQL Server CDC] Polling safety cap reached")

        except asyncio.CancelledError:
            logger.info("[SQL Server CDC] Polling cancelled")
        except (OSError, ConnectionError, ValueError, RuntimeError) as exc:
            logger.error("[SQL Server CDC] Polling error: %s", exc)
            raise RuntimeError("SQL Server CDC polling failed") from exc

    async def _process_table_cdc_changes(self, pool: Any, table: str) -> None:
        """Process CDC changes for a single table."""
        # Get the CDC capture instance name
        capture_instance = f"{self.schema}_{table}"

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Get LSN range
                await cursor.execute("SELECT sys.fn_cdc_get_min_lsn(?)", capture_instance)
                min_lsn_row = await cursor.fetchone()
                min_lsn = min_lsn_row[0] if min_lsn_row else None

                await cursor.execute("SELECT sys.fn_cdc_get_max_lsn()")
                max_lsn_row = await cursor.fetchone()
                max_lsn = max_lsn_row[0] if max_lsn_row else None

                if not min_lsn or not max_lsn:
                    return

                # Use last processed LSN or min LSN
                from_lsn = self._last_lsn if self._last_lsn else min_lsn

                # Query CDC changes
                cdc_query = f"""
                    SELECT *
                    FROM cdc.fn_cdc_get_all_changes_{capture_instance}(?, ?, 'all')
                    ORDER BY __$start_lsn
                """  # internal query construction

                try:
                    await cursor.execute(cdc_query, from_lsn, max_lsn)
                except (OSError, ConnectionError, ValueError) as exc:
                    logger.exception("[SQL Server CDC] Failed to read changes for %s", table)
                    raise RuntimeError(
                        f"SQL Server CDC failed to read changes for table {table!r}"
                    ) from exc

                col_names = [desc[0] for desc in cursor.description]

                async for row in cursor:
                    row_dict = dict(zip(col_names, row))

                    # Map CDC operation codes
                    operation_code = row_dict.get("__$operation")
                    if operation_code == 1:
                        operation = ChangeOperation.DELETE
                    elif operation_code == 2:
                        operation = ChangeOperation.INSERT
                    elif operation_code in (3, 4):  # Before/after update
                        operation = ChangeOperation.UPDATE
                    else:
                        continue

                    # Remove CDC metadata columns from data
                    data = {k: v for k, v in row_dict.items() if not k.startswith("__$")}

                    event = ChangeEvent(
                        id="",
                        source_type=CDCSourceType.SQLSERVER,
                        connector_id=self.connector_id,
                        operation=operation,
                        timestamp=datetime.now(timezone.utc),
                        database=self.database,
                        schema=self.schema,
                        table=table,
                        data=data if operation != ChangeOperation.DELETE else None,
                        old_data=data if operation == ChangeOperation.DELETE else None,
                        primary_key={"id": data.get("id")},
                        resume_token=row_dict.get("__$start_lsn", b"").hex(),
                    )

                    await self.cdc_manager.process_event(event)

                # Update last processed LSN
                self._last_lsn = max_lsn

    async def start_change_tracking_polling(self) -> None:
        """
        Start Change Tracking polling for change detection.

        Lighter weight than CDC, requires:
        ALTER DATABASE [db] SET CHANGE_TRACKING = ON;
        ALTER TABLE [table] ENABLE CHANGE_TRACKING;
        """
        if not self.use_change_tracking:
            logger.warning("Change Tracking not enabled for this connector")
            return

        logger.info("[SQL Server CT] Starting Change Tracking polling for %s", self.database)
        self._cdc_task = asyncio.create_task(self._poll_change_tracking())

    async def _poll_change_tracking(self) -> None:
        """Poll Change Tracking for changes."""
        pool = await self._get_pool()
        tables = self.tables or await self._discover_tables()

        try:
            for _page in range(_MAX_PAGES):
                for table in tables:
                    await self._process_table_ct_changes(pool, table)

                await asyncio.sleep(self.poll_interval_seconds)
            else:
                logger.warning("[SQL Server CT] Polling safety cap reached")

        except asyncio.CancelledError:
            logger.info("[SQL Server CT] Polling cancelled")
        except (OSError, ConnectionError, ValueError, RuntimeError) as exc:
            logger.error("[SQL Server CT] Polling error: %s", exc)
            raise RuntimeError("SQL Server Change Tracking polling failed") from exc

    async def _process_table_ct_changes(self, pool: Any, table: str) -> None:
        """Process Change Tracking changes for a single table."""
        # Validate identifiers to prevent SQL injection
        safe_schema = _validate_sql_identifier(self.schema, "schema")
        safe_table = _validate_sql_identifier(table, "table")
        safe_pk_column = _validate_sql_identifier(self.primary_key_column, "column")

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Get minimum valid version
                await cursor.execute(
                    "SELECT CHANGE_TRACKING_MIN_VALID_VERSION(OBJECT_ID(?))",
                    f"{safe_schema}.{safe_table}",
                )
                min_version_row = await cursor.fetchone()
                min_version = min_version_row[0] if min_version_row else None

                if min_version is None:
                    logger.debug("[SQL Server CT] Change Tracking not enabled for %s", table)
                    return

                # Get current version
                await cursor.execute("SELECT CHANGE_TRACKING_CURRENT_VERSION()")
                current_version_row = await cursor.fetchone()
                current_version = current_version_row[0] if current_version_row else None

                if not current_version:
                    return

                # Query changes since last version
                last_version = getattr(self, f"_ct_version_{table}", min_version)

                ct_query = f"""
                    SELECT ct.SYS_CHANGE_OPERATION, ct.[{safe_pk_column}], t.*
                    FROM CHANGETABLE(CHANGES [{safe_schema}].[{safe_table}], ?) AS ct
                    LEFT JOIN [{safe_schema}].[{safe_table}] t
                        ON ct.[{safe_pk_column}] = t.[{safe_pk_column}]
                """  # table name interpolation, parameterized

                try:
                    await cursor.execute(ct_query, last_version)
                except (OSError, ConnectionError, ValueError) as exc:
                    logger.exception("[SQL Server CT] Failed to read changes for %s", table)
                    raise RuntimeError(
                        f"SQL Server Change Tracking failed to read changes for table {table!r}"
                    ) from exc

                col_names = [desc[0] for desc in cursor.description]

                async for row in cursor:
                    row_dict = dict(zip(col_names, row))

                    # Map Change Tracking operation codes
                    operation_code = row_dict.get("SYS_CHANGE_OPERATION")
                    if operation_code == "D":
                        operation = ChangeOperation.DELETE
                    elif operation_code == "I":
                        operation = ChangeOperation.INSERT
                    elif operation_code == "U":
                        operation = ChangeOperation.UPDATE
                    else:
                        continue

                    # Remove CT metadata
                    data = {k: v for k, v in row_dict.items() if not k.startswith("SYS_CHANGE_")}

                    event = ChangeEvent(
                        id="",
                        source_type=CDCSourceType.SQLSERVER,
                        connector_id=self.connector_id,
                        operation=operation,
                        timestamp=datetime.now(timezone.utc),
                        database=self.database,
                        schema=self.schema,
                        table=table,
                        data=data if operation != ChangeOperation.DELETE else None,
                        primary_key={
                            self.primary_key_column: row_dict.get(self.primary_key_column)
                        },
                    )

                    await self.cdc_manager.process_event(event)

                # Update last processed version
                setattr(self, f"_ct_version_{table}", current_version)

    async def stop_cdc_polling(self) -> None:
        """Stop CDC/Change Tracking polling."""
        if self._cdc_task:
            self._cdc_task.cancel()
            try:
                await self._cdc_task
            except asyncio.CancelledError:
                logger.debug("[SQL Server CDC/CT] Polling task cancelled during shutdown")
            self._cdc_task = None

        logger.info("[SQL Server CDC/CT] Stopped polling for %s", self.database)

    async def close(self) -> None:
        """Close connections and cleanup resources."""
        await self.stop_cdc_polling()

        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    async def health_check(self, timeout: float = 5.0) -> ConnectorHealth:
        """Check SQL Server connection health."""
        start_time = datetime.now(timezone.utc)
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    await cursor.fetchone()

            latency_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            return ConnectorHealth(
                name=self.name,
                is_available=True,
                is_configured=True,
                is_healthy=True,
                latency_ms=latency_ms,
                last_check=datetime.now(timezone.utc),
                metadata={
                    "database": self.database,
                    "schema": self.schema,
                    "host": self.host,
                    "cdc_enabled": self.use_cdc,
                    "change_tracking_enabled": self.use_change_tracking,
                },
            )
        except (OSError, RuntimeError, ValueError) as e:
            logger.exception("SQL Server health check failed")
            return ConnectorHealth(
                name=self.name,
                is_available=False,
                is_configured=True,
                is_healthy=False,
                error=f"{type(e).__name__}: {e}",
                last_check=datetime.now(timezone.utc),
                metadata={
                    "database": self.database,
                    "schema": self.schema,
                },
            )
