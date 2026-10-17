---
title: Container Volume Requirements
description: Container Volume Requirements
---

# Container Volume Requirements

This document specifies the persistent storage requirements for containerized Aragora deployments.

## Overview

Aragora uses several data stores that require persistent volumes in containerized environments. Without proper volume mounts, data will be lost when containers restart.

## Required Volumes

### 1. Primary Data Directory

**Path:** `/data` (or `ARAGORA_DATA_DIR`)
**Default Host Path:** `~/.aragora/`
**Required:** Yes (for all deployments)

Contains:
- SQLite databases (when not using PostgreSQL)
- Local file storage
- Temporary processing files

```yaml
# Docker Compose
volumes:
  - aragora-data:/data

# Kubernetes
volumeMounts:
  - name: aragora-data
    mountPath: /data
```

### 2. Workflow Definitions

**Path:** `/data/workflows.db` or `ARAGORA_WORKFLOW_DB`
**Default:** `~/.aragora/workflows.db`
**Required:** Yes (if using workflows)

Stores workflow definitions and execution history.

```yaml
# Ensure included in primary data volume
# Or mount separately for backup isolation:
volumes:
  - aragora-workflows:/data/workflows
```

### 3. Knowledge Mound

**Path:** `/data/knowledge_mound.db`
**Default:** `.nomic/knowledge_mound.db`
**Required:** Yes (if using Knowledge Mound)

Stores organizational knowledge and embeddings.

```yaml
volumes:
  - aragora-knowledge:/data/knowledge
```

### 4. Job Queue

**Path:** `/data/job_queue.db`
**Default:** `.nomic/job_queue.db`
**Required:** Yes (for async job processing)

Stores pending and completed job metadata.

### 5. Decision Results

**Path:** `/data/decision_results.db`
**Default:** `~/.aragora/decision_results.db`
**Required:** Recommended (for decision audit trail)

Stores decision routing results for audit and replay.

### 6. Audit Logs

**Path:** `/data/audit/`
**Default:** `.nomic/audit/`
**Required:** Yes (for compliance)

Stores audit trail files.

```yaml
volumes:
  - aragora-audit:/data/audit
```

## Docker Compose Example

```yaml
version: '3.8'

services:
  aragora:
    image: aragora/aragora:latest
    environment:
      - ARAGORA_DATA_DIR=/data
      - ARAGORA_ENV=production
      - DATABASE_URL=postgresql://user:pass@db:5432/aragora
      - ARAGORA_REDIS_URL=redis://redis:6379/0
    volumes:
      # Primary data volume (required)
      - aragora-data:/data
      # Audit logs (compliance)
      - aragora-audit:/data/audit
      # Backups (optional)
      - ./backups:/backups:ro
    ports:
      - "8080:8080"
      - "8766:8766"

  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: aragora
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: aragora
    volumes:
      - postgres-data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes

volumes:
  aragora-data:
    driver: local
  aragora-audit:
    driver: local
  postgres-data:
    driver: local
  redis-data:
    driver: local
```

## Kubernetes Example

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: aragora-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: standard

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: aragora
spec:
  replicas: 1  # Single replica for SQLite; increase for PostgreSQL
  template:
    spec:
      containers:
        - name: aragora
          image: aragora/aragora:latest
          env:
            - name: ARAGORA_DATA_DIR
              value: /data
            - name: ARAGORA_ENV
              value: production
          volumeMounts:
            - name: data
              mountPath: /data
          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "2Gi"
              cpu: "1000m"
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: aragora-data
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ARAGORA_DATA_DIR` | Primary data directory | `~/.aragora` |
| `ARAGORA_WORKFLOW_DB` | Workflow database path | `$ARAGORA_DATA_DIR/workflows.db` |
| `ARAGORA_AUDIT_DIR` | Audit log directory | `$ARAGORA_DATA_DIR/audit` |
| `ARAGORA_TEMP_DIR` | Temporary file directory | `/tmp/aragora` |

## Storage Sizing Guidelines

| Component | Minimum | Recommended | Notes |
|-----------|---------|-------------|-------|
| Primary Data | 1 GB | 10 GB | Depends on debate volume |
| Knowledge Mound | 5 GB | 50 GB | Grows with knowledge ingestion |
| Audit Logs | 1 GB | 20 GB | 7-year retention requirement |
| PostgreSQL | 5 GB | 100 GB | For multi-instance deployments |
| Redis | 256 MB | 2 GB | Session and cache data |

## Multi-Instance Considerations

When running multiple Aragora instances:

1. **Use PostgreSQL** instead of SQLite for all stores
2. **Use Redis** for session storage and caching
3. **Use shared storage** (NFS, EFS, GCS) for file uploads only
4. **Do not share** SQLite databases between instances

```yaml
environment:
  # Required for multi-instance
  - DATABASE_URL=postgresql://...
  - ARAGORA_REDIS_URL=redis://...
  - ARAGORA_REQUIRE_DISTRIBUTED=true

  # Disable SQLite fallback
  - ARAGORA_STORAGE_MODE=postgres
```

## Backup Recommendations

### Daily Backups

```bash
# SQLite databases
sqlite3 /data/workflows.db ".backup '/backups/workflows_$(date +%Y%m%d).db'"
sqlite3 /data/knowledge_mound.db ".backup '/backups/km_$(date +%Y%m%d).db'"

# PostgreSQL
pg_dump -Fc $DATABASE_URL > /backups/aragora_$(date +%Y%m%d).dump
```

### Verify Backups

```bash
# Check SQLite integrity
sqlite3 /backups/workflows_*.db "PRAGMA integrity_check"

# Check PostgreSQL backup
pg_restore --list /backups/aragora_*.dump
```

## Troubleshooting

### Permission Issues

```bash
# Ensure container user can write to volumes
chown -R 1000:1000 /data

# Or run with specific user
docker run --user 1000:1000 ...
```

### Disk Space

```bash
# Check volume usage
docker system df -v

# Find large files
du -sh /data/*
```

### Database Locks

SQLite may lock files during writes. If experiencing lock issues:

1. Ensure single writer process
2. Use PostgreSQL for multi-process deployments
3. Check for orphaned lock files: `rm /data/*.db-journal`

## Related Documentation

- [DISASTER_RECOVERY.md](./disaster-recovery) - Backup and recovery procedures
- [RUNBOOK_DATABASE_ISSUES.md](../operations/runbook-database) - Database troubleshooting and recovery
- [SCALING.md](./scaling) - Scaling guidelines
