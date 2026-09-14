# TypeScript SDK Breaking Changes

This document tracks breaking changes specific to the Aragora TypeScript SDK. For core API breaking changes, see the main [BREAKING_CHANGES.md](../../docs/BREAKING_CHANGES.md).

---

## Version 2.x

### Unreleased (2026-09-03)

#### Breaking Changes

`streamDebate`, `streamDebateById`, and client stream wrappers now drain accepted
events before ending. A socket close without a genuine terminal event throws
`ConnectionError` after buffered delivery; it no longer manufactures `debate_end`.
Wrap `for await` in `try/catch` (see the [streaming example](../../docs/guides/SDK_QUICKSTART_TYPESCRIPT.md#real-time-streaming)).
Close errors expose `WS_CLOSE_<number>` via `error.code`/`error.errorCode` and the
numeric value via `error.responseBody.code`, without the raw remote reason.
A native transport error may precede close: the iterator retains close diagnostics
for up to 1,000 ms after the first error; repeated errors do not restart the window.
If no close arrives, it throws a sanitized, non-retryable `ConnectionError` without
a close code. Parsing errors fail immediately and are also non-retryable. Here,
non-retryable means explicit caller handling is required, not proof of permanence.
Buffered events still drain; an accepted genuine terminal event before finalization
takes precedence. Close arriving after finalization cannot revise the outcome.
`isRetryableError` respects the new optional fifth `ConnectionError` constructor
argument, `retryable` (default `true` for existing callers). Only close codes
1001,1006,1011,1012,1013,4029 are retryable; all others, including premature1000,
require explicit caller handling. This is eligibility, not automatic retry:
the iterator does not resume, and a new connection guarantees neither replay nor
gap-free delivery. Bound application retries with backoff; do not restart blindly.

Batch 06 removes 11 matched phantom operations from `IndexAPI`, `ReplaysAPI`, and `DocumentsAPI`.
For each removed index method, the named route is absent from both OpenAPI documents and is not accepted by the knowledge-base handler: `getIndexStats` (`GET /api/v1/index/{name}/stats`), `addDocuments` (`POST /api/v1/index/{name}/documents`), `updateDocument` (`PUT /api/v1/index/{name}/documents/{documentId}`), `deleteDocuments` (`DELETE /api/v1/index/{name}/documents`), `rebuildIndex` (`POST /api/v1/index/{name}/rebuild`), and `optimizeIndex` (`POST /api/v1/index/{name}/optimize`). The `IndexDocument` and `UpdateDocumentOptions` interfaces are deleted with `addDocuments` and `updateDocument` and are no longer re-exported by the `namespaces` barrel.
For each removed replay method, the named route is absent from both OpenAPI documents and is not accepted by `ReplaysHandler.can_handle`: `getFromDebate` (`GET /api/v1/debates/{debateId}/replay`), `export` (`GET /api/v1/replays/{replayId}/export`), and `getSummary` (`GET /api/v1/replays/{replayId}/summary`). `replays.getFromDebate` was the only method removed in this batch that carried an `@deprecated` tag.
For each removed document method, the named route is absent from both OpenAPI documents and is not accepted by `DocumentHandler.can_handle`: `download` (`GET /api/v1/documents/{documentId}/download`) and `reprocess` (`POST /api/v1/documents/{documentId}/reprocess`).
Removed 12 `debates` methods from `DebatesAPI` that targeted routes no server
handler dispatches. Every one of them was already marked `@deprecated`; each
call fell through to the debate slug lookup and returned 404, so no working
integration depended on them. The response interfaces used only by those
methods (`DebateHealthDetail`, `BatchResults`, `ArgumentQualityAnalysis`,
`DebateNote`) were removed with them.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `debates.restore(debateId)` | `POST /api/v1/debates/{id}/restore` | `debates.update(debateId, { status: 'active' })` |
| `debates.makePermanent(debateId)` | `POST /api/v1/debates/{id}/make-permanent` | None needed; completed debates persist automatically |
| `debates.findSimilar(debateId, limit)` | `GET /api/v1/debates/{id}/similar` | `consensus.findSimilar({ topic, limit })` (`GET /api/consensus/similar`) with the debate task text as `topic` |
| `debates.analyzeArgumentQuality(debateId)` | `GET /api/v1/debates/{id}/quality` | `debates.getSummary(debateId)` |
| `debates.getNotes(debateId)` | `GET /api/v1/debates/{id}/notes` | No replacement (server has no notes feature) |
| `debates.addNote(debateId, note)` | `POST /api/v1/debates/{id}/notes` | No replacement (server has no notes feature) |
| `debates.deleteNote(debateId, noteId)` | `DELETE /api/v1/debates/{id}/notes/{noteId}` | No replacement (server has no notes feature) |
| `debates.getBatchResults(batchId)` | `GET /api/v1/debates/batch/{id}/results` | `debates.getBatchStatus(batchId)` (includes per-job state) |
| `debates.cancelBatch(batchId)` | `POST /api/v1/debates/batch/{id}/cancel` | Cancel individual debates with `debates.cancel(debateId)` |
| `debates.retryBatch(batchId, options)` | `POST /api/v1/debates/batch/{id}/retry` | Re-submit failed debates with `debates.submitBatch(...)` |
| `debates.getDebateAgentStatistics(debateId)` | `GET /api/v1/debates/{id}/agent-statistics` | `debates.getStatsAgents()` (aggregate per-agent statistics) |
| `debates.getHealth(debateId)` | `GET /api/v1/debates/{id}/health` | `debates.listHealth()` for system-wide debate health |

Removed 10 `webhooks` methods from `WebhooksAPI` that targeted per-webhook
sub-routes no server handler dispatches. The webhook handler only routes
`/api/v1/webhooks/{id}` and `/api/v1/webhooks/{id}/test` below a webhook id,
so every one of these calls returned 404 and no working integration depended
on them. The interfaces used only by those methods (`WebhookDeliveryAttempt`,
`WebhookRetryPolicy`) were removed with them.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `webhooks.listDeliveries(webhookId, options)` | `GET /api/v1/webhooks/{id}/deliveries` | `webhooks.listDeadLetter()` for failed deliveries; successful deliveries are not listed |
| `webhooks.getDelivery(webhookId, deliveryId)` | `GET /api/v1/webhooks/{id}/deliveries/{deliveryId}` | `webhooks.getDeadLetter(id)` for a failed delivery; successful deliveries are not exposed individually |
| `webhooks.retryDelivery(webhookId, deliveryId)` | `POST /api/v1/webhooks/{id}/deliveries/{deliveryId}/retry` | `webhooks.retryDeadLetter(id)` |
| `webhooks.getDeliveryStats(webhookId, options)` | `GET /api/v1/webhooks/{id}/stats` | No replacement; per-webhook delivery statistics are not served (`webhooks.getQueueStats()` reports the shared delivery queue, not a single webhook) |
| `webhooks.subscribeEvents(webhookId, events)` | `POST /api/v1/webhooks/{id}/events` | `webhooks.update(webhookId, { events })` with the full event list |
| `webhooks.unsubscribeEvents(webhookId, events)` | `DELETE /api/v1/webhooks/{id}/events` | `webhooks.update(webhookId, { events })` with the remaining events |
| `webhooks.getRetryPolicy(webhookId)` | `GET /api/v1/webhooks/{id}/retry-policy` | No replacement; the retry policy is server-configured, not per webhook |
| `webhooks.updateRetryPolicy(webhookId, policy)` | `PUT /api/v1/webhooks/{id}/retry-policy` | No replacement; the retry policy is server-configured, not per webhook |
| `webhooks.rotateSecret(webhookId)` | `POST /api/v1/webhooks/{id}/rotate-secret` | `webhooks.delete(webhookId)` then `webhooks.create(...)`; the secret is returned once on creation |
| `webhooks.getSigningInfo(webhookId)` | `GET /api/v1/webhooks/{id}/signing` | Deliveries are signed with HMAC-SHA256 as `sha256=<hex>`; see `docs/api/WEBHOOKS.md` |

Removed 10 `admin` methods from `AdminAPI` that targeted routes no server
handler dispatches. Below an organization or user id the admin handler only
serves the `/activate`, `/deactivate` and `/unlock` user actions; impersonation
is served as `POST /api/v1/admin/impersonate/{userId}` and credits under
`/api/v1/admin/credits/{orgId}/...`. Every call below returned 405 from that
handler, so no working integration depended on them. The
`AdminClientInterface` entries used only by those methods (`getCreditAccount`,
`listCreditTransactions`, `adjustCreditBalance`, `getExpiringCredits`) were
removed with them. The legacy flat methods on `AragoraClient` that target the
same routes (`getAdminOrganization`, `updateAdminOrganization`, `getAdminUser`,
`suspendAdminUser`, `impersonateUser`, `issueCredits`, `getCreditAccount`,
`listCreditTransactions`, `adjustCreditBalance`, `getExpiringCredits`) are
unchanged here and still return 405; do not migrate to them.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `admin.getOrganization(orgId)` | `GET /api/v1/admin/organizations/{id}` | `organizations.get(orgId)` (`GET /api/v1/org/{id}`) |
| `admin.updateOrganization(orgId, updates)` | `PUT /api/v1/admin/organizations/{id}` | `organizations.update(orgId, { name, settings })` (`PUT /api/v1/org/{id}`, served but not yet in the spec; org-admin scoped and accepts only `name` and `settings`) |
| `admin.getUser(userId)` | `GET /api/v1/admin/users/{id}` | `admin.listUsers(...)` and filter by id |
| `admin.suspendUser(userId, reason)` | `POST /api/v1/admin/users/{id}/suspend` | `admin.deactivateUser(userId)` |
| `admin.impersonateUser(userId)` | `POST /api/v1/admin/users/{id}/impersonate` | `openapi.requestPostApiV1AdminImpersonateByUserId(userId)` (`POST /api/v1/admin/impersonate/{userId}`) |
| `admin.issueCredits(orgId, amount, reason, expiresAt)` | `POST /api/v1/admin/organizations/{id}/credits` | ``client.request('POST', `/api/v1/admin/credits/${orgId}/issue`, { body })`` |
| `admin.adjustCredits(orgId, amount, reason)` | `POST /api/v1/admin/organizations/{id}/credits` | ``client.request('POST', `/api/v1/admin/credits/${orgId}/adjust`, { body })`` |
| `admin.getCreditAccount(orgId)` | `GET /api/v1/admin/organizations/{id}/credits` | ``client.request('GET', `/api/v1/admin/credits/${orgId}`)`` |
| `admin.listCreditTransactions(orgId, params)` | `GET /api/v1/admin/organizations/{id}/credits/transactions` | ``client.request('GET', `/api/v1/admin/credits/${orgId}/transactions`, { params })`` |
| `admin.getExpiringCredits(orgId)` | `GET /api/v1/admin/organizations/{id}/credits/expiring` | ``client.request('GET', `/api/v1/admin/credits/${orgId}/expiring`, { params: { within_days: 30 } })`` (`within_days` 1-365, default 30) |

Removed 10 `tenants` methods from `TenantsAPI` that targeted routes no server
handler dispatches. Nothing under `/api/v1/tenants/{id}` is routed, so every
call below returned 404 and no working integration depended on them. There is
no self-service tenant read or write on the HTTP server at all:
`/api/v1/tenants` is declared by the organizations handler and `GET` is in the
spec, but the handler has no branch for it, so `tenants.list` and
`tenants.create` (kept because their route is spec-listed) currently fail too.
`tenants.addMember` and `tenants.removeMember` are also kept only because they
are thin aliases of the flat client methods that own those paths
(`POST /api/v1/tenants/{id}/members`, `DELETE /api/v1/tenants/{id}/members/{userId}`);
those routes are equally unrouted and return 404. Tenant administration lives
only on the opt-in FastAPI surface (`ARAGORA_USE_FASTAPI`): `GET`/`POST
/api/v2/admin/tenants` and `PUT /api/v2/admin/tenants/{tenant_id}` (`name`,
`tier`, `is_active`, `config`; `admin:tenants:write`), none of which is in the
spec or wrapped by this SDK. The `TenantsClientInterface` entries and the
local `UpdateTenantRequest`, `QuotaStatus` and `QuotaUpdate` interfaces used
only by the removed methods were removed with them (the same-named
package-root types in `types.ts` are unchanged). The legacy flat `*Tenant*`
methods on `AragoraClient` that target the same routes are unchanged here and
still return 404; do not migrate to them.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `tenants.get(tenantId)` | `GET /api/v1/tenants/{id}` | No replacement; no tenant read is served (see above) |
| `tenants.update(tenantId, body)` | `PATCH /api/v1/tenants/{id}` | `organizations.update(orgId, { name, settings })` (`PUT /api/v1/org/{id}`, served but not in the spec; org-admin scoped and accepts only `name` and `settings`). Plan and quota changes have no self-service route; admins can use `PUT /api/v2/admin/tenants/{tenant_id}` (`client.request`) when the FastAPI surface is enabled |
| `tenants.delete(tenantId)` | `DELETE /api/v1/tenants/{id}` | No replacement; tenant deletion is not served |
| `tenants.suspend(tenantId)` | `POST /api/v1/tenants/{id}/suspend` | No replacement; tenant suspension is not served |
| `tenants.reactivate(tenantId)` | `POST /api/v1/tenants/{id}/reactivate` | No replacement; tenant reactivation is not served |
| `tenants.getUsage(tenantId)` | `GET /api/v1/tenants/{id}/usage` | ``client.request('GET', '/api/v1/quotas/usage')`` (in the spec; `quotas.getUsageHistory()` targets the unversioned `/api/quotas/usage` alias); scoped to the caller's own organization, not an arbitrary tenant id |
| `tenants.getQuotas(tenantId)` | `GET /api/v1/tenants/{id}/quotas` | `quotas.list()` (`GET /api/v1/quotas`); scoped to the caller's own organization |
| `tenants.updateQuotas(tenantId, body)` | `PUT /api/v1/tenants/{id}/quotas` | `quotas.requestIncrease(resource, requestedLimit, reason)` (`POST /api/v1/quotas/request-increase`) files a request; there is no direct quota write |
| `tenants.listMembers(tenantId, params)` | `GET /api/v1/tenants/{id}/members` | `organizations.listMembers(orgId, params)` (`GET /api/v1/org/{id}/members`); the server ignores pagination and the caller must be an org member |
| `tenants.inviteMember(tenantId, body)` | `POST /api/v1/tenants/{id}/members/invite` | `organizations.invite(orgId, { email, role })` (`POST /api/v1/org/{id}/invite`, served but only the `GET` verb is in the spec; caller must be an org admin and `role` must be `member` or `admin`) |

Removed 2 `media` methods that targeted per-file audio routes no server
handler dispatches. The audio handler serves only `/audio/{debateId}.mp3`,
`/api/v1/podcast/feed.xml` and the `/api/v1/podcast/episodes` collection;
`/api/v1/media/audio/{id}` returned 404. `media.uploadAudio(params)`
(`POST /api/v1/media/audio`) is kept: that path is declared by the audio
handler even though no POST branch serves it yet.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `media.getAudio(audioId)` | `GET /api/v1/media/audio/{id}` | `media.getAudioUrl(debateId)` builds the served `/audio/{debateId}.mp3` path; there is no per-file metadata route |
| `media.deleteAudio(audioId)` | `DELETE /api/v1/media/audio/{id}` | No replacement; audio deletion is not served |

Removed 6 `agents` methods from `AgentsAPI` that targeted routes no server
handler dispatches: the agents handler rewrites `/api/v1/agents/{name}/...` to
`/api/agent/{name}/...`, dispatches only read-only sub-routes (`profile`,
`history`, `calibration`, `consistency`, `flips`, `network`, `rivals`, `allies`,
`moments`, `positions`, `domains`, `performance`, `metadata`, `introspect`,
plus the two-segment `head-to-head/{opponent}` and
`opponent-briefing/{opponent}`) and has no POST or PUT branch, and
`/api/v1/agents/stats` is rejected as an invalid agent path. Every call below
failed.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `agents.getStats()` | `GET /api/v1/agents/stats` | `ranking.getStats()` (`GET /api/v1/ranking/stats`; `total_agents`, `total_matches`, `avg_elo`, `top_agent`, `elo_range`) for aggregate ranking statistics, or `client.request('GET', '/api/v1/agents', { params: { include_stats: 'true' } })` for per-agent ELO and match counts (`agents.list()` sends no params). Per-agent stats also exist as `GET /api/v2/agents/{agent_id}/stats` on the opt-in FastAPI surface (`ARAGORA_USE_FASTAPI`), served but not in the spec |
| `agents.calibrate(name, options)` | `POST /api/v1/agents/{name}/calibrate` | No replacement; calibration is recorded by the debate loop, not triggered over HTTP. Read the result with `agents.getCalibrationSummary(name)` / `agents.getCalibrationCurve(name)` (`GET /api/v1/agent/{name}/calibration-summary` and `.../calibration-curve`) |
| `agents.enable(name)` | `POST /api/v1/agents/{name}/enable` | No replacement; there is no per-agent enable/disable switch on the HTTP server. Registration is the only served lifecycle mutation besides the per-agent heartbeat (`agents.heartbeat(agentId, status)`, `POST /api/v1/control-plane/agents/{id}/heartbeat`): `agents.register(agentId, options)` / `agents.unregister(agentId)` (`POST` / `DELETE /api/v1/control-plane/agents[/{id}]`, served but not in the spec); the dashboard `pause`/`resume` routes under the same prefix are declared but not dispatched |
| `agents.disable(name, reason)` | `POST /api/v1/agents/{name}/disable` | See `agents.enable` |
| `agents.getQuota(name)` | `GET /api/v1/agents/{name}/quota` | `quotas.list()` (`GET /api/v1/quotas`) or `quotas.get(resource)` (`GET /api/quotas/{resource}`; the server maps unversioned `/api/...` paths to v1, so this reaches the spec-listed `GET /api/v1/quotas/{resource}`); quotas are scoped to the caller's organization, not to an agent |
| `agents.setQuota(name, options)` | `PUT /api/v1/agents/{name}/quota` | `quotas.requestIncrease(resource, requestedLimit, reason)` (`POST /api/v1/quotas/request-increase`) files a request; there is no direct quota write and no per-agent quota |

Removed 4 `backups` methods from `BackupsAPI` that targeted routes no server
handler dispatches. The backup handler accepts only `/api/v2/backups...` paths
and below a backup id serves only `verify`, `verify-comprehensive` and
`restore-test`, so every call below returned 404.

| Removed Method | Route | Migration |
|----------------|-------|-----------|
| `backups.restore(backupId, options)` | `POST /api/v1/backups/{id}/restore` | ``client.request('POST', `/api/v2/backups/${backupId}/restore-test`, { body: { target_path: targetPath } })`` (`POST /api/v2/backups/{id}/restore-test`, served but not in the spec) performs a dry-run restore into a server-side scratch path only; `backups.testRestore` targets the same route but currently sends no request body, so its `targetPath` argument is ignored and the server uses its default scratch file. A real restore is operator-only via `aragora backup restore <backup_id> [--output PATH] [--dry-run]` on the server host |
| `backups.createSchedule(options)` | `POST /api/v1/backups/schedules` | No replacement; the backup schedule is server configuration (`BACKUP_ENABLED`, `BACKUP_DAILY_TIME`, `BACKUP_DR_DRILL_ENABLED`, `BACKUP_DR_DRILL_INTERVAL_DAYS`), not an API resource |
| `backups.listSchedules()` | `GET /api/v1/backups/schedules` | No replacement; see `backups.createSchedule` |
| `backups.deleteSchedule(scheduleId)` | `DELETE /api/v1/backups/schedules/{id}` | No replacement; see `backups.createSchedule` |

---

## Migration Guides

- [API v1 to v2 Migration](../../docs/api/V1_TO_V2_MIGRATION.md) - Complete guide for API migration
- [SDK Guide](../../docs/SDK_GUIDE.md) - Full SDK documentation

---
