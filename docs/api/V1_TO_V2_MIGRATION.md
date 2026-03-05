# v1 to v2 API Migration Guide

This guide covers migrating API clients from the Aragora v1 (legacy ThreadingHTTPServer) endpoints to the v2 (FastAPI/uvicorn) endpoints.

## Overview

### Why v2?

The v1 API runs on Python's `ThreadingHTTPServer` with a mixin-based handler architecture. It works, but has limitations:

- **Concurrency**: ~500 concurrent connections per process.
- **No native async**: Sync handlers bridge to async code, adding overhead.
- **Manual OpenAPI**: The OpenAPI spec is maintained separately from handler code.
- **No request validation**: Body/query validation is handler-by-handler.

The v2 API runs on FastAPI/uvicorn:

- **Concurrency**: 10,000+ concurrent connections (async-native).
- **Auto-generated OpenAPI**: Pydantic models produce accurate schemas at `/api/v2/docs`.
- **Request validation**: Pydantic validates all request bodies and query parameters automatically. Invalid input returns 422 with detailed error messages.
- **Server-Sent Events**: Native SSE support for real-time debate streaming.
- **Dependency injection**: Auth, RBAC, and storage are injected via FastAPI `Depends()`.
- **Middleware stack**: Security headers, CORS, tracing, and body size validation are applied consistently.

### What's different?

| Aspect | v1 | v2 |
|--------|----|----|
| Server | `ThreadingHTTPServer` | uvicorn (ASGI) |
| Path prefix | `/api/v1/...` | `/api/v2/...` |
| Docs | Manual (`/api/v1/docs`) | Auto-generated (`/api/v2/docs`, `/api/v2/redoc`) |
| Validation | Per-handler | Pydantic models (auto 422 on bad input) |
| Auth | Header extraction in handler | FastAPI dependency injection |
| Errors | Varies by handler | Consistent JSON: `{"detail": "..."}` |
| Streaming | WebSocket only | SSE (decisions) + WebSocket |

### Scope

The v2 API covers **19 route modules** with 120+ endpoints across debates, decisions, agents, consensus, receipts, gauntlet, pipeline, knowledge, workflows, compliance, auth, memory, costs, tasks, notifications, inbox, and the API explorer. The v1 API has ~3,000+ operations; the v2 surface covers the most commonly used operations. Endpoints not yet migrated to v2 remain available on v1.

---

## Quick Start

### Option 1: Standalone FastAPI server

```bash
uvicorn aragora.server.fastapi.factory:app --host 0.0.0.0 --port 8081
```

This starts only the v2 API on port 8081. The v1 server does not run.

### Option 2: Replace v1 with v2 via environment variable

```bash
ARAGORA_USE_FASTAPI=true aragora serve
```

When `ARAGORA_USE_FASTAPI=true` is set, `aragora serve` starts FastAPI/uvicorn instead of `ThreadingHTTPServer` on the same port (default 8080). WebSocket servers still start on their dedicated ports (8765-8768).

### Option 3: Run v2 on a separate port alongside v1

```bash
# Terminal 1: v1 on default port
aragora serve --http-port 8080

# Terminal 2: v2 on separate port
ARAGORA_FASTAPI_PORT=8081 uvicorn aragora.server.fastapi.factory:app --port 8081
```

### Verify it works

```bash
# Health check
curl http://localhost:8081/api/v2/health

# Interactive API docs
open http://localhost:8081/api/v2/docs
```

---

## Endpoint Mapping Table

All v2 routes use the `/api/v2` prefix. The equivalent v1 routes use `/api/v1` (or `/api/` without version for some legacy endpoints).

