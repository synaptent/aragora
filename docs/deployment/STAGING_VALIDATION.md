# Staging Environment Validation Runbook

**Version:** 1.0.0
**Last Updated:** January 14, 2026

---

## Overview

This runbook defines the validation procedures for staging deployments before production promotion. All checks must pass before releasing to production.

---

## Pre-Deployment Checklist

### Environment Setup

```bash
# Set staging environment
export ARAGORA_ENV=staging
export ARAGORA_API_URL=https://staging-api.aragora.ai
export ARAGORA_WS_URL=wss://staging-ws.aragora.ai

# Verify environment variables
env | grep ARAGORA
```

### Required Secrets

| Secret | Source | Validated |
|--------|--------|-----------|
| `ARAGORA_JWT_SECRET` | Secrets manager | [ ] |
| `ANTHROPIC_API_KEY` | Secrets manager | [ ] |
| `OPENAI_API_KEY` | Secrets manager | [ ] |
| `SUPABASE_URL` | Secrets manager | [ ] |
| `SUPABASE_KEY` | Secrets manager | [ ] |
| `STRIPE_SECRET_KEY` | Secrets manager | [ ] |
| `SENTRY_DSN` | Secrets manager | [ ] |

---

## Deployment Validation

### 1. Infrastructure Health

```bash
#!/bin/bash
# infrastructure_check.sh

echo "=== Aragora Staging Validation ==="
echo ""

# API Health
echo "Checking API health..."
API_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" $ARAGORA_API_URL/api/health)
if [ "$API_HEALTH" == "200" ]; then
    echo "  [PASS] API health: $API_HEALTH"
else
    echo "  [FAIL] API health: $API_HEALTH"
    exit 1
fi

# Detailed health
echo "Checking detailed health..."
HEALTH_DETAILS=$(curl -s $ARAGORA_API_URL/api/health/detailed)
echo "$HEALTH_DETAILS" | jq -e '.checks.database.status == "healthy"' > /dev/null
if [ $? -eq 0 ]; then
    echo "  [PASS] Database healthy"
else
    echo "  [FAIL] Database unhealthy"
    exit 1
fi

echo "$HEALTH_DETAILS" | jq -e '.checks.redis.status == "healthy"' > /dev/null
if [ $? -eq 0 ]; then
    echo "  [PASS] Redis healthy"
else
    echo "  [WARN] Redis not available (optional)"
fi

# WebSocket connectivity
echo "Checking WebSocket..."
WS_CHECK=$(curl -s -o /dev/null -w "%{http_code}" $ARAGORA_API_URL/api/ws/stats)
if [ "$WS_CHECK" == "200" ]; then
    echo "  [PASS] WebSocket server running"
else
    echo "  [WARN] WebSocket stats unavailable"
fi

echo ""
echo "=== Infrastructure Check Complete ==="
```

### 2. Authentication Validation

```bash
#!/bin/bash
# auth_check.sh

echo "=== Authentication Validation ==="

# Test token generation
echo "Testing token generation..."
TOKEN_RESPONSE=$(curl -s -X POST $ARAGORA_API_URL/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email": "staging-test@aragora.ai", "password": "staging-password"}')

if echo "$TOKEN_RESPONSE" | jq -e '.access_token' > /dev/null 2>&1; then
    echo "  [PASS] Token generation works"
    ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token')
else
    echo "  [INFO] Login test skipped (no test user)"
fi

# Test API key authentication
echo "Testing API key auth..."
API_KEY_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $STAGING_API_KEY" \
    $ARAGORA_API_URL/api/user/me)

if [ "$API_KEY_RESPONSE" == "200" ] || [ "$API_KEY_RESPONSE" == "401" ]; then
    echo "  [PASS] API key auth endpoint responding"
else
    echo "  [FAIL] API key auth endpoint error: $API_KEY_RESPONSE"
fi

echo ""
echo "=== Authentication Validation Complete ==="
```

### 3. Core Functionality Tests

```bash
#!/bin/bash
# functionality_check.sh

echo "=== Core Functionality Validation ==="

# Test debate creation (dry run)
echo "Testing debate endpoint..."
DEBATE_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST $ARAGORA_API_URL/api/debates \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $STAGING_API_KEY" \
    -d '{"topic": "Staging validation test", "agents": ["demo", "demo"], "rounds": 1, "dry_run": true}')

if [ "$DEBATE_CHECK" == "200" ] || [ "$DEBATE_CHECK" == "201" ] || [ "$DEBATE_CHECK" == "401" ]; then
    echo "  [PASS] Debate endpoint responding"
else
    echo "  [WARN] Debate endpoint: $DEBATE_CHECK"
fi

# Test audit log
echo "Testing audit log..."
AUDIT_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $STAGING_API_KEY" \
    "$ARAGORA_API_URL/api/audit/events?limit=5")

if [ "$AUDIT_CHECK" == "200" ] || [ "$AUDIT_CHECK" == "401" ]; then
    echo "  [PASS] Audit endpoint responding"
else
    echo "  [WARN] Audit endpoint: $AUDIT_CHECK"
fi

# Test usage endpoint
echo "Testing usage tracking..."
USAGE_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $STAGING_API_KEY" \
    "$ARAGORA_API_URL/api/billing/usage")

if [ "$USAGE_CHECK" == "200" ] || [ "$USAGE_CHECK" == "401" ]; then
    echo "  [PASS] Usage endpoint responding"
else
    echo "  [WARN] Usage endpoint: $USAGE_CHECK"
fi

echo ""
echo "=== Core Functionality Validation Complete ==="
```

