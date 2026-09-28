# Aragora Database Migration Guide

This guide documents the database migration framework for Aragora.

## Quick Start

```bash
# Check migration status
python -m aragora.migrations status

# Apply all pending migrations
python -m aragora.migrations upgrade

# Rollback the last migration
python -m aragora.migrations downgrade

# Rollback last 3 migrations
python -m aragora.migrations downgrade --steps 3

# Preview rollback without executing
python -m aragora.migrations downgrade --dry-run

# Create a new migration
python -m aragora.migrations create "Add email to users"
```

## Migration Framework Overview

Aragora uses a custom migration framework built on top of Alembic concepts but with
additional features for zero-downtime deployments and enterprise requirements.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| Runner | `aragora/migrations/runner.py` | Core migration execution engine |
| Patterns | `aragora/migrations/patterns.py` | Zero-downtime migration patterns |
| Templates | `aragora/migrations/templates.py` | Migration file generators |
| CLI | `aragora/migrations/__main__.py` | Command-line interface |
| Versions | `aragora/migrations/versions/` | Migration files |

### Migration File Naming

Migrations use timestamp-based versioning: `v{YYYYMMDDHHmmss}_{name}.py`

Example: `v20260201000000_add_debate_metrics_indexes.py`

## Creating Migrations

### Using Templates (Recommended)

```python
from aragora.migrations.templates import create_migration_file
from pathlib import Path

# Create add column migration
filename, content = create_migration_file(
    name="Add email verified to users",
    template_type="add_column",
    table="users",
    column="email_verified",
    data_type="BOOLEAN",
    default="FALSE",
    create_index=True,
)

# Write to file
Path(f"aragora/migrations/versions/{filename}").write_text(content)
```

### Available Templates

| Template Type | Use Case |
|---------------|----------|
| `basic` | Simple SQL migrations |
| `add_column` | Add a column with optional index |
| `add_index` | Create indexes (with CONCURRENTLY support) |
| `add_table` | Create new tables with columns and indexes |
| `data_migration` | Backfill data with batching |
| `constraint` | Add CHECK, UNIQUE, or FK constraints |

### Manual Migration Creation

```python
"""
Add email verified column to users.

Migration created: 2026-02-01T12:00:00
"""

from aragora.migrations.runner import Migration
from aragora.migrations.patterns import safe_add_nullable_column, safe_drop_column

def up_fn(backend):
    safe_add_nullable_column(backend, "users", "email_verified", "BOOLEAN", default="FALSE")

def down_fn(backend):
    safe_drop_column(backend, "users", "email_verified", verify_unused=False)

migration = Migration(
    version=20260201120000,
    name="Add email verified to users",
    up_fn=up_fn,
    down_fn=down_fn,
)
```

## Zero-Downtime Patterns

### Adding Columns

**Safe**: Add nullable columns
```python
safe_add_nullable_column(backend, "users", "email", "TEXT")
```

**Risky**: Adding NOT NULL without default
- Add as nullable first
- Backfill data
- Add NOT NULL constraint in separate migration

### Removing Columns (Expand/Contract)

1. **Expand Phase**: Stop writing to column (code change)
2. **Wait**: Ensure all code is deployed
3. **Contract Phase**: Drop column

```python
safe_drop_column(backend, "users", "old_column", verify_unused=True)
```

### Creating Indexes

```python
# PostgreSQL: Uses CONCURRENTLY to avoid blocking
safe_create_index(backend, "idx_users_email", "users", ["email"], concurrently=True)
```

### Data Migrations

```python
from aragora.migrations.patterns import backfill_column

# Batch updates to avoid locking
backfill_column(
    backend,
    table="users",
    column="status",
    value="'active'",
    where_clause="status IS NULL",
    batch_size=1000,
    sleep_between_batches=0.1,
)
```

## Rollback Procedures

### Validation Before Rollback

```python
from aragora.migrations import get_migration_runner

runner = get_migration_runner()
validation = runner.validate_rollback(steps=2)

if not validation.safe:
    print("Rollback blocked:", validation.errors)
else:
    runner.rollback_steps(steps=2, reason="Bug found in migration")
```