### Health

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/health` | `/api/v2/health` | GET | v2 adds `subsystems` object with per-component health |
| `/api/v1/metrics/summary` | `/api/v2/metrics/summary` | GET | Same shape |
| (none) | `/healthz` | GET | Kubernetes liveness (new) |
| (none) | `/livez` | GET | Kubernetes liveness strict (new) |
| (none) | `/readyz` | GET | Kubernetes readiness (new) |

### Debates

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/debates` | `/api/v2/debates` | GET | v2 uses `limit`/`offset` query params (not `page`/`per_page`). Response is `{debates, total, limit, offset}` |
| `/api/v1/debates` | `/api/v2/debates` | POST | Request body: `question` (was `topic` in some v1 variants), `agents` (string), `rounds`, `consensus`. Response: `{debate_id, status}` |
| `/api/v1/debates/{id}` | `/api/v2/debates/{debate_id}` | GET | Full debate detail. Response model includes typed `protocol`, `agents`, `rounds` fields |
| `/api/v1/debates/{id}/messages` | `/api/v2/debates/{debate_id}/messages` | GET | Adds `has_more` boolean for pagination |
| `/api/v1/debates/{id}/convergence` | `/api/v2/debates/{debate_id}/convergence` | GET | Same data, typed response model |
| `/api/v1/debates/{id}/export/{fmt}` | `/api/v2/debates/{debate_id}/export/{export_format}` | GET | Path param renamed from `format` to `export_format`. Supports `json`, `csv`, `html`, `txt`, `md` |
| (none) | `/api/v2/debates/{debate_id}/argument-graph` | GET | New. Returns argument graph (JSON or Mermaid) |
| (none) | `/api/v2/debates/{debate_id}/stats` | GET | New. Graph statistics |
| `/api/v1/debates/{id}` | `/api/v2/debates/{debate_id}` | PATCH | New. Update title, tags, status, metadata |
| `/api/v1/debates/{id}` | `/api/v2/debates/{debate_id}` | DELETE | Cascade deletes critiques. Use PATCH+`status=archived` for soft delete |

### Decisions (Async Debate Orchestration)

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/debates` (POST, sync) | `/api/v2/decisions` | POST | **Breaking**: Returns 202 (not 200). Debate runs in background. Response includes `events_url` for SSE subscription |
| (none) | `/api/v2/decisions` | GET | List all decisions with status filter |
| (none) | `/api/v2/decisions/{debate_id}` | GET | Poll for status: `progress`, `current_round`, `result` |
| (none) | `/api/v2/decisions/{debate_id}` | DELETE | Cancel a running debate |
| (none) | `/api/v2/decisions/{debate_id}/events` | GET | **New**: Server-Sent Events stream for real-time updates |

### Agents

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/agents` | `/api/v2/agents` | GET | Adds `include_stats` query param. Response: `{agents, total}` |
| `/api/v1/agents/{id}` | `/api/v2/agents/{agent_id}` | GET | Typed response with `type`, `requires_api_key`, `fallback_model` |
| `/api/v1/agents/rankings` | `/api/v2/agents/rankings` | GET | Same as leaderboard (alias) |
| `/api/v1/agents/leaderboard` | `/api/v2/agents/leaderboard` | GET | Adds `domain` filter, `win_rate` field |
| (none) | `/api/v2/agents/domains` | GET | New. List agent domains/specializations |
| (none) | `/api/v2/agents/{agent_id}/capabilities` | GET | New. Provider, model, context window, specialties |
| (none) | `/api/v2/agents/{agent_id}/stats` | GET | New. Performance stats, recent history |
| (none) | `/api/v2/agents/{agent_id}/calibration` | GET | New. Calibration scores and buckets |
| `/api/v1/agents` | `/api/v2/agents` | POST | Register a custom agent. Returns 201 |

