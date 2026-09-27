# Go-Live Production Checklist

Step-by-step operator runbook for first production deployment of Aragora.

## Prerequisites

- [ ] Docker 24+ and Docker Compose v2 installed
- [ ] At least one LLM API key (Anthropic or OpenAI)
- [ ] DNS configured for your domain (e.g., `aragora.yourdomain.com`)
- [ ] TLS certificate or Let's Encrypt configured
- [ ] PostgreSQL 15+ (managed or self-hosted)
- [ ] Redis 7+ (managed or self-hosted)
- [ ] 4GB+ RAM available (8GB recommended for production)

---

## Phase 1: Pre-Deployment Validation

### 1.1 Verify Container Images

```bash
# Pull the latest images from ghcr.io
docker pull ghcr.io/synaptent/aragora/backend:latest
docker pull ghcr.io/synaptent/aragora/frontend:latest

# Or pin to a specific version
docker pull ghcr.io/synaptent/aragora/backend:2.10.0
docker pull ghcr.io/synaptent/aragora/frontend:2.10.0

# Verify images downloaded
docker images | grep aragora
```

### 1.2 Configure Secrets

**Option A: AWS Secrets Manager (recommended for production)**

```bash
# Create the secret
aws secretsmanager create-secret \
  --name aragora/production \
  --secret-string '{
    "ANTHROPIC_API_KEY": "sk-ant-...",
    "OPENAI_API_KEY": "sk-...",
    "OPENROUTER_API_KEY": "sk-or-...",
    "ARAGORA_API_TOKEN": "<generate-a-strong-token>",
    "POSTGRES_PASSWORD": "<strong-password>",
    "STRIPE_SECRET_KEY": "sk_live_..."
  }'

# Verify
aws secretsmanager get-secret-value --secret-id aragora/production --query Name
```

**Option B: Environment file (smaller deployments)**

```bash
cp .env.template .env

# Edit .env and set all required values
# At minimum:
#   ANTHROPIC_API_KEY=sk-ant-...
#   ARAGORA_API_TOKEN=<generate-a-strong-token>
#   POSTGRES_PASSWORD=<strong-password>
```

### 1.3 Generate API Token

```bash
# Generate a secure random token
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 1.4 Validate Environment Variables

```bash
# Required variables check
for var in ANTHROPIC_API_KEY ARAGORA_API_TOKEN; do
  if [ -z "${!var}" ]; then
    echo "MISSING: $var"
  else
    echo "OK: $var (set)"
  fi
done
```

### 1.5 Network and DNS

```bash
# Verify DNS resolves
dig aragora.yourdomain.com +short

# Verify port availability
for port in 8080 8765 5432 6379 9090 3001; do
  if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "WARNING: Port $port already in use"
  else
    echo "OK: Port $port available"
  fi
done
```

---

## Phase 2: Infrastructure Setup

### 2.1 Database Setup

**PostgreSQL (Docker Compose)**

```bash
cd deploy
docker compose --profile postgres up -d postgres

# Wait for healthy
docker compose --profile postgres exec postgres pg_isready -U aragora

# Verify connection
docker compose --profile postgres exec postgres psql -U aragora -c "SELECT version();"
```

**PostgreSQL (Managed / RDS)**

```bash
# Set the DSN
export ARAGORA_POSTGRES_DSN="postgresql://aragora:<password>@<host>:5432/aragora?sslmode=require"

# Verify connectivity
psql "$ARAGORA_POSTGRES_DSN" -c "SELECT 1;"
```

### 2.2 Redis Setup

```bash
cd deploy
docker compose up -d redis

# Wait for healthy
docker compose exec redis redis-cli ping
# Expected: PONG

# Verify persistence is enabled
docker compose exec redis redis-cli CONFIG GET appendonly
# Expected: appendonly yes
```

### 2.3 Storage Volumes

```bash
# Verify volumes exist
docker volume ls | grep aragora

# If starting fresh, they are created automatically
# For persistent data, ensure backup volumes are mounted:
#   - aragora-data: Application state
#   - aragora-knowledge: Knowledge Mound data
#   - aragora-logs: Log files
#   - postgres-data: Database files
#   - redis-data: Redis AOF
```

---

## Phase 3: Deploy

### 3.1 Start Services

**Docker Compose**

```bash
cd deploy

# Start core services (backend + frontend + Redis)
docker compose up -d

# With PostgreSQL
docker compose --profile postgres up -d

# With monitoring (Prometheus + Grafana + Jaeger + Loki)
docker compose --profile monitoring up -d

# All profiles
docker compose --profile postgres --profile monitoring up -d
```

**Kubernetes (Helm)**

```bash
# Create namespace
kubectl create namespace aragora

# Create secrets
kubectl -n aragora create secret generic aragora-secrets \
  --from-literal=anthropic-api-key="sk-ant-..." \
  --from-literal=aragora-api-token="<token>" \
  --from-literal=postgres-password="<password>"

