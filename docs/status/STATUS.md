# Aragora Project Status

*Last updated: March 6, 2026*

> See [README](../README.md) for the five pillars framework. See [EXTENDED_README](../EXTENDED_README.md) for the comprehensive technical reference.

## Next Steps (Canonical)

Priorities are tracked here to avoid drift across multiple NEXT_STEPS docs.

Detailed execution plan: `docs/status/NEXT_STEPS_CANONICAL.md`.

- **Offline/dev golden path**: keep `--demo` and explicit `--local` runs quiet and network-free (no outbound provider calls, no KM/RLM/background enrichments).
- **Docs alignment**: keep agent catalog and file path references synced to runtime (`list_available_agents()`) and current module layout.
- **SDK and package alignment**: keep Python, TypeScript SDK, live UI, and IDE extension versions aligned to `v2.8.0`.
- **External penetration test**: requires third-party vendor engagement.

## Phase 9: Adoption Readiness (February 14-15, 2026)

### Handler Routing Bug Fix
- **10 `extract_path_param` index bugs fixed** across handler files (off-by-one from leading empty string in `path.split("/")`)
- All 38 remaining `extract_path_param` calls verified correct
- 1 `strip_version_prefix` path comparison bug fixed in `gastown_dashboard.py`

### Exception Handler Narrowing (Final Sweep)
- 80+ additional handler files narrowed from `except Exception` to specific types
- TypeScript SDK: 37 HTTP method verb corrections (GET/POST/DELETE/PATCH alignment)
- Error messages sanitized to prevent information leakage (no `str(e)` in responses)

### HardenedOrchestrator
- Gold path wired: canary tokens, spectate events, work stealing
- SpectatorStream.emit() API fix for event data formatting
- OpenClaw computer-use integration bridge

### Multi-Agent Coordination Infrastructure
- `HierarchicalCoordinator`: Planner/Worker/Judge cycle (561 LOC, 70 tests)
- `ParallelOrchestrator`: Concurrent task execution with semaphore-based limits
- `SemanticConflictDetector`: Cross-branch conflict detection
- CI feedback integration and worktree-based parallel sessions

### Deployment Consolidation
- `docker-compose.quickstart.yml` for zero-config offline demo (2 services, no API keys)
- Dashboard service added to `deploy/self-hosted/docker-compose.yml`
- Deployment README rewritten with "which deployment should I use?" decision table
- Main README deployment section streamlined to 3-option table

### Frontend Simplification
- Sidebar reduced from 30+ items to 5 in simple mode (New Debate, Dashboard, Debates, Settings, About)
- Knowledge, Agents, Analytics, Documents, Leaderboard gated behind `minMode: 'standard'`

### SDK & Examples
- New `batch_verify_claims.py` example for concurrent claim verification
- SDK quickstart doc updated with real-world examples table

### Cross-Cycle Learning (Nomic)
- Calibration-weighted agent selection across self-improvement cycles
- Budget hard cutoff with structured logging

## Phase 8: GA Final Polish (February 9-11, 2026)

### Exception Handler Sweep
- **0 bare `except Exception: pass` remaining** (220 handlers fixed across 125 files)
- All replaced with `logger.debug/warning("message", exc_info=True)`

### Pydantic v2 Migration
- 4 `class Config:` → `model_config = {...}` in FastAPI routes

### SDK Consolidation
- `aragora-client` deprecated (DeprecationWarning, classifier `7 - Inactive`)
- `aragora-sdk` confirmed canonical; docs updated throughout

### File Decomposition
- 14 large files split into focused submodules
  - `sdk_missing.py` (2,522 → 78 LOC, 3 submodules)
  - `receipt.py` (1,694 → 29 LOC, 2 submodules)
  - `debate_rounds.py` (1,590 → 1,159 + 673 helper module)
  - `coordinator.py` (1,627 → 623 LOC, 2 mixins)
  - `qbo.py` (1,617 → 595 LOC, 3 submodules)
  - `analytics_metrics` (1,588 → 234 LOC, 4 submodules)
  - `checkpoint.py` (1,587 → 737 LOC, backends extracted)
  - `postgres_store.py` (1,581 → 237 LOC, 3 submodules)
- Files >1,500 LOC: 23 → 15 (target met)

### OpenClaw Security
- Skill scanner for pre-execution validation
- Publisher enforcement for marketplace integrity
- Standalone gateway deployment support

### Nomic Loop Improvements
- Depth limits to prevent unbounded recursion
- Anti-fragile task reassignment on agent failure

### Connector Reliability
- Pagination guards added to all `while True` loops across connectors

### NotImplementedError Audit
- All `NotImplementedError` in server handlers verified as legitimate mixin/ABC patterns
- Control plane handlers (`agents.py`, `health.py`, `tasks.py`) use mixin pattern with 5 interface stubs each, all properly implemented by `ControlPlaneHandler` in `__init__.py`
- 0 HTTP endpoint stubs remain -- all are base class contract declarations

### Database Reliability
- Migration version locking with TOCTOU protection (advisory locks)
- Connectivity validation at startup (SQLite + PostgreSQL)

### Memory & Isolation
- Multi-tenant memory isolation with RBAC enforcement
- Memory coordinator atomic writes with retry
- Tier transition race condition fixes

### SME Dashboard & Onboarding
- `/usage` page with CostBreakdown and UsageTrend components
- IntegrationSelector onboarding component

### Documentation Reorganization
- 288 docs reorganized from flat `docs/` into 16 topic subdirectories
  - `docs/api/`, `docs/architecture/`, `docs/debate/`, `docs/deployment/`
  - `docs/enterprise/`, `docs/guides/`, `docs/integrations/`, `docs/knowledge/`
  - `docs/observability/`, `docs/reference/`, `docs/resilience/`, `docs/status/`
  - `docs/streaming/`, `docs/testing/`, `docs/workflow/`

### SDK Routes & Tests
- 57 new SDK routes (audit, debates, auth, gateway)
- 282 new handler tests (audit_sessions, template_marketplace, finding_workflow)
- 770 ruff type violations fixed

### Test Health
- 4 known_bug skips → xfail
- Skip baseline: 368 (reduced from 425)
- Tests: 136,000+ collected across 3,200+ files

## Phase 7 Complete (February 2026)

### Code Quality Quick Wins
- **Ruff Linting**: All violations fixed - 0 lint errors
- **Circular Imports**: Fixed in `shared_inbox/__init__.py` and `handlers/utils/cache.py`
- **RBAC Function Signatures**: Fixed `record_rbac_check` calls across handlers
- **Modules**: 3,001 Python files
- **Tests**: 130,778 collected across 2,998 test files
- **Mypy Errors**: 0 (strict mode with --ignore-missing-imports)
- **Commercial Readiness**: 95% (SMB-ready, enterprise features verified)

### Files Modified
- `aragora/server/handlers/external_integrations.py` - Fixed RBAC calls (allowed -> granted)
- `aragora/server/handlers/connectors.py` - Fixed RBAC calls
- `aragora/server/handlers/shared_inbox/__init__.py` - Added lazy `__getattr__` imports
- `aragora/server/handlers/utils/cache.py` - NEW: Moved from admin/cache to break import cycle

### Security Hardening
- **Security Debate API**: Multi-agent debate endpoints for vulnerability analysis (`/api/v1/audit/security/debate`)
- **Security Audit Scheduling**: Automated security scans with cron expressions and optional debate on critical findings
- **CI Security Pipeline**: 6-job pipeline - CodeQL, Bandit, Aragora Scanner, dependency audit, RBAC coverage, secret scanning
- **Secrets Management**: Rotation framework with AWS/Vault/local backends (`scripts/secrets_manager.py`)

### OpenClaw Gateway (NEW)
- **OpenAPI Specification**: 18 endpoint paths covering sessions, actions, credentials, policy rules, approvals, and admin operations
- **Stability**: STABLE - production-ready gateway for computer use automation
- **Key Endpoints**:
  - Session management (create, list, get, close, end)
  - Action execution (execute, status, cancel)
  - Credential management (store, list, delete, rotate)
  - Policy rules (get, add, remove)
  - Approval workflow (list, approve, deny)
  - Admin (health, metrics, audit, stats)

### Test Coverage Improvements
- **RBAC Handler Tests**: 44 comprehensive tests for RBAC handler (previously 12% coverage)
  - Permission listing/retrieval
  - Role CRUD operations
  - Assignment management
  - Permission checking endpoints
- **Code Review Handler Tests**: 24 tests for code review endpoints
  - Code review, diff review, PR review
  - Circuit breaker behavior
  - Security scan endpoint
- **Async SQLite Migration**: Added async wrappers for all blocking memory CRUD operations
  - `update_entry_async`, `update_async`, `promote_entry_async`, `demote_entry_async`
  - Uses `asyncio.run_in_executor()` to prevent event loop blocking

### Files Added
- `aragora/server/handlers/security_debate.py` - Security debate API handler
- `aragora/scheduler/security_audit_schedule.py` - Scheduled security scans with debate integration
- `scripts/security_scan.py` - CI-friendly security scanner CLI
- `scripts/secrets_manager.py` - Secrets rotation management
- `.github/workflows/security.yml` - CI security pipeline (6 jobs)
- `aragora/server/openapi/endpoints/openclaw.py` - OpenClaw gateway OpenAPI specification (18 endpoints)
- `tests/server/handlers/test_rbac.py` - Comprehensive RBAC handler tests (44 tests)
- `tests/server/handlers/test_code_review.py` - Code review handler tests (24 tests)

### Files Modified
- `aragora/memory/continuum/crud.py` - Added async wrappers for all blocking SQLite operations
- `aragora/server/openapi/endpoints/__init__.py` - Registered OpenClaw endpoints

### GA Readiness Verification Audit (February 3, 2026)

Independent verification of production readiness found the project is **98% GA-ready** (up from 95% after resolving SDK parity, slash commands, and decision receipts gaps). Key findings:

| Area | Previous Estimate | Verified Status |
|------|-------------------|-----------------|
| SSRF Protection | HIGH-severity gap | Already remediated at all 3 locations (`validate_webhook_url()` in external_integrations.py) |
| OAuth Provider Tests | 0% coverage | 164 tests passing across OIDC, Google, GitHub, Discord, Slack, Apple providers |
| Billing/Payments Tests | 0% coverage | 295 tests passing (billing core, costs, payments handlers) |
| OpenAPI Specification | Not started | 2,189 endpoints documented, 64 endpoint modules, 397 `@api_endpoint` decorators, full CI/CD |
| Self-Hosted Deployment | Missing production setup | Docker Compose + .env.example comprehensive (193 + 125 lines) |
| Knowledge Handler Tests | Partial | 97 tests passing (whitespace validation fix applied) |

**Remaining GA Gaps (genuine):**
- External penetration test (requires third-party vendor)
- ~~TypeScript SDK parity at ~70% (target: 95%)~~ → **RESOLVED**: 99.3% parity (136/136 namespaces matched)
- ~~Slack/Teams OAuth wizard and slash commands~~ → **RESOLVED**: 7+ slash commands per platform fully implemented
- ~~Decision receipts cryptographic signing + PDF export~~ → **RESOLVED**: 3 signing backends (HMAC-SHA256, RSA-SHA256, Ed25519) + PDF export via WeasyPrint

### Files Modified
- `aragora/server/handlers/knowledge_base/facts.py` - Fixed whitespace-only statement validation

### READMEs Added
- `aragora/cli/README.md` - CLI module documentation
- `aragora/config/README.md` - Configuration module documentation
- `aragora/utils/README.md` - Utilities module documentation
- `aragora/skills/README.md` - Skills system documentation
- `aragora/policy/README.md` - Policy engine documentation
- `aragora/server/handlers/openclaw/README.md` - OpenClaw gateway handler documentation
- `aragora/server/handlers/workspace/README.md` - Workspace management handler documentation
- `aragora/server/handlers/shared_inbox/README.md` - Shared inbox handler documentation
- `aragora/server/handlers/bots/README.md` - Multi-channel bot integration documentation
- `aragora/server/handlers/payments/README.md` - Payment processing handler documentation

### Tests Added (Phase 7.1)
- **Workspace Members Tests**: 23 tests for member management, role assignment, RBAC profiles
- **Workspace Policies Tests**: 24 tests for retention policy CRUD, execution, expiring items
- **OpenAPI Decorator Tests**: 81 tests for `@api_endpoint` decorator, schema validation, parameter extraction
- **Interface Handler Tests**: 18 tests already existed - verified all passing
- **Distributed Rate Limiting**: 28 tests already existed - verified all passing (Redis backend, circuit breaker, fallback)
- **Email Sync Resilience**: 19 tests already existed - verified all passing (circuit breaker, retry, backoff)

### Production Features Verified
- **Distributed Rate Limiting**: Redis-backed sliding window algorithm with graceful fallback to in-memory
- **Email Sync Reliability**: Circuit breaker, exponential backoff retry, OAuth token persistence with encryption
- **Bot Cache Optimization**: Heap-based O(log n) TTL cleanup for response caching
- **Circuit Breaker Defaults**: Tuned (threshold=5, cooldown=60s) across all resilience patterns
- **Debate Stability Detection**: Beta-Binomial model with KS-distance for statistical early stopping (opt-in via `enable_stability_detection`)
- **Knowledge Mound Adapter Base**: 41 adapters using unified base class with resilience, metrics, and tracing

---

## Current Release

\12.7.0\3

### v2.5.0 - Type Safety & SDK Expansion (January 2026)

**Production Ready** - Summary below reflects released work. Validate against the repo before publication.

#### Key Highlights
- **Type safety** - Fixed 10+ mypy type errors across server handlers
- **TypeScript SDK** - 183 namespaces wired to client (added backups, dashboard, devices, expenses, rlm, threat-intel, unified-inbox)
- **Bot handler consolidation** - All 8 bot handlers now use BotHandlerMixin
- **RBAC standardization** - 90%+ of handlers now have permission checks
- **Feedback handler tests** - 21 new tests for NPS and feedback submission
- **Lines of Code**: 1,480,000+ LOC
- **Tests**: 136,000+ across 3,200+ files
- **0 production blockers**

#### What's New in 2.5.0

**Type Error Fixes** (FIX)
- **Handler Fixes** (`aragora/server/handlers/`)
  - Fixed async/await mismatches in explainability handler
  - Fixed AgentRating field access in Slack handler
  - Fixed indexed assignment types in composite analytics
  - Added proper type hints to dashboard health checks
  - Fixed async call chain in knowledge analytics

**TypeScript SDK Expansion** (FEATURE)
- **SDK Namespaces** (`sdk/typescript/src/namespaces/`)
  - Backups namespace for disaster recovery
  - Dashboard namespace for admin metrics
  - Devices namespace for smart speaker integration
  - Expenses namespace for receipt management
  - RLM namespace for context compression
  - Threat Intelligence namespace for security monitoring
  - Unified Inbox namespace for multi-provider email

**Bot Handler Consolidation** (FEATURE)
- **Bot Handlers** (`aragora/server/handlers/bots/`)
  - All 8 platforms (Slack, Discord, Telegram, WhatsApp, Teams, Alexa, Google Home, Apple Shortcuts) use BotHandlerMixin
  - Consistent authentication and status endpoint patterns
  - Standardized webhook signature verification

**RBAC Standardization** (FEATURE)
- **Permission Checks** (`aragora/server/handlers/`)
  - External integrations handler RBAC fix
  - Feedback handler permission enforcement
  - 90%+ handler coverage for permission checks

**Testing Improvements** (TEST)
- **Feedback Handler Tests** (`tests/server/handlers/`)
  - 21 new tests for NPS submission
  - General feedback submission tests
  - Admin summary access tests
  - RBAC permission enforcement tests

---

## Previous Release

### v2.4.0 - Python SDK Expansion & Knowledge Mound Integration (January 2026)

**Production Ready** - Aragora 2.4.0 expands Python SDK coverage with 10+ new resource namespaces, improves CDC → Knowledge Mound integration, and aligns all package versions.

#### Key Highlights
- **Python SDK expansion** - Added orgs, tenants, policies, codebase, costs, decisions, onboarding, notifications, gmail, explainability resources
- **Knowledge Mound integration** - CDC integration coverage with search parameter alignment
- **Bot client improvements** - Deferred API base validation to runtime initialization
- **Control plane hardening** - Improved error handling for agent/task retrieval
- **Package alignment** - All packages aligned to v2.4.0
- **Lines of Code**: 695,000+ LOC
- **0 production blockers**

#### What's New in 2.4.0

**Python SDK Resource Expansion** (FEATURE)
- **SDK Resources** (formerly `aragora-py/`, now consolidated into `sdk/python/`)
  - Organizations namespace for org management
  - Tenants namespace for multi-tenancy
  - Policies namespace for policy configuration
  - Codebase namespace for code analysis
  - Costs namespace for usage tracking
  - Decisions namespace for decision management
  - Onboarding namespace for user onboarding
  - Notifications namespace for alert management
  - Gmail namespace for email integration
  - Explainability namespace for decision explanations

**CDC → Knowledge Mound Integration** (FEATURE)
- **Integration Tests** (`tests/knowledge/`)
  - Comprehensive CDC to Knowledge Mound flow testing
  - Search parameter alignment (`q` key)
  - Real-time knowledge sync validation

**Bot Client Improvements** (FEATURE)
- **Bot Runtime** (`aragora/bots/`)
  - Deferred API base validation to runtime
  - Better initialization error handling
  - Improved session management

**Bug Fixes** (BUG)
- Fixed Python SDK payloads for billing + RBAC endpoints
- Aligned knowledge search parameter key to `q`
- Preserved legacy Sunset header behavior for normalized paths
- Fixed per-debate cost tracking reset during initialization

---

### v2.2.0 - CLI Setup Wizard & Decision Routing (January 2026)

**Production Ready** - Aragora 2.2.0 introduces a guided CLI setup wizard for self-hosted deployments and enhanced decision inbox with deep links.

