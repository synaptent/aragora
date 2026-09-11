# Aragora Intended Architecture Charter

Status: DRAFT v0.6 — pending operator ratification; ARCH-015 is binding under the #8851 item-3 exception
Date: 2026-07-06 | Owner: operator (armand)
Enforcement targets: merge-gate reviewers, all AI fleets (Claude, Codex, Factory droids, launchd daemons), humans

Provenance: authored by the conductor via orchestrated multi-agent review on 2026-07-06
(draft v0.1 2026-07-05 from 8 evidence-grounded cluster maps; v0.2 incorporates an adversarial
critic pass — see Amendment log, §6). Operator-commissioned. Amendments require an
operator-approved PR touching this file.

---

## Binding status (read this first)

**Ratification condition (machine-checkable):** this charter is RATIFIED **iff** this file
exists at `docs/architecture/INTENDED_ARCHITECTURE.md` on `main` with a first-section header
line `Status: RATIFIED vN.N`, landed via an operator-approved PR. Any other copy — scratchpad,
branch, gist, PR body — is a proposal, not a charter.

**While Status is DRAFT, the ONLY binding entries are those backed by a pre-existing
operator-approved artifact:**

| Entry | Binding because |
|---|---|
| CHR-P4A-001..004 | operator-approved `P4A_LAYERING_DISPOSITION.md` / `P4A_EVENTS_QUEUE_INVERSION.md` + merged PRs #8712 #8717 #8719 #8890 #8909 |
| CHR-X-007 (no new `aragora.metrics` imports) | the shim's own published deprecation contract (`aragora/metrics/__init__.py` DeprecationWarning, "for one release") |
| ARCH-015 (`aragora/queue`) | operator authorization on 2026-08-18 unparked #8851 acceptance item 3 for this disposition only; [`QUEUE_ADOPTION_DISPOSITION.md`](QUEUE_ADOPTION_DISPOSITION.md) records the live boundary |

Everything else in this document is PROPOSED and becomes binding only at ratification.
This file lives in the repo precisely so that diff-grounded reviewers and quarantining
adjudicators can see it; a charter that lives in a scratchpad binds nobody.

---

## Placement protocol (the 2-minute version for a fresh agent)

Before you add a module, package, export, or cross-package import edge:

1. **Identify the concern** your code implements. Look it up in the Authority Table (§2)
   by ARCH-id. Code for a chartered concern may be added **only** to its authority module.
2. **Grep your target path and symbols** against `docs/architecture/charters.yaml`
   (the machine encoding of §3). If the path/symbol appears in an entry with state
   `REMOVED` — stop; do not re-add; cite the CHR id. State `PENDING` or `EXPIRING` —
   no new importers/callers; existing ones keep working. While this charter's Status is
   DRAFT, that freeze is OPERATIVE only for the entries listed in the Binding status
   block; for all other entries it is advisory guidance — flag, don't block.
   State `EXCLUSION` — never build it.
3. **Package not in §2 or Appendix A as mapped?** It is **UNMAPPED**: frozen for
   architectural growth (§2d). Fix bugs, don't extend its surface, don't import it anew.
4. **New top-level `aragora/<pkg>` or new concern?** That requires an operator-approved
   amendment to this charter **in the same PR** (R5).
5. **Entry says PARKED?** Stop and surface to the operator with the entry ID (R4).

On any structural conflict, once RATIFIED **this charter wins over every other file in
`docs/architecture/`**; while DRAFT, see the Binding status block (§0 precedence).

---

## 0. Ratification legend, precedence, and entry states

Legend used throughout (referenced from §2 and §3):

- **RATIFIED** — operator-approved charter exists (P4a docs, merged downshift PRs). Binding now.
- **PROPOSED** — this draft's disposition, traceable to cluster-map evidence. Binding only
  after operator/#8851 sign-off (see Binding status block).
- **PARKED** — deliberately undecided; has a named owner and a calendar review date.
  Do not act either way.

Registry entry states (§3): `REMOVED` (edge is gone, do not re-add) | `EXPIRING` (temporary
compat exception with an ISO deadline or concrete triggering PR/issue) | `PENDING` (removal or
absorption chartered, not yet executed — **no new importers/callers**; applies equally to
EXPIRING per R3) | `EXCLUSION` (never wire this) | `PARKED` (frozen both ways).
While this charter's Status is DRAFT, the PENDING/EXPIRING no-new-importers/callers rule is
OPERATIVE only for the entries listed in the Binding status block; for all other entries it
is advisory guidance — flag, don't block.

**ID permanence rule:** ARCH-ids and CHR-ids are permanent. Never reused, never renumbered.
Entries are only ever state-transitioned (with date + PR recorded in the entry).

**Evidence snapshot caveat:** all importer counts and `file:line` anchors in this charter
(and `charters.yaml`) are a snapshot as of 2026-07-06 — verify by re-running the stated grep
before citing; a stale anchor is not evidence.

**Precedence:** once RATIFIED, this charter supersedes every other file under
`docs/architecture/` (ARCHITECTURE.md, ARCHITECTURE_THREE_LAYER.md, SYSTEM_DIAGRAM.md,
system-overview.md, GATEWAY_ARCHITECTURE.md, and the rest) on any structural or
architectural-intent conflict; while Status is DRAFT, supersession extends only as far as
the Binding status block. Those files
remain useful as description; they are not authority. CHR-X-025 charters their SUPERSEDED-BY
stamping. On numeric conflict, `docs/METRICS.md` wins (R7). On liveness/feature-status
conflict with CLAUDE.md's tables, this charter's §1 status marks and §3 states win pending
the approved CLAUDE.md edit (R7b).

---

## 1. Layer Model — the Decision Integrity Platform in six layers

Product story: *adversarial multi-model vetting that produces verifiable decision receipts,
delivered to any channel, on a platform that also develops itself.* Each layer names its
AUTHORITY modules; anything else implementing that layer's concern is a duplicate (see §2).

```
 L6  INTENT          docs/METRICS.md, CLAUDE.md/AGENTS.md/AGENT_OPERATING_CONTRACT,
     (charters)      THIS CHARTER + removals registry (§3) + charters.yaml
 ───────────────────────────────────────────────────────────────────────────────
 L5  FLEET           nomic/dev_coordination (leases) → swarm (boss/merge daemons)
     (dev-side only) → worktree/ → settle_tier4_pr + review-queue transports;
                      agent_bridge, consult_claude/fable_goal_cycle, harnesses
 ───────────────────────────────────────────────────────────────────────────────
 L4  EDGE            IN: connectors/ (Gmail, GitHub, chat, web)
     (in/out)        OUT: channels/ (transport) + notifications/service (policy)
                      + webhooks/retry_queue; mcp/ (agent tool surface); broadcast/
 ───────────────────────────────────────────────────────────────────────────────
 L3  PRODUCT         server/unified_server + handler_registry + stream/;
     SURFACE         aragora CLI; sdk/python + sdk/typescript (parity-gated);
                      pipeline/ (idea→goal→workflow→execution) + workflow/ (DAG lib)
                      + queue/ (durable jobs)
 ───────────────────────────────────────────────────────────────────────────────
 L2  KNOWLEDGE       knowledge/mound (durable org knowledge + receipt sink);
     & MEMORY        memory/continuum+consensus (session memory); rlm/ (context
                      navigation); evidence/ + documents/ (ingestion); insights/
 ───────────────────────────────────────────────────────────────────────────────
 L1  DECISION CORE   debate/ (Arena — the ONLY deliberation engine); agents/
     (the product)   (heterogeneous roster); reasoning/ (claims/provenance base);
                      verification/, explainability/, evaluation/, ranking/;
                      gauntlet/ (the ONLY receipt emitter; receipts/ is a facade
                      over it — see ARCH-002); aragora-verify PyPI pkg (the ONLY
                      external verifier)
 ───────────────────────────────────────────────────────────────────────────────
 L0  PLATFORM        storage/ (persistence), rbac/+auth/ (authn/z), observability/
     SUBSTRATE       (P4a single authority), resilience/, billing/, compliance/,
                      privacy/, security/, backup/, scheduler/ (ops cron jobs)
```

Five-minute read for an outside engineering manager: a question enters at L3/L4, the L1 core
debates it across heterogeneous models, grounds it in L2 knowledge, and emits a
cryptographically verifiable **decision receipt** (gauntlet → ODR schema → `aragora-verify`).
L0 makes that auditable and access-controlled. L5 is the same machinery pointed at the repo
itself: fleets take **work leases**, ship PRs through a receipt-gated merge quorum, and settle.
L6 is where intent lives so reviewers can cite it.

**L5 packaging note:** fleet machinery (nomic/, swarm/, worktree/, harnesses/) currently ships
inside the `aragora` package namespace and therefore inside the customer wheel. "Dev-side only"
is intent the artifact does not yet enforce. Whether fleet code is excluded from the customer
distribution via the packaging manifest is a chartered open decision: CHR-X-039 (PARKED,
owner: operator, review by 2026-09-01).

### Layer status (honest marks — do not over-claim)

