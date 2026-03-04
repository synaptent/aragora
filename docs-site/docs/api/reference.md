---
title: Aragora API Reference
description: Aragora API Reference
---

# Aragora API Reference

> **Last Updated:** 2026-02-23 (v2.8.0 alignment with repo versions)

This document describes the HTTP and WebSocket APIs for Aragora's control plane
for multi-agent AI debate across organizational knowledge and channels.

## SDK Coverage

| SDK | Version | Methods | Coverage |
|-----|---------|---------|----------|
| TypeScript (`@aragora/sdk`) | 2.8.0 | 380 async | Full API (79 namespaces) |
| Python (`aragora`) | 2.8.0 | 220 async + 420 sync | Full API |

Versions reflect the current repo tags (see `pyproject.toml` and
`aragora/__version__.py`). If versions drift, run
`python scripts/check_version_alignment.py`.

Both SDKs provide complete coverage of all API endpoints including:
- Debates, Agents, Memory, Knowledge
- Gauntlet, Verification, Workflows
- Control Plane, RBAC, Tenancy
- Authentication, Billing, Audit
- Backups, Expenses, RLM, Unified Inbox, Feedback

## Related Documentation

| Document | Purpose | When to Use |
|----------|---------|-------------|
| **API_REFERENCE.md** (this) | Complete endpoint catalog | Primary reference for all endpoints |
| [API_ENDPOINTS.md](./endpoints) | Auto-generated endpoint list | Cross-check handler coverage |
| [API_EXAMPLES.md](./examples) | Runnable code examples | Learning API patterns |
| [API_RATE_LIMITS.md](./rate-limits) | Rate limiting details | Understanding throttling |
| [API_VERSIONING.md](./versioning) | Version strategy | API migration planning |
| [API_STABILITY.md](./stability) | Stability guarantees | Production decisions |
| [WEBSOCKET_EVENTS.md](../guides/websocket-events) | WebSocket event types | Real-time integration |
| [MCP README](../analysis/adr) | MCP server tools and setup | AI tool integration via MCP |

## Endpoint Usage Status

Endpoint counts vary by deployment and enabled handlers. To audit the current
surface area, run:

```bash
python scripts/generate_api_docs.py --format json
```

## OpenAPI Specification

The generated OpenAPI spec lives in `docs/api/openapi.json` and
`docs/api/openapi.yaml` (JSON-formatted for compatibility). Regenerate them with:

```bash
python scripts/export_openapi.py --output-dir docs/api
```

The canonical spec is produced by `aragora/server/openapi` and the endpoint
definitions under `aragora/server/openapi/endpoints/`. If you add or change endpoints, update the
OpenAPI endpoint definitions and re-export the docs.

Each OpenAPI operation includes `x-aragora-stability` to indicate whether it is
stable, beta, experimental, internal, or deprecated. See `docs/API_STABILITY.md`
for the promotion workflow.

## Auth Signup & SSO API

Self-service signup and SSO/OIDC endpoints live under `/api/v1/auth`.
Signup flows are in-memory by default; use a database-backed store for production.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/signup` | Register new user |
| POST | `/api/v1/auth/verify-email` | Verify email address |
| POST | `/api/v1/auth/resend-verification` | Resend verification email |
| POST | `/api/v1/auth/setup-organization` | Create org after signup |
| POST | `/api/v1/auth/invite` | Invite team member |
| POST | `/api/v1/auth/accept-invite` | Accept invitation |
| GET | `/api/v1/auth/check-invite` | Check invitation validity |
| GET | `/api/v1/auth/sso/login` | Get SSO authorization URL |
| GET | `/api/v1/auth/sso/callback` | Handle OAuth/OIDC callback |
| POST | `/api/v1/auth/sso/refresh` | Refresh access token |
| POST | `/api/v1/auth/sso/logout` | Logout from SSO |
| GET | `/api/v1/auth/sso/providers` | List available providers |
| GET | `/api/v1/auth/sso/config` | Get provider configuration |

## SCIM 2.0 Provisioning API

SCIM 2.0 (RFC 7643/7644) endpoints for automated user and group provisioning
from identity providers (Okta, Azure AD, OneLogin, etc.). Endpoints are
mounted at `/scim/v2/` and use Bearer token authentication.

**Authentication**: Set `SCIM_BEARER_TOKEN` environment variable. All requests
must include `Authorization: Bearer <token>` header.

### User Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/scim/v2/Users` | List users with filtering and pagination |
| POST | `/scim/v2/Users` | Create a new user |
| GET | `/scim/v2/Users/\{id\}` | Get user by ID |
| PUT | `/scim/v2/Users/\{id\}` | Replace user (full update) |
| PATCH | `/scim/v2/Users/\{id\}` | Partial update user |
| DELETE | `/scim/v2/Users/\{id\}` | Delete user (soft delete by default) |

### Group Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/scim/v2/Groups` | List groups with filtering and pagination |
| POST | `/scim/v2/Groups` | Create a new group |
| GET | `/scim/v2/Groups/\{id\}` | Get group by ID |
| PUT | `/scim/v2/Groups/\{id\}` | Replace group (full update) |
| PATCH | `/scim/v2/Groups/\{id\}` | Partial update group (add/remove members) |
| DELETE | `/scim/v2/Groups/\{id\}` | Delete group |

### Query Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `startIndex` | int | 1-based pagination offset | 1 |
| `count` | int | Page size (max 1000) | 100 |
| `filter` | string | SCIM filter expression | — |

### Supported Filter Operators

`eq`, `ne`, `co`, `sw`, `ew`, `pr`, `gt`, `ge`, `lt`, `le`, `and`, `or`

Example: `filter=userName eq "john@example.com"`

### Content Type

All responses use `application/scim+json` media type per RFC 7644.

## Dashboard API

Dashboard endpoints return overview stats, activity, and quick actions.
Responses are cached in-memory for 30 seconds by default.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/dashboard` | Get dashboard overview |
| GET | `/api/v1/dashboard/stats` | Get detailed stats |
| GET | `/api/v1/dashboard/activity` | Get recent activity |
| GET | `/api/v1/dashboard/inbox-summary` | Get inbox summary |
| GET | `/api/v1/dashboard/quick-actions` | Get available quick actions |
| POST | `/api/v1/dashboard/quick-actions/\{action\}` | Execute quick action |

## Deliberations API

Active AI debate sessions and stats.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/deliberations/active` | List active deliberations |
| GET | `/api/v1/deliberations/stats` | Deliberation statistics |
| GET | `/api/v1/deliberations/\{id\}` | Get deliberation details |
| GET | `/api/v1/deliberations/stream` | WebSocket stream of deliberations |

## Code Review API

Code review endpoints run multi-agent reviews for snippets, diffs, and PRs.
Results are stored in-memory by default.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/code-review/review` | Review code snippet |
| POST | `/api/v1/code-review/diff` | Review diff/patch |
| POST | `/api/v1/code-review/pr` | Review GitHub PR |
| GET | `/api/v1/code-review/results/\{id\}` | Get review result |
| GET | `/api/v1/code-review/history` | Review history |
| POST | `/api/v1/code-review/security-scan` | Quick security scan |

## Devices API

Device registration and push notification endpoints.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/devices/register` | Register a device for push notifications |
| GET | `/api/v1/devices/health` | Device connector health |
| GET | `/api/v1/devices/user/\{user_id\}` | List user devices |
| POST | `/api/v1/devices/user/\{user_id\}/notify` | Notify all user devices |
| GET | `/api/v1/devices/\{device_id\}` | Get device info |
| DELETE | `/api/v1/devices/\{device_id\}` | Unregister device |
| POST | `/api/v1/devices/\{device_id\}/notify` | Notify a device |
| POST | `/api/v1/devices/alexa/webhook` | Alexa skill webhook |
| POST | `/api/v1/devices/google/webhook` | Google Home webhook |

## A2A (Agent-to-Agent) API

Agent discovery and task execution endpoints.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/a2a/.well-known/agent.json` | Agent discovery card |
| GET | `/api/v1/a2a/openapi.json` | A2A OpenAPI spec |
| GET | `/api/v1/a2a/agents` | List agents |
| GET | `/api/v1/a2a/agents/\{name\}` | Get agent details |
| POST | `/api/v1/a2a/tasks` | Submit task |
| GET | `/api/v1/a2a/tasks/\{id\}` | Get task status |
| POST | `/api/v1/a2a/tasks/\{id\}/stream` | Stream task output |

## Metrics API

Operational and Prometheus metrics endpoints.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/metrics` | Operational metrics |
| GET | `/api/metrics/health` | Health metrics |
| GET | `/api/metrics/cache` | Cache metrics |
| GET | `/api/metrics/system` | System metrics |
| GET | `/api/metrics/verification` | Verification metrics |
| GET | `/api/metrics/background` | Background task metrics |
| GET | `/api/metrics/debate` | Debate metrics |
| GET | `/metrics` | Prometheus export |

## Plugins API

Plugin management and marketplace endpoints.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/plugins` | List plugins |
| GET | `/api/v1/plugins/installed` | List installed plugins |
| GET | `/api/v1/plugins/marketplace` | Marketplace listings |
| GET | `/api/v1/plugins/submissions` | List submissions |
| POST | `/api/v1/plugins/submit` | Submit plugin |
| GET | `/api/v1/plugins/\{name\}` | Plugin details |
| POST | `/api/v1/plugins/\{name\}/install` | Install plugin |
| DELETE | `/api/v1/plugins/\{name\}/install` | Uninstall plugin |
| POST | `/api/v1/plugins/\{name\}/run` | Run plugin action |

## Cross-Pollination API

Knowledge sharing between debates and Knowledge Mound.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/cross-pollination/stats` | Cross-pollination stats |
| GET | `/api/v1/cross-pollination/metrics` | Cross-pollination metrics |
| GET | `/api/v1/cross-pollination/subscribers` | List subscribers |
| POST | `/api/v1/cross-pollination/subscribe` | Subscribe a debate |
| DELETE | `/api/v1/cross-pollination/subscribers/\{debate_id\}` | Unsubscribe a debate |
| GET | `/api/v1/cross-pollination/bridge` | Bridge configuration |
| PUT | `/api/v1/cross-pollination/bridge` | Update bridge config |
| GET | `/api/v1/cross-pollination/km` | Knowledge Mound status |
| GET | `/api/v1/cross-pollination/km/staleness-check` | Knowledge staleness check |
| GET | `/api/v1/laboratory/cross-pollinations/suggest` | Suggest cross-pollination |

## Platform APIs (Advertising, Analytics, CRM, Ecommerce, Support)

These endpoints unify operational data across platforms. They are backed by
`SecureHandler` and respect RBAC permissions.

### Advertising

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/advertising/platforms` | List connected platforms |
| POST | `/api/v1/advertising/connect` | Connect a platform |
| DELETE | `/api/v1/advertising/\{platform\}` | Disconnect platform |
| GET | `/api/v1/advertising/campaigns` | Cross-platform campaigns |
| POST | `/api/v1/advertising/\{platform\}/campaigns` | Create campaign |
| GET | `/api/v1/advertising/performance` | Cross-platform performance |
| POST | `/api/v1/advertising/analyze` | Performance analysis |

### Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/analytics/platforms` | List connected platforms |
| POST | `/api/v1/analytics/connect` | Connect a platform |
| GET | `/api/v1/analytics/dashboards` | Cross-platform dashboards |
| POST | `/api/v1/analytics/query` | Execute unified query |
| GET | `/api/v1/analytics/reports` | Available reports |
| POST | `/api/v1/analytics/reports/generate` | Generate report |
| GET | `/api/v1/analytics/metrics` | Metrics overview |
| GET | `/api/v1/analytics/realtime` | Real-time metrics |

#### Endpoint Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analytics/endpoints` | Aggregated endpoint metrics |
| GET | `/api/analytics/endpoints/slowest` | Top N slowest endpoints |
| GET | `/api/analytics/endpoints/errors` | Top N endpoints by error rate |
| GET | `/api/analytics/endpoints/\{endpoint\}/performance` | Endpoint performance detail |
| GET | `/api/analytics/endpoints/health` | Overall API health summary |

### CRM

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/crm/platforms` | List connected platforms |
| POST | `/api/v1/crm/connect` | Connect a platform |
| GET | `/api/v1/crm/contacts` | Cross-platform contacts |
| POST | `/api/v1/crm/\{platform\}/contacts` | Create contact |
| GET | `/api/v1/crm/companies` | Companies |
| GET | `/api/v1/crm/deals` | Deals/opportunities |
| GET | `/api/v1/crm/pipeline` | Sales pipeline |
| POST | `/api/v1/crm/sync-lead` | Sync lead |
| POST | `/api/v1/crm/enrich` | Enrich contact data |

### Ecommerce

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/ecommerce/platforms` | List connected platforms |
| POST | `/api/v1/ecommerce/connect` | Connect a platform |
| GET | `/api/v1/ecommerce/orders` | Cross-platform orders |
| GET | `/api/v1/ecommerce/products` | Products |
| GET | `/api/v1/ecommerce/inventory` | Inventory levels |
| POST | `/api/v1/ecommerce/sync-inventory` | Sync inventory |
| GET | `/api/v1/ecommerce/fulfillment` | Fulfillment status |
| POST | `/api/v1/ecommerce/ship` | Create shipment |

### Support

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/support/platforms` | List connected platforms |
| POST | `/api/v1/support/connect` | Connect a platform |
| GET | `/api/v1/support/tickets` | Cross-platform tickets |
| POST | `/api/v1/support/triage` | Ticket triage |
| POST | `/api/v1/support/auto-respond` | Response suggestions |

## Codebase Analysis API

Codebase security and metrics endpoints live under `/api/v1/codebase` and
`/api/v1/cve`. For full examples and response shapes, see
`docs/CODEBASE_ANALYSIS.md`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/codebase/\{repo\}/scan` | Run dependency vulnerability scan |
| GET | `/api/v1/codebase/\{repo\}/scan/latest` | Latest scan result |
| GET | `/api/v1/codebase/\{repo\}/scan/\{scan_id\}` | Scan by ID |
| GET | `/api/v1/codebase/\{repo\}/scans` | List scan history |
| GET | `/api/v1/codebase/\{repo\}/vulnerabilities` | Vulnerabilities list |
| GET | `/api/v1/codebase/package/\{ecosystem\}/\{package\}/vulnerabilities` | Package advisories |
| GET | `/api/v1/cve/\{cve_id\}` | CVE details |
| POST | `/api/v1/codebase/\{repo\}/scan/sast` | Trigger SAST scan |
| GET | `/api/v1/codebase/\{repo\}/scan/sast/\{scan_id\}` | SAST scan status |
| GET | `/api/v1/codebase/\{repo\}/sast/findings` | SAST findings |
| GET | `/api/v1/codebase/\{repo\}/sast/owasp-summary` | OWASP summary |
| POST | `/api/v1/codebase/\{repo\}/metrics/analyze` | Run metrics analysis |
| GET | `/api/v1/codebase/\{repo\}/metrics` | Latest metrics report |
| GET | `/api/v1/codebase/\{repo\}/metrics/\{analysis_id\}` | Metrics report by ID |
| GET | `/api/v1/codebase/\{repo\}/metrics/history` | Metrics history |
| GET | `/api/v1/codebase/\{repo\}/hotspots` | Complexity hotspots |
| GET | `/api/v1/codebase/\{repo\}/duplicates` | Code duplication summary |
| GET | `/api/v1/codebase/\{repo\}/metrics/file/\{file_path\}` | File-level metrics |

Additional codebase analysis endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/codebase/analyze-dependencies` | Analyze dependencies |
| POST | `/api/v1/codebase/scan-vulnerabilities` | Scan repo for CVEs |
| POST | `/api/v1/codebase/check-licenses` | License compatibility |
| POST | `/api/v1/codebase/sbom` | Generate SBOM |
| POST | `/api/v1/codebase/clear-cache` | Clear dependency analysis cache |
| POST | `/api/v1/codebase/\{repo\}/scan/secrets` | Trigger secrets scan |
| GET | `/api/v1/codebase/\{repo\}/scan/secrets/latest` | Latest secrets scan |
| GET | `/api/v1/codebase/\{repo\}/scan/secrets/\{scan_id\}` | Secrets scan by ID |
| GET | `/api/v1/codebase/\{repo\}/secrets` | Secrets list |
| GET | `/api/v1/codebase/\{repo\}/scans/secrets` | Secrets scan history |

### Code Intelligence API

Code intelligence endpoints support AST analysis, call graphs, and audit runs.
Canonical endpoints live under `/api/v1/codebase` with `/api/codebase` aliases
for UI-driven flows.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/codebase/\{repo\}/analyze` | Analyze codebase structure |
| GET | `/api/v1/codebase/\{repo\}/symbols` | List symbols |
| GET | `/api/v1/codebase/\{repo\}/callgraph` | Fetch call graph |
| GET | `/api/v1/codebase/\{repo\}/deadcode` | Find dead code |
| POST | `/api/v1/codebase/\{repo\}/impact` | Impact analysis |
| POST | `/api/v1/codebase/\{repo\}/understand` | Answer questions about code |
| POST | `/api/v1/codebase/\{repo\}/audit` | Run comprehensive audit |
| GET | `/api/v1/codebase/\{repo\}/audit/\{audit_id\}` | Audit status/result |

### Quick Scan API

Quick scan endpoints power the one-click security scan UI.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/codebase/quick-scan` | Run quick security scan |
| GET | `/api/codebase/quick-scan/\{scan_id\}` | Get quick scan result |
| GET | `/api/codebase/quick-scans` | List quick scans |

## GitHub PR Review API

GitHub pull request review endpoints live under `/api/v1/github/pr`. For full
details, see `docs/GITHUB_PR_REVIEW.md`.
Register `PRReviewHandler` in the server handler registry to expose these
routes in the unified server.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/github/pr/review` | Trigger a PR review |
| GET | `/api/v1/github/pr/\{pr_number\}` | Get PR details |
| GET | `/api/v1/github/pr/review/\{review_id\}` | Get review status/result |
| GET | `/api/v1/github/pr/\{pr_number\}/reviews` | List reviews for a PR |
| POST | `/api/v1/github/pr/\{pr_number\}/review` | Submit review to GitHub |

## GitHub Audit Bridge API

Audit-to-GitHub endpoints live under `/api/v1/github/audit`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/github/audit/issues` | Create issues from findings |
| POST | `/api/v1/github/audit/issues/bulk` | Bulk create issues |
| POST | `/api/v1/github/audit/pr` | Create PR with fixes |
| GET | `/api/v1/github/audit/sync/\{session_id\}` | Get sync status |
| POST | `/api/v1/github/audit/sync/\{session_id\}` | Sync session to GitHub |

## Audit Sessions API

Audit session endpoints manage multi-agent document audits. The UI uses
`/api/audit/sessions`; versioned endpoints live under `/api/v1/audit/sessions`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/audit/sessions` | Create audit session |
| GET | `/api/v1/audit/sessions` | List audit sessions |
| GET | `/api/v1/audit/sessions/\{session_id\}` | Get session details |
| DELETE | `/api/v1/audit/sessions/\{session_id\}` | Delete session |
| POST | `/api/v1/audit/sessions/\{session_id\}/start` | Start audit |
| POST | `/api/v1/audit/sessions/\{session_id\}/pause` | Pause audit |
| POST | `/api/v1/audit/sessions/\{session_id\}/resume` | Resume audit |
| POST | `/api/v1/audit/sessions/\{session_id\}/cancel` | Cancel audit |
| GET | `/api/v1/audit/sessions/\{session_id\}/findings` | List findings |
| GET | `/api/v1/audit/sessions/\{session_id\}/events` | Stream SSE events |
| POST | `/api/v1/audit/sessions/\{session_id\}/intervene` | Human intervention |
| GET | `/api/v1/audit/sessions/\{session_id\}/report` | Export report |

## Security Debate API

Trigger multi-agent debates on security vulnerability findings. Debates use the Arena with
security-focused agents to analyze vulnerabilities and recommend remediation strategies.

