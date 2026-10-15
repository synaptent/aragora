---
title: Breaking Changes
description: Breaking Changes
---

# Breaking Changes

This document tracks all breaking changes across Aragora releases. Use this as a migration reference when upgrading between major or minor versions.

For detailed migration guides, see:
- [API Migration v1 to v2](https://github.com/synaptent/aragora/blob/main/docs/status/MIGRATION_V1_TO_V2.md)
- [API Versioning Strategy](../api/versioning)
- [Deprecation Policy](../contributing/deprecation)

---

## Version 2.x

The sections from v2.4.1 onward restate, release by release, the [CHANGELOG](https://github.com/synaptent/aragora/blob/main/CHANGELOG.md) entries that remove, rename or deprecate something callers may depend on, or that change a default, a response shape or an exit code. Each released entry carries the PR number the CHANGELOG gives it. The CHANGELOG gives none before v2.9.0-rc.1, nor for the v2.9.0-rc.1 entries restated here, so those entries have none. The CHANGELOG's `[Pre-v0.2.0]` section, which sits between v2.4.1 and v2.7.0, records no breaking change and has no section here. For released versions the CHANGELOG remains the complete record.

### Unreleased

Merged on `main` after the v2.11.1 tag, whose commit is `486a10d8`: `git merge-base --is-ancestor <commit> 486a10d8` fails for each merge commit named here (#10298 `36ecdf9c`, #10210 `7836e4fc`, #9112 `003a3127`, #10204 `917398dd`, #10279 `92cf6b1e`, #10388 `366fed25`) and succeeds for contract-drift batch 4 (#10138 `d1b6809b`), which v2.11.1 lists. The first two entries come from the CHANGELOG's `[Unreleased]` section. The SDK removals come from the section headed `Unreleased (2026-09-27)` in `sdk/python/BREAKING_CHANGES.md`, the sections headed `Unreleased (2026-09-27)`, `Unreleased (2026-09-28)` and `Unreleased (2026-10-03)` in `sdk/typescript/BREAKING_CHANGES.md` (the earlier sections those files still label Unreleased shipped in v2.11.1 or before), and from [SDK Breaking Changes](#sdk-breaking-changes) below. Where those sources give no PR number (the budget guard entry and the SDK removals), the number shown is that of the change's merge commit on `main`. Under the exception in the [Deprecation Policy](../contributing/deprecation), the SDK removals may ship only in a minor or major release, and the CHANGELOG of the release that ships them lists them under **Removed**.

- **Knowledge facts need an organization** (#10298, listed as Breaking). On the v1 and v2 knowledge-base APIs, chunk search answers 403 `knowledge_fact_access_closed`, and the other fact routes serve only the caller's organization. Creating or importing facts without an authenticated organization answers 403 `knowledge_org_required`. Knowledge Mound fact sync is closed (`sync_from_facts` raises `OrgScopeRequiredError`), in-process readers that open a fact store without an organization fail closed, and the `aragora knowledge` commands `query`, `facts`, `process` and `stats` exit 2 when they reach the fact store. Without an organization, the chunk searches (`KnowledgePipeline.search`, `SimpleQueryEngine.search` and `query`, `DatasetQueryEngine.query` and the `AuditKnowledgeAdapter` chunk searches) raise `OrgScopeRequiredError`, and the integration helpers (`get_pipeline`, `process_*`, `queue_*_processing`, `process_uploaded_*`) take a keyword-only `org_id`. Chunks embedded before this change are keyed by workspace only and are not returned to organization searches until the documents are uploaded again. Facts stored without an organization are quarantined; see "Legacy facts without an organization (operator-only)" in `docs/knowledge/KNOWLEDGE_MOUND_OPERATIONS.md`. Some knowledge reads are not yet scoped to the organization: Knowledge Mound reads and mirroring stay workspace-scoped, and the in-memory embedding store keeps chunk text under the chunk id alone, so when two organizations store the same chunk id, a search in the earlier one can return the later one's text. The CHANGELOG's Fixed entry "Knowledge ingestion is scoped to the uploader's organization again" gives the details.
- **Budget guard ledger path** (#10210). A relative `ARAGORA_DATA_DIR` or `ARAGORA_NOMIC_DIR` is anchored under the home directory, so the ledger moves from `<working directory>/<dir>/budget_guard.json` to `~/<dir>/budget_guard.json`. Before upgrading mid-month, copy the old file there or set `ARAGORA_BUDGET_GUARD_STORE` to its absolute path; otherwise this month's recorded spend restarts at zero. An absolute data directory keeps the same ledger.
- **SDK and client methods for unserved routes are removed**, and no server route is removed: TypeScript `ModesAPI.getMode` and `SpectateAPI.connectSSE`, with Python `get_mode` and `connect_sse` on the sync and async clients (#9112; the SSE methods called `GET /api/v1/spectate/\{debate_id\}/stream`, which no handler serves, while `GET /api/v1/spectate/stream?debate_id=<id>` is served (a live SSE stream on the unified server, filtered by `debate_id`)); TypeScript `crossPollination.unsubscribe`, `apAutomation.addAPInvoice` and `policies.resolveViolation` (contract-drift batch 5, #10204); TypeScript `AragoraClient.exportReplay` (#10279); `aragora.client` `ReplayAPI.export` and `export_async` (#10388; the same removal is recorded under [Python SDK, Unreleased (2026-10-07)](#unreleased-2026-10-07) below).

---

### v2.11.1 (2026-09-28)

- **SDK methods for unserved routes are removed** (#10138, contract-drift batch 4). Both SDKs drop the methods whose routes no server handler dispatched; those calls could only fail with a route-level 404 or `handler_no_result`. No server route is removed. The full list, with replacements where they exist, is under "Unreleased (2026-09-21)" in `sdk/python/BREAKING_CHANGES.md` and `sdk/typescript/BREAKING_CHANGES.md`. The Python removals shipped in `aragora-sdk` 2.11.0 (PyPI, 2026-09-27); the TypeScript removals reach npm users with the next `@aragora/sdk` publish (the CHANGELOG gives npm's latest as 2.7.4).

---

### v2.11.0 (2026-09-25)

No server routes are removed. A user upgrading from 2.9.x also picks up every v2.10.0 change.

- **ODR v0.2 is the default emitter output** (#10165). Request v0.1 with `--odr-version 0.1`, `?odr_version=0.1` or `ARAGORA_ODR_PROFILE_VERSION=0.1`.
- **SDK methods whose routes no server dispatched are removed** from both SDKs: the phantom agents/backups endpoint pairs (#9983) and the final tranche of phantom routes (#9987). `sdk/python/BREAKING_CHANGES.md` and `sdk/typescript/BREAKING_CHANGES.md` list them.
- **Python SDK:** automatic `Retry-After` waits are capped at 60 s, and incomplete HTTP-date forms are rejected (#10056).
- **TypeScript SDK:** a stream that closes without a terminal event throws `ConnectionError` instead of a synthesized `debate_end` (#10014).
- **Gauntlet CLI exit codes** (#10100): an unconditional PASS/APPROVED exits 0, a conditional or review verdict exits 2, and a rejection, an unknown verdict or non-completion exits 1.

---

### v2.10.0 (2026-09-04)

The CHANGELOG records no breaking changes to the public Python API.

- **SDK methods for phantom endpoints are removed** from both SDKs by contract-drift paydown batches (#9969, #9976).

---

### v2.9.0 (2026-04-25)

- **Mode 3 review briefs** can return `approve_with_followups` where they returned `repair_first`: `REPAIR_FIRST` is downgraded when the severity map reports no `high` finding (#6505, #6510). Callers that pass no severity data keep the three-class behavior.
- **PostgreSQL `webhook_configs`:** migration `v20260424000000_align_webhook_configs_schema.py` keeps the data while moving `org_id` to `workspace_id`, `is_active` to `active` and `events` to `events_json` (#6575).
- **Mode 3 panel budget ceiling** rises from 8.00 to 10.00 USD (#6514).

---

### v2.9.0-rc.1 (2026-04-24)

- **Deprecated:** the individual `supermemory`, `knowledge`, `evolution` and `ML` Arena parameters emit deprecation warnings; use `SupermemoryConfig`, `KnowledgeConfig`, `EvolutionConfig` and `MLConfig`.
- **Response shape:** the cost handler (7 endpoints) and the usage dashboard (6 endpoints) wrap their responses in `{"data": {...}}`.
- **Default:** knowledge extraction is enabled by default in debate outcomes.

---

### v2.8.1-rc.1 (2026-02-25)

**No breaking changes** recorded in the CHANGELOG.

---

### v2.8.0 (2026-02-16)

- **SDK voice namespace:** the stale voice namespace is removed; voice is re-wired into the sync and async clients with gateway methods.
- **TypeScript SDK:** 37 methods send a corrected HTTP verb (GET/POST/DELETE/PATCH aligned with the server endpoints).

---

### v2.7.4 (2026-02-14)

- **SDK:** 1,888 lines of stale SDK methods are removed, and stale TypeScript namespace methods are pruned.
- **Packaging:** the non-PyPI `rlm` is removed from the extras; the RLM dependency comes from PyPI instead of a git URL.
- **Deprecation:** `success_response` now emits the `DeprecationWarning` its documentation describes.

---

### v2.7.3 (2026-02-13)

**No breaking changes** recorded in the CHANGELOG.

---

### v2.7.2 (2026-02-13)

- **RBAC:** the middleware denies unrecognized routes by default instead of allowing them.

---

### v2.7.1 (2026-02-13)

- **SDK:** stale SDK methods and stale TypeScript integrations namespace methods are removed.
- **OpenAPI:** 86 orphaned routes are removed from the OpenAPI spec.

---

### v2.7.0 (2026-02-13)

- **Deprecated:** the individual supermemory, knowledge, evolution and ML Arena parameters, in favor of `SupermemoryConfig`, `KnowledgeConfig`, `EvolutionConfig` and `MLConfig`; `Arena.create()` warns on the legacy parameter style.
- **SDK:** 2,952+ lines of stale SDK methods are removed across 8 namespaces, including methods without backend route coverage.
- **Removed code:** 17 dead modules and 10 orchestrator shims.
- **Deployment:** `deploy/k8s/` is merged into `deploy/kubernetes/`.
- **V1 API sunset preparation:** a deprecation enforcer middleware, a versioned router and a migration guide.

---

### v2.4.1 (2026-01-31)

The CHANGELOG labels no change in this release as breaking.

- **Token signing** uses full 256-bit HMAC-SHA256 signatures instead of truncated 64-bit signatures (listed under Security).

---

### v2.4.0 (2026-01-25)

**No breaking changes.** This release focuses on SDK expansion and bug fixes.

---

### v2.2.0 (2026-01-24)

**No breaking changes.** This release adds new features with backward compatibility.

---

### v2.1.x (2026-01-23 - 2026-01-24)

**No breaking changes.** Series of stability and feature releases.

---

### v2.0.6 (2026-01-20)

**No breaking changes.** Stability release promoting Pulse to stable status.

---

### v2.0.3 (2026-01-20)

**No breaking changes.** Cross-functional integration release with opt-in features.

---

### v2.0.0 (2026-01-17)

#### API Changes

| Category | Change | Migration |
|----------|--------|-----------|
| Response format | All API responses now wrapped with `data` and `meta` objects | Update response parsing: `response["debates"]` becomes `response["data"]["debates"]` |
| Endpoint naming | Endpoints now use plural resource names | `POST /api/v1/debate` becomes `POST /api/v2/debates` |
| Request body | Field `topic` renamed to `task`, `max_rounds` renamed to `rounds` | Update request payloads |
| Authentication | OAuth 2.0 now required for org/user management endpoints | Implement OAuth 2.0 flow for affected endpoints |
| Error format | Standardized error codes with structured responses | Update error handling to use `error.code` and `error.message` |

**Migration Steps:**

1. Update all API endpoint URLs to use `/api/v2/` prefix
2. Update response parsing to access data via `response["data"]`
3. Update request bodies to use new field names (`task`, `rounds`)
4. Implement OAuth 2.0 for organization management endpoints
5. Update error handling for new structured error format

**Example Migration:**

```python
# Before (v1)
response = client.post("/api/v1/debate", {"topic": "Design a cache", "max_rounds": 3})
debates = response["debates"]

# After (v2)
response = client.post("/api/v2/debates", {"task": "Design a cache", "rounds": 3})
debates = response["data"]["debates"]
```

See [MIGRATION_V1_TO_V2.md](https://github.com/synaptent/aragora/blob/main/docs/status/MIGRATION_V1_TO_V2.md) for complete migration guide.

---

## Version 1.x

### v1.0.0 (2026-01-13)

#### Breaking Changes from Pre-1.0

| Category | Change | Migration |
|----------|--------|-----------|
| API versioning | All `/api/` endpoints deprecated | Use `/api/v2/` prefix for new integrations |
| Agent names | Must use canonical names | Use `anthropic-api`, `openai-api` instead of aliases like `claude`, `codex` |
| Rate limiting | Now enabled by default | Configure via `ARAGORA_RATE_LIMIT_*` environment variables |
| Multi-replica deployments | Redis required for session state | Configure Redis for distributed deployments |

**Migration Steps:**

1. Update API calls to use `/api/v2/` prefix
2. Configure Redis for distributed deployments
3. Set `ARAGORA_ENABLE_MFA=true` if using MFA
4. Update SDK to `@aragora/sdk@1.0.0`
5. Review rate limit configuration

See [deprecated/migrations/MIGRATION_0.8_to_1.0.md](https://github.com/synaptent/aragora/blob/main/docs/deprecated/migrations/MIGRATION_0.8_to_1.0.md) for detailed upgrade instructions.

---

## Upcoming Breaking Changes

See [DEPRECATION_POLICY.md](../contributing/deprecation) for the full deprecation timeline.

> **Completed (v2.3.0):** `aragora.modes.gauntlet` (→ `aragora.gauntlet`), `aragora.crawlers` (→ `aragora.connectors`), and `ARAGORA_REQUIRE_DISTRIBUTED_STATE` (→ `ARAGORA_REQUIRE_DISTRIBUTED`) were all removed as planned. No migration action needed.

### Planned v1 Removal (June 1, 2026; Not Carried Out)

| Item | Type | Replacement |
|------|------|-------------|
| API v1 endpoints | API | Use `/api/v2/` endpoints |
| `GET /api/v1/debates` | Endpoint | `GET /api/v2/debates` |
| `POST /api/v1/debate` | Endpoint | `POST /api/v2/debates` |
| `GET /api/v1/agents` | Endpoint | `GET /api/v2/agents` |
| `GET /api/v1/health` | Endpoint | `GET /api/v2/system/health` |

That date has passed. The CHANGELOG records no removal of the v1 API through v2.11.1 or in `[Unreleased]`; v2.7.0 records only the sunset preparation (a deprecation enforcer middleware, a versioned router and a migration guide).

---

## SDK Breaking Changes

### Python SDK

#### Unreleased (2026-10-07)

| Change | Before | After |
|--------|--------|-------|
| Unserved replay export removed | `client.replays.export(replay_id, format)` and `client.replays.export_async(replay_id, format)` (`ReplayAPI` in `aragora.client`) | Removed with no replacement; accessing either name raises `AttributeError`. `client.replays.get(replay_id)` still returns the full replay. |

Both methods called `GET /api/replays/\{replay_id\}/export`, which no handler serves: the
path is absent from the OpenAPI documents and `ReplaysHandler.can_handle` rejects it. The
TypeScript SDK's `AragoraClient.exportReplay`, which called the same route, was already
removed.

#### v2.0.0

| Change | Before | After |
|--------|--------|-------|
| Client initialization | `AragoraClient(base_url="...")` | `AragoraClient(base_url="...", api_version="v2")` |
| Method naming | `client.getDebates()` | `client.debates.list()` |
| Method naming | `client.createDebate(task="...")` | `client.debates.create(task="...")` |
| Method naming | `client.getAgents()` | `client.agents.list()` |

**Migration Example:**

```python
# Before (v1)
from aragora.client import AragoraClient
client = AragoraClient(base_url="https://api.aragora.io")
debates = client.getDebates()

# After (v2)
from aragora.client import AragoraClient
client = AragoraClient(base_url="https://api.aragora.io", api_version="v2")
debates = client.debates.list()
```

### TypeScript SDK

#### v2.0.0

| Change | Before | After |
|--------|--------|-------|
| Major version alignment | Independent versioning | Aligned with core Aragora version |
| API compatibility | v1 default | v2 default |

**Migration:**

```bash
npm install @aragora/sdk@^2.0.0
```

```typescript
// SDK 2.0+ defaults to API v2
const client = new AragoraClient({
  baseUrl: process.env.ARAGORA_API_URL,
  // apiVersion: 'v2' is now the default
});
```

---

## How to Document New Breaking Changes

When introducing a breaking change, follow these steps:

1. **Add to this document** under the appropriate version section
2. **Update CHANGELOG.md** with a "Breaking Changes" or "Deprecated" section
3. **Create migration guide** if the change is complex (link from this document)
4. **Add deprecation warnings** to affected code (see [DEPRECATION_POLICY.md](../contributing/deprecation))
5. **Update SDK documentation** if SDK methods are affected

Use the template at [templates/breaking_change_template.md](https://github.com/synaptent/aragora/blob/main/docs/templates/breaking_change_template.md) for consistent documentation.

---

## Related Documentation

- [API Versioning Strategy](../api/versioning) - Version management and deprecation headers
- [Deprecation Policy](../contributing/deprecation) - Full deprecation process and timeline
- [Migration Guide v1 to v2](https://github.com/synaptent/aragora/blob/main/docs/status/MIGRATION_V1_TO_V2.md) - Complete API migration instructions
- [Release Notes](https://github.com/synaptent/aragora/blob/main/docs/deployment/RELEASE_NOTES.md) - Full release history with all changes
- [CHANGELOG](https://github.com/synaptent/aragora/blob/main/CHANGELOG.md) - Detailed changelog for all versions

---

*Last updated: 2026-10-13*
