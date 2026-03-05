# Claude Code Integration Guide

Context for Claude Code when working with the Aragora codebase.

> **Multi-Agent Coordination:** If multiple AI agents are working on this codebase,
> check `docs/COORDINATION.md` before starting. See `docs/AGENT_ASSIGNMENTS.md`
> for recommended focus areas by track.

## Worktree Isolation (CRITICAL)

**Every Claude Code session MUST run in an isolated worktree.** Multiple sessions share this
repo — editing files in the main directory causes concurrent overwrites.

### Automatic isolation (3 layers)

1. **Preferred: `claude-wt` wrapper** — Launch Claude via `./scripts/claude-wt` instead of `claude`.
   Creates a fresh worktree automatically. Pass `--resume` to reuse an existing one.
2. **Fallback: SessionStart hook** — If launched without the wrapper, a hook detects you're in
   the main directory and outputs a warning. **When you see this warning, call `EnterWorktree`
   before making any file edits.**
3. **Background cleanup** — A LaunchAgent runs every 5 minutes, reconciling worktrees with main
   (merge strategy) and cleaning up stale ones after 24h. Branches are auto-deleted after merge.

### Manual worktree commands

- `./scripts/codex_session.sh` — Legacy session bootstrap (creates worktree + metadata)
- `python3 scripts/codex_worktree_autopilot.py ensure --agent claude --base main --force-new --print-path`
- `python3 scripts/codex_worktree_autopilot.py maintain --base main --strategy merge --ttl-hours 24`
- `python3 scripts/codex_worktree_autopilot.py cleanup --base main --ttl-hours 24 --delete-branches`
- Cleanup stale session worktrees via `python3 scripts/codex_worktree_autopilot.py cleanup --base main --ttl-hours 24`.
- Optional macOS automation: `make worktree-maintainer-install` to run background reconcile-only upkeep every 5 minutes.

## Quick Reference

