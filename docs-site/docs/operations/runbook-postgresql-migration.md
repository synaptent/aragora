---
title: PostgreSQL Migration Runbook
description: PostgreSQL Migration Runbook
---

# PostgreSQL Migration Runbook

**Purpose:** Zero-downtime migration from SQLite to PostgreSQL for production deployments.
**Audience:** DevOps, SRE, Platform Engineers
**Last Updated:** January 2026

---

## Overview

This runbook covers migrating Aragora from SQLite (default) to PostgreSQL for:
- Multi-instance deployments
- High availability requirements
- Enterprise-scale workloads

---

## Prerequisites

### Environment Requirements

| Requirement | Specification |
|-------------|---------------|
| PostgreSQL Version | 14+ (15 recommended) |
| Disk Space | 3x current SQLite database size |
| Downtime Window | 0 (zero-downtime migration) |
| Rollback Time | < 5 minutes |

### Access Requirements

- PostgreSQL superuser or CREATE DATABASE privilege
- Read access to SQLite databases
- Write access to application configuration
- Ability to restart application pods/processes

### Tools Required

```bash
# Install required tools
pip install psycopg2-binary alembic

# Verify PostgreSQL client
psql --version
```

---

## Pre-Migration Checklist

- [ ] PostgreSQL server provisioned and accessible
- [ ] Database user created with appropriate permissions
- [ ] Network connectivity verified from application servers
- [ ] Backup of all SQLite databases completed
- [ ] Maintenance window communicated (if needed)
- [ ] Rollback plan reviewed and tested
- [ ] Monitoring alerts configured for migration metrics

---

## Phase 1: Prepare PostgreSQL

### 1.1 Create Database and User

```sql
-- Connect as superuser
psql -h $PG_HOST -U postgres

-- Create database
CREATE DATABASE aragora
    ENCODING 'UTF8'
    LC_COLLATE 'en_US.UTF-8'
    LC_CTYPE 'en_US.UTF-8'
    TEMPLATE template0;

-- Create application user
CREATE USER aragora_app WITH PASSWORD 'secure_password_here';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE aragora TO aragora_app;

-- Connect to aragora database
\c aragora

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO aragora_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO aragora_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO aragora_app;
```

### 1.2 Configure Connection Pooling (Recommended)

```bash
# PgBouncer configuration for connection pooling
# /etc/pgbouncer/pgbouncer.ini

[databases]
aragora = host=localhost port=5432 dbname=aragora

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 20
min_pool_size = 5
reserve_pool_size = 5
```

### 1.3 Verify Connectivity

```bash
# Test connection
psql -h $PG_HOST -U aragora_app -d aragora -c "SELECT 1"

# Test from application server
python -c "
import psycopg2
conn = psycopg2.connect('postgresql://aragora_app:password@host:5432/aragora')
print('Connection successful')
conn.close()
"
```

---

## Phase 2: Schema Migration

### 2.1 Generate Schema

```bash
# Set environment variable for PostgreSQL
export DATABASE_URL="postgresql://aragora_app:password@host:5432/aragora"

# Run schema migrations
python -m aragora.persistence.migrations.postgres.run_migrations

# Verify tables created
psql $DATABASE_URL -c "\dt"
```

### 2.2 Schema Verification

```sql
-- Expected tables (minimum set)
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;

-- Should include:
-- debates
-- debate_messages
-- users
-- organizations
-- workspaces
-- audit_logs
-- elo_ratings
-- consensus_memory
-- knowledge_nodes
-- job_queue
-- ... (30+ tables)
```

---

## Phase 3: Data Migration

### 3.1 Backup SQLite Databases

```bash
# Create backup directory
mkdir -p /backup/sqlite_$(date +%Y%m%d)

# Copy all SQLite databases
cp .nomic/*.db /backup/sqlite_$(date +%Y%m%d)/

# Verify backups
ls -la /backup/sqlite_$(date +%Y%m%d)/
```

### 3.2 Run Data Migration

```bash
# Set both database URLs
export SQLITE_DIR=".nomic"
export DATABASE_URL="postgresql://aragora_app:password@host:5432/aragora"

# Run migration script
python scripts/migrate_databases.py \
    --source sqlite \
    --target postgresql \
    --batch-size 1000 \
    --parallel 4

# Expected output:
# [INFO] Starting migration...
# [INFO] Migrating debates: 15,234 records
# [INFO] Migrating users: 1,456 records
# [INFO] Migrating audit_logs: 892,341 records
# [INFO] Migration complete in 4m 32s
```

### 3.3 Verify Data Integrity

```bash
# Run verification script
python scripts/migrate_databases.py --verify

# Expected output:
# [INFO] Verifying data integrity...
# [INFO] debates: SQLite=15234, PostgreSQL=15234 ✓
# [INFO] users: SQLite=1456, PostgreSQL=1456 ✓
# [INFO] audit_logs: SQLite=892341, PostgreSQL=892341 ✓
# [INFO] All tables verified successfully
```

### 3.4 Verify Row Counts

```sql
-- Run on PostgreSQL
SELECT
    'debates' as table_name, COUNT(*) as count FROM debates
UNION ALL
SELECT 'users', COUNT(*) FROM users
UNION ALL
SELECT 'audit_logs', COUNT(*) FROM audit_logs
UNION ALL
SELECT 'elo_ratings', COUNT(*) FROM elo_ratings;
```

---

## Phase 4: Application Cutover

