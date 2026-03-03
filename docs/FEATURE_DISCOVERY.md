# Aragora Feature Discovery Guide

*Complete catalog of 180+ features for developers exploring Aragora capabilities*

This document provides a comprehensive inventory of Aragora's features organized by domain. Use this guide to discover what Aragora can do and find the relevant modules for your use case.

> **Quick Links**: [STATUS.md](STATUS.md) for implementation status | [ENTERPRISE_FEATURES.md](ENTERPRISE_FEATURES.md) for enterprise details | [API_REFERENCE.md](./api/API_REFERENCE.md) for endpoints

---

## Quick Reference

| Category | Feature Count | Status Summary |
|----------|---------------|----------------|
| [Core Debate Features](#1-core-debate-features) | 25+ | Stable |
| [Agent System](#2-agent-system) | 20+ | Stable |
| [Memory & Learning](#3-memory--learning) | 20+ | Stable |
| [Knowledge Management](#4-knowledge-management) | 30+ | Stable |
| [Enterprise Features](#5-enterprise-features) | 40+ | Production-Ready |
| [Integrations & Connectors](#6-integrations--connectors) | 50+ | Stable |
| [Observability & Monitoring](#7-observability--monitoring) | 15+ | Stable |
| [Developer Tools](#8-developer-tools) | 25+ | Stable |
| [Self-Improvement](#9-self-improvement--nomic-loop) | 12+ | Stable |

**Total**: 180+ features | 3,000+ Python modules | 208,000+ tests | 3,000+ API operations

---

## 1. Core Debate Features

### Debate Orchestration

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Arena** | Stable | Main debate engine orchestrating multi-agent discussions | `aragora/debate/orchestrator.py` | [DEBATE_PHASES.md](./debate/DEBATE_PHASES.md) |
| **Debate Phases** | Stable | Structured phases (propose, critique, revise, vote) | `aragora/debate/phases/` | [DEBATE_PHASES.md](./debate/DEBATE_PHASES.md) |
| **Consensus Detection** | Stable | Multi-strategy consensus (majority, unanimous, weighted) | `aragora/debate/consensus.py` | |
| **Convergence Detection** | Stable | Semantic similarity tracking with ANN backend | `aragora/debate/convergence.py` | |
| **Team Selection** | Stable | ELO-based agent team composition with calibration | `aragora/debate/team_selector.py` | |
| **Prompt Builder** | Stable | Dynamic prompt construction for debate context | `aragora/debate/prompt_builder.py` | |
| **Extended Rounds** | Stable | Support for 50+ round debates with RLM context management | `aragora/debate/extended_rounds.py` | |
| **Memory Manager** | Stable | Debate-scoped memory coordination | `aragora/debate/memory_manager.py` | |

### Debate Enhancements

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Trickster** | Stable | Hollow consensus detection (devil's advocate) | `aragora/debate/trickster.py` | [TRICKSTER.md](./debate/TRICKSTER.md) |
| **Rhetorical Observer** | Stable | Argument quality analysis and scoring | `aragora/debate/rhetorical_observer.py` | |
| **Security Barrier** | Stable | Telemetry redaction and content protection | `aragora/debate/security_barrier.py` | |
| **Calibration Tracker** | Stable | Agent confidence calibration via `enable_calibration` | `aragora/debate/calibration.py` | |
| **Performance Monitor** | Stable | Debate performance metrics via Arena and AutonomicExecutor | `aragora/debate/performance.py` | |
| **Graph Debates** | Stable | Graph-structured argument topology | `aragora/debate/topology.py` | [GRAPH_DEBATES.md](./debate/GRAPH_DEBATES.md) |
| **Matrix Debates** | Stable | Multi-dimensional debate analysis | `aragora/debate/matrix.py` | [MATRIX_DEBATES.md](./debate/MATRIX_DEBATES.md) |
| **Debate Breakpoints** | Stable | Pause/resume debate execution | `aragora/debate/breakpoints.py` | |
| **Hybrid Debates** | Stable | External + internal agent debates | `aragora/server/handlers/hybrid_debate.py` | |

### User Participation

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Voting** | Stable | User votes on debate positions | `aragora/debate/voting.py` |
| **Suggestions** | Stable | User suggestions during debates | `aragora/audience/suggestions.py` |
| **Audience System** | Stable | Audience engagement and spectator mode | `aragora/audience/` |
| **Spectate** | Stable | Real-time debate spectating | `aragora/spectate/` |

### Configuration

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **ArenaConfig** | Stable | Centralized debate configuration with 40+ options | `aragora/debate/arena_config.py` |
| **DebateProtocol** | Stable | Protocol parameters (rounds, consensus, concurrency) | `aragora/core.py` |
| **Orchestrator Hooks** | Stable | Extension points for custom logic | `aragora/debate/orchestrator_hooks.py` |

---

## 2. Agent System

### Supported Providers (30+ agent types)

| Provider | Type | Models | Key Files |
|----------|------|--------|-----------|
| **Anthropic** | API | Claude 3.5, Claude Opus 4.5 | `aragora/agents/api_agents/anthropic.py` |
| **OpenAI** | API | GPT-4o, GPT-4 Turbo, o1, o3 | `aragora/agents/api_agents/openai.py` |
| **Google** | API | Gemini Pro, Gemini Ultra | `aragora/agents/api_agents/gemini.py` |
| **Mistral** | API | Mistral Large, Codestral | `aragora/agents/api_agents/mistral.py` |
| **xAI** | API | Grok | `aragora/agents/api_agents/grok.py` |
| **OpenRouter** | API | DeepSeek, Llama, Qwen, Yi, Kimi | `aragora/agents/api_agents/openrouter.py` |
| **Ollama** | Local | Any GGUF model | `aragora/agents/api_agents/ollama.py` |
| **LM Studio** | Local | Any local model | `aragora/agents/api_agents/lm_studio.py` |
| **CLI Agents** | CLI | Claude, Codex, Gemini, Grok terminals | `aragora/agents/cli_agents.py` |

### Agent Features

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Agent Spec** | Stable | Unified specification parsing (`provider\|model\|persona\|role`) | `aragora/agents/spec.py` |
| **Airlock Proxy** | Stable | Agent resilience with circuit breaker via `use_airlock` | `aragora/agents/airlock.py` |
| **Fallback Chain** | Stable | Automatic OpenRouter fallback on 429 errors | `aragora/agents/fallback.py` |
| **Rate Limiter** | Stable | Per-provider rate limiting | `aragora/agents/api_agents/rate_limiter.py` |
| **Personas** | Stable | Configurable agent personalities | `aragora/agents/personas.py` |
| **Calibration** | Stable | Agent performance calibration tracking | `aragora/agents/calibration.py` |
| **Error Handling** | Stable | Unified error hierarchy | `aragora/agents/errors.py` |

### External Agents

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **External Framework** | Stable | CrewAI, LangGraph, AutoGen integration | `aragora/agents/external/` |
| **A2A Protocol** | Stable | Agent-to-Agent communication | `aragora/server/handlers/a2a.py` |
| **External Agents API** | Stable | External agent task management | `aragora/server/handlers/external_agents.py` |

---

## 3. Memory & Learning

### Memory Systems

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Continuum Memory** | Stable | Multi-tier memory (fast/medium/slow/glacial) | `aragora/memory/continuum/core.py` | |
| **Consensus Memory** | Stable | Historical debate outcome storage | `aragora/memory/consensus.py` | |
| **Memory Coordinator** | Stable | Atomic cross-system writes via `enable_coordinated_writes` | `aragora/memory/coordinator.py` | |
| **Cross-Debate Memory** | Stable | Institutional knowledge injection via `enable_cross_debate_memory` | `aragora/memory/cross_debate_rlm.py` | |
| **Supermemory** | Stable | Cross-session external memory via `enable_supermemory` (80+ tests) | `aragora/memory/supermemory.py` | |
| **Memory Streams** | Stable | Event-based memory updates | `aragora/memory/streams.py` | |
| **Embeddings** | Stable | Semantic embedding for retrieval (OpenAI, Gemini, Ollama) | `aragora/memory/embeddings.py` | |
| **Critique Store** | Stable | Critique pattern storage | `aragora/memory/store.py` | |
| **Progressive Memory Search** | Stable | Staged retrieval (index → timeline → entries) | `aragora/server/handlers/memory/memory.py` | |
| **Memory Viewer** | Stable | HTML viewer for memory inspection | `aragora/server/handlers/memory/memory.py` | |
| **Tool Usage Capture** | Optional | Opt-in tool usage capture into FAST tier | `aragora/memory/capture.py` | |

### Memory Tiers

| Tier | TTL | Purpose |
|------|-----|---------|
| Fast | 1 min | Immediate context |
| Medium | 1 hour | Session memory |
| Slow | 1 day | Cross-session learning |
| Glacial | 1 week | Long-term patterns |

### Learning & Ranking

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **ELO Rankings** | Stable | Agent skill tracking with continuous updates | `aragora/ranking/elo.py` |
| **Calibration Tracking** | Stable | Confidence calibration metrics | `aragora/ranking/calibration.py` |
| **Leaderboard** | Stable | Agent ranking leaderboards | `aragora/ranking/leaderboard.py` |
| **Tournaments** | Stable | Agent tournament competitions | `aragora/tournaments/` |
| **Selection Feedback** | Stable | Performance-based agent selection via `enable_performance_feedback` | `aragora/debate/selection_feedback.py` |
| **Learning Efficiency** | Stable | Agents who improve get ELO bonuses | `aragora/ranking/learning.py` |

### RLM (Recursive Language Models)

Based on [arXiv:2512.24601](https://arxiv.org/abs/2512.24601) - Context stored as Python variables in REPL, not prompt compression.

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **RLM Factory** | Stable | RLM context management factory | `aragora/rlm/factory.py` | [RLM_GUIDE.md](./guides/RLM_GUIDE.md) |
| **RLM Bridge** | Stable | Integration bridge for RLM | `aragora/rlm/bridge.py` | |
| **RLM Handler** | Stable | Request handling | `aragora/rlm/handler.py` | |
| **Streaming RLM** | Stable | Progressive context loading (top-down, bottom-up, targeted) | `aragora/rlm/streaming.py` | |
| **RLM Training** | Stable | Experience replay buffer and reward computation | `aragora/rlm/training/` | |
| **Cognitive Limiter** | Stable | Context management via `use_rlm_limiter` | `aragora/debate/cognitive_limiter_rlm.py` | |

---

## 4. Knowledge Management

### Knowledge Mound (Phase A2 Complete - 4,300+ tests)

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Core Storage** | Stable | Unified knowledge storage | `aragora/knowledge/mound/core.py` | [KNOWLEDGE_MOUND.md](./knowledge/KNOWLEDGE_MOUND.md) |
| **Semantic Store** | Stable | Vector embedding-based search | `aragora/knowledge/mound/semantic.py` | |
| **Graph Store** | Stable | Relationship and lineage tracking | `aragora/knowledge/mound/graph.py` | |
| **Domain Taxonomy** | Stable | Hierarchical knowledge organization | `aragora/knowledge/mound/taxonomy.py` | |
| **Visibility Levels** | Stable | private/workspace/organization/public/system | `aragora/knowledge/mound/visibility.py` | |
| **Access Grants** | Stable | Fine-grained permissions with expiration | `aragora/knowledge/mound/access.py` | |
| **Cross-Workspace Sharing** | Stable | Share knowledge between workspaces | `aragora/knowledge/mound/sharing.py` | |
| **Federation** | Stable | Multi-region sync (push/pull/bidirectional) | `aragora/knowledge/mound/federation.py` | |
| **Deduplication** | Stable | Find and merge duplicate items | `aragora/knowledge/mound/dedup.py` | |
| **Pruning** | Stable | Archive/delete stale items with policies | `aragora/knowledge/mound/pruning.py` | |
| **Auto-Curation** | Stable | Automated knowledge maintenance with quality scoring | `aragora/knowledge/mound/curation.py` | |
| **Contradiction Detection** | Stable | Identify conflicting knowledge | `aragora/knowledge/mound/contradictions.py` | |
| **Confidence Decay** | Stable | Time-based confidence scoring | `aragora/knowledge/mound/confidence.py` | |
| **RBAC Governance** | Stable | Permission-based knowledge access | `aragora/knowledge/mound/rbac.py` | |
| **KM Resilience** | Stable | ResilientPostgresStore with retry, health, cache invalidation | `aragora/knowledge/mound/resilience.py` | |
| **SLO Alerting** | Stable | Adapter performance monitoring with Prometheus | `aragora/config/performance_slos.py` | |

### Knowledge Adapters (25 Total)

| Adapter | Purpose | Key Files |
|---------|---------|-----------|
| **Belief** | Belief network integration | `aragora/knowledge/mound/adapters/belief_adapter.py` |
| **CalibrationFusion** | Calibration data integration | `aragora/knowledge/mound/adapters/calibration_fusion_adapter.py` |
| **ComputerUse** | Computer use data | `aragora/knowledge/mound/adapters/computer_use_adapter.py` |
| **Consensus** | Debate consensus storage | `aragora/knowledge/mound/adapters/consensus_adapter.py` |
| **Continuum** | Memory tier integration | `aragora/knowledge/mound/adapters/continuum_adapter.py` |
| **ControlPlane** | Control plane data | `aragora/knowledge/mound/adapters/control_plane_adapter.py` |
| **Cost** | Cost tracking and alerts | `aragora/knowledge/mound/adapters/cost_adapter.py` |
| **Critique** | Critique pattern storage | `aragora/knowledge/mound/adapters/critique_adapter.py` |
| **Culture** | Organizational culture patterns | `aragora/knowledge/mound/adapters/culture_adapter.py` |
| **ELO** | Agent rankings | `aragora/knowledge/mound/adapters/elo_adapter.py` |
| **ERC8004** | ERC-8004 compliance | `aragora/knowledge/mound/adapters/erc8004_adapter.py` |
| **Evidence** | Evidence snippet storage | `aragora/knowledge/mound/adapters/evidence_adapter.py` |
| **Extraction** | Knowledge extraction | `aragora/knowledge/mound/adapters/extraction_adapter.py` |
| **Fabric** | Fabric integration | `aragora/knowledge/mound/adapters/fabric_adapter.py` |
| **Gateway** | Gateway data | `aragora/knowledge/mound/adapters/gateway_adapter.py` |
| **Insights** | Analytical insights and Trickster flips | `aragora/knowledge/mound/adapters/insights_adapter.py` |
| **OpenClaw** | OpenClaw integration | `aragora/knowledge/mound/adapters/openclaw_adapter.py` |
| **Performance** | Performance metrics | `aragora/knowledge/mound/adapters/performance_adapter.py` |
| **Provenance** | Decision provenance | `aragora/knowledge/mound/adapters/provenance_adapter.py` |
| **Pulse** | Trending topics | `aragora/knowledge/mound/adapters/pulse_adapter.py` |
| **Ranking** | Performance rankings | `aragora/knowledge/mound/adapters/ranking_adapter.py` |
| **Receipt** | Decision receipts auto-persist | `aragora/knowledge/mound/adapters/receipt_adapter.py` |
| **RLM** | RLM context integration | `aragora/knowledge/mound/adapters/rlm_adapter.py` |
| **Supermemory** | External memory integration | `aragora/knowledge/mound/adapters/supermemory_adapter.py` |
| **Workspace** | Workspace data | `aragora/knowledge/mound/adapters/workspace_adapter.py` |
| **Adapter Factory** | Auto-create adapters from Arena subsystems | `aragora/knowledge/mound/adapters/factory.py` |

### Knowledge Bridges

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **KnowledgeBridgeHub** | Stable | Unified access to all bridges | `aragora/knowledge/bridges.py` |
| **MetaLearner Bridge** | Stable | Cross-memory optimization | `aragora/knowledge/metalearner.py` |
| **Evidence Bridge** | Stable | Evidence collection and storage | `aragora/knowledge/evidence.py` |
| **Pattern Bridge** | Stable | Pattern recognition and storage | `aragora/knowledge/patterns.py` |

### Reasoning & Provenance

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Belief Network** | Stable | Claim provenance tracking with cruxes | `aragora/reasoning/belief.py` | [REASONING.md](./workflow/REASONING.md) |
| **Provenance Tracking** | Stable | Decision lineage and audit trails | `aragora/reasoning/provenance.py` | |
| **Claims System** | Stable | Structured claim management | `aragora/reasoning/claims.py` | |

---

## 5. Enterprise Features

### Authentication & Authorization

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **OIDC Integration** | Production | OpenID Connect SSO with JWK verification | `aragora/auth/oidc.py` | [SSO_SETUP.md](./enterprise/SSO_SETUP.md) |
| **SAML Support** | Production | SAML 2.0 enterprise IdP integration | `aragora/auth/saml.py` | |
| **MFA (TOTP/HOTP)** | Production | Multi-factor via authenticator apps | `aragora/server/middleware/mfa.py` | |
| **API Key Management** | Production | Scoped keys with rotation and usage tracking | `aragora/server/handlers/auth/` | |
| **Session Management** | Production | Token versioning, lockout tracking, cleanup | `aragora/server/session_store.py` | [SESSION_MANAGEMENT.md](./enterprise/SESSION_MANAGEMENT.md) |
| **SCIM 2.0** | Production | Automated user/group provisioning (Okta, Azure AD, OneLogin) | `aragora/auth/scim/` | |
| **Account Lockout** | Production | Progressive delays, IP/user tracking | `aragora/auth/lockout.py` | |

### RBAC v2 (50+ Permissions)

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Permission Models** | Production | Fine-grained permission dataclasses | `aragora/rbac/models.py` |
| **Default Roles** | Production | 7 pre-configured roles (admin, editor, viewer, etc.) | `aragora/rbac/types.py` |
| **Permission Checker** | Production | Cached permission evaluation with wildcards | `aragora/rbac/checker.py` |
| **Decorators** | Production | @require_permission, @require_role, @require_admin | `aragora/rbac/decorators.py` |
| **Middleware** | Production | HTTP route protection | `aragora/rbac/middleware.py` |
| **Audit Logging** | Production | Authorization audit trails | `aragora/rbac/audit.py` |

### Multi-Tenancy

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Tenant Isolation** | Production | SQL query auto-filtering by tenant ID | `aragora/tenancy/isolation.py` |
| **Resource Quotas** | Production | Per-tenant limits (debates, API calls, storage) | `aragora/tenancy/quotas.py` |
| **Usage Metering** | Production | Tenant-aware tracking with billing events | `aragora/billing/metering.py` |
| **Tenant Context** | Production | Thread/async-safe context propagation | `aragora/tenancy/context.py` |

### Security

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **AES-256-GCM Encryption** | Production | Field-level encryption with key derivation | `aragora/security/encryption.py` | [SECRETS.md](./enterprise/SECRETS.md) |
| **Cloud KMS** | Production | AWS KMS, Azure Key Vault, GCP Cloud KMS | `aragora/security/kms_provider.py` | |
| **Key Rotation** | Production | Automatic key rotation with versioning | `aragora/security/key_rotation.py` | |
| **Encrypted Fields** | Production | OAuth tokens, API keys, secrets auto-encrypted | `aragora/storage/encrypted_fields.py` | |
| **Anomaly Detection** | Production | Security anomaly detection | `aragora/security/anomaly_detection.py` | |
| **SSRF Protection** | Production | Server-side request forgery protection | `aragora/security/ssrf_protection.py` | |
| **Rate Limiting** | Production | Multi-layer (IP, token, endpoint) with Redis backend | `aragora/server/rate_limit.py` | [RATE_LIMITING.md](./api/RATE_LIMITING.md) |
| **Circuit Breaker** | Production | Per-provider thresholds, recovery timeout | `aragora/resilience.py` | |
| **Security Headers** | Production | CSP, HSTS, X-Frame-Options | `aragora/server/middleware/security_headers.py` | |

### Compliance & Governance

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Audit Trail** | Production | Tamper-evident logging with hash chains | `aragora/audit/` | |
| **SOC 2 Controls** | Production | SOC 2 Type II compliance controls | `aragora/compliance/soc2.py` | |
| **GDPR Support** | Production | DSAR workflow, right to erasure, portability | `aragora/privacy/` | [DSAR_WORKFLOW.md](./enterprise/DSAR_WORKFLOW.md) |
| **Consent Management** | Production | User consent tracking | `aragora/privacy/consent.py` | |
| **Data Retention** | Production | Configurable retention policies | `aragora/privacy/retention.py` | |
| **Deletion Coordinator** | Production | Unified GDPR deletion across systems | `aragora/deletion_coordinator.py` | |
| **Data Anonymization** | Production | PII anonymization | `aragora/privacy/anonymization.py` | |

### Backup & Disaster Recovery

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Backup Manager** | Production | Incremental backups with retention | `aragora/backup/manager.py` |
| **DR Drills** | Production | Disaster recovery testing | `aragora/backup/dr_drill.py` |
| **PostgreSQL Backends** | Production | Full horizontal scaling for 11 storage modules | `aragora/storage/postgres_store.py` |

---

## 6. Integrations & Connectors

### Chat Platforms

| Platform | Status | Features | Key Files |
|----------|--------|----------|-----------|
| **Slack** | Stable | Bot, OAuth, webhooks, evidence collection | `aragora/connectors/chat/slack/` |
| **Discord** | Stable | Guilds, channels, DMs, reactions, Ed25519 verification | `aragora/connectors/chat/discord.py` |
| **Teams** | Stable | Teams, channels, meetings, JWT verification | `aragora/connectors/chat/teams.py` |
| **Google Chat** | Stable | Spaces, messages, JWT verification | `aragora/connectors/chat/google_chat.py` |
| **Telegram** | Stable | Bot integration with TTS support | `aragora/connectors/chat/telegram.py` |
| **WhatsApp** | Stable | Business API with voice notes | `aragora/connectors/chat/whatsapp.py` |

### Enterprise Streaming

| System | Status | Features | Key Files |
|--------|--------|----------|-----------|
| **Apache Kafka** | Stable | Consumer groups, offset tracking, JSON/Avro/Protobuf | `aragora/connectors/enterprise/streaming/kafka.py` |
| **RabbitMQ** | Stable | Exchange/queue binding, DLQ, bidirectional | `aragora/connectors/enterprise/streaming/rabbitmq.py` |

### Data Sources

| Source | Status | Features | Key Files |
|--------|--------|----------|-----------|
| **GitHub** | Stable | Repos, PRs, issues, code search, webhooks | `aragora/connectors/github.py` |
| **ArXiv** | Stable | Paper search, metadata, PDFs | `aragora/connectors/arxiv.py` |
| **Wikipedia** | Stable | Article content, references | `aragora/connectors/wikipedia.py` |
| **SEC Filings** | Stable | Company filings, financial data | `aragora/connectors/sec.py` |
| **HackerNews** | Stable | Trending tech topics | `aragora/pulse/ingestors/hackernews.py` |
| **Reddit** | Stable | Subreddit discussions | `aragora/pulse/ingestors/reddit.py` |
| **Twitter/X** | Stable | Trending topics | `aragora/pulse/ingestors/twitter.py` |

### Enterprise Systems

| System | Status | Features | Key Files |
|--------|--------|----------|-----------|
| **SharePoint** | Stable | Document libraries, metadata | `aragora/connectors/enterprise/documents/sharepoint.py` |
| **Confluence** | Stable | Pages, spaces, attachments | `aragora/connectors/enterprise/collaboration/confluence.py` |
| **Notion** | Stable | Databases, pages | `aragora/connectors/enterprise/collaboration/notion.py` |
| **PostgreSQL** | Stable | CDC with LISTEN/NOTIFY | `aragora/connectors/enterprise/database/postgres.py` |
| **MongoDB** | Stable | Document queries | `aragora/connectors/enterprise/database/mongodb.py` |
| **MySQL** | Stable | Binlog CDC | `aragora/connectors/enterprise/database/mysql.py` |
| **SQL Server** | Stable | CDC/Change Tracking | `aragora/connectors/enterprise/database/sqlserver.py` |
| **Snowflake** | Stable | Table sync, time travel | `aragora/connectors/enterprise/database/snowflake.py` |
| **Salesforce** | Stable | CRM sync | `aragora/connectors/enterprise/salesforce.py` |
| **HubSpot** | Stable | CRM sync | `aragora/connectors/enterprise/hubspot.py` |
| **Zendesk** | Stable | Support tickets | `aragora/connectors/enterprise/zendesk.py` |
| **Jira** | Stable | Issue tracking | `aragora/connectors/enterprise/jira.py` |

### Advertising & Marketing

| Platform | Status | Features | Key Files |
|----------|--------|----------|-----------|
| **Twitter/X Ads** | Stable | Campaign management, OAuth 1.0a | `aragora/connectors/advertising/twitter_ads.py` |
| **TikTok Ads** | Stable | Campaigns, pixel, audiences, OAuth 2.0 | `aragora/connectors/advertising/tiktok_ads.py` |
| **Mailchimp** | Stable | Audiences, campaigns, automations | `aragora/connectors/marketing/mailchimp.py` |
| **Klaviyo** | Stable | Email/SMS marketing, JSON:API | `aragora/connectors/marketing/klaviyo.py` |
| **Segment** | Stable | CDP tracking, profiles, batch | `aragora/connectors/analytics/segment.py` |

### Email & Communication

| Platform | Status | Features | Key Files |
|----------|--------|----------|-----------|
| **Gmail Sync** | Stable | Pub/Sub real-time, History API, EmailPrioritizer | `aragora/connectors/email/gmail_sync.py` |
| **Outlook Sync** | Stable | Graph change notifications, Delta Query | `aragora/connectors/email/outlook_sync.py` |
| **Twilio Voice** | Stable | Phone-triggered debates, TwiML, HMAC-SHA1 | `aragora/integrations/twilio_voice.py` |
| **Generic SMTP** | Stable | Send/receive email | `aragora/connectors/email/` |

### Healthcare (HIPAA-compliant)

| System | Status | Features | Key Files |
|--------|--------|----------|-----------|
| **HL7v2** | Stable | Message parsing | `aragora/connectors/enterprise/healthcare/hl7.py` |
| **FHIR** | Stable | Resource queries | `aragora/connectors/enterprise/healthcare/fhir.py` |

### Bidirectional Chat Routing

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Debate Origin Tracking** | Stable | Track where debates originate | `aragora/server/debate_origin.py` |
| **Result Router** | Stable | Route results back to originating platform | `aragora/server/result_router.py` |
| **TTS Integration** | Stable | Voice synthesis for chat channels | `aragora/server/stream/tts_integration.py` |

---

## 7. Observability & Monitoring

### Metrics & Tracing

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Prometheus Metrics** | Stable | 14+ custom metrics (requests, latency, agents, debates) | `aragora/observability/metrics.py` | |
| **OpenTelemetry Tracing** | Stable | Distributed tracing with context propagation | `aragora/observability/tracing.py` | |
| **OTLP Export** | Stable | Jaeger, Zipkin, Datadog exporters | `aragora/observability/otlp_export.py` | |
| **Grafana Dashboards** | Stable | Pre-built dashboards for all metrics | `deploy/grafana/` | |
| **SLO Framework** | Stable | Service level objectives with breach alerting | `aragora/observability/slo.py` | |

### Logging & Alerting

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Structured Logging** | Stable | JSON logs with correlation IDs, PII redaction | `aragora/observability/logging.py` | |
| **Alert Runbooks** | Stable | Automated alert responses | `docs/ALERT_RUNBOOKS.md` | [ALERT_RUNBOOKS.md](./deployment/ALERT_RUNBOOKS.md) |

### Health Monitoring

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Health Checks** | Stable | Liveness and readiness probes | `aragora/control_plane/health.py` |
| **Circuit Breaker Metrics** | Stable | Agent failure tracking and recovery | `aragora/resilience.py` |
| **Connection Pooling** | Stable | Adaptive pool with health monitoring | `aragora/server/connection_pool.py` |
| **Redis HA** | Stable | Sentinel/Cluster with failover | `aragora/storage/redis_ha.py` |

---

## 8. Developer Tools

### API & Server

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Unified Server** | Stable | 3,000+ API operations | `aragora/server/unified_server.py` | [API_REFERENCE.md](./api/API_REFERENCE.md) |
| **Handler Registry** | Stable | O(1) route lookup with LRU caching | `aragora/server/handler_registry.py` | |
| **GraphQL API** | Stable | Schema for debates, agents, memory | `aragora/server/graphql/` | |
| **WebSocket Streaming** | Stable | 26 stream modules for real-time events | `aragora/server/stream/` | |
| **Postman Generator** | Stable | API collection export | `aragora/server/postman_generator.py` | |

### SDKs

| SDK | Status | Namespaces | Key Files |
|-----|--------|------------|-----------|
| **Python SDK** | Stable | 105 namespaces | `sdk/python/` |
| **TypeScript SDK** | Stable | 140 namespaces | `sdk/typescript/` |

### CLI

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **CLI Main** | Stable | Command-line interface | `aragora/cli/main.py` |
| **REPL** | Stable | Interactive shell | `aragora/cli/repl.py` |
| **Setup Wizard** | Stable | Guided `aragora setup` for self-hosted | `aragora/cli/setup.py` |
| **Gauntlet CLI** | Stable | Compliance test runner | `aragora/cli/gt.py` |

### Workflow Engine

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Workflow Engine** | Stable | DAG-based automation | `aragora/workflow/engine.py` | [WORKFLOWS.md](./workflow/WORKFLOWS.md) |
| **Workflow Nodes** | Stable | Reusable node types | `aragora/workflow/nodes/` | |
| **Workflow Patterns** | Stable | Hive-mind, map-reduce, review-cycle factories | `aragora/workflow/patterns/` | |
| **Workflow Templates** | Stable | 60+ pre-built templates across 6 categories | `aragora/workflow/templates/` | |
| **Post-Debate Workflows** | Stable | Automated processing via `enable_post_debate_workflow` | `aragora/workflow/triggers.py` | |

### Gauntlet (Compliance Testing)

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Gauntlet Runner** | Stable | Compliance test execution | `aragora/gauntlet/runner.py` | [GAUNTLET.md](./debate/GAUNTLET.md) |
| **Decision Receipts** | Stable | SHA-256 cryptographic audit trails | `aragora/gauntlet/receipts.py` | |
| **Findings** | Stable | Compliance findings management | `aragora/gauntlet/findings.py` | |
| **Gauntlet Defense** | Stable | Attack/defend cycles via `proposer_agent` | `aragora/gauntlet/defense.py` | |
| **Personas** | Stable | GDPR, SOC2, HIPAA, PCI-DSS, AI Act, NIST CSF | `aragora/gauntlet/personas/` | |

### Explainability

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Decision Builder** | Stable | Natural language explanations | `aragora/explainability/builder.py` |
| **Factor Decomposition** | Stable | Agent contributions, evidence quality, consensus strength | `aragora/explainability/factors.py` |
| **Counterfactuals** | Stable | What-if scenario analysis | `aragora/explainability/counterfactual.py` |

### MCP (Model Context Protocol)

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **MCP Server** | Stable | Context protocol server | `aragora/mcp/server.py` | [MCP_INTEGRATION.md](./integrations/MCP_INTEGRATION.md) |
| **MCP Tools** | Stable | Tool definitions | `aragora/mcp/tools.py` | [MCP_ADVANCED.md](./integrations/MCP_ADVANCED.md) |

### Agent Marketplace

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Template Registry** | Stable | Agent, debate, workflow templates | `aragora/marketplace/` | [MARKETPLACE.md](./workflow/MARKETPLACE.md) |
| **Built-in Templates** | Stable | Devil's Advocate, Code Reviewer, Research Analyst | `aragora/marketplace/templates/` | |

---

## 9. Self-Improvement & Nomic Loop

### Nomic Loop

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Nomic Loop** | Stable | Autonomous improvement cycles (5 phases) | `scripts/nomic_loop.py` |
| **Staged Execution** | Stable | Phase-by-phase control | `scripts/nomic_staged.py` |
| **Self Develop** | Stable | Goal-driven decomposition with `--dry-run` | `scripts/self_develop.py` |
| **Meta Planner** | Stable | Debate-driven goal prioritization | `aragora/nomic/meta_planner.py` |
| **Branch Coordinator** | Stable | Parallel branch management | `aragora/nomic/branch_coordinator.py` |
| **Task Decomposer** | Stable | Complex task breakdown (heuristic or debate) | `aragora/nomic/task_decomposer.py` |
| **Autonomous Orchestrator** | Stable | End-to-end orchestration | `aragora/nomic/autonomous_orchestrator.py` |

### Nomic Loop Phases

| Phase | Name | Purpose |
|-------|------|---------|
| 0 | Context | Gather codebase understanding |
| 1 | Debate | Agents propose improvements |
| 2 | Design | Architecture planning |
| 3 | Implement | Code generation (Codex/Claude) |
| 4 | Verify | Tests and checks |

### Autonomous Operations

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Self-Improvement Manager** | Stable | Orchestrates autonomous cycles | `aragora/autonomous/loop_enhancement.py` |
| **Continuous Learning** | Stable | Real-time ELO updates, pattern extraction | `aragora/autonomous/continuous_learning.py` |
| **Proactive Intelligence** | Stable | Scheduled triggers, anomaly detection | `aragora/autonomous/proactive_intelligence.py` |
| **Human-in-the-Loop** | Stable | Approval flows with risk assessment | `aragora/autonomous/approvals.py` |
| **Code Verifier** | Stable | AST syntax validation and test execution | `aragora/autonomous/loop_enhancement.py` |
| **Rollback Manager** | Stable | File backup, restore, cleanup | `aragora/autonomous/loop_enhancement.py` |

---

## 10. Control Plane (1,500+ tests)

### Agent Management

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Agent Registry** | Stable | Agent discovery with heartbeats | `aragora/control_plane/registry.py` |
| **Task Scheduler** | Stable | Priority-based distribution | `aragora/control_plane/scheduler.py` |
| **Health Monitoring** | Stable | Liveness probes | `aragora/control_plane/health.py` |
| **Coordinator** | Stable | Unified control plane API | `aragora/control_plane/coordinator.py` |
| **Leader Election** | Stable | Distributed coordination | `aragora/control_plane/leader.py` |

### Governance

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Policy Engine** | Stable | Policy governance | `aragora/control_plane/policy.py` |
| **Policy Conflict Detector** | Stable | Contradictory policy detection | `aragora/control_plane/policy.py` |
| **Redis Policy Cache** | Stable | Distributed cache for fast evaluation | `aragora/control_plane/policy.py` |
| **Policy Sync Scheduler** | Stable | Background policy synchronization | `aragora/control_plane/policy.py` |

### Notifications

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Omnichannel Delivery** | Stable | Slack/Teams/Email/Webhook delivery | `aragora/control_plane/notifications.py` |
| **Notification Service** | Stable | Unified notification API | `aragora/notifications/service.py` |

---

## 11. Pulse (Trending Topics - 1,000+ tests)

| Feature | Status | Description | Key Files | Docs |
|---------|--------|-------------|-----------|------|
| **Pulse Ingestor** | Stable | Topic ingestion pipeline | `aragora/pulse/ingestor.py` | [PULSE.md](./resilience/PULSE.md) |
| **Quality Filtering** | Stable | Clickbait/spam detection | `aragora/pulse/quality.py` | |
| **Freshness Scoring** | Stable | Configurable decay curves | `aragora/pulse/freshness.py` | |
| **Source Weighting** | Stable | Credibility scores | `aragora/pulse/weighting.py` | |
| **Scheduler** | Stable | Scheduled topic refresh | `aragora/pulse/scheduler.py` | |
| **Store** | Stable | Topic persistence | `aragora/pulse/store.py` | |

---

## 12. Voice & TTS

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **TTS Integration** | Stable | Voice synthesis for debates | `aragora/server/stream/tts_integration.py` |
| **Voice Streaming** | Stable | Voice session management | `aragora/server/stream/voice_stream.py` |
| **Twilio Voice** | Stable | Phone-triggered debates | `aragora/integrations/twilio_voice.py` |
| **Speech Recognition** | Stable | Whisper transcription backends | `aragora/transcription/` |

---

## 13. Verification & Formal Methods

| Feature | Status | Description | Key Files |
|---------|--------|-------------|-----------|
| **Z3 Verification** | Stable | SMT-based verification | `aragora/verification/formal.py` |
| **Lean Backend** | Beta | Lean theorem prover | `aragora/verification/lean.py` |
| **Proof Generation** | Stable | Automated proof generation | `aragora/verification/proofs.py` |

---

## Getting Started

### Quick Start with Debate

```python
from aragora import Arena, Environment, DebateProtocol

env = Environment(task="Should we adopt microservices?")
protocol = DebateProtocol(rounds=3, consensus="majority")
arena = Arena(env, agents=["claude", "gpt4"], protocol=protocol)
result = await arena.run()
```

### Enable Knowledge Mound

```python
from aragora.debate.arena_config import ArenaConfig

config = ArenaConfig(
    enable_knowledge_mound=True,
    enable_km_belief_sync=True,
    enable_coordinated_writes=True,
)
arena = Arena.from_config(env, agents, protocol, config)
```

### Run with Enterprise Features

```python
from aragora.tenancy import TenantContext
from aragora.rbac.decorators import require_permission

async with TenantContext(tenant_id="acme-corp"):
    result = await arena.run()
```

### Self-Improvement Dry Run

```bash
# Preview goal decomposition without executing
python scripts/self_develop.py --goal "Improve test coverage" --dry-run
```

---

## Feature Discovery Tips

### Finding Features by Use Case

| Use Case | Start Here |
|----------|------------|
| Run a multi-agent debate | `aragora/debate/orchestrator.py` |
| Integrate with Slack | `aragora/connectors/chat/slack/` |
| Add authentication | `aragora/auth/` and `aragora/rbac/` |
| Store knowledge | `aragora/knowledge/mound/` |
| Automate workflows | `aragora/workflow/engine.py` |
| Run compliance tests | `aragora/gauntlet/runner.py` |
| Monitor system health | `aragora/observability/` |

### Searching the Codebase

```bash
# Find all handlers
grep -r "class.*Handler" aragora/server/handlers/ --include="*.py"

# Find all adapters
grep -r "class.*Adapter" aragora/ --include="*.py"

# Find all permissions
grep -r "require_permission" aragora/ --include="*.py"

# Find all WebSocket events
grep -r "event_type=" aragora/ --include="*.py"
```

### Key Entry Points

| Purpose | Entry Point |
|---------|-------------|
| Start server | `aragora serve --api-port 8080 --ws-port 8765` |
| Run debate | `from aragora import Arena, Environment` |
| Access knowledge | `from aragora.knowledge.mound import KnowledgeMound` |
| Run workflow | `from aragora.workflow.engine import WorkflowEngine` |
| Run nomic loop | `python scripts/run_nomic_with_stream.py run --cycles 3` |

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [CLAUDE.md](../CLAUDE.md) | Development guide for AI assistants |
| [STATUS.md](STATUS.md) | Release status and changelog |
| [ENTERPRISE_FEATURES.md](ENTERPRISE_FEATURES.md) | Enterprise capability deep-dive |
| [EXTENDED_README.md](EXTENDED_README.md) | Comprehensive technical reference |
| [COMMERCIAL_OVERVIEW.md](COMMERCIAL_OVERVIEW.md) | Commercial positioning |
| [API_REFERENCE.md](./api/API_REFERENCE.md) | REST API documentation |
| [WORKFLOWS.md](./workflow/WORKFLOWS.md) | Workflow engine guide |
| [GAUNTLET.md](./debate/GAUNTLET.md) | Compliance testing guide |
| [PULSE.md](./resilience/PULSE.md) | Trending topics guide |
| [RLM_GUIDE.md](./guides/RLM_GUIDE.md) | Recursive Language Models guide |

---

*Last updated: February 2026*
