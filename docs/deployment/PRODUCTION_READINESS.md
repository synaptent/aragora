# Production Readiness Checklist

Comprehensive checklist for deploying Aragora to production. Complete all sections before go-live.

**Document Version:** 1.0.0
**Last Updated:** 2026-01-13

---

## Quick Status Check

```bash
# Run production readiness validator
python -m aragora.config --validate-production

# Expected output:
# [PASS] Environment mode is production
# [PASS] JWT secret configured (32+ chars)
# [PASS] At least one AI provider configured
# [PASS] Database connection verified
# [WARN] Redis not configured (rate limiting will use in-memory)
```

---

## Pre-Launch Checklist

### 1. Security Configuration

| Item | Status | Verification Command |
|------|--------|---------------------|
| **JWT Secret** (32+ chars) | [ ] | `echo $ARAGORA_JWT_SECRET \| wc -c` (should be >32) |
| **Production environment mode** | [ ] | `echo $ARAGORA_ENV` (should be `production`) |
| **API keys in secret manager** | [ ] | Not in `.env` file, use K8s secrets or vault |
| **CORS origins restricted** | [ ] | Check `ARAGORA_ALLOWED_ORIGINS` excludes `localhost` |
| **Rate limiting enabled** | [ ] | `curl /api/rate-limits/config` returns limits |
| **TLS/HTTPS enforced** | [ ] | `curl -I https://your-domain/api/health` |
| **Token blacklist backend** | [ ] | `echo $ARAGORA_BLACKLIST_BACKEND` (recommend `redis` or `sqlite`) |

**Critical Security Variables:**
```bash
# REQUIRED in production
ARAGORA_ENV=production
ARAGORA_JWT_SECRET=<32+ character random string>

# Generate secure JWT secret:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 2. High Availability

| Item | Status | Verification Command |
|------|--------|---------------------|
| **Minimum 2 replicas** | [ ] | `kubectl get deploy aragora -o jsonpath='{.spec.replicas}'` |
| **HPA configured** | [ ] | `kubectl get hpa aragora` |
| **PDB configured** | [ ] | `kubectl get pdb aragora-pdb` |
| **Anti-affinity rules** | [ ] | Check deployment manifest |
| **Multi-zone distribution** | [ ] | `kubectl get pods -o wide` (different nodes) |

**Kubernetes HA Manifest:**
```yaml
# deploy/kubernetes/deployment.yaml
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

### 3. Database & Persistence

| Item | Status | Verification Command |
|------|--------|---------------------|
| **Database connection works** | [ ] | `curl /api/health \| jq '.checks.database'` |
| **Connection pool configured** | [ ] | Check `ARAGORA_DB_POOL_SIZE` |
| **Automated backups scheduled** | [ ] | Check cron/backup job |
| **Backup restore tested** | [ ] | Document last test date |
| **Migration scripts applied** | [ ] | `kubectl logs job/aragora-migrate` |

**Database Configuration:**
```bash
# Supabase (recommended for production)
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=<service_role_key>

# Connection tuning
ARAGORA_DB_POOL_SIZE=20
ARAGORA_DB_MAX_OVERFLOW=10
ARAGORA_DB_TIMEOUT=60.0
```

### 4. Redis Configuration

| Item | Status | Verification Command |
|------|--------|---------------------|
| **Redis connection works** | [ ] | `redis-cli ping` |
| **Redis URL configured** | [ ] | Check `ARAGORA_REDIS_URL` |
| **Rate limit uses Redis** | [ ] | `curl /api/rate-limits/config` shows `backend: redis` |
| **Redis persistence enabled** | [ ] | `redis-cli CONFIG GET save` |
| **Redis memory limit set** | [ ] | `redis-cli CONFIG GET maxmemory` |

**Redis Configuration:**
```bash
ARAGORA_REDIS_URL=redis://redis.aragora.svc:6379/0
ARAGORA_REDIS_KEY_PREFIX=aragora:prod:
ARAGORA_BLACKLIST_BACKEND=redis

# Fail-open for high availability (optional)
ARAGORA_RATE_LIMIT_FAIL_OPEN=true
```

### 5. Monitoring & Observability

| Item | Status | Verification Command |
|------|--------|---------------------|
| **Prometheus scraping** | [ ] | `curl /metrics \| head` |
| **Grafana dashboards imported** | [ ] | Check Grafana UI |
| **Alert rules configured** | [ ] | Check Alertmanager |
| **Sentry DSN configured** | [ ] | Check `SENTRY_DSN` |
| **Log aggregation working** | [ ] | Check logging platform |