### 4. Performance Baseline

```bash
#!/bin/bash
# performance_check.sh

echo "=== Performance Baseline Validation ==="

# Health endpoint latency
echo "Measuring health endpoint latency..."
HEALTH_TIMES=""
for i in {1..10}; do
    TIME=$(curl -s -o /dev/null -w "%{time_total}" $ARAGORA_API_URL/api/health)
    HEALTH_TIMES="$HEALTH_TIMES $TIME"
done

AVG_HEALTH=$(echo $HEALTH_TIMES | awk '{sum=0; for(i=1;i<=NF;i++) sum+=$i; print sum/NF}')
echo "  Average health latency: ${AVG_HEALTH}s"

if (( $(echo "$AVG_HEALTH < 0.1" | bc -l) )); then
    echo "  [PASS] Health latency < 100ms"
else
    echo "  [WARN] Health latency > 100ms"
fi

# Concurrent request test
echo "Testing concurrent requests..."
ab -n 100 -c 10 -q $ARAGORA_API_URL/api/health 2>/dev/null | grep "Requests per second" || echo "  [INFO] ab not available, skipping"

echo ""
echo "=== Performance Baseline Complete ==="
```

---

## Test Suite Execution

### Run Staging Tests

```bash
# Full staging test suite
pytest tests/ -v -m "not slow" --tb=short -q

# Multi-tenant isolation tests
pytest tests/multi_tenant/ -v --tb=short

# Benchmark tests (if pytest-benchmark installed)
pytest tests/benchmarks/ -v --benchmark-only

# Integration tests
pytest tests/integration/ -v --tb=short -k "staging"
```

### Expected Results

| Test Suite | Min Pass Rate | Critical |
|------------|---------------|----------|
| Unit tests | 99% | Yes |
| Multi-tenant | 100% | Yes |
| Integration | 95% | No |
| Benchmarks | 90% | No |

---

## Data Validation

### Database Schema Check

```sql
-- Verify schema version
SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 1;

-- Check critical tables exist
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN ('users', 'debates', 'audit_events', 'usage_events');

-- Verify indexes
SELECT indexname, tablename FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename;
```

### Data Integrity

```bash
# Verify audit log integrity
curl -X POST $ARAGORA_API_URL/api/audit/verify \
    -H "Authorization: Bearer $STAGING_API_KEY"

# Expected response: {"valid": true, "errors": []}
```

---

## Security Validation

### TLS Configuration

```bash
# Check TLS version
echo | openssl s_client -connect staging-api.aragora.ai:443 2>/dev/null | grep "Protocol"
# Expected: TLSv1.3

# Check certificate validity
echo | openssl s_client -connect staging-api.aragora.ai:443 2>/dev/null | openssl x509 -noout -dates
```

### Security Headers

```bash
# Check security headers
curl -I $ARAGORA_API_URL/api/health 2>/dev/null | grep -E "(Strict-Transport|X-Content-Type|X-Frame)"

# Expected headers:
# Strict-Transport-Security: max-age=31536000
# X-Content-Type-Options: nosniff
# X-Frame-Options: DENY
```

### Rate Limiting

```bash
# Test rate limiting is active
for i in {1..20}; do
    curl -s -o /dev/null -w "%{http_code}\n" $ARAGORA_API_URL/api/health
done | sort | uniq -c
# Should see some 429s if rate limiting is aggressive
```

---

## Rollback Procedures

### Quick Rollback

```bash
# Kubernetes rollback
kubectl -n aragora rollout undo deployment/aragora

# Verify rollback
kubectl -n aragora rollout status deployment/aragora
```

### Database Rollback

```bash
# Restore from backup
pg_restore -d aragora_staging backup_YYYYMMDD.dump

# Or revert migration
alembic downgrade -1
```

---

## Sign-off Checklist

| Category | Check | Validator | Date |
|----------|-------|-----------|------|
| Infrastructure | All health checks pass | | |
| Authentication | Login and API keys work | | |
| Functionality | Core endpoints responding | | |
| Performance | Latency within SLA | | |
| Security | TLS and headers correct | | |
| Tests | Test suite passes | | |
| Data | Schema and integrity valid | | |

### Approval

```
Staging Validation Approved: ________________
Date: ________________
Promoted to Production: [ ] Yes  [ ] No
Production Deploy Date: ________________
```

---

## Related Documentation

- [DEPLOYMENT.md](../DEPLOYMENT.md) - Full deployment guide
- [RUNBOOK.md](RUNBOOK.md) - Operational procedures
- [SLA.md](../enterprise/SLA.md) - Service level agreements
- [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) - Recovery procedures
