# SDK Parity Roadmap

Roadmap for achieving 95%+ API coverage across TypeScript and Python SDKs.

> **Status as of March 2026: COMPLETE.** Both SDKs have exceeded the 95% parity target.
> Current counts: Python 184 namespaces, 5,800+ methods | TypeScript 183 namespaces, 3,700+ methods (99.3% parity).
> This document preserves the January 2026 sprint record.

## Status (Updated 2026-01-28 — targets now exceeded)

| SDK | Namespaces | Methods | Coverage | Target |
|-----|------------|---------|----------|--------|
| TypeScript | 105 | 1,756 | ~90% | 95% |
| Python | 105 | 4,720 | ~95% | 95% |

**Status: NEAR COMPLETE** *(as of Jan 28; see March 2026 note above)*

Both SDKs now have comprehensive coverage with 105 namespaces each. The Python SDK includes auto-generated OpenAPI client with 2,360+ methods plus hand-crafted namespace implementations.

**Recent Progress:**
- TypeScript: 105 namespaces covering all major API categories
- Python: 4,720 methods across 105 namespaces including full OpenAPI coverage
- Both SDKs have parity on namespace structure

## Coverage by Category

Both SDKs now have comprehensive namespace coverage. Here's the breakdown:

### Core Namespaces (Complete)
| Category | TS Namespace | PY Namespace | Status |
|----------|--------------|--------------|--------|
| Auth | ✅ auth.ts | ✅ auth.py (52 methods) | Complete |
| Debates | ✅ debates.ts | ✅ debates.py (64 methods) | Complete |
| Codebase | ✅ codebase.ts | ✅ codebase.py (68 methods) | Complete |
| Agents | ✅ agents.ts | ✅ agents.py (52 methods) | Complete |
| Knowledge | ✅ knowledge.ts | ✅ knowledge.py (80 methods) | Complete |

### Platform Namespaces (Complete)
| Category | TS Namespace | PY Namespace | Status |
|----------|--------------|--------------|--------|
| Workflows | ✅ workflows.ts | ✅ workflows.py (40 methods) | Complete |
| Webhooks | ✅ webhooks.ts | ✅ webhooks.py | Complete |
| Budgets | ✅ budgets.ts | ✅ budgets.py (32 methods) | Complete |
| Memory | ✅ memory.ts | ✅ memory.py | Complete |
| Notifications | ✅ notifications.ts | ✅ notifications.py | Complete |

### Enterprise Namespaces (Complete)
| Category | TS Namespace | PY Namespace | Status |
|----------|--------------|--------------|--------|
| Admin | ✅ admin.ts | ✅ admin.py (54 methods) | Complete |
| Analytics | ✅ analytics.ts | ✅ analytics.py (48 methods) | Complete |
| RBAC | ✅ rbac.ts | ✅ rbac.py | Complete |
| Tenants | ✅ tenants.ts | ✅ tenants.py | Complete |
| Compliance | ✅ compliance.ts | ✅ compliance.py | Complete |
| Audit | ✅ audit.ts | ✅ audit.py (46 methods) | Complete |

### Specialized Namespaces (Complete)
| Category | TS Namespace | PY Namespace | Status |
|----------|--------------|--------------|--------|
| Pulse | ✅ pulse.ts | ✅ pulse.py | Complete |
| Gauntlet | ✅ gauntlet.ts | ✅ gauntlet.py (36 methods) | Complete |
| Explainability | ✅ explainability.ts | ✅ explainability.py | Complete |
| RLM | ✅ rlm.ts | ✅ rlm.py | Complete |
| Control Plane | ✅ control_plane.ts | ✅ control_plane.py (64 methods) | Complete |
| Nomic | ✅ nomic.ts | ✅ nomic.py (42 methods) | Complete |

### Additional Namespaces (105 total per SDK)
Both SDKs include specialized namespaces for:
- Accounting, AP/AR Automation, Advertising
- Billing, Belief Network, Backups
- Chat, Connectors, Cost Management
- Decisions, Documents, Email Services
- Feedback, Genesis, Gmail, Health
- Integrations, Invoice Processing
- Leaderboard, Learning, Laboratory
- Marketplace, Metrics, Monitoring
- OAuth, Organizations, Onboarding
- Payments, Plugins, Policies, Privacy
- Receipts, Replays, Routing, Ranking
- SME, System, Teams, Tenants
- Threat Intel, Tournaments, Training
- Transcription, Unified Inbox, Usage
- Verification, Verticals, Voice, Workspaces
- YouTube, and more...

## Implementation Status

All phases complete. SDK parity achieved.

