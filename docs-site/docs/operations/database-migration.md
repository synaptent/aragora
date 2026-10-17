---
title: Database Migration Runbook
description: Database Migration Runbook
---

# Database Migration Runbook

Procedures for schema updates and database migrations.

## Pre-Migration Checklist

- [ ] Backup completed and verified
- [ ] Migration tested in staging
- [ ] Rollback script prepared
- [ ] Maintenance window scheduled
- [ ] Team notified
- [ ] Monitoring dashboards open

---

## Backup Before Migration

```bash
# PostgreSQL dump
pg_dump -h $DB_HOST -U $DB_USER -d aragora -F c -f backup_$(date +%Y%m%d_%H%M%S).dump

# Verify backup
pg_restore --list backup_*.dump | head -20

# AWS RDS snapshot
aws rds create-db-snapshot \
  --db-instance-identifier aragora \
  --db-snapshot-identifier aragora-pre-migration-$(date +%Y%m%d)
```

---

## Running Migrations

### Alembic (Python)

```bash
# Check current revision
alembic current

# Check pending migrations
alembic history --indicate-current

# Run migrations
alembic upgrade head

# Run specific migration
alembic upgrade abc123

# Generate new migration
alembic revision --autogenerate -m "Add user_preferences table"
```

### Kubernetes Job

```yaml
# migration-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: aragora-migration
  namespace: aragora
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: aragora/api:latest
        command: ["alembic", "upgrade", "head"]
        envFrom:
        - secretRef:
            name: aragora-secrets
      restartPolicy: Never
  backoffLimit: 0
```

```bash
kubectl apply -f migration-job.yaml
kubectl logs -f job/aragora-migration -n aragora
```

### Docker Compose

```bash
# Run migration container
docker compose run --rm aragora-api alembic upgrade head
```

---

## Zero-Downtime Migrations

### Safe Migration Pattern

1. **Add new column/table** (nullable, with defaults)
2. **Deploy code** that writes to both old and new
3. **Backfill data** in new column/table
4. **Deploy code** that reads from new
5. **Remove old column/table** (after verification period)

### Example: Rename Column

```python
# Step 1: Add new column
def upgrade():
    op.add_column('users', sa.Column('display_name', sa.String(255)))

# Step 2: Backfill (run separately)
# UPDATE users SET display_name = name WHERE display_name IS NULL;

# Step 3: Make new column not null (after backfill)
def upgrade():
    op.alter_column('users', 'display_name', nullable=False)

# Step 4: Remove old column (after code deployment)
def upgrade():
    op.drop_column('users', 'name')
```

### Large Table Migration

```python
# Use batched updates for large tables
def upgrade():
    conn = op.get_bind()

    # Add column
    op.add_column('large_table', sa.Column('new_field', sa.String(255)))

    # Backfill in batches
    batch_size = 10000
    offset = 0

    while True:
        result = conn.execute(text(f"""
            UPDATE large_table
            SET new_field = compute_value(old_field)
            WHERE id IN (
                SELECT id FROM large_table
                WHERE new_field IS NULL
                ORDER BY id
                LIMIT {batch_size}
            )
        """))

        if result.rowcount == 0:
            break

        offset += batch_size
        time.sleep(0.1)  # Rate limit
```

---

## Rollback Procedures

### Alembic Rollback

```bash
# Rollback one migration
alembic downgrade -1

# Rollback to specific revision
alembic downgrade abc123

# Rollback all
alembic downgrade base
```

### Restore from Backup

```bash
# Stop application
kubectl scale deployment aragora-api -n aragora --replicas=0

# Restore from dump
pg_restore -h $DB_HOST -U $DB_USER -d aragora -c backup_20240101_120000.dump

# Or restore from RDS snapshot
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier aragora-restored \
  --db-snapshot-identifier aragora-pre-migration-20240101

# Restart application
kubectl scale deployment aragora-api -n aragora --replicas=3
```

---

## Common Issues

### Lock Timeout

```sql
-- Check for blocking queries
SELECT pid, age(clock_timestamp(), query_start), usename, query, state
FROM pg_stat_activity
WHERE state != 'idle'
AND query NOT ILIKE '%pg_stat_activity%'
ORDER BY query_start;

-- Set lock timeout
SET lock_timeout = '10s';

-- Kill blocking query if needed
SELECT pg_terminate_backend(pid);
```

### Long-Running Migration

```sql
-- Monitor migration progress
SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum
FROM pg_stat_user_tables
WHERE relname = 'table_name';

-- Check index creation progress
SELECT phase, blocks_total, blocks_done, tuples_total, tuples_done
FROM pg_stat_progress_create_index;
```

### Connection Exhaustion

```bash
# Check connections
SELECT count(*) FROM pg_stat_activity;

# Kill idle connections
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle'
AND query_start < now() - interval '10 minutes';
```

---

## Verification

```bash
# Verify schema
psql -h $DB_HOST -U $DB_USER -d aragora -c "\d+ table_name"

# Check migration history
alembic history --indicate-current

# Run smoke tests
pytest tests/integration/test_database.py -v

# Check application health
curl http://aragora.company.com/health
```

---

## Emergency Contacts

| Role | Contact |
|------|---------|
| DBA On-Call | dba-oncall@company.com |
| Platform Team | #platform-oncall (Slack) |
| Incident Manager | incident@company.com |

---

## See Also

- [Incident Response Runbook](./incident-response-procedures)
- [Backup and Recovery](../enterprise/features)
