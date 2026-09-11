# Python SDK Breaking Changes

This document tracks breaking changes specific to the Aragora Python SDK. For core API breaking changes, see the main [BREAKING_CHANGES.md](../../docs/BREAKING_CHANGES.md).

---

## Version 2.x

### Unreleased (2026-09-03)

#### Breaking Changes

Batch 06 removes 11 matched phantom operations from both Python index namespace implementations, `ReplaysAPI`, and `DocumentsAPI` (including every async twin).
For each removed index method, the named route is absent from both OpenAPI documents and is not accepted by the knowledge-base handler: `get_index_stats` (`GET /api/v1/index/{name}/stats`), `add_documents` (`POST /api/v1/index/{name}/documents`), `update_document` (`PUT /api/v1/index/{name}/documents/{document_id}`), `delete_documents` (`DELETE /api/v1/index/{name}/documents`), `rebuild_index` (`POST /api/v1/index/{name}/rebuild`), and `optimize_index` (`POST /api/v1/index/{name}/optimize`).
For each removed replay method, the named route is absent from both OpenAPI documents and is not accepted by `ReplaysHandler.can_handle`: `get_from_debate` (`GET /api/v1/debates/{debate_id}/replay`), `export` (`GET /api/v1/replays/{replay_id}/export`), and `get_summary` (`GET /api/v1/replays/{replay_id}/summary`). `replays.get_from_debate` was the only method removed in this batch that carried a runtime `DeprecationWarning`.
For each removed document method, the named route is absent from both OpenAPI documents and is not accepted by `DocumentHandler.can_handle`: `download` (`GET /api/v1/documents/{document_id}/download`) and `reprocess` (`POST /api/v1/documents/{document_id}/reprocess`).
Removed 12 `debates` methods (sync `DebatesAPI` and async `AsyncDebatesAPI`)
that targeted routes no server handler dispatches. Every one of them was
already marked DEPRECATED and emitted a `DeprecationWarning`; each call
fell through to the debate slug lookup and returned 404, so no working
integration depended on them.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `debates.restore(debate_id)` | `POST /api/v1/debates/{id}/restore` | `debates.update(debate_id, status="active")` |
| `debates.make_permanent(debate_id)` | `POST /api/v1/debates/{id}/make-permanent` | None needed; completed debates persist automatically |
| `debates.find_similar(debate_id, limit)` | `GET /api/v1/debates/{id}/similar` | `consensus.get_similar_debates(topic, limit)` (`GET /api/v1/consensus/similar`) with the debate task text as `topic` |
| `debates.get_quality(debate_id)` | `GET /api/v1/debates/{id}/quality` | `debates.get_verification_report(debate_id)` |
| `debates.get_notes(debate_id)` | `GET /api/v1/debates/{id}/notes` | No replacement (server has no notes feature) |
| `debates.add_note(debate_id, content)` | `POST /api/v1/debates/{id}/notes` | No replacement (server has no notes feature) |
| `debates.delete_note(debate_id, note_id)` | `DELETE /api/v1/debates/{id}/notes/{note_id}` | No replacement (server has no notes feature) |
| `debates.get_batch_results(batch_id)` | `GET /api/v1/debates/batch/{id}/results` | `debates.get_batch_status(batch_id)` (includes per-job results) |
| `debates.cancel_batch(batch_id)` | `POST /api/v1/debates/batch/{id}/cancel` | Cancel individual debates with `debates.cancel(debate_id)` |
| `debates.retry_batch(batch_id)` | `POST /api/v1/debates/batch/{id}/retry` | Re-submit failed jobs with `debates.submit_batch(...)` |
| `debates.get_agent_statistics(debate_id)` | `GET /api/v1/debates/{id}/agent-statistics` | `debates.get_agent_stats()` (aggregate per-agent statistics) |
| `debates.get_debate_health(debate_id)` | `GET /api/v1/debates/{id}/health` | `debates.get_health()` for system health, `debates.get(debate_id)` for a debate's status |

