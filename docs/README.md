# Aragora Documentation

Welcome to Aragora's documentation. The `docs/` directory is the canonical
source. The published site in `docs-site/` is synced from these files via
`docs-site/scripts/sync-docs.js`.

Aragora is the **control plane for multi-agent vetted decisionmaking across
organizational knowledge and channels**.

## What Are You Trying To Do?

| Goal | Document |
|------|----------|
| **Run your first debate in 5 minutes** | [Quickstart](./guides/QUICKSTART.md) |
| Full onboarding guide | [Getting Started](./guides/GETTING_STARTED.md) |
| See 20 runnable code examples | [API Cookbook](./guides/API_COOKBOOK.md) |
| Build a Python integration | [SDK Guide](./SDK_GUIDE.md) |
| Build a TypeScript integration | [TypeScript SDK](./guides/SDK_TYPESCRIPT.md) |
| Use the REST API | [API Reference](./api/API_REFERENCE.md) |
| Stream events via WebSocket | [WebSocket Events](./streaming/WEBSOCKET_EVENTS.md) |
| Deploy to production | [Deployment Guide](./deployment/DEPLOYMENT.md) |
| Set up Slack/Telegram/WhatsApp | [Chat Connector Guide](./guides/CHAT_CONNECTOR_GUIDE.md) |
| Troubleshoot an issue | [Troubleshooting](./guides/TROUBLESHOOTING.md) |
| Understand the architecture | [Architecture](./architecture/ARCHITECTURE.md) |

## Core Concepts

| Document | Description |
|----------|-------------|
| [ARCHITECTURE](./architecture/ARCHITECTURE.md) | System architecture overview |
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
| [EXECUTION_NEXT_6_WEEKS_2026-03-05](./status/EXECUTION_NEXT_6_WEEKS_2026-03-05.md) | Active short-horizon plan |
| [DOCUMENTATION_HYGIENE_AND_GAP_REGISTER](./status/DOCUMENTATION_HYGIENE_AND_GAP_REGISTER.md) | Running roadmap, drift, and feature-gap register |

### Memory Tiers

| Tier | Half-Life | Purpose |
|------|-----------|---------|
| Fast | 1 hour | Immediate context within a debate |
| Medium | 24 hours | Session-level memory |
| Slow | 7 days | Cross-session patterns |
| Glacial | 30 days | Long-term institutional knowledge |

See [MEMORY_STRATEGY](./knowledge/MEMORY_STRATEGY.md) for details.

## Using Aragora

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
| [BREAKING_CHANGES](./reference/BREAKING_CHANGES.md) | Breaking changes and migration |
| [MIGRATION_V1_TO_V2](./status/MIGRATION_V1_TO_V2.md) | API v1 to v2 migration guide |
| [WEBSOCKET_EVENTS](./streaming/WEBSOCKET_EVENTS.md) | WebSocket event reference |
| [SDK_TYPESCRIPT](./guides/SDK_TYPESCRIPT.md) | TypeScript SDK guide |
| [SDK_CONSOLIDATION](./guides/SDK_CONSOLIDATION.md) | TypeScript SDK migration (v2 to v3) |
| [SDK_GUIDE](./SDK_GUIDE.md) | Python SDK guide |
| [PYTHON_SDK_MIGRATION](./guides/PYTHON_SDK_MIGRATION.md) | Canonical Python SDK migration (`aragora-client` -> `aragora-sdk`) |
| [LIBRARY_USAGE](./reference/LIBRARY_USAGE.md) | Using Aragora as a library |

### API Quick Reference

| Endpoint Pattern | Purpose |
|-----------------|---------|
| `POST /api/v1/debates` | Start a debate |
| `GET /api/v1/debates/{id}` | Get debate result |
| `GET /ws/debate/{id}` | Stream events via WebSocket |
| `POST /api/v1/knowledge/search` | Search knowledge |
| `GET /api/v1/agents/rankings` | Agent rankings |
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

See [CLI_REFERENCE](./reference/CLI_REFERENCE.md) for full documentation.

## Operations & Deployment

| Document | Description |
|----------|-------------|
| [DEPLOYMENT](./deployment/DEPLOYMENT.md) | Deployment guide |
| [OPERATIONS](./OPERATIONS.md) | Operations runbook |
| [RUNBOOK](./deployment/RUNBOOK.md) | Incident response procedures |
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
| [GOVERNANCE](./enterprise/GOVERNANCE.md) | Decision governance |
| [COMPLIANCE](./enterprise/COMPLIANCE.md) | SOC 2, GDPR support |
| [COMPLIANCE_PRESETS](./enterprise/COMPLIANCE_PRESETS.md) | Built-in audit presets |
| [DATA_CLASSIFICATION](./enterprise/DATA_CLASSIFICATION.md) | Data classification policy |

## Configuration

| Document | Description |
|----------|-------------|
| [ENVIRONMENT](./reference/ENVIRONMENT.md) | Environment variables reference |
| [DATABASE](./reference/DATABASE.md) | Database architecture |
| [CLI_REFERENCE](./reference/CLI_REFERENCE.md) | CLI command reference |

## Development

| Document | Description |
|----------|-------------|
| [CONTRIBUTING](../CONTRIBUTING.md) | Contribution guide |
| [FRONTEND_DEVELOPMENT](./debate/FRONTEND_DEVELOPMENT.md) | Frontend contribution guide |
| [FRONTEND_ROUTES](./guides/FRONTEND_ROUTES.md) | Frontend route and feature map |
| [HANDLER_DEVELOPMENT](./debate/HANDLER_DEVELOPMENT.md) | Writing new server handlers |
| [TESTING](./testing/TESTING.md) | Test suite documentation |
| [CODING_ASSISTANCE](./architecture/CODING_ASSISTANCE.md) | Code review and generation |
| [BREAKING_CHANGES](./reference/BREAKING_CHANGES.md) | Breaking changes by version |
| [DEPRECATION_POLICY](./reference/DEPRECATION_POLICY.md) | Deprecation and migration policy |
| [ERROR_CODES](./reference/ERROR_CODES.md) | Error code reference |

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

- [GitHub Issues](https://github.com/an0mium/aragora/issues)
- [Documentation Updates](https://github.com/an0mium/aragora/pulls)
