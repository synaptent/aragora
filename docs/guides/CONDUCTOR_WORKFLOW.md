# Aragora Conductor Workflow

Use this workflow when one human-facing Codex or Claude session is coordinating multiple bounded workers. The conductor is not a free-roaming implementer. The conductor restores shared state, assigns at most a small number of non-overlapping lanes, and stops as soon as the next decision point is reached.

This guide documents the operating model that matched the repository's recent recovery work:

- one canonical lane per issue
- one worker per active lane
- no worker merges
- no worker touches root
- no new lane until active lanes reach a PR-or-blocker stop condition

For the lower-level coordination primitives, see [Dev Swarm Coordination](../architecture/DEV_SWARM_COORDINATION.md). For spec-driven swarm runs, see [Supervised Swarm Dogfood Operator Guide](SWARM_DOGFOOD_OPERATOR.md).

## 1. Distinguish Root States Correctly

Do not treat every non-ideal root state as "contaminated." There are three different cases:

- `dirty`: uncommitted file changes exist in root
- `behind`: root is clean, but local `main` is older than `origin/main`
- `unsafe for implementation`: root may be clean, but active lanes or overlapping ownership make it a bad implementation base

The correct conductor behavior is:

- if root is `dirty`, stop and report; do not sync or code
- if root is clean and `behind`, fast-forward it to `origin/main`
- even when root is clean and current, do not use it as a worker lane; root is the conductor/integrator surface

## 2. Conductor Loop

Run this loop in the single conductor session before any coding:

1. fetch `origin` and inspect repo state
2. if root is dirty, stop and report
3. if root is clean and behind, fast-forward root `main` to `origin/main`
4. inspect open PRs
5. inspect worktrees
6. identify active lanes
7. choose at most two non-overlapping worker assignments
8. stop assigning once those lanes are in flight

The conductor should emit this summary each cycle:

1. current repo state
2. active lanes
3. canonical ownership
4. next worker assignments
5. stop condition for each worker

## 3. Minimum Conductor Commands

These are the minimum checks needed to keep state coherent:

```bash
git fetch origin --prune
git status -sb
git worktree list --porcelain
gh pr list --state open --limit 20 --json number,title,headRefName,baseRefName,url
```

Useful Aragora-native read surfaces:

```bash
aragora swarm status --json
aragora worktree fleet-status --json
aragora worktree fleet-claims --json
aragora worktree fleet-queue-list --json
aragora worktree autopilot status --json
```

Useful low-level recovery commands when sessions are churny:

```bash
./scripts/codex_session.sh
python3 scripts/codex_worktree_autopilot.py ensure --agent codex --base main --reconcile --print-path
python3 scripts/codex_worktree_autopilot.py maintain --base main --strategy merge --ttl-hours 24
python3 scripts/codex_worktree_autopilot.py reconcile --all --base main
python3 scripts/codex_worktree_autopilot.py cleanup --base main --ttl-hours 24
```

## 4. Decision Rule

Only do one of these per conductor cycle:

1. merge an already-green non-overlapping PR
2. assign one or two bounded worker lanes
3. clean stale state
4. stop because ownership is ambiguous

Do not try to merge, assign, clean, and start follow-up work in the same cycle. That is how stale assumptions compound.

## 5. Hot Coordination Files

Treat these paths as serialized coordination surfaces:

- `docs/status/**`
- `README.md`
- `ROADMAP.md`
- `.github/workflows/**`
- `scripts/reconcile_status_docs.py`
- `scripts/pre_release_check.py`

Only a dedicated docs/truthfulness lane or integrator lane should touch them. General implementation lanes should not edit them.

## 6. Worker Assignment Contract

A worker assignment must include all of the following:

- exactly one issue or one narrow follow-up
- explicit allowed paths
- explicit forbidden paths
- exact validation commands
- exact stop condition

The standard stop condition is:

- open one PR and stop, or
- report one blocker and stop

Workers do not merge, do not widen scope, and do not clean up other lanes.

## 7. Example Conductor Prompt

```text
You are the Aragora conductor/integrator.

Before any coding:
1. fetch origin and inspect repo state
2. if root is dirty, stop and report; do not sync or code
3. if root is clean and behind, fast-forward root main to origin/main
4. inspect open PRs
5. inspect worktrees
6. identify active lanes
7. choose at most 2 non-overlapping worker assignments
8. do not code until ownership is clear

Rules:
- one canonical lane per issue
- one worker per lane
- no worker merges
- no worker touches root
- no new lane until current lanes reach PR-or-blocker stop condition
- if repo state is ambiguous, resolve state first instead of starting work

Output each cycle:
1. current repo state
2. active lanes
3. canonical ownership
4. next worker assignments
5. stop condition for each worker
```

## 8. Why This Replaces "Yes To All In Best Order"

"Yes to all in best order" sounds efficient, but it delegates scheduling and exclusivity to workers that do not share state. The failure mode is predictable:

- duplicate lanes for the same issue
- workers coding on stale branch assumptions
- worktrees cleaned up while still useful
- docs/status hot files edited by unrelated lanes
- PR churn without canonical ownership

The conductor loop fixes that by restoring one shared truth before allowing more work to start.

## 9. Current Best Next Engineering Sequence

After the merged worktree protection and integrator-view slices, the next control-plane work should usually proceed in this order:

1. file-scope ownership enforcement
2. canonical PR / supersession protocol
3. receipt and provenance requirements for every lane
4. prompt rendering from leases and worker roles
5. a first-class `aragora swarm conduct` operator command

That order matches the existing codebase shape more cleanly than jumping straight to many-agent autonomy.