Removed 10 `webhooks` methods (sync `WebhooksAPI` and async `AsyncWebhooksAPI`)
that targeted per-webhook sub-routes no server handler dispatches. The
webhook handler only routes `/api/v1/webhooks/{id}` and
`/api/v1/webhooks/{id}/test` below a webhook id, so every one of these calls
returned 404 and no working integration depended on them.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `webhooks.list_deliveries(webhook_id, status, limit, offset)` | `GET /api/v1/webhooks/{id}/deliveries` | `webhooks.list_dead_letter()` for failed deliveries; successful deliveries are not listed |
| `webhooks.get_delivery(webhook_id, delivery_id)` | `GET /api/v1/webhooks/{id}/deliveries/{delivery_id}` | `webhooks.get_dead_letter(dead_letter_id)` for a failed delivery; successful deliveries are not exposed individually |
| `webhooks.retry_delivery(webhook_id, delivery_id)` | `POST /api/v1/webhooks/{id}/deliveries/{delivery_id}/retry` | `webhooks.retry_dead_letter(dead_letter_id)` |
| `webhooks.get_delivery_stats(webhook_id, days)` | `GET /api/v1/webhooks/{id}/stats` | No replacement; per-webhook delivery statistics are not served (`GET /api/v1/webhooks/queue/stats` reports the shared delivery queue, not a single webhook) |
| `webhooks.subscribe_events(webhook_id, events)` | `POST /api/v1/webhooks/{id}/events` | `webhooks.update(webhook_id, events=[...])` with the full event list |
| `webhooks.unsubscribe_events(webhook_id, events)` | `DELETE /api/v1/webhooks/{id}/events` | `webhooks.update(webhook_id, events=[...])` with the remaining events |
| `webhooks.get_retry_policy(webhook_id)` | `GET /api/v1/webhooks/{id}/retry-policy` | No replacement; the retry policy is server-configured, not per webhook |
| `webhooks.update_retry_policy(webhook_id, **policy)` | `PUT /api/v1/webhooks/{id}/retry-policy` | No replacement; the retry policy is server-configured, not per webhook |
| `webhooks.rotate_secret(webhook_id)` | `POST /api/v1/webhooks/{id}/rotate-secret` | `webhooks.delete(webhook_id)` then `webhooks.create(...)`; the secret is returned once on creation |
| `webhooks.get_signing_info(webhook_id)` | `GET /api/v1/webhooks/{id}/signing` | Deliveries are signed with HMAC-SHA256 as `sha256=<hex>`; see `docs/api/WEBHOOKS.md` |

Removed 10 `admin` methods (sync `AdminAPI` and async `AsyncAdminAPI`) that
targeted routes no server handler dispatches. Below an organization or user id
the admin handler only serves the `/activate`, `/deactivate` and `/unlock`
user actions; impersonation is served as `POST /api/v1/admin/impersonate/{user_id}`
and credits under `/api/v1/admin/credits/{org_id}/...`. Every call below
returned 405 from that handler, so no working integration depended on them.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `admin.get_organization(org_id)` | `GET /api/v1/admin/organizations/{id}` | `organizations.get(org_id)` (`GET /api/v1/org/{id}`) |
| `admin.update_organization(org_id, **fields)` | `PUT /api/v1/admin/organizations/{id}` | `organizations.update(org_id, name=..., settings=...)` (`PUT /api/v1/org/{id}`, served but not yet in the spec; org-admin scoped and accepts only `name` and `settings`) |
| `admin.get_user(user_id)` | `GET /api/v1/admin/users/{id}` | `admin.list_users(...)` and filter by id |
| `admin.suspend_user(user_id, reason)` | `POST /api/v1/admin/users/{id}/suspend` | `admin.deactivate_user(user_id)` |
| `admin.impersonate_user(user_id)` | `POST /api/v1/admin/users/{id}/impersonate` | `client.request("POST", f"/api/v1/admin/impersonate/{user_id}")` |
| `admin.issue_credits(org_id, amount, reason, expires_at=None)` | `POST /api/v1/admin/organizations/{id}/credits` | `client.request("POST", f"/api/v1/admin/credits/{org_id}/issue", json={...})` |
| `admin.adjust_credits(org_id, amount, reason)` | `POST /api/v1/admin/organizations/{id}/credits` | `client.request("POST", f"/api/v1/admin/credits/{org_id}/adjust", json={...})` |
| `admin.get_credit_account(org_id)` | `GET /api/v1/admin/organizations/{id}/credits` | `client.request("GET", f"/api/v1/admin/credits/{org_id}")` |
| `admin.list_credit_transactions(org_id, **params)` | `GET /api/v1/admin/organizations/{id}/credits/transactions` | `client.request("GET", f"/api/v1/admin/credits/{org_id}/transactions", params={...})` |
| `admin.get_expiring_credits(org_id)` | `GET /api/v1/admin/organizations/{id}/credits/expiring` | `client.request("GET", f"/api/v1/admin/credits/{org_id}/expiring", params={"within_days": 30})` (`within_days` 1-365, default 30) |