| What | Where | Key Files |
|------|-------|-----------|
| Debate engine | `aragora/debate/` | `orchestrator.py`, `consensus.py` |
| Agents | `aragora/agents/` | `cli_agents.py`, `api_agents/` |
| Analytics | `aragora/analytics/` | `dashboard.py`, `debate_analytics.py` |
| Audit | `aragora/audit/` | `log.py`, `orchestrator.py`, `codebase_auditor.py`, `bug_detector.py` |
| CI Lanes | `docs/CI_LANES.md` | Two-lane CI: draft PRs run 5 checks, ready PRs run full suite |
| Backup | `aragora/backup/` | `manager.py` (disaster recovery) |
| Billing | `aragora/billing/` | `cost_tracker.py`, `budget_manager.py`, `metering.py`, `forecaster.py` |
| Chat routing | `aragora/server/` | `debate_origin.py`, `result_router.py` |
| CLI | `aragora/cli/` | `main.py`, `parser.py`, `gt.py`, `repl.py`, `commands/` |
| Compliance | `aragora/compliance/` | `framework.py`, `monitor.py`, `policy_store.py`, `report_generator.py` |
| Connectors | `aragora/connectors/` | `slack.py`, `github.py`, `chat/`, `enterprise/streaming/` |
| Control Plane | `aragora/control_plane/` | `policy.py`, `scheduler.py`, `notifications.py` |
| Enterprise | `aragora/auth/`, `aragora/tenancy/` | `oidc.py`, `isolation.py` |
| Events | `aragora/events/` | `dispatcher.py`, `schema.py`, `dead_letter_queue.py`, `subscribers/` |
| Explainability | `aragora/explainability/` | `builder.py`, `factors.py` |
| Gateway | `aragora/gateway/` | `server.py`, `router.py`, `protocol.py` |
| Gauntlet | `aragora/gauntlet/` | `receipts.py`, `runner.py`, `findings.py` |
| Integrations | `aragora/integrations/` | `slack.py`, `email.py`, `discord.py`, `teams.py`, `zapier.py`, `langchain/` |
| Knowledge | `aragora/knowledge/` | `bridges.py`, `mound/`, `mound/resilience.py` |
| MCP | `aragora/mcp/` | `server.py`, `tools.py`, `tools_module/` |
| Memory | `aragora/memory/` | `continuum/`, `consensus.py`, `coordinator.py` |
| Nomic loop | `scripts/` | `nomic_loop.py`, `run_nomic_with_stream.py`, `self_develop.py` |
| Nomic Stores | `aragora/nomic/stores/` | `bead_store.py`, `convoy_store.py`, `paths.py` |
| Notifications | `aragora/notifications/` | `service.py` |
| Observability | `aragora/observability/` | `metrics.py`, `tracing.py`, `slo.py`, `logging.py` |
| Ops | `aragora/ops/` | `deployment_validator.py` (runtime validation) |
| Privacy | `aragora/privacy/` | `anonymization.py`, `consent.py`, `deletion.py`, `retention.py` |
| Pulse | `aragora/pulse/` | `ingestor.py`, `scheduler.py`, `store.py`, `freshness.py`, `quality.py` |
| RBAC v2 | `aragora/rbac/` | `models.py`, `checker.py`, `decorators.py` |
| Reasoning | `aragora/reasoning/` | `belief.py`, `provenance.py`, `claims.py` |
| Resilience | `aragora/resilience/` | `circuit_breaker.py`, `retry.py`, `timeout.py`, `health.py`, `registry.py` |
| RLM | `aragora/rlm/` | `factory.py`, `bridge.py`, `handler.py` |
| Security | `aragora/security/` | `encryption.py`, `key_rotation.py`, `anomaly_detection.py`, `ssrf_protection.py` |
| Self-improvement | `aragora/nomic/` | `meta_planner.py`, `branch_coordinator.py`, `task_decomposer.py` |
| Server | `aragora/server/` | `unified_server.py`, `handlers/`, `startup.py` |
| Skills | `aragora/skills/` | `base.py`, `registry.py`, `marketplace.py`, `installer.py`, `builtin/` |
| Storage | `aragora/storage/` | `postgres_store.py`, `redis_ha.py`, `schema.py`, `repositories/` |
| Streaming | `aragora/connectors/enterprise/streaming/` | `kafka.py`, `rabbitmq.py` |
| TTS/Voice | `aragora/server/stream/` | `tts_integration.py`, `voice_stream.py` |
| Workflow | `aragora/workflow/` | `engine.py`, `patterns/`, `nodes/`, `templates/` |
| Workspace | `aragora/workspace/` | `bead.py`, `convoy.py`, `manager.py` |
| Audience | `aragora/audience/` | Audience suggestion sanitization and clustering |
| Blockchain | `aragora/blockchain/` | ERC-8004 agent identity and reputation registries |
| Coordination | `aragora/coordination/` | Cross-workspace federated execution |
| Deliberation | `aragora/deliberation/` | Deliberation templates and patterns |
| Genesis | `aragora/genesis/` | Fractal resolution, agent evolution, Argonaut ledger |
| Harnesses | `aragora/harnesses/` | External tool integration (Claude Code, Codex) |
| Introspection | `aragora/introspection/` | Agent self-awareness and meta-cognition |
| Learning | `aragora/learning/` | Continual learning with Nested Learning paradigm |
| Marketplace | `aragora/marketplace/` | Agent template and protocol marketplace |
| Moderation | `aragora/moderation/` | Spam filtering and content validation |
| Modes | `aragora/modes/` | Operational modes (Architect, Coder, Reviewer, etc.) |
| Pipeline | `aragora/pipeline/` | Idea-to-Execution 4-stage pipeline (Ideas→Goals→Workflows→Orchestration) |
| Runtime | `aragora/runtime/` | Budget-aware autotuner, metadata, metrics |
| Sandbox | `aragora/sandbox/` | Docker-based safe code execution |
| Spectate | `aragora/spectate/` | Real-time debate observation |
| Visualization | `aragora/visualization/` | Argument cartography and logic mapping |

## Canonical Storage Paths

Bead and convoy data are stored under the canonical store root:

```
<workspace_root>/.aragora_beads
```

Legacy `.gt` stores are supported for backwards compatibility when present.

## Project Overview

Aragora is the **Decision Integrity Platform** -- orchestrating 43 agent types to adversarially vet decisions against your organization's knowledge, then delivering audit-ready decision receipts to any channel. It implements self-improvement through the **Nomic Loop** -- an autonomous cycle where agents debate improvements, design solutions, implement code, and verify changes.

**Five Pillars:** (1) SMB-ready with enterprise-grade security, (2) leading-edge memory and context processing, (3) extensible/modular with broad connectors and SDKs, (4) multi-agent robustness via heterogeneous model consensus, (5) self-healing and self-extending via the Nomic Loop.

