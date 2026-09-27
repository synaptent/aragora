# Aragora Operations Runbook

This runbook provides procedures for common operational tasks and incident response.

## Table of Contents

1. [Health Checks](#health-checks)
2. [Common Issues](#common-issues)
3. [Incident Response](#incident-response)
4. [Maintenance Procedures](#maintenance-procedures)
5. [Scaling Operations](#scaling-operations)
6. [Backup & Recovery](#backup--recovery)

---

## Health Checks

### Service Health

```bash
# Check backend health
curl -s http://localhost:8080/api/health | jq

# Expected response:
{
  "status": "healthy",
  "version": "1.0.0",
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "agents": "healthy"
  }
}
```

### Kubernetes Health

```bash
# Check pod status
kubectl -n aragora get pods

# Check resource usage
kubectl -n aragora top pods

# Check recent events
kubectl -n aragora get events --sort-by=.metadata.creationTimestamp | tail -20
```

### Database Health

```bash
# Check PostgreSQL connections
psql -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"

# Check database size
psql -c "SELECT pg_size_pretty(pg_database_size('aragora'));"
```

---

## Common Issues

### Issue: High API Latency

**Symptoms:**
- Response times >2s
- Grafana alerts firing
- User complaints

**Diagnosis:**
```bash
# Check current latency
curl -w "Time: %{time_total}s\n" -o /dev/null -s http://localhost:8080/api/health

# Check active debates
curl -s http://localhost:8080/api/admin/stats | jq '.active_debates'

# Check agent response times
kubectl -n aragora logs deployment/aragora-backend --tail=100 | grep "agent_response_time"
```

**Resolution:**
1. Scale up backend replicas: `kubectl -n aragora scale deployment/aragora-backend --replicas=4`
2. Check for slow database queries
3. Verify external API quotas (Anthropic, OpenAI)
4. Clear Redis cache if stale: `redis-cli FLUSHDB`

---

### Issue: WebSocket Disconnections

**Symptoms:**
- Clients losing real-time updates
- "Connection lost" errors in UI
- High reconnection rate in metrics

**Diagnosis:**
```bash
# Check WebSocket connections
kubectl -n aragora logs deployment/aragora-backend | grep "websocket"

# Check nginx ingress logs
kubectl -n ingress-nginx logs -l app.kubernetes.io/name=ingress-nginx | grep "websocket"
```

**Resolution:**
1. Verify ingress WebSocket configuration
2. Check proxy timeout settings (should be >60s)
3. Verify keep-alive settings
4. Check for memory pressure causing pod restarts

---

### Issue: Agent API Errors

**Symptoms:**
- Debates failing to complete
- 429 errors in logs
- Agent timeouts

**Diagnosis:**
```bash
# Check error rates
kubectl -n aragora logs deployment/aragora-backend | grep "rate_limit\|429\|timeout"

# Check API key status
curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2024-01-01" \
  -d '{"model":"claude-3-opus-20240229","max_tokens":1,"messages":[{"role":"user","content":"test"}]}'
```

**Resolution:**
1. Check API quotas with provider
2. Enable OpenRouter fallback
3. Reduce concurrent debate limit
4. Implement request queuing

---

### Issue: Database Connection Exhaustion

**Symptoms:**
- "too many connections" errors
- Slow queries
- Backend pods failing health checks

**Diagnosis:**
```bash
# Check connection count
psql -c "SELECT count(*) FROM pg_stat_activity;"

# Check waiting queries
psql -c "SELECT query, state, wait_event FROM pg_stat_activity WHERE state != 'idle' LIMIT 20;"
```

**Resolution:**
1. Increase connection pool size
2. Kill idle connections: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle' AND query_start < now() - interval '10 minutes';`
3. Scale database instance
4. Add PgBouncer for connection pooling

---

## Incident Response

### Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|----------|
| P1 | Service down | 15 min | Complete outage, data loss |
| P2 | Major degradation | 1 hour | 50%+ errors, major feature broken |
| P3 | Minor degradation | 4 hours | Single endpoint slow, minor bugs |
| P4 | Low impact | Next business day | Cosmetic issues, minor UX |

### P1 Incident Procedure

1. **Acknowledge** (within 5 min)
   - Join incident channel
   - Assign incident commander

2. **Assess** (within 15 min)
   - Check all dashboards
   - Identify affected systems
   - Determine blast radius

3. **Mitigate** (ASAP)
   - Rollback recent deployments
   - Scale up resources
   - Enable maintenance mode if needed

4. **Communicate**
   - Update status page
   - Notify affected customers
   - Regular updates every 30 min

5. **Resolve**
   - Implement fix
   - Verify fix in production
   - Close incident

6. **Post-mortem** (within 48 hours)
   - Document timeline
   - Root cause analysis
   - Action items

### Rollback Procedure

```bash
# Get previous deployment
kubectl -n aragora rollout history deployment/aragora-backend

# Rollback to previous revision
kubectl -n aragora rollout undo deployment/aragora-backend

# Verify rollback
kubectl -n aragora rollout status deployment/aragora-backend
```

---

## Maintenance Procedures

### Planned Maintenance Window

1. **Schedule** (48 hours notice)
   - Update status page
   - Notify customers via email
   - Set maintenance window in monitoring

2. **Pre-maintenance**
   - Complete running debates gracefully
   - Disable new debate creation
   - Backup databases

3. **During maintenance**
   - Apply updates/changes
   - Run migrations
   - Test functionality

4. **Post-maintenance**
   - Enable services
   - Verify health checks
   - Monitor for issues
   - Update status page

### Database Migration

```bash
# Backup first
pg_dump aragora > backup_$(date +%Y%m%d).sql

# Run migrations
python -m aragora.migrations upgrade

# Verify
python -m aragora.migrations status
```

### Certificate Renewal

Certificates are auto-renewed by cert-manager. Manual process if needed:

```bash
# Check certificate status
kubectl -n aragora get certificate

# Force renewal
kubectl -n aragora delete secret aragora-tls
kubectl -n aragora annotate certificate aragora-cert cert-manager.io/issue-temporary-certificate="true"
```

---

## Scaling Operations

### Horizontal Scaling

```bash
# Scale backend
kubectl -n aragora scale deployment/aragora-backend --replicas=5

# Scale frontend
kubectl -n aragora scale deployment/aragora-frontend --replicas=3

# Verify
kubectl -n aragora get pods -w
```

### Vertical Scaling

```bash
# Update resource limits
kubectl -n aragora set resources deployment/aragora-backend \
  --limits=memory=4Gi,cpu=2000m \
  --requests=memory=1Gi,cpu=500m
```

### Database Scaling

For PostgreSQL on cloud:
1. Create read replica
2. Update connection string for read operations
3. Monitor replication lag

---

## Backup & Recovery

### Daily Backups

Automated via cron:

```bash
# Manual backup
kubectl -n aragora exec -it postgres-0 -- pg_dump -U aragora aragora > backup.sql

# Verify backup
head -100 backup.sql
```

### Point-in-Time Recovery

```bash
# Restore from backup
kubectl -n aragora exec -i postgres-0 -- psql -U aragora aragora < backup.sql

# Or restore to specific time (if WAL archiving enabled)
pg_restore --target-time="2026-01-20 12:00:00" ...
```

### Knowledge Base Backup

```bash
# Export knowledge mound
curl -X POST http://localhost:8080/api/knowledge/export \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -o knowledge_backup.json

# Restore
curl -X POST http://localhost:8080/api/knowledge/import \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d @knowledge_backup.json
```

---

## Useful Commands

### Quick Diagnostics

```bash
# All pods status
kubectl -n aragora get pods -o wide

# Recent logs
kubectl -n aragora logs deployment/aragora-backend --tail=100 -f

# Resource usage
kubectl -n aragora top pods

# Events
kubectl -n aragora get events --sort-by=.lastTimestamp | tail -20
```

### Debug Mode

```bash
# Enable debug logging
kubectl -n aragora set env deployment/aragora-backend ARAGORA_LOG_LEVEL=DEBUG

# Disable when done
kubectl -n aragora set env deployment/aragora-backend ARAGORA_LOG_LEVEL=INFO
```

### Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| On-call Engineer | PagerDuty | - |
| Engineering Lead | [email] | After 30 min |
| Platform Team | Slack #platform | P1/P2 only |

---

## Appendix: Monitoring Queries

### Prometheus Queries

```promql
# Error rate
sum(rate(aragora_http_requests_total{status=~"5.."}[5m])) / sum(rate(aragora_http_requests_total[5m])) * 100

# P95 latency
histogram_quantile(0.95, sum(rate(aragora_http_request_duration_seconds_bucket[5m])) by (le))

# Active debates
aragora_active_debates

# Memory usage
process_resident_memory_bytes{job="aragora-backend"} / 1024 / 1024 / 1024
```
