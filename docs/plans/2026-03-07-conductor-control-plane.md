# 2026-03-07 Conductor Control Plane Implementation Spec

## Summary

Aragora already has most of the substrate for multi-agent development:

- supervisor-backed swarm runs
- worker launches in isolated worktrees
- worktree autopilot and cleanup
- lease-like coordination state
- completion receipts and integration decisions
- an initial integrator-facing status view

What is still missing is the hierarchy that lets one human-facing session act as a conductor instead of manually copy-pasting instructions across multiple worker sessions.

The goal of this plan is to make Aragora itself manage the pattern that was manually used to recover the repository:

- one conductor/integrator session
- one implementer/planner layer that turns goals into bounded lanes
- multiple workers launched from leases
- one merge authority

## Current Shipped Base

As of `cd2985adf` on `main`, the control-plane baseline already includes:

- worktree/session protection and cleanup hardening
  - `scripts/codex_worktree_autopilot.py`
  - `aragora/worktree/autopilot.py`
- integrator-facing status summary surfaces
  - `aragora/swarm/reporter.py`
  - `aragora/cli/commands/swarm.py`
  - `aragora/cli/commands/worktree.py`
  - `aragora/server/handlers/control_plane/coordination.py`
- supervisor-backed swarm execution
  - `aragora/swarm/supervisor.py`
  - `aragora/swarm/reconciler.py`
  - `aragora/swarm/worker_launcher.py`
- richer coordination semantics
  - `aragora/nomic/dev_coordination.py`
- merge/integration worker
  - `aragora/worktree/integration_worker.py`

This means the next tranche should extend the current codebase, not create a second orchestration system.

## Problem To Solve

The manual operator pattern still lives outside Aragora:

- the user inspects repo state manually
- the user designates canonical lanes manually
- the user copies bounded prompts to worker sessions manually
- the user decides when workers must stop manually
- the user tracks receipts and merge readiness manually

That is workable for a few agents, but not for 10 or 20.

## Target Operating Model

### Roles

1. `Conductor`
- single human-facing Codex or Claude session
- restores shared state
- chooses at most a small number of bounded next actions
- never free-roams as a worker by default

2. `Implementer`
- translates one approved issue or goal into bounded work orders
- owns file-scope definition, tests, and stop conditions

3. `Worker`
- edits only leased scope
- emits a completion receipt
- cannot merge

4. `Integrator`
- the only role allowed to merge, supersede, or discard lanes

### Conductor Cycle

The conductor cycle should become a first-class command:

1. inspect repo state
2. sync clean root to `origin/main`
3. inspect open PRs and worktrees
4. canonicalize ownership
5. choose at most two non-overlapping worker assignments
6. stop assigning until those lanes hit PR-or-blocker stop conditions

## Proposed Deliverables

### 1. Prompt Rendering From Leases

Add role-aware prompt rendering to the coordination layer.

Input:
- `WorkLease`
- `allowed_globs`
- `expected_tests`
- role (`worker`, `reviewer`, `integrator`)
- stop condition

Output:
- bounded worker prompt
- reviewer prompt
- integrator prompt

Likely insertion points:
- `aragora/nomic/dev_coordination.py`
- `aragora/swarm/supervisor.py`
- `aragora/swarm/spec.py`

### 2. First-Class Conductor Command

Add a top-level operator command, conceptually:

```bash
aragora swarm conduct
```

Minimum responsibilities:
- inspect root cleanliness / behind state
- inspect open PRs
- inspect worktrees and leases
- render canonical lane view
- suggest the one next conductor action

Likely insertion points:
- `aragora/cli/commands/swarm.py`
- `aragora/swarm/reporter.py`
- `aragora/server/handlers/control_plane/coordination.py`

### 3. Lane Canonicalization and Supersession

Add explicit support for:
- one canonical lane per issue
- duplicate-lane detection
- superseded lane status
- stop-new-lane-on-active-owner behavior

This should reuse existing coordination artifacts rather than redesign storage in the first tranche.

Likely insertion points:
- `aragora/nomic/dev_coordination.py`
- `aragora/worktree/fleet.py`
- `aragora/swarm/reporter.py`

### 4. Stop-Condition Enforcement

Every launched worker lane should be required to terminate at:
- one PR, or
- one blocker report

Not an open-ended continuation loop.

Likely insertion points:
- `aragora/swarm/worker_launcher.py`
- `aragora/swarm/reconciler.py`
- `aragora/nomic/dev_coordination.py`

## Scope Boundaries

This tranche should not attempt:

- a full visual mission-control UI
- 10+ agent autonomous scaling
- deep schema redesign of coordination storage
- broad model-routing redesign
- a second orchestration stack parallel to the current supervisor/fleet model

Those can come later. The goal here is to remove manual copy-paste and ambiguous ownership first.

## Suggested Issue Order

The next control-plane sequence should be:

1. file-scope ownership enforcement
2. canonical PR / supersession protocol
3. receipts and provenance requirements for every lane
4. prompt rendering from leases
5. first-class conductor command

That order assumes the worktree protection and integrator-view slices are already landed.

## Acceptance Criteria

This plan is successful when all of the following are true:

1. A conductor session can inspect repo state and receive a canonical lane summary without manual shell archaeology.
2. A worker prompt can be generated directly from lease data.
3. An issue with an active owner cannot silently spawn another competing lane.
4. Every worker lane ends at one PR or one blocker.
5. The integrator view can show canonical lane, receipt presence, stale heartbeat status, and merge readiness in one place.

## Suggested First PR Scope

The most reasonable first implementation PR after the already-merged protection/view work is:

- add role-aware prompt rendering from `WorkLease`
- expose rendered prompts through CLI / API read surfaces
- no automatic worker launch changes in that first PR

That is small enough to validate the operating model without touching every coordination path at once.