### Consensus

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/consensus/similar` | `/api/v2/consensus/similar` | GET | `topic` is now a required query param with validation |
| `/api/v1/consensus/settled` | `/api/v2/consensus/settled` | GET | Same shape. `min_confidence` validated (0.0-1.0) |
| `/api/v1/consensus/stats` | `/api/v2/consensus/stats` | GET | Same shape |
| `/api/v1/consensus/dissents` | `/api/v2/consensus/dissents` | GET | Adds `domain` filter |
| (none) | `/api/v2/consensus/contrarian-views` | GET | New. Historical contrarian perspectives |
| (none) | `/api/v2/consensus/risk-warnings` | GET | New. Risk warnings and edge cases |
| `/api/v1/consensus/domain/{d}` | `/api/v2/consensus/domain/{domain}` | GET | Domain validated against safe slug pattern |
| `/api/v1/consensus/status/{id}` | `/api/v2/consensus/status/{debate_id}` | GET | Same shape plus `partial_consensus` and `proof` objects |
| (none) | `/api/v2/consensus/detect` | POST | New. Detect consensus from a list of proposals |

### Receipts

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/receipts` | `/api/v2/receipts` | GET | Paginated with `limit`/`offset`. Adds `verdict` filter |
| `/api/v1/receipts/{id}` | `/api/v2/receipts/{receipt_id}` | GET | Full detail with findings, claims, agents |
| `/api/v1/receipts/{id}/verify` | `/api/v2/receipts/{receipt_id}/verify` | GET/POST | Both methods supported. Returns `checksum_match` field |
| `/api/v1/receipts/{id}/export` | `/api/v2/receipts/{receipt_id}/export` | GET | Supports `json`, `markdown`, `sarif` formats |
| (none) | `/api/v2/receipts/search` | GET | New. Search by query, date range, verdict, risk level |
| (none) | `/api/v2/receipts/stats` | GET | New. Aggregate statistics by verdict, risk, framework |
| (none) | `/api/v2/receipts/batch-verify` | POST | New. Verify up to 100 receipts at once |
| (none) | `/api/v2/receipts/batch-export` | POST | New. Export up to 100 receipts at once |

### Gauntlet

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/gauntlet/run` | `/api/v2/gauntlet/run` | POST | Returns 202. Adds `persona` and `profile` fields |
| `/api/v1/gauntlet/{id}/status` | `/api/v2/gauntlet/{run_id}/status` | GET | Same shape |
| `/api/v1/gauntlet/{id}/findings` | `/api/v2/gauntlet/{run_id}/findings` | GET | Adds `severity` filter, paginated |

### Pipeline

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| (none) | `/api/v2/pipeline/runs` | GET | New. List pipeline runs with pagination |
| (none) | `/api/v2/pipeline/runs` | POST | New. Start an idea-to-execution pipeline |
| (none) | `/api/v2/pipeline/runs/{run_id}` | GET | New. Get pipeline run status |
| (none) | `/api/v2/pipeline/runs/{run_id}/stages` | GET | New. Individual stage results |
| (none) | `/api/v2/pipeline/runs/{run_id}/approve` | POST | New. Human-in-the-loop stage gate approval |
| (none) | `/api/v2/pipeline/runs/{run_id}` | DELETE | New. Cancel a pipeline run |
| (none) | `/api/v2/pipeline/runs/{run_id}/execute-workflow` | POST | New. Convert pipeline result into a workflow |

### Knowledge

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/knowledge/search` | `/api/v2/knowledge/search` | GET | Adds `content_type` and `source` filters |
| (none) | `/api/v2/knowledge/search` | POST | New. Semantic search with JSON body |
| `/api/v1/knowledge/stats` | `/api/v2/knowledge/stats` | GET | Adds `items_by_type`, `items_by_source` |
| (none) | `/api/v2/knowledge/gaps` | GET | New. Coverage gaps, staleness, contradictions |
| (none) | `/api/v2/knowledge/adapters` | GET | New. List Knowledge Mound adapters |
| (none) | `/api/v2/knowledge/staleness` | GET | New. Staleness analysis with configurable threshold |
| (none) | `/api/v2/knowledge/query` | POST | New. Structured query with adapter, tag, confidence filters |
| `/api/v1/knowledge/{id}` | `/api/v2/knowledge/items/{item_id}` | GET | Path changed: added `/items/` segment |
| (none) | `/api/v2/knowledge/items` | POST | New. Ingest a knowledge item |
| (none) | `/api/v2/knowledge/{item_id}` | DELETE | New. Delete a knowledge item |