**Authentication:** Required. Permissions: `audit:write` (POST), `audit:read` (GET).
**Rate limit:** 10 requests per minute per user.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/audit/security/debate` | Trigger security debate on findings |
| GET | `/api/v1/audit/security/debate/\{id\}` | Get security debate status |

### POST /api/v1/audit/security/debate

Trigger a multi-agent security debate on vulnerability findings.

**Request body:**

```json
{
    "findings": [
        {
            "id": "optional-uuid",
            "finding_type": "vulnerability",
            "severity": "critical",
            "title": "SQL Injection in user handler",
            "description": "Unsanitized user input passed to SQL query",
            "file_path": "aragora/server/handlers/users.py",
            "line_number": 42,
            "cve_id": "CVE-2024-1234",
            "package_name": "optional-package",
            "package_version": "1.2.3",
            "recommendation": "Use parameterized queries",
            "metadata": {}
        }
    ],
    "repository": "repo-name",
    "confidence_threshold": 0.7,
    "timeout_seconds": 300
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| findings | array | Yes | List of security findings to debate |
| repository | string | No | Repository name (default: "unknown") |
| confidence_threshold | number | No | Debate confidence threshold, 0.1-1.0 (default: 0.7) |
| timeout_seconds | integer | No | Debate timeout, 30-600 (default: 300) |

**Response (200):**

```json
{
    "debate_id": "uuid",
    "status": "completed",
    "consensus_reached": true,
    "confidence": 0.85,
    "final_answer": "Remediation recommendations...",
    "rounds_used": 3,
    "duration_ms": 12500,
    "findings_analyzed": 2,
    "votes": {
        "SecurityAnalyst": "remediate",
        "CodeReviewer": "remediate"
    }
}
```

### GET /api/v1/audit/security/debate/\{id\}

Get the status of a previously triggered security debate. Currently debates are synchronous,
so this endpoint returns `not_found` for any ID (placeholder for future async support).

**Response (200):**

```json
{
    "debate_id": "the-id",
    "status": "not_found",
    "message": "Debate results are not persisted. Use POST to trigger a new debate."
}
```

## Shared Inbox API

Shared inbox endpoints live under `/api/v1/inbox`. For workflow details, see
`docs/SHARED_INBOX.md`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/inbox/shared` | Create shared inbox |
| GET | `/api/v1/inbox/shared` | List shared inboxes |
| GET | `/api/v1/inbox/shared/\{id\}` | Get inbox details |
| GET | `/api/v1/inbox/shared/\{id\}/messages` | List inbox messages |
| POST | `/api/v1/inbox/shared/\{id\}/messages/\{msg_id\}/assign` | Assign message |
| POST | `/api/v1/inbox/shared/\{id\}/messages/\{msg_id\}/status` | Update status |
| POST | `/api/v1/inbox/shared/\{id\}/messages/\{msg_id\}/tag` | Add tag |
| POST | `/api/v1/inbox/routing/rules` | Create routing rule |
| GET | `/api/v1/inbox/routing/rules` | List routing rules |
| PATCH | `/api/v1/inbox/routing/rules/\{id\}` | Update routing rule |
| DELETE | `/api/v1/inbox/routing/rules/\{id\}` | Delete routing rule |
| POST | `/api/v1/inbox/routing/rules/\{id\}/test` | Test routing rule |

## Inbox Command Center API

Command center endpoints power the inbox UI quick actions and daily digest.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/inbox/command` | Fetch prioritized inbox |
| POST | `/api/inbox/actions` | Execute quick action |
| POST | `/api/inbox/bulk-actions` | Execute bulk action |
| POST | `/api/inbox/reprioritize` | Trigger AI re-prioritization |
| GET | `/api/inbox/sender-profile` | Sender profile |
| GET | `/api/inbox/daily-digest` | Daily digest |
| GET | `/api/v1/inbox/daily-digest` | Daily digest (v1 alias) |
| GET | `/api/email/daily-digest` | Daily digest (email alias) |

## Message Bindings API

Bindings map messages to routing targets (provider/account/pattern). All routes
support `/api/v1` via version stripping.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/bindings` | List all bindings |
| GET | `/api/bindings/\{provider\}` | List bindings for provider |
| POST | `/api/bindings` | Create binding |
| PUT | `/api/bindings/\{id\}` | Update binding |
| DELETE | `/api/bindings/\{id\}` | Delete binding |
| POST | `/api/bindings/resolve` | Resolve binding for a message |
| GET | `/api/bindings/stats` | Router statistics |

## Email Services API

Follow-up tracking, snooze, and category APIs live under `/api/v1/email`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/email/followups/mark` | Mark follow-up |
| GET | `/api/v1/email/followups/pending` | List pending follow-ups |
| POST | `/api/v1/email/followups/\{id\}/resolve` | Resolve follow-up |
| POST | `/api/v1/email/followups/check-replies` | Check for replies |
| POST | `/api/v1/email/followups/auto-detect` | Auto-detect follow-ups |
| GET | `/api/v1/email/\{id\}/snooze-suggestions` | Snooze suggestions |
| POST | `/api/v1/email/\{id\}/snooze` | Apply snooze |
| DELETE | `/api/v1/email/\{id\}/snooze` | Cancel snooze |
| GET | `/api/v1/email/snoozed` | List snoozed emails |
| GET | `/api/v1/email/categories` | List categories |
| POST | `/api/v1/email/categories/learn` | Category feedback |

## Gmail Operations API

Gmail labels, threads, drafts, and message operations.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/gmail/labels` | Create label |
| GET | `/api/v1/gmail/labels` | List labels |
| PATCH | `/api/v1/gmail/labels/\{id\}` | Update label |
| DELETE | `/api/v1/gmail/labels/\{id\}` | Delete label |
| POST | `/api/v1/gmail/messages/\{id\}/labels` | Modify message labels |
| POST | `/api/v1/gmail/messages/\{id\}/read` | Mark read/unread |
| POST | `/api/v1/gmail/messages/\{id\}/star` | Star/unstar |
| POST | `/api/v1/gmail/messages/\{id\}/archive` | Archive message |
| POST | `/api/v1/gmail/messages/\{id\}/trash` | Trash/untrash |
| POST | `/api/v1/gmail/filters` | Create filter |
| GET | `/api/v1/gmail/filters` | List filters |
| DELETE | `/api/v1/gmail/filters/\{id\}` | Delete filter |
| GET | `/api/v1/gmail/threads` | List threads |
| GET | `/api/v1/gmail/threads/\{id\}` | Get thread |
| POST | `/api/v1/gmail/threads/\{id\}/archive` | Archive thread |
| POST | `/api/v1/gmail/threads/\{id\}/trash` | Trash thread |
| POST | `/api/v1/gmail/threads/\{id\}/labels` | Modify thread labels |
| POST | `/api/v1/gmail/drafts` | Create draft |
| GET | `/api/v1/gmail/drafts` | List drafts |
| GET | `/api/v1/gmail/drafts/\{id\}` | Get draft |
| PUT | `/api/v1/gmail/drafts/\{id\}` | Update draft |
| DELETE | `/api/v1/gmail/drafts/\{id\}` | Delete draft |
| POST | `/api/v1/gmail/drafts/\{id\}/send` | Send draft |
| GET | `/api/v1/gmail/messages/\{id\}/attachments/\{attachment_id\}` | Get attachment |

Notes:
- Gmail operations require a connected Gmail account via `/api/v1/email/gmail/oauth/*`.
- Pass `user_id` in query params for GET requests and in the JSON body for write requests.

## Outlook/M365 API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/outlook/oauth/url` | OAuth authorization URL |
| POST | `/api/v1/outlook/oauth/callback` | OAuth callback |
| GET | `/api/v1/outlook/folders` | List mail folders |
| GET | `/api/v1/outlook/messages` | List messages |
| GET | `/api/v1/outlook/messages/\{id\}` | Get message details |
| GET | `/api/v1/outlook/conversations/\{id\}` | Get conversation |
| POST | `/api/v1/outlook/send` | Send message |
| POST | `/api/v1/outlook/reply` | Reply to message |
| GET | `/api/v1/outlook/search` | Search messages |
| POST | `/api/v1/outlook/messages/\{id\}/read` | Mark read/unread |
| POST | `/api/v1/outlook/messages/\{id\}/move` | Move message |
| DELETE | `/api/v1/outlook/messages/\{id\}` | Delete message |

## Accounting (QuickBooks) API

Accounting endpoints live under `/api/accounting` for QuickBooks Online
integration and financial dashboards.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/accounting/status` | Connection status + dashboard data |
| GET | `/api/accounting/connect` | Start OAuth connection |
| GET | `/api/accounting/callback` | OAuth callback |
| POST | `/api/accounting/disconnect` | Disconnect QuickBooks |
| GET | `/api/accounting/customers` | List customers |
| GET | `/api/accounting/transactions` | List transactions |
| POST | `/api/accounting/report` | Generate report |

## Payroll (Gusto) API

Payroll endpoints live under `/api/accounting/gusto` for Gusto OAuth and payroll
data sync.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/accounting/gusto/status` | Connection status |
| GET | `/api/accounting/gusto/connect` | Start OAuth connection |
| GET | `/api/accounting/gusto/callback` | OAuth callback |
| POST | `/api/accounting/gusto/disconnect` | Disconnect Gusto |
| GET | `/api/accounting/gusto/employees` | List employees |
| GET | `/api/accounting/gusto/payrolls` | List payroll runs |
| GET | `/api/accounting/gusto/payrolls/\{payroll_id\}` | Payroll run details |
| POST | `/api/accounting/gusto/payrolls/\{payroll_id\}/journal-entry` | Generate journal entry |

## Banking (Plaid) API

Banking endpoints live under `/api/accounting/plaid` for Plaid Link integration
and bank account syncing.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/accounting/plaid/link/token` | Create Link token |
| POST | `/api/accounting/plaid/exchange` | Exchange public token |
| GET | `/api/accounting/plaid/status` | Connection status |
| POST | `/api/accounting/plaid/disconnect` | Disconnect Plaid |
| GET | `/api/accounting/plaid/accounts` | List bank accounts |
| GET | `/api/accounting/plaid/transactions` | List transactions |
| POST | `/api/accounting/plaid/transactions/sync` | Sync transactions |
| GET | `/api/accounting/plaid/balance` | Get account balances |
| GET | `/api/accounting/plaid/institutions/search` | Search institutions |

## Xero Accounting API

Xero endpoints live under `/api/accounting/xero` for Xero OAuth and accounting
data sync.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/accounting/xero/status` | Connection status |
| GET | `/api/accounting/xero/connect` | Start OAuth connection |
| GET | `/api/accounting/xero/callback` | OAuth callback |
| POST | `/api/accounting/xero/disconnect` | Disconnect Xero |
| GET | `/api/accounting/xero/contacts` | List contacts |
| GET | `/api/accounting/xero/contacts/\{contact_id\}` | Contact details |
| POST | `/api/accounting/xero/contacts` | Create contact |
| GET | `/api/accounting/xero/invoices` | List invoices |
| GET | `/api/accounting/xero/invoices/\{invoice_id\}` | Invoice details |
| POST | `/api/accounting/xero/invoices` | Create invoice |
| GET | `/api/accounting/xero/accounts` | List chart of accounts |
| GET | `/api/accounting/xero/bank-transactions` | List bank transactions |
| POST | `/api/accounting/xero/manual-journals` | Create manual journal |
| GET | `/api/accounting/xero/payments` | List payments |

## Cost Visibility API

Cost endpoints live under `/api/costs`. See `docs/COST_VISIBILITY.md` for
dashboard context.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/costs` | Cost dashboard summary |
| GET | `/api/costs/breakdown` | Cost breakdown |
| GET | `/api/costs/timeline` | Usage timeline |
| GET | `/api/costs/alerts` | Budget alerts |
| POST | `/api/costs/budget` | Set budget limits |
| POST | `/api/costs/alerts/\{alert_id\}/dismiss` | Dismiss alert |

## Chat Knowledge Bridge API

Endpoints for chat + knowledge integration:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chat/knowledge/search` | Search knowledge from chat |
| POST | `/api/v1/chat/knowledge/inject` | Inject knowledge into conversation |
| POST | `/api/v1/chat/knowledge/store` | Store chat as knowledge |
| GET | `/api/v1/chat/knowledge/channel/\{id\}/summary` | Channel knowledge summary |

## Knowledge Mound Governance API

Governance endpoints under `/api/v1/knowledge/mound/governance`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/knowledge/mound/governance/roles` | Create a role |
| POST | `/api/v1/knowledge/mound/governance/roles/assign` | Assign role to user |
| POST | `/api/v1/knowledge/mound/governance/roles/revoke` | Revoke role from user |
| GET | `/api/v1/knowledge/mound/governance/permissions/\{user_id\}` | Get user permissions |
| POST | `/api/v1/knowledge/mound/governance/permissions/check` | Check permissions |
| GET | `/api/v1/knowledge/mound/governance/audit` | Query audit trail |
| GET | `/api/v1/knowledge/mound/governance/audit/user/\{user_id\}` | User activity audit |
| GET | `/api/v1/knowledge/mound/governance/stats` | Governance stats |

## Knowledge Mound Maintenance API

Maintenance endpoints under `/api/v1/knowledge/mound`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/knowledge/mound/dedup/clusters` | Find duplicate clusters |
| GET | `/api/v1/knowledge/mound/dedup/report` | Generate dedup report |
| POST | `/api/v1/knowledge/mound/dedup/merge` | Merge a duplicate cluster |
| POST | `/api/v1/knowledge/mound/dedup/auto-merge` | Auto-merge exact duplicates |
| POST | `/api/v1/knowledge/mound/federation/regions` | Register federated region (admin) |
| GET | `/api/v1/knowledge/mound/federation/regions` | List federated regions |
| DELETE | `/api/v1/knowledge/mound/federation/regions/:id` | Unregister federated region |
| POST | `/api/v1/knowledge/mound/federation/sync/push` | Push sync to region |
| POST | `/api/v1/knowledge/mound/federation/sync/pull` | Pull sync from region |
| POST | `/api/v1/knowledge/mound/federation/sync/all` | Sync with all regions |
| GET | `/api/v1/knowledge/mound/federation/status` | Federation health status |

## Threat Intelligence API

Threat intelligence endpoints live under `/api/v1/threat`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/threat/url` | Scan a URL |
| POST | `/api/v1/threat/urls` | Batch scan URLs |
| GET | `/api/v1/threat/ip/\{ip_address\}` | IP reputation |
| POST | `/api/v1/threat/ips` | Batch IP reputation |
| GET | `/api/v1/threat/hash/\{hash_value\}` | File hash lookup |
| POST | `/api/v1/threat/hashes` | Batch hash lookup |
| POST | `/api/v1/threat/email` | Scan email content |
| GET | `/api/v1/threat/status` | Service status |

## Backups API

Disaster recovery and backup management endpoints under `/api/v1/backups`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/backups` | Create a new backup |
| GET | `/api/v1/backups` | List all backups |
| GET | `/api/v1/backups/\{backup_id\}` | Get backup details |
| DELETE | `/api/v1/backups/\{backup_id\}` | Delete a backup |
| POST | `/api/v1/backups/\{backup_id\}/restore` | Restore from backup |
| POST | `/api/v1/backups/\{backup_id\}/verify` | Verify backup integrity |
| GET | `/api/v1/backups/status` | Get backup service status |
| POST | `/api/v1/backups/schedule` | Configure backup schedule |
| GET | `/api/v1/backups/schedule` | Get backup schedule |

## Expenses API

Receipt management and expense categorization under `/api/v1/expenses`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/expenses/receipts` | Upload a receipt |
| GET | `/api/v1/expenses/receipts` | List receipts |
| GET | `/api/v1/expenses/receipts/\{receipt_id\}` | Get receipt details |
| POST | `/api/v1/expenses/receipts/\{receipt_id\}/categorize` | Categorize receipt |
| POST | `/api/v1/expenses/receipts/\{receipt_id\}/approve` | Approve expense |
| POST | `/api/v1/expenses/sync` | Sync with accounting system |
| GET | `/api/v1/expenses/categories` | List expense categories |
| GET | `/api/v1/expenses/summary` | Get expense summary |

## RLM (Recursive Language Models) API

Context compression and programmatic context management under `/api/v1/rlm`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/rlm/compress` | Compress context |
| POST | `/api/v1/rlm/decompress` | Decompress context |
| POST | `/api/v1/rlm/query` | Query compressed context |
| GET | `/api/v1/rlm/sessions` | List active sessions |
| GET | `/api/v1/rlm/sessions/\{session_id\}` | Get session details |
| DELETE | `/api/v1/rlm/sessions/\{session_id\}` | End session |
| POST | `/api/v1/rlm/stream` | Stream compressed output |

## Unified Inbox API

Multi-provider email management under `/api/v1/unified-inbox`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/unified-inbox` | Get unified inbox messages |
| GET | `/api/v1/unified-inbox/accounts` | List connected accounts |
| POST | `/api/v1/unified-inbox/accounts` | Connect email account |
| DELETE | `/api/v1/unified-inbox/accounts/\{account_id\}` | Disconnect account |
| GET | `/api/v1/unified-inbox/messages/\{message_id\}` | Get message details |
| POST | `/api/v1/unified-inbox/messages/\{message_id\}/archive` | Archive message |
| POST | `/api/v1/unified-inbox/messages/\{message_id\}/reply` | Reply to message |
| POST | `/api/v1/unified-inbox/sync` | Sync all accounts |
| GET | `/api/v1/unified-inbox/stats` | Get inbox statistics |

## Feedback API

User feedback and NPS collection under `/api/v1/feedback`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/feedback/nps` | Submit NPS feedback |
| POST | `/api/v1/feedback/general` | Submit general feedback |
| GET | `/api/v1/feedback/nps/summary` | Get NPS summary (admin) |
| GET | `/api/v1/feedback/prompts` | Get feedback prompts |
| GET | `/api/v1/feedback/history` | Get feedback history |

### New Endpoints (2026-02-03)

| Endpoint | Description | Status |
|----------|-------------|--------|
| `POST /api/testfixer/analyze` | Analyze a failing test | NEW |
| `POST /api/testfixer/propose` | Propose a fix via multi-agent debate | NEW |
| `POST /api/testfixer/apply` | Apply a proposed fix | NEW |
| `POST /api/testfixer/run` | Run the full fix loop | NEW |

### New Endpoints (2026-01-27)

| Endpoint | Description | Status |
|----------|-------------|--------|
| `POST /api/debates/:id/intervention/pause` | Pause a debate | NEW |
| `POST /api/debates/:id/intervention/resume` | Resume a debate | NEW |
| `POST /api/debates/:id/intervention/inject` | Inject argument or follow‑up | NEW |
| `POST /api/debates/:id/intervention/weights` | Adjust agent weight | NEW |
| `POST /api/debates/:id/intervention/threshold` | Adjust consensus threshold | NEW |
| `GET /api/debates/:id/intervention/state` | Get intervention state | NEW |
| `GET /api/debates/:id/intervention/log` | Get intervention log | NEW |
| `GET /api/v1/knowledge/mound/dedup/clusters` | Find duplicate clusters | NEW |
| `GET /api/v1/knowledge/mound/dedup/report` | Generate dedup report | NEW |
| `POST /api/v1/knowledge/mound/dedup/merge` | Merge a duplicate cluster | NEW |
| `POST /api/v1/knowledge/mound/dedup/auto-merge` | Auto-merge exact duplicates | NEW |
| `POST /api/v1/knowledge/mound/federation/regions` | Register federated region | NEW |
| `POST /api/v1/knowledge/mound/federation/sync/push` | Push to region | NEW |
| `POST /api/v1/knowledge/mound/federation/sync/pull` | Pull from region | NEW |
| `POST /api/v1/knowledge/mound/federation/sync/all` | Sync all regions | NEW |
| `GET /api/v1/knowledge/mound/federation/status` | Federation status | NEW |

### New Endpoints (2026-01-22)

| Endpoint | Description | Status |
|----------|-------------|--------|
| `POST /api/control-plane/deliberations` | Run or queue an AI debate session | NEW |
| `GET /api/control-plane/deliberations/:id` | Get AI debate result | NEW |
| `GET /api/control-plane/deliberations/:id/status` | Get AI debate status | NEW |
| `POST /api/v1/decisions` | Create a decision request | NEW |
| `GET /api/v1/decisions/:id` | Get decision result | NEW |
| `GET /api/v1/decisions/:id/status` | Get decision status | NEW |
| `POST /api/v1/github/pr/review` | Trigger a PR review | NEW |
| `GET /api/v1/github/pr/:pr_number` | Get PR details | NEW |
| `GET /api/v1/github/pr/review/:review_id` | Get review status | NEW |
| `GET /api/v1/github/pr/:pr_number/reviews` | List PR reviews | NEW |
| `POST /api/v1/github/pr/:pr_number/review` | Submit review to GitHub | NEW |
| `POST /api/v1/github/audit/issues` | Create GitHub issues from findings | NEW |
| `POST /api/v1/chat/knowledge/search` | Knowledge search from chat | NEW |
| `POST /api/v1/audit/sessions` | Create audit session | NEW |
| `POST /api/v1/inbox/shared` | Create shared inbox | NEW |
| `GET /api/v1/inbox/shared` | List shared inboxes | NEW |
| `POST /api/v1/inbox/routing/rules` | Create routing rule | NEW |
| `GET /api/costs` | Cost dashboard summary | NEW |
| `GET /api/accounting/status` | Accounting dashboard status | NEW |
| `POST /api/codebase/quick-scan` | One-click security scan | NEW |

### New Endpoints (2026-01-09)

| Endpoint | Description | Status |
|----------|-------------|--------|
| `POST /api/debates/graph` | Graph-structured debates with branching | NEW |
| `GET /api/debates/graph/:id` | Get graph debate by ID | NEW |
| `GET /api/debates/graph/:id/branches` | Get branches for graph debate | NEW |
| `GET /api/debates/graph/:id/nodes` | Get nodes for graph debate | NEW |
| `POST /api/debates/matrix` | Parallel scenario debates | NEW |
| `GET /api/debates/matrix/:id` | Get matrix debate by ID | NEW |
| `GET /api/debates/matrix/:id/scenarios` | Get scenario results | NEW |
| `GET /api/debates/matrix/:id/conclusions` | Get matrix conclusions | NEW |
| `GET /api/breakpoints/pending` | List pending human-in-the-loop breakpoints | NEW |
| `GET /api/breakpoints/:id/status` | Get breakpoint status | NEW |
| `POST /api/breakpoints/:id/resolve` | Resolve breakpoint with human input | NEW |
| `GET /api/introspection/all` | Get all agent introspection data | NEW |
| `GET /api/introspection/leaderboard` | Agents ranked by reputation | NEW |
| `GET /api/introspection/agents` | List available agents | NEW |
| `GET /api/introspection/agents/:name` | Get agent introspection | NEW |
| `GET /api/gallery` | List public debates | NEW |
| `GET /api/gallery/:id` | Get public debate details | NEW |
| `GET /api/gallery/:id/embed` | Get embeddable debate summary | NEW |
| `GET /api/billing/plans` | List subscription plans | NEW |
| `GET /api/billing/usage` | Get current usage | NEW |
| `GET /api/billing/subscription` | Get subscription status | NEW |
| `POST /api/billing/checkout` | Create Stripe checkout | NEW |
| `POST /api/billing/portal` | Create billing portal session | NEW |
| `POST /api/billing/cancel` | Cancel subscription | NEW |
| `POST /api/billing/resume` | Resume subscription | NEW |
| `POST /api/webhooks/stripe` | Handle Stripe webhooks | NEW |
| `GET /api/v1/memory/analytics` | Get comprehensive memory tier analytics | NEW |
| `GET /api/v1/memory/analytics/tier/:tier` | Get stats for specific tier | NEW |
| `POST /api/v1/memory/analytics/snapshot` | Take manual analytics snapshot | NEW |
| `GET /api/evolution/ab-tests` | List all A/B tests | NEW |
| `GET /api/evolution/ab-tests/:id` | Get specific A/B test | NEW |
| `GET /api/evolution/ab-tests/:agent/active` | Get active test for agent | NEW |
| `POST /api/evolution/ab-tests` | Create new A/B test | NEW |
| `POST /api/evolution/ab-tests/:id/record` | Record debate result | NEW |
| `POST /api/evolution/ab-tests/:id/conclude` | Conclude test | NEW |
| `DELETE /api/evolution/ab-tests/:id` | Cancel test | NEW |

### New Endpoints (2026-01-20)

| Endpoint | Description | Status |
|----------|-------------|--------|
| `GET /api/v1/debates/:id/explanation` | Get full decision explanation | NEW |
| `GET /api/v1/debates/:id/evidence` | Get evidence chain | NEW |
| `GET /api/v1/debates/:id/votes/pivots` | Get vote pivot analysis | NEW |
| `GET /api/v1/debates/:id/counterfactuals` | Get counterfactual scenarios | NEW |
| `GET /api/v1/debates/:id/summary` | Get human-readable summary | NEW |
| `GET /api/workflow/templates` | List workflow templates | NEW |
| `GET /api/workflow/templates/:id` | Get template details | NEW |
| `GET /api/workflow/templates/:id/package` | Get full template package | NEW |
| `POST /api/workflow/templates/:id/run` | Execute workflow template | NEW |
| `GET /api/workflow/categories` | List template categories | NEW |
| `GET /api/workflow/patterns` | List workflow patterns | NEW |
| `POST /api/workflow/patterns/:id/instantiate` | Create template from pattern | NEW |
| `GET /api/gauntlet/receipts` | List gauntlet receipts | NEW |
| `GET /api/gauntlet/receipts/:id` | Get receipt details | NEW |
| `GET /api/gauntlet/receipts/:id/verify` | Verify receipt integrity | NEW |
| `GET /api/gauntlet/receipts/:id/export` | Export receipt (JSON/HTML/MD/SARIF) | NEW |
| `POST /api/gauntlet/receipts/:id/share` | Create shareable receipt link | NEW |
| `GET /api/gauntlet/receipts/stats` | Get receipt statistics | NEW |
| `POST /api/v1/explainability/batch` | Create batch explanation job | NEW |
| `GET /api/v1/explainability/batch/:id/status` | Get batch job status | NEW |
| `GET /api/v1/explainability/batch/:id/results` | Get batch job results | NEW |
| `POST /api/v1/explainability/compare` | Compare explanations across debates | NEW |
| `GET /api/marketplace/templates` | Browse template marketplace | NEW |
| `GET /api/marketplace/templates/:id` | Get marketplace template details | NEW |
| `POST /api/marketplace/templates` | Publish template to marketplace | NEW |
| `POST /api/marketplace/templates/:id/rate` | Rate a template | NEW |
| `POST /api/marketplace/templates/:id/review` | Review a template | NEW |
| `POST /api/marketplace/templates/:id/import` | Import template to workspace | NEW |
| `GET /api/marketplace/featured` | Get featured templates | NEW |
| `GET /api/marketplace/trending` | Get trending templates | NEW |
| `GET /api/marketplace/categories` | Get marketplace categories | NEW |

### New Endpoints (2026-01-18)

| Endpoint | Description | Status |
|----------|-------------|--------|
| `GET /api/auth/oauth/google` | Start Google OAuth flow | NEW |
| `GET /api/auth/oauth/google/callback` | Google OAuth callback | NEW |
| `GET /api/auth/oauth/github` | Start GitHub OAuth flow | NEW |
| `GET /api/auth/oauth/github/callback` | GitHub OAuth callback | NEW |
| `POST /api/auth/oauth/link` | Link OAuth account to user | NEW |
| `DELETE /api/auth/oauth/unlink` | Unlink OAuth account | NEW |
| `GET /api/auth/oauth/providers` | List available OAuth providers | NEW |
| `GET /api/user/oauth-providers` | Get user's linked providers | NEW |
| `GET /api/workflows` | List workflows | NEW |
| `POST /api/workflows` | Create workflow | NEW |
| `GET /api/workflows/:id` | Get workflow details | NEW |
| `PUT /api/workflows/:id` | Update workflow | NEW |
| `DELETE /api/workflows/:id` | Delete workflow | NEW |
| `POST /api/workflows/:id/execute` | Execute workflow | NEW |
| `GET /api/workflows/:id/versions` | Get workflow versions | NEW |
| `GET /api/workflow-templates` | List workflow templates | NEW |
| `GET /api/workflow-templates/:id` | Get workflow template | NEW |
| `GET /api/workflow-executions` | List workflow executions | NEW |
| `GET /api/workflow-executions/:id` | Get execution status | NEW |
| `DELETE /api/workflow-executions/:id` | Cancel execution | NEW |
| `GET /api/workflow-approvals` | List pending approvals | NEW |
| `POST /api/workflow-approvals/:id` | Submit approval decision | NEW |
| `POST /api/retention/policies` | Create retention policy | NEW |
| `POST /api/retention/policies/:id/execute` | Execute retention policy | NEW |
| `GET /api/retention/expiring` | Get expiring items | NEW |
| `POST /api/classify` | Classify content sensitivity | NEW |
| `GET /api/classify/policy/:level` | Get classification policy | NEW |
| `GET /api/audit/entries` | Query audit entries | NEW |
| `GET /api/audit/report` | Generate compliance report | NEW |
| `GET /api/audit/verify` | Verify audit log integrity | NEW |

### Recently Connected Endpoints

The following endpoints were identified as unused but are now connected:

| Endpoint | Component | Status |
|----------|-----------|--------|
| `GET /api/debates` | DebateListPanel | ✅ Connected |
| `GET /api/agent/\{agent\}/profile` | AgentProfileWrapper | ✅ Connected |
| `GET /api/agent/compare` | AgentComparePanel | ✅ Connected |
| `GET /api/agent/\{agent\}/head-to-head/\{opponent\}` | AgentProfileWrapper | ✅ Connected |
| `GET /api/agent/\{agent\}/network` | AgentProfileWrapper | ✅ Connected (includes rivals/allies) |
| `GET /api/history/debates` | HistoryPanel | ✅ Connected (local API fallback) |
| `GET /api/history/summary` | HistoryPanel | ✅ Connected (local API fallback) |
| `GET /api/history/cycles` | HistoryPanel | ✅ Connected (local API fallback) |
| `GET /api/history/events` | HistoryPanel | ✅ Connected (local API fallback) |
| `GET /api/pulse/trending` | TrendingTopicsPanel | ✅ Connected |
| `GET /api/analytics/disagreements` | AnalyticsPanel | ✅ Connected |

### Remaining High-Value Endpoints (Ready to Wire)

| Endpoint | Feature | Priority |
|----------|---------|----------|
| `GET /api/agent/\{agent\}/history` | Agent debate history | MEDIUM |
| `GET /api/agent/\{agent\}/rivals` | Direct rivals endpoint | LOW |
| `GET /api/agent/\{agent\}/allies` | Direct allies endpoint | LOW |
| `GET /api/debates/\{id\}` | Individual debate detail view | LOW |

## Server Configuration

The unified server exposes HTTP on port 8080 and WebSocket on port 8765 by default.

```bash
aragora serve --api-port 8080 --ws-port 8765
```

## Authentication

API requests may include an `Authorization` header with a bearer token:
```
Authorization: Bearer <token>
```

Rate limiting: 60 requests per minute per token (sliding window).

---

## OAuth Integration

OAuth providers allow users to authenticate with third-party accounts.

### GET /api/auth/oauth/google
Start Google OAuth flow. Redirects user to Google consent screen.

**Parameters:**
- `redirect_url` (string, optional): URL to redirect after successful auth (must be in allowlist)

**Response:** `302 Redirect` to Google OAuth consent screen

### GET /api/auth/oauth/google/callback
Handle Google OAuth callback after user consent.

**Parameters:**
- `code` (string, required): Authorization code from Google
- `state` (string, required): State parameter for CSRF protection
- `error` (string, optional): Error code if user denied consent

**Response:** `302 Redirect` to success URL with auth token

### GET /api/auth/oauth/github
Start GitHub OAuth flow. Redirects user to GitHub consent screen.

**Parameters:**
- `redirect_url` (string, optional): URL to redirect after successful auth

**Response:** `302 Redirect` to GitHub OAuth consent screen

### GET /api/auth/oauth/github/callback
Handle GitHub OAuth callback after user consent.

**Parameters:**
- `code` (string, required): Authorization code from GitHub
- `state` (string, required): State parameter for CSRF protection

**Response:** `302 Redirect` to success URL with auth token

### POST /api/auth/oauth/link
Link an OAuth provider account to the current authenticated user.

**Request Body:**
```json
{
  "provider": "google",
  "code": "authorization_code_from_provider"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Account linked successfully"
}
```

### DELETE /api/auth/oauth/unlink
Remove OAuth provider link from the current user's account.

**Parameters:**
- `provider` (string, required): OAuth provider to unlink (`google` or `github`)

**Response:**
```json
{
  "success": true,
  "message": "Account unlinked successfully"
}
```

### GET /api/auth/oauth/providers
Get list of configured OAuth providers available for authentication.

**Response:**
```json
{
  "providers": [
    {"id": "google", "name": "Google", "enabled": true},
    {"id": "github", "name": "GitHub", "enabled": true}
  ]
}
```

### GET /api/user/oauth-providers
Get list of OAuth providers linked to the current user's account.

**Response:**
```json
{
  "linked_providers": [
    {"provider": "google", "email": "user@gmail.com", "linked_at": "2026-01-15T12:00:00Z"}
  ]
}
```

---

## Workflow Management

Workflows define multi-step automated debate and audit processes.

### GET /api/workflows
List workflows with optional filtering.

**Parameters:**
- `category` (string): Filter by category (`debate`, `analysis`, `integration`, `custom`)
- `tags` (string): Filter by tags (comma-separated)
- `search` (string): Search in workflow name and description
- `limit` (int, default=50, max=200): Maximum workflows to return
- `offset` (int, default=0): Pagination offset

**Response:**
```json
{
  "workflows": [
    {
      "id": "wf-123",
      "name": "Security Audit Workflow",
      "description": "Automated security analysis pipeline",
      "category": "analysis",
      "tags": ["security", "audit"],
      "status": "active",
      "version": 3,
      "created_at": "2026-01-10T10:00:00Z"
    }
  ],
  "total": 25
}
```

### POST /api/workflows
Create a new workflow definition.

**Request Body:**
```json
{
  "name": "Code Review Pipeline",
  "description": "Automated code review with multi-agent debate",
  "category": "analysis",
  "tags": ["code", "review"],
  "steps": [
    {
      "id": "step-1",
      "type": "debate",
      "config": {
        "topic": "{{input.code_diff}}",
        "agents": ["claude", "gpt-4", "deepseek-r1"],
        "rounds": 3
      }
    },
    {
      "id": "step-2",
      "type": "approval",
      "config": {
        "required_approvers": 1,
        "timeout_hours": 24
      }
    }
  ],
  "transitions": [
    {"from": "step-1", "to": "step-2", "condition": "consensus_reached"}
  ]
}
```

### GET /api/workflows/:workflow_id
Get detailed workflow definition by ID.

**Response:**
```json
{
  "id": "wf-123",
  "name": "Security Audit Workflow",
  "description": "...",
  "steps": [...],
  "transitions": [...],
  "input_schema": {...},
  "output_schema": {...},
  "version": 3,
  "created_at": "2026-01-10T10:00:00Z",
  "updated_at": "2026-01-15T14:30:00Z"
}
```

### PUT /api/workflows/:workflow_id
Update an existing workflow. Creates a new version.

### DELETE /api/workflows/:workflow_id
Delete a workflow definition.

### POST /api/workflows/:workflow_id/execute
Start execution of a workflow.

**Request Body:**
```json
{
  "inputs": {
    "code_diff": "...",
    "repository": "my-repo"
  },
  "async": true
}
```

**Response (async=true):**
```json
{
  "execution_id": "exec-456",
  "status": "pending",
  "workflow_id": "wf-123"
}
```

### GET /api/workflows/:workflow_id/versions
Get version history of a workflow.

**Parameters:**
- `limit` (int, default=20): Maximum versions to return

### GET /api/workflow-templates
List workflow templates for quick start.

**Parameters:**
- `category` (string): Filter templates by category

**Response:**
```json
{
  "templates": [
    {
      "id": "tmpl-security-audit",
      "name": "Security Audit",
      "description": "Comprehensive security analysis",
      "category": "security",
      "complexity": "medium"
    }
  ]
}
```

### GET /api/workflow-templates/:template_id
Get a specific workflow template for use as starting point.

### GET /api/workflow-executions
List workflow executions for runtime dashboard.

**Parameters:**
- `workflow_id` (string): Filter by workflow ID
- `status` (string): Filter by status (`pending`, `running`, `completed`, `failed`, `cancelled`)
- `limit` (int, default=50): Maximum executions to return

**Response:**
```json
{
  "executions": [
    {
      "id": "exec-456",
      "workflow_id": "wf-123",
      "workflow_name": "Security Audit",
      "status": "running",
      "current_step": "step-2",
      "progress": 0.5,
      "started_at": "2026-01-18T10:00:00Z"
    }
  ]
}
```

### GET /api/workflow-executions/:execution_id
Get detailed status of a workflow execution.

**Response:**
```json
{
  "id": "exec-456",
  "workflow_id": "wf-123",
  "status": "running",
  "current_step": "step-2",
  "step_results": {
    "step-1": {"status": "completed", "output": {...}}
  },
  "context": {...},
  "started_at": "2026-01-18T10:00:00Z"
}
```

### DELETE /api/workflow-executions/:execution_id
Cancel a running workflow execution.

### GET /api/workflow-approvals
List workflow steps awaiting human approval.

**Response:**
```json
{
  "approvals": [
    {
      "id": "approval-789",
      "execution_id": "exec-456",
      "workflow_name": "Security Audit",
      "step_name": "Final Review",
      "context": {...},
      "requested_at": "2026-01-18T11:00:00Z"
    }
  ]
}
```

### POST /api/workflow-approvals/:approval_id
Submit approval decision for a workflow step.

**Request Body:**
```json
{
  "decision": "approve",
  "comment": "Looks good, proceeding with deployment"
}
```

**Decisions:** `approve`, `reject`

---

## HTTP API Endpoints

### Health & Status

#### GET /api/health
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-01-04T12:00:00Z"
}
```

#### GET /api/nomic/state
Get current nomic loop state.

**Response:**
```json
{
  "phase": "debate",
  "stage": "executing",
  "cycle": 5,
  "total_tasks": 9,
  "completed_tasks": 3
}
```

#### GET /api/nomic/log
Get recent nomic loop log lines.

**Parameters:**
- `lines` (int, default=100, max=1000): Number of log lines to return

---

### Debates

#### GET /api/debates
List recent debates.

**Parameters:**
- `limit` (int, default=20, max=100): Maximum debates to return

**Response:**
```json
{
  "debates": [
    {
      "id": "debate-123",
      "topic": "Rate limiter implementation",
      "consensus_reached": true,
      "confidence": 0.85,
      "timestamp": "2026-01-04T12:00:00Z"
    }
  ]
}
```

#### GET /api/debates/:slug
Get a specific debate by slug/ID.

#### POST /api/debate
Start an ad-hoc debate. **Rate limited**.

**Request Body:**
```json
{
  "question": "Should we use token bucket or sliding window for rate limiting?",
  "agents": "anthropic-api,openai-api",
  "rounds": 3,
  "consensus": "majority"
}
```

**Parameters:**
- `question` (string, required): Topic/question to debate
- `agents` (string, default="grok,anthropic-api,openai-api,deepseek-r1"): Comma-separated agent list (max 10)
- `rounds` (int, default=3): Number of debate rounds
- `consensus` (string, default="majority"): Consensus method

**Available Agent Types:**

API (direct):

| Type | Default Model | Notes |
|------|---------------|-------|
| `anthropic-api` | claude-opus-4-5-20251101 | Anthropic API, streaming |
| `openai-api` | gpt-5.3 | OpenAI API, streaming |
| `gemini` | gemini-3-pro-preview | Google API, streaming |
| `grok` | grok-4-latest | xAI API, streaming |
| `mistral-api` | mistral-large-2512 | Mistral API |
| `codestral` | codestral-latest | Mistral code model |
| `ollama` | llama3.2 | Local Ollama |
| `lm-studio` | local-model | Local LM Studio |
| `kimi` | moonshot-v1-8k | Moonshot API |

OpenRouter:
| Type | Default Model | Notes |
|------|---------------|-------|
| `openrouter` | deepseek/deepseek-chat-v3-0324 | Model via `model` parameter |
| `deepseek` | deepseek/deepseek-reasoner | DeepSeek R1 (reasoning) |
| `deepseek-r1` | deepseek/deepseek-r1 | DeepSeek reasoning |
| `llama` | meta-llama/llama-3.3-70b-instruct | Llama 3.3 70B |
| `mistral` | mistralai/mistral-large-2411 | Mistral Large |
| `qwen` | qwen/qwen3-max | Qwen3 Max |
| `qwen-max` | qwen/qwen3-max | Qwen3 Max |
| `yi` | 01-ai/yi-large | Yi Large |

CLI:

| Type | Default Model | Notes |
|------|---------------|-------|
| `claude` | claude-opus-4-5-20251101 | Claude CLI |
| `codex` | gpt-5.3-codex | Codex CLI |
| `openai` | gpt-5.3 | OpenAI CLI |
| `gemini-cli` | gemini-3-pro-preview | Gemini CLI |
| `grok-cli` | grok-4-latest | Grok CLI |
| `qwen-cli` | qwen3-coder | Qwen CLI |
| `deepseek-cli` | deepseek-v3 | DeepSeek CLI |
| `kilocode` | gemini-explorer | Codebase explorer |

**Response:**
```json
{
  "debate_id": "debate-abc123",
  "status": "started",
  "message": "Debate started with 2 agents"
}
```

#### POST /api/v1/debates/batch
Submit a batch of debates for processing.

**Request Body:**
```json
{
  "items": [
    {
      "question": "Evaluate rate limiting options",
      "agents": "anthropic-api,openai-api",
      "rounds": 3,
      "consensus": "majority",
      "priority": 5
    }
  ],
  "webhook_url": "https://example.com/webhooks/batch",
  "max_parallel": 5
}
```

#### GET /api/v1/debates/batch/\{batch_id\}/status
Get batch status and item results.

#### GET /api/v1/debates/batch
List batch requests.

**Parameters:**
- `limit` (int, default=50, max=100): Maximum batches to return
- `status` (string, optional): Filter by status (pending, processing, completed, failed)

#### GET /api/debates/:id/export/:format
Export a debate in various formats.

**Path Parameters:**
- `id` (string, required): Debate slug/ID
- `format` (string, required): Export format - `json`, `csv`, `dot`, or `html`

**Query Parameters:**
- `table` (string, optional): For CSV format only - `summary` (default), `messages`, `critiques`, `votes`, or `verifications`

**Response (JSON format):**
```json
{
  "artifact_id": "abc123",
  "debate_id": "debate-slug",
  "task": "Rate limiter implementation",
  "consensus_proof": {
    "reached": true,
    "confidence": 0.85,
    "vote_breakdown": {"anthropic-api": true, "gemini": true}
  },
  "agents": ["anthropic-api", "gemini"],
  "rounds": 3,
  "content_hash": "sha256:abcd1234"
}
```

**Response (CSV format):** Returns text/csv with debate data table
**Response (DOT format):** Returns text/vnd.graphviz for visualization with GraphViz
**Response (HTML format):** Returns self-contained HTML viewer with interactive graph

#### POST /api/debates/graph
Run a graph-structured debate with automatic branching.

**Request Body:**
```json
{
  "task": "Design a distributed caching system",
  "agents": ["anthropic-api", "openai-api"],
  "max_rounds": 5,
  "branch_policy": {
    "min_disagreement": 0.7,
    "max_branches": 3,
    "auto_merge": true,
    "merge_strategy": "synthesis"
  }
}
```

**Response:**
```json
{
  "debate_id": "uuid",
  "task": "Design a distributed caching system",
  "graph": {
    "nodes": [...],
    "edges": [...],
    "root_id": "node-123"
  },
  "branches": [...],
  "merge_results": [...],
  "node_count": 15,
  "branch_count": 2
}
```

**Branch Policy Options:**
- `min_disagreement` (float): Threshold to trigger branching (default: 0.7)
- `max_branches` (int): Maximum concurrent branches (default: 3)
- `auto_merge` (bool): Automatically merge converging branches (default: true)
- `merge_strategy` (string): "best_path", "synthesis", "vote", "weighted", "preserve_all"

#### GET /api/debates/graph/:id
Get a graph debate by ID.

#### GET /api/debates/graph/:id/branches
Get all branches for a graph debate.

#### GET /api/debates/graph/:id/nodes
Get all nodes in a graph debate.

#### POST /api/debates/matrix
Run parallel scenario debates with comparative analysis.

**Request Body:**
```json
{
  "task": "Design a rate limiter",
  "agents": ["anthropic-api", "openai-api"],
  "scenarios": [
    {
      "name": "High throughput",
      "parameters": {"rps": 10000},
      "constraints": ["Must handle burst traffic"]
    },
    {
      "name": "Low latency",
      "parameters": {"latency_ms": 10},
      "constraints": ["P99 under 10ms"]
    },
    {
      "name": "Baseline",
      "is_baseline": true
    }
  ],
  "max_rounds": 3
}
```

**Response:**
```json
{
  "matrix_id": "uuid",
  "task": "Design a rate limiter",
  "scenario_count": 3,
  "results": [
    {
      "scenario_name": "High throughput",
      "parameters": {"rps": 10000},
      "winner": "anthropic-api",
      "final_answer": "...",
      "confidence": 0.85,
      "consensus_reached": true
    }
  ],
  "universal_conclusions": ["All scenarios reached consensus"],
  "conditional_conclusions": [
    {
      "condition": "When High throughput",
      "conclusion": "Use token bucket algorithm",
      "confidence": 0.85
    }
  ],
  "comparison_matrix": {
    "scenarios": ["High throughput", "Low latency", "Baseline"],
    "consensus_rate": 1.0,
    "avg_confidence": 0.82,
    "avg_rounds": 2.5
  }
}
```

#### GET /api/debates/matrix/:id
Get matrix debate results by ID.

#### GET /api/debates/matrix/:id/scenarios
Get all scenario results for a matrix debate.

#### GET /api/debates/matrix/:id/conclusions
Get conclusions (universal and conditional) for a matrix debate.

### Debate Interventions

Mid‑debate controls for pausing, resuming, injecting user input, and adjusting
consensus parameters.

#### POST /api/debates/\{debate_id\}/intervention/pause
Pause an active debate.

#### POST /api/debates/\{debate_id\}/intervention/resume
Resume a paused debate.

#### POST /api/debates/\{debate_id\}/intervention/inject
Inject an argument or follow‑up into the next round.

**Request Body:**
```json
{
  "content": "What about rate limits for burst traffic?",
  "type": "follow_up",
  "source": "user"
}
```

#### POST /api/debates/\{debate_id\}/intervention/weights
Adjust an agent’s influence weight (0.0–2.0).

**Request Body:**
```json
{
  "agent": "anthropic-api",
  "weight": 1.5
}
```

#### POST /api/debates/\{debate_id\}/intervention/threshold
Adjust consensus threshold (0.5–1.0).

**Request Body:**
```json
{
  "threshold": 0.85
}
```

#### GET /api/debates/\{debate_id\}/intervention/state
Get the current intervention state (pause, weights, threshold, pending injections).

#### GET /api/debates/\{debate_id\}/intervention/log
Get recent intervention log entries.

---

### History (Supabase)

#### GET /api/history/cycles
Get cycle history.

**Parameters:**
- `loop_id` (string, optional): Filter by loop ID
- `limit` (int, default=50, max=200): Maximum cycles to return

#### GET /api/history/events
Get event history.

**Parameters:**
- `loop_id` (string, optional): Filter by loop ID
- `limit` (int, default=100, max=500): Maximum events to return

#### GET /api/history/debates
Get debate history.

**Parameters:**
- `loop_id` (string, optional): Filter by loop ID
- `limit` (int, default=50, max=200): Maximum debates to return

#### GET /api/history/summary
Get summary statistics.

**Parameters:**
- `loop_id` (string, optional): Filter by loop ID

---

### Leaderboard & ELO

#### GET /api/leaderboard
Get agent rankings by ELO.

**Parameters:**
- `limit` (int, default=20, max=50): Maximum agents to return
- `domain` (string, optional): Filter by domain

**Response:**
```json
{
  "rankings": [
    {
      "agent": "anthropic-api",
      "elo": 1523,
      "wins": 45,
      "losses": 12,
      "domain": "general"
    }
  ]
}
```

#### GET /api/matches/recent
Get recent ELO matches.

**Parameters:**
- `limit` (int, default=10, max=50): Maximum matches to return
- `loop_id` (string, optional): Filter by loop ID

#### GET /api/agent/:name/history
Get an agent's match history.

**Parameters:**
- `limit` (int, default=30, max=100): Maximum matches to return

---

### Insights

#### GET /api/insights/recent
Get recent debate insights.

**Parameters:**
- `limit` (int, default=20, max=100): Maximum insights to return

**Response:**
```json
{
  "insights": [
    {
      "type": "pattern",
      "content": "Agents prefer incremental implementations",
      "confidence": 0.78,
      "source_debate": "debate-123"
    }
  ]
}
```

---

### Flip Detection

Position reversal detection API for tracking agent consistency.

#### GET /api/flips/recent
Get recent position flips across all agents.

**Parameters:**
- `limit` (int, default=20, max=100): Maximum flips to return

**Response:**
```json
{
  "flips": [
    {
      "id": "flip-abc123",
      "agent_name": "gemini",
      "original_claim": "X is optimal",
      "new_claim": "Y is optimal",
      "flip_type": "contradiction",
      "similarity_score": 0.82,
      "detected_at": "2026-01-04T12:00:00Z"
    }
  ],
  "count": 15
}
```

#### GET /api/flips/summary
Get aggregate flip statistics.

**Response:**
```json
{
  "total_flips": 42,
  "by_type": {
    "contradiction": 10,
    "refinement": 25,
    "retraction": 5,
    "qualification": 2
  },
  "by_agent": {
    "gemini": 15,
    "anthropic-api": 12,
    "codex": 10,
    "grok": 5
  },
  "recent_24h": 8
}
```

#### GET /api/agent/:name/consistency
Get consistency score for an agent.

**Response:**
```json
{
  "agent_name": "anthropic-api",
  "total_positions": 150,
  "total_flips": 12,
  "consistency_score": 0.92,
  "contradictions": 2,
  "refinements": 8,
  "retractions": 1,
  "qualifications": 1
}
```

#### GET /api/agent/:name/flips
Get flips for a specific agent.

**Parameters:**
- `limit` (int, default=20, max=100): Maximum flips to return

---

### Consensus Memory

Historical consensus data and similarity search.

#### GET /api/consensus/similar
Find debates similar to a topic.

**Parameters:**
- `topic` (string, required): Topic to search for
- `limit` (int, default=5, max=20): Maximum results to return

**Response:**
```json
{
  "query": "rate limiting",
  "results": [
    {
      "topic": "Rate limiter design",
      "conclusion": "Token bucket preferred",
      "strength": "strong",
      "confidence": 0.85,
      "similarity": 0.92,
      "agents": ["anthropic-api", "gemini"],
      "dissent_count": 1,
      "timestamp": "2026-01-03T10:00:00Z"
    }
  ],
  "count": 3
}
```

#### GET /api/consensus/settled
Get high-confidence settled topics.

**Parameters:**
- `min_confidence` (float, default=0.8): Minimum confidence threshold
- `limit` (int, default=20, max=100): Maximum topics to return

**Response:**
```json
{
  "min_confidence": 0.8,
  "topics": [
    {
      "topic": "Consensus algorithm choice",
      "conclusion": "Weighted voting preferred",
      "confidence": 0.95,
      "strength": "strong",
      "timestamp": "2026-01-04T08:00:00Z"
    }
  ],
  "count": 15
}
```

#### GET /api/consensus/stats
Get consensus memory statistics.

**Response:**
```json
{
  "total_consensus": 150,
  "total_dissents": 42,
  "by_strength": {
    "strong": 80,
    "moderate": 50,
    "weak": 20
  },
  "by_domain": {
    "general": 100,
    "architecture": 30,
    "security": 20
  },
  "avg_confidence": 0.78
}
```

#### GET /api/consensus/dissents
Get dissenting views relevant to a topic.

**Parameters:**
- `topic` (string, required): Topic to search for (max 500 chars)
- `domain` (string, optional): Filter by domain

**Response:**
```json
{
  "topic": "rate limiting",
  "domain": null,
  "similar_debates": [
    {
      "topic": "Rate limiter design",
      "conclusion": "Token bucket preferred",
      "confidence": 0.85
    }
  ],
  "dissents_by_type": {
    "alternative": 3,
    "concern": 2,
    "objection": 1
  },
  "unacknowledged_dissents": 2
}
```

#### GET /api/consensus/domain/:domain
Get consensus history for a domain.

**Parameters:**
- `limit` (int, default=50, max=200): Maximum records to return

---

### Pulse (Trending Topics)

Real-time trending topic ingestion for dynamic debate generation.

#### GET /api/pulse/trending
Get trending topics from social media platforms.

**Parameters:**
- `limit` (int, default=10, max=50): Maximum topics to return per platform

**Response:**
```json
{
  "topics": [
    {
      "topic": "AI regulation debate",
      "platform": "twitter",
      "volume": 15000,
      "category": "tech"
    }
  ],
  "count": 5
}
```

#### POST /api/pulse/debate-topic
Start a debate on a trending topic.

**Request Body:**
```json
{
  "topic": "Should AI be regulated?",
  "rounds": 3,
  "consensus_threshold": 0.7
}
```

**Response:**
```json
{
  "debate_id": "pulse-1234567890-abc123",
  "topic": "Should AI be regulated?",
  "status": "started"
}
```

### Pulse Scheduler

Automated debate creation from trending topics.

#### GET /api/pulse/scheduler/status
Get current scheduler state and metrics.

**Response:**
```json
{
  "state": "running",
  "run_id": "run-1234567890-abc123",
  "config": {
    "poll_interval_seconds": 300,
    "max_debates_per_hour": 6,
    "min_volume_threshold": 100,
    "min_controversy_score": 0.3,
    "dedup_window_hours": 24
  },
  "metrics": {
    "polls_completed": 15,
    "topics_evaluated": 120,
    "debates_created": 8,
    "duplicates_skipped": 5,
    "uptime_seconds": 3600
  }
}
```

#### POST /api/pulse/scheduler/start
Start the pulse debate scheduler.

**Response:**
```json
{
  "status": "started",
  "run_id": "run-1234567890-abc123"
}
```

#### POST /api/pulse/scheduler/stop
Stop the pulse debate scheduler.

**Response:**
```json
{
  "status": "stopped"
}
```

#### POST /api/pulse/scheduler/pause
Pause the scheduler (maintains state but stops polling).

**Response:**
```json
{
  "status": "paused"
}
```

#### POST /api/pulse/scheduler/resume
Resume a paused scheduler.

**Response:**
```json
{
  "status": "running"
}
```

#### PATCH /api/pulse/scheduler/config
Update scheduler configuration.

**Request Body:**
```json
{
  "max_debates_per_hour": 10,
  "min_controversy_score": 0.4
}
```

**Response:**
```json
{
  "status": "updated",
  "config": { ... }
}
```

#### GET /api/pulse/scheduler/history
Get history of scheduled debates.

**Parameters:**
- `limit` (int, default=50): Maximum records to return
- `offset` (int, default=0): Pagination offset
- `platform` (string, optional): Filter by platform
- `category` (string, optional): Filter by category

**Response:**
```json
{
  "history": [
    {
      "id": "sched-123",
      "topic_text": "AI ethics debate",
      "platform": "hackernews",
      "category": "tech",
      "debate_id": "pulse-456",
      "created_at": 1704067200,
      "consensus_reached": true,
      "confidence": 0.85
    }
  ],
  "total": 100
}
```

---

### Slack Integration

Slack bot integration for debate notifications and commands.

#### GET /api/integrations/slack/status
Get Slack integration status.

**Response:**
```json
{
  "enabled": true,
  "signing_secret_configured": true,
  "bot_token_configured": false,
  "webhook_configured": true
}
```

#### POST /api/integrations/slack/commands
Handle Slack slash commands (called by Slack).

**Supported Commands:**
- `/aragora help` - Show available commands
- `/aragora status` - Get system status
- `/aragora debate "topic"` - Start a debate
- `/aragora agents` - List top agents by ELO

#### POST /api/integrations/slack/interactive
Handle Slack interactive components (buttons, menus).

#### POST /api/integrations/slack/events
Handle Slack Events API callbacks.

---

### Agent Profile (Combined)

#### GET /api/agent/:name/profile
Get a combined profile with ELO, persona, consistency, and calibration data.

**Response:**
```json
{
  "agent": "anthropic-api",
  "ranking": {
    "rating": 1523,
    "recent_matches": 10
  },
  "persona": {
    "type": "analytical",
    "primary_stance": "pragmatic",
    "specializations": ["architecture", "security"],
    "debate_count": 45
  },
  "consistency": {
    "score": 0.92,
    "recent_flips": 2
  },
  "calibration": {
    "brier_score": 0.15,
    "prediction_count": 30
  }
}
```

---

### Agent Relationship Network

Analyze agent relationships, alliances, and rivalries.

#### GET /api/agent/:name/network
Get complete influence/relationship network for an agent.

**Response:**
```json
{
  "agent": "anthropic-api",
  "influences": [["gemini", 0.75], ["openai", 0.62]],
  "influenced_by": [["codex", 0.58]],
  "rivals": [["grok", 0.81]],
  "allies": [["gemini", 0.72]]
}
```

#### GET /api/agent/:name/rivals
Get top rivals for an agent.

**Parameters:**
- `limit` (int, default=5, max=20): Maximum rivals to return

**Response:**
```json
{
  "agent": "anthropic-api",
  "rivals": [["grok", 0.81], ["openai", 0.65]],
  "count": 2
}
```

#### GET /api/agent/:name/allies
Get top allies for an agent.

**Parameters:**
- `limit` (int, default=5, max=20): Maximum allies to return

**Response:**
```json
{
  "agent": "anthropic-api",
  "allies": [["gemini", 0.72], ["codex", 0.55]],
  "count": 2
}
```

---

### Critique Patterns

Retrieve high-impact critique patterns for learning.

#### GET /api/critiques/patterns
Get critique patterns ranked by success rate.

**Parameters:**
- `limit` (int, default=10, max=50): Maximum patterns to return
- `min_success` (float, default=0.5): Minimum success rate threshold

**Response:**
```json
{
  "patterns": [
    {
      "issue_type": "security",
      "pattern": "Consider input validation",
      "success_rate": 0.85,
      "usage_count": 12
    }
  ],
  "count": 5,
  "stats": {
    "total_critiques": 150,
    "total_patterns": 42
  }
}
```

---

### Replays

#### GET /api/replays
List available debate replays.

**Response:**
```json
{
  "replays": [
    {
      "id": "nomic-cycle-1",
      "name": "Nomic Cycle 1",
      "event_count": 245,
      "created_at": "2026-01-03T10:00:00Z"
    }
  ]
}
```

#### GET /api/replays/:id
Get a specific replay by ID.

---

### Broadcast (Podcast Generation)

Generate audio podcasts from debate traces.

#### POST /api/debates/:id/broadcast
Generate an MP3 podcast from a debate.

**Rate limited**. Requires the broadcast module (`pip install aragora[broadcast]`).

**Response:**
```json
{
  "success": true,
  "debate_id": "rate-limiter-2026-01-01",
  "audio_path": "/tmp/aragora_debate_rate-limiter.mp3",
  "format": "mp3"
}
```

**Error Response (503):**
```json
{
  "error": "Broadcast module not available"
}
```

---

### Documents

#### GET /api/documents
List uploaded documents.

#### POST /api/documents/upload
Upload a document for processing.

**Headers:**
- `Content-Type: multipart/form-data`
- `X-Filename: document.pdf`

**Supported formats:** PDF, Markdown, Python, JavaScript, TypeScript, Jupyter notebooks

**Max size:** 10MB

#### GET /api/documents/formats
Get supported document formats and metadata.

**Response:**
```json
{
  "formats": {
    ".pdf": {"name": "PDF", "mime": "application/pdf"},
    ".md": {"name": "Markdown", "mime": "text/markdown"},
    ".py": {"name": "Python", "mime": "text/x-python"},
    ".js": {"name": "JavaScript", "mime": "text/javascript"},
    ".ts": {"name": "TypeScript", "mime": "text/typescript"},
    ".ipynb": {"name": "Jupyter Notebook", "mime": "application/x-ipynb+json"}
  }
}
```

---

### Debate Analytics

Real-time debate analytics and pattern detection.

#### GET /api/analytics/disagreements
Get debates with significant disagreements or failed consensus.

**Parameters:**
- `limit` (int, default=20, max=100): Maximum records to return

**Response:**
```json
{
  "disagreements": [
    {
      "debate_id": "debate-123",
      "topic": "Rate limiter design",
      "agents": ["anthropic-api", "gemini"],
      "dissent_count": 2,
      "consensus_reached": false,
      "confidence": 0.45,
      "timestamp": "2026-01-04T12:00:00Z"
    }
  ],
  "count": 5
}
```

#### GET /api/analytics/role-rotation
Get agent role assignments across debates.

**Parameters:**
- `limit` (int, default=50, max=200): Maximum rotations to return

**Response:**
```json
{
  "rotations": [
    {
      "debate_id": "debate-123",
      "agent": "anthropic-api",
      "role": "proposer",
      "timestamp": "2026-01-04T12:00:00Z"
    }
  ],
  "summary": {
    "anthropic-api": {"proposer": 10, "critic": 8, "judge": 5},
    "gemini": {"proposer": 8, "critic": 12, "judge": 3}
  },
  "count": 50
}
```

#### GET /api/analytics/early-stops
Get debates that terminated before completing all planned rounds.

**Parameters:**
- `limit` (int, default=20, max=100): Maximum records to return

**Response:**
```json
{
  "early_stops": [
    {
      "debate_id": "debate-123",
      "topic": "Consensus algorithm",
      "rounds_completed": 2,
      "rounds_planned": 5,
      "reason": "early_consensus",
      "consensus_early": true,
      "timestamp": "2026-01-04T12:00:00Z"
    }
  ],
  "count": 3
}
```

---

### Learning Evolution

#### GET /api/learning/evolution
Get learning evolution patterns.

---

### Modes

List available debate and operational modes.

#### GET /api/modes
Get all available modes.

**Response:**
```json
{
  "modes": [
    {
      "name": "architect",
      "description": "High-level design and planning mode",
      "category": "operational",
      "tool_groups": ["read", "browser", "mcp"]
    },
    {
      "name": "redteam",
      "description": "Adversarial red-teaming for security analysis",
      "category": "debate"
    }
  ],
  "count": 8
}
```

---

### Agent Position Tracking

Track agent positions and consistency via truth-grounding system.

#### GET /api/agent/:name/positions
Get position history for an agent.

**Parameters:**
- `limit` (int, default=50, max=200): Maximum positions to return

**Response:**
```json
{
  "agent": "anthropic-api",
  "total_positions": 45,
  "avg_confidence": 0.82,
  "reversal_count": 3,
  "consistency_score": 0.93,
  "positions_by_debate": {
    "rate-limiter-2026-01-01": 5,
    "consensus-algo-2026-01-02": 3
  }
}
```

---

### System Statistics

System-wide metrics and health monitoring.

#### GET /api/ranking/stats
Get ELO ranking system statistics.

**Response:**
```json
{
  "total_agents": 8,
  "total_matches": 245,
  "avg_rating": 1523,
  "rating_spread": 312,
  "domains": ["general", "architecture", "security"],
  "active_last_24h": 5
}
```

#### GET /api/v1/memory/tier-stats
Get memory tier statistics from continuum memory system.

**Response:**
```json
{
  "tiers": {
    "fast": {"count": 50, "avg_importance": 0.85},
    "slow": {"count": 200, "avg_importance": 0.65},
    "glacial": {"count": 1000, "avg_importance": 0.35}
  },
  "total_entries": 1250,
  "last_consolidation": "2026-01-04T12:00:00Z"
}
```

#### GET /api/v1/memory/analytics
Get comprehensive memory tier analytics.

**Parameters:**
- `days` (int, default=30, min=1, max=365): Number of days to analyze

**Response:**
```json
{
  "total_memories": 1000,
  "tier_stats": {
    "fast": {"count": 100, "avg_importance": 0.8},
    "medium": {"count": 300, "avg_importance": 0.6},
    "slow": {"count": 400, "avg_importance": 0.4},
    "glacial": {"count": 200, "avg_importance": 0.2}
  },
  "learning_velocity": 0.75,
  "promotion_effectiveness": 0.82
}
```

#### GET /api/v1/memory/analytics/tier/:tier
Get stats for a specific memory tier.

**Path Parameters:**
- `tier` (string, required): Tier name - `fast`, `medium`, `slow`, or `glacial`

**Parameters:**
- `days` (int, default=30, min=1, max=365): Number of days to analyze

**Response:**
```json
{
  "tier": "fast",
  "count": 100,
  "avg_importance": 0.8,
  "hit_rate": 0.95,
  "promotion_rate": 0.3
}
```

#### POST /api/v1/memory/analytics/snapshot
Take a manual analytics snapshot for all memory tiers.

**Response:**
```json
{
  "status": "success",
  "message": "Snapshot recorded for all tiers"
}
```

---

#### GET /api/critiques/patterns
Get successful critique patterns for learning.

**Parameters:**
- `limit` (int, default=10, max=50): Maximum patterns to return
- `min_success` (float, default=0.5): Minimum success rate filter

**Response:**
```json
{
  "patterns": [
    {
      "issue_type": "edge_case",
      "pattern": "Consider boundary conditions for...",
      "success_rate": 0.85,
      "usage_count": 23
    }
  ],
  "count": 5,
  "stats": {"total_patterns": 150, "avg_success_rate": 0.72}
}
```

#### GET /api/critiques/archive
Get archive statistics for resolved patterns.

**Response:**
```json
{
  "archived": 42,
  "by_type": {
    "security": 15,
    "performance": 12,
    "edge_case": 15
  }
}
```

---

### Agent Reputation

Track agent reliability and voting weights.

#### GET /api/reputation/all
Get all agent reputations ranked by score.

**Response:**
```json
{
  "reputations": [
    {
      "agent": "anthropic-api",
      "score": 0.85,
      "vote_weight": 1.35,
      "proposal_acceptance_rate": 0.78,
      "critique_value": 0.82,
      "debates_participated": 45
    }
  ],
  "count": 4
}
```

#### GET /api/agent/:name/reputation
Get reputation for a specific agent.

**Response:**
```json
{
  "agent": "anthropic-api",
  "score": 0.85,
  "vote_weight": 1.35,
  "proposal_acceptance_rate": 0.78,
  "critique_value": 0.82,
  "debates_participated": 45
}
```

---

### Agent Comparison

Compare agents head-to-head.

#### GET /api/agent/compare
Get head-to-head comparison between two agents.

**Parameters:**
- `agent_a` (string, required): First agent name
- `agent_b` (string, required): Second agent name

**Response:**
```json
{
  "agent_a": "anthropic-api",
  "agent_b": "gemini",
  "matches": 15,
  "agent_a_wins": 9,
  "agent_b_wins": 6,
  "win_rate_a": 0.6,
  "domains": {
    "architecture": {"a_wins": 5, "b_wins": 2},
    "security": {"a_wins": 4, "b_wins": 4}
  }
}
```

---

### Agent Expertise & Grounded Personas

Evidence-based agent identity and expertise tracking.

#### GET /api/agent/:name/domains
Get agent's best expertise domains by calibration score.

**Parameters:**
- `limit` (int, default=5, max=20): Maximum domains to return

**Response:**
```json
{
  "agent": "anthropic-api",
  "domains": [
    {"domain": "security", "calibration_score": 0.89},
    {"domain": "api_design", "calibration_score": 0.85}
  ],
  "count": 2
}
```

#### GET /api/agent/:name/grounded-persona
Get truth-grounded persona synthesized from performance data.

**Response:**
```json
{
  "agent": "anthropic-api",
  "elo": 1523,
  "domain_elos": {"security": 1580, "architecture": 1490},
  "games_played": 45,
  "win_rate": 0.62,
  "calibration_score": 0.78,
  "position_accuracy": 0.72,
  "positions_taken": 128,
  "reversals": 8
}
```

#### GET /api/agent/:name/identity-prompt
Get evidence-grounded identity prompt for agent initialization.

**Parameters:**
- `sections` (string, optional): Comma-separated sections to include (performance, calibration, relationships, positions)

**Response:**
```json
{
  "agent": "anthropic-api",
  "identity_prompt": "## Your Identity: anthropic-api\nYour approach: analytical, thorough...",
  "sections": ["performance", "calibration"]
}
```

---

### Contrarian Views & Risk Warnings

Historical dissenting views and edge case concerns from past debates.

#### GET /api/consensus/contrarian-views
Get historical contrarian views on a topic.

**Parameters:**
- `topic` (string, required): Topic to search for contrarian views
- `domain` (string, optional): Filter by domain
- `limit` (int, default=5, max=20): Maximum views to return

**Response:**
```json
{
  "topic": "rate limiting implementation",
  "domain": null,
  "contrarian_views": [
    {
      "agent": "gemini",
      "position": "Token bucket has edge cases",
      "reasoning": "Under burst traffic conditions...",
      "confidence": 0.75,
      "timestamp": "2026-01-03T10:00:00Z"
    }
  ],
  "count": 1
}
```

#### GET /api/consensus/risk-warnings
Get risk warnings and edge case concerns from past debates.

**Parameters:**
- `topic` (string, required): Topic to search for risk warnings
- `domain` (string, optional): Filter by domain
- `limit` (int, default=5, max=20): Maximum warnings to return

**Response:**
```json
{
  "topic": "database migration",
  "domain": "infrastructure",
  "risk_warnings": [
    {
      "agent": "anthropic-api",
      "warning": "Consider rollback strategy for schema changes",
      "severity": "high",
      "timestamp": "2026-01-02T15:00:00Z"
    }
  ],
  "count": 1
}
```

---

### Head-to-Head & Opponent Analysis

Detailed comparison and strategic briefings between agents.

#### GET /api/agent/:agent/head-to-head/:opponent
Get detailed head-to-head statistics between two agents.

**Response:**
```json
{
  "agent": "anthropic-api",
  "opponent": "gemini",
  "matches": 12,
  "agent_wins": 5,
  "opponent_wins": 4,
  "draws": 3,
  "win_rate": 0.42,
  "recent_form": "WDLWW"
}
```

#### GET /api/agent/:agent/opponent-briefing/:opponent
Get strategic briefing about an opponent for an agent.

**Response:**
```json
{
  "agent": "anthropic-api",
  "opponent": "gemini",
  "briefing": {
    "relationship": "rival",
    "strength": 0.7,
    "head_to_head": {"wins": 5, "losses": 4, "draws": 3},
    "opponent_strengths": ["visual reasoning", "synthesis"],
    "opponent_weaknesses": ["consistency", "edge cases"],
    "recommended_strategy": "Focus on logical rigor and consistency"
  }
}
```

---

### Calibration Analysis

Detailed calibration curves and prediction accuracy.

#### GET /api/agent/:name/calibration-curve
Get calibration curve showing expected vs actual accuracy per confidence bucket.

**Parameters:**
- `buckets` (int, default=10, max=20): Number of confidence buckets
- `domain` (string, optional): Filter by domain

**Response:**
```json
{
  "agent": "anthropic-api",
  "domain": null,
  "buckets": [
    {
      "range_start": 0.0,
      "range_end": 0.1,
      "total_predictions": 15,
      "correct_predictions": 2,
      "accuracy": 0.13,
      "expected_accuracy": 0.05,
      "brier_score": 0.08
    },
    {
      "range_start": 0.9,
      "range_end": 1.0,
      "total_predictions": 42,
      "correct_predictions": 38,
      "accuracy": 0.90,
      "expected_accuracy": 0.95,
      "brier_score": 0.02
    }
  ],
  "count": 10
}
```

---

### Meta-Critique Analysis

Analyze debate quality and identify process issues.

#### GET /api/debate/:id/meta-critique
Get meta-level analysis of a debate including repetition, circular arguments, and ignored critiques.

**Response:**
```json
{
  "debate_id": "debate-123",
  "overall_quality": 0.72,
  "productive_rounds": [1, 2, 4],
  "unproductive_rounds": [3],
  "observations": [
    {
      "type": "repetition",
      "severity": "medium",
      "agent": "gemini",
      "round": 3,
      "description": "Agent repeated similar points from round 1"
    }
  ],
  "recommendations": [
    "Encourage agents to address critiques directly",
    "Consider reducing round count for simple topics"
  ]
}
```

---

### Agent Personas

Agent persona definitions and customizations.

#### GET /api/personas
Get all agent personas.

**Response:**
```json
{
  "personas": [
    {
      "agent_name": "anthropic-api",
      "description": "Analytical reasoner focused on logical consistency",
      "traits": ["analytical", "precise", "evidence-focused"],
      "expertise": ["security", "architecture"],
      "created_at": "2026-01-01T00:00:00Z"
    },
    {
      "agent_name": "grok",
      "description": "Creative problem-solver with lateral thinking",
      "traits": ["creative", "unconventional", "synthesis-focused"],
      "expertise": ["innovation", "edge-cases"],
      "created_at": "2026-01-01T00:00:00Z"
    }
  ],
  "count": 2
}
```

---

### Persona Laboratory

Experimental framework for evolving agent personas and detecting emergent traits.

#### GET /api/laboratory/emergent-traits
Get emergent traits detected from agent performance patterns.

**Parameters:**
- `min_confidence` (float, default=0.5): Minimum confidence threshold
- `limit` (int, default=10, max=50): Maximum traits to return

**Response:**
```json
{
  "emergent_traits": [
    {
      "agent": "anthropic-api",
      "trait": "adversarial_robustness",
      "domain": "security",
      "confidence": 0.85,
      "evidence": "Consistently identifies edge cases in security debates",
      "detected_at": "2026-01-04T10:00:00Z"
    }
  ],
  "count": 1,
  "min_confidence": 0.5
}
```

#### POST /api/laboratory/cross-pollinations/suggest
Suggest beneficial trait transfers for a target agent.

**Request Body:**
```json
{
  "target_agent": "gemini"
}
```

**Response:**
```json
{
  "target_agent": "gemini",
  "suggestions": [
    {
      "source_agent": "anthropic-api",
      "trait_or_domain": "logical_rigor",
      "reason": "Target agent underperforms in formal reasoning domains"
    }
  ],
  "count": 1
}
```

---

### Belief Network Analysis

Bayesian belief network for probabilistic debate reasoning.

#### GET /api/belief-network/:debate_id/cruxes
Identify key claims that would most impact the debate outcome.

**Parameters:**
- `top_k` (int, default=3, max=10): Number of cruxes to return

**Response:**
```json
{
  "debate_id": "debate-123",
  "cruxes": [
    {
      "claim_id": "claim-456",
      "statement": "The proposed architecture scales linearly",
      "score": 0.87,
      "centrality": 0.9,
      "uncertainty": 0.75
    }
  ],
  "count": 1
}
```

---

### Provenance & Evidence Chain

Verify evidence provenance and claim support.

#### GET /api/provenance/:debate_id/claims/:claim_id/support
Get verification status of all evidence supporting a claim.

**Response:**
```json
{
  "debate_id": "debate-123",
  "claim_id": "claim-456",
  "support": {
    "verified": true,
    "evidence_count": 3,
    "supporting": [
      {
        "evidence_id": "ev-001",
        "type": "citation",
        "integrity_verified": true,
        "relevance": 0.92
      }
    ],
    "contradicting": []
  }
}
```

---

### Agent Routing & Selection

Optimal agent selection for tasks based on ELO, expertise, and team dynamics.

#### POST /api/routing/recommendations
Get agent recommendations for a task.

**Request Body:**
```json
{
  "task_id": "design-review",
  "primary_domain": "architecture",
  "secondary_domains": ["security", "performance"],
  "required_traits": ["analytical"],
  "limit": 5
}
```

**Response:**
```json
{
  "task_id": "design-review",
  "primary_domain": "architecture",
  "recommendations": [
    {
      "name": "anthropic-api",
      "type": "anthropic-api",
      "match_score": 0.92,
      "domain_expertise": 0.85
    }
  ],
  "count": 1
}
```

---

### Tournament System

Tournament management and standings.

#### GET /api/tournaments/:tournament_id/standings
Get current tournament standings.

**Response:**
```json
{
  "tournament_id": "round-robin-2026",
  "standings": [
    {
      "agent": "anthropic-api",
      "wins": 8,
      "losses": 2,
      "draws": 1,
      "points": 25,
      "total_score": 142.5,
      "win_rate": 0.73
    }
  ],
  "count": 4
}
```

---

### Team Analytics

Analyze team performance and find optimal combinations.

#### GET /api/routing/best-teams
Get best-performing team combinations from history.

**Parameters:**
- `min_debates` (int, default=3, max=20): Minimum debates for a team to qualify
- `limit` (int, default=10, max=50): Maximum combinations to return

**Response:**
```json
{
  "min_debates": 3,
  "combinations": [
    {
      "agents": ["anthropic-api", "gemini"],
      "success_rate": 0.85,
      "total_debates": 12,
      "wins": 10
    }
  ],
  "count": 5
}
```

---

### Prompt Evolution

Track agent prompt evolution and learning.

#### GET /api/evolution/:agent/history
Get prompt evolution history for an agent.

**Parameters:**
- `limit` (int, default=10, max=50): Maximum history entries to return

**Response:**
```json
{
  "agent": "anthropic-api",
  "history": [
    {
      "from_version": 1,
      "to_version": 2,
      "strategy": "pattern_mining",
      "patterns_applied": ["logical_rigor", "edge_case_handling"],
      "created_at": "2026-01-04T08:00:00Z"
    }
  ],
  "count": 3
}
```

---

### Evolution A/B Testing

Run controlled experiments comparing prompt versions to determine which performs better.

#### GET /api/evolution/ab-tests
List all A/B tests with optional filters.

**Parameters:**
- `agent` (string, optional): Filter by agent name
- `status` (string, optional): Filter by status (active, concluded, cancelled)
- `limit` (int, default=50, max=200): Maximum tests to return

**Response:**
```json
{
  "tests": [
    {
      "id": "test-123",
      "agent": "anthropic-api",
      "baseline_prompt_version": 1,
      "evolved_prompt_version": 2,
      "status": "active",
      "baseline_wins": 5,
      "evolved_wins": 7,
      "started_at": "2026-01-10T12:00:00Z"
    }
  ],
  "count": 1
}
```

#### GET /api/evolution/ab-tests/:id
Get a specific A/B test by ID.

**Response:**
```json
{
  "id": "test-123",
  "agent": "anthropic-api",
  "baseline_prompt_version": 1,
  "evolved_prompt_version": 2,
  "status": "active",
  "baseline_wins": 5,
  "evolved_wins": 7,
  "baseline_debates": 10,
  "evolved_debates": 10,
  "evolved_win_rate": 0.58,
  "is_significant": false,
  "started_at": "2026-01-10T12:00:00Z",
  "concluded_at": null
}
```

#### GET /api/evolution/ab-tests/:agent/active
Get the active A/B test for a specific agent.

**Response:**
```json
{
  "agent": "anthropic-api",
  "has_active_test": true,
  "test": {
    "id": "test-123",
    "baseline_prompt_version": 1,
    "evolved_prompt_version": 2,
    "status": "active"
  }
}
```

#### POST /api/evolution/ab-tests
Create a new A/B test.

**Request Body:**
```json
{
  "agent": "anthropic-api",
  "baseline_version": 1,
  "evolved_version": 2,
  "metadata": {"description": "Test new reasoning patterns"}
}
```

**Response (201 Created):**
```json
{
  "message": "A/B test created",
  "test": {
    "id": "test-456",
    "agent": "anthropic-api",
    "status": "active"
  }
}
```

**Error (409 Conflict):** Agent already has an active test.

#### POST /api/evolution/ab-tests/:id/record
Record a debate result for an A/B test.

**Request Body:**
```json
{
  "debate_id": "debate-789",
  "variant": "evolved",
  "won": true
}
```

**Response:**
```json
{
  "message": "Result recorded",
  "test": {
    "id": "test-123",
    "baseline_wins": 5,
    "evolved_wins": 8
  }
}
```

#### POST /api/evolution/ab-tests/:id/conclude
Conclude an A/B test and determine the winner.

**Request Body:**
```json
{
  "force": false
}
```

**Response:**
```json
{
  "message": "A/B test concluded",
  "result": {
    "test_id": "test-123",
    "winner": "evolved",
    "confidence": 0.85,
    "recommendation": "Adopt evolved prompt",
    "stats": {
      "evolved_win_rate": 0.65,
      "baseline_win_rate": 0.35,
      "total_debates": 20
    }
  }
}
```

#### DELETE /api/evolution/ab-tests/:id
Cancel an active A/B test.

**Response:**
```json
{
  "message": "A/B test cancelled",
  "test_id": "test-123"
}
```

---

### Load-Bearing Claims

Identify claims with highest structural importance in debates.

#### GET /api/belief-network/:debate_id/load-bearing-claims
Get claims with highest centrality (most load-bearing).

**Parameters:**
- `limit` (int, default=5, max=20): Maximum claims to return

**Response:**
```json
{
  "debate_id": "debate-123",
  "load_bearing_claims": [
    {
      "claim_id": "claim-456",
      "statement": "The architecture must support horizontal scaling",
      "author": "anthropic-api",
      "centrality": 0.92
    }
  ],
  "count": 3
}
```

---

### Calibration Summary

Comprehensive agent calibration analysis.

#### GET /api/agent/:name/calibration-summary
Get comprehensive calibration summary for an agent.

**Parameters:**
- `domain` (string, optional): Filter by domain

**Response:**
```json
{
  "agent": "anthropic-api",
  "domain": null,
  "total_predictions": 250,
  "total_correct": 215,
  "accuracy": 0.86,
  "brier_score": 0.12,
  "ece": 0.05,
  "is_overconfident": false,
  "is_underconfident": true
}
```

#### GET /api/calibration/leaderboard
Get agents ranked by calibration quality (accuracy vs confidence).

**Parameters:**
- `limit` (int, default=10, max=50): Maximum agents to return
- `domain` (string, optional): Filter by domain

**Response:**
```json
{
  "agents": [
    {
      "name": "anthropic-api",
      "elo": 1542,
      "calibration_score": 0.92,
      "brier_score": 0.08,
      "accuracy": 0.89,
      "games": 45
    },
    {
      "name": "grok",
      "elo": 1518,
      "calibration_score": 0.88,
      "brier_score": 0.11,
      "accuracy": 0.85,
      "games": 38
    }
  ],
  "count": 2
}
```

---

### Continuum Memory

Multi-timescale memory system with surprise-weighted importance scoring.

Note: `/api/memory/*` legacy routes are supported as aliases for `/api/v1/memory/*`.

#### GET /api/v1/memory/continuum/retrieve
Retrieve memories from the continuum memory system.

**Parameters:**
- `query` (string, optional): Search query for memory content
- `tiers` (string, default="fast,medium"): Comma-separated tier names (fast, medium, slow, glacial)
- `limit` (int, default=10, max=50): Maximum memories to return
- `min_importance` (float, default=0.0): Minimum importance threshold (0.0-1.0)

**Response:**
```json
{
  "query": "error patterns",
  "tiers": ["FAST", "MEDIUM"],
  "memories": [
    {
      "id": "mem-123",
      "tier": "FAST",
      "content": "TypeError pattern in agent responses",
      "importance": 0.85,
      "surprise_score": 0.3,
      "consolidation_score": 0.7,
      "success_rate": 0.92,
      "update_count": 15,
      "created_at": "2026-01-03T10:00:00Z",
      "updated_at": "2026-01-04T08:00:00Z"
    }
  ],
  "count": 1
}
```

#### POST /api/v1/memory/continuum/consolidate
Run memory consolidation and get tier transition statistics.

**Response:**
```json
{
  "consolidation": {
    "promoted": 5,
    "demoted": 2,
    "pruned": 1
  },
  "message": "Memory consolidation complete"
}
```

#### GET /api/v1/memory/search-index
Progressive disclosure stage 1: compact index results with previews and token estimates.

**Parameters:**
- `q` (string, required): Search query
- `tier` (string, optional): Comma-separated tier filter
- `limit` (int, default=20, max=100): Maximum results
- `min_importance` (float, default=0.0): Minimum importance threshold
- `use_hybrid` (bool, default=false): Use hybrid vector+keyword search
- `include_external` (bool, default=false): Include external memory sources
- `external` (string, optional): Comma-separated sources (`supermemory`, `claude-mem`)
- `project` (string, optional): claude-mem project filter

#### GET /api/v1/memory/search-timeline
Progressive disclosure stage 2: timeline around an anchor entry.

**Parameters:**
- `anchor_id` (string, required): Memory ID to anchor timeline
- `before` (int, default=3, max=50): Entries before anchor
- `after` (int, default=3, max=50): Entries after anchor
- `tier` (string, optional): Comma-separated tier filter
- `min_importance` (float, default=0.0): Minimum importance threshold

#### GET /api/v1/memory/entries
Progressive disclosure stage 3: full entries by ID.

**Parameters:**
- `ids` (string, required): Comma-separated memory IDs

#### GET /api/v1/memory/viewer
HTML Memory Viewer UI (uses progressive disclosure endpoints).

---

### Formal Verification

#### POST /api/verification/formal-verify
Attempt formal verification of a claim using Z3 SMT solver.

**Request Body:**
```json
{
  "claim": "If X > Y and Y > Z, then X > Z",
  "claim_type": "logical",
  "context": "Transitivity property of greater-than",
  "timeout": 30
}
```

**Parameters:**
- `claim` (required): The claim to verify
- `claim_type` (optional): Hint for the type (assertion, logical, arithmetic, constraint)
- `context` (optional): Additional context for translation
- `timeout` (optional): Timeout in seconds (default: 30, max: 120)

**Response:**
```json
{
  "claim": "If X > Y and Y > Z, then X > Z",
  "status": "proof_found",
  "is_verified": true,
  "language": "z3_smt",
  "formal_statement": "(declare-const X Int)...",
  "proof_hash": "a1b2c3d4e5f6",
  "proof_search_time_ms": 15.2,
  "prover_version": "z3-4.12.0"
}
```

**Status Values:**
- `proof_found`: Claim is formally verified
- `proof_failed`: Counterexample found (claim is false)
- `translation_failed`: Could not translate to formal language
- `timeout`: Solver timed out
- `not_supported`: Claim type not suitable for formal proof
- `backend_unavailable`: Z3 not installed

---

### Insight Extraction

#### POST /api/insights/extract-detailed
Extract detailed insights from debate content.

**Request Body:**
```json
{
  "content": "The debate transcript content...",
  "debate_id": "debate-123",
  "extract_claims": true,
  "extract_evidence": true,
  "extract_patterns": true
}
```

**Response:**
```json
{
  "debate_id": "debate-123",
  "content_length": 5420,
  "claims": [
    {
      "text": "Therefore, we should adopt this approach",
      "position": 12,
      "type": "argument"
    }
  ],
  "evidence_chains": [
    {
      "text": "According to the 2024 study",
      "type": "citation",
      "source": "the 2024 study"
    }
  ],
  "patterns": [
    {
      "type": "causal_reasoning",
      "strength": "strong",
      "instances": 5
    }
  ]
}
```

**Pattern Types:**
- `balanced_comparison`: Uses "on one hand... on the other hand"
- `concession_rebuttal`: Uses "while... however"
- `enumerated_argument`: Uses "first... second..."
- `conditional_reasoning`: Uses "if... then"
- `causal_reasoning`: Uses "because" (with instance count)

---

## Capability Probing

#### POST /api/probes/run
Run capability probes against an agent to detect vulnerabilities.

**Request Body:**
```json
{
  "agent": "anthropic-api",
  "strategies": ["contradiction", "hallucination"],
  "probe_count": 3
}
```

**Response:**
```json
{
  "agent": "anthropic-api",
  "probe_count": 3,
  "available_strategies": ["contradiction", "hallucination", "sycophancy", "persistence"],
  "status": "ready"
}
```

---

## Red Team Analysis

#### POST /api/debates/:id/red-team
Run adversarial analysis on a debate's conclusions.

**Request Body:**
```json
{
  "attack_types": ["steelman", "strawman"],
  "intensity": 5
}
```

**Response:**
```json
{
  "debate_id": "debate-123",
  "task": "Security implementation",
  "consensus_reached": true,
  "intensity": 5,
  "available_attacks": ["steelman", "strawman", "edge_case", "assumption_probe", "counterexample"],
  "status": "ready"
}
```

---

## Usage Examples

Common API operations with curl. Replace `localhost:8080` with your server address.

### Health Check

```bash
# Check server health
curl http://localhost:8080/api/health
```

### Starting a Debate

```bash
# Start a new debate
curl -X POST http://localhost:8080/api/debates/start \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Is microservices architecture better than monolith?",
    "agents": ["anthropic-api", "openai-api", "gemini"],
    "rounds": 3
  }'
```

### Listing and Viewing Debates

```bash
# List recent debates (default limit: 20)
curl http://localhost:8080/api/debates

# List with custom limit
curl "http://localhost:8080/api/debates?limit=50"

# Get specific debate details
curl http://localhost:8080/api/debates/debate-abc123
```

### Exporting Debates

```bash
# Export as JSON
curl http://localhost:8080/api/debates/debate-abc123/export?format=json

# Export messages as CSV
curl http://localhost:8080/api/debates/debate-abc123/export?format=csv&table=messages \
  -o debate-messages.csv

# Export as standalone HTML
curl http://localhost:8080/api/debates/debate-abc123/export?format=html \
  -o debate-report.html
```

### Agent Information

```bash
# Get leaderboard
curl http://localhost:8080/api/agent/leaderboard

# Get agent profile
curl http://localhost:8080/api/agent/anthropic-api/profile

# Compare two agents
curl "http://localhost:8080/api/agent/compare?a=anthropic-api&b=openai-api"

# Get head-to-head record
curl http://localhost:8080/api/agent/anthropic-api/head-to-head/openai-api
```

### Nomic Loop Status

```bash
# Get current nomic loop state
curl http://localhost:8080/api/nomic/state

# Get nomic loop logs (last 100 lines)
curl http://localhost:8080/api/nomic/log

# Get more log lines
curl "http://localhost:8080/api/nomic/log?lines=500"
```

### Tournaments

```bash
# List tournaments
curl http://localhost:8080/api/tournaments

# Get tournament details
curl http://localhost:8080/api/tournaments/tourney-abc123

# Get tournament bracket
curl http://localhost:8080/api/tournaments/tourney-abc123/bracket
```

### Authenticated Requests

```bash
# With bearer token
curl http://localhost:8080/api/debates \
  -H "Authorization: Bearer your-token-here"

# Tokens in query parameters are not accepted; use Authorization header instead
```

### WebSocket Connection (wscat)

```bash
# Connect to WebSocket for real-time events
wscat -c ws://localhost:8765/ws

# With authentication token
wscat -c ws://localhost:8765/ws -H "Authorization: Bearer your-token-here"
```

---

## WebSocket API

Connect to the WebSocket server for real-time streaming:

```javascript
const ws = new WebSocket('ws://localhost:8765/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.type, data.data);
};
```

### Event Types

WebSocket events use a shared envelope and are documented in
`docs/WEBSOCKET_EVENTS.md`. Filter by `loop_id` to scope to a single debate.

Common debate lifecycle events:
- `debate_start`, `round_start`, `agent_message`, `critique`, `vote`, `consensus`, `debate_end`

Token streaming events:
- `token_start`, `token_delta`, `token_end`

Control messages (on connect / acknowledgements):
- `connection_info`, `loop_list`, `sync`, `ack`, `error`, `auth_revoked`

### Event Format

```json
{
  "type": "agent_message",
  "data": { "content": "I disagree...", "role": "critic" },
  "timestamp": 1732735053.123,
  "round": 2,
  "agent": "anthropic-api",
  "loop_id": "loop-abc123",
  "seq": 42
}
```

---

## Formal Verification

Formal claim verification using theorem provers.

#### POST /api/verification/formal-verify
Attempt formal verification of a logical claim.

**Request Body:**
```json
{
  "claim": "If A implies B and B implies C, then A implies C",
  "debate_id": "debate-123",
  "context": "Optional context for the claim"
}
```

**Response:**
```json
{
  "verified": true,
  "method": "lean",
  "proof_sketch": "...",
  "confidence": 0.95
}
```

---

### Detailed Insights

#### POST /api/insights/extract-detailed
Extract detailed insights from debate content.

**Request Body:**
```json
{
  "debate_id": "debate-123",
  "content": "The debate transcript or summary...",
  "focus": "security"
}
```

**Response:**
```json
{
  "insights": [
    {
      "type": "pattern",
      "description": "Security vulnerability pattern detected",
      "confidence": 0.85,
      "actionable": true
    }
  ],
  "count": 3
}
```

---

### Formal Verification

Attempt formal verification of claims using SMT solvers.

#### GET /api/verification/status
Get status of formal verification backends.

**Response:**
```json
{
  "available": true,
  "backends": [
    {"language": "z3_smt", "available": true},
    {"language": "lean4", "available": false}
  ]
}
```

#### POST /api/verification/formal-verify
Attempt formal verification of a claim.

**Request Body:**
```json
{
  "claim": "If X > Y and Y > Z, then X > Z",
  "claim_type": "logical",
  "context": "Transitivity check",
  "timeout": 30
}
```

**Response:**
```json
{
  "status": "proof_found",
  "is_verified": true,
  "language": "z3_smt",
  "formal_statement": "(assert (not (=> (and (> x y) (> y z)) (> x z))))",
  "proof_hash": "a1b2c3d4e5f6",
  "proof_search_time_ms": 15.4
}
```

---

### Analytics & Patterns

Analyze debate patterns and agent behavior.

#### GET /api/analytics/disagreements
Get analysis of agent disagreement patterns.

**Parameters:**
- `limit` (int, default=20, max=100): Maximum entries

**Response:**
```json
{
  "patterns": [
    {
      "topic": "Error handling strategies",
      "agents": ["anthropic-api", "gemini"],
      "disagreement_rate": 0.73,
      "debates_count": 8
    }
  ]
}
```

#### GET /api/analytics/role-rotation
Get role rotation analysis across debates.

**Parameters:**
- `limit` (int, default=50, max=200): Maximum entries

#### GET /api/analytics/early-stops
Get early termination signals and patterns.

**Parameters:**
- `limit` (int, default=20, max=100): Maximum entries

---

### Agent Network & Relationships

Analyze agent relationships based on debate history.

#### GET /api/agent/:name/network
Get agent's relationship network with other agents.

**Response:**
```json
{
  "agent": "anthropic-api",
  "connections": [
    {"agent": "gemini", "relationship": "rival", "strength": 0.8},
    {"agent": "deepseek", "relationship": "ally", "strength": 0.65}
  ]
}
```

#### GET /api/agent/:name/rivals
Get agent's top rivals (agents they often disagree with).

**Parameters:**
- `limit` (int, default=5, max=20): Maximum rivals

#### GET /api/agent/:name/allies
Get agent's top allies (agents they often agree with).

**Parameters:**
- `limit` (int, default=5, max=20): Maximum allies

#### GET /api/agent/:name/positions
Get agent's historical positions on topics.

**Parameters:**
- `limit` (int, default=50, max=200): Maximum positions

---

### Laboratory & Emergent Traits

Track emergent agent behaviors and traits.

#### GET /api/laboratory/emergent-traits
Get emergent traits discovered across agents.

**Parameters:**
- `min_confidence` (float, default=0.5): Minimum confidence threshold
- `limit` (int, default=10, max=50): Maximum traits

**Response:**
```json
{
  "traits": [
    {
      "trait": "contrarian_stance",
      "agents": ["grok"],
      "confidence": 0.82,
      "evidence_count": 15
    }
  ]
}
```

#### POST /api/laboratory/cross-pollinations/suggest
Suggest trait cross-pollination between agents.

---

### Belief Network

Analyze claim dependencies and belief propagation.

#### GET /api/belief-network/:debate_id/cruxes
Get debate cruxes (key disagreement points).

**Parameters:**
- `top_k` (int, default=3, max=10): Number of cruxes to return

**Response:**
```json
{
  "debate_id": "debate-123",
  "cruxes": [
    {
      "claim": "Performance matters more than readability",
      "centrality": 0.85,
      "agents_for": ["gemini"],
      "agents_against": ["anthropic-api"]
    }
  ]
}
```

#### GET /api/belief-network/:debate_id/load-bearing-claims
Get claims that most influence the debate outcome.

**Parameters:**
- `limit` (int, default=5, max=20): Maximum claims

---

### Tournaments

Agent tournament management.

#### GET /api/tournaments
List tournaments.

**Response:**
```json
{
  "tournaments": [
    {
      "id": "t-001",
      "name": "Weekly Championship",
      "status": "in_progress",
      "participants": 8
    }
  ]
}
```

#### GET /api/tournaments/:id/standings
Get tournament standings and bracket.

---

### Modes

Available stress-test and interaction modes.

#### GET /api/modes
List available modes.

**Response:**
```json
{
  "modes": [
    {"name": "standard", "description": "Standard decision stress-test (multi-agent debate engine)"},
    {"name": "adversarial", "description": "Red-team adversarial mode"},
    {"name": "consensus", "description": "Consensus-building mode"}
  ]
}
```

---

### Routing & Team Selection

Agent selection and team composition.

#### GET /api/routing/best-teams
Get best performing agent team combinations.

**Parameters:**
- `min_debates` (int, default=3, max=20): Minimum debates together
- `limit` (int, default=10, max=50): Maximum teams

**Response:**
```json
{
  "teams": [
    {
      "agents": ["anthropic-api", "gemini", "deepseek"],
      "win_rate": 0.85,
      "debates": 12,
      "avg_confidence": 0.82
    }
  ]
}
```

#### POST /api/routing/recommendations
Get agent routing recommendations for a topic.

**Request Body:**
```json
{
  "topic": "API security design",
  "required_count": 3
}
```

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "error": "Description of the error"
}
```

Common HTTP status codes:
- `400` - Bad request (invalid parameters)
- `403` - Forbidden (access denied)
- `404` - Not found
- `500` - Internal server error

---

## CORS Policy

The API allows cross-origin requests from:
- `http://localhost:3000`
- `http://localhost:8080`
- `https://aragora.ai`
- `https://www.aragora.ai`

Other origins are blocked by the browser.

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| General API | 60 req/min per token |
| Document upload | 10 req/min |
| WebSocket | Unlimited messages |

---

## Security Notes

1. **Path traversal protection**: All file paths are validated to prevent directory traversal attacks
2. **Input validation**: All integer/float parameters have bounds checking
3. **Error sanitization**: API keys and tokens are redacted from error messages
4. **Origin validation**: CORS uses allowlist instead of wildcard
5. **SQL injection prevention**: LIKE patterns are escaped to prevent wildcard injection
6. **Rate limiting**: Expensive endpoints (debate creation, uploads) are rate limited
7. **Query bounds**: Maximum 10 agents per debate, 10 parts per multipart upload
8. **Database timeouts**: SQLite connections have 30-second timeout to prevent deadlocks
9. **Content-Length validation**: Headers validated to prevent integer parsing attacks

---

## Python Module APIs

The following sections document the Python APIs for extending Aragora.

### Plugin System (`aragora.plugins`)

The plugin system provides a sandboxed execution environment for code analysis, linting, and security scanning extensions.

#### PluginManifest

Defines plugin metadata and capabilities.

```python
from aragora.plugins.manifest import PluginManifest, PluginCapability, PluginRequirement

manifest = PluginManifest(
    name="my-linter",
    version="1.0.0",
    description="Custom code linter",
    entry_point="my_linter:run",  # module:function format
    capabilities=[PluginCapability.LINT, PluginCapability.CODE_ANALYSIS],
    requirements=[PluginRequirement.READ_FILES],
    timeout_seconds=30.0,
    tags=["python", "lint"],
)

# Validate manifest
valid, errors = manifest.validate()
```

**PluginCapability Enum:**
- `CODE_ANALYSIS` - Analyze code structure
- `LINT` - Check code style/issues
- `SECURITY_SCAN` - Security vulnerability detection
- `FORMAT` - Code formatting
- `TEST` - Test execution

**PluginRequirement Enum:**
- `READ_FILES` - Read file access
- `WRITE_FILES` - Write file access
- `NETWORK` - Network access
- `SUBPROCESS` - Subprocess execution

#### PluginRunner

Executes plugins in a sandboxed environment with restricted builtins.

```python
from aragora.plugins.runner import PluginRunner, PluginContext

runner = PluginRunner(manifest)

# Create execution context
ctx = PluginContext(
    working_dir="/path/to/project",
    input_data={"files": ["main.py", "utils.py"]},
)
ctx.allowed_operations = {"read_files"}

# Run plugin
result = await runner.run(ctx, timeout_override=60.0)

if result.success:
    print(result.output)
else:
    print(result.errors)
```

**Security Features:**
- Restricted builtins (no `exec`, `eval`, `compile`, `__import__`, `open`)
- Path traversal prevention (cannot access parent directories)
- Configurable timeouts
- Capability-based permissions

#### PluginRegistry

Manages plugin discovery and instantiation.

```python
from aragora.plugins.runner import get_registry, run_plugin

# Get global registry
registry = get_registry()

# List all plugins
plugins = registry.list_plugins()

# Get plugins by capability
lint_plugins = registry.list_by_capability(PluginCapability.LINT)

# Run a plugin by name
result = await run_plugin("lint", {"files": ["main.py"]})
```

---

### Genesis System (`aragora.genesis`)

The Genesis system implements evolutionary agent algorithms with genetic operators and provenance tracking.

#### AgentGenome

Represents an agent's genetic makeup with traits, expertise, and fitness tracking.

```python
from aragora.genesis import AgentGenome, generate_genome_id

# Create a genome
genome = AgentGenome(
    genome_id=generate_genome_id(
        traits={"analytical": 0.8, "creative": 0.6},
        expertise={"security": 0.9},
        parents=[]
    ),
    name="security-specialist-v1",
    traits={"analytical": 0.8, "creative": 0.6},
    expertise={"security": 0.9, "backend": 0.7},
    model_preference="anthropic-api",
    generation=0,
    fitness_score=0.5,
)

# Create from existing Persona
genome = AgentGenome.from_persona(persona, model="gemini")

# Convert back to Persona for debate use
persona = genome.to_persona()

# Update fitness based on debate outcome
genome.update_fitness(
    consensus_win=True,
    critique_accepted=True,
    prediction_correct=False
)

# Calculate genetic similarity (0-1)
similarity = genome1.similarity_to(genome2)
```

#### GenomeStore

SQLite-based persistence for genomes.

```python
from aragora.genesis import GenomeStore

store = GenomeStore(db_path=".nomic/genesis.db")

# Save genome
store.save(genome)

# Retrieve by ID
genome = store.get("abc123def456")

# Get by name (returns latest generation)
genome = store.get_by_name("security-specialist")

# Get top performers
top_10 = store.get_top_by_fitness(n=10)

# Get lineage (ancestors)
lineage = store.get_lineage(genome_id)  # [child, parent, grandparent, ...]
```

#### GenomeBreeder

Genetic operators for evolving agent populations.

```python
from aragora.genesis import GenomeBreeder

breeder = GenomeBreeder(
    mutation_rate=0.1,      # Probability of mutating each trait
    crossover_ratio=0.5,    # Blend ratio (0.5 = equal parents)
    elite_ratio=0.2,        # Fraction preserved unchanged
)

# Crossover: blend two parents
child = breeder.crossover(
    parent_a=genome1,
    parent_b=genome2,
    name="hybrid-agent",
    debate_id="debate-123"
)

# Mutation: random modifications
mutated = breeder.mutate(genome, rate=0.2)

# Spawn specialist: create domain-focused agent
specialist = breeder.spawn_specialist(
    domain="security",
    parent_pool=[genome1, genome2, genome3],
    debate_id="debate-123"
)
```

#### Population

Collection of genomes with aggregate statistics.

```python
from aragora.genesis import Population

pop = Population(
    population_id="gen-5",
    genomes=[genome1, genome2, genome3],
    generation=5,
)

print(f"Size: {pop.size}")
print(f"Average fitness: {pop.average_fitness:.2f}")
print(f"Best: {pop.best_genome.name}")

# Find by ID
genome = pop.get_by_id("abc123")
```

#### GenesisLedger

Immutable event log with cryptographic hashing.

```python
from aragora.genesis import GenesisLedger, GenesisEvent, GenesisEventType

ledger = GenesisLedger(db_path=".nomic/genesis.db")

# Events are automatically hashed and linked
# Common event types:
# - DEBATE_START, DEBATE_END, DEBATE_SPAWN, DEBATE_MERGE
# - CONSENSUS_REACHED, TENSION_DETECTED, TENSION_RESOLVED
# - AGENT_BIRTH, AGENT_DEATH, AGENT_MUTATION, AGENT_CROSSOVER
# - FITNESS_UPDATE, POPULATION_EVOLVED, GENERATION_ADVANCE
```

#### FractalTree

Tree structure for nested sub-debates.

```python
from aragora.genesis import FractalTree

tree = FractalTree(root_id="main-debate")
tree.add_node("main-debate", parent_id=None, depth=0, success=True)
tree.add_node("sub-1", parent_id="main-debate", tension="scope", depth=1)
tree.add_node("sub-2", parent_id="main-debate", tension="definition", depth=1)

children = tree.get_children("main-debate")  # ["sub-1", "sub-2"]
nested_dict = tree.to_dict()  # Recursive structure
```

---

### Evolution System (`aragora.evolution`)

Prompt evolution enables agents to improve their system prompts based on successful debate patterns.

#### PromptEvolver

Main class for evolving agent prompts.

```python
from aragora.evolution import PromptEvolver, EvolutionStrategy

evolver = PromptEvolver(
    db_path="aragora_evolution.db",
    strategy=EvolutionStrategy.HYBRID,
)

# Extract patterns from successful debates
patterns = evolver.extract_winning_patterns(
    debates=recent_debates,
    min_confidence=0.6,
)

# Store patterns for future use
evolver.store_patterns(patterns)

# Get most effective patterns
top_patterns = evolver.get_top_patterns(
    pattern_type="issue_identification",
    limit=10,
)

# Evolve an agent's prompt
new_prompt = evolver.evolve_prompt(
    agent=my_agent,
    patterns=top_patterns,
    strategy=EvolutionStrategy.APPEND,
)

# Apply evolution and save version
evolver.apply_evolution(agent, patterns)

# Track performance
evolver.update_performance(
    agent_name="anthropic-api",
    version=3,
    debate_result=result,
)
```

#### EvolutionStrategy

Available strategies for prompt evolution:

```python
from aragora.evolution import EvolutionStrategy

# APPEND: Add new learnings section to existing prompt
# REPLACE: Replace old learnings section with new patterns
# REFINE: Use LLM to synthesize patterns into coherent prompt
# HYBRID: Append first, refine if prompt exceeds 2000 chars
```

#### Prompt Versioning

Track prompt versions and their performance:

```python
# Save a new version
version = evolver.save_prompt_version(
    agent_name="anthropic-api",
    prompt="You are a helpful assistant...",
    metadata={"source": "manual", "note": "Added security focus"},
)

# Get specific version
v1 = evolver.get_prompt_version("anthropic-api", version=1)

# Get latest version
latest = evolver.get_prompt_version("anthropic-api")

# Get evolution history
history = evolver.get_evolution_history("anthropic-api", limit=10)
# Returns: [{"from_version": 2, "to_version": 3, "strategy": "append", ...}, ...]
```

---

## Breakpoints API

Human-in-the-loop breakpoint management for debate supervision.

### List Pending Breakpoints

```http
GET /api/breakpoints/pending
```

Returns all breakpoints awaiting human resolution.

**Response:**
```json
{
  "breakpoints": [
    {
      "id": "bp_abc123",
      "debate_id": "debate_xyz",
      "type": "consensus_uncertain",
      "created_at": "2026-01-09T10:00:00Z",
      "context": {
        "agents_involved": ["anthropic-api", "openai-api"],
        "disagreement_score": 0.85
      }
    }
  ]
}
```

### Get Breakpoint Status

```http
GET /api/breakpoints/:id/status
```

Returns the current status of a specific breakpoint.

### Resolve Breakpoint

```http
POST /api/breakpoints/:id/resolve
```

Resolve a pending breakpoint with human guidance.

**Request Body:**
```json
{
  "resolution": "continue",
  "guidance": "The agents should focus on practical implementation",
  "override_winner": null
}
```

---

## Introspection API

Agent self-awareness and reputation metrics.

### Get All Agent Introspection

```http
GET /api/introspection/all
```

Returns introspection data for all agents.

### Get Introspection Leaderboard

```http
GET /api/introspection/leaderboard
```

Returns agents ranked by reputation score.

**Response:**
```json
{
  "rankings": [
    {
      "agent": "anthropic-api",
      "reputation_score": 0.92,
      "consistency": 0.88,
      "win_rate": 0.67
    }
  ]
}
```

### List Available Agents

```http
GET /api/introspection/agents
```

Returns list of agents available for introspection.

### Get Agent Availability

```http
GET /api/introspection/agents/availability
```

Returns credential availability for known agent types.

### Get Agent Introspection

```http
GET /api/introspection/agents/:name
```

Returns detailed introspection for a specific agent.

---

## Gallery API

Public debate gallery for sharing and embedding.

### List Public Debates

```http
GET /api/gallery
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 20 | Max debates to return |
| `offset` | int | 0 | Pagination offset |
| `agent` | string | - | Filter by agent name |

**Response:**
```json
{
  "debates": [
    {
      "id": "gallery_abc123",
      "title": "Should AI systems be open-sourced?",
      "agents": ["anthropic-api", "openai-api"],
      "winner": "anthropic-api",
      "created_at": "2026-01-09T10:00:00Z",
      "view_count": 1234
    }
  ],
  "total": 156,
  "has_more": true
}
```

### Get Public Debate

```http
GET /api/gallery/:id
```

Returns full debate history for a public debate.

### Get Embeddable Summary

```http
GET /api/gallery/:id/embed
```

Returns an embeddable summary suitable for sharing.

**Response:**
```json
{
  "embed_html": "<div class='aragora-embed'>...</div>",
  "og_tags": {
    "title": "AI Debate: Open Source AI",
    "description": "Claude vs GPT-4 debate on open-source AI",
    "image": "https://api.aragora.ai/og/gallery_abc123.png"
  }
}
```

---

## Billing API

Subscription and usage management (requires authentication).

### List Plans

```http
GET /api/billing/plans
```

Returns available subscription plans with features and pricing.

**Response:**
```json
{
  "plans": [
    {
      "id": "free",
      "name": "Free",
      "price": 0,
      "debates_per_month": 10,
      "features": ["basic_agents", "public_gallery"]
    },
    {
      "id": "pro",
      "name": "Pro",
      "price": 29,
      "debates_per_month": 500,
      "features": ["all_agents", "private_debates", "api_access"]
    }
  ]
}
```

### Get Current Usage

```http
GET /api/billing/usage
```

Returns current usage for the authenticated user.

**Response:**
```json
{
  "debates_used": 45,
  "debates_limit": 500,
  "api_calls_used": 1234,
  "api_calls_limit": 10000,
  "period_ends": "2026-02-01T00:00:00Z"
}
```

### Get Subscription Status

```http
GET /api/billing/subscription
```

Returns current subscription details.

### Create Checkout Session

```http
POST /api/billing/checkout
```

Create a Stripe checkout session for plan upgrade.

**Request Body:**
```json
{
  "plan_id": "pro",
  "success_url": "https://aragora.ai/billing/success",
  "cancel_url": "https://aragora.ai/billing/cancel"
}
```

**Response:**
```json
{
  "checkout_url": "https://checkout.stripe.com/..."
}
```

### Create Billing Portal Session

```http
POST /api/billing/portal
```

Create a Stripe billing portal session for subscription management.

### Cancel Subscription

```http
POST /api/billing/cancel
```

Cancel subscription at end of current billing period.

### Resume Subscription

```http
POST /api/billing/resume
```

Resume a previously canceled subscription.

### Stripe Webhook

```http
POST /api/webhooks/stripe
```

Handle Stripe webhook events (subscription updates, payment events).

---

## Usage Metering API

Enterprise usage metering endpoints for tracking consumption and quotas.

### Get Usage Summary

```http
GET /api/v1/billing/usage
GET /api/v1/billing/usage/summary
Authorization: Bearer <token>
```

Query Parameters:
- `period`: Billing period (`hour`, `day`, `week`, `month`, `quarter`, `year`). Default: `month`

Returns current usage for the authenticated user's organization.

**Response:**
```json
{
  "usage": {
    "period_start": "2026-01-01T00:00:00Z",
    "period_end": "2026-01-31T23:59:59Z",
    "period_type": "month",
    "tokens": {
      "input": 500000,
      "output": 250000,
      "total": 750000,
      "cost": "12.50"
    },
    "counts": {
      "debates": 45,
      "api_calls": 1500
    },
    "by_provider": {...},
    "limits": {...},
    "usage_percent": {...}
  }
}
```

### Get Usage Breakdown

```http
GET /api/v1/billing/usage/breakdown
Authorization: Bearer <token>
```

Query Parameters:
- `start`: Start date (ISO format)
- `end`: End date (ISO format)

Returns detailed usage breakdown by model, provider, and day.

**Response:**
```json
{
  "breakdown": {
    "totals": {
      "cost": "125.50",
      "tokens": 5000000,
      "debates": 150,
      "api_calls": 5000
    },
    "by_model": [...],
    "by_provider": [...],
    "by_day": [...],
    "by_user": [...]
  }
}
```

### Get Limits

```http
GET /api/v1/billing/limits
Authorization: Bearer <token>
```

Returns current tier limits and utilization percentages.

**Response:**
```json
{
  "limits": {
    "tier": "enterprise_plus",
    "limits": {
      "tokens": 999999999,
      "debates": 999999,
      "api_calls": 999999
    },
    "used": {
      "tokens": 750000,
      "debates": 45,
      "api_calls": 1500
    },
    "percent": {
      "tokens": 0.075,
      "debates": 0.0045,
      "api_calls": 0.15
    },
    "exceeded": {
      "tokens": false,
      "debates": false,
      "api_calls": false
    }
  }
}
```

### Get Quota Status

```http
GET /api/v1/quotas
Authorization: Bearer <token>
```

Returns current quota status for all resources using the unified QuotaManager.

**Response:**
```json
{
  "quotas": {
    "debates": {
      "limit": 100,
      "current": 45,
      "remaining": 55,
      "period": "day",
      "percentage_used": 45.0,
      "is_exceeded": false,
      "is_warning": false,
      "resets_at": "2026-01-24T00:00:00Z"
    },
    "api_requests": {...},
    "tokens": {...},
    "storage_bytes": {...},
    "knowledge_bytes": {...}
  }
}
```

### Export Usage

```http
GET /api/v1/billing/usage/export
Authorization: Bearer <token>
```

Query Parameters:
- `start`: Start date (ISO format)
- `end`: End date (ISO format)
- `format`: Export format (`csv` or `json`). Default: `csv`

Returns usage data as downloadable CSV or JSON.

---

## SME Usage Dashboard API

Comprehensive usage visibility and ROI tracking for SME users.

### Get Usage Summary

```http
GET /api/v1/usage/summary
Authorization: Bearer <token>
```

Query Parameters:
- `period`: Time period (`hour`, `day`, `week`, `month`, `quarter`, `year`). Default: `month`
- `start`: Custom start date (ISO format)
- `end`: Custom end date (ISO format)

Returns unified usage metrics including debates, costs, tokens, and activity.

**Response:**
```json
{
  "summary": {
    "period": {
      "type": "month",
      "start": "2025-12-27T00:00:00Z",
      "end": "2026-01-26T23:59:59Z",
      "days": 30
    },
    "debates": {
      "total": 45,
      "completed": 40,
      "consensus_rate": 85.5
    },
    "costs": {
      "total_usd": "12.50",
      "avg_per_debate_usd": "0.28",
      "by_provider": {
        "anthropic": "8.50",
        "openai": "4.00"
      }
    },
    "tokens": {
      "total": 750000,
      "input": 500000,
      "output": 250000
    },
    "activity": {
      "active_days": 15,
      "debates_per_day": 1.5,
      "api_calls": 1500
    }
  }
}
```

### Get Usage Breakdown

```http
GET /api/v1/usage/breakdown
Authorization: Bearer <token>
```

Query Parameters:
- `dimension`: Breakdown dimension (`agent`, `model`, `day`, `debate`). Default: `agent`
- `period`: Time period
- `start`: Custom start date
- `end`: Custom end date

Returns detailed usage breakdown by the specified dimension.

**Response:**
```json
{
  "breakdown": {
    "dimension": "agent",
    "period": {
      "start": "2025-12-27T00:00:00Z",
      "end": "2026-01-26T23:59:59Z"
    },
    "items": [
      {
        "name": "claude",
        "cost_usd": "8.50",
        "percentage": 68.0
      },
      {
        "name": "gpt-4",
        "cost_usd": "4.00",
        "percentage": 32.0
      }
    ]
  }
}
```

### Get ROI Metrics

```http
GET /api/v1/usage/roi
Authorization: Bearer <token>
```

Query Parameters:
- `benchmark`: Industry benchmark (`sme`, `enterprise`, `tech_startup`, `consulting`). Default: `sme`
- `period`: Time period
- `hourly_rate`: Override hourly rate assumption (USD)

Returns ROI analysis comparing AI-assisted decisions with traditional methods.

**Response:**
```json
{
  "roi": {
    "period": {
      "start": "2025-12-27T00:00:00Z",
      "end": "2026-01-26T23:59:59Z"
    },
    "time_savings": {
      "total_hours_saved": 45.0,
      "avg_hours_per_debate": 1.5,
      "value_of_time_saved_usd": "3375.00"
    },
    "cost": {
      "total_ai_cost_usd": "12.50",
      "avg_cost_per_debate_usd": "0.28",
      "traditional_cost_estimate_usd": "3500.00"
    },
    "roi": {
      "percentage": 26900,
      "net_savings_usd": "3362.50",
      "payback_period_debates": 1
    },
    "quality": {
      "consensus_rate": 85.5,
      "avg_confidence": 0.87,
      "decisions_with_high_confidence": 38
    },
    "productivity": {
      "debates_per_active_day": 3.0,
      "time_per_decision_minutes": 5.2,
      "traditional_time_per_decision_hours": 4.0
    },
    "benchmark": {
      "name": "sme",
      "hourly_rate_usd": "75.00",
      "avg_decision_cost_usd": "300.00",
      "avg_hours_per_decision": 4.0
    }
  }
}
```

### Get Budget Status

```http
GET /api/v1/usage/budget-status
Authorization: Bearer <token>
```

Returns current budget utilization and projections.

**Response:**
```json
{
  "budget": {
    "monthly": {
      "limit_usd": "100.00",
      "spent_usd": "45.50",
      "remaining_usd": "54.50",
      "percent_used": 45.5,
      "days_remaining": 15,
      "projected_end_spend_usd": "91.00"
    },
    "daily": {
      "limit_usd": "10.00",
      "spent_usd": "1.50"
    },
    "alert_level": null
  }
}
```

### Get Usage Forecast

```http
GET /api/v1/usage/forecast
Authorization: Bearer <token>
```

Query Parameters:
- `benchmark`: Industry benchmark for ROI projections

Returns usage forecast based on current patterns.

**Response:**
```json
{
  "forecast": {
    "projected_monthly_debates": 60,
    "projected_monthly_cost_usd": "16.80",
    "projected_time_savings_hours": 60.0,
    "projected_roi_percentage": 28000,
    "confidence": 0.85,
    "recommendations": [
      "Current usage pattern is efficient",
      "Consider increasing debate usage for higher ROI"
    ]
  }
}
```

### Get Industry Benchmarks

```http
GET /api/v1/usage/benchmarks
Authorization: Bearer <token>
```

Returns industry benchmark comparison data.

**Response:**
```json
{
  "benchmarks": {
    "sme": {
      "name": "Small/Medium Enterprise",
      "hourly_rate_usd": "75.00",
      "avg_decision_cost_usd": "300.00",
      "avg_hours_per_decision": 4.0,
      "avg_participants": 3
    },
    "enterprise": {
      "name": "Enterprise",
      "hourly_rate_usd": "150.00",
      "avg_decision_cost_usd": "1200.00",
      "avg_hours_per_decision": 8.0,
      "avg_participants": 5
    },
    "tech_startup": {
      "name": "Tech Startup",
      "hourly_rate_usd": "100.00",
      "avg_decision_cost_usd": "400.00",
      "avg_hours_per_decision": 4.0,
      "avg_participants": 4
    },
    "consulting": {
      "name": "Consulting",
      "hourly_rate_usd": "250.00",
      "avg_decision_cost_usd": "2000.00",
      "avg_hours_per_decision": 8.0,
      "avg_participants": 4
    }
  }
}
```

### Export Usage Data

```http
GET /api/v1/usage/export
Authorization: Bearer <token>
```

Query Parameters:
- `format`: Export format (`csv`, `json`, `pdf`). Default: `csv`
- `period`: Time period
- `start`: Custom start date
- `end`: Custom end date
- `include_roi`: Include ROI metrics (`true`/`false`). Default: `false`

Returns usage data as downloadable file.

**Response (JSON format):**
```json
{
  "organization": "My Company",
  "period": {
    "start": "2025-12-27T00:00:00Z",
    "end": "2026-01-26T23:59:59Z"
  },
  "totals": {
    "cost_usd": "12.50",
    "tokens": 750000,
    "api_calls": 1500
  },
  "by_agent": {
    "claude": "8.50",
    "gpt-4": "4.00"
  },
  "by_model": {
    "claude-3-opus": "5.00",
    "claude-3-sonnet": "3.50",
    "gpt-4-turbo": "4.00"
  },
  "roi": {
    "time_saved_hours": 45.0,
    "net_savings_usd": "3362.50"
  }
}
```

---

## Job Queue API

Background job queue management for long-running tasks.

### Submit Job

```http
POST /api/queue/jobs
Authorization: Bearer <token>
Content-Type: application/json

{
  "type": "debate_export",
  "payload": {
    "debate_id": "debate-123",
    "format": "json"
  },
  "priority": "normal"
}
```

Response:
```json
{
  "job_id": "job-abc123",
  "status": "pending",
  "position": 3
}
```

### List Jobs

```http
GET /api/queue/jobs?status=pending&limit=20
```

Query parameters:
- `status`: Filter by status (`pending`, `running`, `completed`, `failed`)
- `type`: Filter by job type
- `limit`: Max results (default 50)
- `offset`: Pagination offset

### Get Job Status

```http
GET /api/queue/jobs/\{job_id\}
```

Response:
```json
{
  "job_id": "job-abc123",
  "type": "debate_export",
  "status": "running",
  "progress": 45,
  "created_at": "2026-01-18T10:00:00Z",
  "started_at": "2026-01-18T10:00:05Z"
}
```

### Retry Failed Job

```http
POST /api/queue/jobs/\{job_id\}/retry
Authorization: Bearer <token>
```

### Cancel Job

```http
DELETE /api/queue/jobs/\{job_id\}
Authorization: Bearer <token>
```

### Queue Statistics

```http
GET /api/queue/stats
```

Response:
```json
{
  "pending": 12,
  "running": 3,
  "completed_24h": 156,
  "failed_24h": 2,
  "avg_wait_time_ms": 1250,
  "avg_processing_time_ms": 4500
}
```

### Worker Status

```http
GET /api/queue/workers
```

Response:
```json
{
  "workers": [
    {
      "id": "worker-1",
      "status": "busy",
      "current_job": "job-abc123",
      "jobs_completed": 42
    }
  ]
}
```

---

## Moments API

Track and query significant debate moments (upsets, reversals, breakthroughs).

### Get Moments Summary

```http
GET /api/moments/summary
```

Response:
```json
{
  "total_moments": 156,
  "by_type": {
    "upset_victory": 23,
    "position_reversal": 18,
    "consensus_breakthrough": 45,
    "calibration_vindication": 12,
    "alliance_shift": 8,
    "streak_achievement": 30,
    "domain_mastery": 20
  },
  "recent_count_24h": 12
}
```

### Get Moments Timeline

```http
GET /api/moments/timeline?limit=50&offset=0
```

Response:
```json
{
  "moments": [
    {
      "id": "moment-123",
      "type": "upset_victory",
      "debate_id": "debate-456",
      "agent": "claude-3",
      "description": "Won against higher-rated opponent",
      "significance": 0.85,
      "timestamp": "2026-01-18T10:30:00Z"
    }
  ],
  "total": 156
}
```

### Get Trending Moments

```http
GET /api/moments/trending?limit=10
```

Returns most significant recent moments.

### Get Moments by Type

```http
GET /api/moments/by-type/\{type\}
```

Valid types: `upset_victory`, `position_reversal`, `calibration_vindication`, `alliance_shift`, `consensus_breakthrough`, `streak_achievement`, `domain_mastery`

---

## Checkpoint API

Pause, checkpoint, and resume debates.

### List Checkpoints

```http
GET /api/checkpoints?debate_id=abc123&limit=20
```

Response:
```json
{
  "checkpoints": [
    {
      "id": "cp-123",
      "debate_id": "debate-456",
      "round": 3,
      "created_at": "2026-01-18T10:00:00Z",
      "reason": "manual_pause",
      "resumable": true
    }
  ]
}
```

### Get Resumable Checkpoints

```http
GET /api/checkpoints/resumable
```

Returns checkpoints that can be resumed.

### Get Checkpoint Details

```http
GET /api/checkpoints/\{id\}
```

Response:
```json
{
  "id": "cp-123",
  "debate_id": "debate-456",
  "round": 3,
  "state": {
    "current_round": 3,
    "agents": ["claude-3", "gpt-4"],
    "votes": {"claude-3": 2, "gpt-4": 1}
  },
  "created_at": "2026-01-18T10:00:00Z",
  "resumable": true
}
```

### Resume from Checkpoint

```http
POST /api/checkpoints/\{id\}/resume
Authorization: Bearer <token>
```

Resumes a paused debate from the checkpoint state.

### Delete Checkpoint

```http
DELETE /api/checkpoints/\{id\}
Authorization: Bearer <token>
```

### Create Checkpoint for Debate

```http
POST /api/debates/\{id\}/checkpoint
Authorization: Bearer <token>
Content-Type: application/json

{
  "reason": "user_requested"
}
```

### Pause Debate

```http
POST /api/debates/\{id\}/pause
Authorization: Bearer <token>
```

Pauses a running debate and creates a checkpoint automatically.

---

## Workspace API (Enterprise)

Multi-tenant workspace management with data isolation.

### Create Workspace

```http
POST /api/workspaces
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Engineering Team",
  "description": "Workspace for engineering debates",
  "settings": {
    "default_retention_days": 90,
    "require_approval": true
  }
}
```

### List Workspaces

```http
GET /api/workspaces
Authorization: Bearer <token>
```

### Get Workspace Details

```http
GET /api/workspaces/\{id\}
Authorization: Bearer <token>
```

### Delete Workspace

```http
DELETE /api/workspaces/\{id\}
Authorization: Bearer <token>
```

### Add Workspace Member

```http
POST /api/workspaces/\{id\}/members
Authorization: Bearer <token>
Content-Type: application/json

{
  "user_id": "user-123",
  "role": "member",
  "permissions": ["read", "write"]
}
```

### Remove Workspace Member

```http
DELETE /api/workspaces/\{id\}/members/\{user_id\}
Authorization: Bearer <token>
```

### Retention Policies

```http
GET /api/retention/policies
POST /api/retention/policies
PUT /api/retention/policies/\{id\}
DELETE /api/retention/policies/\{id\}
POST /api/retention/policies/\{id\}/execute
GET /api/retention/expiring
```

### Content Classification

```http
POST /api/classify
Content-Type: application/json

{
  "content": "Debate transcript text...",
  "context": "internal_review"
}
```

Response:
```json
{
  "level": "confidential",
  "confidence": 0.92,
  "reasons": ["contains_internal_data"]
}
```

### Audit Log

```http
GET /api/audit/entries?actor=user-123&action=read&limit=100
GET /api/audit/report?start=2026-01-01&end=2026-01-18
GET /api/audit/verify
```

SOC 2 Controls: CC6.1, CC6.3 - Logical access controls

---

## Privacy API (GDPR/CCPA)

Data export and account deletion for regulatory compliance.

### Export User Data

```http
GET /api/v1/privacy/export
Authorization: Bearer <token>
```

GDPR Article 15, CCPA Right to Know. Exports all user data.

Response:
```json
{
  "export_id": "export-123",
  "status": "processing",
  "estimated_completion": "2026-01-18T10:30:00Z"
}
```

### Get Data Inventory

```http
GET /api/v1/privacy/data-inventory
Authorization: Bearer <token>
```

Response:
```json
{
  "categories": [
    {
      "name": "debate_history",
      "description": "Your debate participation history",
      "count": 42,
      "retention": "90 days"
    },
    {
      "name": "preferences",
      "description": "Account settings and preferences",
      "count": 1,
      "retention": "Until account deletion"
    }
  ]
}
```

### Delete Account

```http
DELETE /api/v1/privacy/account
Authorization: Bearer <token>
Content-Type: application/json

{
  "password": "your-current-password",
  "confirm": true,
  "reason": "no_longer_needed"
}
```

GDPR Article 17, CCPA Right to Delete.

### Update Privacy Preferences

```http
POST /api/v1/privacy/preferences
Authorization: Bearer <token>
Content-Type: application/json

{
  "do_not_sell": true,
  "marketing_opt_out": false,
  "analytics_opt_out": false,
  "third_party_sharing": true
}
```

CCPA Do Not Sell compliance.

SOC 2 Control: P5-01 - User access to personal data

---

## Training Export API

Export debate data for model fine-tuning.

### Export SFT Data

```http
POST /api/training/export/sft
Authorization: Bearer <token>
Content-Type: application/json

{
  "filters": {
    "min_quality": 0.8,
    "start_date": "2026-01-01",
    "end_date": "2026-01-18"
  },
  "format": "jsonl"
}
```

Supervised Fine-Tuning format export.

### Export DPO Data

```http
POST /api/training/export/dpo
Authorization: Bearer <token>
Content-Type: application/json

{
  "filters": {
    "min_margin": 0.3,
    "include_ties": false
  },
  "format": "jsonl"
}
```

Direct Preference Optimization format with chosen/rejected pairs.

### Export Gauntlet Data

```http
POST /api/training/export/gauntlet
Authorization: Bearer <token>
```

Adversarial training data from gauntlet challenges.

### Get Export Statistics

```http
GET /api/training/stats
```

Response:
```json
{
  "total_debates": 1234,
  "exportable_sft": 890,
  "exportable_dpo": 456,
  "last_export": "2026-01-17T15:00:00Z"
}
```

### List Export Formats

```http
GET /api/training/formats
```

Response:
```json
{
  "formats": [
    {"id": "jsonl", "name": "JSON Lines", "extensions": [".jsonl"]},
    {"id": "parquet", "name": "Apache Parquet", "extensions": [".parquet"]},
    {"id": "csv", "name": "CSV", "extensions": [".csv"]}
  ]
}
```

### Training Jobs

```http
GET /api/training/jobs
POST /api/training/jobs/\{id\}/start
POST /api/training/jobs/\{id\}/complete
GET /api/training/jobs/\{id\}/metrics
GET /api/training/jobs/\{id\}/artifacts
```

---

## Explainability API

Get decision explanations, evidence chains, vote pivots, counterfactuals, and summaries.

### Get Full Explanation

```http
GET /api/v1/debates/\{debate_id\}/explanation
Authorization: Bearer <token>
```

**Query Parameters:**
- `format` (string, default: `json`): `json` or `summary` (Markdown)

**Response (json):**
```json
{
  "decision_id": "dec-abc123",
  "debate_id": "debate-123",
  "conclusion": "Adopt a tiered rate limiting strategy",
  "confidence": 0.87,
  "consensus_reached": true,
  "evidence_chain": [],
  "vote_pivots": [],
  "counterfactuals": [],
  "evidence_quality_score": 0.82
}
```

### Get Evidence Chain

```http
GET /api/v1/debates/\{debate_id\}/evidence
Authorization: Bearer <token>
```

**Query Parameters:**
- `limit` (int, default: 20)
- `min_relevance` (float, default: 0.0)

**Response:**
```json
{
  "debate_id": "debate-123",
  "evidence_count": 5,
  "evidence_quality_score": 0.82,
  "evidence": []
}
```

### Get Vote Pivots

```http
GET /api/v1/debates/\{debate_id\}/votes/pivots
Authorization: Bearer <token>
```

**Query Parameters:**
- `min_influence` (float, default: 0.0)

### Get Counterfactuals

```http
GET /api/v1/debates/\{debate_id\}/counterfactuals
Authorization: Bearer <token>
```

**Query Parameters:**
- `min_sensitivity` (float, default: 0.0)

### Get Summary

```http
GET /api/v1/debates/\{debate_id\}/summary
Authorization: Bearer <token>
```

**Query Parameters:**
- `format` (string, default: `markdown`): `markdown`, `json`, or `html`

### Batch Explainability

Process multiple debates in a single request for efficiency.

#### Create Batch Job

```http
POST /api/v1/explainability/batch
Authorization: Bearer <token>
Content-Type: application/json

{
  "debate_ids": ["debate-1", "debate-2", "debate-3"],
  "options": {
    "include_evidence": true,
    "include_counterfactuals": false,
    "include_vote_pivots": false,
    "format": "full"  // "full", "summary", or "minimal"
  }
}
```

**Response (202 Accepted):**
```json
{
  "batch_id": "batch-a1b2c3d4e5f6",
  "status": "pending",
  "total_debates": 3,
  "status_url": "/api/v1/explainability/batch/batch-a1b2c3d4e5f6/status",
  "results_url": "/api/v1/explainability/batch/batch-a1b2c3d4e5f6/results"
}
```

#### Get Batch Status

```http
GET /api/v1/explainability/batch/\{batch_id\}/status
Authorization: Bearer <token>
```

**Response:**
```json
{
  "batch_id": "batch-a1b2c3d4e5f6",
  "status": "processing",
  "total_debates": 3,
  "processed_count": 2,
  "success_count": 2,
  "error_count": 0,
  "created_at": 1737356400.0,
  "started_at": 1737356401.0,
  "progress_pct": 66.7
}
```

#### Get Batch Results

```http
GET /api/v1/explainability/batch/\{batch_id\}/results
Authorization: Bearer <token>
```

**Query Parameters:**
- `include_partial` (boolean, default: false): Include results while still processing
- `offset` (int, default: 0): Pagination offset
- `limit` (int, default: 50, max: 100): Results per page

**Response:**
```json
{
  "batch_id": "batch-a1b2c3d4e5f6",
  "status": "completed",
  "total_debates": 3,
  "processed_count": 3,
  "success_count": 3,
  "error_count": 0,
  "results": [
    {
      "debate_id": "debate-1",
      "status": "success",
      "processing_time_ms": 125.4,
      "explanation": {
        "confidence": 0.87,
        "consensus_reached": true,
        "contributing_factors": [...]
      }
    }
  ],
  "pagination": {
    "offset": 0,
    "limit": 50,
    "total": 3,
    "has_more": false
  }
}
```

### Compare Explanations

Compare decision factors across multiple debates.

```http
POST /api/v1/explainability/compare
Authorization: Bearer <token>
Content-Type: application/json

{
  "debate_ids": ["debate-1", "debate-2"],
  "compare_fields": ["confidence", "consensus_reached", "contributing_factors", "evidence_quality"]
}
```

**Response:**
```json
{
  "debates_compared": ["debate-1", "debate-2"],
  "comparison": {
    "confidence": {
      "debate-1": 0.87,
      "debate-2": 0.92
    },
    "confidence_stats": {
      "min": 0.87,
      "max": 0.92,
      "avg": 0.895,
      "spread": 0.05
    },
    "consensus_reached": {
      "debate-1": true,
      "debate-2": true
    },
    "consensus_agreement": true,
    "contributing_factors": {
      "evidence_quality": {
        "debate-1": 0.35,
        "debate-2": 0.42
      }
    },
    "common_factors": ["evidence_quality", "argument_strength"]
  }
}
```

---

## Workflow Templates API

Manage and execute reusable workflow templates with pre-built patterns.

### List Workflow Templates

```http
GET /api/workflow/templates
Authorization: Bearer <token>
```

**Query Parameters:**
- `category` (string): Filter by category
- `pattern` (string): Filter by pattern type (hive_mind, map_reduce, review_cycle, pipeline, parallel)
- `search` (string): Search by name or description
- `tags` (string): Filter by tags (comma-separated)
- `limit` (int, default: 50, max: 100)
- `offset` (int, default: 0)

**Response:**
```json
{
  "templates": [
    {
      "id": "security/code-review",
      "name": "Security Code Review",
      "description": "Multi-agent security analysis workflow",
      "category": "security",
      "pattern": "review_cycle",
      "tags": ["security", "code", "audit"]
    }
  ],
  "total": 15,
  "limit": 50,
  "offset": 0
}
```

### Get Template Details

```http
GET /api/workflow/templates/\{template_id\}
Authorization: Bearer <token>
```

### Get Template Package

```http
GET /api/workflow/templates/\{template_id\}/package
Authorization: Bearer <token>
```

**Query Parameters:**
- `include_examples` (boolean, default: true): Include usage examples

**Response:**
```json
{
  "id": "security/code-review",
  "name": "Security Code Review",
  "description": "Multi-agent security analysis workflow",
  "workflow_definition": {
    "nodes": [...],
    "edges": [...],
    "config": {...}
  },
  "input_schema": {
    "type": "object",
    "properties": {
      "code_path": {"type": "string"},
      "severity_threshold": {"type": "string", "enum": ["low", "medium", "high"]}
    }
  },
  "output_schema": {...},
  "documentation": "# Security Code Review\n\nThis workflow...",
  "examples": [
    {
      "name": "Basic usage",
      "inputs": {"code_path": "src/auth.py"},
      "description": "Review authentication module"
    }
  ],
  "version": "1.2.0"
}
```

### Run Workflow Template

```http
POST /api/workflow/templates/\{template_id\}/run
Authorization: Bearer <token>
Content-Type: application/json

{
  "inputs": {
    "code_path": "src/api/handlers.py",
    "severity_threshold": "medium"
  },
  "config": {
    "timeout": 300,
    "priority": "high",
    "async": false
  },
  "workspace_id": "ws-123"
}
```

**Response (sync):**
```json
{
  "execution_id": "exec-456",
  "status": "completed",
  "result": {
    "findings": [...],
    "summary": "Found 3 potential vulnerabilities"
  },
  "duration_ms": 45200
}
```

**Response (async):**
```json
{
  "execution_id": "exec-456",
  "status": "running",
  "status_url": "/api/workflow-executions/exec-456"
}
```

### List Template Categories

```http
GET /api/workflow/categories
```

**Response:**
```json
{
  "categories": [
    {
      "id": "security",
      "name": "Security",
      "description": "Security analysis workflows",
      "template_count": 8,
      "icon": "shield"
    },
    {
      "id": "research",
      "name": "Research",
      "description": "Research and analysis workflows",
      "template_count": 12,
      "icon": "search"
    }
  ]
}
```

### List Workflow Patterns

```http
GET /api/workflow/patterns
```

**Response:**
```json
{
  "patterns": [
    {
      "id": "hive_mind",
      "name": "Hive Mind",
      "description": "Parallel agent consultation with aggregation",
      "available": true,
      "use_cases": ["Research", "Brainstorming", "Consensus building"]
    },
    {
      "id": "map_reduce",
      "name": "Map-Reduce",
      "description": "Distribute work, combine results",
      "available": true,
      "use_cases": ["Large document analysis", "Batch processing"]
    }
  ]
}
```

### Instantiate Pattern

```http
POST /api/workflow/patterns/\{pattern_id\}/instantiate
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "My Security Review",
  "description": "Custom security review workflow",
  "category": "security",
  "config": {
    "max_agents": 5,
    "consensus_threshold": 0.7
  },
  "agents": ["anthropic-api", "openai-api", "mistral-api"]
}
```

---

## Gauntlet Receipts API

Access and export gauntlet verification receipts with cryptographic integrity verification.

### List Gauntlet Receipts

```http
GET /api/gauntlet/receipts
Authorization: Bearer <token>
```

**Query Parameters:**
- `verdict` (string): Filter by verdict (pass, fail, warn)
- `from_date` (string): Start date (ISO 8601)
- `to_date` (string): End date (ISO 8601)
- `limit` (int, default: 50)
- `offset` (int, default: 0)

**Response:**
```json
{
  "receipts": [
    {
      "id": "receipt-789",
      "debate_id": "debate-123",
      "verdict": "pass",
      "confidence": 0.92,
      "timestamp": "2026-01-20T10:30:00Z",
      "hash": "sha256:a1b2c3..."
    }
  ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

### Get Receipt Details

```http
GET /api/gauntlet/receipts/\{receipt_id\}
Authorization: Bearer <token>
```

**Response:**
```json
{
  "id": "receipt-789",
  "debate_id": "debate-123",
  "verdict": "pass",
  "confidence": 0.92,
  "timestamp": "2026-01-20T10:30:00Z",
  "hash": "sha256:a1b2c3d4e5f6...",
  "agents": ["anthropic-api", "openai-api"],
  "rounds": 3,
  "consensus_type": "majority",
  "findings": [
    {
      "type": "security",
      "severity": "low",
      "description": "Input validation could be strengthened"
    }
  ],
  "metadata": {
    "duration_ms": 45000,
    "token_count": 12500
  }
}
```

### Verify Receipt Integrity

```http
GET /api/gauntlet/receipts/\{receipt_id\}/verify
Authorization: Bearer <token>
```

**Response:**
```json
{
  "valid": true,
  "hash": "sha256:a1b2c3d4e5f6...",
  "computed_hash": "sha256:a1b2c3d4e5f6...",
  "verification_timestamp": "2026-01-20T11:00:00Z"
}
```

### Export Receipt

```http
GET /api/gauntlet/receipts/\{receipt_id\}/export
Authorization: Bearer <token>
```

**Query Parameters:**
- `format` (string, required): "json", "html", "markdown", or "sarif"

**Response (format=sarif):**
```json
{
  "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
  "version": "2.1.0",
  "runs": [
    {
      "tool": {
        "driver": {
          "name": "Aragora Gauntlet",
          "version": "1.0.0"
        }
      },
      "results": [...]
    }
  ]
}
```

### Create Shareable Link

```http
POST /api/gauntlet/receipts/\{receipt_id\}/share
Authorization: Bearer <token>
Content-Type: application/json

{
  "expires_in": 86400,
  "allow_download": true
}
```

**Response:**
```json
{
  "share_url": "https://app.aragora.ai/receipts/share/abc123",
  "expires_at": "2026-01-21T11:00:00Z",
  "token": "abc123"
}
```

### Get Receipt Statistics

```http
GET /api/gauntlet/receipts/stats
Authorization: Bearer <token>
```

**Query Parameters:**
- `period` (string): "day", "week", "month"

**Response:**
```json
{
  "period": "week",
  "total": 156,
  "by_verdict": {
    "pass": 120,
    "fail": 24,
    "warn": 12
  },
  "average_confidence": 0.87,
  "average_duration_ms": 42000
}
```

---

## Deprecated Endpoints

The following endpoints are deprecated and will be removed in future versions.

| Endpoint | Status | Removal | Migration |
|----------|--------|---------|-----------|
| `GET /api/debates/list` | Deprecated | v2.0 | Use `GET /api/debates` |
| `POST /api/debate/new` | Deprecated | v2.0 | Use `POST /api/debates/start` |
| `GET /api/elo/rankings` | Deprecated | v2.0 | Use `GET /api/agent/leaderboard` |
| `GET /api/agent/elo` | Deprecated | v2.0 | Use `GET /api/agent/\{name\}/profile` |
| `POST /api/stream/start` | Deprecated | v2.0 | Use WebSocket `/ws` connection |

### Migration Guide

#### Debate Listing

```bash
# Old (deprecated)
curl http://localhost:8080/api/debates/list

# New (recommended)
curl http://localhost:8080/api/debates
```

#### Starting Debates

```bash
# Old (deprecated)
curl -X POST http://localhost:8080/api/debate/new \
  -d '{"question": "..."}'

# New (recommended)
curl -X POST http://localhost:8080/api/debates/start \
  -H "Content-Type: application/json" \
  -d '{"question": "...", "agents": ["anthropic-api", "openai-api"]}'
```

#### Agent Rankings

```bash
# Old (deprecated)
curl http://localhost:8080/api/elo/rankings
curl http://localhost:8080/api/agent/elo?name=anthropic-api

# New (recommended)
curl http://localhost:8080/api/agent/leaderboard
curl http://localhost:8080/api/agent/anthropic-api/profile
```

### Deprecation Timeline

- **v1.5** (Current): Deprecated endpoints still functional, emit deprecation warnings in response headers
- **v2.0** (Planned): Deprecated endpoints return 410 Gone status
- **v2.1** (Planned): Deprecated endpoints removed entirely

Response headers for deprecated endpoints:

```
Deprecation: true
Sunset: 2026-06-01
Link: </api/debates>; rel="successor-version"
```

---

## Changelog

### 2026-01-09
- Added Graph Debates API (4 endpoints for branching debates)
- Added Matrix Debates API (4 endpoints for parallel scenarios)
- Added Breakpoints API (3 endpoints for human-in-the-loop)
- Added Introspection API (4 endpoints for agent self-awareness)
- Added Gallery API (3 endpoints for public debate sharing)
- Added Billing API (8 endpoints for subscription management)
- Updated endpoint count from 106 to 124

### 2026-01-05
- Added CSV and HTML export formats for debates
- Added token streaming events (`token_start`, `token_delta`, `token_end`)
- Added phase timeout events (`phase_start` now includes timeout, added `phase_timeout`)
- Added usage examples section with curl commands
- Added deprecated endpoints documentation with migration guide
