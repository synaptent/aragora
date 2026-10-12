"""
Migration Templates for Aragora Database Migrations.

Provides template generators for common migration patterns to ensure consistency
and reduce boilerplate when creating new migrations.

Templates Available:
- add_column_template: Add a new column with optional index
- add_index_template: Create an index (with CONCURRENTLY support)
- add_table_template: Create a new table with standard columns
- add_constraint_template: Add constraints (CHECK, UNIQUE, FK)
- data_migration_template: Template for data migrations
- composite_migration_template: Combine multiple operations

Usage:
    from aragora.migrations.templates import (
        generate_add_column_migration,
        generate_add_index_migration,
        generate_add_table_migration,
    )

    # Generate migration file content
    content = generate_add_column_migration(
        version=20260201120000,
        name="Add email_verified to users",
        table="users",
        column="email_verified",
        data_type="BOOLEAN",
        default="FALSE",
        create_index=True,
    )

    # Write to file
    Path("migrations/versions/v20260201120000_add_email_verified.py").write_text(content)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ColumnType(Enum):
    """Common column types with PostgreSQL and SQLite equivalents."""

    TEXT = ("TEXT", "TEXT")
    VARCHAR = ("VARCHAR", "TEXT")
    INTEGER = ("INTEGER", "INTEGER")
    BIGINT = ("BIGINT", "INTEGER")
    BOOLEAN = ("BOOLEAN", "INTEGER")  # SQLite doesn't have native BOOLEAN
    TIMESTAMP = ("TIMESTAMP", "TIMESTAMP")
    TIMESTAMPTZ = ("TIMESTAMPTZ", "TIMESTAMP")
    JSONB = ("JSONB", "TEXT")
    REAL = ("REAL", "REAL")
    UUID = ("UUID", "TEXT")

    @property
    def postgres(self) -> str:
        return self.value[0]

    @property
    def sqlite(self) -> str:
        return self.value[1]


@dataclass
class ColumnDefinition:
    """Definition for a table column."""

    name: str
    data_type: str | ColumnType
    nullable: bool = True
    default: str | None = None
    primary_key: bool = False
    unique: bool = False
    references: str | None = None  # "table_name(column)" for FK
    check: str | None = None  # CHECK constraint expression

    def to_sql(self, is_postgres: bool = True) -> str:
        """Generate SQL column definition."""
        if isinstance(self.data_type, ColumnType):
            dtype = self.data_type.postgres if is_postgres else self.data_type.sqlite
        else:
            dtype = self.data_type

        parts = [f'"{self.name}" {dtype}']

        if self.primary_key:
            parts.append("PRIMARY KEY")
        if not self.nullable and not self.primary_key:
            parts.append("NOT NULL")
        if self.default is not None:
            parts.append(f"DEFAULT {self.default}")
        if self.unique and not self.primary_key:
            parts.append("UNIQUE")
        if self.references:
            parts.append(f"REFERENCES {self.references}")
        if self.check:
            parts.append(f"CHECK ({self.check})")

        return " ".join(parts)


@dataclass
class IndexDefinition:
    """Definition for a table index."""

    name: str
    table: str
    columns: list[str]
    unique: bool = False
    where: str | None = None  # Partial index condition
    concurrently: bool = True  # PostgreSQL CONCURRENTLY option

    def to_create_sql(self, is_postgres: bool = True) -> str:
        """Generate CREATE INDEX SQL."""
        unique_str = "UNIQUE " if self.unique else ""
        concurrent_str = "CONCURRENTLY " if is_postgres and self.concurrently else ""
        cols = ", ".join(f'"{c}"' for c in self.columns)
        sql = f'CREATE {unique_str}INDEX {concurrent_str}IF NOT EXISTS "{self.name}" ON "{self.table}" ({cols})'
        if self.where:
            sql += f" WHERE {self.where}"
        return sql

    def to_drop_sql(self, is_postgres: bool = True) -> str:
        """Generate DROP INDEX SQL."""
        concurrent_str = "CONCURRENTLY " if is_postgres and self.concurrently else ""
        return f'DROP INDEX {concurrent_str}IF EXISTS "{self.name}"'


@dataclass
class TableDefinition:
    """Definition for a complete table."""

    name: str
    columns: list[ColumnDefinition]
    indexes: list[IndexDefinition] = field(default_factory=list)
    primary_key: list[str] | None = None  # Composite PK


# =============================================================================
# Template Generators
# =============================================================================


def generate_add_column_migration(
    version: int,
    name: str,
    table: str,
    column: str,
    data_type: str,
    nullable: bool = True,
    default: str | None = None,
    create_index: bool = False,
    index_name: str | None = None,
) -> str:
    """
    Generate a migration that adds a column to an existing table.

    Args:
        version: Migration version (timestamp format: YYYYMMDDHHmmss)
        name: Human-readable migration name
        table: Target table name
        column: Column name to add
        data_type: SQL data type (e.g., "TEXT", "INTEGER", "BOOLEAN")
        nullable: Whether column allows NULL (default: True for safety)
        default: Default value expression (e.g., "FALSE", "'pending'", "NOW()")
        create_index: Whether to create an index on the new column
        index_name: Custom index name (auto-generated if not provided)

    Returns:
        Complete migration file content as a string
    """
    idx_name = index_name or f"idx_{table}_{column}"

    index_create = ""
    index_drop = ""
    if create_index:
        index_create = f'''
        # Create index on new column
        safe_create_index(backend, "{idx_name}", "{table}", ["{column}"])'''
        index_drop = f'''safe_drop_index(backend, "{idx_name}")
        '''

    nullable_comment = "nullable" if nullable else "NOT NULL"
    default_comment = f" with default {default}" if default else ""

    return f'''"""
{name}