**Monitoring Setup:**
```yaml
# ServiceMonitor for Prometheus Operator
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: aragora
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: aragora
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
```

### 6. SSL/TLS Certificates

| Item | Status | Verification Command |
|------|--------|---------------------|
| **cert-manager installed** | [ ] | `kubectl get pods -n cert-manager` |
| **ClusterIssuer configured** | [ ] | `kubectl get clusterissuer` |
| **Certificate issued** | [ ] | `kubectl get certificate -n aragora` |
| **Certificate valid** | [ ] | `echo \| openssl s_client -connect domain:443 2>/dev/null \| openssl x509 -noout -dates` |
| **Auto-renewal working** | [ ] | cert-manager handles automatically |

**Certificate Verification:**
```bash
# Check certificate status
kubectl describe certificate aragora-tls -n aragora

# Check expiration
kubectl get certificate aragora-tls -n aragora -o jsonpath='{.status.notAfter}'

# Test HTTPS
curl -vI https://your-domain.com/api/health 2>&1 | grep -E "SSL|subject|expire"
```

### 7. OAuth & Authentication

| Item | Status | Verification Command |
|------|--------|---------------------|
| **OAuth redirect URLs set** | [ ] | Check `GOOGLE_OAUTH_REDIRECT_URI`, `OAUTH_SUCCESS_URL` |
| **Allowed hosts configured** | [ ] | Check `OAUTH_ALLOWED_REDIRECT_HOSTS` |
| **SSO configured (if used)** | [ ] | See [SSO_SETUP.md](../enterprise/SSO_SETUP.md) |
| **Session timeout reasonable** | [ ] | Check `ARAGORA_JWT_EXPIRY_HOURS` (max 168h) |

**Production OAuth Configuration:**
```bash
# REQUIRED for OAuth in production
GOOGLE_OAUTH_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
GOOGLE_OAUTH_REDIRECT_URI=https://api.yourdomain.com/api/auth/oauth/google/callback
OAUTH_SUCCESS_URL=https://yourdomain.com/auth/success
OAUTH_ERROR_URL=https://yourdomain.com/auth/error
OAUTH_ALLOWED_REDIRECT_HOSTS=yourdomain.com,api.yourdomain.com

# Frontend URLs
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
NEXT_PUBLIC_WS_URL=wss://api.yourdomain.com
```

### 8. API Provider Configuration

| Item | Status | Verification Command |
|------|--------|---------------------|
| **Primary provider configured** | [ ] | `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` set |
| **Fallback provider configured** | [ ] | `OPENROUTER_API_KEY` for quota exhaustion |
| **Circuit breakers enabled** | [ ] | `curl /api/agents/circuit-breakers` |
| **Agent timeout configured** | [ ] | Check `ARAGORA_AGENT_TIMEOUT_SECONDS` |

**Provider Configuration:**
```bash
# Primary providers (at least one required)
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx

# Fallback provider (highly recommended)
OPENROUTER_API_KEY=sk-or-xxx

# Optional additional providers
MISTRAL_API_KEY=xxx
GEMINI_API_KEY=AIzaSy...
XAI_API_KEY=xai-xxx
```

### 9. RLM (Recursive Language Models)

| Item | Status | Verification Command |
|------|--------|---------------------|
| **RLM package installed** | [ ] | `python -c "from aragora.rlm import HAS_OFFICIAL_RLM; print(HAS_OFFICIAL_RLM)"` |
| **TRUE RLM enabled** | [ ] | Check server logs for `Created AragoraRLM with TRUE RLM support` |
| **Compression fallback NOT active** | [ ] | Logs should NOT show `Created AragoraRLM with compression fallback` |

**Verification Commands:**
```bash
# Check if TRUE RLM is available
python -c "from aragora.rlm import HAS_OFFICIAL_RLM; print(f'TRUE RLM: {HAS_OFFICIAL_RLM}')"
# Expected: TRUE RLM: True

# Check server logs after startup
docker logs aragora 2>&1 | grep -E "RLM Factory|TRUE RLM|compression fallback"
# Expected: [RLM Factory] Created AragoraRLM with TRUE RLM support
# NOT Expected: [RLM Factory] Created AragoraRLM with compression fallback

# Verify rlm package is installed
python -c "import aragora.rlm" 2>/dev/null || echo "RLM not importable - reinstall the base package: pip install -e ."
```

