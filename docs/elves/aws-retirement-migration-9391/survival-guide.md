# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

## Mission

Deliver a provider-neutral, externally verifiable production canary for issue #9391 without
attempting AWS recovery. Keep provider choice in deployment configuration and secret adapters;
leave AWS workflow/governance retirement for a separate exact-scope Tier-4 PR after canary proof.

## Run Control

- **Run mode:** finite
- **Stop policy:** blocker-only after launch; mandatory staging boundary before launch
- **User intent:** "yes to all in best order proceed"
- **Checkpoint due by:** none
- **Checkpoint semantics:** staging completion is a mandatory launch boundary
- **May continue after checkpoint:** only from a fresh launch call
- **Actual stop conditions:** all six batches complete, explicit user stop, or a genuine blocker
  with no safe workaround; missing live credentials blocks only Batch 5.
- **Workspace ownership:** dedicated worktree at
  `$HOME/.codex/worktrees/aws-retirement-migration-9391-20260819/aragora`
- **Branch tip at start:** `6955ab420ed959dcce9cece4120b298453adc9c3`
- **Branch:** `codex/aws-retirement-migration-9391`
- **Lease:** `803c32bd-760`, owner `codex-elves-aws-retirement-9391-20260819`
- **Merge policy:** user-merges; no settlement or merge authority
- **Final-response policy:** allowed for staging; after launch, disallowed until stop gate permits
- **Time allocation:** implement 33%, validate 34%, review 33%
- **Batch completion rule:** update log and guide, commit, push, poll PR, and continue; no batch is
  complete while its finished work exists only locally.
- **Re-read rule:** immediately after every commit and push, re-read this survival guide before
  doing anything else.
- **Checkpoint rule:** staging is the only checkpoint that is a stop; launched checkpoints are
  delivery targets and do not permit stopping.
- **Continuation rule:** after launch, if work remains and no genuine blocker applies, continue
  without waiting for acknowledgment.

## Session Budget

- **Started:** 2026-08-19 09:10 America/Chicago
- **User returns:** unspecified
- **Time budget:** finite, no hard deadline
- **Batches remaining:** 6 of 6

## Stop Gate

- **Planned batches remaining:** 6
- **Stop allowed right now:** no
- **Why:** the operator launched the finite run; Batches 1-6 remain and only a genuine blocker can
  halt the run. Missing live credentials blocks Batch 5 only.
- **Next required action:** write the Batch 1 contract and pre-implementation survey, then
  implement provider-neutral mounted-directory secret custody.

## Effort Standard

- Work as hard as you can for the full launched run. Do not be lazy.
- Carry every batch through implementation, validation, independent review, docs, commit, and push.
- Do not settle for the minimum acceptable change, a first green test, or a shallow review.
- After each batch, immediately take the next highest-value action named by the plan and Stop Gate.
- Split scope before quality degrades or the PR approaches the 800-line operating limit.

## Forbidden Stop Reasons

- A commit, push, PR, or green focused test exists while later batches remain.
- A delivery checkpoint was reached after launch.
- The live-deploy credentials are missing while implementation or dry-run work remains.
- The remaining work feels large or a batch boundary feels convenient.
- The user is silent after launch.

## Non-Negotiables

- No AWS login, MFA, billing, EC2/SSM diagnosis, restart, or redeploy.
- No workflow, protected-governance, branch-protection, evidence, settlement, or merge-helper edits.
- No provider-specific branches in application code and no Supabase-specific persistence path.
- No private keys or database credentials in environment examples, logs, commits, or evidence.
- Preserve both stale July 17 contingency worktrees and all shared-root dirt untouched.
- Do not create paid infrastructure without an existing authorized target or explicit budget.
- Never weaken, skip, or delete tests; never use destructive git or force-push commands.

## Launch Readiness

- [x] Plan saved
- [x] Survival guide initialized
- [x] Learnings initialized
- [x] Execution log initialized
- [x] Dedicated branch/worktree created
- [x] Lease claimed and no conflicting live owner found
- [x] Draft PR opened and recorded
- [x] Focused preflight completed; constraints recorded
- [x] Run mode and non-negotiables recorded
- [x] Stop Gate transitioned to `Stop allowed right now: no` on the fresh launch call.
- [x] Launch prompt prepared