### Phase 1: Foundation ✅ COMPLETE
- [x] TypeScript: Core namespaces (Auth, Debates, Codebase, Agents, Knowledge)
- [x] Python: Core namespaces with full async support
- [x] Code generation tooling (`scripts/generate_sdk.py`)
- [x] SDK test infrastructure

### Phase 2: Platform Coverage ✅ COMPLETE
- [x] TypeScript: Platform namespaces (Workflows, Webhooks, Budgets, Memory)
- [x] Python: Platform namespaces with streaming support
- [x] Async/streaming in Python SDK
- [x] WebSocket client implementation

### Phase 3: Enterprise Features ✅ COMPLETE
- [x] TypeScript: Enterprise namespaces (Admin, Analytics, RBAC, Tenants)
- [x] Python: Enterprise namespaces with full coverage
- [x] Retry/circuit breaker patterns
- [x] Error handling standardization

### Phase 4: Parity ✅ COMPLETE
- [x] TypeScript: 105 namespaces, 1,756 methods
- [x] Python: 105 namespaces, 4,720 methods
- [x] Cross-SDK namespace parity
- [x] OpenAPI auto-generation (2,360+ methods)
- [ ] Cross-SDK test suite
- [ ] Documentation sync

**Deliverables:**
- TypeScript: +55 endpoints (340 total, 95%)
- Python: +105 endpoints (340 total, 95%)

## SDK Architecture

### TypeScript SDK (`sdk/typescript/`)

```
sdk/typescript/
├── src/
│   ├── client.ts           # Main client
│   ├── auth/               # Auth endpoints
│   ├── debates/            # Debate operations
│   ├── agents/             # Agent management
│   ├── knowledge/          # KM operations
│   ├── workflows/          # Workflow engine
│   └── types/              # Generated types
├── examples/
└── tests/
```

### Python SDK (`sdk/python/`)

> Note: The legacy `aragora-py/` directory was removed in February 2026. The canonical Python SDK is now `sdk/python/`.

```
sdk/python/
├── aragora_sdk/
│   ├── client.py           # Main client
│   ├── namespaces/         # Namespaced API surface
│   ├── generated_types.py  # Auto-generated Pydantic models
├── examples/
└── tests/
```

## Code Generation Strategy

To accelerate development and ensure consistency:

1. **OpenAPI Spec** - Maintain `api/openapi.yaml` as source of truth
2. **Type Generation** - Auto-generate TypeScript types and Pydantic models
3. **Client Generation** - Use templates for endpoint wrappers
4. **Test Generation** - Generate test stubs from spec

### Generator Pipeline

```bash
# Generate from OpenAPI spec
python scripts/generate_sdk.py --spec api/openapi.yaml --output sdk/

# Outputs:
# - sdk/typescript/src/types/generated.ts
# - sdk/python/aragora_sdk/generated_types.py
# - sdk/*/tests/test_*.py (stubs)
```

## Quality Standards

### Required for Each Endpoint

- [ ] Type definitions (TS) / Pydantic models (Python)
- [ ] Input validation
- [ ] Error handling with typed exceptions
- [ ] JSDoc/docstring documentation
- [ ] Unit test with mocked HTTP
- [ ] Integration test example

### SDK Features

| Feature | TypeScript | Python |
|---------|------------|--------|
| Async support | Native | asyncio |
| Streaming | ReadableStream | AsyncGenerator |
| Retry logic | Configurable | tenacity |
| Rate limiting | Built-in | Built-in |
| Auth refresh | Automatic | Automatic |
| Pagination | Cursor-based | Cursor-based |

## Tracking Progress

Update this document as endpoints are implemented:

### Weekly Status Update

**Week of 2026-01-27**
- TypeScript: 53 namespaces implemented (was 47)
- New namespaces added:
  - `DeliberationsAPI` - Vetted decisionmaking visibility
  - `GenesisAPI` - Evolution and genome lineage
  - `LaboratoryAPI` - Emergent traits and cross-pollination
  - `TeamsAPI` - Microsoft Teams bot integration
  - `LearningAPI` - Meta-learning analytics
  - `BatchAPI` - Batch debate operations
- Total new endpoints covered: ~35
- Blockers: None

```markdown
### Template for Future Updates

**Week of YYYY-MM-DD**
- TypeScript: X/358 (Y.Y%)
- Python: X/358 (Y.Y%)
- New endpoints: [list]
- Blockers: [any]
```

## Resources

- **API Reference:** `docs/API_REFERENCE.md`
- **SDK Guide:** `docs/SDK_GUIDE.md`
- **OpenAPI Spec:** `api/openapi.yaml`
- **TypeScript SDK:** `sdk/typescript/`
- **Python SDK:** `sdk/python/`

## Issue Tracking

This roadmap tracks GitHub issue #102 (SDK Parity).

Updates will be posted to the issue as milestones are reached.