Removed 10 `tenants` methods (sync `TenantsAPI` and async `AsyncTenantsAPI`)
that targeted routes no server handler dispatches. Nothing under
`/api/v1/tenants/{id}` is routed, so every call below returned 404 and no
working integration depended on them. There is no self-service tenant read or
write on the HTTP server at all: `/api/v1/tenants` is declared by the
organizations handler and `GET` is in the spec, but the handler has no branch
for it, so `tenants.list(...)` and `tenants.create(...)` (kept because their
route is spec-listed) currently fail too. Tenant administration lives only on
the opt-in FastAPI surface (`ARAGORA_USE_FASTAPI`): `GET`/`POST
/api/v2/admin/tenants` and `PUT /api/v2/admin/tenants/{tenant_id}` (`name`,
`tier`, `is_active`, `config`; `admin:tenants:write`), none of which is in the
spec or wrapped by this SDK.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `tenants.get(tenant_id)` | `GET /api/v1/tenants/{id}` | No replacement; no tenant read is served (see above) |
| `tenants.update(tenant_id, name=..., plan=..., settings=..., quotas=...)` | `PATCH /api/v1/tenants/{id}` | `organizations.update(org_id, name=..., settings=...)` (`PUT /api/v1/org/{id}`, served but not in the spec; org-admin scoped and accepts only `name` and `settings`). Plan and quota changes have no self-service route; admins can use `PUT /api/v2/admin/tenants/{tenant_id}` (`client.request`) when the FastAPI surface is enabled |
| `tenants.delete(tenant_id)` | `DELETE /api/v1/tenants/{id}` | No replacement; tenant deletion is not served |
| `tenants.suspend(tenant_id, reason)` | `POST /api/v1/tenants/{id}/suspend` | No replacement; tenant suspension is not served |
| `tenants.reactivate(tenant_id)` | `POST /api/v1/tenants/{id}/reactivate` | No replacement; tenant reactivation is not served |
| `tenants.get_usage(tenant_id)` | `GET /api/v1/tenants/{id}/usage` | `quotas.get_usage(period)` (`GET /api/v1/quotas/usage`); scoped to the caller's own organization, not an arbitrary tenant id |
| `tenants.get_quotas(tenant_id)` | `GET /api/v1/tenants/{id}/quotas` | `quotas.list()` (`GET /api/v1/quotas`); scoped to the caller's own organization |
| `tenants.update_quotas(tenant_id, quotas)` | `PUT /api/v1/tenants/{id}/quotas` | `quotas.request_increase(resource, requested_limit=..., justification=...)` (`POST /api/v1/quotas/request-increase`) files a request; there is no direct quota write |
| `tenants.list_members(tenant_id)` | `GET /api/v1/tenants/{id}/members` | `organizations.list_members(org_id)` (`GET /api/v1/org/{id}/members`); unpaginated, caller must be an org member |
| `tenants.invite_member(tenant_id, email, role)` | `POST /api/v1/tenants/{id}/members/invite` | `organizations.invite_member(org_id, email, role)` (`POST /api/v1/org/{id}/invite`, served but only the `GET` verb is in the spec; caller must be an org admin and `role` must be `member` or `admin`) |