**Codebase Scale:** 3,000+ Python modules | 208,000+ tests | 4,000+ test files | 210+ debate modules | 3,000+ API operations across 2,900+ paths | 41 registered KM adapters | 185 SDK namespaces

## Architecture

```
aragora/
├── debate/           # Core debate orchestration
│   ├── orchestrator.py     # Arena class - main debate engine
│   ├── phases/             # Extracted phase implementations
│   ├── team_selector.py    # Agent team selection (ELO + calibration)
│   ├── memory_manager.py   # Memory coordination
│   ├── prompt_builder.py   # Prompt construction
│   ├── consensus.py        # Consensus detection and proofs
│   └── convergence.py      # Semantic similarity detection
│   # Configurable concurrency: MAX_CONCURRENT_PROPOSALS, MAX_CONCURRENT_CRITIQUES, MAX_CONCURRENT_REVISIONS
├── agents/           # Agent implementations
│   ├── cli_agents.py       # CLI agents (claude, codex, gemini, grok)
│   ├── api_agents/         # API agents directory
│   │   ├── anthropic.py    # Anthropic API agent
│   │   ├── openai.py       # OpenAI API agent
│   │   ├── mistral.py      # Mistral API agent (Large, Codestral)
│   │   ├── grok.py         # xAI Grok agent
│   │   └── openrouter.py   # OpenRouter (DeepSeek, Llama, Qwen, Yi, Kimi)
│   ├── fallback.py         # OpenRouter fallback on quota errors
│   └── airlock.py          # AirlockProxy for agent resilience
├── memory/           # Learning and persistence
│   ├── continuum/          # Multi-tier memory (fast/medium/slow/glacial)
│   ├── consensus.py        # Historical debate outcomes
│   └── coordinator.py      # Atomic cross-system memory writes
├── knowledge/        # Unified knowledge management
│   ├── bridges.py          # KnowledgeBridgeHub, MetaLearner, Evidence bridges
│   └── mound/              # KnowledgeMound with sync, revalidation
│       └── adapters/       # KM adapters (41 registered)
│           └── factory.py  # Auto-create adapters from Arena subsystems
├── connectors/       # External integrations
│   ├── chat/               # Telegram, WhatsApp connectors
│   └── enterprise/
│       └── streaming/      # Event stream ingestion
│           ├── kafka.py    # Apache Kafka consumer
│           └── rabbitmq.py # RabbitMQ consumer/publisher
├── server/           # HTTP/WebSocket API
│   ├── unified_server.py   # Main server (3,000+ API operations)
│   ├── startup.py          # Server startup sequence
│   ├── debate_origin.py    # Bidirectional chat result routing
│   ├── handlers/           # HTTP endpoint handlers (580+ modules)
│   │   └── social/         # Chat platform handlers (Telegram, WhatsApp)
│   └── stream/             # WebSocket streaming (190+ event types)
│       ├── tts_integration.py  # TTS for voice/chat
│       └── voice_stream.py     # Voice session management
├── ranking/          # Agent skill tracking
│   └── elo.py              # ELO ratings and calibration
├── resilience.py     # CircuitBreaker for agent failure handling
├── control_plane/    # Enterprise orchestration (1,500+ tests)
│   ├── registry.py        # Agent discovery with heartbeats
│   ├── scheduler.py       # Priority-based task distribution
│   ├── health.py          # Liveness probes and monitoring
│   └── coordinator.py     # Unified control plane API
├── rbac/             # Role-based access control v2
│   ├── models.py           # Permission, Role, RoleAssignment dataclasses
│   ├── types.py            # 7 default roles, 50+ permissions
│   ├── checker.py          # PermissionChecker with caching
│   ├── decorators.py       # @require_permission, @require_role
│   ├── middleware.py       # HTTP route protection
│   └── audit.py            # Authorization audit logging
├── backup/           # Disaster recovery
│   └── manager.py          # BackupManager with incremental support
└── verification/     # Proof generation
    └── formal.py           # Z3/Lean verification backends
```

## Protected Files

**Do NOT modify without explicit approval:**
- `CLAUDE.md` - This file
- `aragora/__init__.py` - Package exports
- `.env` - Environment configuration (never commit)
- `scripts/nomic_loop.py` - Critical for self-improvement safety

## Nomic Loop

The autonomous self-improvement cycle (`scripts/nomic_loop.py`):

| Phase | Name | Purpose |
|-------|------|---------|
| 0 | Context | Gather codebase understanding |
| 1 | Debate | Agents propose improvements |
| 2 | Design | Architecture planning |
| 3 | Implement | Code generation (Codex/Claude) |
| 4 | Verify | Tests and checks |