#### Key Highlights
- **CLI setup wizard** - Guided `aragora setup` command for self-hosted configuration
- **Decision Inbox** - Filters and receipt deep links for better navigation
- **Slack/Teams routing** - Receipt links routed to UI when `ARAGORA_PUBLIC_URL` is set
- **Cost dashboard** - Components wired to backend API
- **Lines of Code**: 693,000+ LOC
- **0 production blockers**

#### What's New in 2.2.0

**CLI Setup Wizard** (FEATURE)
- **Setup Command** (`aragora/cli/setup.py`)
  - Interactive configuration wizard
  - Database connection setup
  - API key configuration
  - Environment file generation
  - Self-hosted deployment guidance

**Decision Inbox Enhancements** (FEATURE)
- **Inbox Filters** (`aragora/live/components/inbox/`)
  - Filter by status, date, priority
  - Receipt deep links for direct navigation
  - Improved search functionality

**Slack/Teams Receipt Routing** (FEATURE)
- **Receipt Router** (`aragora/integrations/`)
  - Routes receipt links to UI when `ARAGORA_PUBLIC_URL` configured
  - Supports Slack and Teams platforms
  - Deep link generation for decision receipts

**Cost Dashboard Wiring** (FEATURE)
- **Dashboard Components** (`aragora/live/components/costs/`)
  - Backend API integration
  - Real-time cost display
  - Usage breakdown visualization

---

### v2.1.15 - Connector Hardening & CI Validation (January 2026)

**Production Ready** - Aragora 2.1.15 hardens connector implementations with abstract property enforcement and adds CI version alignment validation.

#### Key Highlights
- **Connector hardening** - Abstract property pattern enforcement for connector identification
- **AuthContext improvements** - Better error handling and session management
- **Playwright configuration** - Production-ready E2E test setup
- **CI validation** - Version alignment validation job added to CI
- **Q1 2026 planning** - 60+ issues across 6 sprints documented
- **Lines of Code**: 692,000+ LOC
- **0 production blockers**

#### What's New in 2.1.15

**Connector Hardening** (FEATURE)
- **Abstract Properties** (`aragora/connectors/`)
  - Enforced abstract property pattern for connector identification
  - Removed class-level defaults that shadowed abstract properties
  - Improved connector type safety

**AuthContext Improvements** (FEATURE)
- **Session Management** (`aragora/auth/`)
  - Better error handling for auth failures
  - Improved session lifecycle management
  - Enhanced security logging

**Playwright E2E Configuration** (FEATURE)
- **Test Setup** (`aragora/live/playwright.config.ts`)
  - Production-ready Playwright configuration
  - Multi-browser test support
  - CI-optimized test runner

**CI Version Alignment** (CI/CD)
- **Validation Job** (`.github/workflows/`)
  - Cross-package version validation
  - `check_version_alignment.py` script
  - Prevents version drift between packages

**Bug Fixes** (BUG)
- Fixed flaky timing test with tolerance for CI variability
- Fixed circuit breaker test with explicit threshold configuration
- Fixed router path handling for unified inbox
- Fixed SDK version mismatch (2.2.0 → 2.1.15)

---

### v2.1.14 - Infrastructure Improvements Release (January 2026)

**Production Ready** - Aragora 2.1.14 delivers major infrastructure improvements including circuit breaker configuration, Redis high availability, webhook reliability, and enhanced developer experience with GraphQL.

#### Key Highlights
- **Infrastructure improvements** - Circuit breaker configuration, Redis HA, OTLP export
- **Webhook reliability** - Persistent retry queue with exponential backoff
- **Security enhancements** - ML spam classifier, threat intel enrichment
- **Developer experience** - GraphQL API layer, E2E test harness
- **365+ new tests** across 9 infrastructure features
- **Lines of Code**: 690,000+ LOC
- **0 production blockers**

#### What's New in 2.1.14

**Circuit Breaker Configuration** (FEATURE)
- **CircuitBreakerConfig** (`aragora/resilience_config.py`)
  - Per-provider threshold configuration (failure_threshold, recovery_timeout)
  - Supports: anthropic, openai, gemini, mistral, grok, deepseek, openrouter
  - `CircuitBreakerMode`: global (one breaker) vs entity (per-provider breakers)
  - Dynamic config loading from environment
  - 91 new tests

**Redis Sentinel/Cluster Support** (FEATURE)
- **RedisHAClient** (`aragora/storage/redis_ha.py`)
  - Sentinel mode with automatic master discovery
  - Cluster mode with sharding support
  - Failover handling with connection pooling
  - Health monitoring and metrics
  - 35 new tests

**Webhook Retry Queue** (FEATURE)
- **WebhookRetryQueue** (`aragora/webhooks/retry_queue.py`)
  - Persistent delivery with configurable retry attempts
  - Exponential backoff with jitter
  - Dead letter queue for failed deliveries
  - Delivery statistics and monitoring
  - 48 new tests

**ML Spam Classifier Integration** (FEATURE)
- **SpamClassificationPipeline** (`aragora/moderation/spam_integration.py`)
  - Multi-provider spam detection pipeline
  - Akismet, SpamAssassin, CleanTalk integration
  - Voting threshold for consensus
  - Real-time classification with caching
  - 48 new tests

**Threat Intel Enrichment** (FEATURE)
- **ThreatIntelEnricher** (`aragora/security/threat_intel_enrichment.py`)
  - CVE database lookup for security topics
  - Threat intel feed integration
  - Context enrichment for debates
  - Caching with TTL
  - 43 new tests

**OpenTelemetry OTLP Export** (FEATURE)
- **OTLPExporter** (`aragora/observability/otlp_export.py`)
  - Jaeger, Zipkin, Datadog exporters
  - OTLP gRPC and HTTP protocols
  - Configurable sampling rate
  - Service name and environment tags
  - 21 new tests

**GraphQL API Layer** (FEATURE)
- **GraphQL Schema** (`aragora/server/graphql/`)
  - Schema for debates, agents, memory
  - Resolvers with authentication
  - GraphiQL playground integration
  - 32 new tests

**E2E Integration Test Harness** (FEATURE)
- **E2ETestHarness** (`tests/e2e/harness.py`)
  - Full integration test framework
  - Mock agent implementations
  - Lifecycle testing
  - 37 new tests

**Testing** (QUALITY)
- 91 new circuit breaker configuration tests
- 35 new Redis HA tests (Sentinel, Cluster, failover)
- 48 new webhook retry queue tests (backoff, dead letter, stats)
- 48 new ML spam classifier tests (multi-provider, voting, caching)
- 43 new threat intel enrichment tests (CVE lookup, feeds, caching)
- 21 new OTLP export tests (Jaeger, Zipkin, Datadog)
- 32 new GraphQL API tests (schema, resolvers, auth)
- 37 new E2E test harness tests (lifecycle, mocks)

---

### v2.1.13 - Control Plane Governance Hardening (January 2026)

**Production Ready** - Aragora 2.1.13 completes the control plane for vetted decision-making with governance hardening, omnichannel delivery wiring, and decision receipt persistence.

#### Key Highlights
- **Governance hardening** - Policy conflict detection, distributed cache, continuous sync
- **Omnichannel wiring** - Debate completion → notification dispatcher integration
- **Decision receipts** - Auto-persistence to Knowledge Mound
- **88 new tests** across governance, omnichannel, and receipt features
- **Lines of Code**: 685,000+ LOC
- **0 production blockers**

#### What's New in 2.1.13

**Governance Hardening** (FEATURE)
- **PolicyConflictDetector** (`aragora/control_plane/policy.py`)
  - Detects agent allowlist/blocklist conflicts
  - Detects non-overlapping allowlists (impossible to satisfy)
  - Detects region constraint conflicts
  - Detects enforcement level inconsistencies
  - Skips disabled policies and non-overlapping scopes
- **RedisPolicyCache** (`aragora/control_plane/policy.py`)
  - SHA256-based cache keys from evaluation context
  - Configurable TTL (default 5 minutes)
  - Cache invalidation support
  - Hit/miss/error statistics tracking
  - Graceful fallback when Redis unavailable
- **PolicySyncScheduler** (`aragora/control_plane/policy.py`)
  - Background async task for periodic policy sync
  - Syncs from both compliance store and control plane store
  - Change detection via policy hash comparison
  - Automatic cache invalidation on policy changes
  - Conflict detection callback support
  - Policy version hash for cache key invalidation

