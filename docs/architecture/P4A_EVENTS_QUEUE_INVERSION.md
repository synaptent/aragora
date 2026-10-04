# P4a EventBus / Job-Queue Registry Inversion (events + queue relocate-UP)

> **Status:** Implemented; final-main seal reconciliation (2026-07-13).
> **Milestone:** `p4a-layering-foundation`.
> **Supersedes:** the cancelled relocate batches `p4a-events-subscribers-relocate` (2a)
> and `p4a-queue-workers-relocate` (2b).
> **Scope:** resolves the layering inversion for BOTH `aragora.events`
> (`cross_subscribers` + `subscribers` + `security_events`/`security_dispatcher`/`arena_bridge`)
> AND the sibling `aragora.queue` (`worker` + `workers.*`), with grimp evidence.
> This document originally specified the homes, domain-free registry, bootstrap,
> relocate-UP no-shim exemption, batch breakdown, and exact AGENTS.md / shims.md
> policy text. The final-main reconciliation below records the landed result.

## 0. TL;DR

`aragora.events` (infrastructure) and `aragora.queue` (infrastructure) each import
UP into `domain`/`application`/`interface` because domain-coupled *handlers*
(`cross_subscribers`/`subscribers`) and *workers* (`queue.workers.*`) live inside
the infra package. The sanctioned fix (per
`docs/architecture/P4A_LAYERING_DISPOSITION.md` lines 185-190, 337) is the
**EventBus / job-handler registry inversion**:

1. The events/queue packages keep only a **domain-free registry + dispatch surface**
   (`register_subscriber`/`register_factory`/`get`/`reset`/`SubscriberStats`,
   and the queue transport). ZERO domain imports (eager, lazy, or `TYPE_CHECKING`).
2. Each domain-coupled handler/worker **moves to a home at or above the highest
   layer it imports** (prefer the coupled domain package; use an existing
   application/interface home for multi-domain/server couplings). It
   **self-registers on import**.
3. A single explicit **bootstrap** at each composition root imports the relevant
   subscriber/worker modules to guarantee registration.
4. The moved paths get **NO re-export shim** at their old `events`/`queue`
   locations (a shim re-creates the layering edge - the proven failure mode of
   worker `5f92db63`). ALL consumers (runtime + the monkeypatching test files:
   ~7 on the moved handler paths, ~12 total including the §6.3 SPLIT symbols)
   are **repointed** to the new homes. This is a *sanctioned relocate-UP
   exemption* from the usual "shim every moved path" rule (§8).

Grimp proves (§7) that after the inversion,
`check_import_contracts.py --layers foundation,infrastructure` clears
`events -> {agents,debate,knowledge,memory,nomic,ranking,reasoning,workflow}` and
`queue -> {agents,debate,gauntlet,integrations,memory,nomic,ranking,server}` plus
the subscriber-side `events -> server`, **with zero new un-baselined edge**. At
that batch boundary, the residual `events -> server` was owned by Batch 1b-sweep
and Batch 2c (core dispatcher), not E1-E7b. Those direct contributors subsequently
cleared; §3 and §7 record the sealed final-main result.

## 1. Why relocate-UP + a re-export shim is impossible (the 5f92db63 result)

Worker `5f92db63` (handoff
`handoffs/2026-07-01T02-52-44-111Z__p4a-events-subscribers-relocate__5f92db63*.json`)
empirically proved that **relocate-UP plus a mandatory re-export shim CANNOT clear
`events -> domain`**:

- The usual VAL-CROSS-004 rule ("shim every moved path") requires an
  identity-preserving re-export at the old path so external callers and the ~7
  handler-path test files (plus the §6.1 SPLIT-symbol test files) that
  `@patch(...)` the *old* submodule paths keep working
  (e.g. `@patch("aragora.events.cross_subscribers.handlers.validation.record_km_inbound_event")`).
- An **eager** identity-preserving shim at `aragora.events.<x>` re-imports the
  relocated module, so `aragora.events.<x> -> <home> -> aragora.<domain>` is
  re-created. grimp counts indirect **and** lazy chains through the shim, so
  `resolved_violations == {}` after relocation + eager shim.
- No relocation target avoids a violation *while a shim exists*: a domain/unlayered
  home keeps `events -> domain`; an `application` home creates a NEW un-baselined
  `events -> application` (fail-on-new); a `foundation` home makes
  `foundation -> domain`.

**Conclusion:** the only way to clear the edge is to *remove the events/queue
package's import of the domain module entirely* - i.e. the domain-coupled code must
leave `events`/`queue` **and leave behind no re-export**. That forces (a) a
domain-free registry surface that stays, and (b) a no-shim relocate-UP with all
consumers repointed. Both are specified below.

## 2. How the checker attributes edges (empirically proven: direct first-hop)

`scripts/ci/check_import_contracts.py` records each violation as
`f"{importer} -> {imported}"` at **layer-package granularity**
(`aragora.events -> aragora.debate`) straight from import-linter's
`LayersContract` metadata; import-linter in turn calls grimp's
`find_illegal_dependencies_for_layers`. We replicated that exact primitive with
grimp 3.14 against the local tree (`/tmp/sx_grimp_evidence.py`). Decisive finding:

> **Every `events -> domain` / `queue -> domain` route is `[head] -> [tail]` with
> an EMPTY middle.** grimp attributes an illegal layer edge to the **direct
> first-hop importer**. A transitive `events.dispatcher -> server.* -> ... ->
> debate.*` chain is **NOT** collapsed into `events -> debate`; it is attributed
> as `events -> server` (the first illegal hop) plus a legal downward
> `server -> debate`.

Sample (verbatim grimp output, current tree at `fce9aa5e09`):

```
aragora.events -> aragora.debate   (9 route(s))
      route: [aragora.events.cross_subscribers.handlers.basic] -> [aragora.debate.selection_feedback]
      route: [aragora.events.security_dispatcher] -> [aragora.debate.orchestrator]
aragora.events -> aragora.server   (10 route(s))
      route: [aragora.events.dispatcher] -> [aragora.server.middleware.tracing]
```