**Why TRUE RLM Matters:**
- TRUE RLM uses REPL-based context navigation for efficient memory retrieval
- Compression fallback uses a 5-level hierarchy (50%→80%→95% compression) which loses context fidelity
- TRUE RLM significantly improves knowledge retrieval quality in production workloads

**Troubleshooting:**
- If `HAS_OFFICIAL_RLM` is `False`: Install the official RLM package with `pip install rlm`
- Docker builds: Verify `pip install -e .` is included in the Dockerfile pip install line
- Lightsail/EC2: Ensure setup scripts include `pip install -e .`

### 10. Resource Limits

| Item | Status | Verification Command |
|------|--------|---------------------|
| **CPU limits set** | [ ] | Check deployment manifest |
| **Memory limits set** | [ ] | Check deployment manifest |
| **Concurrent debate limit** | [ ] | Check `ARAGORA_MAX_CONCURRENT_DEBATES` |
| **Rate limits configured** | [ ] | Check `ARAGORA_RATE_LIMIT` |

**Recommended Resource Limits:**
```yaml
# Kubernetes deployment
resources:
  requests:
    cpu: "500m"
    memory: "512Mi"
  limits:
    cpu: "2000m"
    memory: "2Gi"
```

### 10. Disaster Recovery

| Item | Status | Verification Command |
|------|--------|---------------------|
| **Backup schedule configured** | [ ] | Check cron jobs |
| **Backup retention policy** | [ ] | Document: ___ days |
| **Restore procedure tested** | [ ] | Document last test: ______ |
| **Rollback procedure documented** | [ ] | See [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) |
| **Incident response plan** | [ ] | See [RUNBOOK.md](RUNBOOK.md) |

---

## Go-Live Verification

Run these commands immediately before and after go-live:

### Pre-Launch Health Check

```bash
#!/bin/bash
# pre_launch_check.sh

echo "=== Pre-Launch Health Check ==="

# 1. Health endpoint
echo -n "Health endpoint: "
curl -sf https://your-domain/api/health | jq -r '.status' || echo "FAILED"

# 2. Database
echo -n "Database: "
curl -sf https://your-domain/api/health | jq -r '.checks.database.status' || echo "FAILED"

# 3. Redis
echo -n "Redis: "
curl -sf https://your-domain/api/health | jq -r '.checks.redis.status' || echo "FAILED"

# 4. Certificate validity
echo -n "TLS Certificate: "
echo | openssl s_client -connect your-domain:443 2>/dev/null | openssl x509 -noout -checkend 604800 && echo "OK (>7 days)" || echo "EXPIRING SOON"

# 5. Replicas
echo -n "Replicas: "
kubectl get deploy aragora -n aragora -o jsonpath='{.status.readyReplicas}/{.spec.replicas}'
echo ""

# 6. Pod distribution
echo "Pod distribution:"
kubectl get pods -n aragora -o wide | awk '{print $1, $7}' | tail -n +2

# 7. Circuit breakers
echo -n "Circuit breakers open: "
curl -sf https://your-domain/api/agents/circuit-breakers | jq '[.[] | select(.state=="open")] | length' || echo "?"

echo "=== Check Complete ==="
```

### Post-Launch Smoke Test

```bash
#!/bin/bash
# smoke_test.sh

echo "=== Post-Launch Smoke Test ==="

BASE_URL="https://your-domain"
TOKEN="your-test-token"

# 1. Create a test debate
echo "Creating test debate..."
DEBATE_ID=$(curl -sf -X POST "$BASE_URL/api/debates" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"topic": "Smoke test debate", "agents": ["claude", "gpt-4"], "max_rounds": 1}' \
  | jq -r '.debate_id')

if [ "$DEBATE_ID" == "null" ] || [ -z "$DEBATE_ID" ]; then
  echo "FAILED: Could not create debate"
  exit 1
fi
echo "Created debate: $DEBATE_ID"

# 2. Check debate status
sleep 5
echo "Checking debate status..."
STATUS=$(curl -sf "$BASE_URL/api/debates/$DEBATE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r '.status')
echo "Debate status: $STATUS"

# 3. WebSocket connectivity
echo "Testing WebSocket..."
timeout 5 websocat "wss://your-domain/ws" -1 && echo "WebSocket: OK" || echo "WebSocket: FAILED"

# 4. Metrics endpoint
echo -n "Metrics endpoint: "
curl -sf "$BASE_URL/metrics" | head -1 && echo "OK" || echo "FAILED"

echo "=== Smoke Test Complete ==="
```