Removed 2 `media` methods (sync and async) that targeted per-file audio routes
no server handler dispatches. The audio handler serves only
`/audio/{debate_id}.mp3`, `/api/v1/podcast/feed.xml` and the
`/api/v1/podcast/episodes` collection; `/api/v1/media/audio/{id}` returned 404.
`media.upload_audio(...)` (`POST /api/v1/media/audio`) is kept: that path is
declared by the audio handler even though no POST branch serves it yet.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `media.get_audio(audio_id)` | `GET /api/v1/media/audio/{id}` | `media.get_audio_url(debate_id)` builds the served `/audio/{debate_id}.mp3` URL; there is no per-file metadata route |
| `media.delete_audio(audio_id)` | `DELETE /api/v1/media/audio/{id}` | No replacement; audio deletion is not served |

Removed 6 `agents` methods (sync `AgentsAPI` and async `AsyncAgentsAPI`) that
targeted routes no server handler dispatches: the agents handler rewrites
`/api/v1/agents/{name}/...` to `/api/agent/{name}/...`, dispatches only
read-only sub-routes (`profile`, `history`, `calibration`, `consistency`,
`flips`, `network`, `rivals`, `allies`, `moments`, `positions`, `domains`,
`performance`, `metadata`, `introspect`, plus the two-segment
`head-to-head/{opponent}` and `opponent-briefing/{opponent}`) and has no POST
or PUT branch, and `/api/v1/agents/stats` is rejected as an invalid agent path.
Every call below failed.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `agents.get_stats()` | `GET /api/v1/agents/stats` | `ranking.get_stats()` (`GET /api/v1/ranking/stats`; `total_agents`, `total_matches`, `avg_elo`, `top_agent`, `elo_range`) for aggregate ranking statistics, or `client.request("GET", "/api/v1/agents", params={"include_stats": "true"})` for per-agent ELO and match counts (`agents.list()` sends no params). Per-agent stats also exist as `GET /api/v2/agents/{agent_id}/stats` on the opt-in FastAPI surface (`ARAGORA_USE_FASTAPI`), served but not in the spec |
| `agents.calibrate(name, options)` | `POST /api/v1/agents/{name}/calibrate` | No replacement; calibration is recorded by the debate loop, not triggered over HTTP. Read the result with `agents.get_calibration_summary(name)` / `agents.get_calibration_curve(name)` (`GET /api/v1/agent/{name}/calibration-summary` and `.../calibration-curve`) |
| `agents.enable(name)` | `POST /api/v1/agents/{name}/enable` | No replacement; there is no per-agent enable/disable switch on the HTTP server. Registration is the only served lifecycle mutation besides the per-agent heartbeat (`POST /api/v1/control-plane/agents/{id}/heartbeat`): `agents.register(agent_id, ...)` / `agents.unregister(agent_id)` (`POST` / `DELETE /api/v1/control-plane/agents[/{id}]`, served but not in the spec); the dashboard `pause`/`resume` routes under the same prefix are declared but not dispatched |
| `agents.disable(name, reason)` | `POST /api/v1/agents/{name}/disable` | See `agents.enable` |
| `agents.get_quota(name)` | `GET /api/v1/agents/{name}/quota` | `quotas.list()` (`GET /api/v1/quotas`) or `quotas.get(resource)` (`GET /api/v1/quotas/{resource}`); quotas are scoped to the caller's organization, not to an agent |
| `agents.set_quota(name, limits)` | `PUT /api/v1/agents/{name}/quota` | `quotas.request_increase(resource, requested_limit=..., justification=...)` (`POST /api/v1/quotas/request-increase`) files a request; there is no direct quota write and no per-agent quota |

