# Aragora Documentation

Welcome to Aragora's documentation. The `docs/` directory is the canonical
source. The published site in `docs-site/` is synced from these files via
`docs-site/scripts/sync-docs.js`.

This page is the single documentation index. It links every page kept at the
top of `docs/` ([Top-Level Pages](#top-level-pages)) and every curated
subdirectory ([Documentation Map](#documentation-map)). Two sub-indexes cover
narrower needs, and every page they link is also linked from this page:

- [Start Here](./START_HERE.md): choose a package (`aragora-debate`, the
  Python or TypeScript SDK, or the full platform) and follow its short
  quickstart.
- [Documentation Index](./INDEX.md): a short flat list of the most-used pages.
  The docs site publishes it as its documentation index page.

**Aragora is an auditable execution control plane for AI-assisted decisions: multi-model review in, a verifiable Decision Receipt out.**
It uses multi-model review, receipts, provenance, and truthful gates so
consequential decisions can be inspected instead of merely trusted.

## What Are You Trying To Do?

The core loop — run a debate, get a receipt, verify it independently, then
wire it into CI — comes first below; everything else follows.

| Goal | Document |
|------|----------|
| **Run your first debate in under a minute** | [Quickstart](./quickstart.md) |
| Understand the receipt model (native record vs. the portable ODR) | [Receipt Lineage Reconciliation](./specs/RECEIPT_LINEAGE_RECONCILIATION.md) |
| Verify a receipt independently, no Aragora install required (`aragora-verify` exit codes: `0 verified / 1 failed / 2 usage / 3 signatures-present-unchecked`) | [Independent Verifier Guide](./specs/INDEPENDENT_VERIFIER_GUIDE.md) |
| Add multi-model CI review + receipts to your pull requests | [GitHub Action Setup](./guides/GITHUB_ACTION_SETUP.md) |
| Choose a package and install path (`aragora-debate`, SDKs, or the full platform) | [Start Here](./START_HERE.md) |
| See ten real-world decisions Aragora is built for | [Use Cases](./guides/USE_CASES.md) |
| Review or audit the project quickly | [Cold Reviewer Guide](./guides/COLD_REVIEWER_GUIDE.md) |
| Understand the supported API contract | [Supported API Surface](./api/SUPPORTED_SURFACE.md) |
| See 20 runnable code examples | [API Cookbook](./guides/API_COOKBOOK.md) |
| Build a Python integration | [SDK Guide](./SDK_GUIDE.md) |
| Build a TypeScript integration | [TypeScript SDK](./guides/SDK_TYPESCRIPT.md) |
| Use the REST API | [API Reference](./api/API_REFERENCE.md) |
| Use the command line | [CLI Reference](./CLI_REFERENCE.md) |
| Stream events via WebSocket | [WebSocket Events](./streaming/WEBSOCKET_EVENTS.md) |
| Deploy to production | [Deployment Guide](./DEPLOYMENT.md) |
| Set up Slack/Telegram/WhatsApp | [Chat Connector Guide](./guides/CHAT_CONNECTOR_GUIDE.md) |
| Troubleshoot an issue | [Troubleshooting](./guides/TROUBLESHOOTING.md) |
| Understand the architecture | [Architecture](./architecture/ARCHITECTURE.md) |

## Getting Started

| Document | Description |
|----------|-------------|
| [quickstart](./quickstart.md) | Canonical quickstart: your first debate in under a minute. The older [Getting Started](./guides/GETTING_STARTED.md), [Docker Quickstart](./guides/QUICKSTART_DOCKER.md) and [Developer Quickstart](./guides/DEVELOPER_QUICKSTART.md) pages redirect here |
| [START_HERE](./START_HERE.md) | Sub-index: choose a package and follow its path |
| [ZERO_CONFIG](./getting-started/ZERO_CONFIG.md) | What works after `pip install` with no keys or services |
| [INSTALL_MATRIX](./reference/INSTALL_MATRIX.md) | Which install command to run for each distribution and audience |
| [aragora-debate](../aragora-debate/README.md) | Standalone debate engine package (zero dependencies, works offline) |
| [Quickstart examples](../examples/quickstart/) | Runnable scripts: simple debate, signed receipt, evidence quality |
| [python-quickstart](./guides/python-quickstart.md) | Python SDK quickstart against a running server |
| [typescript-quickstart](./guides/typescript-quickstart.md) | TypeScript SDK quickstart |
| [SELF_HOSTED_QUICKSTART](./guides/SELF_HOSTED_QUICKSTART.md) | Self-host the full platform |
| [LOCAL_DEVELOPMENT](./guides/LOCAL_DEVELOPMENT.md) | Local development: virtual environment, API keys, server, tests and linting |
| [LOCAL_DEVELOPMENT (backend + frontend)](./getting-started/LOCAL_DEVELOPMENT.md) | Run the backend and frontend together on your machine |
| [FIRST_CONTRIBUTION](./guides/FIRST_CONTRIBUTION.md) | Suggested first issues and opening your first PR |

## Core Concepts

| Document | Description |
|----------|-------------|
| [ARCHITECTURE](./architecture/ARCHITECTURE.md) | System architecture overview |
| [IMPORT_LAYERS](./architecture/IMPORT_LAYERS.md) | Import layer contract: membership, TYPE_CHECKING policy, tranche procedure, Partition A handover |
| [FEATURE_DISCOVERY](./status/FEATURE_DISCOVERY.md) | Current feature inventory and file map |
| [FEATURE_GAP_LIST](./FEATURE_GAP_LIST.md) | Planned, partial, and hardening work |
| [MODES_GUIDE](./guides/MODES_GUIDE.md) | Debate modes (standard, gauntlet, genesis) |
| [DEBATE_INTERNALS](./debate/DEBATE_INTERNALS.md) | Debate engine internals (Arena, phases, consensus) |
| [REASONING](./workflow/REASONING.md) | Belief networks, provenance, and claims |
| [WORKFLOW_ENGINE](./workflow/WORKFLOW_ENGINE.md) | DAG-based workflow execution |
| [RESILIENCE](./resilience/RESILIENCE.md) | Circuit breaker and fault tolerance |
| [CONTROL_PLANE](./reference/CONTROL_PLANE.md) | Control plane architecture |
| [CONTROL_PLANE_GUIDE](./guides/CONTROL_PLANE_GUIDE.md) | Control plane operations guide |
| [MEMORY](./knowledge/MEMORY.md) | Memory systems overview |
| [KNOWLEDGE_MOUND](./knowledge/KNOWLEDGE_MOUND.md) | Centralized knowledge storage with 42 registered adapter specs |
| [DOCUMENTS](./reference/DOCUMENTS.md) | Document ingestion and parsing |

## Current Status & Planning

| Document | Description |
|----------|-------------|
| [STATUS](./status/STATUS.md) | Current shipped state and recent delivery summary |
| [NEXT_STEPS_CANONICAL](./status/NEXT_STEPS_CANONICAL.md) | Single source of truth for execution priorities |
| [ACTIVE_EXECUTION_ISSUES](./status/ACTIVE_EXECUTION_ISSUES.md) | Live GitHub issue map for the execution program |
| [ARAGORA_IDEA_TO_EXECUTION_STRATEGY](./plans/ARAGORA_IDEA_TO_EXECUTION_STRATEGY.md) | Current strategy narrative for the unified idea-to-execution product |
| [EXECUTION_NEXT_6_WEEKS](./status/EXECUTION_NEXT_6_WEEKS_2026-03-05.md) | Active short-horizon plan |
| [DOCUMENTATION_HYGIENE_AND_GAP_REGISTER](./status/DOCUMENTATION_HYGIENE_AND_GAP_REGISTER.md) | Running roadmap, drift, and feature-gap register |
| [ROADMAP](../ROADMAP.md) | Project roadmap |

### Memory Tiers

| Tier | Half-Life | Purpose |
|------|-----------|---------|
| Fast | 1 hour | Immediate context within a debate |
| Medium | 24 hours | Session-level memory |
| Slow | 7 days | Cross-session patterns |
| Glacial | 30 days | Long-term institutional knowledge |

See [MEMORY_STRATEGY](./knowledge/MEMORY_STRATEGY.md) for details.

## Using Aragora

### Receipts & Verification

| Document | Description |
|----------|-------------|
| [OPEN_DECISION_RECEIPT](./specs/OPEN_DECISION_RECEIPT.md) | Open Decision Receipt (ODR) content profile |
| [RECEIPT_LINEAGE_RECONCILIATION](./specs/RECEIPT_LINEAGE_RECONCILIATION.md) | Native receipt record vs. the portable ODR |
| [INDEPENDENT_VERIFIER_GUIDE](./specs/INDEPENDENT_VERIFIER_GUIDE.md) | Verify a receipt with `aragora-verify`, no Aragora install required |
| [RECEIPT_CONTRACT](./RECEIPT_CONTRACT.md) | Receipt contract for new integrations |

### Debates & Gauntlet

| Document | Description |
|----------|-------------|
| [GAUNTLET](./debate/GAUNTLET.md) | Adversarial stress testing (primary) |
| [PROBE_STRATEGIES](./debate/PROBE_STRATEGIES.md) | Probe attack strategies |
| [GENESIS](./workflow/GENESIS.md) | Agent evolution and genesis |
| [GRAPH_DEBATES](./debate/GRAPH_DEBATES.md) | Graph debate mode (experimental) |
| [MATRIX_DEBATES](./debate/MATRIX_DEBATES.md) | Matrix debate mode (experimental) |

### Agents & Memory

| Document | Description |
|----------|-------------|
| [AGENT_SELECTION](./debate/AGENT_SELECTION.md) | Agent selection algorithms |
| [AGENTS](./debate/AGENTS.md) | Agent type catalog and defaults |
| [AGENT_DEVELOPMENT](./debate/AGENT_DEVELOPMENT.md) | Creating custom agents |
| [CUSTOM_AGENTS](./guides/CUSTOM_AGENTS.md) | Custom agent configuration |
| [VIBEPROXY](./guides/VIBEPROXY.md) | Local VibeProxy transport and Fable advisory routing |
| [MEMORY_STRATEGY](./knowledge/MEMORY_STRATEGY.md) | Memory tier architecture |
| [MEMORY_ANALYTICS](./knowledge/MEMORY_ANALYTICS.md) | Memory system analytics |

### Inbox & Channels

| Document | Description |
|----------|-------------|
| [INBOX_GUIDE](./guides/INBOX_GUIDE.md) | Unified inbox setup and triage workflows |
| [EMAIL_PRIORITIZATION](./integrations/EMAIL_PRIORITIZATION.md) | Priority scoring and tiers |
| [SHARED_INBOX](./guides/SHARED_INBOX.md) | Shared inbox routing and team workflows |
| [CHANNELS](./integrations/CHANNELS.md) | Supported channels and delivery |

### Integrations

| Document | Description |
|----------|-------------|
| [BOT_INTEGRATIONS](./integrations/BOT_INTEGRATIONS.md) | Slack bot setup |
| [CHAT_CONNECTOR_GUIDE](./guides/CHAT_CONNECTOR_GUIDE.md) | Telegram and WhatsApp |
| [MCP_SETUP_GUIDE](./integrations/MCP_SETUP_GUIDE.md) | **Start here** — MCP setup, 80-tool catalog, workflows |
| [MCP_INTEGRATION](./integrations/MCP_INTEGRATION.md) | Model Context Protocol tool parameters |
| [MCP_ADVANCED](./integrations/MCP_ADVANCED.md) | Advanced MCP patterns |
| [INTEGRATIONS](./integrations/INTEGRATIONS.md) | Third-party integrations |
| [GITHUB_PR_REVIEW](./integrations/GITHUB_PR_REVIEW.md) | PR review automation |
| [TINKER_INTEGRATION](./integrations/TINKER_INTEGRATION.md) | Tinker framework integration |

### Costs & Billing

| Document | Description |
|----------|-------------|
| [BILLING](./reference/BILLING.md) | Billing and subscriptions |
| [COST_VISIBILITY](./observability/COST_VISIBILITY.md) | Cost tracking and budgets |

## API & SDK

| Document | Description |
|----------|-------------|
| [API_REFERENCE](./api/API_REFERENCE.md) | Complete API documentation |
| [API_ENDPOINTS](./api/API_ENDPOINTS.md) | HTTP endpoint reference |
| [API_EXAMPLES](./api/API_EXAMPLES.md) | API usage examples |
| [API_COOKBOOK](./guides/API_COOKBOOK.md) | 20 common patterns with runnable code |
| [API_VERSIONING](./api/API_VERSIONING.md) | API version policy |
| [WEBHOOKS](./api/WEBHOOKS.md) | Webhook API |
| [BREAKING_CHANGES](./BREAKING_CHANGES.md) | Breaking changes and migration |
| [MIGRATION_V1_TO_V2](./status/MIGRATION_V1_TO_V2.md) | API v1 to v2 migration guide |
| [WEBSOCKET_EVENTS](./streaming/WEBSOCKET_EVENTS.md) | WebSocket event reference |
| [SDK_TYPESCRIPT](./guides/SDK_TYPESCRIPT.md) | TypeScript SDK guide |
| [SDK_CONSOLIDATION](./guides/SDK_CONSOLIDATION.md) | TypeScript SDK migration (v2 to v3) |
| [SDK_GUIDE](./SDK_GUIDE.md) | Python SDK guide |
| [SDK_QUICKSTART](./guides/SDK_QUICKSTART.md) | Install to first debate in under 2 minutes, no server or API keys |
| [PYTHON_SDK_MIGRATION](./guides/PYTHON_SDK_MIGRATION.md) | Canonical Python SDK migration (`aragora-client` -> `aragora-sdk`) |
| [LIBRARY_USAGE](./reference/LIBRARY_USAGE.md) | Using Aragora as a library |

### API Quick Reference

| Endpoint Pattern | Purpose |
|-----------------|---------|
| `POST /api/debates` | Start a debate |
| `GET /api/debates/{id}` | Get debate result |
| `GET /ws/debates/{id}` | Stream events via WebSocket |
| `POST /api/v2/knowledge/search` | Search knowledge |
| `GET /api/v2/agents/rankings` | Agent rankings |
| `GET /health` | Health check |

### CLI Quick Reference

```bash
aragora ask "Question"          # Run a debate
aragora gauntlet "Claim"        # Stress-test a claim
aragora review path/to/code     # Review code
aragora serve --api-port 8080 --ws-port 8765  # Start full API + WS server
aragora setup                   # Interactive setup wizard
aragora doctor                  # Health check
aragora backup create           # Create backup
aragora backup restore          # Restore from backup
aragora skills scan file.py     # Scan for malicious patterns
```

See [CLI_REFERENCE](./CLI_REFERENCE.md) for full documentation and the
[generated flag catalog](./reference/CLI_REFERENCE.md) for every option.

## Operations & Deployment

| Document | Description |
|----------|-------------|
| [DEPLOYMENT](./DEPLOYMENT.md) | Deployment guide |
| [PRODUCTION_DEPLOYMENT](./deployment/PRODUCTION_DEPLOYMENT.md) | Production deployment guide |
| [OPERATIONS](./operations/OPERATIONS.md) | Operations runbook |
| [SELF_HOSTING](./operations/SELF_HOSTING.md) | Run Aragora on your own infrastructure |
| [GA_CHECKLIST](./GA_CHECKLIST.md) | Self-hosted GA readiness checklist |
| [RUNBOOK](./deployment/RUNBOOK.md) | Incident response procedures |
| [INCIDENT_RESPONSE](./deployment/INCIDENT_RESPONSE.md) | Incident response playbooks |
| [PRODUCTION_READINESS](./deployment/PRODUCTION_READINESS.md) | Production readiness checklist |
| [OBSERVABILITY](./observability/OBSERVABILITY.md) | Monitoring and telemetry |
| [SCALING](./deployment/SCALING.md) | Scaling guide |
| [RATE_LIMITING](./api/RATE_LIMITING.md) | Rate limit configuration |
| [QUEUE](./resilience/QUEUE.md) | Debate queue management |
| [ASYNC_GATEWAY](./deployment/ASYNC_GATEWAY.md) | Async gateway setup |

## Security & Compliance

| Document | Description |
|----------|-------------|
| [SECURITY](./enterprise/SECURITY.md) | Security overview |
| [SECURITY_DEPLOYMENT](./deployment/SECURITY_DEPLOYMENT.md) | Secure deployment practices |
| [SECRETS_MANAGEMENT](./enterprise/SECRETS_MANAGEMENT.md) | Managing API keys and secrets |
| [SSO_SETUP](./enterprise/SSO_SETUP.md) | SSO configuration |
| [AUTH_GUIDE](./enterprise/AUTH_GUIDE.md) | Authentication (OIDC, SAML, MFA) |
| [RBAC_MATRIX](./enterprise/RBAC_MATRIX.md) | RBAC permission matrix |
| [ENTERPRISE_FEATURES (enterprise)](./enterprise/ENTERPRISE_FEATURES.md) | SSO, RBAC, multi-tenancy and compliance capabilities |
| [GOVERNANCE](./enterprise/GOVERNANCE.md) | Decision governance |
| [COMPLIANCE](./enterprise/COMPLIANCE.md) | SOC 2, GDPR support |
| [COMPLIANCE_PRESETS](./enterprise/COMPLIANCE_PRESETS.md) | Built-in audit presets |
| [DATA_CLASSIFICATION](./enterprise/DATA_CLASSIFICATION.md) | Data classification policy |

## Configuration

| Document | Description |
|----------|-------------|
| [ZERO_CONFIG](./getting-started/ZERO_CONFIG.md) | What works after `pip install` with no keys or services |
| [ENVIRONMENT](./reference/ENVIRONMENT.md) | Environment variables reference |
| [DATABASE](./reference/DATABASE.md) | Database architecture |
| [CLI_REFERENCE](./CLI_REFERENCE.md) | CLI command reference ([generated flag catalog](./reference/CLI_REFERENCE.md)) |

## Development

| Document | Description |
|----------|-------------|
| [CONTRIBUTING](../CONTRIBUTING.md) | Contribution guide |
| [CLAUDE.md](../CLAUDE.md) | Codebase map and conventions for coding agents |
| [CONDUCTOR_WORKFLOW](./guides/CONDUCTOR_WORKFLOW.md) | Aragora Conductor workflow for agent-driven development |
| [WORKER_PROMPT_PACK](./guides/WORKER_PROMPT_PACK.md) | Prompt pack for Aragora worker agents |
| [DEV_SWARM_COORDINATION](./architecture/DEV_SWARM_COORDINATION.md) | Dev swarm coordination: leases, receipts and integration |
| [Conductor control plane spec](./plans/2026-03-07-conductor-control-plane.md) | Conductor control plane implementation spec |
| [FRONTEND_DEVELOPMENT](./debate/FRONTEND_DEVELOPMENT.md) | Frontend contribution guide |
| [FRONTEND_ROUTES](./guides/FRONTEND_ROUTES.md) | Frontend route and feature map |
| [HANDLER_DEVELOPMENT](./debate/HANDLER_DEVELOPMENT.md) | Writing new server handlers |
| [TESTING](./testing/TESTING.md) | Test suite documentation |
| [CODING_ASSISTANCE](./architecture/CODING_ASSISTANCE.md) | Code review and generation |
| [STRANGER_TEST](./guides/STRANGER_TEST.md) | Copy-paste kit for cold-eyes feedback from a new developer |
| [BREAKING_CHANGES](./reference/BREAKING_CHANGES.md) | Breaking changes by version |
| [DEPRECATION_POLICY](./reference/DEPRECATION_POLICY.md) | Deprecation and migration policy |
| [ERROR_CODES](./reference/ERROR_CODES.md) | Error code reference |
| [Reference Index](./reference/INDEX.md) | Index of the `reference/` directory |

## Features

| Document | Description |
|----------|-------------|
| [PULSE](./resilience/PULSE.md) | Trending topic automation |
| [BROADCAST](./integrations/BROADCAST.md) | Audio broadcast generation |
| [NOMIC_LOOP](./workflow/NOMIC_LOOP.md) | Self-improvement system |
| [FORMAL_VERIFICATION](./workflow/FORMAL_VERIFICATION.md) | Z3/Lean verification |
| [TRICKSTER](./debate/TRICKSTER.md) | Hollow consensus detection |
| [A_B_TESTING](./testing/A_B_TESTING.md) | A/B testing framework |
| [EVOLUTION_PATTERNS](./workflow/EVOLUTION_PATTERNS.md) | Evolution pattern library |
| [GITHUB_ACTIONS](./deployment/GITHUB_ACTIONS.md) | CI/CD integration |

## Advanced / Research

| Document | Description |
|----------|-------------|
| [NOMIC_LOOP](./workflow/NOMIC_LOOP.md) | Self-improvement system |
| [GENESIS](./workflow/GENESIS.md) | Fractal resolution and agent evolution |
| [CROSS_POLLINATION](./integrations/CROSS_POLLINATION.md) | Cross-debate knowledge transfer |
| [FORMAL_VERIFICATION](./workflow/FORMAL_VERIFICATION.md) | Z3/Lean verification |
| [TRICKSTER](./debate/TRICKSTER.md) | Hollow consensus detection |
| [TRUST_PORTABILITY](./architecture/TRUST_PORTABILITY.md) | ERC-8004 agent identity and portable reputation across organizations |
| [ADR/README](./ADR/README.md) | Architecture Decision Records |

## Troubleshooting

| Document | Description |
|----------|-------------|
| [TROUBLESHOOTING](./guides/TROUBLESHOOTING.md) | Common issues and solutions |
| [NOMIC_LOOP_TROUBLESHOOTING](./guides/NOMIC_LOOP_TROUBLESHOOTING.md) | Nomic loop specific issues |
| [CONNECTOR_TROUBLESHOOTING](./guides/CONNECTOR_TROUBLESHOOTING.md) | Connector issues |
| [ALERT_RUNBOOKS](./deployment/ALERT_RUNBOOKS.md) | Alert response procedures |

## Case Studies

| Document | Description |
|----------|-------------|
| [case-studies/README](./case-studies/README.md) | Real-world applications and audits |

---

## Strategy & Positioning

| Document | Description |
|----------|-------------|
| [STRATEGY_INDEX](./strategy/STRATEGY_INDEX.md) | Where the consolidated strategy and outreach documents live |
| [WHY_ADVERSARIAL_DEBATE](./strategy/WHY_ADVERSARIAL_DEBATE.md) | Why one model's opinion is not enough for consequential decisions |
| [FOCUS](./strategy/FOCUS.md) | Focus strategy: depth over breadth |
| [HONEST_ASSESSMENT](./strategy/HONEST_ASSESSMENT.md) | What works, what does not, and why it matters |
| [COMPARISON_MATRIX](./strategy/COMPARISON_MATRIX.md) | Aragora compared with agent frameworks |
| [PRICING](./strategy/PRICING.md) | Open-source core and commercial tiers |
| [ROADMAP_30_60_90](./strategy/ROADMAP_30_60_90.md) | 30/60/90-day roadmap written in February 2026 |

---

## Documentation Map

The curated subdirectories of `docs/`. Each directory link opens the
directory; the entry pages are good places to start. Other subdirectories
(`api/`, `debate/`, `enterprise/`, `specs/` and more) are indexed by topic in
the sections above.

| Directory | What it holds | Start with |
|-----------|---------------|------------|
| [getting-started/](./getting-started/) | First-run and install guides | [ZERO_CONFIG](./getting-started/ZERO_CONFIG.md), [LOCAL_DEVELOPMENT](./getting-started/LOCAL_DEVELOPMENT.md) |
| [guides/](./guides/) | Task-oriented how-to guides | [USE_CASES](./guides/USE_CASES.md), [API_COOKBOOK](./guides/API_COOKBOOK.md), [TROUBLESHOOTING](./guides/TROUBLESHOOTING.md) |
| [reference/](./reference/) | Configuration, environment, error codes and the generated CLI flag catalog | [Reference Index](./reference/INDEX.md) |
| [architecture/](./architecture/) | System design and structural contracts | [ARCHITECTURE](./architecture/ARCHITECTURE.md), [IMPORT_LAYERS](./architecture/IMPORT_LAYERS.md), [TRUST_PORTABILITY](./architecture/TRUST_PORTABILITY.md) |
| [operations/](./operations/) | Operating, self-hosting and production runbooks | [OPERATIONS](./operations/OPERATIONS.md), [SELF_HOSTING](./operations/SELF_HOSTING.md), [PRODUCTION_RUNBOOK](./operations/PRODUCTION_RUNBOOK.md) |
| [governance/](./governance/) | Merge gates, operator delegation and repository governance | [TIERED_MERGE_GATE_ENABLEMENT](./governance/TIERED_MERGE_GATE_ENABLEMENT.md), [QUORUM_EVIDENCE_RUNBOOK](./governance/QUORUM_EVIDENCE_RUNBOOK.md), [OPERATOR_DELEGATION_POLICY](./governance/OPERATOR_DELEGATION_POLICY.md), [LOOP_CONTROL_PLANE](./governance/LOOP_CONTROL_PLANE.md) |
| [strategy/](./strategy/) | Positioning, pricing and roadmaps | [STRATEGY_INDEX](./strategy/STRATEGY_INDEX.md), [ROADMAP_30_60_90](./strategy/ROADMAP_30_60_90.md) |

---

## Top-Level Pages

Every Markdown page kept at the top of `docs/` is listed here. Most keep that
path because tools, tests, protected files or published links depend on it;
other pages live in the subdirectories above.

| Page | Description |
|------|-------------|
| [AGENT_ASSIGNMENTS](./AGENT_ASSIGNMENTS.md) | Agent task assignments by track |
| [AGENT_FLYWHEEL_ARAGORA_NATIVE](./AGENT_FLYWHEEL_ARAGORA_NATIVE.md) | Agent Flywheel concepts mapped to Aragora primitives |
| [AGENT_OPERATING_CONTRACT](./AGENT_OPERATING_CONTRACT.md) | Operating contract for autonomous agents in this repository |
| [API_ENDPOINTS](./API_ENDPOINTS.md) | Generated HTTP endpoint list (`scripts/generate_api_docs.py`) |
| [BREAKING_CHANGES](./BREAKING_CHANGES.md) | Planned breaking changes for v3.0 |
| [CANONICAL_GOALS](./CANONICAL_GOALS.md) | Canonical goals and foundational thesis |
| [CAPABILITY_MATRIX](./CAPABILITY_MATRIX.md) | Generated capability matrix |
| [CI_LANES](./CI_LANES.md) | Two-lane CI system |
| [CLI_REFERENCE](./CLI_REFERENCE.md) | CLI command reference |
| [COMMERCIAL_OVERVIEW](./COMMERCIAL_OVERVIEW.md) | Commercial positioning and readiness |
| [COORDINATION](./COORDINATION.md) | Multi-agent coordination for this repository |
| [DEPLOYMENT](./DEPLOYMENT.md) | Deployment guide |
| [ENTERPRISE_FEATURES](./ENTERPRISE_FEATURES.md) | Enterprise features reference |
| [EU_AI_ACT_COMPLIANCE](./EU_AI_ACT_COMPLIANCE.md) | EU AI Act compliance with Aragora |
| [EXTENDED_README](./EXTENDED_README.md) | Extended technical reference |
| [FEATURE_DISCOVERY](./FEATURE_DISCOVERY.md) | Compatibility entry point for the feature inventory |
| [FEATURE_GAP_LIST](./FEATURE_GAP_LIST.md) | Planned, partial, and hardening work |
| [GA_CHECKLIST](./GA_CHECKLIST.md) | Self-hosted GA readiness checklist |
| [INDEX](./INDEX.md) | Sub-index: short flat list of the most-used pages (the docs site's documentation index) |
| [LANDING_PAGE](./LANDING_PAGE.md) | Landing page copy |
| [METRICS](./METRICS.md) | Canonical generated metrics |
| [NEXT_STEPS](./NEXT_STEPS.md) | Compatibility pointer to the canonical next steps |
| [PACKAGING](./PACKAGING.md) | Packaging strategy |
| [RECEIPT_CONTRACT](./RECEIPT_CONTRACT.md) | Receipt contract for new integrations |
| [REVIEW_AUTHORITY_PRINCIPLES](./REVIEW_AUTHORITY_PRINCIPLES.md) | Principles behind review authority |
| [SDK_COMPARISON](./SDK_COMPARISON.md) | Python and TypeScript SDK comparison |
| [SDK_GUIDE](./SDK_GUIDE.md) | Python SDK guide |
| [SDK_QUICKSTART_PYTHON](./SDK_QUICKSTART_PYTHON.md) | Python SDK quickstart |
| [START_HERE](./START_HERE.md) | Sub-index: choose a package and follow its path |
| [STATUS](./STATUS.md) | Project status |
| [THESIS](./THESIS.md) | The Aragora thesis |
| [WHY_ARAGORA](./WHY_ARAGORA.md) | Why Aragora |
| [quickstart](./quickstart.md) | Run your first debate |

---

## Archived/Historical Documents

Deprecated and historical documents live under `docs/deprecated/`. These are
kept for reference but are no longer maintained.

See [docs/deprecated/README.md](./deprecated/README.md) for the full index.

---

## API Documentation

- [OpenAPI Specification (YAML)](./api/openapi.yaml)
- [OpenAPI Specification (JSON)](./api/openapi.json)
- [Interactive Docs](./index.html) - Swagger UI
  - `openapi.yaml` is JSON-formatted for compatibility; regenerate with
    `python scripts/export_openapi.py --output-dir docs/api`.

---

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full contribution guide. For
frontend contributions, also see [FRONTEND_DEVELOPMENT.md](./debate/FRONTEND_DEVELOPMENT.md),
and for new agents, see [AGENT_DEVELOPMENT.md](./debate/AGENT_DEVELOPMENT.md).

## Documentation Maintenance

### Inventory

- Markdown files under `docs/`: 435+ (includes deprecated)
- Sync to docs-site: `node docs-site/scripts/sync-docs.js`
- API endpoint list: `python scripts/generate_api_docs.py --output docs/API_ENDPOINTS.md`
- OpenAPI export: `python scripts/export_openapi.py --output-dir docs/api`

### Review Schedule

Documentation is reviewed and updated according to this schedule:

| Category | Review Frequency | Last Review |
|----------|------------------|-------------|
| Quick Start / Getting Started | Monthly | 2026-02 |
| API Reference | With each release | 2026-02 |
| Architecture / Core Concepts | Quarterly | 2026-02 |
| Feature Documentation | When features change | 2026-02 |
| Security Documentation | Monthly | 2026-02 |
| Troubleshooting | As issues are reported | Ongoing |

### Documentation Review Checklist

When reviewing documentation:

1. **Accuracy**: Do code examples still work? Are APIs current?
2. **Completeness**: Are all features documented? Missing sections?
3. **Clarity**: Is the writing clear and accessible?
4. **Links**: Do all internal/external links work?
5. **Versioning**: Is version-specific info clearly marked?

### Reporting Issues

Found outdated or incorrect documentation?

1. Open a GitHub issue with the label `documentation`
2. Include the document path and section
3. Describe what's incorrect or outdated
4. Suggest a correction if possible

---

## Support

- [GitHub Issues](https://github.com/synaptent/aragora/issues)
- [Documentation Updates](https://github.com/synaptent/aragora/pulls)
