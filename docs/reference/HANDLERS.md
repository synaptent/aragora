# HTTP Handler Reference

This document indexes all HTTP handlers in `aragora/server/handlers/`.

## Overview

The server uses a modular handler architecture organized by domain. Each handler extends `BaseHandler` and registers routes it can handle. Counts vary by deployment; run `python scripts/generate_api_docs.py --format json` to enumerate the full surface area. See the [Experimental Handlers](#experimental-handlers) section for features in development.

## Handler Structure

```
handlers/
├── admin/              # Administration & system management
├── agents/             # Agent management & leaderboards
├── auth/               # Authentication & authorization
├── debates/            # Core debate operations
├── decisions/          # Decision explainability endpoints
├── evolution/          # Prompt evolution & A/B testing
├── features/           # Feature modules (audio, evidence, inbox, etc.)
├── inbox/              # Inbox command + shared inbox workflows
├── knowledge/          # Knowledge analytics + sharing
├── knowledge_base/     # Knowledge Mound API surface
├── memory/             # Memory & learning systems
├── social/             # Social features & integrations
├── verification/       # Formal verification
├── voice/              # Voice endpoints
├── control_plane.py    # Control plane orchestration
├── decision.py         # Unified decision router
├── deliberations.py    # Vetted decisionmaking dashboard endpoints (deliberations API)
├── gauntlet.py         # Gauntlet stress-test API
├── webhook_management.py # Outbound webhook management
├── workflows.py        # Workflow execution endpoints
└── webhooks/           # Webhook integrations + compatibility exports
```

---

## Admin Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `admin/admin.py` | `/api/admin/*` | System-wide administration, user/org listing |
| `admin/billing.py` | `/api/billing/*` | Subscription & payment management |
| `admin/dashboard.py` | `/api/dashboard/*` | Consolidated debate metrics |
| `admin/health.py` | `/health`, `/ready` | Health & readiness probes |
| `admin/system.py` | `/api/system/*` | System config & maintenance |
| `usage_metering.py` | `/api/v1/billing/usage/*`, `/api/v1/quotas` | Usage metering and quota status |

### Key Endpoints

```
GET  /health              - Health check
GET  /ready               - Readiness check
GET  /api/admin/users     - List users (admin only)
GET  /api/admin/stats     - System statistics
GET  /api/dashboard       - Aggregated metrics

# Usage Metering (Enterprise)
GET  /api/v1/billing/usage         - Current billing period usage summary
GET  /api/v1/billing/usage/summary - Alias for usage summary
GET  /api/v1/billing/usage/breakdown - Detailed usage by model, provider, day
GET  /api/v1/billing/limits        - Current tier limits and utilization
GET  /api/v1/billing/usage/export  - Export usage as CSV or JSON
GET  /api/v1/quotas                - Quota status for all resources
```

---

## Agent Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `agents/agents.py` | `/api/agents/*` | Agent registration, status, configuration |
| `agents/calibration.py` | `/api/calibration/*` | Calibration curves & prediction accuracy |
| `agents/leaderboard.py` | `/api/leaderboard/*` | ELO rankings & tournament results |
| `agents/probes.py` | `/api/probes/*` | Capability probing & adversarial testing |

### Key Endpoints

```
GET  /api/agents                    - List agents
GET  /api/agents/:name              - Get agent details
GET  /api/leaderboard               - ELO rankings
GET  /api/calibration/:agent        - Agent calibration data
POST /api/probes/run                - Run capability probes
```

---

## Auth Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `auth/handler.py` | `/api/auth/*` | Login, logout, session management |
| `oauth.py` | `/api/oauth/*` | OAuth2 provider integration |
| `auth/signup_handlers.py` | `/api/v1/auth/*` | Self-service signup, org setup, invitations |
| `auth/sso_handlers.py` | `/api/v1/auth/sso/*` | OIDC-based SSO endpoints |
| `sso.py` | `/auth/sso/*` | SAML/legacy SSO endpoints |

### Key Endpoints

```
POST /api/auth/login      - User login
POST /api/auth/logout     - User logout
GET  /api/auth/me         - Current user info
GET  /api/oauth/:provider - OAuth initiation
POST /api/oauth/callback  - OAuth callback
POST /api/v1/auth/signup  - Self-service signup
GET  /api/v1/auth/sso/login - SSO login (OIDC)
```

---

## Control Plane & Decisioning Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `control_plane.py` | `/api/control-plane/*`, `/api/v1/control-plane/*` | Agent registry, queues, health, and task orchestration |
| `decision.py` | `/api/v1/decisions/*` | Unified decision router across debate/workflow/gauntlet |
| `decisions/explain.py` | `/api/v1/decisions/:id/explain` | Decision explainability payloads |
| `deliberations.py` | `/api/v1/deliberations/*` | Vetted decisionmaking dashboard and event stream |

### Key Endpoints

```
POST /api/v1/decisions              - Submit a decision request
GET  /api/v1/decisions/:id          - Get decision status/result
POST /api/control-plane/deliberations - Run or queue a vetted decisionmaking session
GET  /api/v1/deliberations/active   - List active deliberations
```

---

## Debate Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `debates/handler.py` | `/api/debates/*` | Core debate CRUD operations |
| `debates/batch.py` | `/api/debates/batch/*` | Batch debate submission |
| `debates/fork.py` | `/api/debates/:id/fork` | Counterfactual forking |
| `debates/graph_debates.py` | `/api/graph-debates/*` | Branching graph debates |
| `debates/matrix_debates.py` | `/api/matrix-debates/*` | Multi-scenario matrix debates |

### Key Endpoints

```
POST /api/debates               - Create debate
GET  /api/debates/:id           - Get debate status
GET  /api/debates/:id/result    - Get debate result
POST /api/debates/:id/vote      - Submit vote
POST /api/debates/:id/fork      - Fork debate
POST /api/graph-debates         - Create graph debate
POST /api/matrix-debates        - Create matrix debate
```

---

## Feature Handlers

Representative feature handlers are listed below. The features namespace
evolves quickly; see [API_ENDPOINTS.md](../api/API_ENDPOINTS.md) for the full
auto-generated list.

| Module | Routes | Description |
|--------|--------|-------------|
| `features/audio.py` | `/audio/*`, `/api/v1/podcast/*` | Audio file serving + podcast feed |
| `features/broadcast.py` | `/api/v1/debates/*/broadcast*` | Live debate broadcasting |
| `features/connectors.py` | `/api/v1/connectors/*` | Connector registry + sync jobs |
| `features/documents.py` | `/api/v1/documents/*` | Document upload + metadata |
| `features/document_query.py` | `/api/v1/documents/*` | Document Q&A, summarize, compare, extract |
| `features/evidence.py` | `/api/v1/evidence/*` | Evidence collection & search |
| `features/features.py` | `/api/v1/features/*` | Feature flags & toggles |
| `features/gmail_ingest.py` | `/api/v1/gmail/*` | Gmail ingestion, sync, search |
| `features/gmail_query.py` | `/api/v1/gmail/query` | Gmail query API |
| `features/integrations.py` | `/api/v1/integrations/*` | Integration configuration + status |
| `features/unified_inbox.py` | `/api/v1/inbox/*` | Unified inbox accounts + triage |
| `features/email_webhooks.py` | `/api/v1/webhooks/*` | Gmail/Outlook webhook subscriptions |
| `features/routing_rules.py` | `/api/v1/routing-rules/*` | Routing rules management |
| `features/smart_upload.py` | `/api/v1/upload/*` | Smart upload + file classification |
| `features/cloud_storage.py` | `/api/v1/cloud/*` | Cloud storage provider integrations |
| `features/codebase_audit.py` | `/api/v1/codebase/*` | Codebase scans + findings |
| `features/reconciliation.py` | `/api/v1/reconciliation/*` | Reconciliation runs + reports |
| `features/marketplace.py` | `/api/v1/marketplace/*` | Template marketplace API |
| `features/rlm.py` | `/api/v1/rlm/*` | RLM query/compress endpoints |
| `features/advertising.py` | `/api/v1/advertising/*` | Advertising platform APIs |
| `features/analytics_platforms.py` | `/api/v1/analytics/*` | Analytics/BI platform APIs |
| `features/cross_platform_analytics.py` | `/api/v1/analytics/cross-platform/*` | Cross-platform analytics aggregation |
| `features/crm.py` | `/api/v1/crm/*` | CRM platform APIs |
| `features/ecommerce.py` | `/api/v1/ecommerce/*` | Ecommerce platform APIs |
| `features/support.py` | `/api/v1/support/*` | Support/helpdesk platform APIs |
| `features/legal.py` | `/api/v1/legal/*` | Legal platform integrations |
| `features/devops.py` | `/api/v1/devops/*` | DevOps integrations |
| `features/plugins.py` | `/api/v1/plugins/*` | Plugin management |
| `features/pulse.py` | `/api/v1/pulse/*` | Trending topics |

### Key Endpoints

```
GET  /api/v1/features           - List feature flags
POST /api/v1/evidence/collect   - Collect evidence
GET  /api/v1/pulse/trending     - Get trending topics
POST /api/v1/documents/upload   - Upload a document
POST /api/v1/debates/*/broadcast - Start live broadcast
```

---

## Inbox & Email Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `email.py` | `/api/v1/email/*` | Inbox prioritization, categorization, feedback |
| `features/gmail_ingest.py` | `/api/v1/gmail/*` | Gmail OAuth, sync, search |
| `features/gmail_query.py` | `/api/v1/gmail/query` | Gmail query API |
| `features/unified_inbox.py` | `/api/v1/inbox/*` | Unified inbox accounts + triage |
| `shared_inbox.py` | `/api/v1/inbox/shared*` | Shared inbox routing + rules |
| `inbox/*` | `/api/v1/inbox/*` | Action items + team inbox workflows |

---

## Workflow & Template Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `workflows.py` | `/api/v1/workflows*` | Workflow execution + approvals |
| `workflow_templates.py` | `/api/v1/workflow/templates*` | Workflow templates CRUD + run |
| `template_marketplace.py` | `/api/v1/marketplace/*` | Template marketplace + featured sets |

---

## Gauntlet & Audit Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `gauntlet.py` | `/api/v1/gauntlet/*` | Adversarial stress tests + receipts |
| `features/audit_sessions.py` | `/api/v1/audit/sessions*` | Audit session lifecycle + reports |
| `audit_trail.py` | `/api/v1/audit-trails*`, `/api/v1/receipts*` | Audit trails + decision receipts |
| `audit_export.py` | `/api/v1/audit/*` | Export audit logs + verify integrity |

---

## Memory Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `memory/memory.py` | `/api/v1/memory/*` | Memory tier management |
| `memory/insights.py` | `/api/v1/insights/*` | Extracted insights |
| `memory/learning.py` | `/api/v1/learning/*` | Continuous learning |
| `memory/memory_analytics.py` | `/api/v1/memory/analytics*` | Memory usage analytics |

### Key Endpoints

```
GET  /api/v1/memory/tiers       - Memory tier configuration
POST /api/v1/memory/search      - Search memory
GET  /api/v1/insights/recent    - List insights
GET  /api/v1/memory/analytics   - Memory analytics snapshots
```

---

## Social Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `social/collaboration.py` | `/api/collaboration/*` | Team collaboration sessions (legacy unversioned) |
| `social/notifications.py` | `/api/v1/notifications/*` | Email + Telegram notifications |
| `social/relationship.py` | `/api/v1/relationships*`, `/api/v1/relationship/*` | Agent relationships |
| `social/sharing.py` | `/api/v1/debates/*/share`, `/api/v1/shared/*` | Debate sharing |
| `social/slack.py` | `/api/v1/integrations/slack/*` | Slack commands/events |
| `social/telegram.py` | `/api/v1/integrations/telegram/*` | Telegram webhooks |
| `social/whatsapp.py` | `/api/v1/integrations/whatsapp/*` | WhatsApp webhooks |
| `social/social_media.py` | `/api/v1/debates/*/publish/*`, `/api/v1/youtube/*` | Social publishing |

### Key Endpoints

```
POST /api/v1/debates/:id/share          - Share debate
GET  /api/v1/notifications/status      - Notification status
GET  /api/v1/relationship/:a/:b         - Agent relationship
POST /api/v1/integrations/slack/events - Slack events webhook
```

---

## Verification Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `verification/verification.py` | `/api/v1/verification/*` | Verification status + formal checks |
| `verification/formal_verification.py` | `/api/v1/verify/*` | Formal proofs (Z3/Lean) |

### Key Endpoints

```
POST /api/v1/verify/claim       - Verify a claim
GET  /api/v1/verify/status      - Verification status
POST /api/formal/prove          - Generate formal proof
```

---

## Other Handlers

| Module | Routes | Description |
|--------|--------|-------------|
| `analytics.py` | `/api/analytics/*` | Usage analytics |
| `accounting.py` | `/api/accounting/*` | QuickBooks + Gusto accounting |
| `ap_automation.py` | `/api/v1/accounting/ap/*` | Accounts payable automation |
| `ar_automation.py` | `/api/v1/accounting/ar/*` | Accounts receivable automation |
| `audit_export.py` | `/api/audit/*` | Audit log export |
| `auditing.py` | `/api/auditing/*` | Security analysis |
| `belief.py` | `/api/belief/*` | Belief network analysis |
| `breakpoints.py` | `/api/breakpoints/*` | Human-in-the-loop |
| `checkpoints.py` | `/api/checkpoints/*` | Debate checkpoints |
| `consensus.py` | `/api/consensus/*` | Consensus memory |
| `critique.py` | `/api/critique/*` | Critique patterns |
| `code_review.py` | `/api/v1/code-review/*` | Multi-agent code review |
| `dashboard.py` | `/api/v1/dashboard/*` | Main dashboard API |
| `docs.py` | `/api/docs/*` | API documentation |
| `debates/intervention.py` | `/api/debates/*/intervention/*` | Mid‑debate interventions |
| `gallery.py` | `/api/gallery/*` | Debate gallery |
| `gauntlet.py` | `/api/gauntlet/*` | Adversarial testing |
| `genesis.py` | `/api/genesis/*` | Agent breeding |
| `introspection.py` | `/api/introspection/*` | Agent introspection |
| `laboratory.py` | `/api/laboratory/*` | Persona experiments |
| `metrics.py` | `/api/metrics/*` | Prometheus metrics |
| `moments.py` | `/api/moments/*` | Significant moments |
| `nomic.py` | `/api/nomic/*` | Nomic loop control |
| `organizations.py` | `/api/organizations/*` | Organization management |
| `persona.py` | `/api/persona/*` | Persona management |
| `privacy.py` | `/api/privacy/*` | Data privacy |
| `replays.py` | `/api/replays/*` | Debate replays |
| `reviews.py` | `/api/reviews/*` | Debate reviews |
| `tournaments.py` | `/api/tournaments/*` | Tournament management |
| `training.py` | `/api/training/*` | Training data export |
| `webhook_management.py` | `/api/webhooks/*` | Webhook management |
| `connectors.py` | `/api/connectors/*` | Data connector management |
| `control_plane.py` | `/api/control-plane/*` | Enterprise control plane |
| `routing.py` | `/api/routing/*` | Agent routing & team selection |
| `selection.py` | `/api/selection/*` | Selection plugin API |
| `evaluation.py` | `/api/evaluation/*` | LLM-as-Judge evaluation |
| `knowledge.py` | `/api/knowledge/*` | Knowledge base API |
| `ml.py` | `/api/ml/*` | ML capabilities API |
| `policy.py` | `/api/policy/*` | Policy compliance |
| `queue.py` | `/api/queue/*` | Job queue management |
| `repository.py` | `/api/repository/*` | Repository indexing |
| `uncertainty.py` | `/api/uncertainty/*` | Uncertainty estimation |
| `verticals.py` | `/api/verticals/*` | Vertical specialists |
| `workspace.py` | `/api/workspace/*` | Enterprise workspace |
| `workflows.py` | `/api/workflows/*` | Workflow engine API |

---

## Experimental Handlers

These handlers are functional but APIs may change. Check `aragora/server/handlers/__init__.py` for current stability levels.

| Handler | Phase | Description |
|---------|-------|-------------|
| `AnalyticsDashboardHandler` | EXPERIMENTAL | Enterprise analytics dashboard |
| `RoutingHandler` | Phase A | Agent routing and team selection |
| `SelectionHandler` | Phase A | Selection plugin API |
| `ControlPlaneHandler` | Phase 0 | Enterprise control plane |
| `DocumentQueryHandler` | Phase A | Natural language document querying |
| `EvaluationHandler` | EXPERIMENTAL | LLM-as-Judge evaluation |
| `EvidenceEnrichmentHandler` | Phase A | Evidence enrichment for findings |
| `FindingWorkflowHandler` | Phase A | Finding workflow management |
| `FolderUploadHandler` | Phase A | Folder upload support |
| `KnowledgeHandler` | EXPERIMENTAL | Knowledge base API |
| `KnowledgeMoundHandler` | Phase A1 | Knowledge Mound system |
| `MLHandler` | EXPERIMENTAL | ML capabilities API |
| `PolicyHandler` | Phase 2 | Policy and compliance management |
| `QueueHandler` | Phase A1 | Job queue management |
| `RepositoryHandler` | Phase A3 | Repository indexing |
| `SchedulerHandler` | Phase A | Audit scheduling |
| `SlackHandler` | EXPERIMENTAL | Slack integration |
| `UncertaintyHandler` | Phase A1 | Uncertainty estimation |
| `VerticalsHandler` | Phase A1 | Vertical specialist API |
| `WorkflowHandler` | Phase 2 | Workflow engine API |
| `WorkspaceHandler` | Phase 2 | Enterprise workspace/privacy |

### Stability Levels

- **STABLE**: Production-ready, backwards compatible
- **PREVIEW**: Feature complete, API may change slightly
- **EXPERIMENTAL**: In development, expect breaking changes
- **Phase 0/A/A1/A3/2**: Enterprise feature rollout phases

---

## Utility Modules

| Module | Description |
|--------|-------------|
| `base.py` | Base handler class with common utilities |
| `exceptions.py` | Handler exception types |
| `interface.py` | Handler Protocol definitions and contracts |
| `types.py` | Type definitions |
| `utilities.py` | Shared handler utility functions |
| `utils/database.py` | Database access helpers |
| `utils/decorators.py` | Handler decorators |
| `utils/params.py` | Query parameter parsing |
| `utils/rate_limit.py` | Rate limiting utilities |
| `utils/responses.py` | Response formatting |
| `utils/routing.py` | Route matching utilities |
| `utils/safe_data.py` | Data sanitization |

---

## Creating New Handlers

```python
from aragora.server.handlers.base import (
    BaseHandler,
    json_response,
    error_response,
)

class MyHandler(BaseHandler):
    """My custom handler."""

    routes = [
        "GET /api/my-feature",
        "POST /api/my-feature",
    ]

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/my-feature")

    def handle(self, path, query_params, handler):
        return json_response({"status": "ok"})

    def handle_post(self, path, query_params, handler):
        body, err = self.read_json_body_validated(handler)
        if err:
            return err
        return json_response({"received": body})
```

Register in `handlers/__init__.py`:

```python
from .my_handler import MyHandler

ALL_HANDLERS = [
    # ... existing handlers ...
    MyHandler,
]
```

---

## See Also

- [API Endpoints](../api/API_ENDPOINTS.md) - Full endpoint reference
- [API Rate Limits](../api/API_RATE_LIMITS.md) - Rate limiting configuration
- [WebSocket Events](../streaming/WEBSOCKET_EVENTS.md) - Real-time event streaming
