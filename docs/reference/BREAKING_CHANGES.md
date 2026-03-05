# Breaking Changes

This document tracks all breaking changes across Aragora releases. Use this as a migration reference when upgrading between major or minor versions.

For detailed migration guides, see:
- [API Migration v1 to v2](../status/MIGRATION_V1_TO_V2.md)
- [API Versioning Strategy](../api/API_VERSIONING.md)
- [Deprecation Policy](./DEPRECATION_POLICY.md)

---

## Version 2.x

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

See [MIGRATION_V1_TO_V2.md](../status/MIGRATION_V1_TO_V2.md) for complete migration guide.

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

See [deprecated/migrations/MIGRATION_0.8_to_1.0.md](../deprecated/migrations/MIGRATION_0.8_to_1.0.md) for detailed upgrade instructions.

---

## Upcoming Breaking Changes

See [DEPRECATION_POLICY.md](./DEPRECATION_POLICY.md) for the full deprecation timeline.

> **Completed (v2.3.0):** `aragora.modes.gauntlet` (→ `aragora.gauntlet`), `aragora.crawlers` (→ `aragora.connectors`), and `ARAGORA_REQUIRE_DISTRIBUTED_STATE` (→ `ARAGORA_REQUIRE_DISTRIBUTED`) were all removed as planned. No migration action needed.

### Scheduled for Removal: June 1, 2026

| Item | Type | Replacement |
|------|------|-------------|
| API v1 endpoints | API | Use `/api/v2/` endpoints |
| `GET /api/v1/debates` | Endpoint | `GET /api/v2/debates` |
| `POST /api/v1/debate` | Endpoint | `POST /api/v2/debates` |
| `GET /api/v1/agents` | Endpoint | `GET /api/v2/agents` |
| `GET /api/v1/health` | Endpoint | `GET /api/v2/system/health` |

---

## SDK Breaking Changes

### Python SDK

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
4. **Add deprecation warnings** to affected code (see [DEPRECATION_POLICY.md](./DEPRECATION_POLICY.md))
5. **Update SDK documentation** if SDK methods are affected

Use the template at [templates/breaking_change_template.md](../templates/breaking_change_template.md) for consistent documentation.

---

## Related Documentation

- [API Versioning Strategy](../api/API_VERSIONING.md) - Version management and deprecation headers
- [Deprecation Policy](./DEPRECATION_POLICY.md) - Full deprecation process and timeline
- [Migration Guide v1 to v2](../status/MIGRATION_V1_TO_V2.md) - Complete API migration instructions
- [Release Notes](../deployment/RELEASE_NOTES.md) - Full release history with all changes
- [CHANGELOG](../../CHANGELOG.md) - Detailed changelog for all versions

---

*Last updated: 2026-01-31*