### Workflows

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/workflows` | `/api/v2/workflows` | GET | Paginated with `limit`/`offset` and `status` filter |
| `/api/v1/workflows/{id}` | `/api/v2/workflows/{workflow_id}` | GET | Full detail with typed nodes and edges |
| `/api/v1/workflows` | `/api/v2/workflows` | POST | Returns 201. Accepts `template` field |
| `/api/v1/workflows/{id}/execute` | `/api/v2/workflows/{workflow_id}/execute` | POST | Same semantics. Adds `async_execution` flag |
| `/api/v1/workflows/{id}/status` | `/api/v2/workflows/{workflow_id}/status` | GET | Adds `progress` (0-1), `completed_nodes`, `failed_nodes` |
| (none) | `/api/v2/workflows/templates` | GET | New. List workflow templates with category filter |
| (none) | `/api/v2/workflows/{workflow_id}/history` | GET | New. Execution history |
| (none) | `/api/v2/workflows/{workflow_id}/approve` | POST | New. Approve a pending workflow step |

### Compliance

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/compliance/status` | `/api/v2/compliance/status` | GET | Same shape |
| `/api/v1/compliance/controls` | `/api/v2/compliance/controls` | GET | Paginated. Adds `framework` filter |
| `/api/v1/compliance/policies` | `/api/v2/compliance/policies` | GET | Paginated |
| `/api/v1/compliance/frameworks` | `/api/v2/compliance/frameworks` | GET | New. List compliance frameworks |
| `/api/v1/compliance/frameworks/{id}` | `/api/v2/compliance/frameworks/{framework_id}` | GET | New. Framework details |
| `/api/v1/compliance/violations` | `/api/v2/compliance/violations` | GET | Adds severity, status filters |
| `/api/v1/compliance/audit-log` | `/api/v2/compliance/audit-log` | GET | Same shape |
| `/api/v1/compliance/check` | `/api/v2/compliance/check` | POST | Same semantics |
| (none) | `/api/v2/compliance/artifacts/generate` | POST | New. Generate compliance artifacts |
| (none) | `/api/v2/compliance/report/{debate_id}` | GET | New. Compliance report for a specific debate |

### Auth

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/auth/login` | `/api/v2/auth/login` | POST | Same semantics. Returns JWT tokens |
| `/api/v1/auth/logout` | `/api/v2/auth/logout` | POST | Same semantics |
| `/api/v1/auth/me` | `/api/v2/auth/me` | GET | Same semantics |
| `/api/v1/auth/refresh` | `/api/v2/auth/refresh` | POST | Same semantics |

### Memory

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/memory/search` | `/api/v2/memory/search` | GET | Adds `tier` and `source` filters |
| `/api/v1/memory/store` | `/api/v2/memory/store` | POST | Same semantics |
| `/api/v1/memory/recall` | `/api/v2/memory/recall` | GET | Same semantics |

### Costs

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/costs` | `/api/v2/costs` | GET | Dashboard summary |
| `/api/v1/costs/breakdown` | `/api/v2/costs/breakdown` | GET | By provider/feature |
| `/api/v1/costs/timeline` | `/api/v2/costs/timeline` | GET | Time series data |
| `/api/v1/costs/alerts` | `/api/v2/costs/alerts` | GET | Active budget alerts |
| `/api/v1/costs/budget` | `/api/v2/costs/budget` | POST | Set budget limits |
| `/api/v1/costs/usage` | `/api/v2/costs/usage` | GET | Token usage stats |
| (none) | `/api/v2/costs/efficiency` | GET | New. Cost efficiency metrics |
| (none) | `/api/v2/costs/forecast` | GET | New. Spend forecast |
| (none) | `/api/v2/costs/recommendations` | GET | New. Optimization recommendations |
| (none) | `/api/v2/costs/estimate` | POST | New. Estimate cost for a debate config |
| (none) | `/api/v2/costs/budgets` | GET | New. List all workspace budgets |
| (none) | `/api/v2/costs/analytics/trend` | GET | New. Spend trend analytics |
| (none) | `/api/v2/costs/analytics/by-agent` | GET | New. Spend by agent |
| (none) | `/api/v2/costs/analytics/by-model` | GET | New. Spend by model |
| (none) | `/api/v2/costs/export` | POST | New. Export cost data (CSV/JSON) |

### Tasks (Control Plane)

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/tasks/{id}` | `/api/v2/tasks/{task_id}` | GET | Task details |
| `/api/v1/tasks` | `/api/v2/tasks` | POST | Submit a task (returns 201) |
| `/api/v1/tasks/claim` | `/api/v2/tasks/claim` | POST | Claim a task from the queue |
| `/api/v1/tasks/{id}/complete` | `/api/v2/tasks/{task_id}/complete` | POST | Mark task complete |
| `/api/v1/tasks/{id}/fail` | `/api/v2/tasks/{task_id}/fail` | POST | Mark task failed |
| `/api/v1/tasks/{id}/cancel` | `/api/v2/tasks/{task_id}/cancel` | POST | Cancel a task |
| `/api/v1/queue` | `/api/v2/queue` | GET | Queue status |
| `/api/v1/queue/metrics` | `/api/v2/queue/metrics` | GET | Queue metrics |
| `/api/v1/tasks/history` | `/api/v2/tasks/history` | GET | Task history |
| `/api/v1/deliberations/{id}` | `/api/v2/deliberations/{request_id}` | GET | Get deliberation |
| `/api/v1/deliberations/{id}/status` | `/api/v2/deliberations/{request_id}/status` | GET | Deliberation status |
| `/api/v1/deliberations` | `/api/v2/deliberations` | POST | Start deliberation (returns 202) |

