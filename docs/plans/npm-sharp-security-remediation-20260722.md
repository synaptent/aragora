# Plan: Remediate the inherited sharp security advisory

## Mission

Create one isolated, current-main pull request that removes the `sharp <0.35.0`
exposure reported by `npm audit` in `aragora/live`, while preserving the existing
Next.js application behavior. A later operator-approved scope expansion updates
Next.js from 16.2.9 to the security-fixed 16.2.11 patch after the live production
audit began reporting new high-severity Next.js advisories. Done means the exact
production audit gate is clean,
the frontend builds and tests successfully with the selected sharp release, the
dependency delta is fully classified, and the draft PR is independently reviewed
and ready for operator review.

The branch was created from `origin/main` at
`24ecf7e79ab7486e91712a4ca33e10aff1973ea7` and then normally merged the newer
current main at `563331f03e568e5b34c481bde86a5c1f89575c9e` during staging. This is a
separate security lane; PR #9477 is context only and is outside this run's authority.

## Scope

### In Scope

- Falsify or confirm GHSA-f88m-g3jw-g9cj against the exact current-main lockfile.
- Add one `sharp` entry to the existing `aragora/live/package.json` `overrides`
  object if the advisory and a compatible patched release are both confirmed.
- Regenerate only `aragora/live/package-lock.json`, then classify every changed
  package entry by dependency family.
- Replace all three `node:18.19-alpine` stages in `aragora/live/Dockerfile` with
  the repository-standard `node:20.11-alpine`; this exact scope expansion was
  operator-approved after independent review found the existing engine mismatch.
- Update the direct Next.js dependency from 16.2.9 to the security-fixed 16.2.11
  patch and regenerate its exact lockfile closure; this second scope expansion was
  operator-approved after the live production audit reported new high-severity
  advisories affecting releases through 16.2.10.
- Run the exact npm audit gate plus focused frontend lint, tests, and production build.
- Perform an independent, non-countable review and leave a draft PR ready for the
  operator. Security changes remain operator-review-required.

### Out of Scope

- Any edit, comment, evidence collection, settlement, readiness transition, or
  merge action on PR #9477.
- Merge-quorum evidence, human settlement, branch-protection changes, or merging
  this dependency PR.
- Changes to `.github/**`, CI/security workflows, protected governance files, SDK
  dependencies, or direct dependencies outside the sharp family and the exact
  operator-approved Next.js 16.2.11 security patch. The generated Next.js lock
  closure, `@emnapi/runtime`, and sharp's nested `semver` are the only approved
  out-of-family transitive exceptions.
- Production deployment, runtime inference requests, or later #9409 work units.

## Batches

### Batch 1: Prove and remediate the sharp advisory

**Tasks:**

- [x] Re-read the survival guide and live operator steering, renew the branch lease,
  verify the branch still starts from the recorded exact base, and create
  `elves/pre-batch-1` before product edits.
- [x] Reproduce the baseline with `npm ci --ignore-scripts` followed by
  `npm audit --omit=dev --audit-level=high --json`; stop as `UNFOUNDED` if the
  advisory is absent or below high severity.
- [x] Confirm the selected patched sharp release from the npm registry and upstream
  advisory. Prefer the upstream-recommended current patched line and document its
  Node engine and breaking-change risk.
- [x] Add only a sharp override to the existing overrides block and regenerate the
  lockfile with lifecycle scripts disabled.
- [x] Parse the lockfile diff into distinct changed package entries. If more than
  five transitive packages change, or any changed package is outside the
  `sharp` / `@img/sharp*` family, revert the product-file changes and stop for
  explicit operator approval before any implementation commit or push.
- [x] After the measured ceiling and family gates are either satisfied or the exact
  exception set receives operator authority, run the complete validation strategy,
  inspect the cumulative diff, commit, push, and poll all draft-PR checks and comments.
- [x] Perform a fresh final readiness review of the exact head without collecting
  countable quorum evidence. Fix blockers and repeat validation before handoff.

**Acceptance criteria:**

- [x] Baseline evidence names `sharp@0.34.5` as an indirect high-severity finding
  through `next@16.2.9` for GHSA-f88m-g3jw-g9cj.
