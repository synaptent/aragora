# Disaster Recovery Runbook

Comprehensive disaster recovery procedures for Aragora.

## Table of Contents

- [Recovery Objectives](#recovery-objectives)
- [Incident Classification](#incident-classification)
- [Backup Strategy](#backup-strategy)
- [Recovery Procedures](#recovery-procedures)
- [Service Recovery Checklist](#service-recovery-checklist)
- [Communication Templates](#communication-templates)
- [Post-Incident Review](#post-incident-review)

---

## Recovery Objectives

### Recovery Time Objective (RTO)

| Service Tier | RTO Target | Description |
|--------------|------------|-------------|
| Critical | < 1 hour | Core debate engine, authentication |
| High | < 4 hours | API endpoints, WebSocket streaming |
| Medium | < 8 hours | Analytics, leaderboards, telemetry |
| Low | < 24 hours | Historical data, archives |

### Recovery Point Objective (RPO)

| Data Type | RPO Target | Backup Frequency |
|-----------|------------|------------------|
| User accounts | < 1 hour | Continuous replication |
| Active debates | < 15 minutes | Transaction log shipping |
| Debate history | < 1 hour | Hourly snapshots |
| Agent ratings | < 1 hour | Hourly snapshots |
| Audit logs | < 24 hours | Daily backups |
| Telemetry | < 24 hours | Daily exports |

---

## Incident Classification

### Severity Levels

| Level | Name | Definition | Response Time |
|-------|------|------------|---------------|
| SEV-1 | Critical | Complete service outage, data loss risk | < 15 minutes |
| SEV-2 | High | Major functionality impaired | < 1 hour |
| SEV-3 | Medium | Partial service degradation | < 4 hours |
| SEV-4 | Low | Minor issues, workarounds exist | < 24 hours |

### Common Incident Types

| Type | Severity | Description |
|------|----------|-------------|
| Database corruption | SEV-1 | Data integrity compromised |
| Complete outage | SEV-1 | All services unavailable |
| Authentication failure | SEV-1 | Users cannot log in |
| Data breach | SEV-1 | Unauthorized data access |
| API degradation | SEV-2 | Slow or failing API calls |
| Agent failures | SEV-2 | LLM providers unavailable |
| Memory exhaustion | SEV-2 | Server OOM conditions |
| Partial outage | SEV-3 | Some features unavailable |
| Performance issues | SEV-3 | Slow response times |
| Scheduled maintenance | SEV-4 | Planned downtime |

---

## Backup Strategy

### Automated Backups

#### Database Backups

```bash
# SQLite backup (default)
# Location: .nomic/backups/
# Frequency: Hourly
# Retention: 14 days

# Verify backup schedule
ls -la .nomic/backups/

# Manual backup
python scripts/migrate_databases.py --backup
```

#### PostgreSQL Backups (Production)

```bash
# Continuous archiving (WAL)
archive_mode = on
archive_command = 'cp %p /backup/wal/%f'

# Full backup (daily)
pg_dump -Fc aragora > /backup/aragora_$(date +%Y%m%d).dump

# Point-in-time recovery enabled
restore_command = 'cp /backup/wal/%f %p'
```

#### Redis Backups

```bash
# RDB snapshots (default every 15 minutes)
save 900 1
save 300 10
save 60 10000

# AOF persistence
appendonly yes
appendfsync everysec

# Manual backup
redis-cli BGSAVE
cp /var/lib/redis/dump.rdb /backup/redis_$(date +%Y%m%d).rdb
```

### Backup Verification

#### Daily Verification Script

```bash
#!/bin/bash
# scripts/verify_backups.sh

set -e

echo "=== Backup Verification $(date) ==="

# 1. Check backup files exist
BACKUP_DIR=".nomic/backups"
LATEST_BACKUP=$(ls -t $BACKUP_DIR | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "ERROR: No backups found!"
    exit 1
fi

echo "Latest backup: $LATEST_BACKUP"

# 2. Verify backup age (should be < 24 hours old)
backup_mtime() {
    mtime=$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || true)
    case "$mtime" in
        ''|*[!0-9]*) return 1 ;;
    esac
    printf '%s\n' "$mtime"
}

BACKUP_PATH="$BACKUP_DIR/$LATEST_BACKUP"
BACKUP_MTIME=$(backup_mtime "$BACKUP_PATH") || {
    echo "ERROR: Could not read backup mtime: $BACKUP_PATH"
    exit 1
}
BACKUP_AGE=$(( ($(date +%s) - BACKUP_MTIME) / 3600 ))
if [ $BACKUP_AGE -gt 24 ]; then
    echo "WARNING: Backup is $BACKUP_AGE hours old!"
fi

# 3. Validate database integrity
echo "Validating database integrity..."
python scripts/migrate_databases.py --validate

# 4. Test restore to temporary location
TEMP_DIR=$(mktemp -d)
echo "Testing restore to $TEMP_DIR..."
cp -r "$BACKUP_DIR/$LATEST_BACKUP"/* "$TEMP_DIR/"

# 5. Verify restored data
sqlite3 "$TEMP_DIR/aragora_users.db" "SELECT COUNT(*) FROM users" > /dev/null
sqlite3 "$TEMP_DIR/aragora_debates.db" "SELECT COUNT(*) FROM debates" > /dev/null

echo "Restore verification: PASSED"

# Cleanup
rm -rf "$TEMP_DIR"

echo "=== Verification Complete ==="
```

#### Weekly Full Recovery Test

```bash
#!/bin/bash
# scripts/test_full_recovery.sh

# Run in isolated environment (Docker)
docker-compose -f docker-compose.recovery-test.yml up -d

# Restore from backup
docker exec aragora-recovery python scripts/migrate_databases.py --restore /backup/latest

# Run health checks
docker exec aragora-recovery curl -f http://localhost:8080/api/health

# Run integration tests
docker exec aragora-recovery pytest tests/integration/ -v --timeout=300

# Cleanup
docker-compose -f docker-compose.recovery-test.yml down -v
```

---

## Recovery Procedures

### Procedure 1: Database Recovery (SQLite)

**Scenario:** Database corruption or data loss

**Steps:**

1. **Stop the service**
   ```bash
   # Kubernetes
   kubectl scale deployment aragora --replicas=0

   # Systemd
   sudo systemctl stop aragora
   ```

2. **Assess damage**
   ```bash
   # Check database integrity
   sqlite3 .nomic/aragora_users.db "PRAGMA integrity_check"
   sqlite3 .nomic/aragora_debates.db "PRAGMA integrity_check"
   ```

3. **List available backups**
   ```bash
   ls -la .nomic/backups/
   # Output shows: backup_YYYYMMDD_HHMMSS/
   ```

4. **Restore from backup**
   ```bash
   # Move corrupted files
   mv .nomic/aragora_users.db .nomic/aragora_users.db.corrupted
   mv .nomic/aragora_debates.db .nomic/aragora_debates.db.corrupted

   # Restore from backup
   BACKUP="backup_20260113_100000"
   cp ".nomic/backups/$BACKUP/aragora_users.db" .nomic/
   cp ".nomic/backups/$BACKUP/aragora_debates.db" .nomic/
   ```

5. **Verify restoration**
   ```bash
   python scripts/migrate_databases.py --validate
   ```

6. **Restart service**
   ```bash
   kubectl scale deployment aragora --replicas=3
   # OR
   sudo systemctl start aragora
   ```

7. **Verify service health**
   ```bash
   curl http://localhost:8080/api/health
   ```

### Procedure 2: Database Recovery (PostgreSQL)

**Scenario:** PostgreSQL database failure

**Steps:**

1. **Stop application connections**
   ```bash
   kubectl scale deployment aragora --replicas=0
   ```

2. **Connect to PostgreSQL**
   ```bash
   psql -h $DB_HOST -U postgres
   ```

3. **Drop and recreate database** (if necessary)
   ```sql
   DROP DATABASE IF EXISTS aragora;
   CREATE DATABASE aragora;
   ```

4. **Restore from backup**
   ```bash
   # From pg_dump
   pg_restore -d aragora /backup/aragora_YYYYMMDD.dump

   # OR point-in-time recovery
   # Edit recovery.conf:
   restore_command = 'cp /backup/wal/%f %p'
   recovery_target_time = '2026-01-13 10:00:00'
   ```

5. **Run migrations**
   ```bash
   python scripts/migrate_databases.py --migrate
   ```

6. **Restart application**
   ```bash
   kubectl scale deployment aragora --replicas=3
   ```

### Procedure 3: Redis Recovery

**Scenario:** Redis data loss or corruption

**Steps:**

1. **Stop Redis**
   ```bash
   redis-cli SHUTDOWN NOSAVE
   ```

2. **Restore RDB snapshot**
   ```bash
   cp /backup/redis_YYYYMMDD.rdb /var/lib/redis/dump.rdb
   chown redis:redis /var/lib/redis/dump.rdb
   ```

3. **Start Redis**
   ```bash
   systemctl start redis
   ```

4. **Verify data**
   ```bash
   redis-cli INFO keyspace
   redis-cli DBSIZE
   ```

**Note:** Aragora automatically falls back to in-memory storage if Redis is unavailable. Rate limiting and session data may be temporarily reset.

### Procedure 4: Complete Service Recovery

**Scenario:** Total infrastructure failure

**Steps:**

1. **Provision infrastructure**
   ```bash
   # Terraform (if using IaC)
   cd terraform/
   terraform apply -auto-approve

   # OR Kubernetes
   kubectl apply -f k8s/
   ```

2. **Deploy application**
   ```bash
   # Build and push image
   docker build -t aragora:recovery .
   docker push registry/aragora:recovery

   # Deploy
   kubectl set image deployment/aragora aragora=registry/aragora:recovery
   ```

3. **Restore databases**
   ```bash
   # Follow database recovery procedures above
   ```

4. **Restore secrets**
   ```bash
   # From backup or secret manager
     kubectl create secret generic aragora-secrets \
       --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
       --from-literal=OPENAI_API_KEY=$OPENAI_API_KEY \
       --from-literal=ARAGORA_JWT_SECRET=$ARAGORA_JWT_SECRET
   ```

5. **Verify all services**
   ```bash
   # Health check
   curl http://aragora.example.com/api/health

   # Run smoke tests
   pytest tests/smoke/ -v
   ```

### Procedure 5: Security Incident Response

**Scenario:** Suspected data breach or security incident

**Steps:**

1. **Immediate containment**
   ```bash
   # Revoke all active sessions
   redis-cli FLUSHDB

   # Rotate JWT secret
   kubectl patch secret aragora-secrets -p '{"data":{"ARAGORA_JWT_SECRET":"'$(openssl rand -base64 32 | base64)'"}}'

   # Restart application (forces re-authentication)
   kubectl rollout restart deployment/aragora
   ```

2. **Preserve evidence**
   ```bash
   # Snapshot current state
   kubectl logs deployment/aragora > /evidence/logs_$(date +%Y%m%d_%H%M%S).log

   # Backup databases before any changes
   python scripts/migrate_databases.py --backup

   # Export audit logs
   sqlite3 .nomic/aragora_audit.db ".dump" > /evidence/audit_$(date +%Y%m%d).sql
   ```

3. **Investigate**
   ```bash
   # Review audit logs
   sqlite3 .nomic/aragora_audit.db "SELECT * FROM audit_log WHERE timestamp > datetime('now', '-24 hours')"

   # Check for suspicious activity
   grep -E "(failed|unauthorized|suspicious)" /evidence/logs_*.log
   ```

4. **Notify stakeholders**
   - Use communication templates below
   - Contact security@aragora.ai

5. **Remediate**
   - Patch vulnerability if identified
   - Reset affected user passwords
   - Update firewall rules if necessary

6. **Document**
   - Complete post-incident review
   - Update runbooks if needed

---

## Service Recovery Checklist

### Pre-Recovery

- [ ] Incident classified and severity assigned
- [ ] On-call personnel notified
- [ ] Communication sent to stakeholders
- [ ] Backup availability confirmed
- [ ] Recovery environment prepared

### During Recovery

- [ ] Services stopped gracefully
- [ ] Corrupted data preserved for analysis
- [ ] Backup restored successfully
- [ ] Data integrity verified
- [ ] Services restarted in correct order:
  1. [ ] Database (PostgreSQL/SQLite)
  2. [ ] Cache (Redis)
  3. [ ] Application servers
  4. [ ] Load balancer health checks passing

### Post-Recovery

- [ ] All health checks passing
- [ ] User authentication working
- [ ] Debate creation/retrieval functional
- [ ] WebSocket connections established
- [ ] Agent API calls successful
- [ ] Rate limiting operational
- [ ] Metrics and logging flowing
- [ ] Users notified of recovery
- [ ] Post-incident review scheduled

---

## Communication Templates

### Initial Incident Notification

```
Subject: [ARAGORA] Service Incident - [SEVERITY]

Team,

We are currently investigating an incident affecting Aragora services.

**Status:** Investigating
**Severity:** [SEV-1/SEV-2/SEV-3/SEV-4]
**Impact:** [Brief description of user impact]
**Started:** [Timestamp]

We will provide updates every [15/30/60] minutes.

Current actions:
- [Action 1]
- [Action 2]

Next update: [Timestamp]

---
Aragora Incident Response Team
```

### Status Update

```
Subject: [ARAGORA] Incident Update - [STATUS]

**Incident ID:** [ID]
**Status:** [Investigating/Identified/Monitoring/Resolved]
**Duration:** [X hours Y minutes]

**Update:**
[Description of current status and actions taken]

**Next Steps:**
- [Step 1]
- [Step 2]

**ETA to Resolution:** [Estimate or "TBD"]

Next update: [Timestamp]
```

### Resolution Notification

```
Subject: [ARAGORA] Incident Resolved - [BRIEF SUMMARY]

Team,

The incident affecting Aragora services has been resolved.

**Resolution Time:** [Timestamp]
**Total Duration:** [X hours Y minutes]
**Root Cause:** [Brief summary]

**Actions Taken:**
- [Action 1]
- [Action 2]

**Data Impact:**
- [Any data loss or recovery details]
- [Time range affected]

A post-incident review will be conducted within 48 hours.

---
Aragora Incident Response Team
```

### User-Facing Status Page

```
**Current Status: [Operational/Degraded/Outage]**

[Date] [Time] - [Update Message]

We are currently experiencing [issues with X / degraded performance / an outage].

Affected services:
- [Service 1]
- [Service 2]

What you may experience:
- [Symptom 1]
- [Symptom 2]

We are actively working to resolve this issue. Updates will be posted here.

Last updated: [Timestamp]
```

---

## Post-Incident Review

### Review Timeline

| Task | Deadline |
|------|----------|
| Incident timeline documented | 24 hours |
| Post-incident review meeting | 48 hours |
| Action items assigned | 72 hours |
| Root cause analysis complete | 1 week |
| Preventive measures implemented | 2 weeks |

### Review Template

```markdown
# Post-Incident Review: [Incident Title]

**Date:** [Date]
**Duration:** [X hours Y minutes]
**Severity:** [SEV-X]
**Author:** [Name]

## Summary
[1-2 paragraph summary of what happened]

## Timeline
| Time | Event |
|------|-------|
| HH:MM | [Event description] |
| HH:MM | [Event description] |

## Root Cause
[Detailed explanation of what caused the incident]

## Impact
- **Users affected:** [Number/percentage]
- **Data loss:** [Yes/No, details]
- **Revenue impact:** [If applicable]

## What Went Well
- [Item 1]
- [Item 2]

## What Could Be Improved
- [Item 1]
- [Item 2]

## Action Items
| Action | Owner | Due Date | Status |
|--------|-------|----------|--------|
| [Action] | [Name] | [Date] | [Open/Done] |

## Lessons Learned
[Key takeaways and recommendations]
```

---

## Emergency Contacts

| Role | Contact | Escalation Time |
|------|---------|-----------------|
| On-call Engineer | [PagerDuty/Slack] | Immediate |
| Engineering Lead | [Contact] | 15 minutes |
| Security Team | security@aragora.ai | SEV-1 only |
| Infrastructure | [Contact] | As needed |

---

## Component-Specific Recovery

### Knowledge Mound Recovery

**Scenario:** Knowledge Mound data loss or corruption

**Backup Procedures:**

```bash
# Knowledge Mound stores data in SQLite
# Location: .nomic/knowledge_mound.db

# Manual backup
sqlite3 .nomic/knowledge_mound.db ".backup '/backup/km_$(date +%Y%m%d_%H%M%S).db'"

# Verify backup integrity
sqlite3 /backup/km_*.db "PRAGMA integrity_check"
sqlite3 /backup/km_*.db "SELECT COUNT(*) FROM knowledge_nodes"
```

**Recovery Steps:**

1. **Stop KM operations**
   ```bash
   # Disable KM endpoints temporarily
   curl -X POST http://localhost:8080/api/admin/features/knowledge-mound/disable
   ```

2. **Restore from backup**
   ```bash
   mv .nomic/knowledge_mound.db .nomic/knowledge_mound.db.corrupted
   cp /backup/km_YYYYMMDD_HHMMSS.db .nomic/knowledge_mound.db
   ```

3. **Rebuild vector indices** (if needed)
   ```bash
   python -c "
   from aragora.knowledge.mound import get_knowledge_mound
   km = get_knowledge_mound()
   km.rebuild_indices()
   "
   ```

4. **Re-enable KM**
   ```bash
   curl -X POST http://localhost:8080/api/admin/features/knowledge-mound/enable
   ```

### Job Queue Recovery

**Scenario:** Interrupted jobs (transcription, routing, gauntlet)

The job queue system (`aragora/queue/`) automatically recovers interrupted jobs on startup. However, manual recovery may be needed after certain failures.

**Recovery Commands:**

```bash
# Check pending/interrupted jobs
python -c "
from aragora.queue.job_queue import JobQueueStore
store = JobQueueStore('.nomic/job_queue.db')
import asyncio

async def check():
    pending = await store.list_jobs(status='pending')
    processing = await store.list_jobs(status='processing')
    failed = await store.list_jobs(status='failed')
    print(f'Pending: {len(pending)}, Processing: {len(processing)}, Failed: {len(failed)}')

asyncio.run(check())
"

# Recover specific job types
python -c "
from aragora.queue.workers import recover_interrupted_transcriptions
from aragora.server.workers.gauntlet_worker import recover_interrupted_gauntlets
from aragora.server.workers.routing_worker import recover_interrupted_routing
import asyncio

async def recover():
    t = await recover_interrupted_transcriptions()
    g = await recover_interrupted_gauntlets()
    r = await recover_interrupted_routing()
    print(f'Recovered: {t} transcriptions, {g} gauntlets, {r} routing jobs')

asyncio.run(recover())
"

# Manually retry failed jobs
python -c "
from aragora.queue.job_queue import JobQueueStore
store = JobQueueStore('.nomic/job_queue.db')
import asyncio

async def retry_failed():
    failed = await store.list_jobs(status='failed')
    for job in failed:
        if job.retry_count < 3:
            await store.update_job_status(job.job_id, 'pending')
            print(f'Retried job {job.job_id}')

asyncio.run(retry_failed())
"
```

### Encrypted Secrets Recovery

**Scenario:** Encryption key loss or secrets corruption

**CRITICAL:** The encryption key (`ARAGORA_ENCRYPTION_KEY`) must be backed up securely. Without it, encrypted secrets cannot be recovered.

**Key Backup:**

```bash
# NEVER store encryption key in plain text alongside backups
# Use a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.)

# Example: Store in AWS Secrets Manager
aws secretsmanager create-secret \
  --name aragora/encryption-key \
  --secret-string "$ARAGORA_ENCRYPTION_KEY"

# Example: Store in HashiCorp Vault
vault kv put secret/aragora/encryption-key value="$ARAGORA_ENCRYPTION_KEY"
```

**Recovery Steps:**

1. **Retrieve encryption key from backup**
   ```bash
   # From AWS Secrets Manager
   export ARAGORA_ENCRYPTION_KEY=$(aws secretsmanager get-secret-value \
     --secret-id aragora/encryption-key \
     --query SecretString --output text)

   # From HashiCorp Vault
   export ARAGORA_ENCRYPTION_KEY=$(vault kv get -field=value secret/aragora/encryption-key)
   ```

2. **Verify key matches encrypted data**
   ```bash
   python -c "
   from aragora.security.encryption import get_encryption_service
   svc = get_encryption_service()
   # Will fail if key is wrong
   print('Encryption service initialized successfully')
   "
   ```

3. **If key is lost and secrets cannot be recovered:**
   - Generate new encryption key: `openssl rand -hex 32`
   - Users must re-enter sensitive credentials (API keys, tokens)
   - Update integration store entries with new encrypted values

### Debate Origin Recovery

**Scenario:** Lost debate origin mapping (debates not routed back to source)

Origin data (`aragora/server/debate_origin.py`) maps debates to their source (Slack, Discord, email, etc.).

**Recovery Steps:**

1. **Check origin store**
   ```bash
   python -c "
   from aragora.server.debate_origin import get_origin_store
   import asyncio

   async def check():
       store = get_origin_store()
       # SQLite-backed store
       count = await store.count()
       print(f'Stored origins: {count}')

   asyncio.run(check())
   "
   ```

2. **Rebuild from debate metadata** (partial recovery)
   ```bash
   python -c "
   from aragora.storage.debate_store import get_debate_store
   from aragora.server.debate_origin import get_origin_store, DebateOrigin
   import asyncio

   async def rebuild():
       debate_store = get_debate_store()
       origin_store = get_origin_store()

       debates = await debate_store.list_all()
       recovered = 0
       for d in debates:
           if d.metadata and 'source' in d.metadata:
               origin = DebateOrigin(
                   debate_id=d.debate_id,
                   platform=d.metadata['source'],
                   channel_id=d.metadata.get('channel_id'),
                   user_id=d.metadata.get('user_id'),
               )
               await origin_store.save(origin)
               recovered += 1
       print(f'Recovered {recovered} origins from debate metadata')

   asyncio.run(rebuild())
   "
   ```

### Consensus Healing Recovery

**Scenario:** Multiple stale or failed consensus states

The consensus healing worker (`aragora/memory/consensus_healing_worker.py`) automatically identifies and heals problematic consensus states.

**Manual Healing:**

```bash
# Start consensus healing with custom config
python -c "
from aragora.memory.consensus_healing_worker import (
    ConsensusHealingWorker,
    HealingConfig,
    HealingAction,
)
import asyncio

async def heal():
    config = HealingConfig(
        enabled=True,
        scan_interval_seconds=60,
        stale_threshold_hours=24,
        max_auto_actions_per_scan=10,
        allowed_actions=[
            HealingAction.RE_DEBATE,
            HealingAction.EXTEND_ROUNDS,
            HealingAction.ARCHIVE,
        ],
    )

    worker = ConsensusHealingWorker(config=config)

    # Single scan
    candidates = await worker._scan_for_candidates()
    print(f'Found {len(candidates)} healing candidates')

    for c in candidates:
        print(f'  - {c.debate_id}: {c.reason.value}')

asyncio.run(heal())
"

# Force archive old stale debates
python -c "
from aragora.memory.consensus_healing_worker import get_consensus_healing_worker
import asyncio

async def archive_stale():
    worker = get_consensus_healing_worker()
    results = await worker.force_archive_stale(older_than_days=30)
    print(f'Archived {len(results)} stale debates')

asyncio.run(archive_stale())
"
```

### Human Checkpoint Recovery

**Scenario:** Lost pending approvals after restart

Human checkpoints (`aragora/workflow/nodes/human_checkpoint.py`) now persist to GovernanceStore.

**Recovery Steps:**

```bash
# List all pending approvals
python -c "
from aragora.storage.governance_store import get_governance_store
import asyncio

async def list_pending():
    store = get_governance_store()
    pending = await store.list_approvals(status='pending')
    print(f'Pending approvals: {len(pending)}')
    for p in pending:
        print(f'  - {p.approval_id}: {p.title} (requested: {p.requested_at})')

asyncio.run(list_pending())
"

# Recover pending approvals on startup
python -c "
from aragora.workflow.nodes.human_checkpoint import HumanCheckpointNode
import asyncio

async def recover():
    node = HumanCheckpointNode()
    recovered = await node.recover_pending_approvals()
    print(f'Recovered {recovered} pending approvals')

asyncio.run(recover())
"
```

---

## Automated Recovery Integration

### Startup Recovery Hooks

Add to your application startup sequence:

```python
# aragora/server/startup.py

async def run_recovery_hooks():
    """Run automated recovery on startup."""
    from aragora.queue.workers import recover_interrupted_transcriptions
    from aragora.server.workers.gauntlet_worker import recover_interrupted_gauntlets
    from aragora.server.workers.routing_worker import recover_interrupted_routing
    from aragora.workflow.nodes.human_checkpoint import HumanCheckpointNode

    # Recover interrupted jobs
    await recover_interrupted_transcriptions()
    await recover_interrupted_gauntlets()
    await recover_interrupted_routing()

    # Recover pending approvals
    checkpoint = HumanCheckpointNode()
    await checkpoint.recover_pending_approvals()

    # Start consensus healing (background)
    from aragora.memory.consensus_healing_worker import start_consensus_healing
    await start_consensus_healing()
```

### Deployment Validation

Before accepting traffic after recovery, run deployment validation:

```bash
python -c "
from aragora.deploy.validator import validate_deployment, ValidationLevel
import asyncio

async def validate():
    result = await validate_deployment(level=ValidationLevel.FULL)
    if not result.passed:
        print('Deployment validation FAILED:')
        for check in result.checks:
            if not check.passed:
                print(f'  - {check.name}: {check.message}')
        exit(1)
    print('Deployment validation PASSED')

asyncio.run(validate())
"
```

---

## Disaster Recovery Testing Schedule

Regular DR testing ensures procedures remain valid and teams stay practiced.

### Testing Cadence

| Test Type | Frequency | Last Tested | Next Scheduled |
|-----------|-----------|-------------|----------------|
| Backup restoration | Monthly | - | TBD |
| Database failover | Quarterly | - | TBD |
| Full DR drill | Annually | - | TBD |
| Security incident drill | Quarterly | - | TBD |
| Communication drill | Quarterly | - | TBD |

### Monthly Backup Restoration Test

```bash
# 1. Select random backup from past week
BACKUP=$(ls -t .nomic/backups/ | shuf | head -1)

# 2. Restore to isolated environment
aragora backup restore $BACKUP --output /tmp/dr-test/aragora.db

# 3. Verify data integrity
sqlite3 /tmp/dr-test/aragora.db "PRAGMA integrity_check"
sqlite3 /tmp/dr-test/aragora.db "SELECT COUNT(*) FROM debates"

# 4. Document results
echo "$(date): Tested $BACKUP - PASSED" >> /var/log/dr-test.log

# 5. Cleanup
rm -rf /tmp/dr-test/
```

### Quarterly Failover Drill

1. Announce drill to team (30 min notice)
2. Simulate primary database failure
3. Execute failover procedure
4. Verify service restoration within RTO
5. Document time to recovery
6. Fail back to primary
7. Post-drill review meeting

### Annual Full DR Exercise

1. Schedule 4-hour window
2. Notify all stakeholders
3. Simulate complete infrastructure loss
4. Execute full recovery from backups
5. Verify all services operational
6. Measure RTO/RPO compliance
7. Document lessons learned
8. Update runbook as needed

---

## Programmatic Backup API

### BackupManager

The `BackupManager` provides comprehensive backup operations with verification:

```python
from aragora.backup.manager import (
    BackupManager,
    BackupType,
    RetentionPolicy,
)

# Initialize with custom retention
policy = RetentionPolicy(
    keep_daily=7,
    keep_weekly=4,
    keep_monthly=3,
    min_backups=1,
)

manager = BackupManager(
    backup_dir="/var/backups/aragora",
    retention_policy=policy,
    compression=True,
    verify_after_backup=True,
)

# Create backup
backup = manager.create_backup(
    source_path="/path/to/aragora.db",
    backup_type=BackupType.FULL,
    metadata={"reason": "pre-deployment"},
)
print(f"Backup created: {backup.id}, verified: {backup.verified}")

# Comprehensive verification
result = manager.verify_restore_comprehensive(backup.id)
print(f"Schema valid: {result.schema_validation.valid}")
print(f"Integrity valid: {result.integrity_check.valid}")
print(f"Table checksums valid: {result.table_checksums_valid}")

# Restore with dry run
manager.restore_backup(backup.id, "/path/to/restore.db", dry_run=True)

# Cleanup expired backups
deleted = manager.cleanup_expired()
print(f"Deleted {len(deleted)} expired backups")
```

### BackupScheduler

Automated backup scheduling with DR drill integration:

```python
from aragora.backup.scheduler import (
    BackupScheduler,
    BackupSchedule,
    start_backup_scheduler,
)
from datetime import time

# Configure schedule
schedule = BackupSchedule(
    hourly_minute=30,              # :30 every hour
    daily=time(2, 0),              # 2 AM daily
    weekly_day=6,                  # Sunday
    weekly_time=time(3, 0),        # 3 AM Sunday
    monthly_day=1,                 # 1st of month
    monthly_time=time(4, 0),       # 4 AM
    verify_after_backup=True,
    retention_cleanup_after=True,
    enable_dr_drills=True,
    dr_drill_interval_days=30,     # Monthly DR drills
)

# Start scheduler
scheduler = await start_backup_scheduler(backup_manager, schedule)

# Manual backup
job = await scheduler.backup_now(verify=True, cleanup=True)
print(f"Backup job: {job.id}, status: {job.status}")

# Get stats
stats = scheduler.get_stats()
print(f"Total: {stats.total_backups}, Success: {stats.successful_backups}")
print(f"Next daily: {stats.next_daily}")
```

### DRDrillScheduler

Automated DR drill scheduling for SOC 2 CC9 compliance:

```python
from aragora.scheduler.dr_drill_scheduler import (
    DRDrillScheduler,
    DRDrillConfig,
    DrillType,
    ComponentType,
    get_dr_drill_scheduler,
)

# Configure drills
config = DRDrillConfig(
    monthly_drill_day=15,             # 15th of each month
    quarterly_drill_months=[3, 6, 9, 12],
    annual_drill_month=1,             # January
    target_rto_seconds=3600,          # 1 hour
    target_rpo_seconds=300,           # 5 minutes
)

scheduler = DRDrillScheduler(config)
await scheduler.start()

# Manual drill execution
drill = await scheduler.execute_drill(
    drill_type=DrillType.BACKUP_RESTORATION,
    components=[ComponentType.DATABASE, ComponentType.OBJECT_STORAGE],
)

print(f"Drill: {drill.drill_id}")
print(f"Status: {drill.status.value}")
print(f"RTO: {drill.rto_seconds:.1f}s (target: {drill.target_rto_seconds}s)")
print(f"RPO: {drill.rpo_seconds:.1f}s (target: {drill.target_rpo_seconds}s)")
print(f"Compliant: {drill.is_compliant}")
print(f"Recommendations: {drill.recommendations}")

# Compliance report
report = scheduler.get_compliance_report()
print(f"Compliance rate: {report['compliance_rate']:.0%}")
print(f"Average RTO: {report['average_rto_seconds']:.0f}s")
```

### DR Drill CLI

```bash
# Full DR drill
python scripts/dr_drill.py --mode full \
  --api-url https://api.aragora.ai \
  --backup-dir /var/backups/aragora

# Backup verification only
python scripts/dr_drill.py --mode backup

# Failover testing only
python scripts/dr_drill.py --mode failover

# Generate report
python scripts/dr_drill.py --mode full --output dr_report.md
```

---

## SOC 2 Compliance

This runbook supports the following SOC 2 Trust Services Criteria:

| Control | Description | How Addressed |
|---------|-------------|---------------|
| CC9.1 | Business continuity planning | Automated DR drills, documented procedures |
| CC9.2 | Recovery testing | Monthly backup restoration, quarterly failover |
| A1.2 | Backup procedures | Automated daily/weekly/monthly backups |
| A1.3 | Recovery procedures | Step-by-step restore procedures |

### Compliance Metrics

Track these metrics for SOC 2 audits:

| Metric | Target | Measurement |
|--------|--------|-------------|
| RTO | < 1 hour | Measured during DR drills |
| RPO | < 5 minutes | Backup frequency verification |
| Backup verification rate | 100% | All backups verified after creation |
| DR drill success rate | > 95% | Monthly drill pass rate |
| Backup retention compliance | 100% | Retention policy enforcement |

---

## Related Documentation

- [SECURITY.md](../enterprise/SECURITY.md) - Security policies and incident response
- [TROUBLESHOOTING.md](../guides/TROUBLESHOOTING.md) - Common issues and solutions
- [RUNBOOK.md](RUNBOOK.md) - Operational procedures
- [DATABASE.md](../reference/DATABASE.md) - Database operations and encryption
- [SECRETS_MANAGEMENT.md](../enterprise/SECRETS_MANAGEMENT.md) - Encryption key management
- [QUEUE.md](../resilience/QUEUE.md) - Job queue operations
- [RBAC_MATRIX.md](../enterprise/RBAC_MATRIX.md) - Role-based access control permissions
