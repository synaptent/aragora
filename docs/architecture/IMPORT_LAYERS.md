# Import Layers

Aragora's top-level packages are arranged in five layers. A module may import its own layer or any layer
below it, never a layer above it:

```text
interface  >  application  >  domain  >  infrastructure  >  foundation
```

The contract lives in [.importlinter](../../.importlinter) and is checked by
[scripts/ci/check_import_contracts.py](../../scripts/ci/check_import_contracts.py) against the shrink-only
baseline [scripts/baselines/import_contracts_baseline.json](../../scripts/baselines/import_contracts_baseline.json).
Symbols moved down a layer keep a compatibility re-export at their old path; every such move is listed in
[shims.md](shims.md).

This page is in its M3 form. Measured on `origin/main` at `b0ab11df1366` (2026-10-06, after #10367) with
tranche T4a applied: 125 layered names, 85 baselined pairs (17 in Partition A, 68 in Partition B), and the
live pair set equals the baseline.

## Enforcement

- `.importlinter` declares one `layers` contract (`Aragora layers: interface > application > domain >
  infrastructure > foundation`) with the container `aragora`. Each layer is exactly one line of
  colon-separated names; the checker maps the five lines to the five layers by position and refuses any
  other line count.
- `scripts/ci/check_import_contracts.py` runs import-linter and compares the violating pairs (recorded at
  top-level package granularity, for example `aragora.config -> aragora.server`) with the baseline. Exit 0:
  no new pair. Exit 1: a new pair. Exit 2: an environment or usage error (missing config or baseline,
  import-linter not installed, a layer-count mismatch, or a refused freeze). `--json` prints the `new` and
  `resolved` pairs per contract; `--layers foundation,infrastructure` restricts fail-on-new to importers in
  those layers.
- `scripts/ci/measure_import_graph.py --check` ratchets the mutual import cycle count against
  `scripts/baselines/import_cycles_baseline.json` (140, shrink-only).
- Pinned by tests: `tests/ci/test_layer_membership.py` (exact per-layer sets, five lines, checker mapping),
  `tests/ci/test_importlinter_tc_policy.py` (the TYPE_CHECKING policy) and `tests/ci/test_shims_ledger.py`
  (every [shims.md](shims.md) row resolves at both paths to the same object).

## Current layer membership

Exactly what `.importlinter` declares today (125 names). The container package `aragora` itself is never a
member.

| layer | count | members |
|---|---|---|
| interface | 8 | `server` `cli` `mcp` `gateway` `bots` `channels` `integrations` `connectors` |
| application | 22 | `workflow` `pipeline` `nomic` `swarm` `gauntlet` `goals` `implement` `modes` `verticals` `autonomous` `broadcast` `canvas` `spectate` `analytics` `audit` `control_plane` `golden` `inbox` `marketplace` `services` `skills` `stores` |
| domain | 43 | `debate` `agents` `memory` `knowledge` `ranking` `reasoning` `evidence` `evaluation` `explainability` `learning` `ml` `advocates` `analysis` `audience` `blockchain` `compliance` `container` `core` `deliberation` `documents` `embeddings` `epistemic` `evolution` `genesis` `heterogeneity` `insights` `introspection` `metrics` `moderation` `prompts` `pulse` `replay` `reputation` `rlm` `routing` `templates` `tools` `tournaments` `training` `uncertainty` `verification` `visualization` `work` |
| infrastructure | 31 | `storage` `resilience` `events` `observability` `security` `queue` `db` `caching` `billing` `backup` `migrations` `cache` `deletion_coordinator` `fabric` `maintenance` `monitoring` `performance` `resilience_config` `resilience_patterns` `runtime` `sandbox` `streaming` `telemetry` `transcription` `auth` `logging_config` `notifications` `persistence` `privacy` `rbac` `tenancy` |
| foundation | 21 | `api_errors` `config` `core_types` `exceptions` `errors` `utils` `protocols` `types` `__version__` `_lazy_imports` `core_protocols` `docs_only` `http_client` `models` `serialization` `task_brief` `topic_handler` `topic_spec` `topics` `type_protocols` `shared` |

The domain, infrastructure and foundation lines are complete. The interface and application lines grow in
later tranches (next section).

## Planned final membership

The design census of 2026-09-10 names 167 top-level modules (interface 13, application 59, domain 43,
infrastructure 31, foundation 21). One of them, the application module `tasks`, was deleted from `main`
by PR #9057 (commit `5ac7fa3fc280`, 2026-09-30), so it is not planned. The final membership is the remaining
166 names. A top-level module that appears after the census is classified explicitly before it is layered.

| layer | status | count | members |
|---|---|---|---|
| interface | layered | 8 | `server` `cli` `mcp` `gateway` `bots` `channels` `integrations` `connectors` |
| interface | tranche T6 | 5 | `__main__` `approvals` `client` `extensions` `webhooks` |
| application | layered | 22 | `workflow` `pipeline` `nomic` `swarm` `gauntlet` `goals` `implement` `modes` `verticals` `autonomous` `broadcast` `canvas` `spectate` `analytics` `audit` `control_plane` `golden` `inbox` `marketplace` `services` `skills` `stores` |
| application | tranche T4b | 8 | `computer_use` `coordination` `export` `markets` `plugins` `prompt_engine` `receipts` `workspace` |
| application | tranche T5 | 28 | `brief_engine` `codex` `compat` `essay` `factory` `fixtures` `gti` `harnesses` `hooks` `ideacloud` `interrogation` `missions` `onboarding` `operations` `ops` `pdb` `playbooks` `policy` `prediction` `ralph` `reports` `review` `scheduler` `schedulers` `sync` `trail` `triage` `worktree` |
| domain | layered | 43 | `debate` `agents` `memory` `knowledge` `ranking` `reasoning` `evidence` `evaluation` `explainability` `learning` `ml` `advocates` `analysis` `audience` `blockchain` `compliance` `container` `core` `deliberation` `documents` `embeddings` `epistemic` `evolution` `genesis` `heterogeneity` `insights` `introspection` `metrics` `moderation` `prompts` `pulse` `replay` `reputation` `rlm` `routing` `templates` `tools` `tournaments` `training` `uncertainty` `verification` `visualization` `work` |
| infrastructure | layered | 31 | `storage` `resilience` `events` `observability` `security` `queue` `db` `caching` `billing` `backup` `migrations` `cache` `deletion_coordinator` `fabric` `maintenance` `monitoring` `performance` `resilience_config` `resilience_patterns` `runtime` `sandbox` `streaming` `telemetry` `transcription` `auth` `logging_config` `notifications` `persistence` `privacy` `rbac` `tenancy` |
| foundation | layered | 21 | `api_errors` `config` `core_types` `exceptions` `errors` `utils` `protocols` `types` `__version__` `_lazy_imports` `core_protocols` `docs_only` `http_client` `models` `serialization` `task_brief` `topic_handler` `topic_spec` `topics` `type_protocols` `shared` |

Tranche T4a landed in milestone M3; T4b, T5 and T6 land in M4. Deprecated shim packages that are listed
(`cache`, `core_protocols`, `metrics`, `monitoring`, `telemetry`, `type_protocols`, `operations`,
`schedulers`, `resilience_patterns`) stay listed until they are retired; when a listed module is deleted, its
name leaves `.importlinter` in the same PR, because import-linter errors on a missing layer module.

## Runtime and TYPE_CHECKING policy

`[importlinter]` carries `exclude_type_checking_imports = True` (spelling `True`, added by #10296). Imports
inside `if TYPE_CHECKING:` create no layer edge. Every other import does, at any scope: grimp records the
physical import site, so a lazy or function-scope import still counts. Rules:

- Do not hide a runtime dependency behind `importlib`, `__import__` or a function-scope import.
- Use `TYPE_CHECKING` only for annotation-only use (stringified annotations or a local `Protocol`).
- `scripts/ci/measure_import_graph.py` also excludes `TYPE_CHECKING` imports, so both tools see the same
  graph.

## Sanctioned seams

`ignore_imports` in the layers contract holds exactly these three pairs and nothing else:

```text
aragora.exceptions -> aragora.connectors.exceptions
aragora.exceptions -> aragora.server.handlers.exceptions
aragora.utils.redis_cache -> aragora.caching.redis
```

The two `aragora.exceptions` seams keep the lazy exception fallbacks; the `redis_cache` seam is a
one-release compatibility shim. A fourth seam, for the `control_plane` exceptions mirror, is planned for the
M3 control_plane split. Until it lands, the pair from `exceptions` to `control_plane` is baselined (adopted
with tranche T4a). Any further seam needs an explicit architecture decision; it is never a convenience fix.

## Fix classes

When a pair violates the contract, use the first fix class that applies:

1. **Move symbol down** (with a shim). The symbol belongs in a lower package: move it, leave a deprecation
   re-export at the old path, add a [shims.md](shims.md) row, and test both paths with fixed inputs and
   expected outputs. Never move a symbol up with a shim; relocating up needs zero lower-layer callers first.
2. **Registry or protocol inversion.** The lower layer defines a `Protocol` or registration hook; the upper
   package registers its implementation in its own package init or in a non-startup server module. An
   unregistered hook raises an explicit error instead of succeeding silently. Example:
   `aragora/core/decision_route_hooks.py` (#10331, #10335).
3. **Event emission.** Replace the direct upward call with an event on the existing `aragora.events`
   machinery.
4. **Delete the import** when it is dead or trivially replaceable (#10325 deleted the dead
   `aragora.rlm.compressor` import in `aragora/events/cross_subscribers/manager.py`).
5. **Sanctioned seam** (`ignore_imports`): only the pairs listed above.

## Tranche procedure

Tranches add names to existing layer lines; they never add a line. Run the steps from a worktree based on
`origin/main` with `PYTHONPATH` set to that worktree.

1. Append the tranche's names to their layer lines in `.importlinter`, and update the tables on this page and
   `tests/ci/test_layer_membership.py`.
2. See what the tranche exposes. Exit 1 lists the new pairs:

   ```bash
   python3 scripts/ci/check_import_contracts.py --json
   ```

3. Fix the cheap pairs with the fix classes above, then adopt the rest:

   ```bash
   python3 scripts/ci/check_import_contracts.py --freeze --adopt
   ```

4. Confirm that both commands exit 0:

   ```bash
   python3 scripts/ci/check_import_contracts.py
   python3 scripts/ci/measure_import_graph.py --check
   ```

5. Commit `.importlinter`, the baseline and the fixes together. The adoption PR body carries a table of the
   adopted pairs (importer, imported, sites, planned fix class, planned PR).

The baseline grows only in such an adoption PR. After a fix lands, shrink the baseline with the plain,
shrink-only freeze:

```bash
python3 scripts/ci/check_import_contracts.py --freeze
```

Plain `--freeze` refuses to add a pair (exit 2) and never hand-edits the file. A resolved pair must not come
back.

## Tranche history

Facts below are taken from the PR descriptions, which are authoritative. The squash commit message of #10325
attributes the `agents` to `gauntlet` chain to `compliance`; the PR description corrects it (the chain runs
through `aragora.training.specialist_models`).

| PR | merge commit | change | layered names | baseline pairs |
|---|---|---|---|---|
| #10296 | `01e1a35343` | `exclude_type_checking_imports = True`; fixed `aragora.reasoning -> aragora.gauntlet` (annotation-only import moved under `TYPE_CHECKING`); adopted `aragora.evaluation -> aragora.gauntlet` and `aragora.swarm -> aragora.cli`; 10 pairs resolved under the policy | 51 | 51 to 43 |
| #10299 | `d618fd3ac9` | Tranche T1: 25 foundation and infrastructure names, no new pair | 76 | 43 |
| #10301 | `7ef59e9766` | Moved the debate embedding cache down to `aragora.shared.embedding_cache` with a shim, so T2 does not expose `aragora.shared -> aragora.debate` | 76 | 43 |
| #10307 | `394aea2dae` | Moved debate tracing down to `aragora.observability.debate_tracing` (so T2 does not expose `aragora.logging_config -> aragora.debate`) and the shift ledger to `aragora.evaluation.shift_ledger`, both with shims | 76 | 43 |
| #10314 | `73308762b8` | Tranche T2: `auth logging_config notifications persistence privacy rbac tenancy` (infrastructure) and `shared` (foundation); 6 pairs adopted, `aragora.workflow -> aragora.server` resolved | 84 | 43 to 48 |
| #10325 | `7f6f13fd7b` | Tranche T3: 32 domain names; 12 pairs adopted; `aragora.events -> aragora.rlm` fixed by deleting a dead import; `aragora.agents -> aragora.gauntlet` resolved by reattribution (its only chain, `aragora.agents.specialist_factory` to `aragora.training.specialist_models` to `aragora.gauntlet.config`, is now reported as `aragora.training -> aragora.gauntlet`) | 116 | 48 to 59 |
| #10331 | `846b967795` | Decision-router inversion, part 1: hooks in `aragora/core/decision_route_hooks.py`; removes `aragora.core` imports of connectors, pipeline and server | 116 | 59 to 56 |
| #10335 | `ba7ec9c83b` | Decision-router inversion, part 2: keyed route targets for workflow and gauntlet | 116 | 56 to 54 |
| #10376 | `d4c9f6c7d5` | Tranche T4a: 9 application names; 35 pairs adopted; `aragora.skills -> aragora.cli` fixed by deleting a dead import; `aragora.agents -> aragora.server` and the `debate`, `nomic` and `pipeline` pairs to `aragora.gateway` resolved by reattribution (their only routes ran through `aragora.control_plane.scheduler` and `aragora.stores.canonical`, and now count toward `aragora.control_plane -> aragora.server` and `aragora.stores -> aragora.gateway`) | 125 | 54 to 85 |
| #10382 | `4ec2d475be` | Audit split: the compliance audit log, the unified audit facade and the audit persistence backends moved down to `aragora.observability` (`audit_log`, `unified_audit`, `audit_persistence`) with re-exports at the old `aragora.audit` paths; the server registers the HTTP middleware audit logger; the storage, debate and rlm sites flipped. Resolved `aragora.audit -> aragora.server`, `aragora.debate -> aragora.audit`, `aragora.rlm -> aragora.audit` and `aragora.storage -> aragora.audit` | 125 | 85 to 81 |

The two config pairs adopted by #10314 (`aragora.config -> aragora.persistence`, `aragora.config ->
aragora.tenancy`) are fixed by the config-seam PR #10316 (Tier 4), which was prepared and is awaiting
operator settlement at the time of writing.

## Partition A handover

Partition A is every violating pair whose imported package is `aragora.server` (pair level, not every server
import). These pairs stay baselined: the server-as-library migration of the server modules owns them, and the
layering work adds no new Partition A site. Measured on `b0ab11df1366` with tranche T4a applied: 17 pairs, 80
direct sites.

- **sites** lists every direct, runtime (not `TYPE_CHECKING`) `from aragora.server...` or `import
  aragora.server...` statement inside the importer package.
- **server modules imported** names the server modules imported at those sites.
- **indirect routes** lists routes that reach `aragora.server` through a package that is not layered yet. None
  is left after tranche T4a. The routes through `aragora.control_plane` and `aragora.audit` now count toward
  those packages' own rows, which T4a added. `aragora.agents` had no direct site (its only route ran through
  `aragora/control_plane/scheduler.py:23`), so its pair left the baseline and the site moved to the
  `aragora.control_plane` row.
- The audit split moved `aragora/audit/unified.py` to `aragora/observability/unified_audit.py` and replaced its
  `aragora.server.middleware.audit_logger` import with `register_middleware_audit_logger`, which
  `aragora.server.decision_routes.register_decision_routes` calls. The `aragora.audit` pair left the baseline,
  and the route from `aragora/rbac/decorators.py:58` through `aragora.audit.unified` no longer reaches
  `aragora.server`.
- Re-measure after each fix. A pair leaves the baseline only when every direct site and indirect route is gone.

| importer | layer | server modules imported | sites (file:line) | suggested landing module | fix class | indirect routes |
|---|---|---|---|---|---|---|
| `aragora.auth` | infrastructure | `aragora.server.http_client_pool`, `aragora.server.middleware.audit_logger` | `aragora/auth/oidc.py:446`, `aragora/auth/oidc.py:683`, `aragora/auth/oidc.py:903`, `aragora/auth/oidc.py:1023`, `aragora/auth/oidc.py:830` | `aragora.observability.http_client_pool` (pool); `aragora.observability.audit_log` (new, audit events) | flip the pool sites (the server module is an alias); move symbol down for the audit logger | none |
| `aragora.blockchain` | domain | `aragora.server.handlers.integrations.erc8004` | `aragora/blockchain/handler.py:85`, `aragora/blockchain/handler.py:105`, `aragora/blockchain/handler.py:128`, `aragora/blockchain/handler.py:147`, `aragora/blockchain/handler.py:164`, `aragora/blockchain/handler.py:179`, `aragora/blockchain/handler.py:200` | `aragora.blockchain.config`; `aragora.knowledge.mound.adapters.erc8004_adapter`; `aragora.blockchain.connector_registry` (new) | import the real homes of the config and adapter; registry for `ERC8004Connector`, which `aragora.connectors.blockchain` registers | none |
| `aragora.control_plane` | application | `aragora.server.prometheus_control_plane`, `aragora.server.stream.control_plane_stream`, `aragora.server.http_client_pool` | `aragora/control_plane/arena_bridge.py:124`, `aragora/control_plane/arena_bridge.py:194`, `aragora/control_plane/channels.py:291`, `aragora/control_plane/channels.py:423`, `aragora/control_plane/channels.py:543`, `aragora/control_plane/health.py:25`, `aragora/control_plane/policy/manager.py:65`, `aragora/control_plane/scheduler.py:23` | `aragora.observability.metrics.control_plane`; `aragora.events.emitter` (new); `aragora.observability.http_client_pool` (alias) | move symbol down (the `record_control_plane_*` recorders); event (the control-plane stream); flip the pool sites | none |
| `aragora.debate` | domain | `aragora.server.result_router`, `aragora.server.debate_origin`, `aragora.server.research_phase`, `aragora.server.question_classifier`, `aragora.server.decision_integrity_utils`, `aragora.server.webhook_delivery`, `aragora.server.prometheus_rlm`, `aragora.server.stream`, `aragora.server.handlers.debates.spectate`, `aragora.server.handlers.metrics`, `aragora.server.handlers.features.provenance` | `aragora/debate/orchestrator_runner.py:1942`, `aragora/debate/orchestrator_runner.py:1951`, `aragora/debate/phases/feedback_phase.py:1081`, `aragora/debate/context_strategies/claude_search.py:39`, `aragora/debate/context_strategies/claude_search.py:56`, `aragora/debate/context/sources.py:90`, `aragora/debate/context_gatherer/sources.py:100`, `aragora/debate/prompt_context_providers.py:41`, `aragora/debate/hook_handlers.py:794`, `aragora/debate/hook_handlers.py:872`, `aragora/debate/hook_handlers.py:1108`, `aragora/debate/hook_handlers.py:1207`, `aragora/debate/phases/context_init.py:1848`, `aragora/debate/phases/context_init.py:1872`, `aragora/debate/phases/context_init.py:1893`, `aragora/debate/settlement_event_listener.py:121`, `aragora/debate/event_bridge.py:106`, `aragora/debate/arena_phases.py:68` | `aragora.debate.origin_hooks` (new); `aragora.debate.research_phase` (new); `aragora.debate.question_classifier` (new); `aragora.debate.decision_plan_hooks` (new); `aragora.events.webhook_delivery` (new); `aragora.observability.prometheus_rlm` (new); `aragora.events.emitter` (new); `aragora.events.spectator_bus` (new); `aragora.observability.metrics.verification` (new); `aragora.reasoning.provenance` | registry (result routing, origins, decision plans, provenance managers); move symbol down (research phase, classifier, webhook delivery, RLM metrics, verification metric); event (emitter, spectator events) | none (since T4a, the route from `aragora/debate/extensions.py:802` through `aragora.control_plane.channels` counts toward the `aragora.control_plane` row) |
| `aragora.gauntlet` | application | `aragora.server.stream.emitter`, `aragora.server.stream.arena_hooks` | `aragora/gauntlet/api/export.py:85`, `aragora/gauntlet/orchestrator.py:488` | `aragora.events.emitter` (new); `aragora.events.context` | event (emitter); flip the `streaming_task_context` site | none |
| `aragora.implement` | application | `aragora.server.stream.arena_hooks` | `aragora/implement/executor.py:627`, `aragora/implement/executor.py:769`, `aragora/implement/executor.py:1283`, `aragora/implement/planner.py:206`, `aragora/implement/planner.py:328` | `aragora.events.context` | flip the sites (`streaming_task_context` already lives in `aragora.events.context`) | none |
| `aragora.inbox` | application | `aragora.server.debate_origin.registry`, `aragora.server.result_router` | `aragora/inbox/debate_router.py:695`, `aragora/inbox/debate_router.py:788` | `aragora.debate.origin_hooks` (new) | registry (origin lookup and result routing) | none |
| `aragora.knowledge` | domain | `aragora.server.handlers.features.control_plane`, `aragora.server.handlers.social.notifications` | `aragora/knowledge/mound/ops/staleness.py:134`, `aragora/knowledge/mound/notifications.py:476` | `aragora.queue.control_plane_tasks` (new); `aragora.notifications.service` | move symbol down (the shared task list); registry (the email integration registers as a notification provider) | none (since T4a, the route from `aragora/knowledge/mound/revalidation_scheduler.py:241` through `aragora.control_plane.scheduler` counts toward the `aragora.control_plane` row) |
| `aragora.modes` | application | `aragora.server.stream.arena_hooks` | `aragora/modes/deep_audit.py:282` | `aragora.events.context` | flip the site | none |
| `aragora.nomic` | application | `aragora.server.stream.arena_hooks`, `aragora.server.stream.emitter`, `aragora.server.stream.nomic_loop_stream`, `aragora.server.stream.pipeline_stream`, `aragora.server.handlers.sme.feedback` | `aragora/nomic/phases/context.py:377`, `aragora/nomic/phases/verify.py:464`, `aragora/nomic/phases/implement.py:249`, `aragora/nomic/cli_stream_bridge.py:128`, `aragora/nomic/cli_stream_bridge.py:150`, `aragora/nomic/meta_planner.py:2009` | `aragora.events.context`; `aragora.events.emitter` (new); `aragora.cli.stream_bridge` (new); `aragora.storage.feedback_store` (new) | flip the `streaming_task_context` sites; event (emitter); relocate `cli_stream_bridge` up to the CLI (its only caller is `scripts/self_develop.py`); move symbol down (`FeedbackStore`) | none (since T4a, the route from `aragora/nomic/testfixer/worker_loop.py` through `aragora.control_plane` counts toward the `aragora.control_plane` row) |
| `aragora.notifications` | infrastructure | `aragora.server.stream.emitter` | `aragora/notifications/service.py:76` | none needed (if an emitter is wanted later, `aragora.events.emitter`) | delete (dead import: `get_emitter` does not exist in that module) | none |
| `aragora.pipeline` | application | `aragora.server.stream.pipeline_stream`, `aragora.server.stream.emitter`, `aragora.server.stream.broadcast`, `aragora.server.result_router`, `aragora.server.handlers.autonomous.approvals` | `aragora/pipeline/idea_to_execution.py:1378`, `aragora/pipeline/status_propagator.py:184`, `aragora/pipeline/executor.py:327`, `aragora/pipeline/execution_notifier.py:202`, `aragora/pipeline/execution_notifier.py:212`, `aragora/pipeline/execution_notifier.py:299`, `aragora/pipeline/execution_notifier.py:308`, `aragora/pipeline/decision_integrity_utils.py:570`, `aragora/pipeline/decision_integrity_utils.py:690` | `aragora.events.pipeline_stream` (new); `aragora.events.emitter` (new); `aragora.debate.origin_hooks` (new); `aragora.autonomous.loop_enhancement` | event (pipeline stream, emitter); delete the two `aragora.server.stream.broadcast` imports (that module does not exist, so they always raise `ImportError`); registry (result routing); move symbol down (the `get_approval_flow` singleton next to `ApprovalFlow`) | none |
| `aragora.ranking` | domain | `aragora.server.handlers.base` | `aragora/ranking/elo_matchmaking.py:148` | `aragora.caching.registry` | event (an invalidation hook keyed by event name, which the handler cache registers with) | none |
| `aragora.rbac` | infrastructure | `aragora.server.auth` | `aragora/rbac/decorators.py:231`, `aragora/rbac/decorators.py:269`, `aragora/rbac/decorators.py:638`, `aragora/rbac/decorators.py:681` | `aragora.auth.config` (new) | move symbol down (`auth_config`; the CORS origin list is passed in instead of read from the server) | none (since T4a, the route from `aragora/rbac/emergency.py:749` through `aragora.control_plane.notifications` counts toward the `aragora.control_plane` row) |
| `aragora.services` | application | `aragora.server.debate_factory`, `aragora.server.stream.usage_stream` | `aragora/services/email_debate.py:215`, `aragora/services/email_debate.py:323`, `aragora/services/expense_tracker.py:450`, `aragora/services/invoice_processor.py:418` | `aragora.debate.factory_hooks` (new); `aragora.events.emitter` (new) | registry (the server registers its arena factory); event (usage stream) | none |
| `aragora.skills` | application | `aragora.server.handlers.utils.url_security`, `aragora.server.http_client_pool` | `aragora/skills/builtin/evidence_fetch.py:26`, `aragora/skills/builtin/evidence_fetch.py:149`, `aragora/skills/builtin/evidence_fetch.py:263`, `aragora/skills/builtin/evidence_fetch.py:350` | `aragora.security.ssrf_protection`; `aragora.observability.http_client_pool` (alias) | flip to the existing `validate_url`; flip the pool sites | none |

### Landing map by server module

This map explains each suggested landing module. "New" means the module does not exist yet. "Alias" means the
server module is already a deprecated alias of the lower module, so the fix is only a site flip. Server modules
whose importers are not layered yet (they arrive with tranches T4b and T5) are included so the migration has one
list.

| server module | suggested landing module | fix |
|---|---|---|
| `aragora.server.http_client_pool` | `aragora.observability.http_client_pool` (alias) | flip the import sites |
| `aragora.server.prometheus_control_plane` | `aragora.observability.metrics.control_plane` | move the `record_control_plane_*` recorders down; the server module re-exports them |
| `aragora.server.prometheus_rlm` | `aragora.observability.prometheus_rlm` (new, next to `prometheus_cross_pollination`) | move symbol down |
| `aragora.server.middleware.audit_logger` | `aragora.observability.audit_log` (holds the compliance audit log since the audit split; the HTTP middleware logger has not moved) | move symbol down |
| `aragora.server.auth` (`auth_config`) | `aragora.auth.config` (new) | move symbol down; the CORS origin list is passed in |
| `aragora.server.handlers.integrations.erc8004` | `aragora.blockchain.config`, `aragora.knowledge.mound.adapters.erc8004_adapter`, `aragora.blockchain.connector_registry` (new) | import the real homes; `aragora.connectors.blockchain` registers `ERC8004Connector` |
| `aragora.server.result_router`, `aragora.server.debate_origin` | `aragora.debate.origin_hooks` (new) | registry: the server registers origin lookup, receipt posting and result routing |
| `aragora.server.research_phase` | `aragora.debate.research_phase` (new) | move symbol down (it imports only `aragora.agents`, `aragora.config` and `aragora.models`) |
| `aragora.server.question_classifier` | `aragora.debate.question_classifier` (new) | move symbol down (it imports only `aragora.agents`) |
| `aragora.server.decision_integrity_utils` | `aragora.debate.decision_plan_hooks` (new) | registry: the server module is an alias of `aragora.pipeline.decision_integrity_utils`, which sits above `aragora.debate`; `aragora.pipeline` registers, as in `aragora/core/decision_route_hooks.py` |
| `aragora.server.webhook_delivery` | `aragora.events.webhook_delivery` (new) | move symbol down (it imports only `aragora.observability` and `aragora.persistence`) |
| `aragora.server.stream`, `aragora.server.stream.emitter` | `aragora.events.emitter` (new) | move `SyncEventEmitter` and `get_global_emitter` down; first remove or invert the function-scope `aragora.debate.telemetry_config` import in the emitter |
| `aragora.server.stream.arena_hooks` (`streaming_task_context`) | `aragora.events.context` | flip the import sites (the server module re-exports this function) |
| `aragora.server.stream.pipeline_stream` | `aragora.events.pipeline_stream` (new) | move the pipeline emitter down; the aiohttp routes stay in the server |
| `aragora.server.stream.nomic_loop_stream` | `aragora.cli.stream_bridge` (new) | relocate `aragora.nomic.cli_stream_bridge` up to the CLI |
| `aragora.server.stream.broadcast` | none (module does not exist) | delete the imports |
| `aragora.server.handlers.debates.spectate` | `aragora.events.spectator_bus` (new) | move the collector registry and `push_spectator_event` down |
| `aragora.server.handlers.metrics` (`track_verification`) | `aragora.observability.metrics.verification` (new) | move symbol down |
| `aragora.server.handlers.features.provenance` | `aragora.reasoning.provenance` | registry of per-debate managers next to `ProvenanceManager` |
| `aragora.server.handlers.features.control_plane` (`_task_queue`) | `aragora.queue.control_plane_tasks` (new) | move the shared task list down; the handler imports it |
| `aragora.server.handlers.social.notifications` | `aragora.notifications.service` | registry: send through the notification service; the email integration registers as a provider |
| `aragora.server.handlers.sme.feedback`, `aragora.server.handlers.feedback` | `aragora.storage.feedback_store` (new) | move `FeedbackStore` (SQLite) down |
| `aragora.server.handlers.autonomous.approvals` | `aragora.autonomous.loop_enhancement` | move the `get_approval_flow` singleton next to `ApprovalFlow` |
| `aragora.server.handlers.base` (`invalidate_on_event`) | `aragora.caching.registry` | event-keyed invalidation hook that the handler cache registers with |
| `aragora.server.stream.control_plane_stream`, `aragora.server.stream.usage_stream`, `aragora.server.stream.broadcaster` | `aragora.events.emitter` (new) | event emission |
| `aragora.server.debate_factory` | `aragora.debate.factory_hooks` (new) | registry: the server registers its arena factory |
| `aragora.server.handlers.utils.url_security` | `aragora.security.ssrf_protection` | flip to the existing `validate_url` |
| `aragora.server.handlers.openclaw` | `aragora.compat` | inversion: the server registers its handler over the compat logic |
| `aragora.server.documents` | `aragora.documents.parsing` (alias) | flip the import sites |
| `aragora.server.storage` | `aragora.storage.debate_storage` (alias) | flip the import sites |
| `aragora.server.stream.events` | `aragora.events.types` (alias) | flip the import sites |
| `aragora.server.metrics`, `aragora.server.prometheus` | `aragora.observability.server_metrics`, `aragora.observability.prometheus` (aliases) | flip the import sites |
| `aragora.server.middleware.tracing` | `aragora.observability.middleware.tracing` (alias) | flip the import sites |

## Related

- [shims.md](shims.md): every moved symbol, its old and new path, the PR and the retire-after condition.
- [ARCHITECTURE.md](ARCHITECTURE.md): system architecture overview.
