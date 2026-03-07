# Feature Maturity Matrix

> **Last reviewed:** 2026-03-06
> **Snapshot basis:** 2026-01-14 / v1.5.0
> Historical maturity snapshot. It is not the current ship/no-ship source of truth. Use [STATUS](STATUS.md), [FEATURE_GAP_LIST](../FEATURE_GAP_LIST.md), [FEATURE_DISCOVERY](FEATURE_DISCOVERY.md), and [DOCUMENTATION_HYGIENE_AND_GAP_REGISTER](DOCUMENTATION_HYGIENE_AND_GAP_REGISTER.md) for current release posture.

---

## Overview

This document tracks the maturity level of Aragora features. Use this to understand which features are production-ready and which are still in development.

---

## Maturity Levels

| Level | Symbol | Description | Usage Guidelines |
|-------|--------|-------------|------------------|
| **Stable** | ![Stable](https://img.shields.io/badge/status-stable-brightgreen) | Production-ready, extensively tested, API frozen | Safe for production use |
| **Experimental** | ![Experimental](https://img.shields.io/badge/status-experimental-yellow) | Working but may change | Use with awareness, expect changes |
| **Preview** | ![Preview](https://img.shields.io/badge/status-preview-orange) | Early access, expect issues | For testing only, not production |
| **Deprecated** | ![Deprecated](https://img.shields.io/badge/status-deprecated-red) | Being phased out | Migrate to replacement |

---

## Core Features

### Debate Engine

| Feature | Status | Tests | Notes |
|---------|--------|-------|-------|
| Arena orchestration | Stable | 150+ | Core debate flow |
| Multi-round debates | Stable | 50+ | Configurable rounds |
| Consensus detection | Stable | 30+ | Multiple algorithms |
| Convergence tracking | Stable | 25+ | Semantic similarity |
| Agent selection | Stable | 40+ | ELO + calibration |
| Memory integration | Stable | 60+ | Multi-tier memory |

### Agent System

| Feature | Status | Tests | Notes |
|---------|--------|-------|-------|
| Anthropic (Claude) | Stable | 30+ | Primary provider |
| OpenAI (GPT) | Stable | 30+ | Primary provider |
| Mistral | Stable | 15+ | Code + chat models |
| Grok (xAI) | Stable | 10+ | Real-time data |
| OpenRouter fallback | Stable | 20+ | Auto-failover on 429 |
| Circuit breaker | Stable | 25+ | Failure handling |
| Rate limiting | Stable | 15+ | Per-provider limits |

### Memory System

| Feature | Status | Tests | Notes |
|---------|--------|-------|-------|
| ContinuumMemory | Stable | 66+ | Multi-tier (fast/medium/slow/glacial) |
| CritiqueStore | Stable | 40+ | Critique persistence |
| ConsensusMemory | Stable | 30+ | Historical outcomes |
| Embeddings | Experimental | 10+ | Semantic search |

---

## API Handlers

### Stable Handlers (Production-Ready)

| Handler | Endpoints | Tests | Description |
|---------|-----------|-------|-------------|
| DebatesHandler | `/api/debates/*` | 50+ | Debate CRUD operations |
| AgentsHandler | `/api/agents/*` | 40+ | Agent profiles, rankings |
| SystemHandler | `/api/system/*` | 20+ | System status, modes |
| HealthHandler | `/api/health/*` | 15+ | Health checks |
| AuthHandler | `/api/auth/*` | 60+ | Authentication, MFA |
| BillingHandler | `/api/billing/*` | 45+ | Stripe integration |
| ConsensusHandler | `/api/consensus/*` | 30+ | Consensus queries |
| MemoryHandler | `/api/v1/memory/*` | 25+ | Memory operations (legacy `/api/memory/*` supported) |
| TournamentHandler | `/api/tournaments/*` | 35+ | Tournament mode |
| GraphDebatesHandler | `/api/debates/graph/*` | 95+ | Graph visualization |
| EvolutionHandler | `/api/evolution/*` | 66+ | Agent evolution |
| LaboratoryHandler | `/api/laboratory/*` | 70+ | Experiment runner |
| GauntletHandler | `/api/gauntlet/*` | 50+ | Adversarial testing |
| InsightsHandler | `/api/insights/*` | 110+ | Pattern analysis |
| AuditingHandler | `/api/audit/*` | 55+ | Audit logs |
| OrganizationsHandler | `/api/organizations/*` | 49+ | Team management |
| WebhookHandler | `/api/webhooks/*` | 30+ | Webhook delivery |
| AdminHandler | `/api/admin/*` | 33+ | Admin operations |
| PrivacyHandler | `/api/privacy/*` | 40+ | GDPR/CCPA data export/deletion |

### Experimental Handlers

| Handler | Endpoints | Tests | Notes |
|---------|-----------|-------|-------|
| SlackHandler | `/api/slack/*` | 15+ | Slack integration - new, API may change |

---

## Integrations

### External Services

| Integration | Status | Notes |
|-------------|--------|-------|
| Stripe billing | Stable | Subscriptions, webhooks |
| Google OAuth | Stable | Single sign-on |
| GitHub OAuth | Experimental | Repository integration |
| Slack | Experimental | Notifications, slash commands |
| Discord | Preview | Bot integration |

### Infrastructure

| Integration | Status | Notes |
|-------------|--------|-------|
| PostgreSQL | Stable | Production database |
| SQLite | Stable | Development/testing |
| Redis | Stable | Caching, sessions |
| AWS S3 | Stable | File storage |
| AWS Secrets Manager | Stable | Secret management |
| Prometheus | Stable | Metrics collection |
| OpenTelemetry | Stable | Distributed tracing |
| Sentry | Stable | Error tracking |

---

## Frontend Components

### Live Dashboard

| Feature | Status | Notes |
|---------|--------|-------|
| Debate viewer | Stable | Real-time updates |
| Agent leaderboard | Stable | ELO rankings |
| Consensus gallery | Stable | Browse past debates |
| Graph visualization | Stable | D3.js graphs |
| Matrix view | Stable | Comparison matrix |
| Laboratory UI | Stable | Experiment builder |

### Admin Portal

| Feature | Status | Notes |
|---------|--------|-------|
| User management | Stable | CRUD, roles |
| Organization management | Stable | Teams, tiers |
| System metrics | Stable | Real-time dashboard |
| Audit log viewer | Stable | Searchable logs |
| Nomic controls | Stable | Pause/resume/reset |

---

## CLI Tools

| Tool | Status | Notes |
|------|--------|-------|
| `aragora serve` | Stable | Start API server |
| `aragora debate` | Stable | Run debates |
| `aragora agent` | Stable | Agent management |
| `aragora billing` | Stable | Subscription management |
| `aragora migrate` | Stable | Database migrations |
| `aragora export` | Experimental | Training data export |

---

## Feature Flags

Some features can be enabled/disabled via environment variables:

| Flag | Default | Feature |
|------|---------|---------|
| `ENABLE_GRAPH_DEBATES` | true | Graph debate visualization |
| `ENABLE_MATRIX_VIEW` | true | Matrix comparison view |
| `ENABLE_EVOLUTION` | true | Agent evolution features |
| `ENABLE_LABORATORY` | true | Experiment runner |
| `ENABLE_SLACK` | false | Slack integration |
| `ENABLE_DISCORD` | false | Discord integration |
| `ENABLE_EMBEDDINGS` | false | Experimental embeddings |

---

## Planned Features (Roadmap)

### Q1 2026

| Feature | Target Status | ETA |
|---------|---------------|-----|
| Slack integration | Stable | February |
| Discord bot | Experimental | March |
| Advanced embeddings | Stable | March |

### Q2 2026

| Feature | Target Status | ETA |
|---------|---------------|-----|
| Multi-language support | Preview | April |
| Custom agent training | Experimental | May |
| Enterprise SSO (SAML) | Stable | June |

---

## Breaking Changes

### Version 1.5.0 (Current)

No breaking changes from 1.4.x.

### Upcoming (2.0.0)

| Change | Impact | Migration |
|--------|--------|-----------|
| Memory API v2 | Medium | Migration guide TBD |
| Deprecated handlers removed | Low | Use new handler names |

---

## Feature Backlog (TODOs)

Active development items tracked in code:

| Location | Description | Priority |
|----------|-------------|----------|
| `gauntlet.py:881` | Enhanced report generation | Low |
| `video_gen.py:687` | Resolution parameter support | Low |
| `migrations/runner.py` | Template placeholders (intentional) | N/A |

---

## Stability Promotion Criteria

Features are promoted from Experimental to Stable when:

1. **Test coverage** > 80% for the module
2. **No critical bugs** in production for 30 days
3. **API frozen** - no breaking changes planned
4. **Documentation** complete
5. **Security review** passed

---

## Related Documents

- [STATUS.md](./STATUS.md) - Current system status
- [CHANGELOG.md](../deployment/RELEASE_NOTES.md) - Version history
- [API.md](../api/API_REFERENCE.md) - API documentation
- [RUNBOOK.md](../deployment/RUNBOOK.md) - Operational procedures