### Notifications

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/notifications/status` | `/api/v2/notifications/status` | GET | Notification system status |
| `/api/v1/notifications/email/recipients` | `/api/v2/notifications/email/recipients` | GET | List email recipients |
| `/api/v1/notifications/email/config` | `/api/v2/notifications/email/config` | POST | Configure email |
| `/api/v1/notifications/telegram/config` | `/api/v2/notifications/telegram/config` | POST | Configure Telegram |
| `/api/v1/notifications/email/recipient` | `/api/v2/notifications/email/recipient` | POST | Add email recipient |
| `/api/v1/notifications/email/recipient` | `/api/v2/notifications/email/recipient` | DELETE | Remove email recipient |
| `/api/v1/notifications/test` | `/api/v2/notifications/test` | POST | Send test notification |
| `/api/v1/notifications/send` | `/api/v2/notifications/send` | POST | Send notification |

### Inbox

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| `/api/v1/inbox/command` | `/api/v2/inbox/command` | GET | Prioritized inbox items |
| `/api/v1/inbox/actions` | `/api/v2/inbox/actions` | POST | Quick actions |
| `/api/v1/inbox/bulk-actions` | `/api/v2/inbox/bulk-actions` | POST | Bulk operations |
| `/api/v1/inbox/sender-profile` | `/api/v2/inbox/sender-profile` | GET | Sender profile |
| `/api/v1/inbox/daily-digest` | `/api/v2/inbox/daily-digest` | GET | Daily digest |
| `/api/v1/inbox/reprioritize` | `/api/v2/inbox/reprioritize` | POST | AI re-prioritization |

### API Explorer

| v1 Path | v2 Path | Method | Changes |
|---------|---------|--------|---------|
| (none) | `/api/v2/explorer/openapi.json` | GET | New. Merged OpenAPI spec (v1 + v2) |
| (none) | `/api/v2/explorer/stats` | GET | New. Endpoint statistics |
| (none) | `/api/v2/explorer/swagger` | GET | New. Swagger UI |
| (none) | `/api/v2/explorer/redoc` | GET | New. ReDoc UI |

---

## Breaking Changes

### 1. Error response format

**v1** error responses vary by handler:

```json
{"error": "Not found"}
{"message": "Invalid request", "status": 400}
{"data": null, "error": "..."}
```

**v2** uses FastAPI's consistent format:

```json
{"detail": "Debate abc123 not found"}
```

Validation errors return 422 with structured details:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "question"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

**Migration**: Check for `detail` instead of `error` or `message` in error responses.

### 2. Decisions endpoint returns 202

In v1, `POST /api/v1/debates` runs the debate synchronously and returns the result. In v2, `POST /api/v2/decisions` returns 202 immediately with a debate ID. You must poll `GET /api/v2/decisions/{id}` or subscribe to `GET /api/v2/decisions/{id}/events` (SSE) for the result.

### 3. Pagination uses limit/offset

v1 used `page`/`per_page` in some handlers. v2 consistently uses `limit` (default 50, max 100) and `offset` (default 0).

```
# v1
GET /api/v1/debates?page=2&per_page=25

