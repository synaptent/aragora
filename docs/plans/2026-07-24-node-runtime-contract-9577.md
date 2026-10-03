# Node 24 Runtime Contract for `aragora/live` (#9577)

## Mission

Make the supported Node runtime for `aragora/live` explicit and mechanically
consistent across the workflows that install or execute the live frontend.
The contract is Node `24.18.x` at execution time and Node 24 for package
consumers. Prove the contract with a focused repository test and a real
frontend build under the declared runtime.

This is an isolated Tier 4 workflow lane reconciled with an operator-authorized
current-main commit. It does not modify or re-review PR #9505. The original
draft-readiness stop was later superseded by exact OWNER authorization recorded
below.

## Authorization and boundaries

The operator explicitly approved this separate follow-up lane and the required
workflow edits on 2026-07-24. That approval does not authorize branch
protection changes, evidence collection, settlement, ready-for-review, or
merge.

On 2026-07-25, the operator explicitly authorized merging current main
`1cd722cc2df2330466af2511f6f3b6b83d496b83` into PR #9591, preserving PR
#9589's dependency and lockfile changes, reconciling the Batch 1 baseline and
contract against that state, and resuming the Node 24 implementation. This is
a branch reconciliation only; it does not authorize merging PR #9591.

On 2026-07-27, the operator explicitly authorized merging current main
`566db09f7f1628915030073d7e1e93992dcf1411` into PR #9591 while preserving
the already-merged work from PRs #9505 and #9621. After successful validation
and independent review, the same authorization permits OWNER ready-for-review,
exact-head quorum collection, Tier 4 human-risk settlement, and merge through
the repository-supported gates. It does not authorize bypassing a failed gate
or modifying either preserved change.

In scope:

- `aragora/live/package.json`
- the root package record in `aragora/live/package-lock.json`
- only the Node selector(s) used by `aragora/live` consumers in these 13
  workflows:
  - `.github/workflows/deploy-frontend.yml`
  - `.github/workflows/deploy-secure.yml`
  - `.github/workflows/e2e.yml`
  - `.github/workflows/integration-gate.yml`
  - `.github/workflows/lighthouse.yml`
  - `.github/workflows/lint.yml`
  - `.github/workflows/live-deploy-mode-gate.yml`
  - `.github/workflows/merge-group-frontend-typecheck.yml`
  - `.github/workflows/nightly-full-matrix.yml`
  - `.github/workflows/onramp-integration.yml`
  - `.github/workflows/production-monitor.yml`
  - `.github/workflows/release.yml`
  - `.github/workflows/test.yml`
- `tests/ci/test_live_node_runtime_workflows.py`
- this plan and temporary Elves recovery artifacts

Out of scope:

- product changes belonging to PR #9505 or PR #9621
- workflow Node selectors used only by the TypeScript SDK, CLI, or another
  package
- dependency, Next.js, Dockerfile, Docker Compose, branch-protection, runner,
  secret, environment, or deployment-setting changes
- another Fable or inference consult

## Live-state tripwires

The staging base is `c7c4681eb08d5e7c7966d10dfba3a1520d671319`.
Before Batch 1 product edits:

1. Re-read global and lane steering.
2. Renew lease `00ea44f4-78d` as session
   `elves-node-runtime-contract-9577-20260724`.
3. Fetch `origin/main` and compare it with the staging base.
4. If main advanced, inspect overlap against every in-scope product path.
   Because the branch is published, reconcile only with a merge and record the
   new base; never rebase it. The exact reconciliations at `1cd722cc...` and
   `566db09f...` are separately authorized above. Later current-main commits
   must be inspected for overlap; disjoint advancement may be left for the
   repository mergeability gate, while any unapproved in-scope overlap remains
   a hard stop.
5. Verify the draft PR exact head before editing.
6. Verify at least three healthy runners with the `aragora` label.
7. Verify no protected required context on current main has been terminal red
   for more than 30 minutes.

Stop and ask the operator if there is current-main overlap, foreign
ownership/lease, steering that narrows this scope, runner capacity below
three, or a sustained required-check incident.

## Runtime contract

- Add `"engines": { "node": ">=24.18.0 <25" }` to
  `aragora/live/package.json`.
- Mirror that field only in the lockfile root package record.
- Use exact `24.18.0` in the 13 GitHub Actions workflow selectors that execute
  `aragora/live`.
- Do not blindly replace every Node 20 selector in a workflow. Preserve
  unrelated package jobs, especially SDK-only jobs.
- Make a Node 24 frontend build an observable affected-path gate. Prefer the
  existing live workflow job that already performs `npm ci`, type checking,
  and `npm run build`; change structure only if the existing trigger or path
  logic cannot prove the affected live paths.

## Batch 1 — implement and prove the contract

1. Inventory every `actions/setup-node` consumer in the 13 workflows and map
   each selector to the package it executes.
2. Add the package and lockfile-root engine contract without regenerating or
   changing dependency records.
3. Change only live-frontend selectors to exact `24.18.0`.
4. Add a focused static contract test that:
   - checks the package and lockfile root engine fields agree;
   - checks the 13 expected workflow files remain in the contract set;
   - proves every job that operates in `aragora/live` resolves to Node
     `24.18.0`;
   - allows unrelated SDK/CLI Node selectors to remain independently managed;
   - proves at least one affected-path workflow performs `npm ci` and a real
     frontend build under that selector.