| Layer | Status | Notes |
|---|---|---|
| L1 Decision core | **core/stable**, under-consolidation | debate/ ≈230 modules, 14 `orchestrator_*.py` + 8 `arena_*.py` shards; **three** receipt class lineages pending reconciliation (gauntlet, export/decision_receipt "Legacy", receipts/ lane+operational — see ARCH-002, CHR-X-001/037) |
| L2 Knowledge/memory | **core/stable**, under-consolidation | mound is live hub (159 external importers); 4 embedding stacks; unified-memory gateway flag-off limbo |
| L3 Product surface | **core/stable** | 327 handler modules register clean; any handler module not registered is **dormant** per R6 (see ARCH-023 disposition); sdk-parity CI-gated; second FastAPI stack PARKED (CHR-X-011) |
| L4 Edge | **under-consolidation** | Slack exists in ~7 stacks; two live Telegram clients; two live notification services |
| L0 Platform substrate | **core/stable** with prod-dormant lanes | Postgres/Redis-HA/multi-tenant paths are **code-live, prod-dormant** (prod = sqlite + `ARAGORA_SINGLE_INSTANCE=true`) — never cite them as exercised |
| L5 Fleet machinery | **adopted-machinery** | live via launchd (swarm-boss-loop, ctl-merge-executor, worktree-maintainer); `check_work_lease.py` still fail-open (v0); packaging ruling parked (CHR-X-039) |
| L6 Intent | **under-consolidation** | METRICS.md drift-gated; `scripts/ci/check_import_contracts.py` is UNWIRED (no workflow/Makefile caller) — wiring it is a ratification precondition (R8) |

---

## 2. Authority Table — one authority per concern

Rules of the table: the **single authority** column is the only module where code for that
concern may be added. "Duplicates found" are evidence-grounded, not exhaustive. Dispositions:
**adopt** (keep as authority) / **absorb** (fold into authority, then delete) / **retire**
(delete after registry entry) / **park** (frozen, owner + review date). Ratification per §0
legend. **Every row has a permanent ARCH-id; every non-adopt disposition points at a §3 CHR-id**
— reviewers and gates cite rows by these ids, never by prose.

### 2a. Decision core & knowledge