# Install
helm install aragora deploy/helm/aragora/ \
  --namespace aragora \
  --set secrets.existingSecret=aragora-secrets \
  -f deploy/helm/aragora/values-production.yaml

# Watch rollout
kubectl -n aragora rollout status deployment/aragora-backend --timeout=300s
```

### 3.2 Wait for Startup

```bash
# Wait for backend to be healthy (up to 2 minutes)
echo "Waiting for backend..."
for i in $(seq 1 60); do
  if curl -sf http://localhost:8080/healthz >/dev/null 2>&1; then
    echo "Backend is healthy after ${i}x2 seconds"
    break
  fi
  sleep 2
done

# Verify readiness
curl -sf http://localhost:8080/readyz | python3 -m json.tool
```

### 3.3 Run Database Migrations

```bash
# Migrations run automatically on startup, but to run manually:
docker compose exec backend python -m aragora.db.migrate upgrade

# Check migration status
docker compose exec backend python -m aragora.db.migrate status
```

---

## Phase 4: Post-Deployment Verification

### 4.1 Health Checks

```bash
# Liveness probe (K8s-style, no auth)
curl -sf http://localhost:8080/healthz
# Expected: {"status": "ok"}

# Readiness probe (no auth)
curl -sf http://localhost:8080/readyz
# Expected: {"status": "ready", ...}

# Detailed health (requires API token)
curl -sf http://localhost:8080/api/health \
  -H "Authorization: Bearer $ARAGORA_API_TOKEN" | python3 -m json.tool
# Expected: status=healthy, all components healthy
```

### 4.2 Smoke Tests

```bash
# API version check
curl -sf http://localhost:8080/api/v1/status | python3 -m json.tool

# List available agents
curl -sf http://localhost:8080/api/v1/agents \
  -H "Authorization: Bearer $ARAGORA_API_TOKEN" | python3 -m json.tool

# Start a test debate
curl -sf -X POST http://localhost:8080/api/v1/debates \
  -H "Authorization: Bearer $ARAGORA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "What is 2+2? Provide a brief answer.",
    "protocol": {"rounds": 1, "consensus": "majority"}
  }' | python3 -m json.tool
```

### 4.3 WebSocket Connectivity

```bash
# Test WebSocket endpoint (requires websocat or wscat)
# Install: npm install -g wscat
wscat -c ws://localhost:8765/ws --execute '{"type":"ping"}' --wait 2

# Or with curl (just verify the upgrade handshake)
curl -sf -o /dev/null -w "%{http_code}" \
  -H "Upgrade: websocket" \
  -H "Connection: Upgrade" \
  http://localhost:8765/ws
# Expected: 101 (Switching Protocols)
```

### 4.4 Frontend

```bash
# Verify frontend is serving
curl -sf -o /dev/null -w "%{http_code}" http://localhost:3000/
# Expected: 200

# Verify API connection from frontend
curl -sf http://localhost:3000/ | grep -q "aragora" && echo "Frontend OK" || echo "Frontend FAILED"
```

### 4.5 TLS Verification

```bash
# If TLS is configured, verify the certificate
openssl s_client -connect aragora.yourdomain.com:443 -servername aragora.yourdomain.com </dev/null 2>/dev/null | \
  openssl x509 -noout -dates -subject

