---
title: Aragora Documentation Hub
description: Aragora Documentation Hub
---

# Aragora Documentation Hub

Quick navigation for the Aragora platform documentation.

## What Are You Trying To Do?

### Getting Started
| Goal | Document |
|------|----------|
| First time setup | [GETTING_STARTED.md](../getting-started/overview) |
| Quick API test | [API_QUICK_START.md](../guides/api-quickstart) |
| Run a debate | [API_EXAMPLES.md](../api/examples) |

### Build an Integration
| Goal | Document |
|------|----------|
| Python SDK | [SDK_GUIDE.md](../guides/sdk) |
| TypeScript SDK | [SDK_TYPESCRIPT.md](../guides/sdk-typescript) |
| WebSocket streaming | [WEBSOCKET_EVENTS.md](../guides/websocket-events) |
| Full API reference | [API_REFERENCE.md](../api/reference) |

### Deploy to Production
| Goal | Document |
|------|----------|
| Deployment guide | [DEPLOYMENT.md](../deployment/overview) |
| Docker setup | [deployment/DOCKER.md](../deployment/docker) |
| Production readiness | [PRODUCTION_READINESS.md](../operations/production-readiness) |
| CI/CD security | [CI_CD_SECURITY.md](../security/ci-cd) |

### Troubleshoot Issues
| Goal | Document |
|------|----------|
| General troubleshooting | [TROUBLESHOOTING.md](../operations/troubleshooting) |
| Alert runbooks | [ALERT_RUNBOOKS.md](../operations/alert-runbooks) |
| Operations guide | [OPERATIONS.md](../operations/overview) |

---

## Core System Documentation

### Debate Engine
The core multi-agent debate orchestration system.

```
ARCHITECTURE.md          # Overall system design
    └── DEBATE_INTERNALS.md  # How debates work
        └── algorithms/CONSENSUS.md     # Consensus mechanisms
```

### Memory Systems
Multi-tier memory for cross-debate learning.

```
MEMORY.md                # Overview of memory architecture
├── MEMORY_TIERS.md      # Fast/Medium/Slow/Glacial tiers
├── MEMORY_STRATEGY.md   # Consolidation and decay strategies
└── MEMORY_ANALYTICS.md  # Memory usage metrics
```

**Key Concepts (half-life):**
- **Fast tier** (1 hour): Immediate context within a debate
- **Medium tier** (24 hours): Session-level memory
- **Slow tier** (7 days): Cross-session patterns
- **Glacial tier** (30 days): Long-term institutional knowledge

### Knowledge Mound
Centralized knowledge storage with validation and retrieval.

```
KNOWLEDGE_MOUND.md            # Architecture and concepts
└── KNOWLEDGE_MOUND_OPERATIONS.md  # Operational procedures
```

**Key Features:**
- 41 registered adapters (Continuum, Consensus, Evidence, ELO, and 37 more)
- Additional adapter files present but not factory-registered (extraction, nomic_cycle, openclaw, ranking)
- Semantic search with validation feedback
- RBAC-governed access
- Contradiction detection

### Control Plane
Enterprise orchestration layer for multi-agent systems.

```
CONTROL_PLANE.md         # Architecture overview
└── CONTROL_PLANE_GUIDE.md   # Operational guide
```

**Features:** Agent registry, task scheduler, policy governance, health monitoring

---

## Integration Channels

| Channel | Doc | Description |
|---------|-----|-------------|
| Slack | [BOT_INTEGRATIONS.md](../guides/bot-integrations) | Slack bot setup |
| Telegram | [CHAT_CONNECTOR_GUIDE.md](../guides/chat-connector) | Telegram integration |
| WhatsApp | [CHAT_CONNECTOR_GUIDE.md](../guides/chat-connector) | WhatsApp Business |
| Email | [EMAIL_PRIORITIZATION.md](../guides/email-prioritization) | Email processing |
| GitHub | [GITHUB_PR_REVIEW.md](../api/github-pr-review) | PR review automation |

---

## Enterprise Features

| Feature | Doc | Description |
|---------|-----|-------------|
| Authentication | [AUTH_GUIDE.md](../security/authentication) | SSO, MFA, API keys |
| RBAC | [GOVERNANCE.md](../enterprise/governance) | Role-based access control |
| Compliance | [COMPLIANCE.md](../enterprise/compliance) | SOC 2, GDPR |
| Billing | [BILLING.md](../enterprise/billing) | Usage metering and costs |
| Security | [SECURITY.md](../security/overview) | Security architecture |

---

## API Quick Reference

| Endpoint Pattern | Purpose | Doc Section |
|-----------------|---------|-------------|
| `POST /api/v1/debates` | Start debate | [API_EXAMPLES.md#debates](../api/examples) |
| `GET /ws/debate/\{id\}` | Stream events | [WEBSOCKET_EVENTS.md](../guides/websocket-events) |
| `POST /api/v1/documents` | Ingest documents | [DOCUMENTS.md](../guides/documents) |
| `GET /api/v1/knowledge/search` | Search knowledge | [KNOWLEDGE_MOUND.md](../core-concepts/knowledge-mound) |

---

## CLI Reference

```bash
aragora ask "Question"      # Run a debate
aragora serve               # Start server
aragora setup               # Interactive setup wizard
aragora backup create       # Create database backup
aragora backup restore      # Restore from backup
```

See [CLI_REFERENCE.md](../api/cli) for full documentation.

---

## Document Index

For the complete document listing, see [INDEX.md](./documentation-index).

Deprecated documentation is archived in `docs/deprecated/` in the source repository.