---

## Environment Variable Quick Reference

### Minimum Production Configuration

```bash
# Environment mode
ARAGORA_ENV=production

# Authentication (REQUIRED)
ARAGORA_JWT_SECRET=<64-character-random-string>

# AI Providers (at least one required)
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
OPENROUTER_API_KEY=sk-or-xxx  # Fallback

# Database
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=<service_role_key>

# Redis (recommended)
ARAGORA_REDIS_URL=redis://redis:6379/0

# OAuth URLs (required for authentication)
GOOGLE_OAUTH_REDIRECT_URI=https://api.yourdomain.com/api/auth/oauth/google/callback
OAUTH_SUCCESS_URL=https://yourdomain.com/auth/success
OAUTH_ERROR_URL=https://yourdomain.com/auth/error
OAUTH_ALLOWED_REDIRECT_HOSTS=yourdomain.com,api.yourdomain.com

# Frontend
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
NEXT_PUBLIC_WS_URL=wss://api.yourdomain.com
```

### Production Tuning

```bash
# Rate limiting
ARAGORA_RATE_LIMIT=100            # Requests per minute per token
ARAGORA_IP_RATE_LIMIT=200         # Requests per minute per IP
ARAGORA_BURST_MULTIPLIER=2.0      # Allow short bursts

# Debate limits
ARAGORA_MAX_CONCURRENT_DEBATES=20
ARAGORA_AGENT_TIMEOUT_SECONDS=90

# WebSocket
ARAGORA_WS_MAX_MESSAGE_SIZE=131072  # 128KB
ARAGORA_WS_HEARTBEAT=30

# Observability
SENTRY_DSN=https://xxx@sentry.io/xxx
ARAGORA_LOG_LEVEL=INFO
ARAGORA_TELEMETRY_LEVEL=CONTROLLED

# Security
ARAGORA_BLACKLIST_BACKEND=redis
```

---

## Rollback Procedures

### Quick Rollback (Kubernetes)

```bash
# View rollout history
kubectl rollout history deployment/aragora -n aragora

# Rollback to previous version
kubectl rollout undo deployment/aragora -n aragora

# Rollback to specific revision
kubectl rollout undo deployment/aragora -n aragora --to-revision=3

# Verify rollback
kubectl rollout status deployment/aragora -n aragora
```

### Manual Rollback (Docker/Systemd)

```bash
# Stop current version
systemctl stop aragora

# Switch symlink to previous version
cd /opt/aragora
rm current
ln -s releases/v0.9.0 current  # Previous version

# Start
systemctl start aragora

# Verify
curl http://localhost:8080/api/health | jq '.version'
```

### Database Rollback

```bash
# Stop service first
kubectl scale deployment aragora --replicas=0 -n aragora

# Restore from backup
pg_restore -d aragora /backups/aragora_pre_release.dump

# Restart service
kubectl scale deployment aragora --replicas=3 -n aragora
```

---

## Alert Configuration

### Critical Alerts (PagerDuty/Immediate)

| Alert | Condition | Response Time |
|-------|-----------|---------------|
| `AragoraDown` | Health check fails for 2 min | Immediate |
| `HighErrorRate` | >5% error rate for 5 min | 5 min |
| `DatabaseDown` | DB check fails for 1 min | Immediate |
| `CertificateExpiring` | <7 days until expiry | 24 hours |

### Warning Alerts (Slack/Email)

| Alert | Condition | Response Time |
|-------|-----------|---------------|
| `HighMemory` | >80% memory for 10 min | 1 hour |
| `CircuitBreakerOpen` | Any agent circuit open | 15 min |
| `HighLatency` | p95 >500ms for 10 min | 1 hour |
| `RateLimitSpike` | >1000 429s in 5 min | 30 min |

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Engineering Lead | | | |
| Security Review | | | |
| Operations | | | |
| Product Owner | | | |

---

## Related Documentation

- [RUNBOOK.md](RUNBOOK.md) - Operational procedures and incident response
- [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) - Recovery procedures
- [ENVIRONMENT.md](../reference/ENVIRONMENT.md) - Complete environment variable reference
- [DEPLOYMENT.md](../DEPLOYMENT.md) - Kubernetes and Docker deployment guides
- [SECURITY.md](../enterprise/SECURITY.md) - Security architecture and practices
- [SCALING.md](SCALING.md) - Scaling guidelines and capacity planning