### 4.1 Blue-Green Deployment Approach

```yaml
# Kubernetes deployment strategy
# deploy/kubernetes/postgres-migration.yaml

apiVersion: apps/v1
kind: Deployment
metadata:
  name: aragora-postgres
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    spec:
      containers:
        - name: aragora
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: aragora-postgres-secrets
                  key: database-url
            - name: ARAGORA_DB_POOL_SIZE
              value: "20"
            - name: ARAGORA_DB_MAX_OVERFLOW
              value: "10"
```

### 4.2 Environment Configuration

```bash
# Update environment variables
export DATABASE_URL="postgresql://aragora_app:password@host:5432/aragora"
export ARAGORA_DB_POOL_SIZE=20
export ARAGORA_DB_MAX_OVERFLOW=10
export ARAGORA_DB_POOL_TIMEOUT=30

# Disable SQLite fallback in production
export ARAGORA_REQUIRE_DATABASE=true
```

### 4.3 Rolling Restart

```bash
# Kubernetes
kubectl rollout restart deployment/aragora

# Monitor rollout
kubectl rollout status deployment/aragora

# Docker Compose
docker-compose up -d --no-deps --build aragora
```

### 4.4 Health Check Verification

```bash
# Verify health endpoints
curl -s http://localhost:8080/api/health | jq '.checks.database'

# Expected response:
# {
#   "healthy": true,
#   "latency_ms": 2.3
# }

# Verify detailed health
curl -s http://localhost:8080/api/health/stores | jq '.stores'
```

---

## Phase 5: Post-Migration

### 5.1 Performance Tuning

```sql
-- Analyze all tables for query planner
ANALYZE;

-- Create additional indexes if needed
CREATE INDEX CONCURRENTLY idx_debates_created
    ON debates(created_at DESC);

CREATE INDEX CONCURRENTLY idx_audit_logs_timestamp
    ON audit_logs(timestamp DESC);

CREATE INDEX CONCURRENTLY idx_messages_debate
    ON debate_messages(debate_id, created_at);
```

### 5.2 Monitor Performance

```sql
-- Check slow queries
SELECT query, calls, mean_time, total_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;

-- Check table sizes
SELECT
    relname as table,
    pg_size_pretty(pg_total_relation_size(relid)) as total_size
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
```

### 5.3 Configure Backups

```bash
# Add PostgreSQL backup to cron
# /etc/cron.d/aragora-backup

# Daily full backup at 2 AM
0 2 * * * postgres pg_dump -Fc aragora > /backup/aragora_$(date +\%Y\%m\%d).dump

# Hourly WAL archiving
0 * * * * postgres pg_basebackup -D /backup/wal -Ft -z -P
```

---

## Rollback Procedure

If issues are encountered, roll back within 5 minutes:

### Immediate Rollback

```bash
# 1. Update environment to use SQLite
export DATABASE_URL=""
export ARAGORA_REQUIRE_DATABASE=false

# 2. Rolling restart
kubectl rollout restart deployment/aragora

# 3. Verify health
curl http://localhost:8080/api/health
```

### Restore from Backup

```bash
# If SQLite files were modified, restore from backup
cp /backup/sqlite_YYYYMMDD/*.db .nomic/

# Restart application
kubectl rollout restart deployment/aragora
```

---

## Troubleshooting

### Connection Issues

```bash
# Test network connectivity
nc -zv $PG_HOST 5432

# Check PostgreSQL logs
tail -f /var/log/postgresql/postgresql-15-main.log

# Verify pg_hba.conf allows connections
sudo cat /etc/postgresql/15/main/pg_hba.conf
```

### Performance Issues

```sql
-- Check for long-running queries
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active'
ORDER BY duration DESC;

-- Kill long-running query if needed
SELECT pg_terminate_backend(pid);

-- Check connection count
SELECT count(*) FROM pg_stat_activity;
```

### Data Inconsistency

```bash
# Re-run verification
python scripts/migrate_databases.py --verify --detailed

# Check specific table
python -c "
from aragora.persistence.postgres import get_session
from aragora.storage.models import Debate

with get_session() as session:
    count = session.query(Debate).count()
    print(f'PostgreSQL debates: {count}')
"
```

---

## Monitoring Checklist

Post-migration monitoring for 48 hours:

- [ ] Database connection pool utilization < 80%
- [ ] Query latency p99 < 100ms
- [ ] No connection timeouts in logs
- [ ] Disk I/O within expected range
- [ ] Memory usage stable
- [ ] No deadlocks reported
- [ ] Backup jobs completing successfully
- [ ] Replication lag < 1 second (if using replicas)

---

## Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | (required) |
| `ARAGORA_DB_POOL_SIZE` | Connection pool size | 10 |
| `ARAGORA_DB_MAX_OVERFLOW` | Max overflow connections | 5 |
| `ARAGORA_DB_POOL_TIMEOUT` | Connection timeout (seconds) | 30 |
| `ARAGORA_REQUIRE_DATABASE` | Fail if DB unavailable | false |

### Related Documentation

- [DATABASE_SETUP.md](../deployment/database-setup) - Initial database setup
- [DISASTER_RECOVERY.md](./disaster-recovery-runbook) - Recovery procedures
- [SCALING.md](../deployment/scaling) - Scaling guidelines
- [REDIS_HA.md](../deployment/redis-ha) - Redis high availability

---

**Document Owner:** Platform Team
**Review Cycle:** Quarterly