**Safety features:** Automatic backups, protected file checksums, rollback on failure, human approval for dangerous changes.

## Self-Improvement CLI

The self-improvement system uses the Nomic Loop components programmatically. Two CLI tools are available:

### Quick Start (Dry Run)

Preview goal decomposition without executing:

```bash
# Fast heuristic decomposition for concrete goals
python scripts/self_develop.py --goal "Refactor dashboard.tsx and api.py" --dry-run

# Debate-based decomposition for abstract goals (slower, more nuanced)
python scripts/self_develop.py --goal "Maximize utility for SME businesses" --dry-run --debate
```

### Full Autonomous Run

```bash
# Run with human approval at checkpoints
python scripts/self_develop.py --goal "Improve test coverage" --require-approval

# Focus on specific tracks
python scripts/self_develop.py --goal "Enhance SDK" --tracks developer qa

# Parallel execution across tracks
python scripts/self_develop.py --goal "Improve SME experience" --tracks sme developer --max-parallel 2
```

### Staged Execution

Run individual Nomic Loop phases for fine-grained control:

```bash
# Run phases individually
python scripts/nomic_staged.py debate      # Multi-agent debate on improvements
python scripts/nomic_staged.py design      # Design the implementation
python scripts/nomic_staged.py implement   # Generate implementation instructions
python scripts/nomic_staged.py verify      # Verify changes work
python scripts/nomic_staged.py commit      # Commit the changes

# Run debate + design + implement, then pause before verify
python scripts/nomic_staged.py all
```

### Nomic Loop Variants

| Variant | Location | Use Case |
|---------|----------|----------|
| Original loop | `scripts/nomic_loop.py` | Autonomous multi-cycle self-improvement |
| Staged execution | `scripts/nomic_staged.py` | Phase-by-phase manual control |
| Goal-driven | `scripts/self_develop.py` | Decompose high-level goals into tracks |
| Programmatic API | `aragora/nomic/autonomous_orchestrator.py` | Library integration for custom workflows |

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| MetaPlanner | `aragora/nomic/meta_planner.py` | Debate-driven goal prioritization |
| BranchCoordinator | `aragora/nomic/branch_coordinator.py` | Parallel branch management |
| TaskDecomposer | `aragora/nomic/task_decomposer.py` | Break complex tasks into subtasks |
| AutonomousOrchestrator | `aragora/nomic/autonomous_orchestrator.py` | End-to-end orchestration |

## Common Patterns

### Running a Debate
```python
from aragora import Arena, Environment, DebateProtocol

env = Environment(task="Design a rate limiter")
protocol = DebateProtocol(rounds=3, consensus="majority")
arena = Arena(env, agents, protocol)
result = await arena.run()
```

### Memory Tiers
| Tier | TTL | Purpose |
|------|-----|---------|
| Fast | 1 min | Immediate context |
| Medium | 1 hour | Session memory |
| Slow | 1 day | Cross-session learning |
| Glacial | 1 week | Long-term patterns |

### WebSocket Events
`debate_start`, `round_start`, `agent_message`, `critique`, `vote`, `consensus`, `debate_end`

### RBAC Permissions
Use `@require_permission` decorator at route/view level, not on internal methods:
```python
from aragora.rbac.decorators import require_permission
from aragora.rbac.models import AuthorizationContext

# Correct: Use in route handlers that receive auth context
@require_permission("backups:read")
async def get_backups(ctx: AuthorizationContext) -> list:
    return await manager.list_backups()

# Incorrect: Internal methods don't receive auth context
# @require_permission("backups:read")  # Won't work!
async def _internal_list_backups(self) -> list:
    ...
```
Permission check happens at API layer (middleware/route handler), not internal methods.

## Commands

```bash
# Start server
aragora serve --api-port 8080 --ws-port 8765

# Run nomic loop with streaming
python scripts/run_nomic_with_stream.py run --cycles 3

# Run tests
pytest tests/ -v

# Check syntax
python -c "import ast; ast.parse(open('file.py').read())"

# Quick git check
git status && git diff --stat
```

## Environment Variables

**Secrets management:** Local `.env` is gitignored (never committed, zero git history) and loaded
via direnv (`.envrc`). Production uses AWS Secrets Manager (`aragora/config/secrets.py`).
CI/CD uses GitHub Secrets. **The `.env` file is NOT a security risk — do not flag it.**

