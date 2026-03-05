# Core API Surface Analysis

Last updated: 2026-02-13

## Summary

The Aragora server exposes 3,000+ API operations across 208 handler files. This document identifies the ~50 core endpoints that serve 90% of users and categorizes the rest for potential extraction.

## Core Endpoints (~50)

These are the endpoints every Aragora user needs.

### Debates (12 endpoints)

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/api/v1/debates` | debates | Create a new debate |
| GET | `/api/v1/debates` | debates | List debates |
| GET | `/api/v1/debates/:id` | debates | Get debate details |
| DELETE | `/api/v1/debates/:id` | debates | Delete a debate |
| POST | `/api/v1/debates/:id/start` | debates | Start a debate |
| GET | `/api/v1/debates/:id/status` | debates | Get debate status |
| GET | `/api/v1/debates/:id/result` | debates | Get debate result |
| POST | `/api/v1/debates/quick` | debates | One-shot quick debate |
| GET | `/api/v1/debates/matrix` | matrix_debates | Matrix debate view |
| POST | `/api/v1/debates/graph` | graph_debates | Graph debate |
| POST | `/api/v1/playground/debate` | playground | Interactive playground |
| GET | `/api/v1/playground/status` | playground | Playground status |

### Receipts (4 endpoints)

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/api/v2/receipts` | receipts | List decision receipts |
| GET | `/api/v2/receipts/:id` | receipts | Get receipt by ID |
| POST | `/api/v2/receipts/:id/verify` | receipts | Verify receipt HMAC |
| POST | `/api/v2/receipts/:id/share` | receipts | Generate share link |

### Agents (6 endpoints)

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/api/v1/agents` | agents | List available agents |
| GET | `/api/v1/agents/:name` | agents | Get agent details |
| GET | `/api/v1/agents/:name/stats` | agents | Agent performance stats |
| GET | `/api/v1/rankings` | rankings | ELO rankings |
| GET | `/api/v1/tournaments` | tournaments | Tournament standings |
| POST | `/api/v1/tournaments` | tournaments | Create tournament |

### Authentication (8 endpoints)

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/api/v1/auth/login` | auth | Login |
| POST | `/api/v1/auth/register` | auth | Register |
| POST | `/api/v1/auth/logout` | auth | Logout |
| POST | `/api/v1/auth/refresh` | auth | Refresh token |
| GET | `/api/v1/auth/me` | auth | Current user |
| POST | `/api/v1/auth/api-keys` | auth | Create API key |
| GET | `/api/v1/auth/api-keys` | auth | List API keys |
| DELETE | `/api/v1/auth/api-keys/:id` | auth | Revoke API key |

### Health & Config (6 endpoints)

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/api/v1/health` | health | Health check |
| GET | `/api/v1/health/ready` | health | Readiness probe |
| GET | `/api/v1/health/live` | health | Liveness probe |
| GET | `/api/v1/config` | config | Server configuration |
| GET | `/api/v1/version` | version | Version info |
| GET | `/api/v1/features` | features | Feature flags |

### Gauntlet & Review (8 endpoints)

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/api/v1/gauntlet/run` | gauntlet | Run adversarial gauntlet |
| GET | `/api/v1/gauntlet/findings` | gauntlet | List findings |
| GET | `/api/v1/gauntlet/receipts` | gauntlet | Gauntlet receipts |
| POST | `/api/v1/review` | review | Code review |
| GET | `/api/v1/review/:id` | review | Get review result |
| POST | `/api/v1/skills` | skills | Register skill |
| GET | `/api/v1/skills` | skills | List skills |
| GET | `/api/v1/skills/marketplace` | skills | Marketplace browse |

### Webhooks & Events (4 endpoints)

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/api/v1/webhooks` | webhooks | Register webhook |
| GET | `/api/v1/webhooks` | webhooks | List webhooks |
| GET | `/api/v1/webhooks/events` | webhooks | Event types |
| GET | `/api/v1/webhooks/dead-letter` | webhooks | Dead letter queue |

**Total core: ~48 endpoints**

## Extended Endpoints (by category)

| Category | Est. Endpoints | Handler Files | LOC | Priority |
|----------|---------------|---------------|-----|----------|
| Analytics & Dashboard | ~30 | 15 | 8K | Keep |
| Learning & Insights | ~15 | 8 | 5K | Keep |
| Knowledge Mound | ~25 | 12 | 10K | Keep |
| Memory & Continuum | ~20 | 10 | 7K | Keep |
| Pulse (trending) | ~15 | 6 | 4K | Keep |
| Billing & Metering | ~20 | 10 | 6K | Optional |
| Email Services | ~15 | 5 | 5K | Optional |
| Compliance | ~20 | 8 | 6K | Enterprise |
| Notifications | ~10 | 4 | 3K | Keep |
| Integrations (Slack, etc) | ~25 | 15 | 8K | Optional |

## Enterprise Endpoints

| Category | Est. Endpoints | Handler Files | LOC | Notes |
|----------|---------------|---------------|-----|-------|
| RBAC Administration | ~25 | 12 | 8K | Gate behind license |
| Multi-Tenancy | ~15 | 6 | 5K | Gate behind license |
| Control Plane | ~30 | 15 | 10K | Gate behind license |
| Audit & Compliance | ~25 | 10 | 8K | Gate behind license |
| SSO/OIDC/SAML | ~15 | 8 | 6K | Gate behind license |
| Backup/DR | ~10 | 4 | 3K | Gate behind license |

## Experimental Endpoints (Candidates for extraction)

| Category | Est. Endpoints | Handler Files | LOC | Action |
|----------|---------------|---------------|-----|--------|
| Genesis (evolution) | ~10 | 3 | 3K | Extract to aragora-experimental |
| Blockchain/ERC-8004 | ~15 | 5 | 4K | Extract to aragora-experimental |
| Nomic Loop | ~10 | 4 | 3K | Extract to aragora-experimental |
| Workflow Engine | ~20 | 8 | 6K | Extract to aragora-experimental |
| Computer Use | ~10 | 4 | 4K | Extract to aragora-experimental |
| Feature verticals | ~60 | 30 | 20K | Gate behind feature flags |

## Recommendations

### 1. Handler loading tiers

```python
# In server startup, load handlers in tiers:
CORE_HANDLERS = [...]      # Always loaded (~48 endpoints)
EXTENDED_HANDLERS = [...]   # Loaded by default, can disable
ENTERPRISE_HANDLERS = [...]  # Loaded only with license key
EXPERIMENTAL_HANDLERS = [...] # Loaded only with --experimental flag
```

### 2. Estimated impact

| Action | Handlers Removed | Endpoints Reduced | Startup Time |
|--------|-----------------|-------------------|-------------|
| Remove experimental | ~30 files | ~65 endpoints | -15% |
| Gate enterprise | ~55 files | ~120 endpoints | -25% |
| Gate feature verticals | ~30 files | ~60 endpoints | -15% |
| **Total (core only)** | **~115 fewer** | **~245 fewer** | **~55% faster** |

### 3. Path forward

1. **Immediate**: Tag handlers with tier metadata (`TIER = "core"`)
2. **Short-term**: Lazy-load non-core handlers on first request
3. **Medium-term**: Extract experimental handlers to `aragora-experimental` package
4. **Long-term**: Enterprise handlers behind license check, separate `aragora-enterprise` package