Removed 4 `backups` methods (sync `BackupsAPI` and async `AsyncBackupsAPI`) that
targeted routes no server handler dispatches. The backup handler accepts only
`/api/v2/backups...` paths and below a backup id serves only `verify`,
`verify-comprehensive` and `restore-test`, so every call below returned 404.
The retained Python `backups` methods still target `/api/v1/backups...`, which
the handler also rejects.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `backups.restore(backup_id, target_namespace, data_types, dry_run)` | `POST /api/v1/backups/{id}/restore` | No served Python replacement: `backups.test_restore(backup_id, target_path)` posts to `/api/v1/backups/{backup_id}/restore-test`, which the v2-only backup handler rejects. For a dry-run restore into a server-side scratch path use `client.request("POST", f"/api/v2/backups/{backup_id}/restore-test", json={"target_path": ...})` (`POST /api/v2/backups/{id}/restore-test`, served but not in the spec); the TypeScript `backups.testRestore` targets the same route but currently sends no request body, so its `targetPath` argument is ignored. A real restore is operator-only via `aragora backup restore <backup_id> [--output PATH] [--dry-run]` on the server host |
| `backups.schedule(schedule, backup_type, retention_days, enabled)` | `POST /api/v1/backups/schedules` | No replacement; the backup schedule is server configuration (`BACKUP_ENABLED`, `BACKUP_DAILY_TIME`, `BACKUP_DR_DRILL_ENABLED`, `BACKUP_DR_DRILL_INTERVAL_DAYS`), not an API resource |
| `backups.list_schedules()` | `GET /api/v1/backups/schedules` | No replacement; see `backups.schedule` |
| `backups.delete_schedule(schedule_id)` | `DELETE /api/v1/backups/schedules/{id}` | No replacement; see `backups.schedule` |

---

### v2.4.0 (2026-01-25)

**No breaking changes.** Added new namespace resources.

**New Features:**
- Added resources: `orgs`, `tenants`, `policies`, `codebase`, `costs`, `decisions`, `onboarding`, `notifications`, `gmail`, `explainability`
- Fixed payloads for billing and RBAC endpoints

---

### v2.2.0 (2026-01-24)

**No breaking changes.** Version aligned with core package.

---

### v2.0.0 (2026-01-17)

#### Breaking Changes

| Change | Before | After | Migration |
|--------|--------|-------|-----------|
| API version default | v1 | v2 | Explicit `api_version="v1"` to keep old behavior |
| Method naming | Camel case methods | Namespace-based methods | `client.getDebates()` becomes `client.debates.list()` |
| Response format | Direct data | Wrapped in `data`/`meta` | Access via `response["data"]` |

#### Method Renames

| Old Method | New Method |
|------------|------------|
| `client.getDebates()` | `client.debates.list()` |
| `client.createDebate(...)` | `client.debates.create(...)` |
| `client.getDebate(id)` | `client.debates.get(id)` |
| `client.getAgents()` | `client.agents.list()` |
| `client.getAgent(name)` | `client.agents.get(name)` |
| `client.submitVote(...)` | `client.debates.vote(debate_id, ...)` |
| `client.getConsensus(id)` | `client.consensus.get(id)` |

#### Migration Example

```python
# Before (v1.x)
from aragora.client import AragoraClient

client = AragoraClient(base_url="https://api.aragora.ai")
debates = client.getDebates()
debate = client.createDebate(topic="Should we use GraphQL?", max_rounds=3)

# After (v2.x)
from aragora import AragoraClient

client = AragoraClient(
    base_url="https://api.aragora.ai",
    api_version="v2"  # Optional, v2 is now default
)
response = client.debates.list()
debates = response["data"]["debates"]

response = client.debates.create(
    task="Should we use GraphQL?",  # 'topic' renamed to 'task'
    rounds=3  # 'max_rounds' renamed to 'rounds'
)
debate = response["data"]
```

#### Response Format Change

```python
# Before (v1.x) - Direct data access
response = client.debates.list()
debates = response["debates"]
count = response["count"]

# After (v2.x) - Wrapped response
response = client.debates.list()
debates = response["data"]["debates"]
count = response["data"]["count"]
meta = response["meta"]  # Contains version, timestamp, request_id
```

---

## Version 1.x

### v1.0.0 (2026-01-14)

**Initial stable release.** No breaking changes from pre-1.0 beta versions.

---

## Upcoming Breaking Changes

### Scheduled for v3.0.0

No breaking changes currently scheduled.

---

## Migration Guides

- [API v1 to v2 Migration](../../docs/api/V1_TO_V2_MIGRATION.md) - Complete guide for API migration
- [SDK Guide](../../docs/SDK_GUIDE.md) - Full SDK documentation

---

## Deprecation Warnings

The SDK emits `DeprecationWarning` for deprecated methods. Enable warnings to see them:

```python
import warnings
warnings.filterwarnings("default", category=DeprecationWarning, module="aragora")
```

Or run Python with `-W default`:

```bash
python -W default your_script.py
```

---

*Last updated: 2026-01-31*
