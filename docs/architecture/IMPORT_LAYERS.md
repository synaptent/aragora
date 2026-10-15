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

This page is in its M4 form. Measured on `origin/main` at `c57b259dd1b1` (2026-10-15, after #10647): 166
layered names (every top-level module) and 18 baselined pairs, all in Partition A (pairs into
`aragora.server`). Partition B (every other pair) is empty, and the live pair set equals the baseline.

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
- Pinned by tests: `tests/ci/test_layer_membership.py` (exact per-layer sets, five lines, checker mapping,
  every top-level module layered),
  `tests/ci/test_importlinter_tc_policy.py` (the TYPE_CHECKING policy) and `tests/ci/test_shims_ledger.py`
  (every [shims.md](shims.md) row resolves at both paths to the same object).

## Current layer membership

Exactly what `.importlinter` declares today (166 names). The container package `aragora` itself is never a
member.

| layer | count | members |
|---|---|---|
| interface | 13 | `server` `cli` `mcp` `gateway` `bots` `channels` `integrations` `connectors` `__main__` `approvals` `client` `extensions` `webhooks` |
| application | 58 | `workflow` `pipeline` `nomic` `swarm` `gauntlet` `goals` `implement` `modes` `verticals` `autonomous` `broadcast` `canvas` `spectate` `analytics` `audit` `control_plane` `golden` `inbox` `marketplace` `services` `skills` `stores` `computer_use` `coordination` `export` `markets` `plugins` `prompt_engine` `receipts` `workspace` `brief_engine` `codex` `compat` `essay` `factory` `fixtures` `gti` `harnesses` `hooks` `ideacloud` `interrogation` `missions` `onboarding` `operations` `ops` `pdb` `playbooks` `policy` `prediction` `ralph` `reports` `review` `scheduler` `schedulers` `sync` `trail` `triage` `worktree` |
| domain | 43 | `debate` `agents` `memory` `knowledge` `ranking` `reasoning` `evidence` `evaluation` `explainability` `learning` `ml` `advocates` `analysis` `audience` `blockchain` `compliance` `container` `core` `deliberation` `documents` `embeddings` `epistemic` `evolution` `genesis` `heterogeneity` `insights` `introspection` `metrics` `moderation` `prompts` `pulse` `replay` `reputation` `rlm` `routing` `templates` `tools` `tournaments` `training` `uncertainty` `verification` `visualization` `work` |
| infrastructure | 31 | `storage` `resilience` `events` `observability` `security` `queue` `db` `caching` `billing` `backup` `migrations` `cache` `deletion_coordinator` `fabric` `maintenance` `monitoring` `performance` `resilience_config` `resilience_patterns` `runtime` `sandbox` `streaming` `telemetry` `transcription` `auth` `logging_config` `notifications` `persistence` `privacy` `rbac` `tenancy` |
| foundation | 21 | `api_errors` `config` `core_types` `exceptions` `errors` `utils` `protocols` `types` `__version__` `_lazy_imports` `core_protocols` `docs_only` `http_client` `models` `serialization` `task_brief` `topic_handler` `topic_spec` `topics` `type_protocols` `shared` |

Every line is complete: every `aragora/<name>.py` and `aragora/<name>/__init__.py` (except `__init__`) is a
member, and `tests/ci/test_layer_membership.py` fails when a new top-level module is not layered.
`aragora/live` is the Next.js frontend; it has no `__init__.py`, so it is not a Python module.

## Planned final membership

The design census of 2026-09-10 names 167 top-level modules (interface 13, application 59, domain 43,
infrastructure 31, foundation 21). One of them, the application module `tasks`, was deleted from `main`
by PR #9057 (commit `5ac7fa3fc280`, 2026-09-30), so it is not planned. The final membership is the remaining
166 names, all layered since tranche T6. A top-level module that appears after the census is classified
explicitly before it is layered.

| layer | status | count | members |
|---|---|---|---|
| interface | layered | 13 | `server` `cli` `mcp` `gateway` `bots` `channels` `integrations` `connectors` `__main__` `approvals` `client` `extensions` `webhooks` |
| application | layered | 58 | `workflow` `pipeline` `nomic` `swarm` `gauntlet` `goals` `implement` `modes` `verticals` `autonomous` `broadcast` `canvas` `spectate` `analytics` `audit` `control_plane` `golden` `inbox` `marketplace` `services` `skills` `stores` `computer_use` `coordination` `export` `markets` `plugins` `prompt_engine` `receipts` `workspace` `brief_engine` `codex` `compat` `essay` `factory` `fixtures` `gti` `harnesses` `hooks` `ideacloud` `interrogation` `missions` `onboarding` `operations` `ops` `pdb` `playbooks` `policy` `prediction` `ralph` `reports` `review` `scheduler` `schedulers` `sync` `trail` `triage` `worktree` |
| domain | layered | 43 | `debate` `agents` `memory` `knowledge` `ranking` `reasoning` `evidence` `evaluation` `explainability` `learning` `ml` `advocates` `analysis` `audience` `blockchain` `compliance` `container` `core` `deliberation` `documents` `embeddings` `epistemic` `evolution` `genesis` `heterogeneity` `insights` `introspection` `metrics` `moderation` `prompts` `pulse` `replay` `reputation` `rlm` `routing` `templates` `tools` `tournaments` `training` `uncertainty` `verification` `visualization` `work` |
| infrastructure | layered | 31 | `storage` `resilience` `events` `observability` `security` `queue` `db` `caching` `billing` `backup` `migrations` `cache` `deletion_coordinator` `fabric` `maintenance` `monitoring` `performance` `resilience_config` `resilience_patterns` `runtime` `sandbox` `streaming` `telemetry` `transcription` `auth` `logging_config` `notifications` `persistence` `privacy` `rbac` `tenancy` |
| foundation | layered | 21 | `api_errors` `config` `core_types` `exceptions` `errors` `utils` `protocols` `types` `__version__` `_lazy_imports` `core_protocols` `docs_only` `http_client` `models` `serialization` `task_brief` `topic_handler` `topic_spec` `topics` `type_protocols` `shared` |

Tranche T4a landed in milestone M3, and T4b, T5 and T6 landed in M4. Deprecated shim packages that are listed
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

`ignore_imports` in the layers contract holds exactly these four pairs and nothing else:

```text
aragora.exceptions -> aragora.connectors.exceptions
aragora.exceptions -> aragora.server.handlers.exceptions
aragora.utils.redis_cache -> aragora.caching.redis
aragora.exceptions -> aragora.control_plane.exceptions
```

The three `aragora.exceptions` seams keep the lazy exception fallbacks (the `control_plane` one mirrors the
control-plane exception types through `aragora.exceptions.__getattr__`, added with the M3 control_plane
split); the `redis_cache` seam is a one-release compatibility shim. Any further seam needs an explicit
architecture decision; it is never a convenience fix.

## Fix classes

When a pair violates the contract, use the first fix class that applies:

1. **Move symbol down** (with a shim). The symbol belongs in a lower package: move it, leave a deprecation
   re-export at the old path, add a [shims.md](shims.md) row, and test both paths with fixed inputs and
   expected outputs. Never move a symbol up with a shim; relocating up needs zero lower-layer callers first.
2. **Registry or protocol inversion.** The lower layer defines a `Protocol` or registration hook; the upper
   package registers its implementation in its own package init or in a non-startup server module. An
   unregistered hook raises an explicit error instead of succeeding silently. Examples:
   `aragora/core/decision_route_hooks.py` (#10331, #10335), `aragora/models/receipts/operations.py` (#10590)
   and `aragora/training/evaluation_protocols.py` (#10591, registered through an entry point).
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
| #10390 | `2652b4a148` | Code scanner inversion: `aragora.agents.code_scanners` holds the scanner registry, and `aragora.audit` registers its security scanner and bug detector from its init and through the `aragora.code_scanners` entry point. Resolved `aragora.agents -> aragora.audit` | 125 | 81 to 80 |
| #10394 | `bfa8a0e11a` | Audit split site flips: the rbac permission-denial audit and the compliance monitor's audit log lookups import from `aragora.observability` (`unified_audit`, `audit_log`). Resolved `aragora.compliance -> aragora.audit` and `aragora.rbac -> aragora.audit` | 125 | 65 to 63 |
| #10316 | `35844533c4` | Config seam: the data-dir and tenant-context primitives moved into `aragora.config` with re-exports at the old paths. Resolved `aragora.config -> aragora.persistence` and `aragora.config -> aragora.tenancy` | 125 | 63 to 61 |
| #10510 | `d0ed109463` | Tranche T4b: `computer_use coordination export markets plugins prompt_engine receipts workspace` (application); adopted `aragora.computer_use -> aragora.connectors`, `aragora.export -> aragora.cli`, `aragora.knowledge -> aragora.coordination` and `aragora.markets -> aragora.connectors`; none resolved | 133 | 61 to 65 |
| #10512 | `aeb96bccec` | Receipts foundation, part 1: the ODR JCS canonicalizer and the oversight attestation helpers moved down to `aragora.models.receipts.jcs` and `aragora.models.receipts.attestation`; `aragora.gauntlet.odr_jcs` and `aragora.gauntlet.attestation` are module aliases of the new modules | 133 | 65 |
| #10590 | `934a63ed7b` | Receipts foundation, part 2: the gauntlet receipt models and the legacy export receipt moved down to `aragora.models.receipts.gauntlet` and `aragora.models.receipts.legacy`. `aragora.models.receipts.operations` holds typed hooks for signing, exporters, the compliance generator, provider detection and failure classification, and an unregistered hook raises. `aragora.gauntlet.receipt_models` and `aragora.export.decision_receipt` alias the new modules and register the adapters from their own init | 133 | 65 |
| #10592 | `76e7486296` | Receipts foundation, part 3: the canonical hash and normalization helpers split into `aragora.models.receipts.canonical` (re-exported from `aragora.models.receipts.gauntlet`); the receipt facades import receipt signing on first use | 133 | 65 |
| #10591 | `8453160ddd` | Training evaluation inversion: `aragora.training.evaluation_protocols` holds the specialist-evaluator hook and the shared scoring rules, and `aragora.gauntlet.training_adapter` registers the gauntlet evaluator through the `aragora.training_evaluators` entry point. Resolved `aragora.training -> aragora.gauntlet` | 133 | 65 to 64 |
| #10594 | `06603465fb` | Receipt site flip: `aragora.evaluation.outcome_backed_receipt` imports the gauntlet receipt from `aragora.models.receipts.gauntlet`, and `aragora.agents.receipt_hooks` registers provider detection and failure classification for it. Resolved `aragora.evaluation -> aragora.gauntlet` | 133 | 64 to 63 |
| #10596 | `43c9522b05` | Compliance site flip: `aragora.compliance.oversight_fetch` and `oversight_pack` import the oversight attestation helpers and the JCS canonicalizer from `aragora.models.receipts`. Resolved `aragora.compliance -> aragora.gauntlet`, the last receipt pair | 133 | 63 to 62 |
| #10598 | `f14f82796b` | `cli.review` seam, part 1: the review-comment verdict parser and `SettlementReceipt` get homes in `aragora.review` (`comment_verdicts`, `settlement_receipt`), and the `aragora.swarm` sites and `aragora.review.observe_outcomes_cli` import them there. The homes are verbatim copies pinned to the CLI definitions by parity tests until the Tier-4 re-export edit; `aragora/swarm/quorum_evidence.py` keeps `aragora.swarm -> aragora.cli` live until then | 133 | 62 |
| #10599 | `3f78f841a0` | `cli.review` seam, part 2: `extract_review_findings` moved down to `aragora.review.diff_review`; `aragora.cli.review` re-exports it | 133 | 62 |
| #10600 | `6b7d46683e` | `cli.review` seam, part 3: the review debate runner (`run_review_debate`, `build_review_prompt`, `get_available_agents` and the review defaults) moved down to `aragora.review.diff_review` with re-exports; the OpenClaw PR review runner imports it there, so `aragora.compat` no longer imports `aragora.cli`. Resolved `aragora.export -> aragora.cli` and `aragora.nomic -> aragora.cli` (their only routes, from `aragora.export.case_study` and `aragora.nomic.execution_bridge`, ran through that import) | 133 | 62 to 60 |
| #10602 | `324ea90c24` | Tranche T5: `brief_engine codex compat essay factory fixtures gti harnesses hooks ideacloud interrogation missions onboarding operations ops pdb playbooks policy prediction ralph reports review scheduler schedulers sync trail triage worktree` (application); adopted `aragora.compat -> aragora.server`, `aragora.harnesses -> aragora.mcp`, `aragora.ideacloud -> aragora.connectors`, `aragora.ops -> aragora.gateway` and `aragora.ops -> aragora.server`; `aragora.implement`, `aragora.nomic`, `aragora.swarm` and `aragora.workflow -> aragora.mcp` resolved by reattribution (their only chains run through `aragora/harnesses/claude_code.py:570` and now count toward `aragora.harnesses -> aragora.mcp`) | 161 | 60 to 61 |
| #10607 | `2647ad8b5a` | Approval-request inversion: `aragora.events.approval_requests` holds the notifier hook, and `aragora.approvals` registers its chat notifier from its init and through the `aragora.approval_notifiers` entry point; the `aragora.workflow`, `aragora.pipeline` and `aragora.computer_use` sites call the hook, so none of them imports `aragora.approvals` (tranche T6). Resolved `aragora.computer_use -> aragora.connectors` (its only chain ran through `aragora.approvals.chat`) | 161 | 61 to 60 |
| #10609 | `f754e076ca` | Moved the gastown hook runner to `aragora.worktree.hook_runner`, with shims at `aragora.extensions.gastown.hooks` and `aragora.extensions.gastown.models`, so `aragora.nomic` no longer imports `aragora.extensions` (tranche T6) | 161 | 60 |
| #10610 | `7d461a3733` | Tranche T6: `__main__ approvals client extensions webhooks` (interface), so every top-level module is layered; no pair adopted and none resolved (interface is the top layer, and the pairs into `aragora.approvals` and `aragora.extensions` were removed by #10607 and #10609) | 166 | 60 |
| #10611 | `c5055f49b3` | Moved the OpenClaw policy and proxy to `aragora.compat.openclaw_policy` and `aragora.compat.openclaw_proxy`, the synthetic GitHub markets adapter to `aragora.markets.synthetic_github` and the repository crawler to `aragora.analysis.codebase.repository_crawler`, each with a package shim at the old path. Resolved `aragora.markets -> aragora.connectors`, `aragora.nomic -> aragora.connectors`, `aragora.ops -> aragora.gateway`, `aragora.skills -> aragora.gateway` and `aragora.workflow -> aragora.gateway` | 166 | 60 to 55 |
| #10612 | `f7712f1ee7` | `TaskStatus` and `TaskPriority` moved down to `aragora.types.task_scheduling`; `aragora.agents.scheduler_protocol` holds a distributed-scheduler factory slot that the control-plane init registers; `aragora/debate/extensions.py` imports the task-event and notification types from `aragora.events`, and the feedback phase drops an unused broadcast import. Resolved `aragora.agents -> aragora.control_plane`, `aragora.debate -> aragora.broadcast` and `aragora.knowledge -> aragora.control_plane` | 166 | 55 to 52 |
| #10613 | `21ea1d60c5` | Moved the improvement queue to `aragora.learning.improvement_queue` and `EmailRecipient` to `aragora.notifications.email_recipient`, with re-exports at the old paths. Resolved `aragora.knowledge -> aragora.integrations` and `aragora.memory -> aragora.nomic` | 166 | 52 to 50 |
| #10615 | `2504f01476` | Moved the SQLite improvement-goal queue (`ImprovementGoal`, `FeedbackGoal`, `ImprovementQueue`) to `aragora.learning.improvement_goal_queue`; `aragora.nomic.feedback_orchestrator` re-exports it. Resolved `aragora.introspection -> aragora.nomic` | 166 | 50 to 49 |
| #10617 | `019e9d7a4b` | Tier 3: `aragora/rbac/security_notifier.py` holds a security-notification sender slot that `aragora.control_plane.security_registration` registers from the control-plane init and through the `aragora.security_notifiers` entry point. Resolved `aragora.rbac -> aragora.control_plane` | 166 | 49 to 48 |
| #10616 | `92576835f8` | Tier 3: `AgentStatus` moved down to `aragora.types.agent_status`; the team selector takes an injected agent registry, and the marketplace template lookup goes through the `aragora/debate/template_registry_hooks.py` factory slot, which `aragora.marketplace.debate_registration` fills through the `aragora.debate_template_registries` entry point. Resolved `aragora.debate -> aragora.control_plane` and `aragora.debate -> aragora.marketplace` | 166 | 48 to 46 |
| #10622 | `ebbc07c408` | Moved the gateway decision router to `aragora.routing.gateway_decision_router`, the cross-workspace coordinator to `aragora.tenancy.cross_workspace` and the Supermemory client package to `aragora.memory.supermemory`, with package shims at the old paths. Resolved `aragora.routing -> aragora.gateway`, `aragora.knowledge -> aragora.coordination` and `aragora.memory -> aragora.connectors` | 166 | 46 to 43 |
| #10625 | `34678b89a6` | Moved the change-approval, spec test-generator and agent-role helpers from `aragora.nomic` to `aragora.agents` (`change_approval`, `spec_test_generator`, `roles`), and the context builder, repository profile and codebase summary to `aragora.rlm` (`context_builder`, `repository_profile`, `codebase_summary`), with package shims at the old paths. Resolved `aragora.agents -> aragora.nomic` and `aragora.rlm -> aragora.nomic` | 166 | 43 to 41 |
| #10626 | `a01b2692b9` | `aragora.stores.canonical` builds the gateway store through `aragora.stores.gateway_store_hook` (entry point `aragora.gateway_stores`), and `aragora.pipeline.execution_notifier` looks up chat connectors through `aragora.events.chat_connectors` (entry point `aragora.chat_connector_lookups`). Resolved `aragora.pipeline -> aragora.connectors` and `aragora.stores -> aragora.gateway` | 166 | 41 to 39 |
| #10627 | `1077f2bb58` | The post-debate coordinator builds the decision-plan bridge through `aragora.debate.decision_plan_bridges`, which `aragora.integrations.decision_bridge_registration` fills through the `aragora.decision_plan_bridges` entry point. Resolved `aragora.debate -> aragora.integrations` | 166 | 39 to 38 |
| #10628 | `ede40520b3` | Moved the receipt store to `aragora.storage.receipt_lifecycle_store` with a shim at `aragora.gauntlet.receipt_store`; the debate builds receipts from `aragora.models.receipts` and runs the post-debate gauntlet through `aragora.debate.gauntlet_runners` (entry point `aragora.debate_gauntlet_runners`). Resolved `aragora.debate -> aragora.gauntlet` | 166 | 38 to 37 |
| #10630 | `6e9475aff6` | Moved the spectator stream (`events`, `stream`, `redaction`, `ws_bridge`) from `aragora.spectate` to `aragora.events.spectate` and the PII redactor to `aragora.utils.pii_redactor`, with shims at the old paths; `aragora.harnesses.claude_code` gets the MCP config generator through `aragora.harnesses.mcp_config` (entry point `aragora.harness_mcp_configs`). Resolved `aragora.debate -> aragora.spectate` and `aragora.harnesses -> aragora.mcp` | 166 | 37 to 35 |
| #10631 | `4b4f194786` | The debate runs post-debate workflows through `aragora.debate.workflow_backends` (entry point `aragora.debate_workflow_backends`), and `aragora.services.ar_automation` sends invoices through `aragora.notifications.email_senders` (entry point `aragora.email_senders`). Resolved `aragora.debate -> aragora.workflow` and `aragora.services -> aragora.integrations` | 166 | 35 to 33 |
| #10634 | `479fb4655d` | The prompt builder reads operational-mode prompts through `aragora.debate.mode_prompts`, which `aragora.cli.mode_prompt_registration` fills through the `aragora.debate_mode_prompts` entry point. Resolved `aragora.debate -> aragora.modes` | 166 | 33 to 32 |
| #10635 | `a297d7d91b` | `aragora.runtime.connector_factory` holds a connector factory slot (`create_connector`) that `aragora.connectors.factory_registration` fills through the `aragora.connector_factories` entry point; the vertical tooling and the code reviewer build their connectors through it. Resolved `aragora.agents -> aragora.connectors` and `aragora.verticals -> aragora.connectors` | 166 | 32 to 30 |
| #10603 | `d5c2c579b2` | `cli.review` seam, part 4 (Tier 4): the CLI modules re-export the `aragora.review` homes (`comment_verdicts`, `settlement_receipt` and the new `github_transport` for the GitHub transport-error classification), so each object has one definition, and `aragora/swarm/quorum_evidence.py` imports them there. The four `aragora/review` modules the merge-gate classifier now loads join its Tier-4 authority closure. Resolved `aragora.swarm -> aragora.cli` | 166 | 30 to 29 |
| #10637 | `da34c46bba` | The debate evidence gatherers and the receipt delivery hook build their connectors through the connector factory (kinds `web_search`, `github`, `local_docs`, `slack_chat`, `teams_chat`). Resolved `aragora.debate -> aragora.connectors` | 166 | 29 to 28 |
| #10638 | `13f18e6fcf` | The knowledge adapters, the swarm commander and the IdeaCloud ingestors build their connectors through the connector factory (kinds `claude_mem`, `obsidian`, `feed_ingestor`, `twitter`). Resolved `aragora.knowledge -> aragora.connectors`, `aragora.swarm -> aragora.connectors` and `aragora.ideacloud -> aragora.connectors` | 166 | 28 to 25 |
| #10640 | `f6bb1c2588` | The services and the workflow nodes build their connectors through the connector factory (kinds `gmail`, `outlook`, `slack_enterprise`, `browser`, `web`); the connector step reads `is_retryable` and `retry_after` from the error instead of importing the connector exception classes. Resolved `aragora.services -> aragora.connectors` and `aragora.workflow -> aragora.connectors` | 166 | 25 to 23 |
| #10641 | `dc7a5290b4` | Moved the source `Evidence` record to `aragora.reasoning.source_evidence` (`aragora.connectors.base` re-exports it); the evidence collector builds its document connector through the connector factory (kind `documents`). Resolved `aragora.evidence -> aragora.connectors` | 166 | 23 to 22 |
| #10642 | `d38f5749f4` | Tier 3, settled by the operator: moved the Teams identity bridge to `aragora.auth.teams_identity`; `aragora.connectors.chat.teams_identity` is the same module object. Resolved `aragora.auth -> aragora.connectors` | 166 | 22 to 21 |
| #10643 | `5e8c7cf65a` | Moved the execution-mode and backbone run-ledger contracts to `aragora.types.execution_mode` and `aragora.types.backbone_contracts` (alias packages at the old `aragora.pipeline` paths), and `ApprovalMode`, `PlanStatus` and `RiskLevel` to `aragora.types.decision_plans`. None resolved: `aragora.debate -> aragora.pipeline` still had live sites | 166 | 21 |
| #10644 | `e3b5dd0ac1` | The debate reaches the decision pipeline through the declared slot `aragora.debate.pipeline_backends`, which `aragora.pipeline.debate_registration` fills through the `aragora.debate_pipeline_backends` entry point. Resolved `aragora.debate -> aragora.pipeline` | 166 | 21 to 20 |
| #10646 | `d8a5564fb9` | The debate reaches the nomic loop through the declared slot `aragora.debate.nomic_backends`, which `aragora.nomic.debate_registration` fills through the `aragora.debate_nomic_backends` entry point, at 13 of the 14 sites. None resolved: the last site, in `aragora/debate/team_selector.py`, waited for #10647 | 166 | 20 |
| #10647 | `c57b259dd1` | Tier 3: the team selector reads nomic regressions through the nomic backend, and `aragora.security.threat_intel_enrichment` builds its CVE client through the `aragora.security.cve_clients` slot, which `aragora.analysis.codebase.cve_registration` fills through the `aragora.security_cve_clients` entry point. Resolved `aragora.debate -> aragora.nomic` and `aragora.security -> aragora.analysis`, so Partition B is empty | 166 | 20 to 18 |

The two config pairs adopted by #10314 (`aragora.config -> aragora.persistence`, `aragora.config ->
aragora.tenancy`) were fixed by the config-seam PR #10316 (Tier 4, settled by the operator).

## Landing map by server module

This map explains each suggested landing module in the handover table below. "New" means the module does not
exist yet. "Alias" means the server module is already a deprecated alias of the lower module, so the fix is only
a site flip. Rows whose importers have no live site any more are kept so the migration has one list.

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
| `aragora.server.stream.broadcast` | none (module does not exist) | dead import: delete the branch or repoint at the real emitter/broadcast API |
| `aragora.server.handlers.debates.spectate` | `aragora.events.spectate` (holds the spectator stream since #10630) | move the collector registry and `push_spectator_event` down next to the stream |
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
| `aragora.server.handlers.openclaw` | `aragora.compat.openclaw.gateway_hooks` (new) | inversion: the server registers its handler over the compat logic |
| `aragora.server.handlers.debates.auditing` | `aragora.observability.audit_log` | flip the ops presence probe to the audit log's home |
| `aragora.server.documents` | `aragora.documents.parsing` (alias) | flip the import sites |
| `aragora.server.storage` | `aragora.storage.debate_storage` (alias) | flip the import sites |
| `aragora.server.stream.events` | `aragora.events.types` (alias) | flip the import sites |
| `aragora.server.metrics`, `aragora.server.prometheus` | `aragora.observability.server_metrics`, `aragora.observability.prometheus` (aliases) | flip the import sites |
| `aragora.server.middleware.tracing` | `aragora.observability.middleware.tracing` (alias) | flip the import sites |

## Partition A handover

Partition A is every violating pair whose imported package is `aragora.server` (pair level, not every server
import). These pairs stay baselined: the server-as-library migration of the server modules owns them, and the
layering work adds no new Partition A site. Measured on `c57b259dd1b1` (2026-10-15, after #10647): 18 pairs and
81 direct sites, and Partition B is empty, so the baseline holds exactly these 18 pairs. Earlier counts: 17 pairs
and 80 sites at `b0ab11df1366` with tranche T4a applied; the audit split (#10382) removed the `aragora.audit`
row, tranche T5 added `aragora.compat` and `aragora.ops` (one site each), and tranches T4b and T6 and the
Partition B burn-down (#10611 to #10647) added none.

- **sites** lists every direct, runtime (not `TYPE_CHECKING`) `from aragora.server...` or `import
  aragora.server...` statement inside the importer package, as `file:line` on `c57b259dd1b1`.
- **server modules imported** names the server modules imported at those sites.
- **indirect routes** lists routes that reach `aragora.server` through a package that is not layered. Every
  top-level module is layered since tranche T6, so none is left. The burn-down also removed the routes that
  earlier rows noted through `aragora.control_plane`: `aragora.debate`, `aragora.knowledge` and `aragora.rbac` no
  longer import it (#10616, #10612, #10617).
- Compared with the mission start (`ebe1bfd262`), 19 sites have a new `file:line`. Eighteen are the same import
  statements, shifted by edits elsewhere in their files; their introducing commits predate the mission. The
  nineteenth, `aragora/nomic/meta_planner_scan.py:203`, is the `FeedbackStore` import that the meta-planner
  split (#10499, not a layering PR) moved out of `aragora/nomic/meta_planner.py`. No layering PR added a site.
- Three sites are dead imports, not live couplings: `aragora/notifications/service.py:76` imports `get_emitter`,
  which `aragora.server.stream.emitter` does not define, and `aragora/pipeline/execution_notifier.py:212` and
  `:319` import `aragora.server.stream.broadcast`, which does not exist. Each raises `ImportError` inside a
  `try` that catches it (the notifier records a `websocket_broadcast` delivery error), so the branch never
  does its work. Delete the branch or repoint it at the real emitter or broadcast API; do not move it to a
  landing module.
- Re-measure after each fix. A pair leaves the baseline only when every direct site and indirect route is gone.

| importer | layer | server modules imported | sites (file:line) | suggested landing module | fix class | indirect routes |
|---|---|---|---|---|---|---|
| `aragora.auth` | infrastructure | `aragora.server.http_client_pool`, `aragora.server.middleware.audit_logger` | `aragora/auth/oidc.py:446`, `aragora/auth/oidc.py:683`, `aragora/auth/oidc.py:830`, `aragora/auth/oidc.py:903`, `aragora/auth/oidc.py:1023` | `aragora.observability.http_client_pool` (alias); `aragora.observability.audit_log` | flip the pool sites (the server module is an alias); move symbol down (`audit_security_event`, next to the compliance audit log) | none |
| `aragora.blockchain` | domain | `aragora.server.handlers.integrations.erc8004` | `aragora/blockchain/handler.py:85`, `aragora/blockchain/handler.py:105`, `aragora/blockchain/handler.py:128`, `aragora/blockchain/handler.py:147`, `aragora/blockchain/handler.py:164`, `aragora/blockchain/handler.py:179`, `aragora/blockchain/handler.py:200` | `aragora.blockchain.config`; `aragora.knowledge.mound.adapters.erc8004_adapter`; `aragora.blockchain.connector_registry` (new) | import the real homes of the config and adapter; registry for `ERC8004Connector`, which `aragora.connectors.blockchain` registers | none |
| `aragora.compat` | application | `aragora.server.handlers.openclaw` | `aragora/compat/openclaw/standalone.py:93` | `aragora.compat.openclaw.gateway_hooks` (new) | registry (the server registers `OpenClawGatewayHandler`, resolved through an entry point as the code-scanner registry is; moving the module up is costlier because `deploy/openclaw/docker-compose.standalone.yml` runs it by module path) | none |
| `aragora.control_plane` | application | `aragora.server.prometheus_control_plane`, `aragora.server.stream.control_plane_stream`, `aragora.server.http_client_pool` | `aragora/control_plane/arena_bridge.py:124`, `aragora/control_plane/arena_bridge.py:194`, `aragora/control_plane/channels.py:259`, `aragora/control_plane/channels.py:391`, `aragora/control_plane/channels.py:511`, `aragora/control_plane/health.py:25`, `aragora/control_plane/policy/manager.py:65`, `aragora/control_plane/scheduler.py:23` | `aragora.observability.metrics.control_plane`; `aragora.events.emitter` (new); `aragora.observability.http_client_pool` (alias) | move symbol down (the `record_control_plane_*` recorders); event (the control-plane stream); flip the pool sites | none |
| `aragora.debate` | domain | `aragora.server.handlers.metrics`, `aragora.server.research_phase`, `aragora.server.handlers.debates.spectate`, `aragora.server.webhook_delivery`, `aragora.server.handlers.features.provenance`, `aragora.server.decision_integrity_utils`, `aragora.server.result_router`, `aragora.server.debate_origin`, `aragora.server.prometheus_rlm`, `aragora.server.question_classifier`, `aragora.server.stream` | `aragora/debate/arena_phases.py:68`, `aragora/debate/context/sources.py:94`, `aragora/debate/context_gatherer/sources.py:104`, `aragora/debate/context_strategies/claude_search.py:39`, `aragora/debate/context_strategies/claude_search.py:56`, `aragora/debate/event_bridge.py:106`, `aragora/debate/hook_handlers.py:796`, `aragora/debate/hook_handlers.py:874`, `aragora/debate/hook_handlers.py:1113`, `aragora/debate/hook_handlers.py:1212`, `aragora/debate/orchestrator_runner.py:1961`, `aragora/debate/orchestrator_runner.py:1970`, `aragora/debate/phases/context_init.py:1848`, `aragora/debate/phases/context_init.py:1872`, `aragora/debate/phases/context_init.py:1893`, `aragora/debate/phases/feedback_phase.py:1082`, `aragora/debate/prompt_context_providers.py:41`, `aragora/debate/settlement_event_listener.py:121` | `aragora.debate.origin_hooks` (new); `aragora.debate.research_phase` (new); `aragora.debate.question_classifier` (new); `aragora.debate.decision_plan_hooks` (new); `aragora.events.webhook_delivery` (new); `aragora.observability.prometheus_rlm` (new); `aragora.events.emitter` (new); `aragora.events.spectate`; `aragora.observability.metrics.verification` (new); `aragora.reasoning.provenance` | registry (result routing, origins, decision plans, provenance managers); move symbol down (research phase, classifier, webhook delivery, RLM metrics, verification metric, and the spectator collector registry next to the spectator stream that #10630 moved into `aragora.events.spectate`); event (emitter) | none |
| `aragora.gauntlet` | application | `aragora.server.stream.emitter`, `aragora.server.stream.arena_hooks` | `aragora/gauntlet/api/export.py:85`, `aragora/gauntlet/orchestrator.py:488` | `aragora.events.emitter` (new); `aragora.events.context` | event (emitter); flip the `streaming_task_context` site | none |
| `aragora.implement` | application | `aragora.server.stream.arena_hooks` | `aragora/implement/executor.py:627`, `aragora/implement/executor.py:781`, `aragora/implement/executor.py:1295`, `aragora/implement/planner.py:206`, `aragora/implement/planner.py:328` | `aragora.events.context` | flip the sites (`streaming_task_context` already lives in `aragora.events.context`) | none |
| `aragora.inbox` | application | `aragora.server.debate_origin.registry`, `aragora.server.result_router` | `aragora/inbox/debate_router.py:695`, `aragora/inbox/debate_router.py:788` | `aragora.debate.origin_hooks` (new) | registry (origin lookup and result routing) | none |
| `aragora.knowledge` | domain | `aragora.server.handlers.social.notifications`, `aragora.server.handlers.features.control_plane` | `aragora/knowledge/mound/notifications.py:476`, `aragora/knowledge/mound/ops/staleness.py:134` | `aragora.queue.control_plane_tasks` (new); `aragora.notifications.service` | move symbol down (the shared task list); registry (the email integration registers as a notification provider) | none |
| `aragora.modes` | application | `aragora.server.stream.arena_hooks` | `aragora/modes/deep_audit.py:282` | `aragora.events.context` | flip the site | none |
| `aragora.nomic` | application | `aragora.server.stream.nomic_loop_stream`, `aragora.server.stream.pipeline_stream`, `aragora.server.handlers.sme.feedback`, `aragora.server.stream.arena_hooks`, `aragora.server.stream.emitter` | `aragora/nomic/cli_stream_bridge.py:128`, `aragora/nomic/cli_stream_bridge.py:150`, `aragora/nomic/meta_planner_scan.py:203`, `aragora/nomic/phases/context.py:395`, `aragora/nomic/phases/implement.py:249`, `aragora/nomic/phases/verify.py:464` | `aragora.events.context`; `aragora.events.emitter` (new); `aragora.cli.stream_bridge` (new); `aragora.storage.feedback_store` (new) | flip the `streaming_task_context` sites; event (emitter); relocate `cli_stream_bridge` up to the CLI (its only caller is `scripts/self_develop.py`); move symbol down (`FeedbackStore`) | none |
| `aragora.notifications` | infrastructure | `aragora.server.stream.emitter` | `aragora/notifications/service.py:76` | none: dead import, nothing to move | dead import: delete the branch or repoint at the real emitter/broadcast API; do not move to a landing module (`get_emitter` is not defined in `aragora.server.stream.emitter`, so the import raises `ImportError`, which the surrounding `except` swallows) | none |
| `aragora.ops` | application | `aragora.server.handlers.debates.auditing` | `aragora/ops/enterprise_validator.py:180` | `aragora.observability.audit_log` | flip the presence probe (it imports the debate auditing endpoint handler to check that audit logging is installed; the compliance audit log lives in `aragora.observability.audit_log`) | none |
| `aragora.pipeline` | application | `aragora.server.handlers.autonomous.approvals`, `aragora.server.result_router`, `aragora.server.stream.broadcast`, `aragora.server.stream.emitter`, `aragora.server.stream.pipeline_stream` | `aragora/pipeline/decision_integrity_utils.py:570`, `aragora/pipeline/decision_integrity_utils.py:690`, `aragora/pipeline/execution_notifier.py:202`, `aragora/pipeline/execution_notifier.py:212`, `aragora/pipeline/execution_notifier.py:310`, `aragora/pipeline/execution_notifier.py:319`, `aragora/pipeline/executor.py:327`, `aragora/pipeline/idea_to_execution.py:1378`, `aragora/pipeline/status_propagator.py:184` | `aragora.events.pipeline_stream` (new); `aragora.events.emitter` (new); `aragora.debate.origin_hooks` (new); `aragora.autonomous.loop_enhancement` | event (pipeline stream, emitter); registry (result routing); move symbol down (the `get_approval_flow` singleton next to `ApprovalFlow`). `aragora/pipeline/execution_notifier.py:212` and `:319`: dead import: delete the branch or repoint at the real emitter/broadcast API; do not move to a landing module (`aragora.server.stream.broadcast` does not exist, so both imports raise `ImportError`, which the notifier records as a `websocket_broadcast` delivery error, and no WebSocket broadcast is ever sent) | none |
| `aragora.ranking` | domain | `aragora.server.handlers.base` | `aragora/ranking/elo_matchmaking.py:148` | `aragora.caching.registry` | event (an invalidation hook keyed by event name, which the handler cache registers with) | none |
| `aragora.rbac` | infrastructure | `aragora.server.auth` | `aragora/rbac/decorators.py:231`, `aragora/rbac/decorators.py:269`, `aragora/rbac/decorators.py:638`, `aragora/rbac/decorators.py:681` | `aragora.auth.config` (new) | move symbol down (`auth_config`; the CORS origin list is passed in instead of read from the server) | none |
| `aragora.services` | application | `aragora.server.debate_factory`, `aragora.server.stream.usage_stream` | `aragora/services/email_debate.py:215`, `aragora/services/email_debate.py:323`, `aragora/services/expense_tracker.py:450`, `aragora/services/invoice_processor.py:418` | `aragora.debate.factory_hooks` (new); `aragora.events.emitter` (new) | registry (the server registers its arena factory); event (usage stream) | none |
| `aragora.skills` | application | `aragora.server.handlers.utils.url_security`, `aragora.server.http_client_pool` | `aragora/skills/builtin/evidence_fetch.py:26`, `aragora/skills/builtin/evidence_fetch.py:149`, `aragora/skills/builtin/evidence_fetch.py:263`, `aragora/skills/builtin/evidence_fetch.py:349` | `aragora.security.ssrf_protection`; `aragora.observability.http_client_pool` (alias) | flip to the existing `validate_url`; flip the pool sites | none |

## Related

- [shims.md](shims.md): every moved symbol, its old and new path, the PR and the retire-after condition.
- [ARCHITECTURE.md](ARCHITECTURE.md): system architecture overview.