Migration created: {datetime.now().isoformat()}

This migration adds a {nullable_comment} column '{column}' to the '{table}' table{default_comment}.
{"It also creates an index for efficient querying." if create_index else ""}

Zero-Downtime Strategy:
1. Add column as nullable (safe, no table lock)
2. {"Backfill existing rows if needed" if default and not nullable else "No backfill needed"}
3. {"Add NOT NULL constraint in separate migration" if not nullable else "Column remains nullable"}
"""

import logging

from aragora.migrations.runner import Migration
from aragora.migrations.patterns import (
    safe_add_nullable_column,
    safe_drop_column,
    safe_create_index,
    safe_drop_index,
)
from aragora.storage.backends import DatabaseBackend

logger = logging.getLogger(__name__)


def up_fn(backend: DatabaseBackend) -> None:
    """Add {column} column to {table} table."""
    logger.info("Adding {column} column to {table}")
    safe_add_nullable_column(
        backend,
        "{table}",
        "{column}",
        "{data_type}",
        default={repr(default) if default else None},
    ){index_create}
    logger.info("Migration {version} applied successfully")


def down_fn(backend: DatabaseBackend) -> None:
    """Remove {column} column from {table} table."""
    logger.info("Removing {column} column from {table}")
    {index_drop}safe_drop_column(backend, "{table}", "{column}", verify_unused=False)
    logger.info("Migration {version} rolled back successfully")


migration = Migration(
    version={version},
    name="{name}",
    up_fn=up_fn,
    down_fn=down_fn,
)
'''


def generate_add_index_migration(
    version: int,
    name: str,
    table: str,
    columns: list[str],
    index_name: str | None = None,
    unique: bool = False,
    where_clause: str | None = None,
) -> str:
    """
    Generate a migration that creates an index.

    Args:
        version: Migration version
        name: Human-readable migration name
        table: Target table name
        columns: Column names to index
        index_name: Custom index name (auto-generated if not provided)
        unique: Whether to create a UNIQUE index
        where_clause: Partial index condition (PostgreSQL)

    Returns:
        Complete migration file content
    """
    cols_str = "_".join(columns)
    idx_name = index_name or f"idx_{table}_{cols_str}"
    unique_str = "unique " if unique else ""
    partial_str = f" (partial: {where_clause})" if where_clause else ""

    columns_arg = "[" + ", ".join(f'"{c}"' for c in columns) + "]"

    return f'''"""
{name}

Migration created: {datetime.now().isoformat()}

This migration creates a {unique_str}index on {table}({", ".join(columns)}){partial_str}.