| ID | Concern | Single authority | Duplicates found | Disposition | Evidence |
|---|---|---|---|---|---|
| ARCH-001 | Deliberation orchestration | `aragora/debate` (Arena) | workflow/coordination/queue must not grow rival debate loops; debate-internal `graph_orchestrator`/`molecule_orchestrator` overlap pipeline staged execution | adopt; consolidation budget on debate/ (PROPOSED) | 194 non-test importers; entrypoints nomic_loop, triage_runner, server handlers |
| ARCH-002 | Receipt emission | `aragora/gauntlet` | **Three receipt class lineages exist:** (1) gauntlet's DecisionReceipt (authority); (2) `aragora/export/decision_receipt.py`, re-exported by `aragora/receipts/__init__.py:9` as `LegacyDecisionReceipt`; (3) `aragora/receipts/` itself emits lane/operational receipts (`emit_lane_receipt`, `emit_operational_receipt`). pipeline `receipt_*` + nomic `dev_receipts` are downstream consumers/fleet mirrors, not emitters | adopt gauntlet (RATIFIED by product story); `receipts/` becomes a **sanctioned facade over gauntlet** — re-exports only, no independent receipt classes; LegacyDecisionReceipt absorbed-or-retired per RECEIPT_LINEAGE_RECONCILIATION (PROPOSED → CHR-X-037); fleet lane/operational receipts are the L5 analogue and must be schema-reconciled in the same spec | 83 gauntlet importers; receipts/__init__.py:9,12-13 |
| ARCH-003 | External receipt verification | `aragora-verify` PyPI pkg (ODR schema) | `aragora/gauntlet/odr_verify.py` — self-documented "no shipped CLI/route calls it" | absorb-or-retire odr_verify per `docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md` (PROPOSED → CHR-X-001) | odr_verify.py docstring; aragora-verify v0.1.1 in-repo |
| ARCH-004 | Quality scoring / eval metrics | `aragora/evaluation` | `aragora/metrics/` — 7-file deprecated re-export shim "for one release" | retire shim on schedule; **new imports of `aragora.metrics` forbidden now** (RATIFIED by shim's own contract → CHR-X-007) | metrics/__init__.py DeprecationWarning |
| ARCH-005 | Claims/evidence base layer | `aragora/reasoning` | — (aragora/evidence imports reasoning; correct layering) | adopt; reasoning is the base, evidence/ the ingestion front-end | 124 importers; evidence/collector.py imports reasoning |
| ARCH-006 | Agent calibration | `aragora/ranking` (calibration_engine et al.) | `aragora/agents/calibration.py` | absorb into ranking (PROPOSED → CHR-X-026) | dual calibration paths risk team-selection schema drift |
| ARCH-007 | Durable knowledge store | `aragora/knowledge/mound` | knowledge top-level legacy surface, **two classes**: (a) `fact_extractor.py`, `migration.py`, `mound_store.py`, `unified/unified_store.py` — verified 0 external importers; (b) `vector_store.py` and `search/` — **live mound-internal importers** (mound/core.py:306 imports KnowledgeVectorStore/KnowledgeVectorConfig — live Weaviate connect path; knowledge/embeddings.py:14 and mound/vector_abstraction/memory.py:27 import search/bm25) | retire class (a) (PROPOSED → CHR-X-002); **absorb** class (b) into mound — re-home the modules or re-point the imports first, delete top-level only after (PROPOSED → CHR-X-038) | rg counts: mound 159 external files; class-(a) 0 importers each; class-(b) importers cited inline |
| ARCH-008 | Debate-session memory | `aragora/memory` (continuum, consensus) | Unified Memory Gateway (gateway/retention_gate/dedup/titans) flag-off by default | park gateway pending explicit adopt-or-retire alongside #8851 (PARKED → CHR-X-020) | orchestrator_config.py:421 `enable_unified_memory=False` |
| ARCH-009 | Outcome→confidence feedback | `aragora/debate/km_outcome_bridge.py` | `memory/outcome_bridge.py` (test-only), `openclaw_bridge.py`, `claude_mem_km_sync.py` (test-only) | retire test-only bridges (PROPOSED → CHR-X-003) | rg: only tests import them |
| ARCH-010 | Embeddings | `aragora/core` embeddings service | `knowledge/embeddings.py`, `memory/embeddings.py`, `ml/embeddings.py` | absorb: demote to provider plugins behind core (PROPOSED → CHR-X-027; coordinate with CHR-X-038 — knowledge/embeddings imports search/bm25) | 4 stacks; mixed 256/1536-dim rows already caused a prod KM crash |
| ARCH-011 | Context navigation | `aragora/rlm` | — | adopt (product + fleet shared) | 17 debate files, nomic/context_builder, `aragora rlm` CLI |

### 2b. Orchestration & fleet

| ID | Concern | Single authority | Duplicates found | Disposition | Evidence |
|---|---|---|---|---|---|
| ARCH-012 | Work ownership / leases | `aragora/nomic/dev_coordination` (SQLite at `<git-common-dir>/aragora-agent-state/dev_coordination.db`; preflight `scripts/check_work_lease.py`) | `coordination/claims.py`; `control_plane/registry.py` heartbeats; `worktree/fleet.py` FleetCoordinationStore | adopt (RATIFIED by #8851 mandate); worktree/fleet stays a **mirror, never a second truth**; coordination/claims.py **absorbs into `aragora/swarm`**, not retired (ruled 2026-07-06 → CHR-X-012) | check_work_lease.py docstring cites #8851 "single ownership truth"; operator ruling 2026-07-06 (#8851), salvage-audited |
| ARCH-013 | Bead/convoy stores | `aragora/nomic/stores` | `aragora/workspace` (delegating wrapper, 11 live importers), Gastown dialect (refinery/rig) | finish convergence; retire Gastown dialect (PROPOSED → CHR-X-028); **absorb workspace/ into nomic/stores, sequenced AFTER CHR-X-028** (ruled 2026-07-06 → CHR-X-043) | workspace/bead.py imports NomicBeadStore; operator ruling 2026-07-06 (#8851), salvage-audited |
| ARCH-014 | Fleet task scheduling | swarm boss loop + dev_coordination dispatch | `control_plane/scheduler.py` (Redis-only; returns None **with a warning log** in prod — invisible unless logs are inspected), `coordination/task_dispatcher.py`, `fabric/scheduler.py`, `workflow/scheduler.py`, `tasks/router.py` | per-component per #8851 ruling 2026-07-06: retire coordination dispatch (CHR-X-012), fabric (CHR-X-013), tasks/ (CHR-X-014), control_plane auto_scaling/agent_federation/regional_sync (CHR-X-015); **PARK control_plane scheduler.py + registry.py remainder** (CHR-X-040); **RELOCATE blockchain_identity** (CHR-X-041); retire workflow/scheduler.py (CHR-X-042); API deprecation path required for control_plane handlers | startup/control_plane.py:55-58 warn-then-None; prod is sqlite single-instance. Complete scheduler inventory: these five + ARCH-022's ops-cron scheduler (a distinct, sanctioned concern); operator ruling 2026-07-06 (#8851), salvage-audited |
| ARCH-015 | Durable server-side jobs | `aragora/queue` (public job contract + Redis Streams transport) | `aragora/storage/job_queue_store.py` is a live backend split used directly by gauntlet, routing, transcription, and test-fixer workers; control_plane scheduler is covered by ARCH-014 | **ADOPT as binding authority** (#8851 item 3, activated 2026-08-18). Existing direct storage-backend consumers are frozen; new durable-job callers enter through `aragora.queue`, and the backend split converges behind that API rather than growing as a peer authority | `scripts/queue_worker.py`; `server/handlers/queue.py`; bot producers; `server/startup/workers.py`; [`QUEUE_ADOPTION_DISPOSITION.md`](QUEUE_ADOPTION_DISPOSITION.md) |
| ARCH-016 | Product DAG workflows | `aragora/workflow` as **library** consumed by pipeline | debate-internal staged execution (see ARCH-001); `workflow/scheduler.py` (duplicate of scheduling concern) | **ADOPT as authority confirmed** (ruled 2026-07-06; DAG library, 36 external importers, engine live in pipeline/CLI/canvas/MCP/handlers); must not grow a rival scheduler or debate loop; retire workflow/scheduler.py (ruled → CHR-X-042) | WorkflowEngine instantiated by pipeline/executor, canvas, mcp, CLI; operator ruling 2026-07-06 (#8851), salvage-audited |
| ARCH-017 | Idea→execution pipeline | `aragora/pipeline` | `aragora/goals/` (single file, is pipeline stage 2); `aragora/autonomous/` (self-described "Nomic Loop Enhancement") | **absorb goals/ into pipeline confirmed** (ruled 2026-07-06): extractor.py becomes the pipeline stage-2 module, repoint the 8 live importers; fold autonomous/ into nomic (PROPOSED → CHR-X-029) | goals/ = extractor.py only; autonomous importers = handlers + one pipeline util; operator ruling 2026-07-06 (#8851), salvage-audited |
| ARCH-018 | Agent process spawning | `aragora/harnesses` | `swarm/worker_launcher.py` spawns codex/Claude directly (0 harness imports); agent_bridge transports | absorb: worker_launcher becomes a harnesses consumer (PROPOSED → CHR-X-030) | worker_launcher.py:613,685 direct spawn |
| ARCH-019 | PR settlement | `scripts/settle_tier4_pr.py` + `aragora/cli` review-queue transports | settle_one_pr, tier4_merge_train, auto_merge_quorum_green, settlement_followup (wrapper sprawl) | absorb wrappers, then retire (PROPOSED → CHR-X-008) | settle_tier4_pr imported by 8+ scripts/modules; ~12 fix commits |
| ARCH-020 | Conductor / goal loop | `scripts/fable_goal_cycle.py` + `scripts/consult_claude.py` | goal_conductor.py (its line `scripts/goal_conductor.py:310` hardcodes the `scripts/nomic_loop.py` path), lane_conductor, overnight_conductor; nomic_loop/self_develop/nomic_staged = legacy **manual** entrypoints | adopt authority; retire old conductors; relabel nomic_loop trio "legacy manual" in CLAUDE.md (PROPOSED → CHR-X-009) | launchd runs swarm boss-loop, nothing runs nomic_loop; fable_goal_cycle merged #8835 |
| ARCH-021 | Worktree lifecycle | `aragora/worktree` (maintainer daemon; `scripts/codex_worktree_autopilot.py` is its implementation detail) | `coordination/worktree_manager.py` (wraps it) | adopt; retire coordination wrapper with coordination/ core (PROPOSED → CHR-X-012) | launchd com.aragora.codex-worktree-maintainer; autopilot.py:49 wrapper |
| ARCH-022 | Scheduled ops jobs (audits, access reviews, DR drills, token refresh, settlement review) | `aragora/scheduler` | `aragora/schedulers/` — deprecated shim package | adopt; retire shim (PROPOSED → CHR-X-031). Ops-cron is a distinct concern from fleet work-dispatch (ARCH-014) and is NOT covered by exclusion CHR-E-003 | package present with launched jobs; shim self-describes deprecated |

### 2c. Surface, edge, substrate

| ID | Concern | Single authority | Duplicates found | Disposition | Evidence |
|---|---|---|---|---|---|
| ARCH-023 | HTTP/WS ingress | `server/unified_server` + `handler_registry` + the 4 instantiated stream servers | `server/fastapi` /api/v2 stack (default-off, no deploy/CI reference); dead `server/extensions.py` init path; unregistered handler modules | park FastAPI with hard deadline (PARKED → CHR-X-011); delete-or-wire extensions init (PROPOSED → CHR-X-016); **blanket rule: any handler module not registered in handler_registry is dormant per R6** — it may not be cited as a feature and needs no removal entry to be treated as dead; triage list is Appendix-A follow-up | unified_server.py:1313 flag; rg: init_extensions has zero callers; 327 modules register vs "700+" advertised |
| ARCH-024 | Python client | `sdk/python/aragora_sdk` (parity-gated) | `aragora/client/` (37 resources, ungated, kept alive only by CLI) | absorb: CLI migrates to the SDK, or client comes under the parity gate — never two ungated (PROPOSED → CHR-X-033) | check_sdk_parity.py:280 hardcodes sdk/python only |
| ARCH-025 | Inbound connectors | `aragora/connectors` | `integrations/{slack,telegram,teams,whatsapp}` platform clients (both Telegram clients LIVE today) | absorb integrations clients into connectors/chat via staged migration (PROPOSED → CHR-X-032); vertical catalog (~132 unreferenced files) tiered "catalog: dynamic-load only, no direct import" (PARKED → CHR-X-023) | runtime_registry.py:424 importlib load; both telegram stacks wired |
| ARCH-026 | Outbound delivery | `aragora/channels` (transport/rendering) + `aragora/notifications/service.py` (policy/routing) | `control_plane/notifications.py` (live, split-brain), `bots/slack_bot.py`+`teams_bot.py` (0 importers), integrations dispatcher | absorb control_plane notifications (P4a downshift pattern, PROPOSED → CHR-X-015 keep-list note); retire dead bots (PROPOSED → CHR-X-004) | dual live services confirmed by importer rg; bots rg = handlers/bots/{discord,zoom} only |
| ARCH-027 | Retry / dead-letter | `aragora/webhooks/retry_queue.py` | `notifications/retry_queue.py`, `events/dead_letter_queue.py`, `integrations/webhooks.py` dispatcher | absorb onto one transport (PROPOSED → CHR-X-034) | 4 implementations, all reachable |
| ARCH-028 | Agent-facing tools | `aragora/mcp` | — | adopt (product + fleet shared) | CLI delegated.py:221; harnesses/claude_code.py:570 |
| ARCH-029 | Observability | `aragora/observability` | `aragora/telemetry/` (0 importers, shim), `aragora/monitoring/` (1 importer), any server-local metrics/tracing home | adopt (**RATIFIED** — P4a); retire shims (PROPOSED → CHR-X-005); server re-adds are charter violations (CHR-P4A-001..003) | P4A_LAYERING_DISPOSITION.md; PRs #8712/#8717/#8719 |
| ARCH-030 | Persistence API | `aragora/storage` | `aragora/db/` (1 importer, near-identical docstring); `aragora/persistence/` (nomic-loop-serving) | absorb db/ (PROPOSED → CHR-X-019); park persistence/ adjudication (PARKED → CHR-X-022) | db sole importer = control_plane/health handler |
| ARCH-031 | Schema migrations | **interim authority: `aragora/persistence/migrations`** — what `auto_migrations` actually runs today; consolidation of the three systems is PARKED → CHR-X-021 | `aragora/migrations` (Postgres), `storage/migrations`, `db/migrate.py` | interim adopt persistence.migrations (its default stands); consolidation parked with owner + date (CHR-X-021). An authority row must always point at code that exists — "to be named" is not an authority | auto_migrations.py defaults to persistence.migrations.runner |
| ARCH-032 | Circuit breaking / retry | `aragora/resilience` | `circuit_breaker_v2.py` (0 importers, self-described shim); top-level `resilience_patterns.py`/`resilience_config.py` | retire v2 shim; absorb top-level files (PROPOSED → CHR-X-006) | simple_circuit_breaker.py docstring; rg 0 external v2 importers |
| ARCH-033 | AuthN/AuthZ | `aragora/rbac` + `aragora/auth` | `security/token_rotation.py` vs `auth/token_rotation.py` | adopt; absorb token_rotation duplication (PROPOSED → CHR-X-035); rbac = Tier 3-4 blast radius, no autonomous refactor | rbac 353 importers |
| ARCH-034 | Key rotation | **interim authority: the existing per-provider rotators as wired by `aragora/server/startup/security.py`** (the code that exists and runs); end-state: one table-driven registry in `aragora/security` | 8 per-provider `*_rotator.py` boilerplate files, each with exactly 1 importer | interim adopt current rotators; absorb into one registry when built (PROPOSED → CHR-X-036). No new per-provider rotator files meanwhile | each rotator's sole importer = startup/security.py |
| ARCH-035 | Numeric truth | `docs/METRICS.md` (generated, drift-gated) | hand-written counts anywhere else | adopt (RATIFIED — "this doc wins") | metrics-drift.yml weekly + per-PR |
| ARCH-036 | Removal intent | **§3 of this charter + `charters.yaml`** | PR threads, stale plans, dormant ADRs | adopt — the #8905 fix | issue #8905 acceptance criteria |

### 2d. Default state for everything else: UNMAPPED

The repo has 144 top-level `aragora/*` packages; §2 dispositions roughly half. **Any package
without a MAPPED row in Appendix A is UNMAPPED, and UNMAPPED is a state, not a gap:**

- **Frozen for architectural growth**: no new cross-package importers of it, no new exports
  consumed from other packages, no new subpackages, and it must not grow an implementation
  of any chartered concern (§2).
- Bug fixes, existing-caller maintenance, and test work continue normally.
- Escaping UNMAPPED requires triage into a layer via charter amendment (R5) — one table row,
  operator-approved.

Appendix A is the generated one-line-per-package triage table (layer + status per package).
Known UNMAPPED packages the v0.1 draft never mentioned include: `receipts` (now mapped,
ARCH-002), `scheduler`/`schedulers` (now mapped, ARCH-022), `epistemic`, `prediction`,
`markets`, `missions`, `ralph`, `gti`, `factory`, `brief_engine`, `advocates`,
`heterogeneity`, and ~60 more — see Appendix A for the full inventory.

---

## 3. Chartered Removals & Exclusions Registry

Machine-citable. Reviewers and gates cite entries by ID. **The normative machine encoding of
this section is `docs/architecture/charters.yaml`, committed alongside this file and updated
in the same PR as any §3 change** — every REMOVED/PENDING/EXPIRING entry carries explicit
`paths` (exact repo-relative paths or well-formed globs) and `symbols`
(`module:export_name`) fields there. A PR that re-adds anything listed as **REMOVED** must
receive a grounded finding citing the entry (per #8905 acceptance criteria) — "backward
compatibility" is NOT a valid counter-argument to a registry entry.

### 3a. Executed (RATIFIED — operator-approved charters, merged PRs)

| ID | State | What | Why | Date | PR/Doc |
|---|---|---|---|---|---|
| CHR-P4A-001 | REMOVED | Server-local metrics/prometheus surface in `aragora/server` (paths/symbols in charters.yaml: `aragora/server/metrics.py` shim, `aragora.observability.server_metrics` is home) | `aragora/observability` is single metrics authority | 2026-06 | #8712, P4A_LAYERING_DISPOSITION.md |
| CHR-P4A-002 | REMOVED | Server tracing/correlation middleware as a server-owned surface (`aragora/server/middleware/tracing.py` shim; home `aragora.observability.middleware.tracing`) | downshifted to observability | 2026-06 | #8717 |
| CHR-P4A-003 | REMOVED | Server `http_client_pool` as a server-owned surface (`aragora/server/http_client_pool.py` shim; home `aragora.observability.http_client_pool`) | downshifted to observability | 2026-06/07 | #8719 |
| CHR-P4A-004 | REMOVED | `create_default_executor` re-export on `aragora.queue`. History: removed by P4a Q1 (#8890); **re-added charter-blind by merged PR #8893** — the first specimen of the charter-blind approval class (#8905); **re-removed, executed, by #8909 (merged 2026-07-05)**. Standing rule: `aragora.queue` must not re-export `create_default_executor`; its home is `aragora/debate/queue_executor.py` (queue stays domain-free). Any re-add is a charter violation citing this entry | queue/events inversion; blast-radius containment | removed #8890, re-added 2026-07-05 #8893, re-removed 2026-07-05 #8909 | #8890, #8893, #8905, #8909, P4A_EVENTS_QUEUE_INVERSION.md |

### 3b. Chartered by this draft (PROPOSED — no new dependents at ratification; execute after ratification/#8851)

| ID | State | What (paths/symbols normative in charters.yaml) | Why | Evidence anchor |
|---|---|---|---|---|
| CHR-X-001 | PENDING | `aragora/gauntlet/odr_verify.py` (second receipt-**verifier** lineage) | `aragora-verify` package is the sole external verifier; two lineages can silently diverge on canonicalization and destroy the receipt claim | odr_verify.py docstring ("no shipped CLI/route calls it"); docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md |
| CHR-X-002 | PENDING | knowledge legacy surface, zero-importer class only: `knowledge/fact_extractor.py`, `knowledge/migration.py`, `knowledge/mound_store.py`, `knowledge/unified/unified_store.py` | superseded by `knowledge/mound`; verified 0 external importers each. (`vector_store.py` and `search/` are NOT here — they have live internal importers; see CHR-X-038) | cluster-map rg counts, re-verified 2026-07-06 |
| CHR-X-003 | PENDING | `memory/outcome_bridge.py`, `memory/openclaw_bridge.py`, `memory/claude_mem_km_sync.py` | test-only; live edge is `debate/km_outcome_bridge.py` | rg: importers are tests only |
| CHR-X-004 | PENDING | `bots/slack_bot.py`, `bots/teams_bot.py` | 0 importers; Slack already served by connectors/chat + handlers + channels dock | rg 'aragora.bots' → discord/zoom handlers only |
| CHR-X-005 | PENDING | `aragora/telemetry/` (0 importers), `aragora/monitoring/` (1 importer) re-export shims | observability is P4a single authority | shim docstrings |
| CHR-X-006 | PENDING | `resilience/circuit_breaker_v2.py` shim; top-level `resilience_patterns.py`/`resilience_config.py` | 0 external importers / package-internal only | simple_circuit_breaker.py docstring |
| CHR-X-007 | PENDING | `aragora/metrics/` shim package (all 7 files) | promised deletion "for one release"; **new imports forbidden effective now** (binding in DRAFT — see Binding status) | metrics/__init__.py DeprecationWarning |
| CHR-X-008 | PENDING | settlement wrappers `scripts/settle_one_pr.py`, `scripts/tier4_merge_train.py`, `scripts/auto_merge_quorum_green.py` (after absorption into settle_tier4_pr/settle_pr) | one settlement path; wrapper sprawl is where fixes get lost | fleet-ops map |
| CHR-X-009 | PENDING | conductor scripts `scripts/goal_conductor.py`, `scripts/lane_conductor.py`, `scripts/overnight_conductor.py` | superseded by fable_goal_cycle + consult_claude; goal_conductor still hardcodes legacy nomic_loop | `scripts/goal_conductor.py:310` — hardcodes the `scripts/nomic_loop.py` path |
| CHR-X-010 | PENDING | zero-importer decision-core modules: `agents/email_agents.py`, `agents/feature_agent.py`, `agents/power_sampling_mixin.py`, `ranking/muse_calibration.py` (email_agents/power_sampling_mixin reachable only via lazy `__init__` re-exports; email_agents' only other mention is a docstring at services/email_prioritization.py:920; debate's PowerSamplingConfig is a separate class, not the mixin). **Explicitly NOT chartered** (real callers verified): `ranking/snapshot.py` (elo.py:96, elo_leaderboard.py:18, elo_matchmaking.py:25), `ranking/redteam.py` (elo.py:90, instantiated elo.py:300,329), `verification/sandbox.py` (formal.py:559 Lean execution, verification/__init__.py:49). `verification/proofs.py` is near-dormant but not chartered here | feature-count inflation; no product or fleet caller for the four listed | zero-importer greps re-verified against critic pass 2026-07-06 |
| CHR-X-012 | PENDING (ruled 2026-07-06) | `aragora/coordination/` core, amended salvage list per #8851 ruling: **ABSORB** `claims.py` (ClaimManager: never-block advisory claims with contested_by reporting) and `registry.py` (SessionRegistry: PID-liveness tri-state discovery with auto-reap) **into `aragora/swarm`** — live consumer `aragora/swarm/session_coordinator.py:20` + `aragora swarm` CLI; existing salvage stands: GitReconciler→worktree/, bus→events/ (session_coordinator also imports CoordinationBus), directives→swarm/; **RETIRE** `task_dispatcher.py`, `health_watchdog.py`, `worktree_manager.py` (sole consumer: nomic/self_improve.py's untested optional path with built-in BranchCoordinator fallback — trim that import block as part of retirement). **GUARD: `cross_workspace.py` and `resolver.py` are NOT covered by this ruling** — they are the package's most-imported modules; **package/`__init__` deletion is BLOCKED** until they receive their own disposition | duplicate of dev_coordination + control_plane concepts; no daemon drives the retired core | orchestration map importer audit; operator ruling 2026-07-06 (#8851), salvage-audited |
| CHR-X-013 | PENDING (per #8851 ruling) | `aragora/fabric/` (flip `ARAGORA_ENABLE_AGENT_FABRIC` default→false first — server import path depends on it) | third agent-pool abstraction; no script/daemon/CI runs a fabric pool | extensions.py:39; instantiation sites only |
| CHR-X-014 | PENDING (ruled 2026-07-06: RETIRE now) | `aragora/tasks/` — inline `router.py` (incl. `VALID_TASK_TYPES`) into `aragora/server/handlers/tasks/execution.py`; **REQUIRED: port the 18 passing tests from `tests/tasks/test_router.py` to the inlined location**; SDK `/api/v2/tasks` unaffected (handler-backed) | one implementation module, one caller (execution.py:39) | rg 'from aragora.tasks'; operator ruling 2026-07-06 (#8851), salvage-audited |
| CHR-X-015 | PENDING (ruled 2026-07-06: split per-component) | narrowed to the RETIRE set: `control_plane/auto_scaling.py` (recommendation engine, scale callbacks default None — never provisions anything; no exports, no callers), `control_plane/agent_federation.py` (discovery/health scaffold; `remote_endpoint` never read, no RPC layer exists; path corrected from stale `federation.py`), `control_plane/regional_sync.py` (zero active instantiation; region_router works without it). `scheduler.py` + `registry.py` remainder → **PARKED CHR-X-040**; `registry.py` health/liveness surface consumed by `aragora/debate/team_selector.py` (optional health filtering, graceful fallback) is **KEPT**; `blockchain_identity.py` → **RELOCATE CHR-X-041**. **Keep-list unchanged authority: `control_plane/policy.py` + policy store/sync/cache, `control_plane/notifications.py` (until absorbed per ARCH-026), deliberation worker** | Redis-only; returns None with a warning log in the actual prod deployment; public-API deprecation path REQUIRED (handlers are served surface) | startup/control_plane.py:55-58; operator ruling 2026-07-06 (#8851), salvage-audited |
| CHR-X-016 | PENDING | dead `server/extensions.py` init path + its None-returning consumers, OR wire `init_extensions()` at startup — one or the other, no limbo | ENABLE_MOLTBOT/ENABLE_GASTOWN flags are cosmetic today; docs over-claim | rg: init_extensions has zero callers |
| CHR-X-017 | PENDING | `aragora/gateway` never-started LocalGateway/device-node/federation server story (registered gateway HTTP handlers stay) | no non-test code starts LocalGateway; untested-in-prod security surface | rg 'LocalGateway' non-test |
| CHR-X-018 | PENDING | docs: root `docs/STATUS.md` mirror, `docs/COORDINATION.md` (frozen 2026-04-28, folds into AGENT_OPERATING_CONTRACT), stale positioning snapshots → `docs/archive/` | intent layer must not contradict itself; CLAUDE.md still points agents at the stale file | docs-charters map git-log dates |
| CHR-X-019 | PENDING | `aragora/db/` (fold into `aragora/storage`) | duplicate get_database abstraction, 1 importer | db/__init__.py docstring |
| CHR-X-025 | PENDING | Superseded sibling architecture docs: stamp `SUPERSEDED-BY: docs/architecture/INTENDED_ARCHITECTURE.md` headers on (or archive to `docs/archive/`) `ARCHITECTURE.md`, `ARCHITECTURE_THREE_LAYER.md`, `SYSTEM_DIAGRAM.md`, `system-overview.md`, `GATEWAY_ARCHITECTURE.md`, `CODEBASE_ANALYSIS.md`, `ANALYSIS.md`, `ground-up-assessment-2026-01-29.md` — executed as part of the ratification PR | rival layer models must not be citable against the charter (§0 precedence) | docs/architecture/ ls 2026-07-06 |
| CHR-X-026 | PENDING | `agents/calibration.py` → absorb into `aragora/ranking` | dual calibration paths (ARCH-006) | ARCH-006 evidence |
| CHR-X-027 | PENDING | `knowledge/embeddings.py`, `memory/embeddings.py`, `ml/embeddings.py` → demote to provider plugins behind `aragora/core` embeddings service | 4 embedding stacks; dimension-mix prod crash (ARCH-010); coordinate with CHR-X-038 | ARCH-010 evidence |
| CHR-X-028 | PENDING | Gastown bead/convoy dialect (`extensions/gastown` refinery/rig store surfaces) | `aragora/nomic/stores` is the single bead/convoy truth (ARCH-013) | workspace/bead.py delegation |
| CHR-X-029 | PENDING (ruled 2026-07-06: ABSORB confirmed) | `aragora/goals/` → absorb into `aragora/pipeline` — `extractor.py` becomes the pipeline stage-2 module; repoint the 8 live importers; `aragora/autonomous/` → fold into `aragora/nomic` | single idea→execution pipeline (ARCH-017) | goals/ = extractor.py only; operator ruling 2026-07-06 (#8851), salvage-audited |
| CHR-X-030 | PENDING | `swarm/worker_launcher.py` direct process spawning → becomes a `aragora/harnesses` consumer | one spawning authority (ARCH-018) | worker_launcher.py:613,685 |
| CHR-X-031 | PENDING | `aragora/schedulers/` deprecated shim package (home: `aragora/scheduler`) | shim-retirement family with CHR-X-005/006/007 (ARCH-022) | shim self-describes deprecated |
| CHR-X-032 | PENDING | `integrations/slack.py`, `integrations/telegram.py`, `integrations/teams.py`, `integrations/whatsapp.py` platform clients → staged migration into `connectors/chat` | one inbound-connector home (ARCH-025); both Telegram stacks live today | runtime wiring rg |
| CHR-X-033 | PENDING | `aragora/client/` ungated Python client → CLI migrates to `sdk/python/aragora_sdk`, or client comes under the parity gate; never two ungated | ungated clients drift silently (ARCH-024, CHR-E-007) | check_sdk_parity.py:280 |
| CHR-X-034 | PENDING | `notifications/retry_queue.py`, `events/dead_letter_queue.py`, `integrations/webhooks.py` dispatcher → consolidate onto `webhooks/retry_queue.py` | 4 retry/dead-letter implementations (ARCH-027) | all reachable per rg |
| CHR-X-035 | PENDING | `security/token_rotation.py` vs `auth/token_rotation.py` — absorb into one (ARCH-033 rules which at execution) | duplicated token rotation | importer rg |
| CHR-X-036 | PENDING | 8 per-provider `security/*_rotator.py` boilerplate files → one table-driven registry in `aragora/security`; no NEW per-provider rotator files meanwhile | each has exactly 1 importer (startup/security.py) (ARCH-034) | startup/security.py wiring |
| CHR-X-037 | PENDING | `aragora/export/decision_receipt.py` (`LegacyDecisionReceipt`) → absorb-or-retire per RECEIPT_LINEAGE_RECONCILIATION; `aragora/receipts/` chartered as **facade-only** over gauntlet (re-exports + fleet lane/operational receipts; no independent product receipt classes) | three receipt lineages is exactly the believability failure the charter exists to prevent (ARCH-002, CHR-E-002) | receipts/__init__.py:9 |
| CHR-X-038 | PENDING | `knowledge/vector_store.py` + `knowledge/search/` → **absorb into `knowledge/mound`** (move under mound or re-point imports first; delete top-level only after). Live internal importers: mound/core.py:306 (KnowledgeVectorStore/KnowledgeVectorConfig — live Weaviate connect path), knowledge/embeddings.py:14 (bm25), mound/vector_abstraction/memory.py:27 (bm25) | deleting in place breaks knowledge/mound — the v0.1 "0 external importers" claim was wrong for these two; corrected per critic pass | import sites cited inline, verified 2026-07-06 |
| CHR-X-041 | PENDING (ruled 2026-07-06: RELOCATE) | `control_plane/blockchain_identity.py` → **relocate to `aragora/blockchain/agent_registry.py`**; live consumer `aragora/blockchain/receipt_settlement.py` must be refactored in the same move (split out of CHR-X-015) | blockchain identity belongs with its sole live consumer, not in control_plane | operator ruling 2026-07-06 (#8851), salvage-audited |
| CHR-X-042 | PENDING (ruled 2026-07-06: RETIRE) | `aragora/workflow/scheduler.py` — duplicate of the scheduling concern (ARCH-014/ARCH-022 inventory); minted alongside the ARCH-016 workflow ADOPT confirmation | workflow stays a DAG **library**; it must not carry a rival scheduler | operator ruling 2026-07-06 (#8851), salvage-audited |
| CHR-X-043 | PENDING (ruled 2026-07-06: ABSORB) | `aragora/workspace/` (delegating wrapper over NomicBeadStore, 11 live importers) → **absorb into `aragora/nomic/stores`** (ARCH-013); **sequenced AFTER CHR-X-028** (gastown retirement) | one bead/convoy truth; wrapper adds an indirection layer with no independent behavior | operator ruling 2026-07-06 (#8851), salvage-audited |

### 3c. Parked (deliberately undecided — named owner + calendar date; do not act either way)

| ID | State | What | Owner | Review by | Condition |
|---|---|---|---|---|---|
| CHR-X-011 | PARKED | `server/fastapi` /api/v2 second HTTP stack | operator | 2026-09-01 | make it THE stack or delete; carrying two indefinitely is the worst option |
| CHR-X-020 | PARKED | Unified Memory Gateway (`memory/gateway` + retention/dedup/titans) | operator | 2026-08-15 (backstop; earlier if #8851 rules) | adopt as sanctioned fan-out API or remove; meanwhile no new callers beyond existing flag paths |
| CHR-X-021 | PARKED | migration-system consolidation (3 systems; interim authority = persistence.migrations per ARCH-031) | operator | 2026-09-01 | pick one system; auto_migrations' persistence.migrations default stands until then |
| CHR-X-022 | PARKED | `aragora/persistence/` vs storage adjudication | operator | 2026-09-01 (backstop; earlier once CHR-X-019 lands) | serves the nomic loop; rule after CHR-X-019 executes |
| CHR-X-023 | PARKED | connector vertical catalog (~132 dynamically-loaded files) | operator | 2026-10-01 | keep as "catalog tier" with contract tests, or prune; grep-based dead-code claims are invalid here (importlib load, runtime_registry.py:424) |
| CHR-X-024 | PARKED | debate flag-only exotica (chaos_theater, blackbox, witness, immune_system) | operator | 2026-09-15 | live caller by the review date or move to an experiments namespace |
| CHR-X-039 | PARKED | L5 fleet-machinery packaging: ships in customer wheel vs excluded via packaging manifest (nomic/, swarm/, worktree/, harnesses/) | operator | 2026-09-01 | P3 pip packaging is proven (#8517); "dev-side only" is currently intent the artifact does not enforce |
| CHR-X-040 | PARKED (ruled 2026-07-06) | `control_plane/scheduler.py` + `control_plane/registry.py` remainder (region routing, load strategies) — split out of CHR-X-015; registry's health/liveness surface consumed by `debate/team_selector.py` is KEPT and excluded from this park | operator | 2026-07-29 (next charter review, #8762 cadence) | adopt as distributed-dispatch authority when a deployment with a real multi-worker agent pool exists; retire if none exists at next charter review. scheduler.py: 82 behavioral tests; priority-tier streams, capability matching, retry+dead-letter, policy/cost gates — capabilities absent from nomic dev_coordination. Operator ruling 2026-07-06 (#8851), salvage-audited |

Parking rule (§5 vocabulary): a park without an owner is abandonment; an expiry without a date
has no teeth. Every PARKED/EXPIRING entry carries a named owner and an ISO date (or a concrete
triggering PR/issue **plus** a backstop date at which it auto-escalates to the operator).

### 3d. Exclusions (never build / never wire) — each with an operational test

| ID | What is excluded | Operational test | Why |
|---|---|---|---|
| CHR-E-001 | New debate/deliberation loops outside `aragora/debate` | any module outside `aragora/debate` that sends a prompt to more than one agent/model and aggregates their outputs into a verdict, vote, consensus, or ranking is a deliberation loop — excluded. (Calling Arena as a library is fine; that is the point.) | one deliberation engine (L1) |
| CHR-E-002 | New receipt emitters outside `aragora/gauntlet`; new external verifiers besides `aragora-verify` | any new class/function outside gauntlet that constructs a decision-receipt artifact (product) — excluded; `receipts/` facade re-exports and dev_coordination fleet receipts (the chartered L5 analogue, ARCH-002) are the closed set of exceptions | receipt integrity is the product claim |
| CHR-E-003 | New schedulers, work-claim/lease stores, or agent registries | allowed dispatch surfaces are the closed list: `aragora/nomic/dev_coordination`, `aragora/queue`, and the swarm boss-loop dispatch inside `aragora/swarm` (supervisor/reconciler). Anything else that assigns work to agents or claims ownership is excluded. Ops-cron (`aragora/scheduler`, ARCH-022) is a distinct sanctioned concern, not a dispatch surface. Complete duplicate inventory: ARCH-014 | six schedulers and three claims systems already; #8851 |
| CHR-E-004 | Server-local metrics/tracing/http-pool homes in `aragora/server` | any new module under `aragora/server` exporting prometheus metrics, tracing middleware, or an HTTP client pool — excluded | P4a; see CHR-P4A-001..003 |
| CHR-E-005 | New KM adapters wrapping PENDING-retire subsystems | no new adapter may wrap anything named in registry entries CHR-X-001..CHR-X-043 while in state PENDING (machine check: adapter target path ∈ charters.yaml pending paths) | adapters manufacture fake "integration" evidence |
| CHR-E-006 | New platform delivery clients outside `connectors/chat` + channels dock | closed platform list: Slack, Teams, Telegram, WhatsApp, Discord, Zoom, Email. A client for any of these outside connectors/chat + channels is excluded; a NEW platform requires a charter amendment (R5) | ~7 Slack stacks is the cautionary tale |
| CHR-E-007 | Second Python client surfaces beyond the parity-gated SDK | any new module presenting a typed Python API-client resource surface outside `sdk/python/aragora_sdk` — excluded (pending CHR-X-033 client absorption) | ungated clients drift silently |
| CHR-E-008 | Standing admin credentials / API keys in local env | any PR adding a standing credential to `.env*`, launchd plists, or shell profiles — excluded; AWS Secrets Manager only | credential architecture (post-incident) |

---

## 4. Fleet Rules — consulting this charter

Binding per the Binding status block (top of file): all rules bind at ratification; while
DRAFT, only the entries listed there bind. These compose with, and do not replace,
`docs/AGENT_OPERATING_CONTRACT.md` (approval matrix, main-red mode) and the lease rule
(`scripts/check_work_lease.py`).

**R1 — Check before you add.** Before creating a module, package, export, or cross-package
import edge, find the concern's ARCH-row in §2 (or the package's Appendix-A state). Code for
a chartered concern goes in its authority module. Adding it to a non-authority module is a
**charter violation**, even if the code is good, tested, and green. Packages with no row are
UNMAPPED and frozen for growth (§2d).

**R2 — Removed means removed.** Re-adding anything in a §3 `REMOVED` entry — including
"compat re-exports", "temporary shims", or flipping a charter end-state test — is a charter
violation. Reviewers must cite the entry ID in their finding. The #8893 pattern
("preserving backward compatibility" for a chartered removal) is explicitly named invalid.

**R3 — Pending and Expiring mean frozen.** `PENDING` **and `EXPIRING`** entries accept
**no new importers/callers** from ratification (or from the entry's own pre-existing
contract, where noted). Existing callers keep working until the removal executes; for
EXPIRING, existing callers must migrate before the stated deadline. Extending a deadline
requires operator approval **and** a registry-entry update in the same PR. This is how we
avoid growing the blast radius while #8851 rulings land.

**R4 — Parked means hands off.** Do not wire, extend, or delete `PARKED` items. If your task
seems to require one, stop and surface it to the operator with the entry ID.

**R5 — New subsystems need a charter amendment.** A new top-level `aragora/<pkg>`, a new
concern row, or promoting an UNMAPPED package requires an operator-approved amendment to this
document in the same PR (Tier 3+ by the operating contract). "It exists so I wired it" is not
an integration argument — check §2 dispositions and §3 states first (control_plane's
warn-then-None startup is the cautionary precedent for wired-but-dead claims).

**R6 — Evidence standard.** Claims of liveness must cite an entrypoint (daemon, CI workflow,
registered handler, CLI command, script with callers) — not the existence of tests or of a KM
adapter (CHR-E-005). Claims about code under this charter must distinguish
**live product / adopted fleet machinery / code-live-prod-dormant / dormant** (§1 status marks).
An unregistered server handler module is dormant (ARCH-023).

**R7 — Doc citability.** A doc claim is citable only if it is generated (doc_stats/METRICS)
or CI-checked. Recency is guidance, not a rule: where recency matters, the date source is
`git log -1 --format=%cs -- <path>` (last commit touching the file), not header dates —
and a mass-format commit does not refresh substance. On numeric conflict, `docs/METRICS.md`
wins.

**R7b — Charter wins on liveness.** On conflict between CLAUDE.md's feature/status tables (or
any marketing/status doc) and this charter's §1 status marks or §3 states, the charter wins
pending the approved CLAUDE.md edit (protected file; queued in the ratification checklist, §6).

**R8 — Gate integration (ratification preconditions, currently honest-red).** The
reviewer/gate grounding must include this registry (#8905 acceptance): a PR touching a
chartered-removed symbol yields a grounded finding citing the CHR id. **Preconditions of
flipping Status to RATIFIED — not follow-ups:**
(a) wire `scripts/ci/check_import_contracts.py` + `scripts/baselines/import_contracts_baseline.json`
into a required check (today: zero callers in workflows/Makefile/pre-commit);
(b) `docs/architecture/charters.yaml` committed and current (done in the PR that landed this
draft — schema in §6);
(c) add #8893 as the charter-blind specimen to the adjudicator eval fixtures.
Until (a) is live, **no §3b entry may transition PENDING → REMOVED** — executing removals a
gate cannot cite reproduces the failure this charter was written to close.

---

## 5. Vocabulary — one language for all fleets

| Term | Canonical meaning | Not to be confused with |
|---|---|---|
| **mission** | A bounded goal given to the fleet, entering via mission intake and decomposed into leased work (fleet spine, L5) | product "debate task"; a mission may spawn many debates |
| **feature** | A shipped, *reachable* capability with a live entrypoint (R6 evidence standard) | tested-but-unwired code; flag-off code; catalog code |
| **work lease** | Exclusive, time-bounded ownership of a branch/lane recorded in `nomic/dev_coordination` (preflight: `check_work_lease.py`) | worktree existence; a git branch; `worktree/fleet.py` mirrors leases, never grants them |
| **receipt** | Verifiable decision artifact emitted by `aragora/gauntlet` (ODR schema), externally checkable by `aragora-verify`; fleet completion receipts in dev_coordination are the L5 analogue | logs, summaries, PR descriptions |
| **gate** | A merge-blocking check: the 5 required CI checks + the tiered quorum (#8638). Severity-gated P2/P3 dissent is advisory: non-blocking but **non-counting** | code review comments generally |
| **settle** | Drive a PR through quorum to a terminal state via `settle_tier4_pr.py`; Tier 1-2 settle on ONE western-frontier PASS | merging by hand; approving |
| **quorum** | The configured reviewer set whose PASS/FAIL verdicts the tiered gate counts (western-frontier = {claude, openai}) | any collection of LLM opinions; Fugu never counts as diversity |
| **charter** | An operator-ratified statement of intended structure (this doc, P4a docs) with a citable registry | plans, proposals, PR-thread decisions |
| **chartered removal** | A §3 entry with an ID; removal intent that survives the PR that executed it | ordinary refactor deletions |
| **authority (module)** | The single module allowed to own a concern (§2) | the module with the most code for that concern |
| **duplicate / dormant** | Second implementation of a chartered concern / code with no live entrypoint per R6 | "unused" by grep alone (see CHR-X-023 importlib caveat) |
| **park** | Deliberate non-decision with a named owner + calendar review date (§3c) | abandonment; parking still freezes wiring |
| **UNMAPPED** | Default state for packages with no §2/Appendix-A mapping: frozen for architectural growth, maintenance allowed (§2d) | "unowned, do what you want" |
| **spine** | The two chartered execution paths: **fleet spine** (missions → dev_coordination → swarm → pipeline → approvals/receipts) and **product spine** (surface → debate core → knowledge → receipt → channels) | any long import chain |
| **tier** | Change-risk class 0-4 from the operating contract driving gate strictness and auto-merge eligibility | RBAC roles; handler tiers (`ARAGORA_HANDLER_TIERS`) |
| **execution loop** | An agent's act-observe cycle inside one task (worker lanes in worktrees); exits on environment feedback | the task loop's review rounds |
| **task loop** | Fresh-context iteration against the same spec until compliance (the merge gate's review-repair rounds); exits on counting PASS with no blocking dissent | retrying with accumulated (polluted) context |
| **product loop** | The continuous backlog-to-merge lifecycle (fleet + merge queue + missions); exits per-item on merge receipts, monitored via open-PR trend and scorecards | any single PR's lifecycle |
| **system loop** | The loop that improves the machinery itself (epic #8972: harness edits validated by gate-outcome deltas); exits on scoreboard non-regression | the product loop it measures |
| **oversight loop** | Goal-setting, budget allocation, culling — the operator's ring (tokens, tier settlements, rulings, rubric curation); its signals are kill-switch metrics and data-window reviews. Autonomy is a dial set per-ring; the tier system is that dial's implementation | a bottleneck to automate away |
| **pipeline (not a loop)** | Fan-out/gather/validate with no feedback into a next cycle (Workflow orchestrations); a topology deployable inside any ring | a loop — a pipeline has no feedback edge |

---

## 6. Amendment & maintenance

### charters.yaml schema (normative)

`docs/architecture/charters.yaml` is generated from §2/§3 and committed in the same PR as any
change to them (R8b made it a ratification precondition; the seed was committed with this
draft). Schema:

```yaml
meta:
  charter: docs/architecture/INTENDED_ARCHITECTURE.md
  version: "0.4"          # must match this doc's version
  status: DRAFT           # DRAFT | RATIFIED
authorities:              # §2 rows
  - id: ARCH-001
    concern: <short name>
    authority: <repo-relative module path(s)>
    layer: L0..L6
    disposition: adopt | absorb | retire | park | interim-adopt
    binding_in_draft: true       # optional: operator activated this authority before full ratification
    decision_record: <path>      # required for an authority made binding while meta.status is DRAFT
    registry_refs: [CHR-...]   # every non-adopt disposition points at ≥1 entry
    ruled: <ISO date>          # optional: operator adopt-or-retire ruling date (#8851);
                               # fixes the disposition, does NOT change binding status
registry:                 # §3 entries
  - id: CHR-X-001
    state: REMOVED | EXPIRING | PENDING | PARKED | EXCLUSION
    ruled: <ISO date>                 # optional: operator ruling date (see authorities)
    paths: [<exact repo-relative paths or well-formed globs>]
    symbols: [<module:export_name>]   # may be empty for whole-path entries
    deadline: <ISO date>              # required for EXPIRING and PARKED
    owner: <name>                     # required for PARKED
    evidence: <one-line anchor>
    superseded_by: <id or null>
```

### Rules

- This charter lives at `docs/architecture/INTENDED_ARCHITECTURE.md`; it and `charters.yaml`
  change only together.
- Amendments: operator approval required (governance-doc class, per operating contract).
  Fleets may PROPOSE entries via PR; entries take effect only when state is set by the operator.
- **Any change to §2, §3, or §4 bumps the charter version** and appends an Amendment-log row.
- IDs are permanent: never reused, never renumbered; entries are only ever state-transitioned.
- Every §3b/§3c execution PR must reference its CHR id in the PR body; the registry entry is
  then updated with date + PR in the same change.
- Review cadence: with the #8762 close-the-loop checkpoint (next: 2026-07-29), reconcile this
  charter against #8851 rulings and newly merged downshifts.

### Ratification checklist (all are preconditions of `Status: RATIFIED`)

1. Operator approves this PR (or a successor) — charter + charters.yaml land on main.
2. R8a: `check_import_contracts.py` wired as a required check.
3. R8c: #8893 added to the adjudicator eval fixtures as the charter-blind specimen.
4. CHR-X-025 executed: sibling architecture docs stamped SUPERSEDED-BY or archived.
5. Pointer lines added to `CLAUDE.md` and `AGENTS.md` (protected files — explicit
   operator-approved edit): "Architecture intent: `docs/architecture/INTENDED_ARCHITECTURE.md`
   + `charters.yaml` — check before adding modules/imports." Includes fixing CLAUDE.md's
   144-row table advertising §3b PENDING subsystems as features with no liveness column (R7b
   governs the interim).
6. The queue-drain cleanup plan lands on main so it is citable
   (`docs/plans/2026-06-30-queue-drain-diagnosis-and-cleanup-plan.md`).

### Amendment log

| Version | Date | PR | Approval evidence | Entries changed |
|---|---|---|---|---|
| v0.1 | 2026-07-05 | (scratchpad draft, never binding) | operator-commissioned | initial: CHR-P4A-001..004, CHR-X-001..024, CHR-E-001..008 |
| v0.2 | 2026-07-06 | this PR (draft) | operator-commissioned; adversarial critic pass applied | added ARCH-001..036 ids; CHR-P4A-004 → REMOVED (#8909); CHR-X-002 split (→ CHR-X-038); CHR-X-010 corrected (snapshot/redteam/sandbox de-chartered); added CHR-X-025..039; parked entries got owners+dates; exclusions got operational tests; UNMAPPED default + Appendix A; R3 covers EXPIRING; R7 date source; R7b; R8 → preconditions |
| v0.3 | 2026-07-06 | this PR (draft) | gate round 1: adversarial review findings applied | DRAFT carve-outs for placement protocol/§0 entry states/precedence (banner + §0); ARCH-020 disposition fix (retire → adopt; retirement confined to CHR-X-009); evidence snapshot caveat (§0); ARCH-020/CHR-X-009 anchor disambiguated (`scripts/goal_conductor.py:310` hardcodes the `scripts/nomic_loop.py` path) |
| v0.4 | 2026-07-06 | this PR (draft) | operator-ratified decision packet #8851 + four adversarial salvage audits (2026-07-06) | operator #8851 rulings encoded after salvage audits: 2 adoptions confirmed, 2 absorptions, 6 retirements, 2 parks, 1 relocation, cross_workspace/resolver guard. Entries amended: ARCH-012/013/014/015/016/017, CHR-X-012/014/015/029; minted: CHR-X-040 (control_plane scheduler+registry park), CHR-X-041 (blockchain_identity relocate), CHR-X-042 (workflow/scheduler retire), CHR-X-043 (workspace absorb). Entries stay PROPOSED-pending-ratification; `ruled: 2026-07-06` marks operator-ruled dispositions |
| v0.5 | 2026-07-08 | this PR (draft) | operator-approved insight fold (loop-taxonomy article) | loop-ring vocabulary added (§5: execution/task/product/system/oversight loop, pipeline); no authority or registry changes |
| v0.6 | 2026-08-18 | this PR (draft) | operator unparked #8851 acceptance item 3 for ARCH-015 only | made `aragora/queue` binding as the durable-job API/transport authority; recorded the live `storage/job_queue_store.py` backend split and froze new direct consumers |

---

*Drafted 2026-07-05 from 8 evidence-grounded cluster maps (decision-core, knowledge-memory,
orchestration-substrate, server-api, fleet-ops, integrations-channels, enterprise-platform,
docs-charters); revised 2026-07-06 after an adversarial critic pass that re-verified importer
claims against the repo. Every disposition traces to an evidence line; where maps, priors, or
the v0.1 draft disagreed with the code (queue/ and workflow/ are live, not dormant; vector_store
and search/ have live mound-internal importers; snapshot/redteam/sandbox have real ELO and
formal-verification callers; #8909 already executed the queue re-removal), the code evidence won.*

## Appendix A. Top-level package triage (generated 2026-07-06)

One line per `aragora/*` package. MAPPED rows cite their ARCH/CHR ids; UNMAPPED rows are
frozen for architectural growth per §2d until triaged by charter amendment (R5). This table is
descriptive inventory — the normative machine encoding is `charters.yaml`.

| Package | Layer | State | Charter refs / notes |
|---|---|---|---|
| `aragora/advocates` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/agents` | L1 | MAPPED | ARCH-001 roster; CHR-X-010 dead modules; CHR-X-026 calibration absorb |
| `aragora/analysis` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/analytics` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/approvals` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/audience` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/audit` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/auth` | L0 | MAPPED | ARCH-033 authority; CHR-X-035 token_rotation |
| `aragora/autonomous` | L5 | MAPPED | CHR-X-029 fold into nomic |
| `aragora/backup` | L0 | MAPPED | L0 |
| `aragora/billing` | L0 | MAPPED | L0 |
| `aragora/blockchain` | — | UNMAPPED | frozen for architectural growth (§2d) EXCEPT as the chartered relocation target for `control_plane/blockchain_identity.py` → `blockchain/agent_registry.py` (CHR-X-041, ruled 2026-07-06); otherwise triage via R5 amendment |
| `aragora/bots` | L4 | MAPPED | CHR-X-004 slack/teams retire; discord/zoom handlers stay |
| `aragora/brief_engine` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/broadcast` | L4 | MAPPED | L4 out |
| `aragora/caching` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/canvas` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/channels` | L4 | MAPPED | ARCH-026 authority (transport) |
| `aragora/cli` | L3 | MAPPED | ARCH-019/024 (migrates to SDK per CHR-X-033) |
| `aragora/client` | L3 | MAPPED | ARCH-024 duplicate; CHR-X-033 absorb |
| `aragora/codex` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/compat` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/compliance` | L0 | MAPPED | L0 |
| `aragora/computer_use` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/config` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/connectors` | L4 | MAPPED | ARCH-025 authority; CHR-X-023 catalog parked |
| `aragora/control_plane` | L0 | MAPPED | ruled 2026-07-06: CHR-X-015 retire (auto_scaling/agent_federation/regional_sync); CHR-X-040 park (scheduler + registry remainder; team_selector health surface kept); CHR-X-041 relocate (blockchain_identity); policy/notifications/deliberation-worker keep-list |
| `aragora/coordination` | L5 | MAPPED | ruled 2026-07-06: CHR-X-012 — absorb claims/registry→swarm; retire task_dispatcher/health_watchdog/worktree_manager; salvage GitReconciler/bus/directives; GUARD: cross_workspace.py + resolver.py unruled, `__init__` deletion blocked |
| `aragora/core` | L1 | MAPPED | ARCH-010 embeddings authority; core types |
| `aragora/db` | L0 | MAPPED | CHR-X-019 fold into storage |
| `aragora/debate` | L1 | MAPPED | ARCH-001 authority; ARCH-009; CHR-X-024 exotica parked |
| `aragora/deliberation` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/documents` | L2 | MAPPED | L2 ingestion |
| `aragora/embeddings` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/epistemic` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/essay` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/evaluation` | L1 | MAPPED | ARCH-004 authority |
| `aragora/events` | L0 | MAPPED | dispatcher stays; dead_letter_queue → CHR-X-034 |
| `aragora/evidence` | L2 | MAPPED | ARCH-005 ingestion front-end |
| `aragora/evolution` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/explainability` | L1 | MAPPED | L1 authority |
| `aragora/export` | L1 | MAPPED | decision_receipt.py → CHR-X-037; rest of export/ UNMAPPED-adjacent, see note |
| `aragora/extensions` | L5 | MAPPED | CHR-X-016 (init path); CHR-X-028 gastown dialect |
| `aragora/fabric` | L5 | MAPPED | CHR-X-013 retire |
| `aragora/factory` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/fixtures` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/gateway` | L4 | MAPPED | CHR-X-017 (LocalGateway story); registered handlers stay |
| `aragora/gauntlet` | L1 | MAPPED | ARCH-002 authority (receipt emission); CHR-X-001 odr_verify |
| `aragora/genesis` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/goals` | L3 | MAPPED | CHR-X-029 absorb into pipeline (ruled 2026-07-06: extractor.py → pipeline stage 2, repoint 8 importers) |
| `aragora/gti` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/harnesses` | L5 | MAPPED | ARCH-018 authority |
| `aragora/heterogeneity` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/hooks` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/ideacloud` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/implement` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/inbox` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/insights` | L2 | MAPPED | L2 |
| `aragora/integrations` | L4 | MAPPED | CHR-X-032 clients absorb into connectors; CHR-X-034 dispatcher |
| `aragora/interrogation` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/introspection` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/knowledge` | L2 | MAPPED | ARCH-007 authority (mound); CHR-X-002/027/038 |
| `aragora/learning` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/live` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/maintenance` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/marketplace` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/markets` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/mcp` | L4 | MAPPED | ARCH-028 authority |
| `aragora/memory` | L2 | MAPPED | ARCH-008 authority; CHR-X-003/020/027 |
| `aragora/metrics` | L1 | MAPPED | CHR-X-007 shim retire; new imports forbidden now |
| `aragora/migrations` | L0 | MAPPED | ARCH-031/CHR-X-021 parked consolidation |
| `aragora/missions` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/ml` | L2 | MAPPED | CHR-X-027 embeddings demote; rest UNMAPPED-adjacent |
| `aragora/moderation` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/modes` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/monitoring` | L0 | MAPPED | CHR-X-005 shim retire |
| `aragora/nomic` | L5 | MAPPED | ARCH-012 authority (dev_coordination); ARCH-013 stores; CHR-X-039 packaging park |
| `aragora/notifications` | L4 | MAPPED | ARCH-026 authority (policy); CHR-X-034 retry consolidation |
| `aragora/observability` | L0 | MAPPED | ARCH-029 authority (P4a RATIFIED) |
| `aragora/onboarding` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/operations` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/ops` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/pdb` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/performance` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/persistence` | L0 | MAPPED | ARCH-031 interim migrations authority; CHR-X-022 parked |
| `aragora/pipeline` | L3 | MAPPED | ARCH-017 authority |
| `aragora/playbooks` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/plugins` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/policy` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/prediction` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/privacy` | L0 | MAPPED | L0 |
| `aragora/prompt_engine` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/prompts` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/protocols` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/pulse` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/queue` | L3 | MAPPED | ARCH-015 authority; CHR-P4A-004 |
| `aragora/ralph` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/ranking` | L1 | MAPPED | ARCH-006 authority; CHR-X-010 muse_calibration only |
| `aragora/rbac` | L0 | MAPPED | ARCH-033 authority |
| `aragora/reasoning` | L1 | MAPPED | ARCH-005 authority |
| `aragora/receipts` | L1 | MAPPED | ARCH-002 facade over gauntlet; CHR-X-037 |
| `aragora/replay` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/reports` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/reputation` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/resilience` | L0 | MAPPED | ARCH-032 authority; CHR-X-006 |
| `aragora/review` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/rlm` | L2 | MAPPED | ARCH-011 authority |
| `aragora/routing` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/runtime` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/sandbox` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/scheduler` | L0 | MAPPED | ARCH-022 authority (ops cron) |
| `aragora/schedulers` | L0 | MAPPED | CHR-X-031 shim retire |
| `aragora/security` | L0 | MAPPED | ARCH-034 authority (interim rotators); CHR-X-035/036 |
| `aragora/server` | L3 | MAPPED | ARCH-023 authority; CHR-X-011 park; CHR-X-016; CHR-P4A-001..003 |
| `aragora/services` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/shared` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/skills` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/spectate` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/storage` | L0 | MAPPED | ARCH-030 authority |
| `aragora/stores` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/streaming` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/swarm` | L5 | MAPPED | ARCH-014 authority (boss loop); CHR-X-030 worker_launcher absorb |
| `aragora/sync` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/tasks` | L3 | MAPPED | CHR-X-014 retire (ruled 2026-07-06: inline router.py into handlers/tasks/execution.py, port 18 tests) |
| `aragora/telemetry` | L0 | MAPPED | CHR-X-005 shim retire |
| `aragora/templates` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/tenancy` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/tools` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/tournaments` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/trail` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/training` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/transcription` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/triage` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/types` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/uncertainty` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/utils` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/verification` | L1 | MAPPED | L1 authority; sandbox.py retained (CHR-X-010 note) |
| `aragora/verticals` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/visualization` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/webhooks` | L4 | MAPPED | ARCH-027 authority |
| `aragora/work` | — | UNMAPPED | frozen for architectural growth (§2d); triage via R5 amendment |
| `aragora/workflow` | L3 | MAPPED | ARCH-016 authority (library; ADOPT confirmed, ruled 2026-07-06); CHR-X-042 scheduler.py retire |
| `aragora/workspace` | L5 | MAPPED | ARCH-013 delegating wrapper over nomic/stores; CHR-X-043 absorb into nomic/stores AFTER CHR-X-028 (ruled 2026-07-06) |
| `aragora/worktree` | L5 | MAPPED | ARCH-021 authority; fleet.py mirror-only (ARCH-012) |

Totals: 144 top-level packages — 64 MAPPED, 80 UNMAPPED.
(Top-level single-file modules under `aragora/*.py` follow their nearest package's state; `resilience_patterns.py`/`resilience_config.py` are chartered in CHR-X-006.)