# v2
GET /api/v2/debates?limit=25&offset=25
```

### 4. Response envelope changes

v1 wrapped some responses in `{"data": {...}}`. v2 returns the typed response directly (no envelope). The exception is the costs module, which preserves the `{"data": {...}}` envelope for frontend compatibility.

### 5. Authentication is enforced via dependency injection

v1 auth was optional on many endpoints. v2 write endpoints require authentication and specific RBAC permissions. Unauthenticated requests to protected endpoints return 401. Missing permissions return 403.

### 6. Path parameter names

Some path parameters have changed names:

| v1 | v2 |
|----|----|
| `{id}` | `{debate_id}`, `{receipt_id}`, `{workflow_id}`, etc. |
| `format` (in path) | `export_format` |
| `{run_id}` | `{run_id}` (unchanged for gauntlet and pipeline) |

---

## Migration Checklist

### Phase 1: Prepare

- [ ] Install `uvicorn` in your deployment (`pip install uvicorn`)
- [ ] Set `ARAGORA_ALLOWED_ORIGINS` to your frontend origins (wildcard `*` is rejected when credentials are enabled)
- [ ] Review the interactive docs at `/api/v2/docs` for the exact request/response models
- [ ] Update your HTTP client to handle 422 validation errors

### Phase 2: Update client code

- [ ] Change base URL from `/api/v1/` to `/api/v2/`
- [ ] Update error handling: check for `detail` field instead of `error`/`message`
- [ ] Update pagination: replace `page`/`per_page` with `limit`/`offset`
- [ ] For debates: switch from sync POST to async `POST /api/v2/decisions` + polling or SSE
- [ ] Update path parameter names (e.g., `{id}` to `{debate_id}`)
- [ ] Remove `{"data": ...}` unwrapping where v2 returns typed responses directly

### Phase 3: Test

- [ ] Run integration tests against v2 endpoints
- [ ] Verify auth token flow (login, token refresh, permission checks)
- [ ] Test SSE event stream for decisions if using real-time updates
- [ ] Verify error handling for 401, 403, 404, 422 responses

### Phase 4: Switch

- [ ] Set `ARAGORA_USE_FASTAPI=true` in your deployment
- [ ] Monitor logs for any 503 errors (subsystem not initialized)
- [ ] Verify health at `/api/v2/health` and `/readyz`

---

## Running Both Servers

You can run v1 and v2 simultaneously for a gradual migration:

```bash
# v1 on port 8080 (default)
aragora serve --http-port 8080

# v2 on port 8081 (separate process)
uvicorn aragora.server.fastapi.factory:app --host 0.0.0.0 --port 8081
```

Or configure your reverse proxy to route:

```nginx
# nginx example
location /api/v2/ {
    proxy_pass http://localhost:8081;
}
location /api/v1/ {
    proxy_pass http://localhost:8080;
}
location /api/ {
    # Default to v1 for unversioned paths
    proxy_pass http://localhost:8080;
}
```

Both servers share the same storage backend (SQLite/PostgreSQL), so data is consistent.

---

## Rollback

To switch back to v1:

1. **Remove the environment variable**:
   ```bash
   unset ARAGORA_USE_FASTAPI
   ```

2. **Restart the server**:
   ```bash
   aragora serve
   ```

The server reverts to `ThreadingHTTPServer` on the same port. No data migration is needed since both servers use the same storage.

If running v2 as a separate process, simply stop the uvicorn process:

```bash
# If running in the foreground
Ctrl+C

# If running as a service
systemctl stop aragora-v2
```

---

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_USE_FASTAPI` | `false` | Use FastAPI/uvicorn instead of ThreadingHTTPServer |
| `ARAGORA_FASTAPI_PORT` | (same as HTTP port) | Port for FastAPI server |
| `ARAGORA_ALLOWED_ORIGINS` | `localhost:3000,localhost:8080` | Comma-separated CORS origins |
| `ARAGORA_VALIDATION_BLOCKING` | `true` | `true` = reject invalid requests, `false` = warn only |
| `ARAGORA_NOMIC_DIR` | `.` | Base directory for storage and data |
| `ARAGORA_ENV` | `development` | Environment name (affects logging format) |