**Implication (the batch's core enabler):** cutting the *direct* subscriber/handler
imports clears `events -> domain`. The dispatcher-side `events -> server` persisted
at the E1-E7b boundary and was assigned to Batch 1b-sweep + Batch 2c (§7); it has
since cleared on final main. Likewise for `queue`.

Two attribution nuances captured for accuracy:
- **Unlayered pass-through.** `subscribers.notification_handlers` shows up under
  `events -> server` because it imports the *unlayered* `aragora.notifications`
  package, through which grimp routes to `server`. Moving `notification_handlers`
  to a delivery home removes it from the `events -> server` head set.
- **`registry` head of `events -> server`** is a transitive artifact through
  `security_events` (which stays but is de-coupled in §5.1); `events.registry`
  has **no direct** `server` import. It is immaterial - `events -> server` stays
  regardless because `dispatcher`/`async_dispatcher` import `server.middleware.tracing`
  directly, and that edge is baselined + owned by Batch 1b-sweep/2c.

## 3. Pre-inversion coupling map and final disposition

The original grimp census used `find_illegal_dependencies_for_layers` with the five
`.importlinter` layers and container `aragora`. The events rows below are reconciled
to final main after E2c-E7b and the later dispatcher/notification boundary work.
Queue rows remain the design-time source census for the Q batches.

### 3.1 `aragora.events` (pre-inversion: 9 edges; final: zero contract edges)

| Original edge | Final-main disposition |
|---|---|
| events -> agents | Cleared by E7a: the security-debate runner moved to `aragora.debate.security_response` behind the domain-free callback seam. |
| events -> debate | Cleared by E4/E7a/E7b: reactions moved to `aragora.debate.event_subscribers`, security composition moved to `aragora.debate.security_response`, and `arena_bridge` moved to `aragora.debate.arena_bridge`. |
| events -> knowledge | Cleared by E2a-E2c: live KM reactions moved to `aragora.knowledge.event_subscribers`; obsolete subscriber modules were deleted. |
| events -> memory | Cleared by E3: the three live `handlers.basic` reactions moved to `aragora.memory.event_subscribers`. |
| events -> nomic | No-code stale edge after E2c deleted `subscribers.testfixer_handlers`; its baseline entry was hand-shrunk by E5. |
| events -> ranking | No-code stale edge after E2c deleted `subscribers.execution_handlers`; its baseline entry was hand-shrunk by E3. No ranking home was created. |
| events -> reasoning | Cleared by E3: `vote_to_belief` moved to `aragora.reasoning.event_subscribers`. |
| events -> server | Subscriber reactions moved to `aragora.server.event_subscribers`; dispatcher and notification/channel boundaries were inverted by their owning features. The final aggregate exception route terminates at the exact authorized `aragora.exceptions -> aragora.server.handlers.exceptions` ignore. |
| events -> workflow | Cleared by E5: the live workflow brake and callable post-debate subscriber moved to `aragora.workflow.event_subscribers`; the unregistered legacy delegate was removed. |

### 3.2 `aragora.queue` (baseline: 8 edges)

| Edge | Direct contributor modules (heads) |
|---|---|
| queue -> agents | `worker` (`agents.base`), `workers.gauntlet_worker` (`agents.base`) |
| queue -> debate | `worker` (`debate.orchestrator.Arena`) |
| queue -> gauntlet | `workers.gauntlet_worker` (`gauntlet`, `gauntlet.storage`) |
| queue -> integrations | `workers.routing_worker` (`integrations.email_reply_loop`) |
| queue -> memory | `workers.consensus_healing_worker` (`memory.consensus`) |
| queue -> nomic | `workers.testfixer_worker` (`nomic.testfixer.http_api`) |
| queue -> ranking | `workers.gauntlet_worker` (`ranking.elo.EloSystem`) |
| queue -> server | `workers.gauntlet_worker` (`server.stream.gauntlet_emitter`), `workers.routing_worker` (`server.debate_origin`) |

> The Batch-1 `queue -> server` contributors (`queue/tracing.py`,
> `queue/webhook_worker.py`) already cleared in Batch 1b/1c, so **`queue -> server`
> is owned entirely by this batch** (both remaining heads are workers).

## 4. The inversion design

### 4.1 Domain-free registry surface (STAYS in events/queue; no move, no shim)

`aragora.events.cross_subscribers` keeps a **domain-free** registry + dispatch core:

```python
# aragora/events/cross_subscribers/__init__.py + manager.py  (ZERO domain imports)
def register_subscriber(name: str, subscriber: object) -> None: ...
def register_factory(name: str, factory: Callable[[], object]) -> None: ...
def get_cross_subscriber_manager() -> "CrossSubscriberManager": ...   # public accessor - UNCHANGED
def reset_cross_subscriber_manager() -> None: ...

# SubscriberStats is REUSED as-is (already domain-free); see the note below:
from aragora.events.subscribers.config import SubscriberStats   # existing, domain-free

class CrossSubscriberManager:     # dispatch-only; iterates registered subscribers
    def dispatch(self, event: StreamEvent) -> None: ...
```

- **`SubscriberStats` is REUSED, not redefined or renamed.** The domain-free stats
  type already exists at `aragora.events.subscribers.config.SubscriberStats` (a rich,
  domain-free dataclass - `name`, `events_processed/failed/skipped/retried`, latency
  percentiles) and is ALREADY re-exported by `cross_subscribers` (imported in
  `cross_subscribers/manager.py:26`, `dispatch.py`, `admin.py`) and by
  `aragora.events.__init__`. The domain-free registry KEEPS that single definition
  and its re-export path unchanged - it does NOT introduce a second `SubscriberStats`.
  No rename is needed: `aragora/events/subscribers/config.py` (SubscriberStats +
  RetryConfig + AsyncDispatchConfig) is domain-free and STAYS in `events`; only the
  domain-coupled handler modules under `subscribers/` (debate/execution/mound/
  testfixer/notification/workflow_automation) move.
- Today `manager.py` (570 LOC) composes domain-coupled **mixins**
  (`BasicHandlersMixin`, `CultureHandlersMixin`, ...). The inversion converts the
  manager into a **registry-backed dispatcher**: it holds a list/dict of registered
  subscriber objects and fans events out to them. The mixin imports are removed as
  each handler group relocates (§4.4).
- `get_cross_subscriber_manager()` **stays at
  `aragora.events.cross_subscribers`** and keeps returning a working manager. This
  is the IDEAL outcome required by the spec: the ~13 lazy consumers
  (debate/memory/server/cli) that call `get_cross_subscriber_manager()` do **not**
  move or break - only the manager's *internals* change (domain-free), not its
  public accessor or import path.
- `aragora.queue` keeps the transport (`base`, `config`, `job`, `retry`, the
  `DebateWorker` base + the domain-free `DebateExecutor` type alias) plus a
  **domain-free job-handler registry** (`register_worker`/`register_job_handler`
  + `get`/`reset`). Only the domain-coupled `create_default_executor` factory
  re-export is **dropped** from `queue/__init__.py` (no re-export shim - a
  re-export would re-create `queue -> {agents,debate}`, §5.2). `DebateWorker` and
  `DebateExecutor` re-exports STAY (both are public, domain-free).

### 4.2 Home-assignment rule (the governing invariant)

> **A relocated handler/worker must live in a package whose layer is at or above
> the highest layer among all packages it imports** - **counting eager, lazy, and
> `TYPE_CHECKING` imports** (grimp counts all three). ("home layer >= max import
> layer.")

Because cross-imports *within* a layer are legal (siblings are colon-separated =
non-independent in `.importlinter`), a handler that touches only `domain` packages
can live in ANY domain package and import its sibling domains freely. A handler
that reaches `application` (workflow/nomic) must live in `application`; one that
reaches `interface` (server/notifications-delivery) must live in `interface`.

This rule is what guarantees **no new upward edge** at the destination (§7 proves
the source edges clear; this rule proves the destination introduces none).

### 4.3 Home assignments (prefer the coupled domain; existing app/interface homes)

The original handlers were multi-reaction classes; the inversion **split each class
by reaction** and filed each reaction under the home matching its target layer. No
new top-level package was introduced (no `aragora/orchestration`), so this work
created **no `module_tiers.yaml` drift** (§9).

| New home (self-registering module) | Layer | Reactions relocated here (source) |
|---|---|---|
| `aragora/knowledge/event_subscribers.py` | domain | KM ingest, validation, mound, provenance, consensus, workflow-outcome, tier-transition, and approval-reinforcement reactions consolidated by E2a-E2c. |
| `aragora/memory/event_subscribers.py` | domain | The three live memory reactions from `handlers.basic`: `knowledge_to_memory`, `evidence_to_insight`, and `mound_to_memory`. |
| `aragora/debate/event_subscribers.py` | domain | The six live debate reactions from `handlers.{basic,strategic}`: ELO, calibration, consensus learning, rhetorical analysis, budget alert, and meta-learning. Security composition and `arena_bridge` moved to separate debate modules (§5.1). |
| `aragora/reasoning/event_subscribers.py` | domain | `vote_to_belief` from `handlers.basic`. |
| `aragora/workflow/event_subscribers.py` | application | The live alert-escalation workflow brake plus one keyed `debate_end_to_workflow` reaction backed by the persistent `PostDebateWorkflowSubscriber`. The obsolete unregistered `basic._handle_debate_end_to_workflow` delegate was deleted rather than re-wired. |
| `aragora/server/event_subscribers.py` | interface | Webhook delivery, knowledge-staleness-to-debate, and gauntlet-notification reactions. The deleted `execution_handlers` and `notification_handlers` modules are not final-main contributors. |

No `aragora/ranking/event_subscribers.py` or
`aragora/nomic/testfixer/event_subscribers.py` was created: E2c had already
deleted their sole source modules, so those two edges required only shrink-only
baseline cleanup.

Queue worker homes (derived the same way; home layer >= each worker's highest
import, counting lazy imports):

| New home | Layer | Worker (source) | Highest import (drives home) |
|---|---|---|---|
| `aragora/debate/queue_executor.py` | domain | `create_default_executor` (from `queue/worker.py`) | `debate.orchestrator`, `agents.base` (domain) |
| `aragora/memory/consensus_healing_worker.py` | domain | `workers.consensus_healing_worker` | `memory.consensus` (domain) |
| `aragora/nomic/testfixer/queue_worker.py` | application | `workers.testfixer_worker` | `nomic.testfixer` (application) |
| `aragora/server/workers/gauntlet_worker.py` | interface | `workers.gauntlet_worker` | `server.stream.gauntlet_emitter` (interface, lazy) |
| `aragora/server/workers/routing_worker.py` | interface | `workers.routing_worker` | `server.debate_origin`, `integrations.email_reply_loop` (interface) |
| (stays in `queue`, or `aragora/transcription/`) | infra/unlayered | `workers.transcription_worker` | only unlayered `transcription` (no layered edge) |

> The two `server` worker homes are dictated by a **lazy** `server.stream`/
> `server.debate_origin` import, which is exactly why §4.2 counts lazy imports. If a
> team prefers those workers in their domain/application package, it must first
> **invert** the server coupling to event emission (Q3 alternative); otherwise an
> `application -> interface` edge appears. No new-home filename collides with an
> existing module (verified).

Rationale: this honors "subscribers belong with their domains" for the pure-domain
reactions, and uses **existing** application (`workflow`, `nomic`) and interface
(`server`) homes for the multi-domain/server-coupled reactions - never inventing a
new unlayered package.

### 4.4 Self-registration + explicit bootstrap (layered composition roots)

Each home module registers its subscriber(s) at import time:

```python
# aragora/knowledge/event_subscribers.py  (domain; imports sibling domains only)
from aragora.events.cross_subscribers import register_subscriber   # infra, downward = legal
class KnowledgeEventSubscriber: ...
register_subscriber("knowledge", KnowledgeEventSubscriber())
```

Because registration only happens when the home module is imported, a **single
explicit bootstrap** at each composition root imports the relevant modules:

- **Interface composition roots** (server startup, CLI) call the *superset*
  `bootstrap_event_subscribers()` which imports the domain **and** application
  **and** interface home modules. Interface may import every layer, so this is legal
  and guarantees full registration for the running product.
- **Domain/library composition root** (Arena / `aragora.debate`) calls a
  *domain-subset* bootstrap that imports only the domain home modules
  (`knowledge`/`memory`/`debate`/`reasoning`/`ranking` `event_subscribers`) -
  domain->domain, legal. Application/interface reactions (workflow/nomic/server)
  register when *those* subsystems initialize (they are no-ops in a pure library
  debate that has no server/workflow engine, matching today's try/except fallbacks).
- **Direct-constructor tests** either call the appropriate bootstrap or import the
  specific home module before asserting registration.

> **Bootstrap location constraint:** the superset bootstrap imports application +
> interface modules, so it must itself live in `interface` (e.g.
> `aragora/server/startup/` or CLI). It must NOT live in `debate`/`events` (that
> would recreate an upward import). The domain-subset bootstrap lives in `debate`
> (domain) and imports only sibling-domain home modules.

**Composition roots that MUST call a bootstrap** (a miss = silently lost
reactions). Today registration is a side effect of importing
`events.cross_subscribers.manager` (its handler mixins register at class-definition
time); after the inversion, registration happens only when a home module is
imported, so every entry point that currently relies on that side effect must call
a bootstrap explicitly. Enumerated from the current
`get_cross_subscriber_manager()` consumers + the product entry points:

| Composition root | File(s) | Bootstrap |
|---|---|---|
| Server startup / lifecycle | `aragora/server/startup/*` (e.g. `knowledge_mound.py:214`), `server/background.py:246`, `server/shutdown_sequence.py:281` | **superset** (once, at startup) |
| CLI entry | `aragora/cli/main.py` (+ `cli/commands/stats.py:321`) | **superset** (once, at CLI init) |
| Arena / debate library | `aragora/debate/orchestrator.py` (Arena init), consumed by `debate/knowledge_manager.py`, `debate/extensions.py` | **domain-subset** |
| Standalone scripts (run debates/workflows without the server) | `scripts/nomic_loop.py`, `scripts/run_nomic_with_stream.py`, `scripts/self_develop.py`, `scripts/queue_worker.py` | superset if they touch workflow/server/queue; domain-subset for pure debate |
| Direct-constructor tests | any test asserting a reaction | call the bootstrap or import the specific home module |
| **Memory tier analytics (DOMAIN, non-Arena dispatch)** | `aragora/memory/tier_analytics.py:282-290` calls `get_cross_subscriber_manager().dispatch(...)` on tier promotion/demotion - a dispatch WITHOUT Arena | **domain-subset** - a pure-library caller that exercises memory-tier analytics but never constructs an Arena must still run the domain-subset bootstrap, else the tier-movement event reaches an empty registry |
| **Server-handler dispatch sites (INTERFACE, non-Arena)** | `server/handlers/cross_pollination.py:58,104,234,272,366`, `server/handlers/agents/agents.py:665`, `server/handlers/knowledge/analytics.py:479` all call `get_cross_subscriber_manager().dispatch(...)` | rely on the **superset** bootstrap already run at server startup (they do NOT each bootstrap); listed so E1's completeness check covers every dispatch site, not just Arena |

> **Register vs dispatch.** The rows above split into two kinds of root: those that
> must *register* (call a bootstrap) and non-Arena *dispatch* sites that merely
> *consume* `get_cross_subscriber_manager().dispatch(...)` and therefore ASSUME
> registration already happened. The dispatch sites are the reason the bootstrap
> cannot be Arena-only: a `debate_end`/tier-movement/cross-pollination event can be
> dispatched from `memory/`, `cli/`, or a `server/handlers/*` path with no Arena in
> the call stack. This list is derived from the ~15 current
> `get_cross_subscriber_manager()` call sites (across `debate/`, `cli/`, `memory/`,
> `server/`); E1's acceptance requires re-running that grep to confirm every root -
> register AND dispatch - is covered. Idempotency: `register_subscriber` is keyed, so
> repeated bootstrap calls are no-ops.

**Registration-completeness safeguard (E1 acceptance):** because a missed root
fails *silently*, add (a) a startup log/metric of the registered subscriber count,
and (b) a test asserting the superset bootstrap registers the **full expected set**
(parity with the pre-inversion registered subscriber list, captured before E2
begins). Any drop between the pre-inversion set and the post-bootstrap set fails the
batch.

## 5. SPLIT modules and cross-handler coupling inversion

Three events modules and one queue module are **SPLIT** rather than fully moved:
they have a domain-free public surface with **many external consumers**, so the
surface STAYS in `events`/`queue` and only the domain-coupled functions relocate.

### 5.1 events SPLITs

- **`security_events.py` (865 LOC).** KEEP (domain-free, stays in events): the
  enums/dataclasses/emitter/factories that external callers import -
  `SecurityEventType`, `SecuritySeverity`, `SecurityFinding`, `SecurityEvent`,
  `SecurityEventEmitter`, `SecurityEventHandler`, `create_vulnerability_event`,
  `create_secret_event`, `create_scan_completed_event`, `get_security_emitter`,
  `set_security_emitter`, **plus the domain-free results store**
  (`_security_debate_results`, `_store_security_debate_result`,
  `get_security_debate_result`, `list_security_debates` - they only read/write an
  in-memory dict, no `debate`/`agents` import).
  MOVE (the domain-coupled runner) -> `aragora/debate/security_response.py` (domain):
  - `trigger_security_debate` (L465 - imports `debate.protocol`, `debate.orchestrator`);
  - `_get_security_debate_agents` (L554 - its grimp-visible coupling is
    `agents.api_agents.{anthropic,openai}`; note its
    `from aragora.agents.factory import get_available_agents` attempt (L557) is a
    DEAD fallback - `aragora/agents/factory.py` does NOT exist, so it always raises
    `ImportError` and contributes no grimp edge - the runner should drop that dead
    branch when it relocates);
  - `build_security_debate_question` (L417 - itself domain-free, but it is the
    runner's question-builder and its 8 `@patch` tests move with it, §6.3).

  **CRITICAL - invert `SecurityEventEmitter._trigger_security_debate` (defined L332,
  fired from `emit()` at L311), do not just move the functions.** The emitter STAYS
  in events, but its auto-debate path for critical findings today calls the
  module-level `trigger_security_debate` DIRECTLY (the call is at L343), which is
  *the* thing that drags `debate`/`agents` into `events`. Relocating
  `trigger_security_debate` alone is
  insufficient: if the retained emitter then imported it from the debate home it
  would simply re-create the edge (`events -> debate`) in the other direction. So
  the emitter must invert to a **registry callback**:
  - `security_events` exposes a domain-free
    `register_security_debate_runner(runner)` / `get_security_debate_runner()` hook
    (zero domain imports - just a module-level Optional[Callable]);
  - the relocated `aragora/debate/security_response.py` registers its
    `trigger_security_debate` as the runner on import (registration guaranteed by
    the debate bootstrap, §4.4);
  - `_trigger_security_debate` invokes the registered runner if present, else
    no-ops returning `None` (exactly matching today's `ImportError` fallback for a
    pure library with no Arena).

  Auto-debate for critical findings still fires WITHOUT `security_events` importing
  `debate`/`agents`. The relocated runner imports the KEPT results store
  (`_store_security_debate_result`) downward (`debate -> events`, legal). Clears
  `events -> agents` and the `security_events` contributor to `events -> debate`,
  matching the §7 simulation, which de-domains `security_events` entirely.
- **`security_dispatcher.py` (499 LOC).** Only ONE domain import
  (`debate.orchestrator.Arena`, lazy at line ~363). KEEP the domain-free dispatch
  routing surface in events; MOVE the single Arena-running function to the debate
  home. Clears the `security_dispatcher` contributor to `events -> debate`.
- **`arena_bridge.py` (184 LOC).** Its only domain import
  (`from aragora.debate.event_bus import DebateEvent, EventBus`) is
  **`TYPE_CHECKING`-only**. **Preferred fix (a) - relocate** `arena_bridge` to
  `aragora/debate/` (domain): it is really a debate-side adapter that bridges the
  domain `EventBus` to the domain-free cross-subscriber registry, so
  `debate -> events.cross_subscribers` is downward, legal. Relocation keeps the
  `DebateEvent`/`EventBus` names resolvable (they are siblings in `debate`), so
  mypy stays clean (the tree is at 0 mypy errors). **Fallback (b) -
  drop-type-only-import** per the `billing -> agents` precedent
  (P4A_LAYERING_DISPOSITION §Batch 3c): the file already has
  `from __future__ import annotations`. **Caveat:** simply deleting the
  `TYPE_CHECKING` import would leave `DebateEvent`/`EventBus` as unresolvable
  forward refs (mypy `Name ... is not defined`); (b) is only valid if the
  annotations are made resolvable another way (a `Protocol` in a same-or-lower
  layer, or replacing the annotations with `object`/`Any`). Because (b) is
  fiddlier and `arena_bridge` genuinely belongs in `debate`, **prefer (a)**.
  Consumers of `aragora.events.arena_bridge` to repoint (§6.3):
  `aragora/server/handlers/cross_pollination.py` (`EVENT_TYPE_MAP`, interface ->
  `debate`, downward legal) and `aragora/debate/orchestrator_memory.py`
  (`ArenaEventBridge`, debate -> debate). Either fix clears the `arena_bridge`
  contributor to `events -> debate`.

### 5.2 queue SPLIT

- **`queue/worker.py` (353 LOC).** KEEP (domain-free, stays in queue):
  - `DebateWorker` (the transport base, `worker.py:32`) - imports only
    `queue.{base,config,job,retry}`, `core`, `exceptions`.
  - `DebateExecutor` (the **type alias** `Callable[[Job], Coroutine[..., dict]]`
    at `worker.py:31`) - domain-free; it is part of `DebateWorker`'s public
    signature (`DebateWorker.__init__(executor: DebateExecutor)`). It must NOT
    move: relocating it would either break `DebateWorker`'s retained signature or
    force `queue/worker.py` to `from aragora.debate... import DebateExecutor`,
    **re-creating the `queue -> debate` edge** (the exact anti-pattern §1 warns
    against).

  MOVE (the ONLY domain-coupled symbol): `create_default_executor`
  (`worker.py:~294`) - its nested `execute_debate` lazily imports
  `agents.base.create_agent`, `core`, `debate.orchestrator.Arena`, and it drives
  the `TYPE_CHECKING` `AgentType` import at `worker.py:21` (used only via
  `cast("AgentType", ...)` inside it). Move it to an executor home
  (e.g. `aragora/debate/queue_executor.py`, domain); once it leaves,
  `worker.py`'s `AgentType` `TYPE_CHECKING` import is unused and is deleted too.

  In `queue/__init__.py`: **KEEP** the `DebateExecutor` + `DebateWorker`
  re-exports (both stay, both are public - `DebateWorker` is documented in
  `aragora/queue/README.md:136`); **DROP only** the `create_default_executor`
  re-export (no shim - a re-export would create `queue -> debate`). Clears
  `queue -> debate` and the `worker` contributor to `queue -> agents`. (This
  matches §7's simulation, which SPLITs `queue.worker` - keeps its surface,
  removes only its domain imports.)

### 5.3 Cross-handler coupling must invert to event emission (not direct import)

The design-time census found two lazy delegates to
`PostDebateWorkflowSubscriber`, but E2c deleted
`subscribers.debate_handlers.py` before E5 landed. The sole remaining delegate,
`handlers.basic._handle_debate_end_to_workflow`, was unregistered dead code. E5
therefore removed that delegate and relocated `PostDebateWorkflowSubscriber` to
`aragora.workflow.event_subscribers`. The application home registers exactly one
keyed `debate_end_to_workflow` reaction. The interface-superset
`bootstrap_event_subscribers()` applies that home once per manager, so one
`DEBATE_END` dispatch invokes `PostDebateWorkflowSubscriber.handle_debate_end`
exactly once even after repeated bootstrap calls.

This preserves the general rule: **handlers communicate through the domain-free
event bus, never by importing each other across layers.** The
`PostDebateWorkflowSubscriber._trigger_workflow` method remains a
definition-construction-only seam and deliberately avoids creating a workflow
engine or probing checkpoint infrastructure. Outcome classification and fail-soft
handling are now reached through the production composition root. Invocation-count
tests patch the handler itself because registration-count parity alone cannot detect a
double-fire.

> Note: the design-time `handlers.strategic` control-plane import and
> `notification_handlers` notification import were unlayered. Final main moved the
> live workflow reaction to its application home and removed the obsolete
> notification handler module through the notification/channel boundary work.

## 6. Consumer census (proves no-shim safety) + repoint list

A no-shim relocate-UP is only safe if **no public/external consumer** depends on the
moved paths. Census (grep across `aragora/`, `tests/`, `scripts/`, `sdk/`):

### 6.1 Moved handler paths (`cross_subscribers.handlers.*`, `subscribers.<handler>`)

- **No `sdk/` consumer. No `aragora/__init__.py` consumer. No non-test runtime
  consumer** outside `aragora/events/`. Runtime access is via
  `subscribers/__init__.py` + `manager.py` (both internal to events, edited in
  place) and via the `get_cross_subscriber_manager()` accessor (which STAYS).
- **Only test consumers require repointing.** These **7 files monkeypatch the moved
  cross_subscribers/subscribers HANDLER paths** - the "~7" figure quoted in §0/§8
  refers to THIS handler-path set:
  - `tests/memory/test_tier_transition_events.py` (`handlers.basic`)
  - `tests/integration/test_e2e_debate_km_flow.py` (`handlers.validation.record_km_inbound_event`)
  - `tests/events/test_strategic_handlers.py` (`handlers.strategic`)
  - `tests/events/test_consensus_ingestion.py` (`handlers.validation.record_km_inbound_event`)
  - `tests/events/test_workflow_to_supermemory.py` (`handlers.basic`)
  - `tests/nomic/testfixer/test_event_integration.py` (`subscribers.testfixer_handlers`)
  - `tests/events/test_post_debate_workflow.py` (`subscribers.workflow_automation.PostDebateWorkflowSubscriber`)
- **Reconciliation with the SPLIT-symbol repoints (§6.3).** The 7 files above are the
  HANDLER-path monkeypatches only. The §5.1/§5.2 SPLIT-moved *symbols* add a further
  set of repointed test files - `tests/debate/test_security_debate.py` (8 `@patch`),
  `tests/events/test_security_events.py`, `tests/events/test_security_dispatcher.py`,
  `tests/events/test_arena_bridge.py`, and (queue) the direct-`@patch`
  `tests/server/handlers/admin/health/test_workers.py` - so the **whole-inversion
  repoint set is ~12 test files**, split across the E-batches and Q-batches (the
  `security_debate`/`security_events` tests move with E7a; `arena_bridge` with E7b).

### 6.2 Moved worker paths (`queue.workers.*`, `create_default_executor`)

- **The `aragora/queue/workers/__init__.py` barrel is itself a move target (drop
  re-exports, no shim).** That `__init__.py` EAGERLY
  `from aragora.queue.workers.<worker> import ...` for `gauntlet_worker`,
  `transcription_worker`, `routing_worker`, and `consensus_healing_worker` - so the
  barrel is a *direct*
  `queue.workers -> {agents,debate,gauntlet,integrations,memory,ranking,server}`
  contributor. Each worker-move batch MUST also **drop that worker's eager re-export
  from the barrel (no shim)** - a re-export would re-create the edge exactly like the
  events shim in §1. After Q3/Q4 the barrel re-exports only the unlayered
  `transcription_worker` (if it stays) and any retained transport symbols.
- **No `sdk/` consumer.** Runtime consumers are **interface-layer + scripts**, all
  repointable to the new homes:
  - `aragora/server/startup/workers.py` (`gauntlet_worker`, `testfixer_worker`)
  - `aragora/server/handlers/gauntlet/runner.py` (`gauntlet_worker.enqueue_gauntlet_job`)
  - `aragora/server/handlers/admin/health/workers.py:146`
    (`from aragora.queue.workers import get_consensus_healing_worker`) -> repoint to
    the `aragora/memory/` consensus-healing home (Q3)
  - `scripts/queue_worker.py` (`create_default_executor`)
- **Public docs referencing moved worker symbols (repoint in the owning batch):**
  - `docs/resilience/QUEUE.md:80-88` + its docs-site mirror
    `docs-site/docs/guides/queue.md:85-93`
    (`from aragora.queue import ... create_default_executor` / `await
    create_default_executor()`) -> repoint to `aragora/debate/queue_executor.py` (Q2).
  - `docs/deployment/DISASTER_RECOVERY.md:900` + its docs-site mirror
    `docs-site/docs/deployment/disaster-recovery.md:905`
    (`from aragora.queue.workers import get_consensus_healing_worker`) -> repoint to
    the `aragora/memory/` home (Q3).
  - Editing a `docs/` source that `sync-docs.js` mirrors forces a mirror regen;
    regenerate + commit the mirror in the same batch (merge-gate docs-site caveat).
- Plus queue/worker tests (`tests/queue/workers/*`, `tests/queue/test_consensus_healing_worker.py`,
  `tests/server/startup/test_workers.py`, `tests/handlers/gauntlet/test_runner.py`,
  and BOTH `tests/handlers/admin/health/test_workers.py` (patches the CONSUMER's
  imported name - follows the repoint automatically) and
  `tests/server/handlers/admin/health/test_workers.py` (directly
  `@patch("aragora.queue.workers.get_consensus_healing_worker")` - repoint to the
  memory home), ...).
- `aragora/debate/model_combinations.py`'s `SingleDebateExecutor` is an unrelated
  `Callable` type alias, NOT a consumer of `queue.worker.DebateExecutor`.

### 6.3 SPLIT-moved symbols (functions relocated out of a retained module)

The §5.1/§5.2 SPLITs move *symbols* out of a module whose surface stays. Because
there is no shim, every consumer of the **old symbol path** repoints. Census:

**`aragora/events/__init__.py` eager re-export DROP list (MANDATORY - each retained
eager re-export re-imports the relocated debate-home module and RE-CREATES
`events -> debate`).** Remove BOTH the import and the `__all__` entry for every moved
symbol. Verified line numbers on head `a5206a616c`:

| Moved symbol | New home | `__init__` import line | `__all__` line | Batch |
|---|---|---|---|---|
| `ArenaEventBridge` | `aragora/debate/arena_bridge.py` | 47 | 126 | E7b |
| `create_arena_bridge` | `aragora/debate/arena_bridge.py` | 48 | 127 | E7b |
| `EVENT_TYPE_MAP` | `aragora/debate/arena_bridge.py` | 49 | 128 | E7b |
| `trigger_security_debate` | `aragora/debate/security_response.py` | 87 | 159 | E7a |
| `build_security_debate_question` | `aragora/debate/security_response.py` | 88 | 160 | E7a |

Concretely: DROP the whole `from .arena_bridge import (ArenaEventBridge,
create_arena_bridge, EVENT_TYPE_MAP)` block (L46-50) since all three names move; and
inside `from .security_events import (...)` DROP only `trigger_security_debate`
(L87) + `build_security_debate_question` (L88), while KEEPING the retained
domain-free names (`SecurityEventEmitter`, `SecurityEventHandler`,
`get_security_debate_result`, `list_security_debates`, the event types + factories).
No `__getattr__` fallback / lazy re-export is added (that would also re-create the
edge - grimp counts lazy chains).

- **`security_events.build_security_debate_question` + `trigger_security_debate`
  (+ `_get_security_debate_agents`)** -> new home
  `aragora/debate/security_response.py` (drop from `events/__init__.py` per the table
  above). `trigger_security_debate`'s ONLY runtime caller is the emitter
  (`security_events.py:343`), which the §5.1 callback inversion de-couples - so no
  runtime import site survives outside the debate home. Consumers to repoint:
  - `aragora/debate/security_debate.py:61,64` (runtime; lazy import + call ->
    `debate -> debate`, legal).
  - `tests/debate/test_security_debate.py` - **8** `@patch(
    "aragora.events.security_events.build_security_debate_question")` sites
    (lines 123,147,179,280,306,329,357,382).
  - `tests/events/test_security_events.py` - direct import (line 23) + call sites
    (~lines 1230-1330) + 2 `@patch` sites (lines 1802,1843). The
    `build_security_debate_question` / `trigger_security_debate` tests move with the
    symbols to `tests/debate/`.
- **`security_dispatcher`'s Arena-runner function** (the single
  `debate.orchestrator.Arena` lazy import, ~line 363) -> `aragora/debate/`
  security home. Consumers: internal to `security_dispatcher` (the dispatch
  surface stays and calls the relocated fn via the domain-free registry / a
  callback param) + its tests in `tests/events/test_security_dispatcher.py`
  (repoint the `@patch` of the Arena path). No `sdk/`/`__init__` consumer.
- **`events.arena_bridge`** -> `aragora/debate/arena_bridge.py` (preferred option
  (a), §5.1). Consumers to repoint: `aragora/server/handlers/cross_pollination.py`
  (`EVENT_TYPE_MAP`), `aragora/debate/orchestrator_memory.py` (`ArenaEventBridge`),
  and `tests/events/test_arena_bridge.py`. (The `control_plane.arena_bridge`
  matches in grep are a DIFFERENT, unrelated module - not moved.)

No `sdk/` or public-API consumer of any SPLIT-moved symbol exists, so the no-shim
exemption holds for the SPLITs too. **Public docs/READMEs** that reference dropped
symbols must also repoint (grok [P3]): `aragora/queue/README.md` and the
`queue/__init__.py` docstring examples use `create_default_executor` (repoint to
the new home) but KEEP `DebateWorker`/`DebateExecutor`; any events docs that show
`from aragora.events import build_security_debate_question` update to the debate
home. These are part of the owning batch's diff, not a separate task.

**Verdict:** no public/external/SDK consumer of any moved path or moved symbol ->
the no-shim relocate-UP exemption (§8) is safe. The repoint set is finite and
enumerated above.

## 7. Grimp evidence: the edges clear with zero new un-baselined edge

### 7.1 Final-main seal

The design-time simulation below predicted that only `events -> server` would
remain after E1-E7b. Subsequent dispatcher, notification, and channel boundary
features removed the real direct contributors. At seal time the only remaining
aggregate routes terminate at the exact authorized exception fallback edges. The
three bounded `.importlinter` ignores therefore make the scoped
foundation/infrastructure checker pass with an empty scoped baseline and zero new
violations. The raw single combined layers contract may still report higher-layer
violations, as allowed by VAL-P4A-006.

### 7.2 Design-time simulation

We simulated the E1-E7b end state in-memory with grimp (`/tmp/sx_grimp_sim.py`): FULL-MOVE
modules are removed from the events/queue subtree (they relocate with no re-export),
and SPLIT modules keep their surface but lose their domain imports. Then we re-ran
`find_illegal_dependencies_for_layers` (the import-linter primitive) and diffed the
edge set. Verbatim result (local tree at `fce9aa5e09`, grimp 3.14, 4238 modules):

```
BEFORE events targets: ['agents', 'debate', 'knowledge', 'memory', 'nomic', 'ranking', 'reasoning', 'server', 'workflow']
BEFORE queue  targets: ['agents', 'debate', 'gauntlet', 'integrations', 'memory', 'nomic', 'ranking', 'server']

FULL-MOVE (remove_module): events cross_subscribers.handlers.*, subscribers.{debate,execution,mound,testfixer,notification}_handlers, workflow_automation;
                           queue workers.{gauntlet,routing,testfixer,consensus_healing,transcription}_worker
SPLIT (remove domain imports only): security_events (-> debate.protocol, debate.orchestrator, agents.api_agents.{anthropic,openai}),
                                    security_dispatcher (-> debate.orchestrator), arena_bridge (-> debate.event_bus),
                                    queue.worker (-> agents.base, debate.orchestrator)

================ RESULT ================
AFTER events targets: ['server']
AFTER queue  targets: []

events->DOMAIN edges remaining (must be empty): []
  events->server remaining heads: ['aragora.events.async_dispatcher', 'aragora.events.dispatcher', 'aragora.events.registry']
queue-> edges remaining (must be empty): []

NEW illegal edges introduced by the simulation (must be empty): []

SIMULATION PASS
```

Reading of the result:

- **events** reduces to `{server}` only: all eight upward edges
  `events -> {agents,debate,knowledge,memory,nomic,ranking,reasoning,workflow}`
  are **cleared**.
- **queue** reduces to `{}` (empty): all eight edges
  `queue -> {agents,debate,gauntlet,integrations,memory,nomic,ranking,server}`
  are **cleared** - including `queue -> server` (both contributors were workers).
- The **subscriber-side** `events -> server` heads (`basic`, `culture`,
  `execution_handlers`, `notification_handlers`) are gone; the **residual**
  `events -> server` heads are `dispatcher`/`async_dispatcher`/`registry`, owned by
  **Batch 1b-sweep** (`dispatcher`/`async_dispatcher` -> `server.middleware.tracing`,
  confirmed direct) and **Batch 2c** (`dispatcher`/`async_dispatcher` ->
  `server.handlers.webhooks`, Tier-3). `events -> server` therefore stays a
  (baselined) edge after this batch - as expected; it is NOT this batch's target.
- **Zero NEW illegal edges** were introduced (the removals cannot add edges; the
  home-assignment rule §4.2 guarantees the *destination* introduces none either -
  every relocated reaction lands in a home at or above its highest import).

> **Fidelity note.** The simulation removes both a handler and any sibling handler
> it couples to (e.g. `debate_handlers` + `workflow_automation`), which is only
> valid because §5.3 inverts that coupling to event emission. If the real
> implementation kept a domain-home handler importing the application `workflow`
> subscriber, it would introduce `debate -> workflow`; the inversion (event
> emission, not import) is therefore load-bearing and is called out as a batch
> acceptance criterion (§10).

**Reproduce:** the full simulation script is committed inline in **Appendix A
(§12)** so the load-bearing evidence is auditable, not a throwaway. From the
worktree root: save §12 to a file and run
`SX_REPO_ROOT="$PWD" python3 <file>` (requires `grimp>=3.14`). The authoritative
gate remains `python3 scripts/ci/check_import_contracts.py --layers
foundation,infrastructure` run after each impl batch lands.

> Note on `transcription_worker`: it is listed in the FULL-MOVE set above for
> package cohesion, but it imports only the **unlayered** `aragora.transcription`
> (+ `events.types`), so it contributes **no** `queue -> {domain}` contract edge.
> Removing it in the simulation is immaterial to the result (the `queue` target
> set is already empty without it); it may equally STAY in `queue`. It is called
> out so an implementer does not hunt for a phantom edge contributor.

## 8. Shim policy: the relocate-UP no-shim exemption

The usual rule (VAL-CROSS-004 / shims.md) is "shim every moved path" so callers of
the old import path keep working. **That rule is INVERTED for a layering relocate-UP**
because an identity-preserving re-export shim at the old `events`/`queue` path
re-imports the relocated (now higher-layer) module and thereby **re-creates the very
`infra -> {domain,application,interface}` edge the move was meant to delete** (proven
by worker `5f92db63`, §1). For this specific case the correct action is: **move with
NO re-export shim, and repoint every consumer.**

Guardrails that make the exemption safe (all satisfied here):
1. The **domain-free surface stays** in `events`/`queue` (registry, dispatch,
   transport, `get_cross_subscriber_manager`, security types/emitter). Only the
   domain-coupled code moves. Public accessors do not move.
2. A **consumer census** (§6) confirms **no public/external/SDK consumer** of the
   moved paths - only internal runtime (repointed) and the monkeypatching tests
   (§6.1: ~7 handler-path files + the §6.3 SPLIT-symbol files, ~12 total; all
   repointed). If any external consumer existed, the exemption would NOT apply and
   an alternative (keep the surface + invert, or a *domain-free* facade) would be
   required instead.
3. grimp shows the edges clear with **no new un-baselined edge** (§7).

### 8.1 Proposed AGENTS.md addition (under "P4a Contracts-Thread Shared Rules")

```md
- **Relocate-UP no-shim exemption (layering only).** The standard "shim every moved
  path" rule (VAL-CROSS-004) is SUSPENDED when a module is moved *up* a layer to
  clear a lower-layer `importer -> imported` contract edge (e.g. moving a
  domain-coupled handler/worker out of infra `events`/`queue`). A re-export shim at
  the old path re-imports the relocated higher-layer module and RE-CREATES the exact
  edge the move deletes (grimp counts indirect, lazy, and TYPE_CHECKING chains
  through the shim), so the shim is forbidden here. Instead: (a) keep only a
  DOMAIN-FREE surface at the old package (registry/dispatch/transport/public
  accessors with zero domain imports, eager or lazy); (b) move the domain-coupled
  code to a home whose layer is >= the highest layer it imports (prefer the coupled
  domain package; use an existing application/interface home for multi-domain/server
  couplings; do not invent a new top-level package without recording module_tiers
  drift); (c) REPOINT every consumer of the moved path - runtime AND tests
  (including `@patch("<old.module.path>")` monkeypatches) - to the new home. This
  exemption REQUIRES a committed consumer census proving no public/external/SDK
  consumer of the moved path, plus grimp evidence that the target edge clears with
  no new un-baselined edge. If any external consumer exists, the exemption does not
  apply.
```

### 8.2 Proposed `{missionDir}/library/shims.md` policy note

```md
## Relocate-UP exception (no shim)

Do NOT add a re-export shim when the move is a layering relocate-UP intended to
clear an import-contract edge (infra -> domain/application/interface). A shim at the
old path re-imports the relocated module and re-creates the edge (empirically:
worker 5f92db63, resolved_violations == {} after relocation + eager shim; grimp
counts indirect/lazy/TYPE_CHECKING chains through the shim). Correct pattern:
- keep a domain-free surface at the old package (registry/dispatch/transport +
  public accessors, zero domain imports);
- move domain-coupled code to a home at or above its highest import layer;
- repoint ALL consumers (runtime + tests, including monkeypatch string paths); no
  shim.
Precondition: a consumer census showing no public/external/SDK consumer of the moved
path, plus grimp evidence the edge clears with no new un-baselined edge. This is the
ONLY sanctioned exception to "shim every moved path". (See
docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md.)
```

## 9. module_tiers drift

The home assignments in §4.3 use **only existing packages**
(`knowledge`, `memory`, `debate`, `reasoning`, `ranking`, `workflow`, `nomic`,
`server`) - **no new top-level package is created**, so there is **no
`aragora/module_tiers.yaml` drift** and no operator Decision line is required for
package addition. A brand-new `aragora/orchestration` package was explicitly
rejected (it would be unlayered/new and would still not solve the server-coupled
reactions, which need the interface layer). If a future implementer decides a new
package is warranted, they MUST add it to `module_tiers.yaml` + `.importlinter` and
record the drift per VAL-P0-006.

## 10. Batch breakdown (implemented sub-features)

Ordered; each is Tier 1-2 (touches only `aragora/events`, `aragora/queue`, and the
domain/application/interface home packages + their tests) unless noted. LOC is an
estimate of code touched (moved + edited + repointed + tests); a couple sit near the
cap and carry a noted split point. **`events.dispatcher`/`async_dispatcher` ->
`server` (webhook signing + tracing) is OUT OF SCOPE** here - that is Batch 1b-sweep
+ Batch 2c (2c is Tier-3, `aragora/server/handlers/webhook_management.py`).

### Events (supersedes cancelled Batch 2a)

| # | Sub-feature | Scope | Clears | ~LOC |
|---|---|---|---|---|
| E1 | Domain-free cross-subscriber registry core | `cross_subscribers/{__init__,manager}.py` -> registry-backed dispatch; add `register_subscriber`/`register_factory`/`get`/`reset`/`SubscriberStats`; keep `get_cross_subscriber_manager` stable; add interface superset + domain-subset bootstrap skeletons. Handlers still in place (register via new API). | none (enabler; no new edge) | ~600 |
| E2 | knowledge-domain home | Move KM reactions from `handlers.{knowledge_mound,validation}` (+ knowledge bits of `basic`/`culture`/`strategic`, `subscribers.mound_handlers`) -> `aragora/knowledge/event_subscribers.py`; self-register; NO shim; repoint `test_e2e_debate_km_flow`, `test_consensus_ingestion`. **Split E2a(knowledge_mound)/E2b(validation) if >800.** | contributes `events->{knowledge,memory}` | ~750 |
| E3 | memory + reasoning homes; ranking cleanup | Move the three live `handlers.basic` memory reactions to `aragora/memory/event_subscribers.py` and `vote_to_belief` to `aragora/reasoning/event_subscribers.py`. Ranking was already a no-code stale edge after E2c, so no ranking home was created. | clears `events->{memory,reasoning,ranking}` | ~600 |
| E4 | debate-domain home | Move the six live debate reactions from `handlers.{basic,strategic}` to `aragora/debate/event_subscribers.py`. `subscribers.debate_handlers` had already been deleted by E2c. | removes the handler share of `events->debate` | ~700 |
| E5 | workflow application home + stale nomic cleanup | Move `subscribers.workflow_automation` and the live strategic workflow brake to `aragora/workflow/event_subscribers.py`; register one keyed `debate_end_to_workflow` reaction in that application home; remove the unregistered `basic._handle_debate_end_to_workflow` delegate. Nomic was already a no-code stale edge after E2c, so no nomic event-subscriber home was created. | clears `events->{workflow,nomic}` | ~700 |
| E6 | interface home (server-coupled reactions) | Move the live basic webhook and culture state-manager reactions to `aragora/server/event_subscribers.py`; relocate gauntlet notification for interface cohesion. `execution_handlers` was already deleted, and later notification/channel plus dispatcher-boundary features removed the remaining real `events->server` contributors. | removes the subscriber-side share of `events->server` | ~700 |
| E7a | security split (events + dispatcher) + emitter callback inversion | SPLIT `security_events`: move `trigger_security_debate` + `_get_security_debate_agents` + `build_security_debate_question` -> `aragora/debate/security_response.py`; add the domain-free `register_security_debate_runner`/`get_security_debate_runner` hook and INVERT `SecurityEventEmitter._trigger_security_debate` to the callback (§5.1); KEEP the domain-free results store in events. SPLIT `security_dispatcher` (move the single Arena-runner fn). DROP `trigger_security_debate` + `build_security_debate_question` from `events/__init__.py` (§6.3 table). Repoint `debate/security_debate.py`, `tests/debate/test_security_debate.py` (8 `@patch`), `tests/events/test_security_events.py`, `tests/events/test_security_dispatcher.py`. | `events->agents` + `security_events`/`security_dispatcher` share of `events->debate` | ~650 |
| E7b | arena_bridge relocate + manager de-mixin | Relocate `arena_bridge` -> `aragora/debate/arena_bridge.py` (preferred option (a); or the drop-TYPE_CHECKING fallback (b), §5.1); DROP the `arena_bridge` trio from `events/__init__.py` (§6.3 table); finalize `manager.py` domain-free (remove the last mixin imports). Repoint `server/handlers/cross_pollination.py:156` (`EVENT_TYPE_MAP`), `debate/orchestrator_memory.py:306` (`ArenaEventBridge`), `tests/events/test_arena_bridge.py`. | `arena_bridge` share of `events->debate` | ~400 |

After E1-E7b, `events ->
{agents,debate,knowledge,memory,nomic,ranking,reasoning,workflow}` was cleared.
Later notification/channel and dispatcher-boundary features removed the real
`events -> server` contributors; the seal closes the final transitive exception
route with the authorized exact-edge ignore. E7 was split into E7a/E7b because
the §5.1 emitter-inversion scope pushed the combined batch past the <=800 LOC cap.

### Queue (supersedes cancelled Batch 2b)

| # | Sub-feature | Scope | Clears | ~LOC |
|---|---|---|---|---|
| Q1 | Domain-free job-handler registry | `queue/__init__.py` + `queue/worker.py`: expose `register_worker`/`register_job_handler` + `get`/`reset`; keep transport base (`DebateWorker`); DROP only the `create_default_executor` re-export from `__init__` (no shim). **KEEP** the `DebateWorker` + `DebateExecutor` (type alias) re-exports. | none (enabler; no new edge) | ~500 |
| Q2 | executor factory -> debate home | Move only `create_default_executor` (the domain-coupled factory; its nested `execute_debate` lazily imports `agents.base`/`core`/`debate.orchestrator`) out of `queue/worker.py` -> `aragora/debate/queue_executor.py` (domain: debate->agents/debate downward, legal); delete `worker.py`'s now-unused `AgentType` `TYPE_CHECKING` import; `DebateExecutor` type alias + `DebateWorker` STAY in `queue`; DROP the `create_default_executor` re-export from `queue/__init__.py` (no shim); repoint `scripts/queue_worker.py`, `queue/README.md`/docstring examples, `docs/resilience/QUEUE.md` + mirror `docs-site/docs/guides/queue.md` (§6.2), tests. | `queue->debate` + `worker` share of `queue->agents` | ~550 |
| Q3 | gauntlet + memory workers | Move `workers.gauntlet_worker` -> **interface** home `aragora/server/workers/gauntlet_worker.py` (it lazily imports `server.stream.gauntlet_emitter` (L0 interface) + `gauntlet`/`agents`/`ranking`; home MUST be interface - an `aragora/gauntlet/` (application) home would create a NEW `application->interface` edge). Move `workers.consensus_healing_worker` -> **domain** home `aragora/memory/consensus_healing_worker.py` (imports only `memory.consensus`). DROP the `gauntlet_worker` + `consensus_healing_worker` eager re-exports from the `queue/workers/__init__.py` barrel (no shim, §6.2). Repoint `server/startup/workers.py`, `server/handlers/gauntlet/runner.py`, `server/handlers/admin/health/workers.py:146` (`get_consensus_healing_worker`), `docs/deployment/DISASTER_RECOVERY.md:900` + mirror `docs-site/docs/deployment/disaster-recovery.md:905`, tests (incl. the direct-`@patch` `tests/server/handlers/admin/health/test_workers.py`). **Split gauntlet vs consensus if >800.** *(Cleaner-but-more-work alternative for gauntlet_worker: invert the `gauntlet_emitter` coupling to event emission, then it may live in `aragora/gauntlet/`.)* | `queue->{gauntlet,ranking,memory}` + gauntlet share of `queue->{agents,server}` | ~800 |
| Q4 | routing + testfixer (+ transcription) workers | Move `workers.routing_worker` -> **interface** home `aragora/server/workers/routing_worker.py` (it imports `server.debate_origin` + `integrations.email_reply_loop`, both L0 interface; home MUST be interface). Move `workers.testfixer_worker` -> **application** home `aragora/nomic/testfixer/queue_worker.py` (imports `nomic.testfixer`, L1). `workers.transcription_worker` clears no layered edge (unlayered `transcription`); MAY stay in `queue` or move to `aragora/transcription/` for cohesion. DROP the `routing_worker` (and `transcription_worker` if it moves) eager re-exports from the `queue/workers/__init__.py` barrel (no shim, §6.2); `testfixer_worker` is NOT in the barrel today, so nothing to drop for it. Repoint tests. **No target-home filename collisions** (verified: none of `aragora/{server/workers,memory,nomic/testfixer}/<worker>.py` exist today). | `queue->{integrations,nomic}` + routing share of `queue->server` | ~700 |

After Q1-Q4: `queue -> {agents,debate,gauntlet,integrations,memory,nomic,ranking,server}`
fully cleared.

**Per-batch acceptance criteria:** (1)
`check_import_contracts.py --layers foundation,infrastructure` shows no NEW edge and
the targeted contributor(s) removed; (2) a **full-layer** re-check -
`check_import_contracts.py` with NO `--layers` filter (all 5 layers) OR a targeted
grimp assertion - shows the batch introduced **no new domain/application/interface
edge** (guards the §5.3 coupling inversion: no domain-home module may retain a
cross-layer import of an application/interface home, e.g. `debate -> workflow`, and
guards that each worker's new home is at/above its highest import); (3) NO re-export
shim at any moved path; (4) all repointed consumers/tests pass; (5)
`get_cross_subscriber_manager()` import path unchanged; (6) **E5-specific:** both
legacy delegates are absent, the application home registers one keyed
`debate_end_to_workflow` reaction, and production invocation-count tests prove
one `PostDebateWorkflowSubscriber.handle_debate_end` call per event before and
after repeated idempotent bootstrap. Registration-count parity is insufficient.

## 11. References

- `docs/architecture/P4A_LAYERING_DISPOSITION.md` (lines 185-190, 326-349: preferred
  EventBus/job-handler registry inversion; Batch 2a/2b/2c decomposition;
  `billing -> agents` TYPE_CHECKING drop precedent).
- Handoff `5f92db63` (relocate-UP + shim impossibility diagnosis).
- `{missionDir}/library/p4a-deferred-shim-callers.md`,
  `{missionDir}/library/p4a-layering-disposition-batches.md`,
  `{missionDir}/library/shims.md`.
- `.importlinter` (5-layer contract), `scripts/ci/check_import_contracts.py`,
  `scripts/baselines/import_contracts_baseline.json` (frozen at `5ce80610c6`).
- Grimp simulation script: **Appendix A (§12)** below (committed inline for
  reproducibility).

## 12. Appendix A: grimp simulation script (reproduces §7)

The exact read-only simulation that produced §7's result. It manipulates the grimp
graph in memory only (no repo files change). Save to a file and run from the
worktree root with `SX_REPO_ROOT="$PWD" python3 <file>` (requires `grimp>=3.14`).
It prints `SIMULATION PASS` when `events` reduces to `{server}`, `queue` reduces to
`{}`, and no new illegal edge is introduced.

```python
"""P4a events/queue inversion - grimp SIMULATION (read-only; proves edges clear).

Simulates the end state of the inversion by manipulating the grimp graph
in-memory (no repo files change):
  * FULL-MOVE modules (domain-coupled handlers/workers) are removed from the
    events/queue subtree (they relocate to domain/application/interface homes,
    with NO re-export shim at the old path).
  * SPLIT modules (security_events/security_dispatcher/arena_bridge, queue.worker)
    keep their domain-free surface in place but lose their domain imports (the
    domain-coupled functions relocate).
Then re-runs import-linter's layer primitive and shows events->{domain} and
queue->{domain} are gone, with no NEW illegal edge introduced.
"""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.environ.get("SX_REPO_ROOT") or os.getcwd()
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import grimp  # noqa: E402

LAYERS = [
    ["server", "cli", "mcp", "gateway", "bots", "channels", "integrations", "connectors"],
    ["workflow", "pipeline", "nomic", "swarm", "gauntlet", "goals", "implement",
     "modes", "verticals", "autonomous", "broadcast", "canvas", "spectate"],
    ["debate", "agents", "memory", "knowledge", "ranking", "reasoning",
     "evidence", "evaluation", "explainability", "learning", "ml"],
    ["storage", "resilience", "events", "observability", "security",
     "queue", "db", "caching", "billing", "backup", "migrations"],
    ["config", "core_types", "exceptions", "errors", "utils", "protocols", "types"],
]

# packages whose import FROM events/queue is an UPWARD (illegal) edge
DOMAIN_APP_IF = set(LAYERS[0]) | set(LAYERS[1]) | set(LAYERS[2])
DOMAIN_ONLY = set(LAYERS[2])


def make_layers():
    return [grimp.Layer(*names, independent=False) for names in LAYERS]


def illegal_edges(graph):
    deps = graph.find_illegal_dependencies_for_layers(
        layers=make_layers(), containers={"aragora"}
    )
    return {(d.importer, d.imported): d for d in deps}


def heads_for(dep):
    hs = set()
    for r in dep.routes:
        hs |= set(r.heads)
    return sorted(hs)


def targets(edges, pkg):
    return {
        imp_tgt[1].split(".")[-1]: dep
        for imp_tgt, dep in edges.items()
        if imp_tgt[0] == pkg
    }


def descendants(graph, package):
    return {m for m in graph.modules if m == package or m.startswith(package + ".")}


def remove_domain_imports(graph, module, domain_pkgs):
    """Remove module's direct imports into any of the given top-level domain pkgs."""
    removed = []
    for imported in list(graph.find_modules_directly_imported_by(module)):
        top = imported.split(".")[1] if imported.count(".") >= 1 else imported
        if top in domain_pkgs:
            graph.remove_import(importer=module, imported=imported)
            removed.append(imported)
    return removed


graph = grimp.build_graph("aragora")
before = illegal_edges(graph)
ev_before = targets(before, "aragora.events")
q_before = targets(before, "aragora.queue")
print("BEFORE events targets:", sorted(ev_before))
print("BEFORE queue  targets:", sorted(q_before))
edge_keys_before = set(before.keys())

# ---- EVENTS move-set ----
FULL_MOVE_EVENTS = sorted(descendants(graph, "aragora.events.cross_subscribers.handlers"))
for m in ["debate_handlers", "execution_handlers", "mound_handlers",
          "testfixer_handlers", "workflow_automation", "notification_handlers"]:
    FULL_MOVE_EVENTS.append(f"aragora.events.subscribers.{m}")
SPLIT_EVENTS = [
    "aragora.events.security_events",
    "aragora.events.security_dispatcher",
    "aragora.events.arena_bridge",
]
# ---- QUEUE move-set ----
FULL_MOVE_QUEUE = [
    "aragora.queue.workers.gauntlet_worker",
    "aragora.queue.workers.routing_worker",
    "aragora.queue.workers.testfixer_worker",
    "aragora.queue.workers.consensus_healing_worker",
    "aragora.queue.workers.transcription_worker",  # immaterial: clears no layered edge
]
SPLIT_QUEUE = ["aragora.queue.worker"]  # keeps DebateWorker/DebateExecutor; loses create_default_executor imports

print("\nFULL-MOVE (remove_module):")
for m in FULL_MOVE_EVENTS + FULL_MOVE_QUEUE:
    if m in graph.modules:
        graph.remove_module(m)
        print("  removed module", m)
    else:
        print("  (absent)", m)

print("\nSPLIT (remove domain imports only, module stays):")
for m in SPLIT_EVENTS + SPLIT_QUEUE:
    if m in graph.modules:
        rm = remove_domain_imports(graph, m, DOMAIN_APP_IF)
        print(f"  {m}: removed imports -> {rm}")

after = illegal_edges(graph)
ev_after = targets(after, "aragora.events")
q_after = targets(after, "aragora.queue")

print("\n================ RESULT ================")
print("AFTER events targets:", sorted(ev_after))
print("AFTER queue  targets:", sorted(q_after))
print("\nevents->DOMAIN edges remaining (must be empty):", sorted(set(ev_after) - {"server"}))
if "server" in ev_after:
    print("  events->server remaining heads (expect dispatcher/async_dispatcher/registry"
          " = Batch1b-sweep/2c):", heads_for(ev_after["server"]))
print("queue-> edges remaining (must be empty):", sorted(q_after))

new_edges = set(after.keys()) - edge_keys_before
print("\nNEW illegal edges introduced by the simulation (must be empty):", sorted(new_edges))

ok = (set(ev_after) - {"server"}) == set() and set(q_after) == set() and new_edges == set()
print("\nSIMULATION", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
```

> This appendix simulates the **destination-free** view (removed/de-domained
> source modules). The home-assignment rule (§4.2) plus the per-batch full-layer
> re-check (§10 acceptance criterion 2) are what prove the *destinations* add no new
> edge; the two together cover both directions.