The index is created with CONCURRENTLY option on PostgreSQL to avoid blocking writes.
"""

import logging

from aragora.migrations.runner import Migration
from aragora.migrations.patterns import safe_create_index, safe_drop_index
from aragora.storage.backends import DatabaseBackend

logger = logging.getLogger(__name__)


def up_fn(backend: DatabaseBackend) -> None:
    """Create index on {table}."""
    logger.info("Creating index {idx_name} on {table}")
    safe_create_index(
        backend,
        "{idx_name}",
        "{table}",
        {columns_arg},
        unique={unique},
        concurrently=True,
    )
    logger.info("Migration {version} applied successfully")


def down_fn(backend: DatabaseBackend) -> None:
    """Drop index from {table}."""
    logger.info("Dropping index {idx_name}")
    safe_drop_index(backend, "{idx_name}", concurrently=True)
    logger.info("Migration {version} rolled back successfully")


migration = Migration(
    version={version},
    name="{name}",
    up_fn=up_fn,
    down_fn=down_fn,
)
'''


def generate_add_table_migration(
    version: int,
    name: str,
    table: str,
    columns: list[dict[str, Any]],
    indexes: list[dict[str, Any]] | None = None,
    include_audit_columns: bool = True,
) -> str:
    """
    Generate a migration that creates a new table.

    Args:
        version: Migration version
        name: Human-readable migration name
        table: Table name to create
        columns: List of column definitions as dicts:
            {{"name": "col", "type": "TEXT", "nullable": True, "default": None}}
        indexes: List of index definitions as dicts:
            {{"columns": ["col"], "unique": False}}
        include_audit_columns: Add created_at and updated_at columns

    Returns:
        Complete migration file content
    """
    indexes = indexes or []

    # Build column definitions
    col_defs = []
    for col in columns:
        parts = [f'"{col["name"]}" {col["type"]}']
        if col.get("primary_key"):
            parts.append("PRIMARY KEY")
        if not col.get("nullable", True) and not col.get("primary_key"):
            parts.append("NOT NULL")
        if col.get("default") is not None:
            parts.append(f"DEFAULT {col['default']}")
        if col.get("unique") and not col.get("primary_key"):
            parts.append("UNIQUE")
        col_defs.append(" ".join(parts))

    # Add audit columns if requested
    if include_audit_columns:
        col_defs.append('"created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        col_defs.append('"updated_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP')

    columns_sql = ",\n                    ".join(col_defs)

    # Build index creation
    index_creates = []
    index_drops = []
    for idx in indexes:
        cols = idx.get("columns", [])
        if not cols:
            continue
        idx_name = idx.get("name", f"idx_{table}_{'_'.join(cols)}")
        unique = idx.get("unique", False)
        unique_str = "UNIQUE " if unique else ""

        cols_sql = ", ".join(f'"{c}"' for c in cols)
        index_creates.append(
            f'backend.execute_write(\'CREATE {unique_str}INDEX IF NOT EXISTS "{idx_name}" ON "{table}" ({cols_sql})\')'
        )
        index_drops.append(f"backend.execute_write('DROP INDEX IF EXISTS \"{idx_name}\"')")

    index_create_code = "\n        ".join(index_creates) if index_creates else "pass  # No indexes"
    index_drop_code = "\n        ".join(index_drops) if index_drops else ""

    return f'''"""
{name}

Migration created: {datetime.now().isoformat()}

This migration creates the '{table}' table.
"""

import logging

from aragora.migrations.runner import Migration
from aragora.storage.backends import DatabaseBackend

logger = logging.getLogger(__name__)


def up_fn(backend: DatabaseBackend) -> None:
    """Create {table} table."""
    logger.info("Creating {table} table")

    backend.execute_write("""
        CREATE TABLE IF NOT EXISTS "{table}" (
            {columns_sql}
        )
    """)

    # Create indexes
    {index_create_code}

    logger.info("Migration {version} applied successfully")


def down_fn(backend: DatabaseBackend) -> None:
    """Drop {table} table."""
    logger.info("Dropping {table} table")

    # Drop indexes first
    {index_drop_code}

    backend.execute_write('DROP TABLE IF EXISTS "{table}"')

    logger.info("Migration {version} rolled back successfully")


migration = Migration(
    version={version},
    name="{name}",
    up_fn=up_fn,
    down_fn=down_fn,
)
'''


def generate_data_migration_template(
    version: int,
    name: str,
    description: str,
) -> str:
    """
    Generate a template for data migrations (backfills, transformations).

    Args:
        version: Migration version
        name: Human-readable migration name
        description: Detailed description of the data migration

    Returns:
        Complete migration file content with backfill template
    """
    return f'''"""
{name}

