# P4a Foundation/Infrastructure Layering Disposition

Doc-first design deliverable for milestone **p4a-layering-foundation** (feature
`p4a-contracts-design`). It mirrors the `p4b-handlers-design` pattern: this
document records, for **every** foundation/infrastructure import-contract edge,
the importer `file:line`, the imported module, and the **authorized
disposition**, then groups them into a batched, Tier-labeled implementation plan
sized for bounded structex features. The orchestrator turns the batch list at
the end into implementation sub-features plus the `p4a-contracts-seal` feature.

**This is a DOC-ONLY deliverable. No move, reclassification, baseline edit, or
`.importlinter` edit is performed in `p4a-contracts-design`.** All such changes
land in the implementation sub-features and the seal.

---

## 1. Scope, contract, and measurement provenance

VAL-P4A-006 requires the import-linter layers contract to reach **0 violations
for the foundation and infrastructure layers**, and the foundation/infra
violation collections in `scripts/baselines/import_contracts_baseline.json` to
be **empty**. The contract is the single `aragora-layers` contract in
`.importlinter` (type `layers`, container `aragora`), enforced shrink-only by
`scripts/ci/check_import_contracts.py` against the baseline.

Layer order (highest to lowest; a module may import its own layer or below,
never above):

```
interface       server, cli, mcp, gateway, bots, channels, integrations, connectors
application     workflow, pipeline, nomic, swarm, gauntlet, goals, implement, modes,
                verticals, autonomous, broadcast, canvas, spectate
domain          debate, agents, memory, knowledge, ranking, reasoning, evidence,
                evaluation, explainability, learning, ml
infrastructure  storage, resilience, events, observability, security, queue, db,
                caching, billing, backup, migrations
foundation      config, core_types, exceptions, errors, utils, protocols, types
```

`--layers foundation,infrastructure` restricts the check to violations whose
**importing** module is in foundation or infrastructure (verified in
`--help`). The ambient `aragora.swarm -> aragora.cli` edge (application layer,
sibling-fleet) is therefore excluded and is **out of scope**; never touch
`aragora/swarm/` for this work.