## Current Phase

**Status:** Launched; Batch 1 contract and survey

**Active batch:** Batch 1: Provider-neutral secret custody

**What was just finished:** steering was empty, lease `803c32bd-760` was renewed, checked-out,
remote, and PR tips all matched `a9b5de83502426ff83415e64b9b27dc562161e1d`; main remained at
the staged base with no overlap, five runners were online, and all six required PR checks were
green. The non-required scheduled AWS uptime monitor remains red on the retired API endpoint.

**Single next action:** record the Batch 1 contract and pre-implementation survey, then implement.

## Active Compute

No active paid or long-running compute. The local Docker daemon is unavailable. No canary host,
Cloudflare tunnel, or paid deployment was created.

## Next Exact Batch

**Batch:** 1: Provider-neutral secret custody

**Scope:**

- Extend the existing `SecretManager`; do not create a parallel secrets subsystem.
- Add protected mounted-directory custody for critical production secrets.
- Preserve AWS compatibility and development environment behavior.
- Add focused precedence, permissions, refresh, presence, and strict-mode tests.

**Acceptance criteria:**

- [ ] Focused secrets tests pass.
- [ ] Targeted Ruff and mypy pass.
- [ ] No secret value appears in logs/errors.
- [ ] Existing AWS behavior is preserved.

**Risk:** `SecretManager` is a shared security surface; run regression-focused consumer review.

**Rollback tag:** `elves/aws-retirement-migration-9391/pre-batch-1` (the unqualified local tag was
already occupied by unrelated historical commit `17af7a7a590e3e04543e1f0f1b9df2faf039dc96` and was
preserved)

## Tool Configuration

```yaml
lint: .venv/bin/ruff check <changed-python-files>
typecheck: .venv/bin/mypy --follow-imports=skip <changed-python-files>
test: .venv/bin/pytest -q tests/config/test_secrets.py tests/gauntlet/test_odr_signing.py tests/scripts/test_verify_receipt.py
compose: docker compose -f <canary-compose> config --quiet
review: github-pr-comments plus independent non-countable review
notification: pr-comment
```

## Plan and Log Paths

- **Plan:** `docs/plans/aws-retirement-migration-9391.md`
- **Learnings:** `docs/elves/aws-retirement-migration-9391/learnings.md`
- **Execution log:** `docs/elves/aws-retirement-migration-9391/execution-log.md`
- **Branch:** `codex/aws-retirement-migration-9391`
- **PR:** #9800
- **Plan hash at staging:** `321c235e2f7a45d9ba779a4e342d2d83111773f07de059fb4d1d0b78fecb9a8e`

## Known Baseline

- Focused tests: 125 passed after installing CI-side-loaded `boto3` and `cryptography` in the
  worktree venv.
- Targeted Ruff: pass.
- Targeted mypy: pass for the three current source files.
- Existing self-hosted compose config: pass with one expected missing-password warning.
- Repository-wide Ruff: ambient failure in a trusted workflow launcher outside scope.
- Runner fleet: five online `aragora` runners.
- Credentials: Supabase CLI available; Hetzner and Cloudflare auth unavailable.

## Collision and prior-art note

The stale worktrees `.claude/worktrees/agent-aabb4bb8146b31a64` and
`.claude/worktrees/agent-ae0d7970371628a0d` contain July 17 uncommitted signing experiments. They
have no live process, lane, lease, or PR. Read-only inspection is allowed; never edit, commit,
clean, or delete them.

## Post-Checkpoint Control Loop

Every completed batch must end with a commit and push. Immediately after every commit and push,
re-read this survival guide before doing anything else. Verify the branch/remote tip, poll PR
comments and checks, update active compute, and start the single next action.
Does the Stop Gate still say `Stop allowed right now: no`? If yes, continue immediately.

## After Any Compaction

Read in this order: this guide, `.elves-session.json`, `learnings.md`, the plan, then the execution
log. Read the Run Control section and Stop Gate explicitly. Recheck steering, lease, live head,
active compute, and `.elves-session.json`'s `continuation_guard` before touching code. Do not repeat
completed batches or infer authority from memory.