Migration created: {datetime.now().isoformat()}

{description}

Data Migration Safety:
- Uses batched updates to avoid long locks
- Includes progress logging
- Idempotent: safe to re-run if interrupted
"""

import logging
import time

from aragora.migrations.runner import Migration
from aragora.migrations.patterns import backfill_column
from aragora.storage.backends import DatabaseBackend

logger = logging.getLogger(__name__)

# Configuration
BATCH_SIZE = 1000
SLEEP_BETWEEN_BATCHES = 0.1  # seconds


def up_fn(backend: DatabaseBackend) -> None:
    """Apply data migration."""
    logger.info("Starting data migration: {name}")

    # Example: Backfill a column
    # updated = backfill_column(
    #     backend,
    #     table="your_table",
    #     column="your_column",
    #     value="'default_value'",
    #     where_clause="status = 'active'",  # optional filter
    #     batch_size=BATCH_SIZE,
    #     sleep_between_batches=SLEEP_BETWEEN_BATCHES,
    # )
    # logger.info(f"Backfilled {{updated}} rows")

    # Example: Custom batched update
    # total_updated = 0
    # while True:
    #     result = backend.fetch_one(\"\"\"
    #         UPDATE your_table
    #         SET new_column = compute_value(old_column)
    #         WHERE new_column IS NULL
    #         LIMIT BATCH_SIZE
    #         RETURNING 1
    #     \"\"\")
    #     if not result:
    #         break
    #     total_updated += BATCH_SIZE
    #     logger.debug(f"Updated {{total_updated}} rows so far")
    #     time.sleep(SLEEP_BETWEEN_BATCHES)

    logger.info("Migration {version} applied successfully")


def down_fn(backend: DatabaseBackend) -> None:
    """Revert data migration (if possible).

    Note: Data migrations are often not fully reversible.
    This rollback should restore the previous state where feasible.
    """
    logger.info("Rolling back data migration: {name}")

    # Example: Reset backfilled column to NULL
    # backend.execute_write(\"\"\"
    #     UPDATE your_table SET your_column = NULL
    # \"\"\")

    logger.warning("Data migration {version} rolled back (data may be in intermediate state)")


migration = Migration(
    version={version},
    name="{name}",
    up_fn=up_fn,
    down_fn=down_fn,
)
'''  # template generates migration file, no user input


def generate_constraint_migration(
    version: int,
    name: str,
    table: str,
    constraint_type: str,
    constraint_name: str,
    definition: str,
) -> str:
    """
    Generate a migration that adds a constraint.

    Args:
        version: Migration version
        name: Human-readable migration name
        table: Target table name
        constraint_type: Type of constraint (CHECK, UNIQUE, FOREIGN KEY)
        constraint_name: Name for the constraint
        definition: Constraint definition (e.g., "rating >= 1 AND rating <= 5")

    Returns:
        Complete migration file content
    """
    constraint_type_upper = constraint_type.upper()

    if constraint_type_upper == "CHECK":
        add_sql = f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint_name}" CHECK ({definition})'
    elif constraint_type_upper == "UNIQUE":
        add_sql = f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint_name}" UNIQUE ({definition})'
    elif constraint_type_upper in ("FOREIGN KEY", "FK"):
        add_sql = (
            f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint_name}" FOREIGN KEY {definition}'
        )
    else:
        add_sql = f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint_name}" {constraint_type} ({definition})'

    return f'''"""
{name}

Migration created: {datetime.now().isoformat()}

This migration adds a {constraint_type_upper} constraint to the '{table}' table.

Constraint: {constraint_name}
Definition: {definition}