### Rollback History

All rollbacks are logged for audit:
```bash
python -m aragora.migrations rollback-history
```

### Emergency Rollback

```bash
# Rollback with reason (stored in audit log)
python -m aragora.migrations downgrade --steps 1 --reason "Production incident #123"
```

## Database Support

### PostgreSQL (Production)

- Full CONCURRENTLY support for index operations
- Advisory locking for migration coordination
- JSONB for metadata columns
- Native BOOLEAN type

### SQLite (Development/Testing)

- Automatic dialect translation
- Limited ALTER TABLE support
- TEXT for JSONB columns
- INTEGER for BOOLEAN

## Testing Migrations

### Unit Tests

```python
def test_migration_forward_and_rollback(backend):
    from aragora.migrations.versions.v20260201000000_my_migration import up_fn, down_fn

    # Forward
    up_fn(backend)
    assert backend.table_exists("my_table")

    # Rollback
    down_fn(backend)
    assert not backend.table_exists("my_table")
```

### Idempotency Tests

```python
def test_migration_is_idempotent(backend):
    from aragora.migrations.versions.v20260201000000_my_migration import up_fn

    # Should not raise when run twice
    up_fn(backend)
    up_fn(backend)
```

### Integration Tests

```python
def test_full_migration_cycle(runner, backend):
    runner.upgrade()
    assert backend.table_exists("expected_table")

    runner.downgrade()
    assert not backend.table_exists("expected_table")
```

## Best Practices

### DO

- Always provide `down_fn` or `down_sql` for rollback
- Use `safe_*` pattern functions for schema changes
- Index tables the migration did not create with `create_index_if_columns_exist`
  (or check `get_missing_columns`): the app's stores create tables at startup,
  and their shape can lack columns the migration assumes
- Test migrations on a copy of production data
- Include data validation before applying constraints
- Use batched updates for data migrations
- Log progress for long-running migrations

### DON'T

- Modify existing migrations that have been applied. The one exception is a fix
  that changes the outcome only where the old version could not apply
  correctly (it failed, or built something meaningless). Add the old checksum
  to `previous_checksums` on its `Migration`: databases that applied the old
  version still verify, and later edits are still detected
- Add NOT NULL columns without defaults to tables with data
- Drop columns that might still be referenced
- Create indexes without CONCURRENTLY on large tables
- Skip rollback testing

## Migration Status Tracking

The framework tracks applied migrations in the `_aragora_migrations` table:

| Column | Type | Description |
|--------|------|-------------|
| version | INTEGER | Migration version (timestamp) |
| name | TEXT | Human-readable name |
| applied_at | TIMESTAMP | When migration was applied |
| applied_by | TEXT | hostname:pid of applying process |

Rollback history is stored in `_aragora_rollback_history`.

## Troubleshooting

### Migration Failed Halfway

1. Check the error message
2. Fix the underlying issue
3. Run upgrade again (migrations track partial state)

### Locked Migrations

PostgreSQL uses advisory locks to prevent concurrent migrations:
```sql
SELECT pg_advisory_unlock(12345678);  -- Release stuck lock
```

### Version Conflicts

If two developers create migrations with the same timestamp:
1. Rename one migration file with a later timestamp
2. Update the version number inside the file

## Current Migrations

| Version | Name | Description |
|---------|------|-------------|
| 20240101000000 | Initial schema | Core tables |
| 20260119000000 | KM visibility | Knowledge Mound access grants |
| 20260120000000 | Channel governance | Channel governance stores |
| 20260120100000 | Marketplace webhooks | Marketplace and webhook batch tables |
| 20260201000000 | Debate metrics indexes | Performance indexes for queries |
| 20260201000100 | Agent performance | Agent performance tracking table |
| 20260201000200 | Decision receipts | Cryptographic audit trail |
| 20260201000300 | Rate limiting | Rate limit tracking tables |
| 20260201000400 | Session management | User session tables |