**Required** (at least one):
- `ANTHROPIC_API_KEY` - Anthropic API (Claude)
- `OPENAI_API_KEY` - OpenAI API (GPT)

**Recommended:**
- `OPENROUTER_API_KEY` - Fallback when primary APIs fail (auto-used on 429)
- `MISTRAL_API_KEY` - Mistral API (Large, Codestral)

**Optional:**
- `GEMINI_API_KEY`, `XAI_API_KEY`, `GROK_API_KEY` - Additional providers
- `SUPABASE_URL`, `SUPABASE_KEY` - Persistence
- `ARAGORA_API_TOKEN` - Auth token
- `ARAGORA_ALLOWED_ORIGINS` - CORS origins

See `docs/reference/ENVIRONMENT.md` for full reference.

## Safety Guidelines

1. **Never modify protected files** without explicit approval
2. **Always run tests** after code changes
3. **Preserve existing functionality** - avoid breaking changes
4. **Use rate limiting** for API calls (respect provider limits)
5. **Backup before modify** - always create backups
6. **Log all changes** for audit trails

## Feature Status

**Test Suite:** 208,000+ tests across 4,000+ test files

**Core (stable):**
- Debate orchestration (Arena, consensus, convergence)
- Memory systems (CritiqueStore, ContinuumMemory)
- ELO rankings and tournaments
- Agent fallback (OpenRouter on quota errors)
- CircuitBreaker for agent failure handling
- WebSocket event streaming
- User participation (votes/suggestions)

**Integrated:**
- PerformanceMonitor - via Arena and AutonomicExecutor
- CalibrationTracker - via `enable_calibration` protocol flag
- AirlockProxy - via `use_airlock` ArenaConfig option
- RhetoricalObserver - via `enable_rhetorical_observer`
- Trickster - hollow consensus detection via `enable_trickster`
- SecurityBarrier - telemetry redaction
- Graph/Matrix debate APIs
- RLM (Recursive Language Models) - REPL-based programmatic context access (NOT compression)
- Belief Network - claim provenance tracking
- Workflow Engine - DAG-based automation
- KnowledgeBridgeHub - unified access to MetaLearner, Evidence, Pattern bridges
- MemoryCoordinator - atomic cross-system writes via `enable_coordinated_writes`
- SelectionFeedbackLoop - performance-based agent selection via `enable_performance_feedback`
- CrossDebateMemory - institutional knowledge injection via `enable_cross_debate_memory`
- Post-debate workflows - automated processing via `enable_post_debate_workflow`
- Chat connectors - Telegram, WhatsApp integration for debate interfaces
- Leader election - distributed coordination via `aragora.control_plane.leader`
- Streaming connectors - Kafka and RabbitMQ for enterprise event ingestion
- Bidirectional chat routing - `debate_origin.py` routes results to originating platform
- Adapter factory - auto-create KM adapters from Arena subsystems
- TTS integration - voice synthesis for debates and chat channels
- Decision Explainability - natural language explanations, factor decomposition, counterfactuals
- Workflow Templates - 50+ pre-built templates across 6 categories, pattern factories
- Gauntlet Receipts - cryptographic audit trails with SHA-256 hashing
- Gauntlet Defense - proposer_agent param enables attack/defend cycles
- KM Resilience - ResilientPostgresStore with retry, health monitoring, cache invalidation
- Supermemory - cross-session external memory via `enable_supermemory` (80+ tests)
- Live Explainability - real-time debate factor tracking via `enable_live_explainability` (EventBus → snapshot → metadata)
- Active Introspection - per-round agent performance tracking via `enable_introspection` (proposals, critiques, influence)
- Argument Verification - structural soundness checking via `auto_verify_arguments` in PostDebateConfig
- Outcome Feedback - systematic error detection → Nomic Loop goals via `auto_outcome_feedback` in PostDebateConfig

**Enterprise (production-ready):**
- Authentication - OIDC/SAML SSO, MFA (TOTP/HOTP), API key management, SCIM 2.0 provisioning
- Multi-Tenancy - Tenant isolation, resource quotas, usage metering
- Security - AES-256-GCM encryption, rate limiting, circuit breakers
- Compliance - SOC 2 controls, GDPR support, audit trails
- Observability - Prometheus metrics, Grafana dashboards, OpenTelemetry tracing
- RBAC v2 - Fine-grained permissions (50+), role hierarchy, decorators, middleware
- Backup/DR - Incremental backups, retention policies, disaster recovery drills
- Control Plane - Agent registry, task scheduler, health monitoring, policy governance (1,500+ tests)
  - PolicyConflictDetector - Detects contradictory policies before they cause issues
  - RedisPolicyCache - Distributed cache for fast policy evaluation
  - PolicySyncScheduler - Continuous background policy synchronization
  - Omnichannel notifications - Debate → Slack/Teams/Email/Webhook delivery
  - ReceiptAdapter - Decision receipts auto-persist to Knowledge Mound