- [x] `npm audit --omit=dev --audit-level=high` exits 0 after the change.
- [x] `npm ls next sharp --all` reports `next@16.2.11` and the intended
  `sharp@0.35.3` override with no invalid dependency state.
- [x] Every changed lockfile package is listed; there are no unexplained or
  unapproved out-of-family changes, and the operating-contract dependency ceiling
  was enforced before the exact exception set received operator approval.
- [x] `npm run lint`, `npm test -- --runInBand`, and `npm run build` pass in
  `aragora/live`; `git diff --check` passes from the repo root.
- [x] The cumulative product diff is limited to `aragora/live/package.json`,
  `aragora/live/package-lock.json`, the three approved base-image substitutions
  in `aragora/live/Dockerfile`, and the durable plan/learnings corrections that
  record both operator-approved scope expansions.
- [x] Independent review finds no unresolved blocker, PR checks are understood, and
  the PR remains unmerged for operator review.

**Docs likely touched:** this plan and the companion durable learnings document,
which record the measured dependency delta and operator-approved scope expansions.

**Risk:** sharp 0.35.x is outside Next 16.2.11's declared `^0.34.5` optional range,
upstream labels 0.35.0 as breaking, and the platform-binary family may exceed the
operating contract's five-transitive-dependency auto-halt ceiling.

## Non-Negotiables

- Do not touch PR #9477 or perform evidence, settlement, readiness, or merge actions.
- Do not edit workflows, protected files, SDK packages, or direct dependencies outside
  sharp and the exact operator-approved Next.js 16.2.11 security patch. The generated
  Next.js lock closure, `@emnapi/runtime`, and sharp-nested `semver` shifts are the only
  approved out-of-family transitive exceptions.
- Stop before committing or pushing product changes if more than five distinct
  transitive packages change or any changed package is outside the sharp family,
  unless the operator explicitly approves that exact measured delta.
- Never merge. This security PR requires operator review even after green validation.
- Every completed batch ends with updated run state, a commit, a push, a survival-guide
  re-read, and a fresh check of PR comments and checks.

## Test Strategy

- **Baseline:** `npm ci --ignore-scripts`; then
  `npm audit --omit=dev --audit-level=high --json`.
- **Dependency proof:** `npm ls next sharp --all` plus a parsed before/after
  `package-lock.json` package-key comparison.
- **Primary gates:** `npm run lint`, `npm test -- --runInBand`, and `npm run build`
  from `aragora/live`.
- **Repository gate:** `git diff --check` and a cumulative path/stat review against
  the recorded exact base.
- **Review gate:** fresh exact-head review of implementation, upstream compatibility,
  every PR comment, and every reported check; no countable evidence collection.
- **Durable docs:** update learnings only for a stable, reusable dependency or
  validation fact discovered during execution.

## Notes

- Current-main preflight on 2026-07-22 reproduced the finding: the exact audit command
  exited 1 and reported indirect `sharp@0.34.5`, high severity, affected range
  `<0.35.0`, through `next@16.2.9`.
- Main advanced during staging when PR #9477 merged independently. This lane performed
  no #9477 evidence, settlement, readiness, or merge action; it normally integrated the
  new base, confirmed `aragora/live/package*.json` were unchanged, and reproduced the
  same audit finding again at the newer current-main base.
- GitHub's reviewed advisory lists 0.35.0 as the first patched version and recommends
  the current 0.35.3 release. The upstream 0.35.0 release notes include breaking
  changes and require Node >=20.9.0.
- Stable `next@16.2.11` still declares `sharp: ^0.34.5`, while
  `next@16.3.0-canary.93` declares `sharp: ^0.35.3`. The operator approved the stable
  16.2.11 security patch after new advisories affected 16.2.9; this does not authorize
  adopting a canary or another Next.js release.
- The current lockfile contains 26 sharp-family entries. The actual changed-entry
  count must be measured after regeneration; do not pre-approve it by assumption.
- Independent review found that `aragora/live/Dockerfile` pinned Node 18.19 even
  though Next 16.2.11 and selected sharp 0.35.3 both require Node >=20.9.
  The operator approved aligning its three stages with `deploy/Dockerfile.frontend`
  and the repository's Node 20 CI standard.