Note: Adding constraints may fail if existing data violates the constraint.
Consider running a data validation query first.
"""

import logging

from aragora.migrations.runner import Migration
from aragora.storage.backends import DatabaseBackend, PostgreSQLBackend

logger = logging.getLogger(__name__)


def _validate_existing_data(backend: DatabaseBackend) -> bool:
    """Check if existing data would violate the constraint."""
    # Implement validation logic specific to your constraint
    # Return True if data is valid, False otherwise
    return True


def up_fn(backend: DatabaseBackend) -> None:
    """Add {constraint_type_upper} constraint to {table}."""
    logger.info("Adding {constraint_type_upper} constraint '{constraint_name}' to {table}")

    # Validate existing data first
    if not _validate_existing_data(backend):
        raise ValueError(
            "Existing data would violate constraint '{constraint_name}'. "
            "Please fix the data before applying this migration."
        )

    is_postgres = isinstance(backend, PostgreSQLBackend)

    if is_postgres:
        # PostgreSQL: Use ALTER TABLE ADD CONSTRAINT
        backend.execute_write('{add_sql}')
    else:
        # SQLite: Limited constraint support
        # SQLite doesn't support adding constraints to existing tables
        # This is a no-op for SQLite; constraint would need table recreation
        logger.warning(
            "SQLite does not support ALTER TABLE ADD CONSTRAINT. "
            "The constraint will only be enforced on PostgreSQL."
        )

    logger.info("Migration {version} applied successfully")


def down_fn(backend: DatabaseBackend) -> None:
    """Remove {constraint_type_upper} constraint from {table}."""
    logger.info("Removing {constraint_type_upper} constraint '{constraint_name}' from {table}")

    is_postgres = isinstance(backend, PostgreSQLBackend)

    if is_postgres:
        backend.execute_write('ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{constraint_name}"')
    else:
        logger.warning("SQLite: Constraint was not added, nothing to remove")

    logger.info("Migration {version} rolled back successfully")


migration = Migration(
    version={version},
    name="{name}",
    up_fn=up_fn,
    down_fn=down_fn,
)
'''


# =============================================================================
# Migration File Generator
# =============================================================================


def create_migration_file(
    name: str,
    template_type: str = "basic",
    **kwargs: Any,
) -> tuple[str, str]:
    """
    Create a new migration file with the appropriate template.

    Args:
        name: Migration name (e.g., "Add email to users")
        template_type: One of: "basic", "add_column", "add_index", "add_table",
                       "data_migration", "constraint"
        **kwargs: Additional arguments passed to the template generator

    Returns:
        Tuple of (filename, content)
    """
    version = int(datetime.now().strftime("%Y%m%d%H%M%S"))

    # Sanitize name for filename
    name_slug = name.lower().replace(" ", "_").replace("-", "_")
    name_slug = re.sub(r"[^a-z0-9_]", "", name_slug)

    filename = f"v{version}_{name_slug}.py"

    if template_type == "add_column":
        content = generate_add_column_migration(version=version, name=name, **kwargs)
    elif template_type == "add_index":
        content = generate_add_index_migration(version=version, name=name, **kwargs)
    elif template_type == "add_table":
        content = generate_add_table_migration(version=version, name=name, **kwargs)
    elif template_type == "data_migration":
        content = generate_data_migration_template(
            version=version,
            name=name,
            description=kwargs.get("description", "Data migration"),
        )
    elif template_type == "constraint":
        content = generate_constraint_migration(version=version, name=name, **kwargs)
    else:
        # Basic template
        content = f'''"""
{name}

Migration created: {datetime.now().isoformat()}
"""

from aragora.migrations.runner import Migration

migration = Migration(
    version={version},
    name="{name}",
    up_sql="""
        -- Add your upgrade SQL here
    """,
    down_sql="""
        -- Add your rollback SQL here (optional but recommended)
    """,
)
'''

    return filename, content


__all__ = [
    "ColumnType",
    "ColumnDefinition",
    "IndexDefinition",
    "TableDefinition",
    "generate_add_column_migration",
    "generate_add_index_migration",
    "generate_add_table_migration",
    "generate_data_migration_template",
    "generate_constraint_migration",
    "create_migration_file",
]