5. Run focused tests and inspect the diff for accidental workflow or lockfile
   churn.
6. Commit and push Batch 1 only after lease verification and
   `bash scripts/automation_pr_preflight.sh origin/main HEAD`.

Batch 1 acceptance:

- only the approved product files and the focused contract test changed;
- no dependency record or transitive package changed;
- all 21 live consumers across the 13 approved workflows resolve to exact
  Node `24.18.0`;
- package and lockfile root declare `>=24.18.0 <25`;
- focused tests pass;
- `git diff --check` and automation preflight pass.

## Batch 2 — validation, independent review, and final readiness

1. Re-read steering, renew the lease, recheck exact head and main overlap.
2. Run the focused Python workflow-contract test.
3. Under exact Node `24.18.0`, run in `aragora/live`:
   - `npm ci`
   - `npm run lint`
   - `npx tsc --noEmit`
   - `npm run build`
4. Run repository workflow policy checks relevant to every changed workflow,
   including checkout-integrity and required-check priority policy where
   applicable.
5. Run `bash scripts/automation_pr_preflight.sh origin/main HEAD`.
6. Obtain an independent, non-countable review of the exact diff. Do not run
   quorum collection or another inference/Fable consult.
7. Poll draft-PR checks and comments, repair only grounded in-scope blockers,
   and repeat validation after any repair.
8. Remove temporary operational artifacts (`.elves-session.json`,
   survival guide, execution log, and session-only learnings) from the product
   diff. Retain this plan as the durable implementation record.
9. Push the final exact head, update the PR body with commands and results, and
   stop for OWNER settlement/merge handling.

Batch 2 acceptance:

- actual Node `24.18.0` install, lint, typecheck, and frontend build pass;
- focused and repository workflow policy checks pass;
- independent review has no unresolved blocking finding;
- required non-quorum checks are green or a precise ambient blocker is
  recorded;
- the final PR contains no session-only operational artifacts;
- no ready flip, evidence collection, settlement, or merge occurred.

## OWNER reconciliation and settlement extension

The 2026-07-27 authorization adds a gated OWNER phase after the original Elves
Batch 2:

1. Merge exact current-main commit `566db09f7f1628915030073d7e1e93992dcf1411`
   without rebasing or force-pushing.
2. Prove that `aragora/live/package.json` without its root `engines` field and
   `aragora/live/package-lock.json` without its root `engines` field are
   byte-for-byte equivalent to that main state. This protects #9621's React
   `19.2.8` dependency baseline and all 1,034 non-root lock records.
3. Re-run the complete Batch 2 validation and obtain a fresh independent,
   non-countable review of the reconciled diff.
4. Push only after a fresh lease, steering, remote-head, main-overlap, and
   preflight check.
5. Complete OWNER review, remove the operator hold, mark the exact head ready,
   and collect countable quorum evidence without changing the diff.
6. If and only if the exact head, required non-quorum checks, supportive quorum,
   mergeability, and Tier 4 human authorization all remain valid, use the
   repository settlement helper to settle and merge.

## Implementation record

Batch 1 added `>=24.18.0 <25` to the live package and lockfile root, changed
the 21 live-serving selectors across the approved workflows to exact
`24.18.0`, and preserved the three named Node 20 SDK/version exceptions.
The focused test owns all 24 selectors across the exact 13-file inventory and
the existing affected-path build-gate shape.

Validation on the 2026-07-27 OWNER reconciliation passed:

- `python3 -m pytest -q tests/ci`: `201 passed, 1 skipped`;
- focused Ruff check and format check: PASS;
- checkout-integrity and required-check-priority policies: PASS;
- `git diff --check` and automation PR preflight: PASS;
- exact `node:24.18-alpine` `npm ci`, lint, `tsc --noEmit`, and production
  build: PASS, with all 228 routes generated;
- pushed-head non-quorum required checks: pending the reconciled push;
- fresh independent non-countable review: no blockers, high confidence.

Relative to authorized main `566db09f...`, the package file without the new
root `engines` field and the lockfile without the matching root `engines` field
are identical. This preserves #9621's React and React DOM `^19.2.8` declarations
and all 1,034 non-root lock records, while the main merge also carries #9505's
already-settled state. The live deploy-mode build job is skipped while #9591
remains a draft, so the exact container run is the actual Node 24 build proof.

## Stop conditions

Stop immediately and report the exact approval question if:

- a change outside the allowed paths is required;
- any dependency or transitive package record changes;
- a Node selector cannot be attributed safely to `aragora/live`;
- current main has new, unapproved overlap with an in-scope product file;
- the exact PR head changes externally;
- another owner or lease claims the branch, PR, or any in-scope file;
- a required check is terminal red on current main for more than 30 minutes;
- the implementation would require branch protection, runner, secret,
  environment, deployment-setting, Dockerfile, Docker Compose, Next.js, or
  dependency changes;
- an independent reviewer reports a blocking issue that cannot be fixed inside
  this scope.

## Delivery

Run mode is finite and has no operator hard stop. The original Elves lane ended
at draft readiness. The separately authorized OWNER lane may reconcile, push,
mark ready, collect countable exact-head evidence, settle, and merge, but only
in that order and only while every repository gate remains valid.