# Verify HTTPS endpoint
curl -sf https://aragora.yourdomain.com/healthz
```

### 4.6 Monitoring Stack

```bash
# Prometheus targets
curl -sf http://localhost:9090/api/v1/targets | python3 -c "
import json, sys
data = json.load(sys.stdin)
for t in data.get('data', {}).get('activeTargets', []):
    print(f\"{t['labels'].get('job', '?'):30s} {t['health']:10s} {t.get('lastError', '')}\")
"

# Grafana health
curl -sf http://localhost:3001/api/health
# Expected: {"database": "ok"}

# Verify Prometheus is scraping Aragora
curl -sf 'http://localhost:9090/api/v1/query?query=up{job="aragora-backend"}' | python3 -m json.tool
```

---

## Phase 5: Security Hardening

### 5.1 Verify Configuration

```bash
# CORS origins restricted
echo "ARAGORA_ALLOWED_ORIGINS should be: https://aragora.yourdomain.com"

# API token is not default
if [ "$ARAGORA_API_TOKEN" = "changeme" ] || [ -z "$ARAGORA_API_TOKEN" ]; then
  echo "CRITICAL: API token must be set to a strong random value"
fi

# Database password is not default
if [ "$POSTGRES_PASSWORD" = "aragora_dev" ] || [ -z "$POSTGRES_PASSWORD" ]; then
  echo "CRITICAL: Database password must be changed from default"
fi
```

### 5.2 Rate Limiting

```bash
# Rate limiting is enabled by default. Verify:
curl -sf http://localhost:8080/api/health \
  -H "Authorization: Bearer $ARAGORA_API_TOKEN" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('Rate limiting:', data.get('features', {}).get('rate_limiting', 'unknown'))
"
```

### 5.3 Firewall Rules

```bash
# Only expose necessary ports externally:
# - 443 (HTTPS via reverse proxy)
# - 8765 (WebSocket, if not proxied)
#
# Internal only (not exposed to internet):
# - 8080 (backend HTTP, behind reverse proxy)
# - 5432 (PostgreSQL)
# - 6379 (Redis)
# - 9090 (Prometheus)
# - 3001 (Grafana)
```

---

## Phase 6: Day-2 Operations

### 6.1 Configure Automated Backups

```bash
# Database backup cron (add to crontab)
# Daily at 2 AM, retain 30 days
cat <<'CRON'
0 2 * * * docker exec aragora-postgres pg_dump -U aragora aragora | gzip > /backups/aragora_$(date +\%Y\%m\%d).sql.gz
0 3 * * * find /backups -name "*.sql.gz" -mtime +30 -delete
CRON

# Verify backup directory exists
mkdir -p /backups
```

### 6.2 Configure Log Rotation

```bash
# Docker handles log rotation via daemon.json:
cat /etc/docker/daemon.json
# Should include:
# {
#   "log-driver": "json-file",
#   "log-opts": {
#     "max-size": "50m",
#     "max-file": "5"
#   }
# }
```

### 6.3 Set Up Alerting

```bash
# Configure Alertmanager for Slack/PagerDuty notifications
# Edit deploy/monitoring/alertmanager.yml with your webhook URLs

# Verify alert rules loaded
curl -sf http://localhost:9090/api/v1/rules | python3 -c "
import json, sys
data = json.load(sys.stdin)
groups = data.get('data', {}).get('groups', [])
print(f'Alert rule groups loaded: {len(groups)}')
for g in groups:
    print(f'  {g[\"name\"]}: {len(g[\"rules\"])} rules')
"
```

### 6.4 Upgrade Procedure

```bash
# 1. Backup
docker exec aragora-postgres pg_dump -U aragora aragora > backup_pre_upgrade.sql

# 2. Pull new images
docker compose pull

# 3. Rolling restart
docker compose up -d --no-deps backend
docker compose up -d --no-deps frontend

# 4. Verify
curl -sf http://localhost:8080/healthz
curl -sf http://localhost:8080/api/v1/status | python3 -m json.tool

# 5. Rollback if needed
docker compose down
docker compose up -d  # Uses cached previous images
# Or restore database:
# psql -U aragora aragora < backup_pre_upgrade.sql
```

### 6.5 Monitoring Dashboards

Import the pre-built Grafana dashboards from `deploy/monitoring/grafana/dashboards/`:

1. **Debate Performance** - Latency, throughput, consensus rates, agent quality
2. **System Health** - CPU, memory, disk, process metrics
3. **API Operations** - Request rates, error rates, p99 latency by endpoint
4. **Security** - Auth failures, rate limiting, RBAC denials, circuit breakers

See `deploy/monitoring/grafana/dashboards/README.md` for import instructions.

---

## Quick Validation Script

Run this after deployment to validate the full stack:

```bash
#!/usr/bin/env bash
set -euo pipefail

API="http://localhost:8080"
PASS=0
FAIL=0

check() {
  local name="$1" cmd="$2"
  if eval "$cmd" >/dev/null 2>&1; then
    echo "[PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "[FAIL] $name"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Aragora Go-Live Validation ==="
echo ""

check "Backend liveness"     "curl -sf $API/healthz"
check "Backend readiness"    "curl -sf $API/readyz"
check "API health"           "curl -sf $API/api/health -H 'Authorization: Bearer $ARAGORA_API_TOKEN'"
check "Frontend"             "curl -sf http://localhost:3000/"
check "Redis"                "docker compose exec -T redis redis-cli ping"
check "Metrics endpoint"     "curl -sf $API/metrics"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && echo "All checks passed." || echo "Some checks failed. Review above."
```

---

## Rollback Procedure

If anything goes wrong during deployment:

**Docker Compose:**

```bash
# Stop current deployment
docker compose down

# Restore database from backup
docker compose --profile postgres up -d postgres
docker compose exec -T postgres psql -U aragora aragora < backup_pre_deploy.sql

# Start with previous image version
ARAGORA_BACKEND_IMAGE=ghcr.io/synaptent/aragora/backend:<previous-version> \
ARAGORA_FRONTEND_IMAGE=ghcr.io/synaptent/aragora/frontend:<previous-version> \
docker compose up -d

# Verify
curl -sf http://localhost:8080/healthz
```

**Kubernetes:**

```bash
# Rollback to previous revision
kubectl -n aragora rollout undo deployment/aragora-backend
kubectl -n aragora rollout undo deployment/aragora-frontend

# Verify
kubectl -n aragora rollout status deployment/aragora-backend
```
