# Aragora Operations Runbook

This document provides operational guidance for running, monitoring, and troubleshooting Aragora in production.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Server Management](#server-management)
3. [Monitoring & Observability](#monitoring--observability)
4. [Admin Console & Developer Portal](#admin-console--developer-portal)
5. [Common Issues & Debugging](#common-issues--debugging)
6. [Scaling Guide](#scaling-guide)
7. [Incident Response](#incident-response)
8. [Database Operations](#database-operations)
9. [Backup & Recovery](#backup--recovery)
10. [Storage Cleanup](#storage-cleanup)
11. [Knowledge Mound Operations](#knowledge-mound-operations)
12. [Security & Governance Hardening](#security--governance-hardening)
13. [Decision Router Cache Invalidation](#decision-router-cache-invalidation)
14. [Webhook Delivery Manager](#webhook-delivery-manager)
15. [Integration Store Metrics](#integration-store-metrics)

---

## Quick Start

### Starting the Server

```bash
# Production mode
aragora serve --api-port 8080 --ws-port 8765

# Development mode (same entrypoint; use env vars for local tuning)
aragora serve --api-port 8080 --ws-port 8765

# With custom data directory
ARAGORA_DATA_DIR=/data/aragora aragora serve --api-port 8080 --ws-port 8765
```

### Verifying Server Health

```bash
# HTTP health check
curl http://localhost:8080/api/health

# Expected response:
# {"status": "healthy", "version": "1.0.0", "uptime": 3600}

# WebSocket health check (public endpoint, no auth required)
curl http://localhost:8080/api/health/ws

# Expected response:
# {"status": "healthy", "clients": 5}
# or when unavailable:
# {"status": "unavailable", "clients": 0, "message": "WebSocket manager not configured"}

# WebSocket connectivity test
wscat -c ws://localhost:8765/ws
```

### Environment Variables

**AI Providers** (at least one required):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | - | Anthropic Claude API key |
| `OPENAI_API_KEY` | Yes* | - | OpenAI API key |
| `OPENROUTER_API_KEY` | No | - | Fallback provider (auto-used on 429) |
| `MISTRAL_API_KEY` | No | - | Mistral API key |
| `GEMINI_API_KEY` | No | - | Google Gemini API key |
| `XAI_API_KEY` | No | - | xAI Grok API key |

**Server Configuration**:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARAGORA_DATA_DIR` | No | `.nomic` | Runtime data directory (databases, backups) |
| `ARAGORA_API_TOKEN` | No | - | API authentication token |
| `ARAGORA_ALLOWED_ORIGINS` | No | See ENVIRONMENT.md | CORS allowed origins (wildcard disallowed) |
| `ARAGORA_LOG_LEVEL` | No | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |

**Authentication** (required for production):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARAGORA_JWT_SECRET` | Prod | - | Secret for JWT signing (min 32 chars) |
| `ARAGORA_JWT_EXPIRY_HOURS` | No | `24` | Token expiration in hours |
| `ARAGORA_REFRESH_TOKEN_EXPIRY_DAYS` | No | `30` | Refresh token expiration in days |
| `GOOGLE_OAUTH_CLIENT_ID` | No | - | Google OAuth client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | No | - | Google OAuth client secret |
| `GOOGLE_OAUTH_REDIRECT_URI` | No | - | OAuth callback URL |
| `OAUTH_SUCCESS_URL` | No | - | Post-login redirect |
| `OAUTH_ERROR_URL` | No | - | Auth error redirect |
| `OAUTH_ALLOWED_REDIRECT_HOSTS` | No | - | Allowed redirect hosts |

**Persistence** (optional):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUPABASE_URL` | No | - | Supabase project URL |
| `SUPABASE_KEY` | No | - | Supabase anon key |
| `ARAGORA_REDIS_URL` | No | - | Redis URL for distributed caching |

*At least one AI provider key is required.

---

## Server Management

### Process Supervision

Use systemd for production deployments:

```ini
# /etc/systemd/system/aragora.service
[Unit]
Description=Aragora Multi-Agent Debate Server
After=network.target

[Service]
Type=simple
User=aragora
WorkingDirectory=/opt/aragora
Environment=PYTHONPATH=/opt/aragora
EnvironmentFile=/opt/aragora/.env
ExecStart=/opt/aragora/venv/bin/aragora serve --api-port 8080 --ws-port 8765
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl enable aragora
sudo systemctl start aragora

# Check status
sudo systemctl status aragora

# View logs
journalctl -u aragora -f
```

### Graceful Shutdown

The server handles SIGTERM gracefully:

```bash
# Graceful shutdown (waits for active debates to complete)
kill -TERM $(pgrep -f "aragora.server")

# Force shutdown (immediate)
kill -9 $(pgrep -f "aragora.server")
```

---

## Monitoring & Observability

### Prometheus Metrics

Metrics are exposed at `/api/metrics`:

```bash
curl http://localhost:8080/api/metrics
```

Key metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `aragora_debates_total` | Counter | Total debates started |
| `aragora_debates_completed` | Counter | Completed debates |
| `aragora_agent_latency_seconds` | Histogram | Agent response latency |
| `aragora_agent_tokens_total` | Counter | Total tokens consumed |
| `aragora_fallback_activations_total` | Counter | Fallback activations |
| `aragora_fallback_success_total` | Counter | Fallback outcomes |
| `aragora_fallback_latency_seconds` | Histogram | Fallback latency |
| `aragora_websocket_connections` | Gauge | Active WebSocket connections |
| `aragora_circuit_breaker_state` | Gauge | Circuit breaker status per agent |

### Grafana Dashboard

Import the provided dashboards:

```bash
# Dashboard files at:
deploy/grafana/dashboards/
  ├── debate-metrics.json      # Debate success rates, rounds, outcomes
  ├── api-latency.json         # API endpoint latency tracking
  ├── agent-performance.json   # Agent response times and errors
  └── slo-tracking.json        # Service level objectives
```

### Log Levels

Set log level via environment:

```bash
export ARAGORA_LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR
```

Log output includes:
- Request correlation IDs (`X-Request-ID`)
- Debate IDs in all related log lines
- Agent response times and token counts

### Alerting Rules

Recommended Prometheus alerting rules:

```yaml
groups:
  - name: aragora
    rules:
      - alert: HighAgentLatency
        expr: histogram_quantile(0.95, aragora_agent_response_seconds) > 30
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent response time > 30s at p95"

      - alert: CircuitBreakerOpen
        expr: aragora_circuit_breaker_state == 2
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Circuit breaker open for {{ $labels.agent }}"

      - alert: HighErrorRate
        expr: rate(aragora_debates_failed[5m]) / rate(aragora_debates_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Debate failure rate > 10%"
```

---

## Admin Console & Developer Portal

### Admin Console (`/admin`)

The admin console surfaces system health, circuit breaker state, recent errors, and rate-limit status.
It is intended for on-call and operations use.

Operational dependencies:
- Auth must be enabled (JWT) and the user role must be `admin`.
- The console reads from these endpoints:
  - `GET /api/health`
  - `GET /api/system/circuit-breakers`
  - `GET /api/system/errors?limit=20` (optional)
  - `GET /api/system/rate-limits` (optional)

Notes:
- If optional endpoints are not available, the UI degrades gracefully.
- For production, restrict `/admin` behind SSO, an allowlist, or an internal network boundary.

### Developer Portal (`/developer`)

The developer portal provides API key management and usage telemetry for authenticated users.

Operational dependencies:
- Auth must be enabled (JWT). Standard users can access their own portal.
- The portal reads from these endpoints:
  - `GET /api/auth/me`
  - `POST /api/auth/api-key`
  - `DELETE /api/auth/api-key`
  - `GET /api/billing/usage`

Notes:
- API keys are bearer credentials; display them once and store only client-side.
- Encourage users to rotate keys on compromise or after team changes.

---

## Common Issues & Debugging

### Agent Timeouts

**Symptoms:** Debates hang, agents stop responding

**Diagnosis:**
```bash
# Check circuit breaker state
curl http://localhost:8080/api/agents/health

# Check agent-specific logs
grep "agent=openai-api" /var/log/aragora/server.log | tail -100
```

**Resolution:**
1. Check API key validity
2. Verify rate limits not exceeded
3. Check network connectivity to provider
4. Circuit breaker will auto-recover after 60s

### WebSocket Disconnections

**Symptoms:** Real-time updates stop, clients disconnect

**Diagnosis:**
```bash
# Check active connections
curl http://localhost:8080/api/ws/stats

# Check for connection errors
grep "WebSocket" /var/log/aragora/server.log | grep -i error
```

**Resolution:**
1. Check nginx/proxy timeout settings (increase to 300s)
2. Verify client heartbeat interval matches server
3. Check for network issues (firewall, NAT timeout)

### Database Locks

**Symptoms:** Slow queries, write failures

**Diagnosis:**
```bash
# Check for WAL bloat
ls -la /data/*.db*

# Check active locks
sqlite3 /data/aragora_memory.db ".shell fuser /data/aragora_memory.db"
```

**Resolution:**
```bash
# Force WAL checkpoint
sqlite3 /data/aragora_memory.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Vacuum database (offline)
sqlite3 /data/aragora_memory.db "VACUUM;"
```

### Memory Leaks

**Symptoms:** Increasing memory usage over time

**Diagnosis:**
```bash
# Check process memory
ps aux | grep aragora

# Profile memory (example)
python -m memray run -m aragora.server --http-port 8080 --port 8765
```

**Resolution:**
1. Check for unclosed database connections
2. Review event buffer sizes
3. Restart server (gracefully) during low-traffic periods

---

## Scaling Guide

### Horizontal Scaling

Aragora supports horizontal scaling with shared state:

```
                    ┌─────────────────┐
                    │   Load Balancer │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    ┌────▼────┐        ┌────▼────┐        ┌────▼────┐
    │ Node 1  │        │ Node 2  │        │ Node 3  │
    │ :8080   │        │ :8080   │        │ :8080   │
    └────┬────┘        └────┬────┘        └────┬────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Redis/Postgres │
                    │  (shared state) │
                    └─────────────────┘
```

**Requirements for horizontal scaling:**
1. Shared database (PostgreSQL or Redis for session state)
2. Sticky sessions for WebSocket connections
3. Shared file storage for replays/checkpoints

### Vertical Scaling

Single-node optimization:

```bash
# Increase worker threads
export ARAGORA_WORKERS=4

# Increase connection pool
export ARAGORA_DB_POOL_SIZE=20

# Increase event buffer
export ARAGORA_EVENT_BUFFER_SIZE=10000
```

### Load Balancer Configuration

nginx example for WebSocket support:

```nginx
upstream aragora {
    ip_hash;  # Sticky sessions for WebSocket
    server 127.0.0.1:8080;
    server 127.0.0.1:8081;
}

server {
    listen 443 ssl http2;
    server_name api.aragora.ai;

    location / {
        proxy_pass http://aragora;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

---

## Incident Response

### Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|----------|
| P1 | Service down | 15 min | Server crash, all agents failing |
| P2 | Major degradation | 1 hour | 50%+ debates failing, high latency |
| P3 | Minor issue | 4 hours | Single agent failing, UI bugs |
| P4 | Low priority | 1 day | Documentation issues, minor UX |

### Response Playbook

#### P1: Service Down

1. **Verify outage scope**
   ```bash
   curl -I http://localhost:8080/api/health
   ```

2. **Check server process**
   ```bash
   systemctl status aragora
   journalctl -u aragora --since "5 minutes ago"
   ```

3. **Attempt restart**
   ```bash
   sudo systemctl restart aragora
   ```

4. **Check database integrity**
   ```bash
   sqlite3 /data/aragora_memory.db "PRAGMA integrity_check;"
   ```

5. **Rollback if needed**
   ```bash
   cd /opt/aragora && git checkout v1.x.x
   sudo systemctl restart aragora
   ```

#### P2: High Error Rate

1. **Identify failing component**
   ```bash
   curl http://localhost:8080/api/agents/health
   ```

2. **Check rate limits**
   ```bash
   grep "rate_limit\|429" /var/log/aragora/server.log
   ```

3. **Check API provider status**
   - Anthropic: https://status.anthropic.com
   - OpenAI: https://status.openai.com

4. **Enable fallback providers**
   ```bash
   export OPENROUTER_API_KEY="..."
   sudo systemctl restart aragora
   ```

### Post-Incident Review

Document in `.nomic/incidents/`:

```markdown
# Incident: YYYY-MM-DD-title

## Summary
Brief description of what happened

## Timeline
- HH:MM - First alert
- HH:MM - Investigation started
- HH:MM - Root cause identified
- HH:MM - Mitigation applied
- HH:MM - Service restored

## Root Cause
Technical description

## Action Items
- [ ] Preventive measure 1
- [ ] Preventive measure 2
```

---

## Database Operations

### Routine Maintenance

```bash
# Daily: WAL checkpoint
sqlite3 /data/aragora_memory.db "PRAGMA wal_checkpoint(PASSIVE);"

# Weekly: Analyze for query optimization
sqlite3 /data/aragora_memory.db "ANALYZE;"

# Monthly: Vacuum (during maintenance window)
sqlite3 /data/aragora_memory.db "VACUUM;"
```

### Schema Migrations

Migrations are in `aragora/migrations/`:

```bash
# Apply pending migrations
python -m aragora.migrations.apply

# Check migration status
python -m aragora.migrations.status

# Rollback last migration
python -m aragora.migrations.rollback
```

### Backup Procedures

```bash
# Hot backup (while server running)
sqlite3 /data/aragora_memory.db ".backup /backups/aragora_memory_$(date +%Y%m%d).db"

# Full backup script
#!/bin/bash
BACKUP_DIR=/backups/$(date +%Y%m%d)
mkdir -p $BACKUP_DIR

for db in /data/*.db; do
    sqlite3 "$db" ".backup $BACKUP_DIR/$(basename $db)"
done

# Compress and upload
tar -czf $BACKUP_DIR.tar.gz $BACKUP_DIR
aws s3 cp $BACKUP_DIR.tar.gz s3://aragora-backups/
```

---

## Backup & Recovery

### Backup Schedule

| Type | Frequency | Retention | Storage |
|------|-----------|-----------|---------|
| WAL checkpoint | Hourly | 24 hours | Local |
| Hot backup | Daily | 7 days | S3 |
| Full backup | Weekly | 30 days | S3 + Glacier |
| Debate traces | On completion | 90 days | S3 |

### Recovery Procedures

#### Point-in-Time Recovery

```bash
# Stop server
sudo systemctl stop aragora

# Restore from backup
cp /backups/20240115/aragora_memory.db /data/aragora_memory.db

# Replay WAL if available
sqlite3 /data/aragora_memory.db "PRAGMA wal_checkpoint(RESTART);"

# Verify integrity
sqlite3 /data/aragora_memory.db "PRAGMA integrity_check;"

# Start server
sudo systemctl start aragora
```

#### Disaster Recovery

1. Provision new server
2. Install Aragora from git
3. Restore latest backup from S3
4. Update DNS to point to new server
5. Verify functionality

---

## Storage Cleanup

The `.nomic/` directory accumulates data over time: backups, checkpoints, session telemetry, and artifacts. Use the cleanup script to manage storage.

### Cleanup Script

```bash
# Preview what would be cleaned up (always run first)
python scripts/cleanup_nomic_state.py --dry-run

# Actually perform cleanup with default settings (7 days retention)
python scripts/cleanup_nomic_state.py

# Customize retention periods
python scripts/cleanup_nomic_state.py \
  --backup-days 14 \
  --session-days 3 \
  --checkpoint-days 7

# Archive old data before deleting
python scripts/cleanup_nomic_state.py --archive-to /backups/nomic_archive/
```

### What Gets Cleaned

| Category | Default Retention | Description |
|----------|-------------------|-------------|
| Backups | 7 days (keep 5 latest) | Nomic loop cycle backups |
| Sessions | 3 days (test: 1 day) | Session telemetry data |
| Checkpoints | 7 days | Debate state checkpoints |
| Artifacts | 7 days | Timestamped debug artifacts |
| Orphaned WAL | Immediate | WAL/SHM files without parent DB |

### Essential Databases (Never Deleted)

The cleanup script preserves these core databases:
- `core.db`, `memory.db`, `agents.db`, `debates.db`
- `agent_elo.db`, `agent_memories.db`, `agent_calibration.db`
- `consensus_memory.db`, `continuum.db`, `continuum_memory.db`
- `users.db`, `usage.db`, `scheduled_debates.db`

### Cleanup Schedule

Recommended: Run cleanup weekly via cron:

```bash
# Add to crontab
0 3 * * 0 cd /opt/aragora && python scripts/cleanup_nomic_state.py --yes >> /var/log/aragora/cleanup.log 2>&1
```

### Manual Analysis

To analyze storage usage without cleaning:

```bash
python scripts/cleanup_nomic_state.py --analyze-only
```

### Decision Receipt Retention

Decision receipts (cryptographic audit trails for debates) are automatically cleaned up by the Receipt Retention Scheduler. This runs as a background async task.

#### Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `ARAGORA_RECEIPT_RETENTION_DAYS` | 2555 (~7 years) | How long to keep receipts |
| `ARAGORA_RECEIPT_CLEANUP_INTERVAL_HOURS` | 24 | How often to run cleanup |

#### Monitoring

Check scheduler status via the API:

```bash
curl -s http://localhost:8080/api/admin/schedulers/receipt-retention/status | jq .

# Expected response:
# {
#   "running": true,
#   "interval_hours": 24,
#   "retention_days": 2555,
#   "stats": {
#     "total_runs": 5,
#     "total_receipts_deleted": 0,
#     "failures": 0,
#     "success_rate": 1.0
#   }
# }
```

#### Manual Cleanup

Trigger immediate cleanup (for maintenance or testing):

```bash
curl -X POST http://localhost:8080/api/admin/schedulers/receipt-retention/cleanup
```

#### Prometheus Metrics

The scheduler exposes these metrics:
- `aragora_receipt_cleanup_total` - Total cleanup operations
- `aragora_receipt_cleanup_duration_seconds` - Cleanup duration histogram
- `aragora_receipts_deleted_total` - Total receipts deleted

---

## Knowledge Mound Operations

The Knowledge Mound (KM) is Aragora's unified knowledge storage system that enables cross-debate learning and organizational knowledge accumulation.

### Health Monitoring

```bash
# Comprehensive KM health check
curl -s http://localhost:8080/api/health/knowledge-mound | jq .

# Expected healthy response:
# {
#   "status": "healthy",
#   "summary": {"total_components": 11, "healthy": 11, "active": 8},
#   "components": {...}
# }
```

### Environment Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_MOUND_DATABASE_URL` | SQLite | PostgreSQL URL for production |
| `KNOWLEDGE_MOUND_REDIS_URL` | - | Redis URL for KM caching |
| `CP_ENABLE_KM` | `true` | Enable Control Plane → KM integration |
| `CP_KM_WORKSPACE` | `default` | Default workspace for Control Plane |

### Prometheus Metrics

Key KM metrics exposed at `/metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `aragora_km_operations_total` | Counter | KM operations by type and status |
| `aragora_km_operation_latency_seconds` | Histogram | Operation latency |
| `aragora_km_adapter_syncs_total` | Counter | Adapter sync operations |
| `aragora_km_cp_task_outcomes_total` | Counter | Control Plane task outcomes stored |
| `aragora_km_forward_sync_latency_seconds` | Histogram | Forward sync latency by adapter |
| `aragora_km_reverse_query_latency_seconds` | Histogram | Reverse query latency |
| `aragora_km_semantic_search_total` | Counter | Semantic search operations |
| `aragora_km_cross_debate_reuse_total` | Counter | Knowledge reused across debates |

### Bidirectional Adapters

KM uses adapters to sync data bidirectionally between subsystems:

| Adapter | Direction | Data Synced |
|---------|-----------|-------------|
| ContinuumAdapter | ↔ | Multi-tier memory entries |
| ConsensusAdapter | ↔ | Debate consensus outcomes |
| CritiqueAdapter | ↔ | Critique patterns and feedback |
| EvidenceAdapter | ↔ | Evidence snippets with quality scores |
| BeliefAdapter | ↔ | Belief network nodes and cruxes |
| InsightsAdapter | ↔ | Debate insights and Trickster flips |
| EloAdapter | ↔ | Agent rankings and calibration |
| PulseAdapter | ↔ | Trending topics and scheduled debates |
| CostAdapter | ↔ | Budget alerts and cost patterns |
| RankingAdapter | ↔ | Agent expertise by domain |
| CultureAdapter | ↔ | Organizational culture patterns |
| ControlPlaneAdapter | ↔ | Task outcomes and agent capabilities |

### Control Plane Integration

The Control Plane stores task outcomes and capability records in KM:

```python
# Task outcomes automatically stored on completion
coordinator.complete_task(task_id, result, agent_id="claude-3", latency_ms=5000)

# Query agent recommendations from KM
recommendations = await coordinator.get_agent_recommendations("debate")
```

### Cross-Workspace Learning

Share insights across workspaces via the Control Plane adapter:

```python
from aragora.knowledge.mound.adapters import ControlPlaneAdapter, CrossWorkspaceInsight

adapter = ControlPlaneAdapter(knowledge_mound=km, workspace_id="workspace_a")

# Share insight
insight = CrossWorkspaceInsight(
    insight_id="insight_001",
    source_workspace="workspace_a",
    target_workspaces=["workspace_b", "workspace_c"],
    task_type="debate",
    content="Structured 3-round debates work best for consensus",
    confidence=0.85,
    created_at=datetime.now().isoformat(),
)
await adapter.share_insight_cross_workspace(insight)

# Query insights from other workspaces
insights = await adapter.get_cross_workspace_insights("debate")
```

### Troubleshooting

**KM not storing data:**
1. Check health endpoint: `curl localhost:8080/api/health/knowledge-mound`
2. Verify database connectivity
3. Check adapter sync metrics: `aragora_km_adapter_syncs_total`

**Slow queries:**
1. Monitor `aragora_km_operation_latency_seconds` histogram
2. Check Redis cache hit rate: `aragora_km_cache_hits_total / (hits + misses)`
3. Consider enabling RLM summaries: `enable_rlm_summaries: true`

**Cross-workspace insights not appearing:**
1. Verify workspace IDs match target_workspaces
2. Check `aragora_km_cp_cross_workspace_shares_total` metric
3. Ensure minimum confidence threshold (default 0.6)

---

## Appendix

### Useful Commands

```bash
# Watch server logs
tail -f /var/log/aragora/server.log | jq .

# Count active debates
curl -s http://localhost:8080/api/debates | jq '.debates | length'

# List agents and their ELO
curl -s http://localhost:8080/api/leaderboard/rankings | jq '.agents[] | {name, elo}'

# View circuit breaker status
curl -s http://localhost:8080/api/circuit-breakers | jq .

# Export debate history
curl -s http://localhost:8080/api/debates/export?format=json > debates.json
```

### Configuration Reference

Full configuration options live in `aragora/config/settings.py` (Pydantic settings)
and `aragora/config/legacy.py` (legacy constants). Environment variables are the
primary configuration surface; see `docs/ENVIRONMENT.md`.

```bash
# Example overrides
export ARAGORA_API_TOKEN="your-secret-token"
export ARAGORA_WS_MAX_MESSAGE_SIZE=65536
export ARAGORA_DB_POOL_SIZE=10
export ARAGORA_DB_POOL_TIMEOUT=30
```

### Support Contacts

- GitHub Issues: https://github.com/synaptent/aragora/issues
- Documentation: https://docs.aragora.ai
- Status Page: https://status.aragora.ai

---

## Security & Governance Hardening

This section covers the security hardening features including encryption at rest, RBAC, and data migration.

### Encryption at Rest

Sensitive data is encrypted using AES-256-GCM with field-level encryption. The following stores support encryption:

- **SyncStore**: Connector credentials (api_key, secret, password, token, etc.)
- **IntegrationStore**: Integration settings with sensitive fields
- **GmailTokenStore**: OAuth access and refresh tokens

#### Configuration

```bash
# Required: Set a 32-byte (64 hex characters) encryption key
export ARAGORA_ENCRYPTION_KEY="your-64-hex-character-encryption-key-here"

# Generate a secure key:
python -c "import secrets; print(secrets.token_hex(32))"
```

#### Migrating Existing Data

If you have existing unencrypted data, use the migration utility:

```bash
# Dry run (preview what will be migrated)
python -m aragora.storage.migrations.encrypt_existing_data --all

# Execute migration
python -m aragora.storage.migrations.encrypt_existing_data --all --execute

# Migrate specific stores
python -m aragora.storage.migrations.encrypt_existing_data --sync-store --execute
python -m aragora.storage.migrations.encrypt_existing_data --integration-store --execute
python -m aragora.storage.migrations.encrypt_existing_data --gmail-tokens --execute
```

The migration is backward-compatible: encrypted fields are marked with `_encrypted: true`, so the system can read both encrypted and plaintext data during transition.

#### Verifying Encryption

```bash
# Check if encryption is properly configured
python -c "
from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE
print(f'Crypto available: {CRYPTO_AVAILABLE}')
if CRYPTO_AVAILABLE:
    svc = get_encryption_service()
    print(f'Active key: {svc.get_active_key_id()}')
"
```

### Encryption Key Rotation

Key rotation is critical for maintaining security. Follow this procedure to rotate encryption keys without data loss.

#### When to Rotate Keys

- **Regular rotation**: Every 90 days (recommended) or per compliance requirements
- **Incident response**: If key compromise is suspected
- **Personnel changes**: When staff with key access leave

#### Key Rotation Procedure

**Step 1: Generate a new encryption key**

```bash
# Generate a new 32-byte (64 hex character) key
python -c "import secrets; print(secrets.token_hex(32))"
```

**Step 2: Add the new key to environment (multi-key support)**

The encryption service supports multiple keys via comma-separated values. The first key is used for encryption, others for decryption only:

```bash
# Format: new_key,old_key1,old_key2,...
export ARAGORA_ENCRYPTION_KEY="new-64-hex-key,old-64-hex-key"
```

**Step 3: Re-encrypt existing data**

```bash
# Dry run to verify (reads with old key, would write with new key)
python -m aragora.storage.migrations.encrypt_existing_data --all

# Execute re-encryption
python -m aragora.storage.migrations.encrypt_existing_data --all --execute
```

**Step 4: Verify re-encryption**

```bash
# Check that all records use the new key
python -c "
from aragora.security.encryption import get_encryption_service
svc = get_encryption_service()
print(f'Active encryption key: {svc.get_active_key_id()}')
"
```

**Step 5: Remove old keys (after verification period)**

After a grace period (e.g., 7 days) to ensure no issues:

```bash
# Remove old keys from environment
export ARAGORA_ENCRYPTION_KEY="new-64-hex-key"
```

#### Rolling Deployment Key Rotation

For zero-downtime rotation across multiple instances:

1. **Phase 1**: Deploy with both keys (new primary, old for decryption)
   ```bash
   export ARAGORA_ENCRYPTION_KEY="new_key,old_key"
   ```

2. **Phase 2**: Run migration job to re-encrypt all data
   ```bash
   python -m aragora.storage.migrations.encrypt_existing_data --all --execute
   ```

3. **Phase 3**: After all instances updated and migration complete, remove old key

#### Emergency Key Compromise Procedure

If a key compromise is detected:

1. **Immediately generate and deploy new key** to all instances
2. **Re-encrypt all data** using the migration utility
3. **Revoke any API tokens** that may have been issued during the compromised period
4. **Review audit logs** for suspicious access patterns
5. **Document the incident** per your incident response policy

#### Key Storage Best Practices

| Environment | Recommended Storage |
|-------------|-------------------|
| Development | AWS Secrets Manager local bundle, or `.env` only with strict mode disabled |
| Staging | AWS Secrets Manager with strict mode enabled |
| Production | AWS Secrets Manager, HashiCorp Vault, or cloud KMS with strict mode enabled |

```bash
# Example: AWS Secrets Manager JSON-bundle integration.
# Provider keys stay in AWS and are hydrated only into the child process.
export ARAGORA_USE_SECRETS_MANAGER=true
export ARAGORA_SECRETS_STRICT=true
export ARAGORA_SECRET_NAME=aragora/production
export AWS_REGION=us-east-2

python3 -m aragora.cli.main secrets health --json --require-all
```

### RBAC (Role-Based Access Control)

Workflow endpoints are protected with RBAC. The following permissions are enforced:

| Permission | Endpoints |
|------------|-----------|
| `workflows.read` | GET /api/workflows, GET /api/workflow-templates, GET /api/workflow-approvals, GET /api/workflow-executions |
| `workflows.create` | POST /api/workflows |
| `workflows.update` | PATCH /api/workflows/{id} |
| `workflows.delete` | DELETE /api/workflows/{id} |
| `workflows.execute` | POST /api/workflows/{id}/execute |
| `workflows.approve` | POST /api/workflow-approvals/{id}/resolve |

#### Authentication Methods

RBAC context is extracted from:
1. **JWT Token**: Primary authentication (set via `Authorization: Bearer <token>`)
2. **Request Headers**: Fallback for service-to-service calls
   - `X-User-ID`: User identifier
   - `X-Org-ID`: Organization/tenant identifier
   - `X-User-Roles`: Comma-separated list of roles

#### Example Request with RBAC

```bash
# Using JWT token
curl -H "Authorization: Bearer $JWT_TOKEN" \
     http://localhost:8080/api/workflows

# Using headers (service-to-service)
curl -H "X-User-ID: user-123" \
     -H "X-Org-ID: org-456" \
     -H "X-User-Roles: admin,member" \
     http://localhost:8080/api/workflows
```

### Observability Metrics

New Prometheus metrics are available for security monitoring:

#### Encryption Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_encryption_operations_total` | Counter | operation, store | Total encrypt/decrypt operations |
| `aragora_encryption_operation_latency_seconds` | Histogram | operation | Operation latency |
| `aragora_encryption_errors_total` | Counter | operation, error_type | Encryption errors |

#### RBAC Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_rbac_permission_checks_total` | Counter | permission, result | Permission check counts |
| `aragora_rbac_permission_denied_total` | Counter | permission, handler | Permission denials |
| `aragora_rbac_check_latency_seconds` | Histogram | - | Permission check latency |

#### Migration Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_migration_records_total` | Counter | store, status | Records processed (migrated/skipped/failed) |
| `aragora_migration_errors_total` | Counter | store, error_type | Migration errors |

#### Grafana Queries

```promql
# Encryption operation rate
rate(aragora_encryption_operations_total[5m])

# Permission denial rate
rate(aragora_rbac_permission_denied_total[5m])

# Migration progress
sum by (status) (aragora_migration_records_total)
```

### Storage Backends

Critical data stores support multiple backends for durability:

| Store | Backends | Default |
|-------|----------|---------|
| ApprovalRequestStore | SQLite, PostgreSQL, Redis | SQLite |
| SessionStore | In-memory, Redis | Redis if available |
| OAuthStateStore | In-memory, Redis | Redis if available |

Configure via environment variables:

```bash
# Use PostgreSQL for approval requests
export ARAGORA_APPROVAL_STORE_BACKEND=postgres
export DATABASE_URL=postgresql://user:pass@host:5432/db

# Use Redis for sessions
export ARAGORA_REDIS_URL=redis://localhost:6379
```

### Troubleshooting

#### Encryption Key Issues

```bash
# Error: "Data will not be recoverable after restart"
# Fix: Set ARAGORA_ENCRYPTION_KEY environment variable

# Error: "Key not found" during decryption
# Cause: Data was encrypted with a different key
# Fix: Use the same key that was used for encryption, or re-migrate data
```

#### RBAC Permission Denied

```bash
# Check what permissions a user has
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/auth/me | jq '.permissions'

# Common causes:
# - Missing required role for the permission
# - Token expired (check exp claim)
# - Org ID mismatch between token and resource
```

#### Migration Failures

```bash
# Check migration status
python -m aragora.storage.migrations.encrypt_existing_data --all -v

# Common issues:
# - ARAGORA_ENCRYPTION_KEY not set
# - Database connection failures
# - Records with corrupt data (logged as errors, others continue)
```

### Security Audit Checklist

Use this checklist to verify security posture before production deployment or during periodic security reviews.

#### Pre-Deployment Checklist

**Encryption**
- [ ] `ARAGORA_ENCRYPTION_KEY` is set (64 hex characters)
- [ ] Key is stored in a secrets manager (not environment file in production)
- [ ] Run `python -c "from aragora.security.encryption import CRYPTO_AVAILABLE; print(CRYPTO_AVAILABLE)"` returns `True`
- [ ] Migration utility has been run to encrypt existing plaintext data

**Authentication**
- [ ] `ARAGORA_JWT_SECRET` is set (32+ characters, cryptographically random)
- [ ] JWT expiration is reasonable (default: 24 hours)
- [ ] Refresh token expiration is reasonable (default: 30 days)
- [ ] OAuth redirect URLs are validated against allowlist
- [ ] MFA is enabled for admin users (SOC 2 CC5-01)

**Authorization (RBAC)**
- [ ] All sensitive endpoints require authentication
- [ ] Permission checks are in place for CRUD operations
- [ ] Admin endpoints require admin role + MFA
- [ ] Service-to-service calls use proper authentication headers

**Network Security**
- [ ] CORS origins are explicitly configured (no wildcards in production)
- [ ] TLS is enabled for all external connections
- [ ] API rate limiting is configured
- [ ] WebSocket connections are authenticated

**Data Protection**
- [ ] Sensitive fields are encrypted at rest (credentials, tokens, secrets)
- [ ] Audit logging is enabled
- [ ] PII handling complies with privacy regulations
- [ ] Backup encryption is enabled

#### Periodic Security Review

**Weekly**
- [ ] Review `aragora_rbac_permission_denied_total` for unusual patterns
- [ ] Check `aragora_encryption_errors_total` for failures
- [ ] Review admin impersonation audit logs

**Monthly**
- [ ] Review user access and remove inactive accounts
- [ ] Verify backup integrity and restore capability
- [ ] Check for unused API tokens and revoke them
- [ ] Review OAuth provider connections

**Quarterly**
- [ ] Rotate encryption keys (see Key Rotation section)
- [ ] Update dependencies for security patches
- [ ] Review and update security documentation
- [ ] Conduct access review with team leads

#### Security Metrics Dashboard

Monitor these metrics continuously:

| Metric | Alert Threshold | Description |
|--------|-----------------|-------------|
| `aragora_rbac_permission_denied_total` | >10/min sustained | Potential attack or misconfiguration |
| `aragora_encryption_errors_total` | Any | Encryption failures need immediate attention |
| `aragora_auth_failures_total` | >5/min per IP | Potential brute force attack |
| `aragora_admin_impersonate_total` | Any | All impersonations should be reviewed |

**Grafana Alert Rules**

```yaml
# Alert on high permission denial rate
- alert: HighPermissionDenialRate
  expr: rate(aragora_rbac_permission_denied_total[5m]) > 0.1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: High rate of permission denials

# Alert on encryption errors
- alert: EncryptionErrors
  expr: increase(aragora_encryption_errors_total[5m]) > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: Encryption errors detected

# Alert on admin impersonation
- alert: AdminImpersonation
  expr: increase(aragora_admin_impersonate_total[5m]) > 0
  labels:
    severity: info
  annotations:
    summary: Admin impersonation event - review audit log
```

#### Compliance Mapping

| Control | Implementation | Verification |
|---------|----------------|--------------|
| SOC 2 CC5-01 | Admin MFA enforcement | Check `enforce_admin_mfa_policy()` in admin handlers |
| SOC 2 CC6-01 | Encryption at rest | Verify `CRYPTO_AVAILABLE` and key configuration |
| SOC 2 CC6-07 | Access control | RBAC permission checks in all handlers |
| GDPR Art. 32 | Data protection | Field-level encryption, audit logging |
| HIPAA 164.312 | Access controls | RBAC, MFA, audit trails |

#### Incident Response Contacts

Maintain this section with current contact information:

```
Security Team Lead: [Name] - [Contact]
On-Call Engineer: [Rotation Schedule/PagerDuty]
Legal/Compliance: [Name] - [Contact]
Data Protection Officer: [Name] - [Contact]
```

---

## Decision Router Cache Invalidation

The DecisionRouter includes a response cache that improves performance by caching routing decisions. The cache supports multiple invalidation strategies for different scenarios.

### Cache Configuration

```python
from aragora.server.middleware.decision_routing import (
    get_decision_router,
    invalidate_cache_for_workspace,
    invalidate_cache_for_policy_change,
    invalidate_cache_for_agent_upgrade,
    get_cache_stats,
)

# Get the router with caching enabled
router = await get_decision_router()
```

### Invalidation Strategies

#### Workspace-Scoped Invalidation

Invalidate all cached decisions for a specific workspace:

```python
# When workspace configuration changes
count = await invalidate_cache_for_workspace("workspace-123")
print(f"Invalidated {count} cached entries for workspace")
```

Use cases:
- Workspace policy updates
- Team membership changes
- Per-workspace routing rule changes

#### Policy Version Invalidation

When global routing policies change, update the policy version:

```python
# Deploy new routing policy
await invalidate_cache_for_policy_change("v2.0.0")

# All cached entries with older policy versions become stale
# and will be re-computed on next access
```

This uses lazy invalidation - entries are marked stale but not immediately removed.

#### Agent Version Invalidation

When agents are upgraded, invalidate responses that used old versions:

```python
# After upgrading Claude from v3.5 to v4
count = await invalidate_cache_for_agent_upgrade("claude", "3.5")
print(f"Invalidated {count} cached entries using claude v3.5")
```

#### Tag-Based Invalidation

Entries can be tagged for granular invalidation:

```python
from aragora.server.middleware.decision_routing import ResponseCache

cache = ResponseCache(max_size=1000, ttl_seconds=3600)

# Store with tags
cache.set(
    key="debate-123",
    result={"decision": "approve"},
    workspace_id="ws-1",
    tags=["debate", "high-priority"],
)

# Invalidate all entries with a specific tag
count = cache.invalidate_by_tag("high-priority")
```

### Cache Monitoring

```python
# Get cache statistics
stats = await get_cache_stats()
print(f"Total entries: {stats['total_entries']}")
print(f"Hit rate: {stats['hit_rate']:.2%}")
print(f"Policy version: {stats['current_policy_version']}")
```

### Prometheus Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `aragora_decision_cache_hits_total` | Counter | Cache hit count |
| `aragora_decision_cache_misses_total` | Counter | Cache miss count |
| `aragora_decision_cache_invalidations_total` | Counter | Invalidation events by type |
| `aragora_decision_cache_size` | Gauge | Current cache size |

### Deployment Recommendations

1. **Rolling deployments**: Set new policy version before deploying new code
2. **Agent upgrades**: Invalidate old agent versions after confirming new agent is healthy
3. **Emergency changes**: Use workspace invalidation for targeted cache clearing
4. **Monitoring**: Alert on sudden drops in cache hit rate

---

## Webhook Delivery Manager

The Webhook Delivery Manager provides reliable webhook delivery with retry logic, dead-letter queuing, and circuit breaker protection.

### Quick Start

```python
from aragora.server.webhook_delivery import (
    deliver_webhook,
    get_delivery_manager,
    WebhookDeliveryManager,
)

# Simple delivery
delivery = await deliver_webhook(
    webhook_id="wh-123",
    event_type="debate_end",
    payload={"debate_id": "d-456", "result": "consensus"},
    url="https://example.com/webhook",
    secret="your-hmac-secret",  # Optional: enables signature verification
)

print(f"Status: {delivery.status}")  # DELIVERED, RETRYING, or DEAD_LETTERED
```

### Configuration

```python
manager = WebhookDeliveryManager(
    max_retries=5,              # Maximum retry attempts (default: 5)
    base_delay_seconds=1.0,     # Initial retry delay (default: 1.0)
    max_delay_seconds=300.0,    # Maximum retry delay cap (default: 300)
    timeout_seconds=30.0,       # Request timeout (default: 30)
    circuit_breaker_threshold=5, # Failures before circuit opens (default: 5)
)
```

### Delivery States

| State | Description |
|-------|-------------|
| `PENDING` | Queued for delivery |
| `IN_PROGRESS` | Currently being delivered |
| `DELIVERED` | Successfully delivered (2xx response) |
| `RETRYING` | Failed, scheduled for retry |
| `DEAD_LETTERED` | Max retries exceeded, moved to dead-letter queue |

### Retry Behavior

Retries use exponential backoff with jitter:

```
delay = min(base_delay * (2 ^ attempt), max_delay) + random_jitter
```

Default progression: 1s → 2s → 4s → 8s → 16s → ... → 300s max

### Circuit Breaker

The circuit breaker prevents overwhelming failing endpoints:

```python
# Circuit opens after threshold consecutive failures
# While open, deliveries to that URL are immediately queued for retry

# Check circuit state
manager = await get_delivery_manager()
is_open = manager._is_circuit_open("https://example.com/webhook")

# Circuit automatically closes after the cooldown period (default: 60s)
```

### Dead-Letter Queue

Failed deliveries are moved to the dead-letter queue after max retries:

```python
# List dead-lettered deliveries
dead_letters = await manager.get_dead_letter_queue(limit=100)

for delivery in dead_letters:
    print(f"ID: {delivery.delivery_id}")
    print(f"Event: {delivery.event_type}")
    print(f"Last error: {delivery.last_error}")
    print(f"Attempts: {delivery.attempts}")

# Retry a dead-lettered delivery
success = await manager.retry_dead_letter(delivery_id="dlv-123")
```

### HMAC Signature Verification

When a secret is provided, webhooks include an HMAC-SHA256 signature:

```python
# Delivery includes X-Webhook-Signature header
delivery = await deliver_webhook(
    webhook_id="wh-123",
    event_type="debate_end",
    payload={"debate_id": "d-456"},
    url="https://example.com/webhook",
    secret="your-secret-key",
)

# Recipient verifies signature:
# X-Webhook-Signature: sha256=<hex-encoded-hmac>
```

Verification code for recipients:

```python
import hmac
import hashlib
import json

def verify_signature(payload: dict, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(),
        json.dumps(payload).encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

### Monitoring

```python
# Get delivery metrics
metrics = await manager.get_metrics()
print(f"Total deliveries: {metrics['total_deliveries']}")
print(f"Success rate: {metrics['success_rate']}%")
print(f"Average latency: {metrics['avg_latency_ms']}ms")
print(f"Dead-lettered: {metrics['dead_lettered']}")
print(f"Retries pending: {metrics['retries_pending']}")
```

### Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_webhook_deliveries_total` | Counter | status, event_type | Total delivery attempts |
| `aragora_webhook_delivery_latency_seconds` | Histogram | event_type | Delivery latency |
| `aragora_webhook_retries_total` | Counter | event_type | Retry attempts |
| `aragora_webhook_dead_lettered_total` | Counter | event_type | Dead-lettered count |
| `aragora_webhook_circuit_breaker_state` | Gauge | endpoint | Circuit breaker state (0=closed, 1=open) |

### Operational Recommendations

1. **Monitor dead-letter queue**: Set up alerts when queue grows
2. **Review circuit breaker opens**: Investigate endpoints that frequently trip
3. **Set appropriate timeouts**: Match recipient's expected processing time
4. **Use secrets**: Always use HMAC signatures in production
5. **Idempotency**: Include `delivery_id` in payload for recipient-side deduplication

---

## Integration Store Metrics

The Integration Store Metrics system provides observability into integration storage operations, including latency tracking, error rates, and health monitoring.

### Quick Start

```python
from aragora.storage.integration_store_metrics import (
    InstrumentedIntegrationStore,
    get_integration_metrics,
    get_integration_health,
)

# Wrap an existing store with instrumentation
instrumented = InstrumentedIntegrationStore(base_store, backend_type="postgresql")

# Use normally - metrics are collected automatically
await instrumented.save({"type": "slack", "user_id": "u-123", "token": "..."})
config = await instrumented.get("slack", "u-123")
```

### Tracked Operations

| Operation | Metrics Collected |
|-----------|-------------------|
| `get` | Latency, success/failure count, cache hit/miss |
| `save` | Latency, success/failure count |
| `delete` | Latency, success/failure count |
| `list` | Latency, active integration count |
| `refresh_token` | Latency, success/failure count |

### Health Monitoring

The store tracks consecutive failures and marks itself unhealthy after 3 failures:

```python
# Check health status
health = await instrumented.health_check()
print(f"Healthy: {health['healthy']}")
print(f"Backend: {health['backend_type']}")
print(f"Consecutive failures: {health['consecutive_failures']}")
print(f"Active integrations: {health['active_integrations']}")
```

Health automatically recovers after a successful operation.

### Getting Metrics

```python
# Get comprehensive metrics
metrics = await get_integration_metrics()

# Structure:
# {
#   "backend_type": "postgresql",
#   "is_healthy": true,
#   "cache_hit_rate": 85.5,
#   "operations": {
#     "get": {"total_calls": 1000, "success_rate": 99.5, "avg_latency_seconds": 0.012},
#     "save": {"total_calls": 200, "success_rate": 100.0, "avg_latency_seconds": 0.025},
#     ...
#   }
# }

# Get health summary
health = await get_integration_health()
# {
#   "healthy": true,
#   "backend_type": "postgresql",
#   "consecutive_failures": 0,
#   "operations_summary": {
#     "get_success_rate": 99.5,
#     "save_success_rate": 100.0,
#     "cache_hit_rate": 85.5
#   }
# }
```

### Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_integration_store_operations_total` | Counter | operation, status | Operation count by type |
| `aragora_integration_store_latency_seconds` | Histogram | operation | Operation latency |
| `aragora_integration_store_health` | Gauge | backend | Health status (1=healthy, 0=unhealthy) |
| `aragora_integration_store_active_integrations` | Gauge | - | Count of active integrations |
| `aragora_integration_store_cache_hit_rate` | Gauge | - | Cache hit rate percentage |
| `aragora_integration_store_consecutive_failures` | Gauge | - | Consecutive failure count |

### Alerting Rules

```yaml
groups:
  - name: integration_store
    rules:
      - alert: IntegrationStoreUnhealthy
        expr: aragora_integration_store_health == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Integration store unhealthy (3+ consecutive failures)"

      - alert: IntegrationStoreHighLatency
        expr: histogram_quantile(0.95, aragora_integration_store_latency_seconds) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Integration store p95 latency > 1s"

      - alert: IntegrationStoreLowSuccessRate
        expr: |
          sum(rate(aragora_integration_store_operations_total{status="success"}[5m])) /
          sum(rate(aragora_integration_store_operations_total[5m])) < 0.95
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Integration store success rate below 95%"
```

### Troubleshooting

**High consecutive failure count:**
1. Check database connectivity
2. Review recent error logs for the backend
3. Verify credentials and connection strings

**Low cache hit rate:**
1. Review access patterns - are integrations being fetched repeatedly?
2. Consider increasing cache TTL
3. Check if cache invalidation is too aggressive

**High latency:**
1. Check database performance (slow queries, locks)
2. Review network latency to database
3. Consider connection pool sizing
