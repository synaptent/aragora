# Technical Debt Tracking

Last Updated: 2026-02-13

## Large File Refactoring Queue

### HIGH Priority -- COMPLETED

#### ~~1. `aragora/observability/metrics.py` (was 3,536 lines)~~
**Status:** DONE. Decomposed into 39 domain-specific modules under `metrics/`. Largest is
`metrics/__init__.py` at 1,110 lines (facade), `metrics/core.py` at 185 lines.

#### ~~2. `aragora/observability/metrics/core.py` (was 2,991 lines)~~
**Status:** DONE. Consolidated into the modular metrics package.

### MEDIUM Priority -- COMPLETED

#### ~~3. `aragora/events/cross_subscribers.py` (was 2,572 lines)~~
**Status:** DONE. Decomposed into `manager.py` (427 lines), `dispatch.py` (327 lines),
`admin.py` (313 lines), plus 4 handler modules in `handlers/`. No file exceeds 650 lines.

#### ~~4. `aragora/server/handlers/admin/health.py` (was 2,549 lines)~~
**Status:** DONE. Extracted `LivenessHandler` (65 lines), `ReadinessHandler` (83 lines),
`StorageHealthHandler` (112 lines). Original `HealthHandler` preserved as facade.

### Keep As-Is (Justified Design)

| File | LOC | Reason |
|------|-----|--------|
| `control_plane/policy.py` | 2,565 | Well-organized domain model, 12 classes with clear purpose |
| `storage/user_store/sqlite_store.py` | 2,439 | Intentional facade pattern over 7 repositories |
| `debate/orchestrator.py` | 1,021 | Core Arena engine, decomposed from 2,180 to 1,021 lines |
| `server/startup.py` | 2,397 | Server initialization complexity justified |
| `server/handlers/social/slack/handler.py` | 2,384 | Slack API handlers, complex by nature |
| `connectors/chat/slack/` | 2,309 | Slack connector, complex by nature |
| `connectors/enterprise/communication/gmail/` | 2,264 | Gmail API integration, justified |
| `services/threat_intelligence.py` | 2,164 | Security service, justified |
| `server/openapi/schemas.py` | 2,045 | API schemas, appropriate grouping |
| `cli/main.py` | 2,013 | CLI entrypoint, appropriate grouping |

## Type Ignore Reduction

Current: 1,628 type: ignore comments (down from 1,643)

**Reduction Strategy:**
1. Focus on `arg-type` ignores (most common, 400+)
2. Add proper type annotations to agent classes
3. Use TypedDict for dictionary parameters
4. Add generics to DataLoader and similar classes

## Exception Handling

BLE001 (blind exception) rule enabled with per-file ignores.
Fixed: 5 high-risk handlers in Phase 3.

**Remaining cleanup:**
- Audit remaining per-file BLE001 ignores
- Add specific exception types where appropriate
- Ensure all exceptions are logged before re-raise

## Test Coverage Gaps

**Comprehensive:** Payment webhooks, chat E2E, CDC-KM integration

**Potential gaps to investigate:**
- Production hardening for MySQL/SQL Server CDC (baseline connectors added)
- CDC event concurrency/race conditions
- Full CDC → Debate context injection (mocked only)

## Deprecated Module Status

The following deprecated modules are **properly maintained** as backwards-compatibility shims:

| Module | Replacement | Status |
|--------|-------------|--------|
| `aragora.modes.gauntlet` | `aragora.gauntlet` | Shim active, emits DeprecationWarning |
| `aragora.crawlers` | `aragora.connectors.repository_crawler` | Shim active, emits DeprecationWarning |
| `aragora.connectors.email.gmail_sync` | New Gmail implementation | Shim active |
| `aragora-py/` (aragora-client) | `aragora-sdk` (PyPI) | Removed (Feb 2026). Use `aragora-sdk` in `sdk/python/` |

**Action:** No removal needed until major version bump. Monitor usage via DeprecationWarning logs.
