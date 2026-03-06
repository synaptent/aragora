# Dev Swarm Coordination

Aragora already has most of the primitives needed for concurrent multi-agent development. The current friction comes from a gap between those primitives and the operational protocol used by Codex/Claude sessions.

## Diagnosis

The repository already solves a large part of the problem:

- worktree/session lifecycle:
  - `scripts/codex_session.sh`
  - `scripts/codex_worktree_autopilot.py`
  - `aragora/worktree/lifecycle.py`
  - `aragora/worktree/maintainer.py`
- human/API-visible coordination state:
  - `aragora/worktree/fleet.py`
  - `aragora/cli/commands/worktree.py`
  - `aragora/server/handlers/control_plane/coordination.py`
- merge/reconcile engines:
  - `aragora/nomic/branch_coordinator.py`
  - `aragora/coordination/reconciler.py`
  - `aragora/coordination/resolver.py`
- queues, events, and receipts:
  - `aragora/nomic/global_work_queue.py`
  - `aragora/nomic/event_bus.py`
  - `aragora/nomic/cycle_receipt.py`
  - `aragora/pipeline/receipt_generator.py`

What was missing was not another worktree manager. The missing layer was a bounded coordination protocol:

- who owns a task
- which files they may change
- how that ownership expires
- how finished work becomes integration work
- how abandoned work becomes salvage work instead of silent loss

## Canonical State Planes

The codebase currently has several overlapping coordination stores. Going forward, the intended roles are:

- `worktree/fleet`: canonical human/API surface for session claims and merge queue
- `nomic/dev_coordination.py`: richer semantics that fleet does not yet model directly
- `event_bus` + receipts: audit and cross-process signaling

This keeps the visible operational state where users already look while avoiding another fully separate control plane.

## Core Artifacts

### WorkLease

`WorkLease` is the bounded ownership object for a single development lane.

Required fields:

- `task_id`
- `owner_agent`
- `owner_session_id`
- `branch`
- `worktree_path`
- `allowed_globs`
- `claimed_paths`
- `expected_tests`
- `expires_at`

Operationally:

- the lease is created by `scripts/codex_session.sh`
- overlap checks consult both active leases and existing `fleet` claims
- lease claims are mirrored into `FleetCoordinationStore`

### CompletionReceipt

`CompletionReceipt` captures what a worker actually produced:

- commits
- changed paths
- tests run
- assumptions
- blockers
- confidence

This is the development analogue of Aragora’s decision and cycle receipts. It turns “agent says it finished” into a typed artifact.

### IntegrationDecision

`IntegrationDecision` is the integrator verdict over a completion receipt:

- `pending_review`
- `merge`
- `cherry_pick`
- `request_changes`
- `discard`
- `salvage`

`pending_review` is projected into integration work immediately after completion. That gives the swarm an explicit integrator lane instead of implicit branch drift.

### SalvageCandidate

`SalvageCandidate` is the missing recovery primitive for:

- stale dirty worktrees
- worktrees ahead of `main`
- stashes with potentially useful changes

This is how cleanup stops destroying value.

## How This Builds On Existing Aragora Orchestration

The development coordination model is intentionally parallel to Aragora’s product orchestration.

### Development Swarm

- planner assigns a bounded task
- worker edits only leased scope
- worker emits completion receipt
- integrator decides merge/cherry-pick/discard
- stale work enters salvage queue

### Product Backbone

- planner/interrogator emits `SpecBundle`
- workers execute bounded plan fragments
- verification produces typed outcome
- receipt gate decides whether execution is trusted
- failures and leftovers feed outcome feedback / nomic loop

## Direct Mapping To Existing Product Primitives

| Dev coordination | Existing Aragora primitive |
| --- | --- |
| `WorkLease` | `SpecBundle` / decision-plan scope |
| `CompletionReceipt` | pipeline receipt / cycle receipt |
| `IntegrationDecision` | policy + decision integrity gate |
| `SalvageCandidate` | outcome feedback / recovery queue |
| active lease conflict detection | execution safety / quality gate |
| fleet merge queue | branch coordinator / reconciler lane |
| event publication | `EventBus` |
| pending work projection | `GlobalWorkQueue` |

## Existing Product Orchestration Patterns Worth Building On

The repo already has mature orchestration patterns that should be reused instead of reimplemented:

- `aragora/pipeline/unified_orchestrator.py`
  - canonical end-to-end flow for research, debate, planning, execution, bug-fix, and feedback
- `aragora/nomic/autonomous_orchestrator.py`
  - queue-driven self-improvement loop
- `aragora/nomic/hierarchical_coordinator.py`
  - manager/worker topology for decomposition
- `aragora/nomic/parallel_orchestrator.py`
  - fan-out/fan-in execution pattern
- `aragora/debate/orchestrator.py` and `aragora/debate/consensus.py`
  - heterogeneous deliberation and synthesis
- `aragora/debate/quality_pipeline.py`
  - explicit quality gates before progression
- `aragora/debate/execution_safety.py`
  - fail-closed execution constraints
- `aragora/pipeline/idea_to_execution.py`
  - intake-to-plan-to-execution flow
- `aragora/nomic/outcome_feedback.py`
  - outcome capture for reprioritization and self-improvement

The correct next architectural move is to wire the development swarm protocol into these patterns, not to create a second orchestration philosophy.

## Best-Order Rollout

1. Keep `fleet` as the canonical visible session/claim/merge surface.
2. Add lease TTL and heartbeat semantics through `dev_coordination`.
3. Mirror lease claims into fleet so humans and APIs see the same ownership picture.
4. Project completion into both:
   - receipt/audit trail
   - fleet merge queue
5. Produce salvage candidates before cleanup paths delete stale work.
6. Reuse `BranchCoordinator` and `GitReconciler` for actual integration workers.
7. Fold the same typed-artifact pattern into the product-side orchestration backbone.

## Immediate Practical Guidance

For concurrent Codex/Claude operation:

- only one agent owns a file scope at a time unless overlap is explicitly allowed
- every session should start with a lease
- every completed session should emit a completion receipt
- only the integrator lane should finalize merge decisions
- stale worktrees and stashes should be scanned into salvage before cleanup

That is the minimum protocol needed to scale concurrent agents without spending the gains on reconciliation friction.