**Integrated:**
- Knowledge Mound - STABLE Phase A2 (100% integrated, 4,300+ tests passing)
  - 41 adapters (Continuum, Consensus, Critique, Evidence, Belief, Insights, ELO, Performance, Pulse, Cost, Provenance, Fabric, Workspace, ComputerUse, Gateway, CalibrationFusion, ControlPlane, Culture, Receipt, DecisionPlan, Outcome, Supermemory, RLM, RLMContext, Trickster, ERC8004, Obsidian, Debate, Workflow, Compliance, LangExtract, Codebase, IdeaCanvas, GoalCanvas, ClaudeMem, Genesis, Pipeline, Explainability, Email, Jira, Confluence)
  - Visibility, sharing, federation, global knowledge
  - Semantic search, validation feedback, cross-debate learning
  - SLO alerting with Prometheus metrics
  - Phase A2: Contradiction detection, confidence decay, RBAC governance, analytics, knowledge extraction
- Pulse (trending topics) - STABLE (1,000+ tests passing)
  - HackerNews, Reddit, Twitter ingestors
  - Quality filtering, freshness scoring, source weighting
  - Integration with debate context and prompt building
- Evidence collection - STABLE with KM integration
- Unified Memory Gateway - STABLE (150 tests, all opt-in via `enable_unified_memory`)
  - MemoryGateway: fan-out query across ContinuumMemory, KM, Supermemory, claude-mem
  - RetentionGate: Titans/MIRAS surprise-driven retain/demote/forget/consolidate
  - CrossSystemDedupEngine: SHA-256 exact + Jaccard near-duplicate detection
  - RLMMemoryNavigator: REPL helpers for programmatic cross-system exploration
  - ClaudeMemAdapter: KM adapter wrapping claude-mem MCP connector

See `docs/STATUS.md` for 74+ detailed feature statuses.

## Key Documentation

| Document | Purpose |
|----------|---------|
| `docs/EXTENDED_README.md` | Comprehensive technical reference (five pillars, all features) |
| `docs/COMMERCIAL_OVERVIEW.md` | Commercial positioning and readiness assessment |
| `docs/WHY_ARAGORA.md` | "Why Aragora" positioning and competitive differentiation |
| `docs/enterprise/ENTERPRISE_FEATURES.md` | Enterprise capabilities reference |
| `docs/FEATURE_DISCOVERY.md` | Complete feature catalog (180+ features) |
| `docs/STATUS.md` | Detailed feature implementation status |
| `docs/api/API_REFERENCE.md` | REST API documentation |
| `docs/SDK_GUIDE.md` | Python and TypeScript SDK usage guide |
| `docs/compliance/EU_AI_ACT_GUIDE.md` | EU AI Act compliance guide and artifact generation |
| `docs/verticals/HEALTHCARE.md` | Healthcare vertical guide (HIPAA, FHIR, clinical decisions) |
| `docs/verticals/FINANCIAL.md` | Financial services vertical guide (risk, SOX, audit) |
| `docs/verticals/LEGAL.md` | Legal vertical guide (contracts, due diligence, litigation) |
| `docs/resilience/RESILIENCE_PATTERNS.md` | Circuit breakers, retry, timeout, health monitoring |
| `docs/CLI_REFERENCE.md` | Complete reference for all 35 CLI commands with examples |
| `docs/FEATURE_GAP_LIST.md` | Feature backlog: planned, partial, and scaffolded features by priority |
| `docs/guides/PIPELINE_GUIDE.md` | 4-stage Idea-to-Execution pipeline usage guide |
| `docs/guides/MODES_GUIDE.md` | Operational modes guide (standard + advanced: RedTeam, DeepAudit, Probing) |
| `docs/guides/RLM_INTEGRATION.md` | Recursive Language Models integration guide |
| `docs/guides/COORDINATION_SYSTEM.md` | Cross-workspace coordination and federated execution guide |