**Measurement provenance.** Edges and `file:line` below were resolved with
grimp 3.14 (the engine import-linter uses) against a clean worktree off
`origin/main` at `17947814fe4d38b9db95f4eb3975e27aa1493d0e` (post #8678 protocols
collapse, #8690 telemetry/monitoring, #8696 metrics->evaluation), graph of 4,216
modules. The `aragora-layers` contract does **not** set
`exclude_type_checking_imports`, so it counts module-scope, function-scope
(lazy), and `TYPE_CHECKING` imports. Line numbers may drift on the live tree;
implementation workers must re-confirm against current `origin/main`.

### Edge census

| Population | Count |
|---|---|
| Foundation/infra edges baselined in `import_contracts_baseline.json` | **54** (22 foundation-importer + 32 infrastructure-importer) |
| New, NOT baselined (#8672 caching shim regression) | **1** (`aragora.utils -> aragora.caching`) |
| **Total edges this doc dispositions** | **55** |
| Of those, with a resolvable **direct** import statement | 42 |
| Of those 42, `TYPE_CHECKING`-only (no runtime coupling) | 1 (`billing -> agents`) |
| **Direct, real-runtime** root-cause edges | **41** |
| **Indirect** (transitive-only; no direct import; clear when their root direct edges clear) | **13** |

### Binding contract mechanics (do not deviate)

1. **In-function / lazy imports do NOT clear a layers-contract edge.** grimp
   counts imports at ALL scopes (module, function, `TYPE_CHECKING`). Converting an
   offending import to lazy only helps the per-FILE checks (VAL-P4A-001..005, where
   `TYPE_CHECKING` is exempt), NOT the layers contract (VAL-P4A-006). The ONLY ways
   to clear a layers edge are: (a) delete the import, (b) move the shared surface to
   a same-or-lower layer with a `DeprecationWarning` shim at the old path,
   (c) reclassify/relocate the importing module to its correct layer, or
   (d) add an `.importlinter` `ignore_imports` entry (authorized only for the 3
   preserve-by-design cases in section 4).
2. **`TYPE_CHECKING`-guarded imports are counted by the layers contract** (they are
   exempt only from the per-file t1 check). The single `TYPE_CHECKING`-only edge
   (`billing -> agents`) is cleared by dropping the guarded import (section 5,
   Batch 3), not by `ignore_imports`.
3. **An edge string clears from the baseline only when its LAST direct import is
   cut.** Several edges (`billing -> server`, `events -> server`,
   `queue -> server`) are realized by multiple imports split across batches; the
   `aragora.X -> aragora.server` string may be hand-removed only after every
   constituent import is gone.

---

## 2. Disposition vocabulary

Per the binding ORCHESTRATOR DECISIONS policy (`library/p4a-contracts-zero-scope.md`):

- **real-move-down** - move the shared surface to a same-or-lower layer; leave a
  `DeprecationWarning` re-export shim at the old path (+ a `library/shims.md` row).
- **invert-dependency** - introduce a registry/callback/entry-point so the
  lower-layer package stops importing the higher-layer orchestrator (the higher
  layer registers into the lower).
- **reclassify/relocate-module** - the importing module is application/interface
  code mislocated in a foundation/infra package; relocate it to its correct
  application home (+ shim at the old import path).
- **ignore_imports** - `.importlinter` `ignore_imports` entry. Authorized ONLY for
  the 3 preserve-by-design cases in section 4; each carries a written
  justification.
- **drop-type-only-import** - remove a `TYPE_CHECKING`-only import (no runtime
  coupling, no shim needed). Used once (`billing -> agents`). This is NOT an
  `ignore_imports`.

Preference order for application-code-mislocated edges (ORCHESTRATOR DECISIONS
point 4): inversion or relocation **over** `ignore_imports`. `ignore_imports` is
used only where the edge is a genuine preserve-by-design plugin/extension point.

---

## 3. Per-edge disposition inventory

`file:line` is the direct import site (measured at `17947814fe`). "indirect"
means no direct import exists; the realizing chain and the root direct edge(s)
that clear it are given. Batch numbers reference section 5.

### 3.1 Foundation importers (22 edges)

#### `aragora.protocols` (12 edges) -> all cleared by Batch 5 (move `protocols.a2a.server` + `protocols.bridge` up)

| Edge | D/I | Importer file:line -> imported | Disposition |
|---|---|---|---|
| protocols -> agents | direct | `aragora/protocols/a2a/server.py:16,311` (`agents.base.AgentType`, `create_agent`); `aragora/protocols/bridge.py:29` (`agents.base.BaseDebateAgent`) | reclassify/relocate-module (Batch 5) |
| protocols -> debate | direct | `aragora/protocols/a2a/server.py:314` (`debate.orchestrator.Arena, DebateProtocol`) | reclassify/relocate-module (Batch 5) |
| protocols -> gauntlet | direct | `aragora/protocols/a2a/server.py:449` (`gauntlet.GauntletRunner, QUICK_GAUNTLET`) | reclassify/relocate-module (Batch 5) |
| protocols -> mcp | direct | `aragora/protocols/bridge.py:241` (`mcp.server.AragoraMCPServer`) | reclassify/relocate-module (Batch 5) |
| protocols -> events | indirect | chain: `protocols.a2a.server -> debate.orchestrator -> learning.meta -> events.dispatcher` | transitive; clears with Batch 5 |
| protocols -> knowledge | indirect | chain: `protocols.a2a.server -> debate.orchestrator -> knowledge.mound.revalidation_scheduler` | transitive; clears with Batch 5 |
| protocols -> memory | indirect | chain: `protocols.a2a.server -> debate.orchestrator -> memory.consensus` | transitive; clears with Batch 5 |
| protocols -> observability | indirect | chain: `protocols.a2a.server -> debate.orchestrator -> observability.n1_detector` | transitive; clears with Batch 5 |
| protocols -> reasoning | indirect | chain: `protocols.a2a.server -> debate.orchestrator -> reasoning.citations` | transitive; clears with Batch 5 |
| protocols -> resilience | indirect | chain: `protocols.a2a.server -> debate.orchestrator -> debate.protocol -> resilience` | transitive; clears with Batch 5 |
| protocols -> server | indirect | chain: `protocols.a2a.server -> audit.document_auditor -> server.documents` | transitive; clears with Batch 5 |
| protocols -> storage | indirect | chain: `protocols.a2a.server -> debate.orchestrator -> storage.schema` | transitive; clears with Batch 5 |

Rationale: `protocols/a2a/server.py` and `protocols/bridge.py` are A2A/MCP
**servers** (they call `create_agent`, run `Arena`, `GauntletRunner`, and
`AragoraMCPServer`) mislocated in the foundation `protocols` package. The
protocol *type* definitions stay in foundation; only the two server/bridge
implementation modules move up. Moving them clears all 4 direct + 8 indirect
protocols edges in one bounded change.

#### Other foundation importers (10 edges)

| Edge | D/I | Importer file:line -> imported | Disposition |
|---|---|---|---|
| config -> observability | indirect | chain: `config/validator.py:97 -> control_plane.leader -> observability` (the `is_distributed_state_required` import in a `try/except`) | invert-dependency (Batch 6): control_plane registers the predicate, or move it to a foundation config helper, so `config.validator` stops importing `control_plane`. Also resolves the architecture-noted `config/validator.py:97 -> control_plane`. |
| core_types -> debate | direct | `aragora/core_types.py:838` (`debate.protocol.DebateProtocol`, function-scope) | real-move-down (Batch 6): relocate the structural `DebateProtocol` contract to foundation (`protocols`/`core_types`), shim at `aragora.debate.protocol`. Lazy at :838 does NOT clear it. |
| errors -> server | direct | `aragora/errors.py:158,184,185,186,187` (module-scope public re-export of `server.errors`: `ErrorCode`, `AragoraAPIError`, `APIDebateError`, `APIMemoryError`, `APIVerificationError`, ...) | real-move-down (Batch 6, PREFERRED). `server/errors.py` is bounded (its only aragora import is `from aragora.exceptions import AragoraError`, downward to foundation), so the inversion is NOT Tier-3-unbounded. Move the API error hierarchy DOWN to a foundation errors home, preserve the public `aragora.errors.API*` surface, leave a `DeprecationWarning` shim at `aragora.server.errors`. **ignore_imports fallback is NOT taken** (boundedness proven). |
| exceptions -> connectors | direct | `aragora/exceptions.py:1148` (`connectors.exceptions`, module-scope `try/except ImportError`) | **ignore_imports** (authorized case 1; section 4) |
| exceptions -> server | direct | `aragora/exceptions.py:1203` (`server.handlers.exceptions` inside `__getattr__`) | **ignore_imports** (authorized case 2; section 4) |
| utils -> agents | direct | `aragora/utils/semantic_extraction.py:15,86` (`agents.base.AgentType`, `create_agent`) | reclassify/relocate-module (Batch 6): `semantic_extraction` is a domain helper (creates agents) mislocated in foundation `utils`; relocate up to a domain home, shim at `aragora.utils.semantic_extraction`. |
| utils -> storage | direct | `aragora/utils/async_utils.py:87,134` (`storage.pool_manager.get_pool_event_loop`) | real-move-down (Batch 6): `get_pool_event_loop` is an asyncio event-loop accessor (foundation-level), move it down, shim at `storage.pool_manager`. |
| utils -> caching | direct (NOT baselined) | `aragora/utils/redis_cache.py:12` (`caching.redis.HybridTTLCache, RedisTTLCache`) | **ignore_imports** (authorized case 3; section 4) - #8672 one-release shim |
| utils -> connectors | indirect | chains: `utils.redis_config -> exceptions -> connectors.exceptions`; `utils.cache -> services -> connectors.enterprise...` | transitive; clears when (a) the exceptions->connectors edge is ignored (seal) AND (b) the `utils.cache -> services` chain is cut (Batch 6). |
| utils -> knowledge | indirect | chains: `utils.cache -> services -> knowledge.mound`; `utils.semantic_extraction -> agents -> ... -> knowledge.mound` | transitive; clears with the `utils.semantic_extraction` relocation + the `utils.cache -> services` cut (Batch 6). |
| utils -> resilience | indirect | chains: `utils.async_utils -> storage.pool_manager -> ... -> resilience`; `utils.semantic_extraction -> agents -> resilience` | transitive; clears with the `utils -> storage` move + the `utils.semantic_extraction` relocation (Batch 6). |

### 3.2 Infrastructure importers (32 edges)

#### `aragora.events` (9 edges) -> Batch 1 (server-utility downshift) + Batch 2 (subscriber relocation/inversion)

| Edge | D/I | Importer file:line -> imported | Disposition |
|---|---|---|---|
| events -> debate | direct (11) | `events/arena_bridge.py:27`; `events/cross_subscribers/handlers/basic.py:118,195,427,456`; `events/cross_subscribers/handlers/strategic.py:226,322`; `events/security_dispatcher.py:363`; `events/security_events.py:485,486`; `events/subscribers/debate_handlers.py:81` (`debate.event_bus/agent_pool/selection_feedback/rhetorical_observer/team_selector/orchestrator/protocol`) | reclassify/relocate-module or invert (Batch 2) |
| events -> knowledge | direct (43) | `events/cross_subscribers/handlers/{basic,culture,knowledge_mound,strategic,validation}.py`; `events/subscribers/{debate_handlers,execution_handlers,mound_handlers}.py` (`knowledge.mound*`) | reclassify/relocate-module or invert (Batch 2) |
| events -> memory | direct (8) | `events/cross_subscribers/handlers/{basic,knowledge_mound,validation}.py`; `events/subscribers/mound_handlers.py:83,84` (`memory.continuum/tier_manager`) | reclassify/relocate-module or invert (Batch 2) |
| events -> agents | direct (2) | `events/security_events.py:571,572` (`agents.api_agents.{anthropic,openai}`) | reclassify/relocate-module or invert (Batch 2) |
| events -> nomic | direct (1) | `events/subscribers/testfixer_handlers.py:213` (`nomic.improvement_queue`) | reclassify/relocate-module or invert (Batch 2) |
| events -> ranking | direct (1) | `events/subscribers/execution_handlers.py:153` (`ranking.elo.EloSystem`) | reclassify/relocate-module or invert (Batch 2) |
| events -> reasoning | direct (1) | `events/cross_subscribers/handlers/basic.py:486` (`reasoning.belief.BeliefNetwork`) | reclassify/relocate-module or invert (Batch 2) |
| events -> workflow | direct (3) | `events/cross_subscribers/handlers/strategic.py:280`; `events/subscribers/workflow_automation.py:50,51` (`workflow.engine/types`) | reclassify/relocate-module or invert (Batch 2) |
| events -> server | direct (18) | SPLIT (see below) | Batch 1 + Batch 2 |

`events -> server` (18 imports) split by target:
- Batch 1 (server-utility downshift): `events/dispatcher.py:40`, `events/async_dispatcher.py:155`, `events/handler_events.py:93`, `events/types.py:461` -> `server.middleware.tracing`; `events/dispatcher.py:45` -> `server.stream.events` (schemas); `events/cross_subscribers/{admin.py:22,dispatch.py:27,handlers/culture.py:19,handlers/knowledge_mound.py:24,handlers/validation.py:21}` -> `server.prometheus_cross_pollination`.
- Batch 2 (relocate/invert subscriber + dispatcher glue): `events/dispatcher.py:44`, `events/subscribers/execution_handlers.py:249`, `events/cross_subscribers/handlers/culture.py:230` -> `server.stream.emitter` / `server.stream.state_manager`; `events/async_dispatcher.py:154`, `events/dispatcher.py:193,476,503`, `events/cross_subscribers/handlers/basic.py:267` -> `server.handlers.webhooks` (`generate_signature`, `get_webhook_store`). **`server.handlers.webhooks` is a Tier-3 path** (`aragora/server/handlers/`); the HMAC `generate_signature` helper extraction down to foundation/security coordinates with P4b (see section 6).

Rationale: the `events.subscribers` / `events.cross_subscribers` packages are
application-layer glue (they orchestrate debate, knowledge, memory, workflow,
nomic, ranking, reasoning) mislocated in infra `events`. Preferred fix is the
EventBus registry inversion (events exposes only dispatch + registration;
application code registers handlers) or relocation of the subscriber package to
an application home. The events CORE dispatcher (`dispatcher.py`,
`async_dispatcher.py`, `handler_events.py`, `types.py`) keeps only same-or-lower
imports once its `server.middleware.tracing` / `server.stream.events` edges are
Batch-1 downshifted and its `server.stream.emitter` / `server.handlers.webhooks`
edges are inverted.

#### `aragora.queue` (8 edges) -> Batch 1 (server-utility downshift) + Batch 2 (worker relocation/inversion)

| Edge | D/I | Importer file:line -> imported | Disposition |
|---|---|---|---|
| queue -> agents | direct (3) | `queue/worker.py:21,309`; `queue/workers/gauntlet_worker.py:212` (`agents.base`) | reclassify/relocate-module or invert (Batch 2) |
| queue -> debate | direct (1) | `queue/worker.py:311` (`debate.orchestrator.Arena`) | reclassify/relocate-module or invert (Batch 2) |
| queue -> gauntlet | direct (4) | `queue/workers/gauntlet_worker.py:31,213,218,448` (`gauntlet`, `gauntlet.storage`) | reclassify/relocate-module or invert (Batch 2) |
| queue -> integrations | direct (1) | `queue/workers/routing_worker.py:230` (`integrations.email_reply_loop`) | reclassify/relocate-module or invert (Batch 2) |
| queue -> memory | direct (1) | `queue/workers/consensus_healing_worker.py:208` (`memory.consensus`) | reclassify/relocate-module or invert (Batch 2) |
| queue -> nomic | direct (1) | `queue/workers/testfixer_worker.py:12` (`nomic.testfixer.http_api`) | reclassify/relocate-module or invert (Batch 2) |
| queue -> ranking | direct (1) | `queue/workers/gauntlet_worker.py:356` (`ranking.elo.EloSystem`) | reclassify/relocate-module or invert (Batch 2) |
| queue -> server | direct (5) | SPLIT: Batch 1 -> `queue/tracing.py:43,48` (`server.middleware.{correlation,tracing}`), `queue/webhook_worker.py:309` (`server.http_client_pool`); Batch 2 -> `queue/workers/gauntlet_worker.py:235` (`server.stream.gauntlet_emitter`), `queue/workers/routing_worker.py:212` (`server.debate_origin`) | Batch 1 + Batch 2 |

Rationale: `queue.worker` + `queue/workers/*` are application workers (they run
`Arena`, gauntlet, agents, routing) mislocated in infra `queue`. Preferred fix
is a job-handler registry inversion (queue is the Redis Streams transport;
application registers worker handlers) or relocation of the workers to an
application home.

#### `aragora.observability` (4 edges) -> Batch 1 (server-utility downshift) + Batch 3 (connectors/integrations/knowledge)

| Edge | D/I | Importer file:line -> imported | Disposition |
|---|---|---|---|
| observability -> server | direct (8) | `observability/alerting.py:336,523`, `observability/slo.py:1193,1229` (`server.http_client_pool`); `observability/otel.py:741`, `observability/trace_correlation.py:91`, `observability/tracing.py:919` (`server.middleware.tracing`); `observability/trace_correlation.py:140` (`server.metrics.API_REQUESTS, API_LATENCY`) | real-move-down per architecture section 6 (Batch 1). All targets are Batch-1 downshift surfaces, so this edge clears FULLY at Batch 1. |
| observability -> connectors | direct (1) | `observability/slo_alert_bridge.py:181` (`connectors.devops.pagerduty`) | invert-dependency (Batch 3): alert-sink registry; pagerduty connector registers, observability publishes. |
| observability -> integrations | direct (2) | `observability/metrics/slo.py:421,592` (`integrations.webhooks.get_dispatcher`) | invert-dependency (Batch 3): webhook-dispatch registry/callback. |
| observability -> knowledge | direct (1) | `observability/metrics/km.py:526` (`knowledge.mound.metrics.get_metrics, HealthStatus`) | reclassify/relocate-module (Batch 3): relocate the KM-specific metrics adapter to `knowledge.mound.metrics` (shim at `observability.metrics.km`), or invert (KM publishes health). `aragora/knowledge/mound/metrics` is a Tier-2 path. |

#### `aragora.billing` (4 edges) -> Batch 1 (server-utility downshift) + Batch 3 (connectors/knowledge/agents/auth)

| Edge | D/I | Importer file:line -> imported | Disposition |
|---|---|---|---|
| billing -> server | direct (4) | SPLIT: Batch 1 -> `billing/budget_alert_notifier.py:422` (`server.http_client_pool`), `billing/cost_tracker.py:36` (`server.prometheus.record_cost_usd`), `billing/cost_tracker.py:606` (`server.stream.events.StreamEvent, StreamEventType`); Batch 3 -> `billing/auth/context.py:72` (`server.middleware.auth.extract_client_ip`) | Batch 1 + Batch 3 |
| billing -> connectors | direct (2) | `billing/budget_alert_notifier.py:350,392` (`connectors.chat.{slack,teams}`) | invert-dependency (Batch 3): notification/channel registry; connectors register as alert sinks. |
| billing -> knowledge | direct (2) | `billing/cost_tracker.py:47,1272` (`knowledge.mound.adapters.cost_adapter.CostAdapter`) | invert-dependency (Batch 3): KM cost_adapter registers as a cost sink; billing publishes cost events. |
| billing -> agents | direct, **TYPE_CHECKING-only** (1) | `billing/calibration_cost_bridge.py:41` (`agents.calibration.CalibrationTracker, CalibrationSummary`, under `if TYPE_CHECKING:`) | **drop-type-only-import** (Batch 3): remove the `TYPE_CHECKING` import (file already has `from __future__ import annotations`), use stringized annotations. No runtime coupling, no shim, NOT ignore_imports. (Seal alternative: `exclude_type_checking_imports = True` on the contract removes exactly this one edge; the code-side drop is preferred to keep the contract strict.) |

For `billing/auth/context.py:72`, `extract_client_ip` is a pure request-IP
parser with no server semantics; real-move-down to a foundation helper
(`utils`), shim at `server.middleware.auth`.

#### `aragora.storage` (4 edges) -> Batch 4

| Edge | D/I | Importer file:line -> imported | Disposition |
|---|---|---|---|
| storage -> server | direct (2) | `storage/redis_utils.py:68,120` (`server.redis_cluster.get_cluster_client`) | real-move-down (Batch 4): `server.redis_cluster` is a Redis cluster client utility mislocated in interface `server`; move down to `storage`/`caching`, shim at `server.redis_cluster`. |
| storage -> connectors | direct (1) | `storage/migrations/encrypt_existing_data.py:143` (`connectors.enterprise.sync_store`) | invert-dependency or relocate (Batch 4): sync-store provider registry, or relocate the encryption migration to ops/application. |
| storage -> gauntlet | direct (1) | `storage/receipt_store.py:1260` (`gauntlet.signing`) | real-move-down or invert (Batch 4): move the signing primitive down to foundation/security (shim at `gauntlet.signing`), or `receipt_store` takes a signer. **ODR right-of-way: `gauntlet/` + receipts territory; run an ODR open-PR conflict check first** (mission invariant 7). |
| storage -> reasoning | direct (2) | `storage/provenance_store.py:16,618` (`reasoning.provenance`) | reclassify/relocate-module or real-move-down (Batch 4): relocate `provenance_store` up to `reasoning` (domain), or move the shared provenance data type down to foundation. **PR title must avoid the Tier-3 keyword `persistence`.** |

#### `aragora.security` (3 edges) -> Batch 4 (Tier 3, security/ paths)

| Edge | D/I | Importer file:line -> imported | Disposition |
|---|---|---|---|
| security -> connectors | direct (2) | `security/migration.py:325,785` (`connectors.enterprise.sync_store.get_sync_store`) | invert-dependency or relocate (Batch 4): sync-store provider registry, or relocate migration to ops/application. |
| security -> gateway | direct (2) | `security/approval_enforcer.py:324,465` (`gateway.openclaw_policy`) | invert-dependency or relocate (Batch 4): policy-provider registry, or relocate `approval_enforcer` to application. |
| security -> server | indirect | chains: `security.migration -> audit.unified -> server.middleware.audit_logger`; `security.anomaly_detection -> events.dispatcher -> server.handlers.webhooks` | transitive (Batch 4 + depends on Batch 1/2). Chain 2 clears with the events->server clearance (Batch 1/2). Chain 1 runs through unlayered `audit`; clear by inverting `security.migration`'s `audit.unified` usage (logging protocol), or via a later `audit_logger` downshift. |

**Tier note:** `aragora/security/` is a Tier-3 merge-gate path; all three
security sub-features require operator settlement.

---

## 4. Authorized `ignore_imports` (exactly 3 preserve-by-design cases)

These are the ONLY `ignore_imports` entries. They are added to `.importlinter`
by `p4a-contracts-seal` (editing `.importlinter` does NOT touch the #8461
path-frozen `exceptions.py`). All other edges use real moves / inversion /
relocation / drop-type-only.

1. **`aragora.exceptions -> aragora.connectors.exceptions`**
   (`aragora/exceptions.py:1148`, module-scope `try/except ImportError` re-export).
   Justification: VAL-P4A-005 preserve-by-design graceful-degradation re-export;
   VAL-P4B-004 clause (c) sanctions `ignore_imports` for it. Must never become an
   eager hard dependency.
2. **`aragora.exceptions -> aragora.server.handlers.exceptions`**
   (`aragora/exceptions.py:1203`, inside `__getattr__` lazy fallback).
   Justification: the deliberate `__getattr__` graceful-degradation fallback
   (VAL-P4A-005); VAL-P4B-004 clause (b) exempts this fallback body and clause (c)
   sanctions the `ignore_imports`. Must never be converted to an eager
   module-scope server import.
3. **`aragora.utils.redis_cache -> aragora.caching.redis`**
   (`aragora/utils/redis_cache.py:12`, the #8672 one-release deprecation shim).
   Justification: `redis_cache.py` is a deprecation shim that must keep importing
   from `caching` for one release (shim invariant 3). Do NOT delete the shim early
   and do NOT reclassify `utils`. **TODO: remove this `ignore_imports` when the
   `redis_cache` shim is retired post-one-release.** This edge is NOT in the
   baseline (it post-dates the freeze), so the seal adds only the `ignore_imports`;
   there is no baseline string to hand-remove for it.

`errors -> server` is explicitly NOT an `ignore_imports`: section 3.1 proves
`server/errors.py` is bounded (only downward import is foundation
`aragora.exceptions`), so the real inversion (move-down + shim) is taken.

---

## 5. Batched, Tier-labeled implementation plan (downshift-first)

Ordering follows the binding policy: the architecture section 6 server-surface
DOWNSHIFT thread runs FIRST (it clears the most edges and pre-satisfies the
VAL-P4B-004 sweep). Each batch is sized for bounded structex features (<=800 LOC
and one bounded change per PR; <=8 open mission PRs). An edge clears from the
baseline only when its LAST direct import is cut (section 1, mechanic 3), so
`billing/events/queue -> server` are removed from the baseline only after both
their Batch-1 and Batch-2/3 portions land.

Every moved importable symbol gets a `DeprecationWarning` shim at the old path
plus a `library/shims.md` row. Each PR runs VAL-P4A-013 (`make test-smoke`) as
the post-PR canary and hand-removes the resolved edge string(s) from
`import_contracts_baseline.json` (section 7).

### Batch 1 - Architecture section 6 server-surface DOWNSHIFT (FIRST; highest leverage)

Move these interface-resident shared surfaces DOWN, each with a
`DeprecationWarning` shim at the old `server.*` path:

| Surface moved | Symbols | New home (architecture section 6) |
|---|---|---|
| `server.metrics` | `API_REQUESTS`, `API_LATENCY`, + the audit-steer `ACTIVE_DEBATES` / `track_debate_outcome` move (reconcile the duplicate `ACTIVE_DEBATES` already in observability) | `observability` |
| `server.prometheus` | `record_cost_usd`, ... | `observability` |
| `server.prometheus_cross_pollination` | `record_km_outbound_event`, ... | `observability` |
| `server.middleware.tracing` | `get_trace_id`, `get_span_id` | `observability` / `foundation` |
| `server.middleware.correlation` | correlation-id helpers | `observability` / `foundation` |
| `server.http_client_pool` | `get_http_pool` | `observability` / `foundation` |
| `server.stream.events` | `StreamEvent`, `StreamEventType` (schemas) | `events` |

Suggested sub-features (each Tier 1-2; none touch `server/handlers/`, parser,
review_queue, or workflows):
- **1a** `server.metrics` + `server.prometheus` + `server.prometheus_cross_pollination` -> `observability` (incl. ACTIVE_DEBATES/track_debate_outcome reconcile). Confirm no external consumer of the `server.metrics` path first (audit-steer).
- **1b** `server.middleware.tracing` + `server.middleware.correlation` -> `observability`/`foundation`.
- **1c** `server.http_client_pool` -> `observability`/`foundation`.
- **1d** `server.stream.events` schemas -> `events`.

Edges cleared by Batch 1:
- **`observability -> server`: FULLY** (all of http_client_pool + middleware.tracing + server.metrics).
- `billing -> server`: partial (http_client_pool, prometheus, stream.events).
- `events -> server`: partial (middleware.tracing, prometheus_cross_pollination, stream.events).
- `queue -> server`: partial (middleware.{correlation,tracing}, http_client_pool).

### Batch 2 - events + queue application-glue relocation / inversion

Reclassify/relocate (or invert via registry) the application-layer subscribers
and workers mislocated in infra `events` and `queue`:
- **2a events subscribers**: relocate `events.cross_subscribers` + `events.subscribers` (+ `security_events`, `security_dispatcher`, `arena_bridge`) to an application home, OR invert via the EventBus registry. Clears `events -> {agents, debate, knowledge, memory, nomic, ranking, reasoning, workflow}` and the subscriber-side `events -> server` imports (`server.stream.state_manager`, `server.stream.emitter`, remaining `server.prometheus_cross_pollination`/`server.handlers.webhooks.get_webhook_store`).
- **2b queue workers**: relocate `queue.worker` + `queue/workers/*` to an application home, OR invert via a job-handler registry. Clears `queue -> {agents, debate, gauntlet, integrations, memory, nomic, ranking}` and the worker-side `queue -> server` imports (`server.stream.gauntlet_emitter`, `server.debate_origin`).
- **2c events dispatcher webhook signing** (Tier-3-flagged): extract the HMAC `generate_signature` helper out of `server/handlers/webhook_management.py` (a Tier-3 path) down to foundation/security so `events.dispatcher`/`async_dispatcher` stop importing `server.handlers.webhooks`. Coordinate file boundaries with `p4b-handlers-*` (section 6).

Tier: 2a/2b Tier 1-2 (events/, queue/ are infra). 2c touches
`aragora/server/handlers/` -> Tier 3 (operator settlement), or fold into the
P4b handlers batch that owns `webhook_management.py`.

### Batch 3 - observability + billing connectors / integrations / knowledge

- **3a observability sinks**: invert `observability/slo_alert_bridge.py` -> `connectors.devops.pagerduty`; invert `observability/metrics/slo.py` -> `integrations.webhooks`; relocate/invert `observability/metrics/km.py` -> `knowledge.mound.metrics`.
- **3b billing notifiers/sinks**: invert `billing/budget_alert_notifier.py` -> `connectors.chat.{slack,teams}`; invert `billing/cost_tracker.py` -> `knowledge.mound.adapters.cost_adapter`.
- **3c billing misc**: drop the `TYPE_CHECKING` `billing -> agents` import; move `extract_client_ip` down from `server.middleware.auth` (clears the last `billing -> server` import).

Tier: observability/ is Tier 2; `knowledge/mound/metrics` is Tier 2; billing/ is
Tier 1. Avoid Tier-3 title keywords. Clears `observability -> {connectors,
integrations, knowledge}`, `billing -> {connectors, knowledge, agents}`, and the
final `billing -> server` import.

### Batch 4 - storage + security edges

- **4a storage**: real-move-down `server.redis_cluster` -> `storage`/`caching` (clears `storage -> server`); invert/relocate `storage/migrations/encrypt_existing_data.py` -> `connectors.enterprise.sync_store`; move/invert `storage/receipt_store.py` -> `gauntlet.signing` (**ODR conflict check first**); relocate/move `storage/provenance_store.py` -> `reasoning.provenance` (**title must avoid `persistence`**).
- **4b security (Tier 3, operator settlement)**: invert/relocate `security/migration.py` -> `connectors.enterprise.sync_store`; invert/relocate `security/approval_enforcer.py` -> `gateway.openclaw_policy`. `security -> server` (indirect) clears once Batch 1/2 cut the events chain and the `security.migration` audit-path is inverted.

Tier: 4a Tier 1-2 (storage/), with ODR coordination on the gauntlet/receipts
edge; 4b Tier 3 (security/).

### Batch 5 - protocols.a2a.server + protocols.bridge move-up

Relocate `aragora.protocols.a2a.server` and `aragora.protocols.bridge` UP out of
the foundation `protocols` package to an application/interface home (they run
agents/Arena/gauntlet/MCP), with `DeprecationWarning` shims at the old protocols
paths. Clears all 12 `protocols -> *` edges (4 direct + 8 indirect) in one
bounded change. Tier 1-2 (protocols/ is foundation; the move targets are
interface/application; no Tier-3 paths or keywords).

### Batch 6 - foundation-primitives

- **6a** `core_types -> debate`: real-move-down `DebateProtocol` to foundation, shim at `aragora.debate.protocol`.
- **6b** `errors -> server`: real-move-down the API error hierarchy to a foundation errors home, preserve `aragora.errors.API*`, shim at `aragora.server.errors`.
- **6c** `config -> observability`: invert `config/validator.py` -> `control_plane.leader` (registry/foundation helper).
- **6d** `utils` domain helpers: relocate `utils.semantic_extraction` up to a domain home; real-move-down the `async_utils` event-loop accessor (clears `utils -> storage`); cut the `utils.cache -> services` chain. Together these clear `utils -> {agents, storage, connectors, knowledge, resilience}` (the indirect `connectors` chain also needs the seal's exceptions->connectors ignore).

Tier 1-2 (foundation + domain paths). Re-confirm path-freeze on
`config/validator.py`, `utils/semantic_extraction.py`, `utils/async_utils.py`,
`utils/cache.py`, `core_types.py`, `errors.py` at execution time.

### Seal - `p4a-contracts-seal` (fulfills VAL-P4A-006 + VAL-P4A-013)

After the batches land: add the 3 authorized `ignore_imports` to `.importlinter`
(section 4), hand-remove any residual foundation/infra strings from
`import_contracts_baseline.json`, then verify the foundation/infra violation
collections are EMPTY and `python3 scripts/ci/check_import_contracts.py --layers
foundation,infrastructure` exits 0, plus VAL-P4A-013 `make test-smoke` green.
Tier 1-2 (`.importlinter` and the baseline JSON are currently path-free).

---

## 6. File-boundary coordination with p4b-handlers-* (VAL-P4B-004 pre-satisfaction)

VAL-P4A-006 (import-linter foundation/infra == 0) and VAL-P4B-004 (server-import
sweep == 0 contribution from foundation/infra members) are **two views of the
same work**: architecture line 580 records the events/stream-schema cleanup as
"informational" at end-P4a because it lands via the VAL-P4B-004 sweep. So doing
the foundation/infra -> server elimination here **PRE-SATISFIES** the
VAL-P4B-004 sweep for the foundation/infra members. Do NOT duplicate it in P4b.

File-boundary rule (utilities vs handlers = different files):

- **This P4a thread owns the server-resident UTILITIES**: `server.metrics`,
  `server.prometheus`, `server.prometheus_cross_pollination`,
  `server.middleware.{tracing,correlation}`, `server.http_client_pool`,
  `server.stream.events` (schemas), `server.redis_cluster`. These are
  non-`handlers/` files; moving them down is Tier 1-2.
- **P4b owns the `server/handlers/*` decomposition** (Tier-3 batches). The only
  overlap is the HMAC `generate_signature` helper in
  `server/handlers/webhook_management.py` (Batch 2c) and the `get_webhook_store` /
  `server.stream.gauntlet_emitter` / `server.debate_origin` server surfaces that
  events/queue subscribers reach into. Coordinate so the handler file is edited by
  exactly one thread: extract the foundation-level helper (signature) in the P4a
  events thread OR fold it into the P4b batch that owns `webhook_management.py`,
  never both.

VAL-P4B-004's conditional `tests/architecture/test_layering_baseline.py` clause
is vacuous today (the file does not exist on `origin/main`); if a P4b/P0 PR adds
it later, the seal must keep it green.

---

## 7. Baseline hand-shrink mechanics (shrink-only)

- Each implementation PR **hand-removes** the exact resolved
  `aragora.X -> aragora.Y` string(s) from the `violations` list in
  `scripts/baselines/import_contracts_baseline.json`, keeping `frozen_from_ref`
  unchanged. Shrink-only: never add a string.
- An `aragora.X -> aragora.server` (or any multi-import) string may be removed
  ONLY after the PR has cut its LAST contributing import (verify with
  `python3 scripts/ci/check_import_contracts.py --layers foundation,infrastructure`
  reporting the edge gone, or a targeted grimp re-measure on the PR head).
- `check_import_contracts.py --freeze` is **unusable** here: without `--adopt` it
  refuses to grow, and the current tree would try to ADD the ambient
  `aragora.swarm -> aragora.cli` edge and the #8672 `aragora.utils ->
  aragora.caching` edge. Always hand-edit the `violations` list; never run
  `--freeze`/`--adopt` on this baseline.
- Regeneration carve-out: PRs that change module structure normally regenerate
  `docs/METRICS.md` + `aragora/module_tiers.yaml`, but BOTH are path-frozen by
  open PRs (#8460/#8461/#8382/#8505/#8627/#8694 and others). Ship the structural
  change WITHOUT the regen and record the generated-file drift in the PR handoff
  `discoveredIssues` for the phase merge-train single-file regen (the established
  pattern; not a deviation).

---

## 8. Out of scope

- `aragora.swarm -> aragora.cli` (application-layer, sibling-fleet ambient edge):
  excluded by `--layers foundation,infrastructure`. Never touch `aragora/swarm/`.
- P4b server/handlers decomposition, cycles, and server-imported-by reduction
  (VAL-P4B-001/002/003): separate milestone; only the file-boundary coordination
  in section 6 applies.

---

## 9. Return-to-orchestrator batch list (sub-features to create)

Recommended bounded structex implementation sub-features, in dependency order
(downshift-first), plus the seal:

1. `p4a-server-downshift-metrics` (Batch 1a; Tier 1-2)
2. `p4a-server-downshift-middleware` (Batch 1b; Tier 1-2)
3. `p4a-server-downshift-httppool` (Batch 1c; Tier 1-2)
4. `p4a-server-downshift-stream-schemas` (Batch 1d; Tier 1-2)
5. `p4a-events-subscribers-relocate` (Batch 2a; Tier 1-2)
6. `p4a-queue-workers-relocate` (Batch 2b; Tier 1-2)
7. `p4a-events-webhook-signing` (Batch 2c; Tier 3 - coordinate with p4b webhooks)
8. `p4a-observability-sinks-invert` (Batch 3a; Tier 1-2)
9. `p4a-billing-sinks-invert` (Batch 3b/3c; Tier 1-2)
10. `p4a-storage-edges` (Batch 4a; Tier 1-2; ODR check on gauntlet.signing; avoid `persistence` in title)
11. `p4a-security-edges` (Batch 4b; Tier 3 - operator settlement)
12. `p4a-protocols-moveup` (Batch 5; Tier 1-2)
13. `p4a-foundation-primitives` (Batch 6; Tier 1-2)
14. `p4a-contracts-seal` (adds the 3 authorized ignore_imports; verifies VAL-P4A-006 + VAL-P4A-013)

Some larger sub-features (events subscribers, queue workers) may need to split
across 2 PRs to stay <=800 LOC; the orchestrator sizes the final set.