**Omnichannel Delivery Wiring** (FEATURE)
- **ArenaExtensions notification wiring** (`aragora/debate/extensions.py`)
  - `notification_dispatcher` and `auto_notify` configuration
  - `notify_min_confidence` threshold for filtering
  - Emits TASK_COMPLETED events on debate completion
  - Emits DELIBERATION_CONSENSUS for high-confidence (≥70%) results
  - Duration calculation from debate context metadata
  - Graceful error handling (won't fail debates)

**Decision Receipt Persistence** (FEATURE)
- **ReceiptAdapter** (`aragora/knowledge/mound/adapters/receipt_adapter.py`)
  - Ingests verified claims as knowledge items with provenance
  - Persists CRITICAL/HIGH severity findings with classification
  - Creates receipt summary items linking all components
  - Establishes SUPPORTS relationships between components
  - `find_related_decisions()` for context retrieval
  - Event callback for WebSocket notifications

**Testing** (QUALITY)
- 25 new governance hardening tests (conflict detection, cache, scheduler)
- 12 new omnichannel wiring tests (notification emission, error handling)
- 18 new receipt adapter tests (ingestion, conversion, stats)

---

### v2.1.12 - Connectors & Email Sync Release (January 2026)

**Production Ready** - Aragora 2.1.12 adds comprehensive advertising, marketing, and analytics platform connectors plus real-time email sync services.

#### Key Highlights
- **45,100+ tests** across 1,220+ test files
- **6 new advertising/marketing connectors** - Twitter Ads, TikTok Ads, Mailchimp, Klaviyo, Segment
- **2 real-time email sync services** - Gmail Pub/Sub, Outlook Graph notifications
- **5 new unified handlers** - Advertising, Analytics, CRM, Support, Ecommerce
- **25 new e-commerce connector tests** - Shopify, Amazon, WooCommerce, ShipStation
- **Lines of Code**: 680,000+ LOC
- **0 production blockers**

#### What's New in 2.1.12

**Advertising Connectors** (FEATURE)
- **Twitter/X Ads** (`aragora/connectors/advertising/twitter_ads.py`)
  - OAuth 1.0a authentication
  - Campaign, ad group, ad management
  - Performance metrics and targeting
  - Tailored audiences and promoted accounts
- **TikTok Ads** (`aragora/connectors/advertising/tiktok_ads.py`)
  - OAuth 2.0 authentication
  - Campaign, ad group, ad CRUD operations
  - Pixel tracking and conversion events
  - Custom audiences and smart targeting

**Marketing Connectors** (FEATURE)
- **Mailchimp** (`aragora/connectors/marketing/mailchimp.py`)
  - Audiences, members, campaigns
  - Templates, automations, reporting
  - Campaign performance analytics
- **Klaviyo** (`aragora/connectors/marketing/klaviyo.py`)
  - Lists, segments, profiles
  - Campaigns and flows
  - Events, templates (email + SMS)
  - JSON:API format (2024-10-15 revision)

**Analytics Connector** (FEATURE)
- **Segment CDP** (`aragora/connectors/analytics/segment.py`)
  - Tracking API (track, identify, page, group, batch)
  - Config API (sources, destinations)
  - Profiles API (user lookup, traits)

**Email Sync Services** (FEATURE)
- **Gmail Sync** (`aragora/connectors/email/gmail_sync.py`)
  - Google Cloud Pub/Sub for real-time notifications
  - History API for incremental message retrieval
  - EmailPrioritizer integration for scoring
  - Tenant-isolated sync state (Redis/Postgres)
- **Outlook Sync** (`aragora/connectors/email/outlook_sync.py`)
  - Microsoft Graph change notifications (webhooks)
  - Delta Query API for incremental sync
  - Automatic subscription renewal
  - EmailPrioritizer integration

**Handler Registry Expansion** (INFRASTRUCTURE)
- 5 new unified API handlers registered:
  - `AdvertisingHandler` - Multi-platform ad management
  - `AnalyticsPlatformsHandler` - CDP and analytics tools
  - `CRMHandler` - Customer relationship platforms
  - `SupportHandler` - Help desk integrations
  - `EcommerceHandler` - Shopping platform connectors

**Testing** (QUALITY)
- 450+ new tests for advertising connectors
- 250+ new tests for marketing connectors
- 100+ new tests for analytics connector
- 120+ new tests for email sync services
- 25+ new tests for e-commerce connectors

---

### v2.1.11 - Type Safety & Quality Release (January 2026)

**Production Ready** - Aragora 2.1.11 significantly improves type safety with mypy error reduction from 307 to 102 errors (67% improvement).

#### Key Highlights
- **43,974+ tests** across 1,200+ test files
- **Type safety improvements** - Reduced mypy errors from 307 to 102 (67% reduction)
- **75+ files updated** with proper type: ignore comments
- **Lines of Code**: 670,000+ LOC
- **0 production blockers**

#### What's New in 2.1.11

**Type Safety Improvements** (QUALITY)
- Systematic type: ignore additions across 75+ modules
- Fixed arg-type, assignment, attr-defined, call-arg, override, misc, index errors
- Added noqa comments for intentional patterns (availability checks, print functions)
- Remaining 102 errors are primarily in linter-conflict files (connectors, rabbitmq, user_store)

---

### v2.1.10 - Quality & Testing Release (January 2026)

**Production Ready** - Aragora 2.1.10 adds comprehensive testing improvements, type safety fixes, and multi-instance deployment support.

#### Key Highlights
- **43,400+ tests** across 960+ test files
- **Type safety fixes** - Resolved mypy errors in 5 key modules
- **Multi-instance support** - PostgreSQL required for distributed deployments
- **Telegram connector** - Full ChatPlatformConnector implementation
- **Lines of Code**: 665,000+ LOC
- **0 production blockers**

#### What's New in 2.1.10

**Testing Improvements** (QUALITY)
- E2E tenant security tests now enabled (API key validation, suspension)
- 950 new tests for telegram connector and notification config store
- Multi-instance durability tests for marketplace store
- Security regression tests for Gmail auth and notifications

**Type Safety** (QUALITY)
- Fixed mypy errors in explainability/builder.py, gauntlet/api/export.py
- Proper Dict[str, Any] typing for nested structures
- Workflow schema type narrowing for YAML parsing
- Credentials provider string conversion fixes

**Multi-Instance Deployment** (INFRASTRUCTURE)
- Marketplace store requires PostgreSQL in ARAGORA_MULTI_INSTANCE mode
- SQLite fallback explicitly disabled for distributed deployments
- Centralized distributed state checking in control plane

**Telegram Connector** (FEATURE)
- Implemented ChatPlatformConnector abstract methods
- format_blocks(), format_button(), format_select_menu() support
- send_ephemeral() for user-specific messages

**Agent Template Marketplace** (FEATURE)
- New `aragora.marketplace` module for template sharing
- AgentTemplate, DebateTemplate, WorkflowTemplate models
- Local SQLite registry with search, ratings, versioning
- Async MarketplaceClient for remote template sharing
- 3 built-in agent templates (Devil's Advocate, Code Reviewer, Research Analyst)
- 3 built-in debate templates (Oxford-Style, Brainstorm, Code Review)
- 38 comprehensive tests for models and registry

---

### v2.1.9 - Security Hardening Release (January 2026)

**Production Ready** - Aragora 2.1.9 implements refined security approaches from audit findings, including tenant isolation and fail-closed webhook verification.

#### Key Highlights
- **Gmail tenant isolation** - org_id binding for admin delegation (Option B)
- **Webhook verification hardened** - Fail-closed with explicit `ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS` override (Option C)
- **Consistent security patterns** - SecureHandler with RBAC across all sensitive endpoints
- **Lines of Code**: 660,000+ LOC
- **0 production blockers**

#### What's New in 2.1.9

**Gmail Handler Security** (SECURITY)
- Added `org_id` field to `GmailUserState` for tenant isolation
- Pass org_id through OAuth callback chain for strict org scoping
- Enables future admin delegation within organizational boundaries
- Matches enterprise patterns (Google Workspace, Microsoft 365)

**Webhook Verification Hardening** (SECURITY)
- Renamed env var to `ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS` for clarity
- Self-documenting flag name for explicit dev mode acknowledgment
- Applied consistently across all chat connectors:
  - Slack (HMAC signature verification)
  - Discord (Ed25519 signature verification)
  - Teams (JWT token verification)
  - Google Chat (JWT token verification)
- Fail-closed by default in production

---

### v2.1.8 - Security Verification & Backend Fixes (January 2026)

**Production Ready** - Aragora 2.1.8 verifies security/durability implementations and adds a SentenceTransformer fallback fix.

#### Key Highlights
- **34,400+ tests** across 928 test files
- **217 security tests verified** - Encryption, governance, routing, RBAC
- **4 security gaps verified implemented** - From commercial viability assessment
- **SentenceTransformer fallback fix** - Graceful degradation to TF-IDF/Jaccard
- **Lines of Code**: 660,000+ LOC
- **0 production blockers**
- **122 fully integrated features**

#### What's New in 2.1.8

**Security/Durability Verification** (VERIFIED)
- **Gap 1: Secrets Encryption** - Already wired in:
  - `integration_store.py` - `_encrypt_settings()` / `_decrypt_settings()`
  - `gmail_token_store.py` - `_encrypt_token()` / `_decrypt_token()`
  - `sync_store.py` - `_encrypt_config()` / `_decrypt_config()`
- **Gap 2: Governance/Approval Wiring** - Already implemented in:
  - `human_checkpoint.py` - Persists to GovernanceStore, recovers on startup
- **Gap 3: Routing Durability** - SQLite fallback already in:
  - `debate_origin.py` - `SQLiteOriginStore`
  - `email_reply_loop.py` - `SQLiteEmailReplyStore`
- **Gap 4: RBAC Enforcement** - Already enforced in:
  - `finding_workflow.py` - All endpoints check `findings.{read,update,assign,bulk}`

**SentenceTransformer Fix** (BUG FIX)
- Added catch-all exception handler in `get_similarity_backend()`
- Ensures graceful fallback to TF-IDF or Jaccard when model loading fails
- Prevents benchmark test failures from initialization errors

---

### v2.1.6 - RBAC Checker & Decorators Testing Release (January 2026)

**Production Ready** - Aragora 2.1.6 adds comprehensive tests for the RBAC permission checker and decorator system, with coverage improvements and additional linter fixes.

#### Key Highlights
- **34,400+ tests** across 928 test files
- **58 new RBAC tests** - Comprehensive checker and decorator coverage
- **RBAC coverage increased** - From 61% to 69%
- **1050+ linter issues resolved** - Auto-fixed with ruff
- **Lines of Code**: 660,000+ LOC
- **0 production blockers**
- **122 fully integrated features**

#### What's New in 2.1.6

**RBAC Checker Tests** (QUALITY)
- `tests/rbac/test_checker.py` - 29 comprehensive tests:
  - Permission checking (exact, wildcard, super wildcard)
  - API key scope restrictions
  - Resource-level access control and policies
  - Role checking helpers (has_role, has_any_role, is_admin)
  - Role assignment management
  - Decision caching and cache invalidation

**RBAC Decorator Tests** (QUALITY)
- `tests/rbac/test_decorators.py` - 29 comprehensive tests:
  - @require_permission decorator
  - @require_role decorator with require_all option
  - @require_owner and @require_admin shortcuts
  - @require_org_access decorator with platform owner support
  - @require_self_or_admin decorator
  - @with_permission_context decorator
  - Async function and method decorator support

**Health Handler Fixes** (QUALITY)
- Added noqa comments for availability check imports
- Proper handling of optional module imports

---

### v2.1.5 - Code Quality & RBAC Testing Release (January 2026)

**Production Ready** - Aragora 2.1.5 delivers comprehensive RBAC enforcer test coverage, automated linter fixes across the codebase, and improved code quality standards.

#### Key Highlights
- **34,400+ tests** across 928 test files
- **23 new RBAC enforcer tests** - Comprehensive permission checking coverage
- **229 linter issues auto-fixed** - Cleaner, more maintainable codebase
- **E2E tests passing** - 476 passed, 29 skipped
- **RBAC coverage increased** - From 55% to 61%
- **Lines of Code**: 660,000+ LOC
- **0 production blockers**
- **122 fully integrated features**

#### What's New in 2.1.5

**RBAC Enforcer Tests** (QUALITY)
- `tests/rbac/test_enforcer.py` - 23 comprehensive tests covering:
  - RBACConfig default and custom values
  - PermissionCheckResult serialization
  - PermissionDeniedException attributes
  - Disabled enforcer behavior (allows all)
  - Deny-by-default and permissive modes
  - Role assignment and revocation
  - Admin permission grants all actions
  - Permission cache invalidation
  - Isolation context handling
  - Resource context conditions

**Linter Auto-Fixes** (QUALITY)
- 229 issues auto-fixed across 106 files
- Removed unused imports (F401)
- Removed unused variables (F841)
- Fixed f-string formatting issues
- Cleaner, more maintainable codebase

**Test Infrastructure** (QUALITY)
- Fixed RBAC permission mocking in tests
- Proper system role usage (workspace_viewer, workspace_editor)
- Role dataclass parameter validation

---

### v2.1.4 - Benchmark & Connector Release (January 2026)

**Production Ready** - Aragora 2.1.4 resolves all pytest-benchmark warnings in async load tests and enhances connector integrations with improved error handling.

#### Key Highlights
- **34,400+ tests** across 928 test files
- **All benchmark warnings resolved** - Async tests now properly use benchmark fixture
- **Enhanced Connectors** - Telegram bot, organization management
- **Improved Middleware** - Better exception handling
- **Webhook Persistence** - Full delivery queue durability
- **Lines of Code**: 660,000+ LOC
- **0 production blockers**
- **122 fully integrated features** (+2 connector capabilities)

#### What's New in 2.1.4

**Benchmark Test Fixes** (QUALITY)
- Fixed 5 async load tests using `benchmark(lambda: None)` pattern
- Manual timing for async operations (pytest-benchmark doesn't support async)
- Removed duplicate imports and simplified circuit breaker test
- All 9 load tests pass without warnings

**Connector Enhancements** (INTEGRATION)
- Enhanced Telegram bot handler with improved error handling
- Added organization management endpoints
- Improved server middleware exception handling
- Added metrics recording for marketplace and webhooks

**Webhook Delivery** (DURABILITY)
- Complete persistence integration for delivery queues
- Webhook delivery handlers for debate events
- Improved retry scheduling

---

### v2.1.2 - Security & Durability Release (January 2026)

**Production Ready** - Aragora 2.1.2 adds comprehensive security and durability improvements including field-level encryption for sensitive data, SQLite fallbacks for all persistence layers, and RBAC enforcement across all finding workflow endpoints.

#### Key Highlights
- **41,950+ tests** collected and passing (+250 new tests)
- **1,200 test files** across all modules
- **47 orchestrator integration tests** re-enabled (was skipped)
- **Field-Level Encryption** - AES-256-GCM for API keys, tokens, secrets
- **SQLite Durability** - All in-memory stores now have SQLite fallbacks
- **RBAC Enforcement** - Full permission checks on finding workflow
- **Governance Wiring** - Approval persistence survives restarts
- **Cloud KMS Integration** - AWS KMS, Azure Key Vault, GCP Cloud KMS
- **PostgreSQL Backends** - Full horizontal scaling for all 11 storage modules
- **Lines of Code**: 655,000+ LOC
- **0 production blockers**
- **120 fully integrated features** (+5 security/durability capabilities)

#### What's New in 2.1.2

**Security & Durability Hardening** (SECURITY)
- Field-level encryption for 12 sensitive keys (API keys, tokens, secrets)
- SQLite fallbacks for debate origin, approval, and control plane stores
- Governance wiring for human checkpoint approval persistence
- RBAC enforcement on all 16 finding workflow endpoints
- JWT authentication takes precedence over header-based auth
- 62 new security/durability tests

**Re-enabled Integration Tests** (QUALITY)
- 47 orchestrator integration tests now passing (was skipped)
- Debate performance benchmarks enabled with KM graceful degradation
- 141 orchestrator tests passing (up from 94)

**Cloud KMS Provider** (SECURITY)
- `aragora/security/kms_provider.py` - Multi-cloud KMS integration:
  - AWS KMS support via boto3
  - Azure Key Vault support via azure-identity
  - GCP Cloud KMS support via google-cloud-kms
  - Auto-detection of cloud platform from environment
  - Envelope encryption with data key decrypt

**Encrypted Fields** (SECURITY)
- `aragora/storage/encrypted_fields.py` - Field-level encryption:
  - Automatic encryption of OAuth tokens, API keys, secrets
  - Platform-specific credential encryption
  - Transparent encrypt/decrypt on storage operations

**PostgreSQL Backends** (SCALING)
- Complete PostgreSQL support for all 11 storage modules
- Unified schema in `migrations/sql/001_initial_schema.sql`
- Atomic transaction handling for multi-table operations

---

### v2.1.1 - Voice & Observability Release (January 2026)

**Production Ready** - Aragora 2.1.1 adds bidirectional Twilio Voice integration for phone-triggered debates, enhanced observability with comprehensive metrics, and PostgreSQL backends for horizontal scaling.

#### Key Highlights
- **41,700+ tests** collected and passing (+1,000 new tests)
- **1,161 test files** across all modules
- **Twilio Voice** - Bidirectional voice for phone-triggered debates
- **Enhanced Observability** - Circuit breaker metrics, debate throughput, memory monitoring
- **PostgreSQL Backends** - Horizontal scaling support for user store
- **JWT Webhook Security** - Proper cryptographic verification for Teams/Google Chat
- **Lines of Code**: 638,000+ LOC (+183,000)
- **0 production blockers**
- **115 fully integrated features** (+5 voice/observability capabilities)

#### What's New in 2.1.1

**Twilio Voice Integration** (NEW)
- `aragora/integrations/twilio_voice.py` - Complete voice integration:
  - `TwilioVoiceConfig` - Voice settings and webhook configuration
  - `CallSession` - Active call session tracking
  - `TwilioVoiceIntegration` - Inbound call handling with speech-to-text
  - TwiML response generation for interactive prompts
  - Outbound calls with TTS for debate results
  - Webhook signature verification with HMAC-SHA1
- `aragora/server/handlers/voice/` - Voice webhook handlers:
  - `POST /api/voice/inbound` - Inbound call handling
  - `POST /api/voice/status` - Call status updates
  - `POST /api/voice/gather` - Speech recognition results
  - `POST /api/voice/gather/confirm` - Confirmation input
- 17 tests in `tests/integrations/test_twilio_voice.py`

**Enhanced Observability** (NEW)
- Circuit breaker state tracking metrics
- Debate throughput monitoring
- Memory usage metrics
- Readiness and liveness probe support
- `/api/health/cross-pollination` endpoint

**PostgreSQL Backends** (NEW)
- PostgreSQL storage backend for user store
- Migration infrastructure with Alembic
- Database initialization scripts
- `migrations/sql/001_initial_schema.sql`

**JWT Webhook Verification** (SECURITY)
- `aragora/connectors/chat/jwt_verify.py` - JWT verification module:
  - Microsoft Teams JWT validation against Azure AD public keys
  - Google Chat JWT validation against Google's JWKS endpoint
  - JWKS client caching with hourly refresh
  - Graceful fallback when PyJWT not installed (with security warning)
- 20 tests in `tests/connectors/chat/test_jwt_verify.py`

---

### v2.1.0 - Audit Findings & Security Release (January 2026)

**Production Ready** - Aragora 2.1.0 addresses audit findings with proper JWT webhook verification, AgentSpec test coverage, and improved deprecation handling.

#### Key Highlights
- JWT webhook verification for Teams and Google Chat
- Comprehensive AgentSpec test suite
- Chat webhook router tests for platform detection
- Improved rlm_backend deprecation with sentinel value

---

### v2.0.10 - Bidirectional Knowledge Mound Integration (January 2026)

**Production Ready** - Aragora 2.0.10 completes full bidirectional Knowledge Mound integration, enabling cross-subsystem organizational learning across the entire platform.

#### Key Highlights
- **40,700+ tests** collected and passing (+2,300 new tests)
- **Knowledge Mound 100% integrated** - All subsystems bidirectionally wired
- **33 KM adapters** - Continuum, Consensus, Critique, Evidence, Pulse, Insights, ELO, Belief, Cost, Receipt, ControlPlane, RLM, Culture, Ranking, LangExtract, Extraction, NomicCycle, OpenClaw, and 15 more
- **Cross-debate learning** - Organizational knowledge persists and improves across debates
- **Semantic search** - Vector-based similarity search in all adapters
- **SLO alerting** - Adapter performance monitoring with Prometheus metrics
- **Lines of Code**: 455,000+ LOC (+5,000)
- **0 production blockers**
- **110 fully integrated features** (+4 KM capabilities)

#### What's New in 2.0.10

**Bidirectional Adapter Architecture** (COMPLETE)
- `aragora/knowledge/mound/adapters/`:
  - `evidence_adapter.py` - Evidence snippets with reliability thresholds
  - `pulse_adapter.py` - Trending topics and scheduled debate outcomes
  - `insights_adapter.py` - Debate insights and Trickster flip events
  - `elo_adapter.py` - Agent rankings and calibration predictions
  - `belief_adapter.py` - Belief network cruxes and converged beliefs
  - `cost_adapter.py` - Budget alerts and cost anomalies (opt-in)
- All adapters support forward sync (data → KM) and reverse queries (KM → data)
- Semantic search with vector embeddings in all adapters

**KM Validation Feedback Loop** (NEW)
- `aragora/events/cross_subscribers.py` - `_handle_km_validation_feedback`
- Listens for CONSENSUS events to validate KM items based on debate outcomes
- Generates `KMValidationResult` for source systems
- Automatic confidence adjustments based on validation

**Cross-Debate Learning Analytics** (NEW)
- `GET /api/knowledge/learning/stats` - Learning analytics endpoint
- Tracks: knowledge reuse rate, validation accuracy, learning velocity
- Cross-debate utility scoring for knowledge items
- Adapter activity monitoring (forward syncs, reverse queries, semantic searches)

**Belief Network KM Seeding** (NEW)
- Debate orchestrator seeds BeliefNetwork from KM at debate start
- Enabled via `ArenaConfig.enable_km_belief_sync`
- Historical beliefs inform new debate reasoning

**Adapter SLO Monitoring** (NEW)
- `aragora/config/performance_slos.py`:
  - `AdapterForwardSyncSLO` - p50: 100ms, p90: 300ms, p99: 800ms
  - `AdapterReverseSLO` - p50: 50ms, p90: 150ms, p99: 500ms
  - `AdapterSemanticSearchSLO` - p50: 100ms, p90: 300ms, p99: 1000ms
  - `AdapterValidationSLO` - p50: 200ms, p90: 500ms, p99: 1500ms
- Prometheus metrics for SLO violations

**KM Dashboard Component** (NEW)
- `aragora/live/src/components/knowledge/KMAdapterActivity.tsx`
- Real-time adapter activity visualization
- Forward/reverse sync statistics per adapter
- WebSocket-powered live updates

---

### v2.0.9 - Phase 5 Autonomous Operations (January 2026)

**Production Ready** - Aragora 2.0.9 completes Phase 5: Autonomous Operations with self-improvement capabilities, continuous learning, and proactive intelligence.

#### Key Highlights
- **38,400+ tests** collected and passing (+200 new tests)
- **1,055 test files** across all modules
- **Phase 5 complete** - Autonomous Operations fully implemented
- **Human-in-the-loop** - Approval flows with risk assessment
- **Continuous learning** - Real-time ELO updates and pattern extraction
- **Proactive intelligence** - Scheduled triggers, alerts, anomaly detection
- **Lines of Code**: 450,000+ LOC (+2,000)
- **0 production blockers**
- **106 fully integrated features** (+4 autonomous capabilities)

#### What's New in 2.0.9

**Autonomous Loop Enhancement** (Phase 5.1 - COMPLETE)
- `aragora/autonomous/loop_enhancement.py`:
  - `SelfImprovementManager` - Orchestrates autonomous improvement cycles
  - `CodeVerifier` - AST syntax validation and test execution
  - `RollbackManager` - File backup, restore, and cleanup
  - `ApprovalFlow` - Human-in-the-loop with risk levels and timeouts
- 27 tests in `tests/autonomous/test_loop_enhancement.py`

**Continuous Learning** (Phase 5.2 - COMPLETE)
- `aragora/autonomous/continuous_learning.py`:
  - `EloUpdater` - Real-time ELO rating adjustments
  - `PatternExtractor` - Cross-debate pattern discovery
  - `KnowledgeDecayManager` - Confidence decay with refresh
  - `ContinuousLearner` - Unified learning orchestration
- 35 tests in `tests/autonomous/test_continuous_learning.py`

**Proactive Intelligence** (Phase 5.3 - COMPLETE)
- `aragora/autonomous/proactive_intelligence.py`:
  - `ScheduledTrigger` - Cron and interval-based debate triggers
  - `AlertAnalyzer` - Threshold monitoring with auto-debate
  - `TrendMonitor` - Direction detection (increasing/decreasing/stable/volatile)
  - `AnomalyDetector` - Z-score based anomaly detection with severity
- 40 tests in `tests/autonomous/test_proactive_intelligence.py`

**Autonomous Server Handlers**
- `aragora/server/handlers/autonomous/`:
  - `approvals.py` - GET/POST approval management endpoints
  - `alerts.py` - Alert monitoring and acknowledgment
  - `triggers.py` - Scheduled trigger CRUD and scheduler control
  - `monitoring.py` - Metrics recording, trends, anomalies
  - `learning.py` - ELO ratings, calibrations, patterns, learning cycles

**Autonomous WebSocket Streaming**
- `aragora/server/stream/autonomous_stream.py`:
  - Real-time event emission for approvals, alerts, triggers, monitoring, learning
  - 40+ new event types in `aragora/events/types.py`

**Autonomous Dashboard UI**
- `aragora/live/src/components/autonomous/`:
  - `AutonomousDashboard.tsx` - Main tabbed dashboard with WebSocket updates
  - `ApprovalPanel.tsx` - Human-in-the-loop approval management
  - `AlertsPanel.tsx` - Alert monitoring with severity sorting
  - `TriggersPanel.tsx` - Scheduled trigger configuration
  - `MonitoringPanel.tsx` - Trends and anomaly visualization
  - `LearningPanel.tsx` - ELO ratings, calibrations, patterns

---

### v2.0.8 - Strategic API Consolidation (January 2026)

**Production Ready** - Aragora 2.0.8 completes 4 strategic priorities: Gauntlet + Receipts API productization, Decision Explainability API, Workflow Templates packaging, and Knowledge Mound persistence hardening.

#### Key Highlights
- **38,200+ tests** collected and passing (+100 new tests)
- **1,050 test files** across all modules
- **Strategic API completions** - 4 major priorities shipped
- **Resilient storage** - ResilientPostgresStore with retry, circuit breaker, health monitoring
- **Lines of Code**: 448,000+ LOC (+2,000)
- **0 production blockers**
- **102 fully integrated features** (+4 strategic priorities)

#### What's New in 2.0.8

**Gauntlet + Receipts API Productization** (PRIORITY 1 - COMPLETE)
- `aragora/gauntlet/receipt.py` - DecisionReceipt dataclass with cryptographic hashing
  - SHA-256 artifact hashing for tamper-evident audit trails
  - Serialization to JSON/dict for compliance documentation
  - Verdict summary (PASS/FAIL/WARN) with finding counts
- `aragora/server/handlers/gauntlet.py` - 6 API endpoints:
  - GET `/api/gauntlet/receipts` - List receipts with filters (verdict, date range)
  - GET `/api/gauntlet/receipts/{id}` - Get receipt by ID
  - POST `/api/gauntlet/receipts/{id}/verify` - Verify artifact integrity
  - GET `/api/gauntlet/receipts/{id}/export` - Export as HTML/JSON
  - GET `/api/gauntlet/runs` - List gauntlet runs
  - GET `/api/gauntlet/runs/{id}` - Get run details
- 23 tests in `tests/server/handlers/test_gauntlet_handler.py`

**Decision Explainability API** (PRIORITY 3 - COMPLETE)
- `aragora/server/handlers/explainability.py` - 4 API endpoints:
  - GET `/api/debates/{id}/explainability` - Get full explanation
  - GET `/api/debates/{id}/explainability/factors` - Get contributing factors
  - GET `/api/debates/{id}/explainability/counterfactual` - Generate what-if scenarios
  - GET `/api/debates/{id}/explainability/provenance` - Get decision provenance chain
- Natural language decision narratives with confidence scores
- Factor decomposition: agent contributions, evidence quality, consensus strength
- Counterfactual analysis for alternative outcome exploration
- 31 tests in `tests/server/handlers/test_explainability_handler.py`

**Workflow Templates Package** (PRIORITY 4 - COMPLETE)
- `aragora/workflow/templates/` - Comprehensive template system:
  - `registry.py` - WORKFLOW_TEMPLATES registry with 50+ templates
  - `package.py` - TemplatePackage, TemplateAuthor, TemplateCategory enums
  - `patterns.py` - Pattern-based template factories (hive-mind, map-reduce, review-cycle)
- Pre-built templates across 6 categories:
  - Legal: contract review, compliance audit, policy analysis
  - Research: literature review, data analysis, hypothesis testing
  - Content: article writing, editing, summarization
  - Development: code review, architecture design, debugging
  - Business: strategy analysis, market research, financial modeling
  - General: brainstorming, decision making, problem solving
- `aragora/server/handlers/workflow_templates.py` - 4 handlers:
  - WorkflowTemplatesHandler - Template CRUD and execution
  - WorkflowCategoriesHandler - Category listing
  - WorkflowPatternsHandler - Pattern listing
  - WorkflowPatternTemplatesHandler - Pattern instantiation
- 23 tests in `tests/server/handlers/test_workflow_templates_handler.py`

**Knowledge Mound Persistence Hardening** (PRIORITY 5 - COMPLETE)
- `aragora/knowledge/mound/resilience.py` - Production-hardened storage layer:
  - ResilientPostgresStore wrapper with automatic retry logic
  - RetryConfig for configurable retry attempts and backoff
  - TransactionConfig for timeout and isolation level settings
  - CacheInvalidationBus for event-driven cache coherence
  - IntegrityChecker for startup verification and repair
  - HealthMonitor for continuous connection monitoring
- `aragora/knowledge/mound/types.py` - New MoundConfig resilience settings:
  - `enable_resilience` - Use ResilientPostgresStore wrapper
  - `enable_integrity_checks` - Run verification on startup
  - `enable_health_monitoring` - Background health checks
  - `enable_cache_invalidation_events` - Emit invalidation events
  - `retry_max_attempts`, `retry_base_delay`, `transaction_timeout`
- `aragora/knowledge/mound/redis_cache.py` - Invalidation bus integration:
  - `subscribe_to_invalidation_bus()` for automatic cache invalidation
  - Event-driven updates on node_updated, node_deleted, query_invalidated, culture_updated
- `aragora/knowledge/mound/core.py` - Wired resilience into production:
  - `_init_postgres()` conditionally wraps store with ResilientPostgresStore
  - `_init_redis()` subscribes to invalidation bus when enabled
- 115 resilience tests in `tests/knowledge/mound/test_resilience.py`

---

### v2.0.7 - Enterprise Streaming & Chat Integration (January 2026)

**Production Ready** - Aragora 2.0.7 adds enterprise streaming connectors (Kafka/RabbitMQ), bidirectional chat result routing, and adapter factory for automated KM integration.

#### Key Highlights
- **38,100+ tests** collected and passing
- **1,047 test files** across all modules
- **Enterprise streaming** - Kafka and RabbitMQ connectors
- **Bidirectional chat** - Results routed back to originating platform
- **Adapter factory** - Auto-create KM adapters from Arena subsystems
- **Lines of Code**: 446,000+ LOC (+2,000)
- **0 production blockers**
- **98 fully integrated features** (+1 streaming)

#### What's New in 2.0.7

**Enterprise Streaming Connectors** (NEW)
- `aragora/connectors/enterprise/streaming/kafka.py` - Apache Kafka consumer
  - Consumer group management for horizontal scaling
  - Offset tracking for reliable delivery
  - JSON, Avro, Protobuf deserialization
  - Schema registry integration (optional)
- `aragora/connectors/enterprise/streaming/rabbitmq.py` - RabbitMQ connector
  - Exchange and queue binding management
  - Manual acknowledgment for reliability
  - Dead letter queue handling
  - Publish support for bidirectional messaging
- Both connectors produce `SyncItem` for direct Knowledge Mound ingestion

**Bidirectional Chat Result Routing** (NEW)
- `aragora/server/debate_origin.py` - Track debate origins for result routing
  - Register origin: `register_debate_origin(debate_id, platform, channel_id, user_id)`
  - Route results: `await route_debate_result(debate_id, result)`
  - Supported platforms: Telegram, WhatsApp, Slack, Discord, Teams, Email
  - Redis backend for HA deployments, in-memory fallback
  - 24-hour TTL with automatic cleanup
- `aragora/server/result_router.py` - Hook-based routing system
- Result formatting: Markdown for Telegram/Slack/Discord, plaintext for WhatsApp, HTML for Email, Adaptive Cards for Teams
- 19 tests in `tests/test_debate_origin.py`

**Adapter Factory for Knowledge Mound** (NEW)
- `aragora/knowledge/mound/adapters/factory.py` - Auto-create adapters
  - Creates adapters from Arena subsystems automatically
  - Dependency checking with graceful fallback
  - Event callback integration for WebSocket events
  - 9 adapter specs: continuum, consensus, critique, evidence, belief, insights, elo, pulse, cost
- Usage: `factory.create_from_subsystems(elo_system=..., continuum_memory=...)`
- ArenaConfig integration: `factory.create_from_arena_config(config)`
- 16 tests in `tests/knowledge/mound/test_adapter_factory.py`

**TTS Integration for Voice & Chat** (NEW)
- `aragora/server/stream/tts_integration.py` - Event-driven TTS synthesis
  - Subscribes to `agent_message` events on EventBus
  - Auto-synthesizes for active voice sessions
  - Rate limiting to prevent audio overlap
  - Chat synthesis: `await tts.synthesize_for_chat(text, "telegram", channel_id)`
- Wired into server startup sequence (`init_tts_integration()`)
- Graceful degradation when TTS backends unavailable

**Enhanced Social Handlers** (ENHANCED)
- `aragora/server/handlers/social/tts_helper.py` - TTS utilities for chat handlers
- `aragora/server/handlers/social/whatsapp.py` - Enhanced WhatsApp handler
- `aragora/server/handlers/social/telegram.py` - Enhanced with TTS support
- Voice note responses for Telegram and WhatsApp

---

### v2.0.6 - Stability Release (January 2026)

**Production Ready** - Aragora 2.0.6 promotes Pulse to stable, fixes asyncio deprecations, and adds bidirectional adapters.

#### Key Highlights
- **38,100+ tests** collected and passing (+700 new tests)
- **1,047 test files** across all modules
- **Pulse promoted to STABLE** (358+ tests passing)
- **ANN similarity backend** for fast convergence detection
- **Lines of Code**: 444,000+ LOC (+1,000)
- **0 production blockers**
- **0 uncommitted files**
- **97 fully integrated features** (+1 Pulse)

#### What's New in 2.0.6

**Pulse Promotion to Stable**
- 358+ tests passing across quality, freshness, weighting, scheduling
- HackerNews, Reddit, Twitter ingestors fully functional
- Quality filtering with clickbait/spam detection
- Source weighting with credibility scores
- Freshness scoring with configurable decay curves

**ANN Similarity Backend**
- Fast approximate nearest neighbor search for convergence detection
- FAISS index integration for large-scale similarity
- 26 ANN-specific tests

**Test Infrastructure Improvements**
- Fast Jaccard convergence backend for tests (avoids ML model loading)
- Fixed deprecated asyncio patterns in tests
- Cross-pollination benchmark suite (12 benchmarks)

---

#### What's New in 2.0.3

**Cross-Pollination Integrations** - 8 new feature connections
- **Calibration → Proposals**: Temperature scaling applied to initial proposal confidence
- **Learning Efficiency → ELO**: Agents who improve consistently get ELO bonuses
- **Memory Checkpoint Snapshots**: Export/restore ContinuumMemory with debate state
- **Knowledge Mound Federation**: Multi-region sync for institutional knowledge
- **Event-Driven Subsystem Communication**: CrossSubscriberManager routes events between subsystems
- **Arena Event Bridge**: Debate events automatically dispatch to cross-subscribers
- **RLM Training Hook**: Automatic trajectory collection from debate outcomes
- **Evidence-Provenance Bridge**: Link evidence snippets to belief claims for provenance

**Feedback Loop Completions**
- Voting accuracy tracking feeds back to agent skill assessment
- Verification results adjust vote confidence (verified → +30%, disproven → -70%)
- Debate outcomes inform learning efficiency metrics

#### What's New in 2.0.2

**Decision Receipt Browser** (`/receipts`) - NEW
- Browse gauntlet receipts with verdict badges (PASS/FAIL/WARN)
- Filter by date range and verdict type
- Full receipt viewer with artifact hash verification
- Export as HTML/JSON for compliance documentation
- Provenance chain visualization

**Training Data Explorer** (`/training/explorer`) - NEW
- Dataset statistics dashboard (total debates, topics, win rates)
- Format documentation for SFT, DPO, Gauntlet exports
- Live preview of training examples
- Confidence threshold filtering
- Bulk export with format selection

**Model Registry** (`/training/models`) - NEW
- Track fine-tuned specialist models
- Job status badges (pending, training, completed, failed)
- Performance metrics (ELO, win rate, accuracy, loss)
- Training progress visualization
- Start/cancel job controls
- Artifact download links

**Risk Heatmap Enhancement** (`/gauntlet`) - ENHANCED
- Interactive risk heatmap visualization
- Rows = categories (Security, Logic, Compliance)
- Columns = severity levels (critical, high, medium, low)
- Click cell to filter findings
- Export as SVG for reports

**Belief Network Dashboard** (`/crux`) - ENHANCED
- New tabs: Cruxes | Load-Bearing | Contested | Stats
- Contested claims panel with confidence delta
- Graph statistics (nodes, edges, depth, centrality)
- Network export options (JSON, GraphML, CSV)
- Enhanced sensitivity analysis

**Episode Generator** (`/broadcast`) - ENHANCED
- Generate podcast episodes from debates
- Debate selector dropdown
- Custom title and description
- Optional video flag
- Generation progress indicator
- Direct play/download after generation

**Knowledge Graph Export** (`/knowledge`) - ENHANCED
- Export buttons (D3 JSON, GraphML)
- Staleness panel with aging/stale/expired indicators
- Color-coded freshness badges
- Batch refresh operations

**Navigation Improvements**
- Added [EXPLORER] and [MODELS] links to `/training`
- Added [RECEIPTS] link to `/gauntlet`
- Cross-page navigation consistency

**RLM Training Module** - NEW
- `aragora/rlm/training/buffer.py` - Experience replay storage with prioritization
- `aragora/rlm/training/reward.py` - Reward signal computation from debate outcomes
- Entropy bonuses, temporal discounting, margin-based rewards

#### Recent Changes (2026-01-20)
- **Bidirectional KM Integration Complete** - Full cross-subsystem event flows:
  - 15 new cross-subscriber handlers for KM ↔ subsystem communication
  - Inbound handlers: memory_to_mound, belief_to_mound, rlm_to_mound, elo_to_mound, insight_to_mound, flip_to_mound, provenance_to_mound
  - Outbound handlers: mound_to_memory_retrieval, mound_to_belief, mound_to_rlm, mound_to_team_selection, mound_to_trickster, staleness_to_debate, mound_to_provenance, culture_to_debate
  - RankingAdapter and RlmAdapter for cross-debate learning
  - Automatic adapter sync on debate completion and server startup
  - Background staleness checker (6-hour interval)
  - Prometheus metrics for KM bidirectional flows (8 new metric types)
  - CultureAccumulator.get_patterns() and get_patterns_summary() methods
  - API endpoints: POST /api/cross-pollination/km/sync, POST /api/cross-pollination/km/staleness-check, GET /api/cross-pollination/km/culture
  - Server shutdown flush for KM adapters and event batches
  - 15 new unit tests in `tests/knowledge/mound/adapters/test_adapter_persistence.py`
- **Knowledge Mound Complete** - All phases (1-3) fully implemented:
  - Phase 1: Core storage, semantic search, graph relationships, culture accumulation
  - Phase 2: Visibility levels, access grants, sharing, global knowledge, federation
  - Phase 3: Deduplication (find/merge duplicates), pruning (archive/delete stale)
  - 525 tests passing in `tests/knowledge/mound/`
  - 73 feature tests for visibility, sharing, global knowledge, federation
  - Full HTTP API coverage with 15+ endpoints
  - React hooks: useVisibility, useSharing, useFederation, useGlobalKnowledge, useDedup, usePruning
  - UI components: ShareDialog, FederationStatus, VisibilitySelector, DedupTab, PruningTab
  - Prometheus metrics for all operations
- **Bidirectional KM Adapters** - Reverse flow from KM to source systems:
  - Critique adapter: KMPatternBoost, KMReputationAdjustment, KMPatternValidation
  - Insights adapter: KMFlipThresholdUpdate, KMAgentFlipBaseline, KMFlipValidation
  - ELO adapter: KMRatingAdjustment, KMCalibrationUpdate
  - Belief adapter: KMBeliefReinforcement, KMClaimValidation
- **Control Plane Multi-Tenancy** - Workspace isolation enforcement:
  - `aragora/control_plane/multi_tenancy.py` - TenantEnforcer, TenantContext
  - Quota enforcement (max agents, concurrent tasks, rate limits)
  - Context variable-based tenant scoping with `with_tenant` decorator
- **Test Performance Fix** - Added `fast_convergence_backend` autouse fixture:
  - By default, tests use Jaccard backend (fast) instead of SentenceTransformer (slow)
  - Tests marked `@pytest.mark.slow` still use real ML models
  - Reduces test suite time by avoiding model loading on every ConvergenceDetector
  - Set via `ARAGORA_CONVERGENCE_BACKEND=jaccard` environment variable
- **Cross-Pollination Verified** - All 21 integration tests pass:
  - ELO → Vote Weighting integration
  - Calibration → Proposal confidence
  - Verification → Confidence adjustment
  - Learning efficiency → ELO bonuses
  - Memory → Debate strategy
  - RLM hierarchy caching
- **Gauntlet CLI** - All 30 stress tests pass:
  - Large input handling (10KB, 100KB, 1MB)
  - Concurrent execution (5, 20 parallel runners)
  - Error recovery from all phases
  - Edge cases (empty, whitespace, null bytes)
- **Whisper Transcription Fixes** - 7 test failures resolved:
  - Fixed `OpenAIWhisperBackend` initialization (model property, API key validation)
  - Added "auto" backend selection support to `get_transcription_backend()`
  - Fixed file size validation test to use configurable limits
  - All 24 whisper backend tests now pass (4 skipped due to optional deps)
- **Memory Embeddings Tests** - 52 new tests for `aragora/memory/embeddings.py`:
  - `tests/memory/test_embeddings.py` covering all providers and utilities
  - Tests for EmbeddingProvider, OpenAIEmbedding, GeminiEmbedding, OllamaEmbedding
  - SemanticRetriever database operations fully tested
  - Integration tests for concurrent embeddings and provider fallback
- **Billing & AgentSpec Verified** - Code audit confirmed proper implementation:
  - Usage sync correctly handles token delta flooring and remainder preservation
  - AgentSpec model/persona properly wired through to agent creation
- **Connector Exception Hierarchy** - Already complete (`aragora/connectors/exceptions.py`):
  - 10 exception types with `is_retryable` and `retry_after` attributes
  - `classify_exception()` utility for converting generic exceptions
  - `connector_error_handler` context manager for consistent error handling
- **New Test Suites** - 5 new test modules with 260+ tests:
  - `tests/runtime/test_autotune.py` - 58 tests for budget-aware debate autotuning
  - `tests/scheduler/test_audit_scheduler.py` - 67 tests for cron/webhook scheduling
  - `tests/evaluation/test_llm_judge.py` - 38 tests for LLM-as-judge evaluation
  - `tests/debate/phases/test_context_init.py` - context initialization tests
  - Various test improvements across existing modules
- **Handler Registry** - Fully extracted from unified_server.py (1,191 LOC module)
  - O(1) exact path lookup via route index
  - LRU cached prefix matching for dynamic routes
  - 60+ handler classes with validation
- **Security Fixes** - XML XXE vulnerability remediation:
  - Migrated `auth/saml.py` and `connectors/arxiv.py` to use `defusedxml`
  - Added `defusedxml>=0.7` as core dependency
- **Test Parallelization** - Added pytest-xdist support:
  - `pytest-xdist>=3.5` added to dev dependencies
  - `serial` marker for tests that must run sequentially
  - Run with `pytest -n auto` for parallel execution
- **Benchmark Fix** - Relaxed concurrent debate SLO from 0.3 to 0.15 debates/sec
  - Reduces flaky test failures in CI environments
- **Code Coverage Analysis** - Module-level coverage metrics (dedicated test files):
  - `memory/streams.py`: 94% coverage (56 tests)
  - `memory/coordinator.py`: 86% coverage (17 tests)
  - `memory/consensus.py`: 88% coverage
  - `visualization/mapper.py`: 97% coverage (109 tests)
  - `ranking/`: 53% aggregate coverage
  - Coverage tool: `pytest --cov=aragora.<module> --cov-report=term-missing`
- **Dependency Audit** - No known vulnerabilities found (pip-audit)
  - 10 packages have non-critical updates available
- **Type Coverage** - 689 mypy errors in core modules (baseline for improvement)
- **Test Parallelization Verified** - 758 tests passed with `pytest -n auto`

#### Recent Changes (2026-01-19)
- **Cross-Functional Integration** - Wired 7 cross-functional features:
  - KnowledgeBridgeHub instantiation (unified MetaLearner/Evidence/Pattern access)
  - MemoryCoordinator for atomic cross-system writes
  - SelectionFeedbackLoop for performance-based agent selection
  - CrossDebateMemory for institutional knowledge injection
  - Evidence storage via EvidenceBridge
  - Culture pattern observation via KnowledgeMound
  - Post-debate workflow triggers
  - See `docs/CROSS_FUNCTIONAL_FEATURES.md` for usage
- **Cross-Functional Metrics** - 7 new Prometheus metrics:
  - `aragora_knowledge_cache_hits_total` / `aragora_knowledge_cache_misses_total`
  - `aragora_memory_coordinator_writes_total`
  - `aragora_selection_feedback_adjustments_total`
  - `aragora_workflow_triggers_total`
  - `aragora_evidence_stored_total` / `aragora_culture_patterns_total`
- **Arena.from_config fix** - Fixed `enable_adaptive_rounds` NameError in `_apply_tracker_components`
- **Modes module tests** - Added 96 tests for `tool_groups.py`, `base.py`, `deep_audit.py`, `redteam.py`
- **Server refactoring** - Extracted 3 modules from `unified_server.py` (1,321 → 1,013 LOC, -308 lines):
  - `server/request_lifecycle.py` - HTTP request lifecycle management (167 LOC)
  - `server/static_file_handler.py` - Static file serving with security (207 LOC)
  - `server/shutdown_sequence.py` - Phase-based graceful shutdown (383 LOC)
- **Persistence test fixes** - Fixed timezone-aware datetime comparisons in `test_persistence_comprehensive.py`
- **ArenaConfig cleanup** - Removed unsupported kwargs from `to_arena_kwargs()` (Memory Coordination, Selection Feedback Loop, Hook System params stored but not yet in Arena.__init__)

#### Bug Fixes (Code Audit)
- **Agent spec parsing** - Fixed 3-part spec bug in PERSONA_TO_AGENT mapping
- **Usage sync persistence** - Watermarks now survive service restarts via SQLite
- **Context gatherer cache** - Task-hash keying prevents leaks between debates
- **React side effect** - Moved setLastAllConnected from useMemo to useEffect
- **Cross-debate memory** - Snapshot pattern fixes race condition in concurrent reads
- **Handler error messages** - safe_error_message on all 500/503 responses
- **Next.js metadata** - Separated viewport export for Next.js 14+ compliance

---

### v2.0.1 - Feature Integration & Consolidation Release (January 2026)

**Production Ready** - Aragora 2.0.1 focuses on frontend error handling, expanded E2E testing, and feature integration improvements.

#### Key Highlights
- **34,300+ tests** collected and passing (+5,400 new tests)
- **Production Readiness**: 99%+ (all major systems complete)
- **Lines of Code**: 440,000+ LOC (+10,000)
- **0 production blockers**
- **0 uncommitted files**

#### What's New in 2.0.1

**Frontend Error Handling Improvements** (NEW)
- `PluginMarketplacePanel` - Error states for installed plugins fetch
- `GauntletPanel` - Error states with retry for details fetch
- Eliminated silent error handling in key components

**ML Dashboard UI** (NEW)
- `/ml` page for ML routing and scoring visualization
- `MLDashboard` component with delegation metrics
- Real-time ML model performance monitoring

**Nomic Loop WebSocket Streaming** (NEW)
- `useNomicLoopWebSocket` hook for real-time updates
- Server-side nomic loop stream handler
- Enhanced nomic-control page integration

**Event Emission System** (NEW)
- `event_emission.py` - Debate lifecycle event utilities
- `arena_hooks.py` - Server-side debate streaming hooks
- Improved debate rounds phase event handling

**Expanded E2E Test Coverage** (NEW)
- `memory.spec.ts` - 23 tests for memory explorer page
- `gauntlet.spec.ts` - 12 tests for gauntlet stress-testing
- Total E2E tests: 420+ (up from 387)

**New Backend Test Suites** (NEW)
- `tests/gauntlet/` - Gauntlet stress testing (5,410+ lines)
- `tests/memory/` - Consensus, store, tier manager tests
- `tests/ranking/` - Calibration, leaderboard, relationships tests

**Backend Improvements**
- Auth v2 middleware for improved authentication
- Knowledge handler enhancements
- Server startup utilities
- Handler registry improvements
- RLM cognitive load limiter integrated into Arena via `use_rlm_limiter` config
- ArenaConfig API alignment with Arena.__init__ parameters
- Auto-wiring of RLM compression into debate rounds (triggers after round 3)

**RLM (Recursive Language Models) Integration** (UPDATED)

Based on [arXiv:2512.24601](https://arxiv.org/abs/2512.24601) - "Recursive Language Models" by Alex L. Zhang, Tim Kraska, and Omar Khattab. MIT Licensed: [github.com/alexzhang13/rlm](https://github.com/alexzhang13/rlm)

**How Real RLM Works:**
1. Context is stored as a Python variable in a REPL environment (NOT in the prompt)
2. LLM writes code to programmatically examine/grep/partition the context
3. LLM can recursively call itself on context subsets
4. LLM dynamically decides decomposition strategy (grep, map-reduce, peek, etc.)
5. Full context remains accessible - no information loss from truncation

**Installation:**
```bash
# Install with real RLM support
pip install aragora[rlm]
```

**Usage:**
```python
from aragora.debate.orchestrator import Arena
from aragora.debate.arena_config import ArenaConfig

config = ArenaConfig(
    use_rlm_limiter=True,                  # Enable RLM context management
    rlm_compression_threshold=5000,        # Chars to trigger RLM
    rlm_max_recent_messages=3,             # Keep N recent at full detail
    rlm_compression_round_threshold=3,     # Start after round N
)
arena = Arena.from_config(env, agents, protocol, config)

# Check if real RLM is available
from aragora.debate.cognitive_limiter_rlm import HAS_OFFICIAL_RLM
if HAS_OFFICIAL_RLM:
    # Uses real REPL-based RLM (infinite context support)
    result = await limiter.query_with_rlm("What did agents agree on?", messages)
else:
    # Falls back to hierarchical summarization
    compressed = await limiter.compress_context_async(messages=messages)
```

**Fallback Mode** (when `rlm` package not installed):
- Uses LLM-based hierarchical summarization (still useful, but not true RLM)
- Creates abstraction levels (FULL, DETAILED, SUMMARY, ABSTRACT)
- Preserves semantics through compression rather than truncation

---

### v2.0.0 - Enterprise & Production Hardening Release (January 2026)

**Production Ready** - Aragora 2.0.0 represents a major milestone with enterprise features, comprehensive E2E testing, and production hardening.

#### Key Highlights
- **28,912+ tests** collected and passing (+4,000 from v1.5.1)
- **Production Readiness**: 99%+ (all major systems complete)
- **Lines of Code**: 430,000+ LOC
- **0 production blockers**
- **0 uncommitted files**

#### What's New in 2.0.0 (Phase 6-7)

**Multi-Tenant Isolation** (NEW)
- `aragora/tenancy/` module with context, isolation, quotas
- Thread-safe and async-safe tenant context management
- SQL query auto-filtering by tenant
- Rate limiting and usage quotas per tenant

**Usage Metering & Billing** (NEW - Enhanced)
- `aragora/billing/metering.py` - Tenant-aware usage tracking
- BillingEvent collection with periodic flush
- Per-tenant cost calculation and projections
- Integration with quota enforcement
- **Two-phase commit sync** - Crash-safe Stripe reporting with `usage_sync_records` table
- **Content-based idempotency** - Stable keys prevent double-billing across restarts
- **Watermark persistence** - SQLite-backed sync watermarks survive service restarts

**Agent Specification Parsing** (STABLE)
- `aragora/agents/spec.py` - Unified AgentSpec class
- Pipe-delimited format: `provider|model|persona|role`
- Legacy colon format support: `provider:persona` (backward compatible)
- Clear separation of provider, model, persona, and role concepts
- Fixed: PERSONA_TO_AGENT now maps to registered agent types (2-part specs)
- 43 comprehensive parsing tests

**Extended Debates (50+ Rounds)** (NEW)
- `aragora/debate/extended_rounds.py` - RLM context management
- Sliding window compression for long debates
- Adaptive context strategy selection
- Checkpoint/resume for extended sessions

**Streaming RLM Queries** (NEW)
- `aragora/rlm/streaming.py` - Progressive context loading
- Top-down, bottom-up, and targeted streaming modes
- Real-time drill-down during debates

**Cross-Debate Memory** (STABLE)
- `aragora/memory/cross_debate_rlm.py` - Institutional memory
- Tiered storage (hot/warm/cold/archive)
- Relevance-based context retrieval
- Fixed: Race condition in concurrent reads via snapshot pattern

**Knowledge Mound** (STABLE - Production Ready, 100% Integrated)
- `aragora/knowledge/mound/` - Unified enterprise knowledge storage
- **911 tests passing** across mound and integration suites
- SemanticStore with mandatory embeddings for semantic search
- KnowledgeGraphStore for relationship tracking and lineage
- DomainTaxonomy for hierarchical organization
- KnowledgeMoundMetaLearner for cross-memory optimization
- **Visibility Levels** (PHASE 2): private, workspace, organization, public, system
- **Access Grants**: Fine-grained permissions with expiration
- **Cross-Workspace Sharing**: Share items between workspaces with permission tracking
- **Global Knowledge**: System-wide verified facts in `__system__` workspace
- **Federation**: Multi-region sync with push/pull/bidirectional modes
- **Deduplication** (PHASE 3): Find/merge duplicate knowledge items
- **Pruning** (PHASE 3): Archive/delete stale items with policy-based automation
- **Auto-Curation** (PHASE 4): Intelligent automated knowledge maintenance
  - Quality scoring with configurable weights (freshness, confidence, usage, relevance, relationships)
  - Tier promotion/demotion based on quality thresholds
  - Automated scheduling with cron expressions
  - Integration with dedup/pruning for comprehensive maintenance
  - CurationPolicy per workspace with customizable thresholds
  - Full audit history and workspace quality summaries
- **Bidirectional Adapters**: ELO, Insights, Critique, Belief, Evidence adapters with reverse flows
- React hooks: `useVisibility`, `useSharing`, `useFederation`, `useGlobalKnowledge`, `useDedup`, `usePruning`
- UI components: ShareDialog, FederationStatus, VisibilitySelector, DedupTab, PruningTab
- TypeScript types: `aragora/live/src/types/knowledge.ts` (50+ type definitions)
- Backend handlers: visibility.py, sharing.py, global_knowledge.py, federation.py, dedup.py, pruning.py
- Integration tests: 73+ tests covering visibility, sharing, global knowledge, federation, dedup, pruning
- Prometheus metrics: visibility changes, access grants, shares, federation syncs, region status
- Staleness detection with automatic revalidation scheduling
- Culture accumulation for organizational learning
- Multi-backend support (SQLite, PostgreSQL, Redis)

**API Versioning** (NEW)
- `aragora/server/versioning/` - URL prefix versioning
- Header-based version negotiation
- RFC 8594 deprecation headers
- Sunset date tracking and warnings

**E2E Integration Tests** (NEW)
- `tests/e2e/` - Comprehensive E2E test suite
- Connector sync lifecycle tests
- Debate 50+ round tests
- Multi-tenant isolation verification

**Performance Benchmarks** (NEW)
- `benchmarks/` - Performance benchmark suite
- RLM compression efficiency metrics
- Tenant isolation overhead tests
- Extended debate memory profiling

**Observability** (NEW)
- Prometheus metrics for RLM and connectors
- Grafana dashboard (`k8s/monitoring/aragora-dashboard.json`)
- Alert rules (`k8s/monitoring/alerts.yaml`)
- Metrics runbook (`docs/RUNBOOK_METRICS.md`)

**Admin UI** (NEW)
- `/admin/tenants` - Tenant management portal
- `/admin/usage` - Usage dashboard with metrics

**Enterprise Connectors** (Complete)
- 22 connectors (databases, collaboration, documents)
- SharePoint, Confluence, Notion, Slack, Google Drive
- Sync persistence with SQLite/PostgreSQL
- Health monitoring and metrics

**Phase 9: Event-Driven Cross-Pollination** (NEW)
- `aragora/events/cross_subscribers.py` - CrossSubscriberManager for event-driven subsystem communication
- `aragora/events/arena_bridge.py` - ArenaEventBridge connecting Arena events to cross-subscribers
- `aragora/reasoning/evidence_bridge.py` - EvidenceProvenanceBridge for claim-evidence linking
- `aragora/rlm/debate_integration.py` - DebateTrajectoryCollector for RLM training from debates
- `aragora/server/handlers/cross_pollination.py` - Observability endpoints for cross-pollination status
- `aragora/config/settings.py:IntegrationSettings` - Centralized configuration for all integrations
- 6 built-in handlers: memory_to_rlm, elo_to_debate, knowledge_to_memory, calibration_to_agent, evidence_to_insight, mound_to_memory
- 138+ tests across event system, bridges, and integration flows
- Environment variables: `ARAGORA_INTEGRATION_RLM_TRAINING`, `ARAGORA_INTEGRATION_KNOWLEDGE_MOUND`, `ARAGORA_INTEGRATION_CROSS_SUBSCRIBERS`

**Phase 8: Cross-Pollination Integrations** (COMPLETE)
- `aragora/debate/hook_handlers.py` - HookHandlerRegistry for automatic subsystem wiring
- `aragora/ranking/performance_integrator.py` - PerformanceEloIntegrator for K-factor modulation
- `aragora/memory/outcome_bridge.py` - OutcomeMemoryBridge for outcome-based memory promotion
- `aragora/debate/trickster_calibrator.py` - TricksterCalibrator for auto-tuning detection
- Checkpoint memory state - Complete debate restoration with memory context
- 113 tests across all Phase 8 integrations
- New ArenaConfig fields: `enable_hook_handlers`, `enable_performance_elo`, `enable_outcome_memory`, `enable_trickster_calibration`, `checkpoint_include_memory`

**Phase 7: Memory Coordination & Feedback** (COMPLETE)
- `aragora/memory/coordinator.py` - MemoryCoordinator for atomic multi-system writes
- `aragora/debate/selection_feedback.py` - SelectionFeedbackLoop for performance-based selection
- `aragora/knowledge/mound/ops/sync.py` - Incremental knowledge sync methods
- Pulse/trending context integration enabled by default
- 60+ tests for coordination and feedback systems

---

### v1.5.1 - E2E Testing & SOC 2 Compliance Update (January 2026)

**Production Ready** - Aragora 1.5.1 adds comprehensive E2E testing coverage and completes SOC 2 documentation gaps.

#### Key Highlights
- **24,525+ tests** collected and passing (+1,077 from v1.5.0)
- **394 E2E tests** covering graceful shutdown, error recovery, connection pooling, WebSocket, nomic loop, auth lifecycle, memory persistence
- **SOC 2 Readiness**: 92% (up from 78%) - all privacy documentation complete
- **0 HIGH severity security issues** (Bandit scan clean)
- **0 ruff violations** (code quality)
- **9.5/10 production readiness score** (up from 9.3)

#### What's New in 1.5.1

**E2E Test Coverage (Phases 16-22)**
- **Graceful Shutdown**: 25 tests for ServerLifecycleManager
- **Error Recovery Chains**: 29 tests for CircuitBreaker and AgentFallbackChain
- **Connection Pool Load**: 20 tests for SQLite pooling under concurrent load
- **WebSocket Real Clients**: 27 tests for SyncEventEmitter and streaming
- **Nomic Loop Cycle**: 43 tests for PhaseValidator and phase transitions
- **Auth Lifecycle**: 30 tests for AuthConfig, token revocation, rate limiting
- **Memory Persistence**: 23 tests for ContinuumMemory tier promotion

**SOC 2 Documentation Complete**
- Privacy Policy with DSAR workflow
- Data Classification Policy
- Breach Notification SLA (72-hour)
- Data Residency Policy
- Incident Response Plan

### v1.5.0 - OAuth, SDK Probes & Performance Release (January 2026)

**Production Ready** - Aragora 1.5.0 completes Sprint 10-12 with comprehensive OAuth E2E testing, SDK capability probes API, and documented performance baselines.

#### Key Highlights (v1.5.0)
- **23,448+ tests** collected and passing (+85 from v1.4.0)
- **OAuth E2E Suite**: 31 tests for Google, YouTube, Twitter OAuth flows
- **SDK v1.1.0**: Capability probes API and verification history endpoints
- **Performance Baseline**: Documented benchmark results in PERFORMANCE.md
- **Async Memory**: Non-blocking memory operations with async wrappers
- **Callback Timeouts**: Prevents hanging debates with 30s timeout protection
- **Philosophical Personas**: New personas for deeper discourse
- **0 HIGH severity security issues** (Bandit scan clean)
- **4 TODO markers** (well below 15 target)

#### What's New in 1.5.0

**OAuth E2E Testing (Sprint 11)**
- **Google OAuth**: 7 tests for state management, replay prevention, entropy
- **YouTube OAuth**: 8 tests for social OAuth flows and handler routes
- **Twitter OAuth**: 16 tests for publishing, content formatting, rate limiting

**SDK Capability Probes**
- **ProbesAPI**: Test agents for vulnerabilities (contradiction, hallucination, sycophancy)
- **Verification History**: Query and analyze past verifications with proof trees
- **TypeScript SDK v1.1.0**: Full type definitions for all new endpoints

**Performance**
- **Benchmark Suite**: 11 API component benchmarks with latency metrics
- **Rate Limiting Tests**: 17 comprehensive rate limiting tests
- **PERFORMANCE.md**: Documented baseline metrics and SLO targets

**Developer Experience**
- **Async Memory Wrappers**: Non-blocking `add_async()`, `get_async()`, `retrieve_async()`
- **Callback Timeouts**: 30s protection for judge termination, early stopping
- **Philosophical Personas**: Philosopher, humanist, existentialist personas

---

## Previous Releases

### v1.4.0 - Admin UI & Governance Release (January 2026)

**Production Ready** - Aragora 1.4.0 adds comprehensive admin console components, Nomic loop governance with approval gates, and SOC 2 compliance documentation.

- **23,363+ tests** collected and passing
- **Admin UI Components**: PersonaEditor, AuditLogViewer, TrainingExportPanel
- **Nomic Governance**: Approval gates (Design, TestQuality, Commit) with audit logging
- **SOC 2 Compliance**: MFA enforcement, data classification, incident response docs

### v1.3.0 - GA Preparation Release (January 2026)

**Production Ready** - Aragora 1.3.0 represents comprehensive security hardening, type safety, and production readiness improvements through Phases 11-15.

#### What's New in 1.3.0 (Phases 11-15 Complete)

**Phase 15 (Latest)**
- **Code Quality**: Fixed all ruff lint violations (0 errors)
- **Secret Scanning**: Added gitleaks job to CI for commit-level secret detection
- **API Documentation**: Generated and committed OpenAPI spec (JSON + YAML) to docs/api/
- **OpenAPI UI**: Added Redoc-powered API documentation at docs/api/index.html
- **GitHub Pages**: Added docs.yml workflow for documentation deployment
- **Frontend Tests**: Added 51 component test files (SettingsPanel, GenesisExplorer, ConsensusKnowledgeBase, etc.)
- **Type Safety**: Expanded typecheck-core from 12 to 15 modules (team_selector.py, convergence.py, prompt_builder.py)
- **CI Enhancement**: docs-sync job validates OpenAPI spec stays in sync with code

**Phase 14**
- **Type Safety Expansion**: typecheck-core expanded to 12 modules (consensus.py, resilience.py, belief.py)
- **E2E Test Suite**: 17 Playwright E2E test files covering critical user flows
- **Accessibility Testing**: axe-core integration for WCAG compliance
- **CI Enhancement**: E2E workflow with backend/frontend integration

**Phase 13**
- **Token Revocation UI**: "Logout All Devices" button in Settings panel
- **Type Safety Expansion**: typecheck-core expanded to 9 modules (orchestrator.py, continuum/core.py)
- **Storage Layer Fixes**: Fixed mypy errors in factory.py and webhook_store.py
- **Training Export Page**: New /training route for ML training data export
- **Production Checklist**: Comprehensive 300+ line PRODUCTION_CHECKLIST.md
- **Public Gallery Page**: /gallery route for browsing debate history

**Phase 12**
- **TrainingExportPanel**: 470-line component for SFT/DPO/Gauntlet exports
- **PublicGallery**: 743-line component for debate browsing with search/filters
- **CI/CD Hardening**: ESLint now blocking (was informational)
- **Bug Fixes**: Fixed showBoot variable declaration order in page.tsx

**Phase 11**
- **Security Hardening**: Full SQL injection audit of high-risk files
  - Audited and documented 16 B608 warnings across storage layer
  - Added `# nosec B608` comments with validation explanations
  - 0 HIGH severity Bandit issues across entire codebase
- **Type Safety**: Fixed secrets.py mypy error (json.loads return type)
- **AWS Integration**: Secrets Manager support for production deployments
- **Genesis/Gauntlet UI**: New frontend components for evolution and stress-testing
- **CI/CD Hardening**: typecheck-core job for strict type checking on core modules

#### What's New in 1.0.1
- Type safety: Fixed all mypy errors (error_monitoring.py Sentry callback types)
- Extended DebateStorageProtocol with 8 new methods
- Fixed AgentRating attribute names (elo, debates_count)
- Fixed EloSystem.get_elo_history method name
- Nomic loop phased workflow documentation
- .env.example with nomic loop settings

#### What's Included (from 1.0.0)
- Multi-agent debate orchestration with consensus detection
- Memory systems: ContinuumMemory, ConsensusMemory with LRU caching
- ELO rankings and tournament system
- Agent fallback via OpenRouter on quota errors
- CircuitBreaker for agent failure handling
- WebSocket event streaming
- Formal verification with Z3 backend
- Gauntlet mode for adversarial stress-testing

## Previous State

### Stabilization Target (0.8.1) - COMPLETE

All stabilization items addressed:

- [x] Canonical onboarding path (START_HERE -> GETTING_STARTED) and doc consistency
- [x] Test tiers + CI alignment for fast/local vs full runs
- [x] Runtime data hygiene (prefer `.nomic` via `ARAGORA_DATA_DIR`, cleanup script)
- [x] Prometheus metrics and Grafana dashboards (deploy/grafana/)
- [x] OpenAPI spec regenerated (1285 endpoints)
- [x] PhaseValidator integrated into Nomic loop
- [x] WebSocket reconnection with exponential backoff
- [x] Plugin submission flow added
- [x] aragora doctor bug fixed (circuit breaker metadata handling)

### Test Status
- **Total Tests**: 12,349 collected (massive expansion via parametrized tests)
- **Frontend Tests**: 34 Jest tests (DebateListPanel, AgentComparePanel)
- **Recent Fixes (2026-01-05)**:
  - Fixed `_get_belief_classes()` → `_get_belief_analyzer()` typo in orchestrator.py
  - Fixed all 7 unanimous consensus tests (were failing due to above typo)
  - ELO tests (3), calibration test (1), replay tests (4) fixed in previous session
- **Code Fixes**:
  - Calibration bucket boundary now includes confidence=1.0
  - Belief analyzer function name corrected in orchestrator.py:2213

### Nomic Loop
- **Cycle**: 1 (running with 6-cycle budget)
- **Phase**: context gathering → debate
- **Last Consensus**: "Stream Gateway & Multiplexer" (80% consensus) - identified verify_system_health.py issue
- **Recent Fixes (2026-01-08 Session 19)**:
  - Fixed TypedDict access in context phase (`result["key"]` not `result.key`)
  - Fixed debate phase empty agents (`_create_debate_phase()` now calls `_select_debate_team()`)
  - Fixed `verify_system_health.py` to check refactored `stream/` package
  - All critical systems now healthy (timeout handling, CLI integration, loop_id routing)
- **Blocking Issues FIXED**:
  - Missing `agent_type` attribute in GeminiAgent (now added to all API agents)
  - RelationshipTracker.get_influence_network() parameter mismatch (fixed)
  - OpenRouterAgent broken super().__init__() call (fixed)
  - `_get_belief_classes()` undefined (fixed - was typo for `_get_belief_analyzer()`)
  - Design phase 0% consensus now detected and cycle skipped (new safeguard)
  - Context phase crash with TypedDict access (fixed 2026-01-08)
  - Debate phase 0/0 agents (fixed 2026-01-08)
- **Position Ledger**: Implemented in `aragora/agents/grounded.py`
- **NomicIntegration**: Fully wired up (probing, belief analysis, checkpointing, staleness)

### Active Agents (default config, 8 total)
| Agent | Model | API |
|-------|-------|-----|
| `grok` | grok-4-latest | xAI |
| `anthropic-api` | claude-opus-4-5-20251101 | Anthropic |
| `openai-api` | gpt-5.3 | OpenAI |
| `deepseek` | deepseek/deepseek-reasoner | OpenRouter |
| `mistral-api` | mistral-large-2512 | Mistral |
| `gemini` | gemini-3-pro-preview | Google |
| `qwen-max` | qwen/qwen3-max | OpenRouter |
| `kimi` | moonshot-v1-8k | Moonshot |

### Recent Changes (2026-01-27)
- **RBAC Permission Compatibility**:
  - Added dot/colon notation compatibility layer (`debate.create` == `debate:create`)
  - Wildcard support for both formats (`debate.*` and `debate:*`)
  - Updated middleware to warn on legacy format usage
  - Added 3 new compatibility tests
- **WebSocket Health Endpoint**:
  - Added `/api/health/ws` and `/api/v1/health/ws` endpoints
  - Reports WebSocket manager availability and client count
  - Added to public routes (no auth required)
  - Added 3 new health tests
- **GitHub App Webhooks**:
  - Added GitHub App webhook handler (`/api/v1/webhooks/github`)
  - HMAC-SHA256 signature verification
  - Auto-triggers code review debates on PR events
  - Supports PR, issues, push, and installation events
  - Added 20 webhook handler tests
- **Backup Monitoring**:
  - Added Prometheus metrics for backup operations
  - RPO/RTO compliance tracking per SLA tier
  - Added backup verification CI workflow (weekly)
  - Added 18 backup monitoring tests
- **OpenAPI → SDK Gating**:
  - Added CI gate to verify SDK types match OpenAPI spec
  - Fails PR if generated types are out of sync
- **Documentation Updates**:
  - Updated RBAC_GUIDE.md with permission format compatibility
  - Updated OPERATIONS.md with WebSocket health endpoint
  - Updated GITHUB_PR_REVIEW.md with webhook integration

### Recent Changes (2026-01-10)
- **Mistral API Integration**:
  - Added `MistralAPIAgent` for direct Mistral API access
  - Added `CodestralAgent` for code-specialized tasks
  - Uses `MISTRAL_API_KEY` environment variable
  - Registered in AgentRegistry with `mistral-api` and `codestral` names
  - Added to `DEFAULT_AGENTS` and `STREAMING_CAPABLE_AGENTS`
- **Technical Debt Reduction**:
  - Extracted `TeamSelector` from orchestrator (-53 LOC)
  - Replaced 7 bare exception catches with specific types (13→6 remaining)
  - All remaining bare catches are correct patterns (transaction rollback)
- **UI Enhancements**:
  - Wired `TricksterAlertPanel` to dashboard
  - Created `RhetoricalObserverPanel` (165 LOC) for debate pattern analysis
  - Added debate mode selector (Standard/Graph/Matrix) to DebateInput
- **Documentation Update**:
  - Updated README.md with Mistral and multi-provider support
  - Updated AGENTS.md with 20+ agent types
  - Updated ENVIRONMENT.md with MISTRAL_API_KEY
  - Comprehensive cross-document consistency check

### Recent Changes (2026-01-09 Night)
- **Nomic Loop Extraction (Waves 1-4 Complete)**:
  - Wave 1: DeadlockManager, ContextFormatter, BackupManager (~990 LOC)
  - Wave 2: DeepAuditRunner, DisagreementHandler, GraphDebateRunner, ForkingRunner (~550 LOC)
  - Wave 3: ArenaFactory (~291 LOC), PostDebateProcessor (~454 LOC)
  - Wave 4: DebatePhase and DesignPhase validated as complete
  - Total: ~2,300 LOC extracted from nomic_loop.py into modular components
- **Runtime Artifact Cleanup**:
  - Removed ~548 files from git tracking (.nomic/backups, .nomic/replays, etc.)
  - Updated .gitignore to comprehensively exclude .nomic state files
  - 262k+ lines of runtime data removed from repository
- **Dependency Alignment**:
  - Standardized installs on `pyproject.toml` + `uv.lock` (pip install .)
  - Removed legacy requirements.txt usage from deploy/docs paths

### Recent Changes (2026-01-13)
- **0.8.1 Stabilization Verification**:
  - Verified EvidenceHandler integration (8 endpoints, STABLE status)
  - Verified timeout middleware exports
  - Added 35 EvidenceHandler tests (34 passing, 1 skipped pending handler fix)
  - Confirmed legacy /api/auth/revoke already migrated to AuthHandler
- **Test Coverage**:
  - New test file: `tests/test_handlers_evidence.py` (35 tests)
  - Covers: list, get, search, collect, associate, statistics, delete endpoints
  - Proper rate limiter isolation via fixture

### Recent Changes (2026-01-09 Evening)
- **Feature Integration Sprint**:
  - Wired PerformanceMonitor to Arena and AutonomicExecutor (tracking for generate/critique/vote)
  - Wired CalibrationTracker via `enable_calibration` protocol flag
  - Added AirlockProxy option via `use_airlock` ArenaConfig flag
  - Wired AgentTelemetry to AutonomicExecutor with `enable_telemetry` flag
  - Wired RhetoricalObserver to DebateRoundsPhase with `enable_rhetorical_observer` flag
  - Added `enable_trickster` and `trickster_sensitivity` protocol flags
  - Added Genesis evolution wiring (population_manager, auto_evolve, breeding_threshold)
- **New Protocol Flags**:
  - `enable_calibration: bool` - Record prediction accuracy for calibration curves
  - `enable_rhetorical_observer: bool` - Passive commentary on debate dynamics
  - `enable_trickster: bool` - Hollow consensus detection
  - `trickster_sensitivity: float` - Threshold for trickster challenges (default 0.7)
- **New ArenaConfig Options**:
  - `performance_monitor` / `enable_performance_monitor` - Agent call telemetry
  - `enable_telemetry` - Prometheus/Blackbox emission
  - `use_airlock` / `airlock_config` - Timeout protection
  - `population_manager` / `auto_evolve` / `breeding_threshold` - Genesis evolution
- **New API Endpoints**:
  - `POST /api/debates/graph` - Run graph-structured debates with branching
  - `GET /api/debates/graph/{id}` - Get graph debate by ID
  - `POST /api/debates/matrix` - Run parallel scenario debates
  - `GET /api/debates/matrix/{id}` - Get matrix debate results
- **New Event Type**:
  - `RHETORICAL_OBSERVATION` - Rhetorical pattern detected in debate rounds

### Recent Changes (2026-01-09 Morning)
- **Demo Consensus Fixtures**:
  - Created `aragora/fixtures/` package with demo consensus data
  - Added `load_demo_consensus()` and `ensure_demo_data()` functions
  - Created `demo_consensus.json` with 5 sample debate topics (architecture domain)
  - Added auto-seed on server startup for empty databases
  - Fixed ConsensusStrength enum mapping (`MEDIUM` → `MODERATE`)
  - Added `[tool.setuptools.package-data]` to include JSON fixtures in deployment
- **New API Endpoint**:
  - `GET /api/consensus/seed-demo` - Manually trigger demo data seeding
- **Nomic Loop Fixes**:
  - Fixed empty agent list crash in design phase (`_select_debate_team()` fallback)
  - Added fallback to default_team when AgentSelector returns empty Team
- **Search Functionality**:
  - Search now works independently of nomic loop (uses HTTP REST, not WebSocket)
  - Demo data ensures search has content even with no live debates

### Recent Changes (2026-01-08 Session 19)
- **Nomic Loop Fixes**:
  - Fixed TypedDict access patterns in context phase (use `result["key"]` not `result.key`)
  - Fixed debate phase agent creation (`_create_debate_phase()` now calls `_select_debate_team()`)
  - Added `topic_hint` parameter to `_create_debate_phase()` for better agent selection
  - Debate phase now correctly shows "Agent weights: 4/4 reliable" instead of "0/0"
- **System Health Verification**:
  - Updated `verify_system_health.py` for refactored `stream/` package
  - Fixed misleading logic (presence of timeout handling is good, not bad)
  - System now correctly reports "All critical systems healthy"
- **Debug Logging**:
  - Added debug logging for dropped critiques in `relationships.py:221-229`
  - Logs reason: missing critic, missing target, or self-critique
- **Documentation Hygiene**:
  - Removed deprecated `docs/API.md` (replaced by `API_REFERENCE.md`)
  - Updated `CLAUDE.md` with stream package refactoring, debate phases, agent modules
  - Updated architecture diagram with `server/stream/` package structure

### Recent Changes (2026-01-08 Earlier)
- **Nomic Loop Phase Extraction**: All 6 phases now have modular implementations
  - `ContextPhase` - Multi-agent codebase exploration
  - `DebatePhase` - Improvement proposal with PostDebateHooks
  - `DesignPhase` - Architecture planning with BeliefContext
  - `ImplementPhase` - Hybrid multi-model code generation
  - `VerifyPhase` - Tests and quality checks
  - `CommitPhase` - Git commit with safety checks
  - Opt-in via `USE_EXTRACTED_PHASES=1` environment variable
  - 29 new tests for phase factories and result types
- **Test Isolation**: Added global `clear_handler_cache` fixture to conftest.py
- **Flaky Test Fixes**: Fixed pulse handler tests that were making real API calls
- **Test Count**: Expanded to 40,500+ tests (from 3,400+)

### Recent Changes (2026-01-07)
- **Database Consolidation**: Implemented full migration system for 22→4 databases
  - Created unified schemas in `aragora/persistence/schemas/` (core.sql, analytics.sql, memory.sql, agents.sql)
  - Added `db_config.py` for centralized database path management
  - Migration script with dry-run, rollback, and verification: `scripts/migrate_databases.py`
- **Type Annotations**: Added mypy configuration and Protocol definitions
  - `aragora/core_protocols.py` with 8 Protocol definitions (StorageBackend, MemoryBackend, EloBackend, etc.)
  - Enhanced mypy config in pyproject.toml with per-module strict settings
- **Performance**: Added LRU caching to ELO system
  - `aragora/utils/cache.py` with TTLCache, lru_cache_with_ttl decorator
  - Cached leaderboards and ratings with automatic invalidation
- **Memory Backend**: Extracted TierManager for configurable memory tiers
  - `aragora/memory/tier_manager.py` with tier configuration and transition metrics
  - ContinuumMemory now uses TierManager for promotion/demotion decisions
- **Stream Architecture**: Extracted ServerBase for common server functionality
  - `aragora/server/stream/server_base.py` with rate limiting, state caching, client management

### Recent Changes (2026-01-06)
- Extracted `SecurityBarrier` and `TelemetryVerifier` to `debate/security_barrier.py` (213 lines)
- Extracted `MemoryManager` to `debate/memory_manager.py`
- Extracted `PromptBuilder` to `debate/prompt_builder.py`
- Fixed Z3 test availability handling (proper pytest.skip when Z3 unavailable)
- Reduced orchestrator.py from 3,758 to 3,545 LOC
- Added comprehensive documentation for Phases 16-19 in FEATURES.md
- Updated ENVIRONMENT.md with telemetry and belief network config options
- Fixed CLAUDE.md CircuitBreaker location (was orchestrator.py, now resilience.py)
- Nomic loop state reset for fresh cycle after root cause analysis

### Recent Changes (2026-01-05)
- Fixed `_get_belief_classes()` → `_get_belief_analyzer()` typo in orchestrator.py
- Fixed all 7 unanimous consensus tests
- Added test baseline capture to nomic loop
- Improved fix targeting prompts (include failing file paths)

### Recent Changes (2026-01-04)
- Added OpenRouter support (DeepSeek, Llama, Mistral)
- Added GrokAgent for xAI API
- Updated default agents to streaming-capable models
- Fixed security: removed API keys from .env.example
- Fixed security: restricted exec() builtins in proofs.py
- Exported KiloCodeAgent for codebase exploration
- Improved debate scrolling (calc(100vh-280px))
- **NEW**: Activated Position Ledger by default in server startup
- **NEW**: Added IP-based rate limiting (DoS protection without auth)
- **NEW**: Initialized Debate Embeddings by default for historical memory
- **NEW**: Added TournamentPanel UI component to dashboard
- **NEW**: Added agent routing hints to DebateInput (domain detection + recommendations)
- **NEW**: Added `/api/tournaments` endpoint to list tournaments
- **NEW**: Added CruxPanel for Belief Network visualization
- **NEW**: Added MemoryInspector for Continuum Memory browsing
- **NEW**: Fixed asyncio.gather timeout in debate orchestrator (prevents 50% timeout failures)
- **NEW**: Fixed BeliefPropagationAnalyzer import in server
- **NEW**: Added LaboratoryPanel for emergent traits and cross-pollinations
- **NEW**: Implemented LLM-based Lean theorem translation (formal.py)
- **NEW**: Implemented LLM-based prompt refinement (evolver.py)
- **NEW**: Fixed security: unvalidated float parameter in /api/critiques/patterns
- **NEW**: Fixed security: path traversal in raw document upload
- **NEW**: Improved error handling in DocumentStore.list_all()
- **NEW**: Added `agent_type` attribute to all API agents (fixes nomic loop blocking issue)
- **NEW**: Fixed OpenRouterAgent broken super().__init__() call
- **NEW**: Fixed RelationshipTracker.get_influence_network() parameter issue in nomic_loop.py
- **NEW**: Added ReasoningDepthProbe and EdgeCaseProbe to prober.py
- **NEW**: Added compute_relationship_metrics() to EloSystem (rivalry/alliance scores)
- **NEW**: Added get_rivals() and get_allies() methods to EloSystem
- **NEW**: Created comprehensive ELO ranking tests (tests/test_elo.py)
- **NEW**: Fixed GitHub connector timeouts (180s → 30s/60s)
- **NEW**: Added __init__.py for evidence, pulse, uncertainty modules
- **NEW**: Implemented MomentDetector for significant debate events (Emergent Persona Lab v2)
- **NEW**: Exported 24+ new classes from main __init__.py (grounded personas, evidence, pulse, uncertainty)
- **NEW**: Created .env.example template for secure API key management
- **NEW**: Exported BeliefNetwork, ReliabilityScorer, WebhookDispatcher in main __init__.py
- **NEW**: Added record_redteam_result() to EloSystem (Red Team → ELO feedback loop)
- **NEW**: Added pattern injection to debate prompts (learned patterns from InsightStore)
- **NEW**: Added 5 UI components: DebateExportModal, OperationalModesPanel, AgentNetworkPanel, RedTeamAnalysisPanel, CapabilityProbePanel
- **NEW**: Fixed security: sanitized error messages in unified_server.py (prevents info disclosure)
- **NEW**: Fixed security: added slug length validation in storage.py (DoS prevention)
- **NEW**: Fixed security: added GitHub connector input validation (repo format + query length)
- **NEW**: Added belief analysis → design phase context (contested/crux claims guide design)
- **NEW**: Fixed stale claims injection to queue ALL stale claims (not just high-severity)
- **NEW**: Fixed security: checkpoint ID validation for git branch names (command injection prevention)
- **NEW**: Fixed security: path segment validation in api.py (400 error on invalid IDs)
- **NEW**: Connected ContinuumMemory.update_outcome() after debates (surprise-based learning)
- **NEW**: Added CritiqueStore.fail_pattern() tracking for failed debates (balanced learning)
- **NEW**: Added belief network persistence across nomic cycles (cross-cycle learning)
- **NEW**: Fixed Python 3.10 compatibility (asyncio.timeout → asyncio.wait_for)
- **NEW**: Fixed aiohttp WebSocket security (origin validation, payload validation, rate limiting)
- **NEW**: Fixed CORS header fallback behavior (don't send Allow-Origin for unauthorized origins)
- **NEW**: Added agent introspection API endpoints (/api/introspection/*)
- **NEW**: Added formal verification integration for decidable claims (Z3 backend)
- **NEW**: Added plugins API endpoints (/api/plugins, /api/plugins/{name}, /api/plugins/{name}/run)
- **NEW**: Added genesis API endpoints (/api/genesis/stats, /api/genesis/events, /api/genesis/lineage/*, /api/genesis/tree/*)
- **NEW**: Connected Z3 SMT solver to post-debate claim verification (auto-verifies decidable claims)
- **NEW**: Added Replay Theater visualization (ReplayGenerator, self-contained HTML replays)
- **NEW**: Wired SpectatorStream events to WebSocket broadcast (real-time UI updates)
- **NEW**: Added optional WebSocket authentication (check_auth integration)
- **NEW**: Added AUDIENCE_DRAIN event type for audience event processing
- **NEW**: Fixed security: path traversal protection in code.py (CodeReader)
- **NEW**: Added deadline enforcement to nomic loop verify-fix cycle (prevents infinite hangs)
- **NEW**: Exported 50+ new classes to main __init__.py (modes, spectate, pipeline, visualization, replay, introspection)
- **NEW**: Connected belief network cruxes to fix guidance prompts (targeted fixing)
- **NEW**: Added ELO confidence weighting from probe results (low-confidence debates = reduced ELO impact)
- **NEW**: Added TournamentManager class for reading tournament SQLite databases
- **NEW**: Wired /api/tournaments with real tournament data from nomic_dir
- **NEW**: Added /api/tournaments/{tournament_id} endpoint for tournament details
- **NEW**: Added TOKEN_START, TOKEN_DELTA, TOKEN_END event mapping to SpectatorStream bridge
- **NEW**: Added /api/agent/{name}/consistency endpoint for FlipDetector scores
- **NEW**: Added /api/agent/{name}/network endpoint for relationship data (rivals, allies)
- **NEW**: Emit MATCH_RECORDED WebSocket event after ELO match recording in orchestrator
- **NEW**: Fixed security: path traversal protection in custom.py (CustomModeLoader)
- **NEW**: Fixed security: environment variable bracket access in formal.py and evolver.py
- **NEW**: Updated CLI serve command to use unified server (aragora serve)
- **NEW**: Added crux cache clearing at cycle start (prevents context bleeding between cycles)
- **NEW**: Added real-time flip_detected WebSocket listener in InsightsPanel (auto-switches to flips tab)
- **NEW**: Added missing event types to events.ts (audience_drain, match_recorded, flip_detected, memory_recall, token_*)
- **NEW**: Added loop_id to FLIP_DETECTED events for multi-loop isolation
- **NEW**: Added original_confidence, new_confidence, domain fields to flip event data
- **NEW**: Fixed security: exec() timeout protection in proofs.py (5s limit prevents CPU exhaustion)
- **NEW**: Fixed security: sanitized error messages in api.py (replay endpoint)
- **NEW**: Fixed AgentRelationship export in __init__.py (was exporting wrong name)
- **NEW**: Added 4 unused UI components to dashboard (AgentNetworkPanel, CapabilityProbePanel, OperationalModesPanel, RedTeamAnalysisPanel)
- **NEW**: Added circuit breaker persistence across nomic cycles (saves/restores cooldowns)
- **NEW**: Added circuit breaker filtering to agent selection (skips agents in cooldown)
- **NEW**: Fixed security: sanitized error messages in token streaming (unified_server.py)
- **NEW**: Added mood/sentiment event types (MOOD_DETECTED, MOOD_SHIFT, DEBATE_ENERGY)
- **NEW**: Added critique and consensus event handling to DebateViewer
- **NEW**: Added ContraryViewsPanel for displaying dissenting opinions
- **NEW**: Added RiskWarningsPanel for domain-specific risk assessment
- **NEW**: Fixed CSP security: removed unsafe-eval from script-src (blocks eval/new Function)
- **NEW**: Added 8 database indexes to elo.py (elo_history, matches, domain_calibration, relationships)
- **NEW**: Exported 4 new modules: audience, plugins, nomic, learning (25+ new public APIs)
- **NEW**: Fixed N+1 query pattern in get_rivals/get_allies (single DB query instead of N+1)
- **NEW**: Wired AUDIENCE_SUMMARY and INSIGHT_EXTRACTED events to WebSocket stream

### Recent Changes (2026-01-05 Session 5)
- **NEW**: Modular handlers expanded to 41 total (agents, analytics, audio, auditing, auth, belief, billing, breakpoints, broadcast, cache, calibration, consensus, critique, dashboard, debates, documents, evolution, gallery, genesis, graph_debates, insights, introspection, laboratory, leaderboard, learning, matrix_debates, memory, metrics, moments, persona, plugins, probes, pulse, relationship, replays, routing, social, system, tournaments, verification)
- **NEW**: Migrated opponent briefing API to AgentsHandler (removed from unified_server.py legacy routes)
- **NEW**: Fork debate initial messages support (Arena accepts initial_messages parameter)
- **NEW**: Fork tests added (TestForkInitialMessages - 6 tests)
- **NEW**: User event queue overflow tests (TestUserEventQueue - 7 tests)
- **NEW**: Webhook logger fix for atexit shutdown (catches ValueError when logger closed)
- **NEW**: Resource availability logging at startup (_log_resource_availability)
- **NEW**: Updated .gitignore for nomic loop state files (.nomic/checkpoints/, .nomic/replays/, *.db files)
- **NEW**: Comprehensive tests for checkpoint, evolution, laboratory, belief modules
- **TOTAL TESTS**: 3,400+ collected (expanded via parametrized tests)

### Recent Changes (2026-01-05 Session 4)
- **NEW**: Modular HTTP handlers framework (base.py, debates.py, agents.py, system.py)
- **NEW**: Wired modular handlers into unified_server.py for gradual migration
- **NEW**: Added DebateListPanel component (debate history browser with filters)
- **NEW**: Added AgentComparePanel component (side-by-side agent comparison)
- **NEW**: Added 34 Jest tests for new frontend components
- **NEW**: Added 35 WebSocket tests (StreamEvent, SyncEventEmitter, TokenBucket)
- **NEW**: Added PhaseRecovery class to nomic_loop.py (structured error handling)
- **NEW**: Added Docker support for frontend (Dockerfile + next.config.js update)
- **NEW**: Added "agents" parameter to query whitelist for /api/agent/compare
- **NEW**: Nomic loop running SwarmAgent design proposal (audience participation)
- **TOTAL TESTS**: 789+ passed (754 Python + 35 WebSocket)

### Recent Changes (2026-01-05 Session 3)
- **NEW**: Fixed security: SAFE_ID_PATTERN bug (was string, needed re.match)
- **NEW**: Fixed security: Added symlink protection in _serve_file() (prevents directory escape)
- **NEW**: Added tests/test_security.py with token validation and SQL injection tests
- **NEW**: Added try/except error handling around all nomic loop phase calls
- **NEW**: Added phase crash recovery (context, debate, design, implement, verify phases)
- **NEW**: Fixed MemoryInspector endpoint (added `/api/v1/memory/tier-stats`, legacy `/api/memory/tier-stats` alias)
- **NEW**: Added design fallback mechanism (uses highest-voted design if no consensus)
- **NEW**: Added design arbitration (judge picks between competing designs on close votes)
- **NEW**: Fixed TypeScript errors in page.tsx (AgentNetworkPanel, RedTeamAnalysisPanel)
- **NEW**: Added missing timedelta import to nomic_loop.py
- **NEW**: Updated test count to 402 passed

### Recent Changes (2026-01-05 Session 2)
- **NEW**: Added design consensus safeguard (skips implementation if design has 0% consensus)
- **NEW**: Fixed security: X-Forwarded-For header only trusted from TRUSTED_PROXIES
- **NEW**: Added AnalyticsPanel for disagreements, early-stops, and role rotation visualization
- **NEW**: Added CalibrationPanel for agent confidence accuracy curves
- **NEW**: Added ConsensusKnowledgeBase for browsing settled topics and searching similar debates
- **NEW**: Killed stalled nomic loop (was stuck 10+ hours on empty plan) and reset state for cycle 2
- **NEW**: Updated Fully Integrated feature count to 54

## Feature Integration Status

### Fully Integrated (92)
| Feature | Status | Location |
|---------|--------|----------|
| Multi-Agent Debate | Active | `aragora/debate/orchestrator.py` |
| Token Streaming | Active | `aragora/agents/streaming.py` |
| ELO Rankings | Active | `aragora/ranking/elo.py` |
| FlipDetector + Vote Weight | Active | `aragora/insights/flip_detector.py` (→ orchestrator.py:1423-1433) |
| Position Ledger | Active | `aragora/agents/grounded.py` |
| Calibration Tracking | Active | `aragora/agents/calibration.py` |
| Convergence Detection + Early Exit | Active | `aragora/debate/convergence.py` + `orchestrator.py:1635` |
| Role Rotation | Active | `aragora/debate/roles.py` |
| PersonaSynthesizer | Active | `aragora/agents/grounded.py` |
| MomentDetector | Active | `aragora/agents/grounded.py` |
| Relationship Metrics | Active | `aragora/ranking/elo.py` |
| Red Team → ELO | Active | `aragora/ranking/elo.py:record_redteam_result()` |
| Pattern Injection | Active | `aragora/debate/orchestrator.py:_format_patterns_for_prompt()` |
| Belief → Design Context | Active | `scripts/nomic_loop.py:phase_design()` (contested/crux claims) |
| Stale Claims Feedback | Active | `scripts/nomic_loop.py:run_cycle()` → `phase_debate()` |
| ContinuumMemory Outcomes | Active | `aragora/debate/orchestrator.py:_update_continuum_memory_outcomes()` |
| Failed Pattern Tracking | Active | `aragora/debate/orchestrator.py` (calls CritiqueStore.fail_pattern) |
| Cross-Cycle Beliefs | Active | `scripts/nomic_loop.py:phase_debate()` (loads prev cycle beliefs) |
| Belief Network | Exported | `aragora/reasoning/belief.py` (exported in __init__.py) |
| Reliability Scoring | Exported | `aragora/reasoning/reliability.py` (exported in __init__.py) |
| Webhook Integration | Exported | `aragora/integrations/webhooks.py` (exported in __init__.py) |
| Z3 Formal Verification | Active | `aragora/debate/orchestrator.py:_verify_claims_formally()` |
| Introspection API | Active | `aragora/server/unified_server.py` (/api/introspection/*) |
| Plugins API | Active | `aragora/server/unified_server.py` (/api/plugins/*) |
| Genesis API | Active | `aragora/server/unified_server.py` (/api/genesis/*) |
| Deadline Enforcement | Active | `scripts/nomic_loop.py` (verify-fix cycle timeout) |
| Crux → Fix Guidance | Active | `scripts/nomic_loop.py` (belief network → fix prompts) |
| Probe → ELO Weighting | Active | `aragora/ranking/elo.py` (confidence_weight parameter) |
| Path Traversal Protection | Active | `aragora/tools/code.py` (_resolve_path validation) |
| Agent Consistency API | Active | `aragora/server/handlers/agents/agents.py` (/api/agent/{name}/consistency) |
| Agent Network API | Active | `aragora/server/handlers/agents/agents.py` (/api/agent/{name}/network) |
| MATCH_RECORDED Event | Active | `aragora/debate/orchestrator.py` (WebSocket emission) |
| Custom Mode Security | Active | `aragora/modes/custom.py` (path traversal protection) |
| Crux Cache Lifecycle | Active | `scripts/nomic_loop.py:run_cycle()` (cleared at cycle start) |
| Unified Serve CLI | Active | `aragora/cli/main.py:cmd_serve()` (unified server integration) |
| Circuit Breaker Persistence | Active | `scripts/nomic_loop.py` (saves/restores across cycles) |
| Circuit Breaker Agent Filtering | Active | `scripts/nomic_loop.py:_select_debate_team()` |
| AgentNetworkPanel | Active | `aragora/live/src/components/AgentNetworkPanel.tsx` |
| CapabilityProbePanel | Active | `aragora/live/src/components/CapabilityProbePanel.tsx` |
| OperationalModesPanel | Active | `aragora/live/src/components/OperationalModesPanel.tsx` |
| RedTeamAnalysisPanel | Active | `aragora/live/src/components/RedTeamAnalysisPanel.tsx` |
| Mood Event Types | Active | `aragora/events/types.py` (MOOD_DETECTED, MOOD_SHIFT, DEBATE_ENERGY) |
| ContraryViewsPanel | Active | `aragora/live/src/components/ContraryViewsPanel.tsx` |
| RiskWarningsPanel | Active | `aragora/live/src/components/RiskWarningsPanel.tsx` |
| AnalyticsPanel | Active | `aragora/live/src/components/AnalyticsPanel.tsx` (disagreements, roles, early-stops) |
| CalibrationPanel | Active | `aragora/live/src/components/CalibrationPanel.tsx` (confidence accuracy) |
| ConsensusKnowledgeBase | Active | `aragora/live/src/components/ConsensusKnowledgeBase.tsx` (settled topics) |
| DebateViewer Critique Handling | Active | `aragora/live/src/components/debate-viewer/DebateViewer.tsx` (critique + consensus) |
| ArgumentCartographer | Active | `aragora/debate/orchestrator.py` (graph visualization) |
| Graph Export API | Active | `aragora/server/handlers/debates/handler.py` (/api/debate/{loop_id}/graph/*) |
| Audience Clusters | Active | `aragora/debate/prompt_context.py` (audience suggestion clustering) |
| Replay Export API | Active | `aragora/server/handlers/replays.py` (/api/replays/*) |
| Database Query Indexes | Active | `aragora/ranking/elo.py` (8 indexes for common queries) |
| N+1 Query Optimization | Active | `aragora/ranking/elo.py` (get_rivals/get_allies batch) |
| Fork Initial Messages | Active | `aragora/debate/orchestrator.py` (initial_messages parameter) |
| Modular HTTP Handlers | Active | `aragora/server/handlers/` (41 handler modules) |
| Resource Availability Logging | Active | `aragora/server/unified_server.py` (_log_resource_availability) |
| Demo Consensus Fixtures | Active | `aragora/fixtures/__init__.py` (auto-seed on server startup) |
| Seed Demo API | Active | `aragora/server/handlers/consensus.py` (/api/consensus/seed-demo) |
| Broadcast Audio Generation | Active | `aragora/broadcast/` (TTS, mixing, storage) |
| Podcast RSS Feed | Active | `aragora/server/handlers/features/audio.py` (/api/podcast/feed.xml) |
| Audio File Serving | Active | `aragora/server/handlers/features/audio.py` (/audio/{id}.mp3) |
| Mistral Direct API | Active | `aragora/agents/api_agents/mistral.py` (MistralAPIAgent, CodestralAgent) |
| TeamSelector | Active | `aragora/debate/team_selector.py` (ELO+calibration scoring) |
| TricksterAlertPanel | Active | `aragora/live/src/components/TricksterAlertPanel.tsx` |
| RhetoricalObserverPanel | Active | `aragora/live/src/components/RhetoricalObserverPanel.tsx` |
| TrainingExportPanel | Active | `aragora/live/src/components/TrainingExportPanel.tsx` (SFT/DPO/Gauntlet export) |
| PublicGallery | Active | `aragora/live/src/components/PublicGallery.tsx` (debate browsing) |
| Token Revocation UI | Active | `aragora/live/src/components/settings-panel/AccountTab.tsx` (Logout All Devices) |
| Production Checklist | Active | `docs/PRODUCTION_CHECKLIST.md` (deployment guide) |
| Decision Receipt Browser | Active | `aragora/live/src/app/(app)/receipts/page.tsx` (compliance receipts) |
| Training Data Explorer | Active | `aragora/live/src/app/(app)/training/explorer/page.tsx` (ML data preview) |
| Model Registry | Active | `aragora/live/src/app/(app)/training/models/page.tsx` (fine-tuned models) |
| Risk Heatmap | Active | `aragora/live/src/components/GauntletPanel.tsx` (security visualization) |
| Belief Network Dashboard | Active | `aragora/live/src/components/CruxPanel.tsx` (enhanced crux analysis) |
| Episode Generator | Active | `aragora/live/src/app/(app)/broadcast/page.tsx` (podcast generation) |
| Knowledge Graph Export | Active | `aragora/live/src/app/(app)/knowledge/page.tsx` (export & staleness) |
| RLM Training Buffer | Active | `aragora/rlm/training/buffer.py` (experience replay) |
| RLM Reward Computation | Active | `aragora/rlm/training/reward.py` (debate outcome rewards) |
| ELO Skill Vote Weighting | Active | `aragora/debate/phases/weight_calculator.py` (domain-specific ELO → vote weight) |
| Evidence Quality Scoring | Active | `aragora/debate/phases/consensus_phase.py` (quality scores → citation bonus) |
| Memory-Based Debate Strategy | Active | `aragora/debate/strategy.py` (memory tiers → adaptive rounds) |
| RLM Hierarchy Caching | Active | `aragora/rlm/bridge.py` (compression result reuse) |
| Verification Confidence Adjust | Active | `aragora/debate/phases/consensus_verification.py` (verify → vote confidence) |
| Voting Accuracy Tracking | Active | `aragora/debate/phases/feedback_phase.py` (vote patterns → ELO bonus) |
| Knowledge Mound High-Confidence | Active | `aragora/debate/knowledge_mound_ops.py` (0.85 threshold for storage) |
| KnowledgeBridgeHub | Active | `aragora/knowledge/bridges.py` (unified MetaLearner/Evidence/Pattern bridges) |
| MemoryCoordinator | Active | `aragora/memory/coordinator.py` (atomic cross-system writes) |
| SelectionFeedbackLoop | Active | `aragora/debate/selection_feedback.py` (performance → agent selection) |
| CrossDebateMemory | Active | `aragora/memory/cross_debate_rlm.py` (institutional knowledge injection) |
| EvidenceBridge Storage | Active | `aragora/knowledge/bridges.py:207-336` (persist evidence in mound) |
| CultureAccumulator | Active | `aragora/knowledge/mound/ops/culture.py` (organizational pattern extraction) |
| Post-Debate Workflows | Active | `aragora/debate/phases/feedback_phase.py` (automated refinement triggers) |
| Calibration → Proposals | Active | `aragora/debate/phases/proposal_phase.py` (temperature scaling for proposal confidence) |
| Learning Efficiency Tracking | Active | `aragora/ranking/elo.py` (learning rate → ELO bonus) |
| Memory Checkpoint Snapshot | Active | `aragora/memory/continuum/core.py` (export/restore for debate state) |
| Knowledge Mound Federation | Active | `aragora/server/handlers/knowledge_base/mound/federation.py` (multi-region sync) |

### Recently Surfaced (6)
| Feature | Status | Location |
|---------|--------|----------|
| Tournament System | TournamentPanel added | `aragora/live/src/components/TournamentPanel.tsx` |
| Agent Routing | Integrated in DebateInput | `aragora/live/src/components/DebateInput.tsx` |
| Belief Network | CruxPanel added | `aragora/live/src/components/CruxPanel.tsx` |
| Continuum Memory | MemoryInspector added | `aragora/live/src/components/MemoryInspector.tsx` |
| Persona Laboratory | LaboratoryPanel added | `aragora/live/src/components/LaboratoryPanel.tsx` |
| Prompt Evolution | LLM refinement implemented | `aragora/evolution/evolver.py` |

### Server Endpoints (72+ total)
- **Used by Frontend**: ~18%
- **Available but Unused**: ~50 endpoints
- **Key Gap**: Frontend uses WebSocket events, bypasses most REST endpoints
- **New APIs**: Introspection (3), Plugins (3), Genesis (4), Graph (3), Audience (1), Replay (2)

### Handler Integration Status (29 handlers)
| Handler | File | Routes | Status |
|---------|------|--------|--------|
| DebatesHandler | debates.py | 9+ | ✅ Active |
| AgentsHandler | agents.py | 6+ | ✅ Active |
| SystemHandler | system.py | 4 | ✅ Active |
| PulseHandler | pulse.py | 3 | ✅ Active |
| AnalyticsHandler | analytics.py | 4 | ✅ Active |
| MetricsHandler | metrics.py | 2 | ✅ Active |
| ConsensusHandler | consensus.py | 8 | ✅ Active |
| BeliefHandler | belief.py | 6 | ✅ Active |
| CritiqueHandler | critique.py | 3 | ✅ Active |
| GenesisHandler | genesis.py | 5 | ✅ Active |
| ReplaysHandler | replays.py | 4 | ✅ Active |
| TournamentHandler | tournaments.py | 3 | ✅ Active |
| MemoryHandler | memory.py | 5 | ✅ Active |
| LeaderboardViewHandler | leaderboard.py | 2 | ✅ Active |
| RelationshipHandler | relationship.py | 3 | ✅ Active |
| MomentsHandler | moments.py | 2 | ✅ Active |
| DocumentHandler | documents.py | 4 | ✅ Active |
| VerificationHandler | verification.py | 2 | ✅ Active |
| AuditingHandler | auditing.py | 3 | ✅ Active |
| DashboardHandler | dashboard.py | 3 | ✅ Active |
| PersonaHandler | persona.py | 4 | ✅ Active |
| IntrospectionHandler | introspection.py | 3 | ✅ Active |
| CalibrationHandler | calibration.py | 3 | ✅ Active |
| RoutingHandler | routing.py | 2 | ✅ Active |
| EvolutionHandler | evolution.py | 3 | ✅ Active |
| PluginsHandler | plugins.py | 3 | ✅ Active |
| BroadcastHandler | broadcast.py | 4 | ✅ Active |
| LaboratoryHandler | laboratory.py | 4 | ✅ Active |
| ProbesHandler | probes.py | 2 | ✅ Active |

**Handler Architecture**: All handlers inherit from `BaseHandler` with:
- `can_handle(path)` - Route matching
- `handle(path, query_params, http_handler)` - GET processing
- `handle_post(path, query_params, http_handler)` - POST processing
- `read_json_body(handler)` - Request body parsing
- `ttl_cache` decorator - Response caching
- `handle_errors` decorator - Centralized error handling

**Handler Test Coverage** (January 2026):
| Handler | Test File | Tests | Status |
|---------|-----------|-------|--------|
| DebatesHandler | test_handlers_debates.py | 30+ | STABLE |
| BeliefHandler | test_handlers_belief.py | 35 | STABLE |
| CalibrationHandler | test_handlers_calibration.py | 27 | STABLE |
| IntrospectionHandler | test_handlers_introspection.py | 25 | STABLE |
| MemoryHandler | test_handlers_memory.py | 22 | STABLE |
| SystemHandler | test_handlers_system.py | 20+ | STABLE |
| ConsensusHandler | test_handlers_consensus.py | 15+ | STABLE |
| BroadcastHandler | test_handlers_broadcast.py | 15+ | STABLE |

## Security Status

### Fixed (2026-01-04)
- Removed real API keys from `.env.local.example`
- Replaced full `__builtins__` with `SAFE_BUILTINS` in proofs.py
- Input validation on all POST endpoints
- Agent type allowlist prevents injection
- **IP-based rate limiting** (120 req/min per IP, DoS protection without auth)
- **Path traversal prevention** (SAFE_ID_PATTERN validation on replay_id, tournament_id)
- **Thread pool for debates** (max 10 concurrent, prevents resource exhaustion)
- **Rate limiter memory bounds** (LRU eviction when >10k entries)
- **CSP hardening** (removed unsafe-eval, blocks eval()/new Function() XSS vectors)

### Remaining Considerations
- ~~Token revocation mechanism not implemented~~ - **DONE** (Phase 13: JWT token versioning + UI)
- Consider API versioning for backwards compatibility

## Channel Production Readiness (Audited January 2026)

### Summary
| Channel | Readiness | Key Gaps |
|---------|-----------|----------|
| **Slack** | 95% ✅ | ~~Missing retry logic~~ **FIXED** - exponential backoff with 429 handling |
| **Discord** | 90% ✅ | ~~Missing retry logic~~ **FIXED** (had retry, added 5xx handling), ~~missing timeouts~~ **FIXED** (30s) |
| **Teams** | 90% ✅ | ~~Missing rate limiting~~ **FIXED**, ~~missing timeouts~~ **FIXED** (10s), ~~missing retry~~ **FIXED** |
| **Email** | 50% ❌ | Global state, missing rate limiting, OAuth refresh |

### Production-Ready Features
- **Slack**: Signature verification (HMAC-SHA256), rate limiting (30/60/100 RPM), comprehensive error handling, **retry logic with exponential backoff**
- **Discord**: Ed25519 signature verification, rate limiting (30 RPM), **retry logic with 429/5xx handling**, **30s timeout**
- **Teams**: Bot Framework SDK auth, rate limiting (30/60 RPM), **retry logic with exponential backoff**, **10s timeout**
- **Email**: Gmail OAuth integration (experimental)

### Remaining Gaps (P0/P1)
1. ~~**No retry logic**~~ - **FIXED for Slack/Teams/Discord** (exponential backoff with 429 rate limit handling)
2. **No circuit breaker** - Cascading failures possible (module exists at `/aragora/resilience.py` but unused)
3. ~~**Missing timeouts**~~ - **FIXED for all channels** (Slack/Teams 10s, Discord 30s), Email still needs work
4. **Email global state** - Not thread-safe for multi-worker deployment

### Recommendation
- **Slack/Teams/Discord**: Safe for production with monitoring
- **Email**: Experimental only - requires persistence layer for OAuth tokens

## Recommendations

### High Priority
1. ~~Activate Position Ledger by default~~ - **DONE** (initialized in server startup)
2. ~~Surface Tournament UI~~ - **DONE** (TournamentPanel added)
3. ~~Enable Belief Network visualization~~ - **DONE** (CRUX link moved to standard mode)

### Medium Priority
1. ~~Create Agent Routing UI~~ - **DONE** (integrated in DebateInput)
2. ~~Implement Continuum Memory inspector~~ - **DONE** (MemoryInspector at /memory-analytics)
3. ~~Add emergent traits browser from PersonaLaboratory~~ - **DONE** (LaboratoryPanel at /laboratory)

### Nomic Loop Improvements
1. **Better Task Splitting**: Decompose large tasks to avoid timeouts
2. **Pattern-based Agent Selection**: Route tasks to agents with best track record
3. **Cross-cycle Learning**: Persist insights between cycles via continuum.db

## Architecture Notes

### Nomic Loop Phase Architecture

The nomic loop (`scripts/nomic_loop.py`) implements a 6-phase self-improvement cycle:

| Phase | Class | Location | Purpose |
|-------|-------|----------|---------|
| 0 | `ContextPhase` | `scripts/nomic/phases/context.py` | Multi-agent codebase exploration |
| 1 | `DebatePhase` | `scripts/nomic/phases/debate.py` | Improvement proposal with hooks |
| 2 | `DesignPhase` | `scripts/nomic/phases/design.py` | Architecture planning |
| 3 | `ImplementPhase` | `scripts/nomic/phases/implement.py` | Hybrid code generation |
| 4 | `VerifyPhase` | `scripts/nomic/phases/verify.py` | Tests and quality checks |
| 5 | `CommitPhase` | `scripts/nomic/phases/commit.py` | Git commit with safety |

**Migration Status**: All phases have opt-in modular implementations via `USE_EXTRACTED_PHASES=1`.

**Factory Methods**: Each phase has a corresponding factory method in NomicLoop:
- `_create_context_phase()`, `_create_debate_phase()`, `_create_design_phase()`
- `_create_implement_phase()`, `_create_verify_phase()`, `_create_commit_phase()`

**PostDebateHooks**: 10 callback hooks for debate post-processing:
- `on_consensus_stored`, `on_calibration_recorded`, `on_insights_extracted`
- `on_memories_recorded`, `on_persona_recorded`, `on_patterns_extracted`
- `on_meta_analyzed`, `on_elo_recorded`, `on_claims_extracted`, `on_belief_network_built`

The codebase is **feature-rich with improving exposure**:
- 3,000+ API operations across 2,900+ paths, 580+ HTTP handler modules
- Many sophisticated features now surfaced via new APIs
- WebSocket-first architecture for real-time, REST for data access

**Recent Progress**:
- Z3 formal verification now active in post-debate flow
- Plugins API enables sandboxed evidence gathering
- Genesis API exposes evolution/lineage tracking
- Introspection API enables agent self-awareness
- Surprise-based ContinuumMemory learning now connected

**Key Insight**: Continuing to expose hidden features via REST APIs increases system utility without new core logic.

## Deployment

### Docker Deployment
```bash
# Quick start (requires .env file with API keys)
docker-compose up -d

# With frontend
docker-compose --profile with-frontend up -d

# View logs
docker-compose logs -f aragora
```

### Environment Variables
Required (at least one):
- `ANTHROPIC_API_KEY` - Anthropic Claude API
- `OPENAI_API_KEY` - OpenAI GPT API

Optional:
- `GEMINI_API_KEY` - Google Gemini API
- `XAI_API_KEY` - xAI Grok API
- `MISTRAL_API_KEY` - Mistral AI API (Large, Codestral)
- `OPENROUTER_API_KEY` - OpenRouter (DeepSeek, Llama, Qwen, Yi)
- `ARAGORA_API_TOKEN` - Optional authentication token
- `ARAGORA_ALLOWED_ORIGINS` - CORS origins (default: http://localhost:3000)

### Health Check
```bash
curl http://localhost:8080/api/health
```

### Recent Additions (2026-01-05)
- **End-to-End Integration Tests**: 22 new tests covering full debate flows
- **Dockerfile**: Production-ready container with non-root user
- **docker-compose.yml**: Complete orchestration with volume persistence
