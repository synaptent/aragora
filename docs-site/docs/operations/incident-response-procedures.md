---
title: Incident Response Runbook
description: Incident Response Runbook
---

# Incident Response Runbook

Procedures for handling production incidents.

## Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|----------|
| SEV1 | Complete outage | < 15 min | API down, data loss |
| SEV2 | Major degradation | < 30 min | High error rate, slow response |
| SEV3 | Minor issue | < 2 hours | Single feature broken |
| SEV4 | Low impact | < 24 hours | Cosmetic issues |

---

## Initial Response

### 1. Acknowledge Incident

```bash
# Create incident channel (Slack)
/incident create "Brief description"

# Or manual notification
# Post in #incidents with @oncall
```

### 2. Assess Impact

```bash
# Check service health
curl http://aragora.company.com/health

# Check error rate
# Grafana: aragora_http_requests_total{status=~"5.."}

# Check recent deployments
kubectl rollout history deployment/aragora-api -n aragora
```

### 3. Declare Severity

Based on:
- Number of users affected
- Revenue impact
- Data integrity risk
- Duration

---

## Common Issues & Fixes

### API Not Responding

```bash
# 1. Check pods
kubectl get pods -n aragora
kubectl describe pod <pod-name> -n aragora

# 2. Check logs
kubectl logs -f deployment/aragora-api -n aragora --tail=100

# 3. Restart if needed
kubectl rollout restart deployment/aragora-api -n aragora

# 4. Check ingress
kubectl get ingress -n aragora
kubectl describe ingress aragora -n aragora
```

### High Error Rate (5xx)

```bash
# 1. Check specific errors
kubectl logs deployment/aragora-api -n aragora | grep -i error | tail -50

# 2. Check database connectivity
kubectl exec -it deployment/aragora-api -n aragora -- \
  python -c "from aragora.database import check_connection; check_connection()"

# 3. Check Redis connectivity
kubectl exec -it deployment/aragora-api -n aragora -- \
  redis-cli -h redis.aragora ping

# 4. Check external service status
curl -I https://api.anthropic.com/v1/messages  # Claude API
curl -I https://api.openai.com/v1/models        # OpenAI API
```

### High Latency

```bash
# 1. Check slow queries
kubectl exec -it postgresql-0 -n aragora -- \
  psql -U postgres -c "SELECT * FROM pg_stat_activity WHERE state = 'active' ORDER BY query_start;"

# 2. Check connection pool
kubectl exec -it deployment/aragora-api -n aragora -- \
  python -c "from aragora.database import get_pool_status; print(get_pool_status())"

# 3. Scale up if needed
kubectl scale deployment/aragora-api -n aragora --replicas=10

# 4. Enable query caching
kubectl set env deployment/aragora-api CACHE_QUERIES=true
```

### Database Issues

```bash
# 1. Check database status
kubectl exec -it postgresql-0 -n aragora -- pg_isready

# 2. Check connections
kubectl exec -it postgresql-0 -n aragora -- \
  psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"

# 3. Kill long-running queries
kubectl exec -it postgresql-0 -n aragora -- \
  psql -U postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'active' AND query_start < now() - interval '5 minutes';"

# 4. Failover to replica (if available)
# AWS RDS: Promote read replica
aws rds promote-read-replica --db-instance-identifier aragora-replica
```

### Memory Issues (OOMKilled)

```bash
# 1. Check pod restarts
kubectl get pods -n aragora -o wide

# 2. Check resource usage
kubectl top pods -n aragora

# 3. Increase memory limits
kubectl patch deployment aragora-api -n aragora -p '
spec:
  template:
    spec:
      containers:
      - name: aragora-api
        resources:
          limits:
            memory: "8Gi"
'

# 4. Check for memory leaks
kubectl logs deployment/aragora-api -n aragora | grep -i "memory\|heap"
```

### Queue Backup

```bash
# 1. Check queue depth
redis-cli -h redis.aragora LLEN aragora:queue:default

# 2. Scale workers
kubectl scale deployment/aragora-worker -n aragora --replicas=20

# 3. Check worker logs
kubectl logs -f deployment/aragora-worker -n aragora

# 4. Clear stuck jobs if needed
redis-cli -h redis.aragora DEL aragora:queue:stuck
```

---

## Rollback Procedures

### Application Rollback

```bash
# Kubernetes
kubectl rollout undo deployment/aragora-api -n aragora
kubectl rollout status deployment/aragora-api -n aragora

# Docker Compose
docker compose pull aragora-api:previous
docker compose up -d
```

### Database Rollback

```bash
# Alembic
alembic downgrade -1

# Or restore from snapshot
# See database-migration.md
```

### Feature Flag Disable

```bash
# Disable problematic feature
kubectl set env deployment/aragora-api \
  FEATURE_NEW_DEBATE_UI=false \
  FEATURE_AI_SUGGESTIONS=false
```

---

## Communication

### Status Page Update

```bash
# Update status page
curl -X POST https://status.company.com/api/incidents \
  -H "Authorization: Bearer $STATUS_PAGE_TOKEN" \
  -d '{
    "status": "investigating",
    "message": "We are investigating reports of API errors."
  }'
```

### Internal Communication

```
Incident: [BRIEF DESCRIPTION]
Severity: SEV[1-4]
Status: [Investigating/Identified/Monitoring/Resolved]
Impact: [Who/what is affected]
ETA: [If known]
Updates: [Channel/URL]
```

---

## Post-Incident

### 1. Verify Recovery

```bash
# Health check
curl http://aragora.company.com/health

# Smoke tests
pytest tests/smoke/ -v

# Monitor error rate for 30 min
```

### 2. Write Postmortem

Template:
```
## Summary
Brief description of what happened.

## Impact
- Duration: X hours
- Users affected: X
- Revenue impact: $X

## Timeline
- HH:MM - Event
- HH:MM - Event

## Root Cause
Why did this happen?

## Resolution
What fixed it?

## Action Items
- [ ] Item 1 (Owner, Due date)
- [ ] Item 2 (Owner, Due date)

## Lessons Learned
What can we do better?
```

### 3. Update Runbooks

If new failure mode discovered, update this runbook.

---

## Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| On-Call Engineer | #oncall (Slack) | PagerDuty |
| Engineering Manager | @manager | Phone |
| VP Engineering | @vp-eng | Phone (SEV1 only) |
| External: Anthropic | support@anthropic.com | - |
| External: OpenAI | support@openai.com | - |

---

## See Also

- [Scaling Runbook](./scaling)
- [Monitoring Setup](./monitoring-setup)
- [Database Migration](./database-migration)
