# Plan: Exact-Head Snapshot Provenance Follow-Up for #9677

## Mission

Fix the three merge-authority paths discovered by the terminal review of PR #9677 without
modifying that PR. Each path must carry the exact full head SHA that produced its eligibility,
settlement, or approval decision through to `--match-head-commit`; missing, malformed, changed, or
unavailable heads must fail closed before a merge subprocess can execute.

This is a fresh-main Tier-4 follow-up. It stops at a validated draft PR ready for exact-head OWNER
settlement. Only after this follow-up is separately settled and merged may a successor lane
reconcile current main into #9677, regenerate derived docs, validate, and run a terminal review.

## Starting State

- Fresh base: `origin/main` at `953c501c2147026c2c996c3f95001580e326ec52`.
- Branch: `codex/merge-snapshot-provenance-9677`.
- Dedicated worktree: `$HOME/.codex/worktrees/merge-snapshot-provenance-9677-20260829/aragora`.
- Lease: `906d51fa-4af`, session `codex-merge-snapshot-provenance-9677-20260829`.
- Baseline: 75 focused tests passed across Codex automation merge, boss drain, and merge arbiter.
- PR #9677 moved during staging to `13fc8850700927e2e4bd4809f77ddf44f282382e` in another worktree; this run must not touch it.

## Scope

### In Scope

- `scripts/merge_codex_automation_prs.py` and its focused tests.
- `scripts/boss_drain_pass.py` and focused coverage in `tests/swarm/test_boss_drain.py`.
- `aragora/swarm/merge_arbiter.py` and its focused tests.
- `aragora/swarm/initiative_integrator.py` and its focused tests, solely because it directly
  imports the merge-arbiter merge seam and must pass its existing PR snapshot head.
- Generator-owned metrics/docs mirrors if required by repository drift gates.
- This plan and temporary Elves run artifacts during execution.

### Out of Scope

- Any edit, commit, push, settlement, evidence collection, or merge on PR #9677.
- `aragora/governance/merge_halt.py` or the #9677 halt-guard implementation.
- Workflows, runner labels, protected governance documents, branch protection, or required-check configuration.
- Quorum evidence, OWNER settlement, ready-for-review transition, or merge of the new PR.
- New merge subsystems, broad refactors, public API changes, dependencies, and unrelated findings.

## Batch 1: Carry Exact Decision Heads Through All Three Merge Paths

### Contract

**Behaviors**

- The Codex automation merger captures `headRefOid`, files, checks, body, and mergeability in its
  eligibility snapshot, carries the validated SHA into `MergeDecision`, and passes that SHA to the
  merge command without a later lookup.
- Boss drain returns the full exact head from `settle_one_pr.py` authorization and uses that same
  value for the merge command without a second PR-head lookup.
- Merge arbiter rejects an absent or malformed head for review matching and merging, and every
  admin merge is pinned to the exact head evaluated by the arbiter.
- The initiative integrator's direct merge-arbiter call carries `headRefOid` from the same
  integrator snapshot and blocks promotion when that SHA is absent or malformed.
- Every path blocks before its merge subprocess when the trusted head is missing or malformed.
- A head change after decision time is rejected by GitHub's `--match-head-commit`, never converted
  into an unpinned or newly authorized merge.

**Build on**

- Existing immutable `PullRequestSnapshot` / `MergeDecision` flow in
  `scripts/merge_codex_automation_prs.py`.
- Existing `settle_one_pr.py` report field `head_sha` and the boss drain apply-time authorization
  check; carry its output instead of replacing it with another lookup.
- Existing merge-arbiter `headRefOid` flow, exact-head human review/receipt checks, and current
  `--match-head-commit` support.
- Existing focused test modules and subprocess mocks; add category tests without weakening or
  deleting existing coverage.

**Acceptance criteria**

- [x] Codex automation eligibility data and exact head come from one `gh pr view` snapshot.
- [x] Codex automation merge consumes the decision head; no live-head lookup occurs between
      selection and merge.
- [x] Boss drain consumes `head_sha` from the authorized settlement report and never performs a
      second `view_pr` to choose its merge head.
- [x] Merge arbiter rejects missing/malformed heads before approval matching and before `_run_gh`
      merge execution.
- [x] Every direct consumer of the modified merge-arbiter seam passes its validated snapshot head.
- [x] All three merge commands always contain `--match-head-commit <same-full-sha>`.
- [x] Tests cover missing/malformed heads, snapshot-to-merge head changes, exact match, and
      preservation of ordinary eligible/authorized behavior.
- [x] Focused tests, Ruff, mypy, `git diff --check`, and relevant drift generators pass.
- [x] Mutation break checks demonstrate that removing head propagation or pinning fails the
      intended tests.

**Blast radius**

- Three merge-authority implementation files, one direct shared consumer, and four focused test
  files; signatures are internal but the behavior is Tier 4 because they can trigger admin merges.
- Risk: high. A false positive can stop automation; a false negative can merge an unreviewed head.
  Prefer explicit full-SHA validation and fail-closed results over compatibility fallbacks.

### Tasks

- [x] Survey every caller/consumer of the modified dataclasses and merge helpers.
- [x] Implement exact-head propagation at the decision snapshot boundary in each path.
- [x] Add category-level regression tests and targeted mutation checks.
- [x] Run focused and cumulative touched-surface validation.
- [x] Run generator-owned drift updates only if required by the changed Python/test counts.

### Docs likely touched

- Generator-owned metrics/status mirrors if drift changes.
- `docs/elves/merge-snapshot-provenance-9677/learnings.md` only for reusable findings.

## Batch 2: Independent Review and Final Draft Readiness

### Contract

**Behaviors**

- A fresh independent reviewer audits the cumulative diff against the invariant:
  `decision head == approval/settlement head == --match-head-commit head`.
- All GitHub PR feedback and exact-head checks are read and triaged.
- Any real P0-P2 finding returns to Batch 1 for one bounded repair; repeated category findings stop
  the lane for OWNER direction rather than starting an unbounded loop.
- Operational Elves artifacts are removed before final draft readiness; this plan remains unless
  cleanup policy is explicitly changed.

**Build on**

- The repository's focused tests, pre-commit/pre-push hooks, automation preflight, and Tier-4
  reporting gates.
- Elves final cumulative review and regression-attestation format.

**Acceptance criteria**

- [x] Fresh cumulative independent review has no unresolved P0-P2 findings.
- [x] All focused tests, Ruff, mypy, hooks, drift checks, and `automation_pr_preflight.sh` pass on
      the exact pushed head.
- [x] PR body records exact head, scope, tests, mutation evidence, Tier-4 status, and residual risk.
- [x] No unresolved review threads or unreplied actionable bot comments remain.
- [x] Survival guide, execution log, and `.elves-session.json` are removed from the final diff;
      the plan is retained.
- [x] Draft PR is reported for exact-head OWNER settlement; no quorum evidence, settlement, ready
      transition, or merge occurs.

**Blast radius**

- No new product scope. This batch validates, reviews, documents, and cleans operational artifacts.
- Risk: medium. The main failure mode is incorrectly treating stale review/check evidence as
  exact-head proof.

## 2026-08-30 Exact-Head Settlement Cycle Extension

The OWNER separately authorized advancing #9874 in the safest order after final draft readiness.
A fresh Claude+OpenAI dry run on exact head `92d9a480735bf85a68e4a8a074f26b8fe6484545`
returned a clean Claude PASS and two OpenAI P2 findings: merge arbiter and initiative integrator
fetched required checks by PR number after taking their decision-head snapshots, without proving
the returned checks belonged to those heads. Settlement remained stopped; no evidence was posted
and the PR remained draft.

The bounded repair changes only the existing shared check-status seam and its two direct consumers:

- Fetch `headRefOid` and `statusCheckRollup` in one PR response.
- Reject a check snapshot whose head differs from the caller's decision head.
- Pass the decision head from merge arbiter and initiative integrator into that check snapshot.
- Block settlement/promotion/merge before any authority or merge call on mismatch.

**Acceptance criteria**

- [x] Both P2 paths fail closed on a changed check-snapshot head.
- [x] Mutation tests fail when the atomic head comparison or either caller's head propagation is removed.
- [x] Cumulative touched-surface tests pass: 151 passed, 0 skipped.
- [x] Scoped Ruff, mypy, drift checks, docs consistency, diff hygiene, and automation preflight pass.
- [ ] One fresh exact-head Claude+OpenAI dry run has no P0-P2 findings and two counted supportive families.
- [ ] Only after a clean current-head packet: mark ready, recheck live gates, post prepared evidence,
      record OWNER settlement, and merge through the Tier-4 helper.

### Terminal-review repair after `5ff8fdabdf2e6310a4ca978424e54a69bca6f8ce`

The next exact-head dry run remained evidence-free and found three distinct fail-open or
misleading outcomes. They are batched into one terminal repair rather than another iterative
review loop:

- Reduce duplicate check names with the established recency-aware fail-closed reducer so an older
  success cannot overwrite a newer failure or pending result by list order.
- Treat an incomplete or malformed per-PR file snapshot as that PR's ineligibility without aborting
  inspection of later PRs in the automation batch; PR-number identity corruption remains lane-wide.
- Require a valid full snapshot head before initiative-integrator dry-run can report `would_merge`,
  and include that head in the result.

**Terminal acceptance criteria**

- [x] Duplicate check rows reduce to the newer failure in either input order.
- [x] A malformed/truncated file snapshot blocks only that PR and a later complete PR remains eligible.
- [x] Initiative dry-run with a missing or malformed snapshot head reports blocked, not `would_merge`.
- [x] Each protection has a mutation break test that fails when the protection is removed.
- [x] Cumulative touched-surface tests pass: 155 passed, 0 skipped; scoped Ruff and mypy pass.
- [x] Drift/docs/preflight checks pass on the restored final tree; the ready-only docs build exposed
      omitted metric mirrors, which were regenerated with `doc_stats.py --write` and the docs-site
      sync before the replacement exact-head review.
- [ ] One fresh exact-head Claude+OpenAI terminal dry run has no P0-P2 findings.
- [ ] If that review finds another P0-P2, stop for OWNER direction rather than start another repair loop.

## Successor Run: Reconcile #9677 After This Follow-Up Lands

This is intentionally not a batch on the current branch. Begin only after the fresh-main follow-up
has actually merged and the active owner of #9677 has released its lane.

1. Re-read #9677's live exact head, owner/lease, current main, checks, and current-main overlap.
2. In a dedicated #9677 worktree, merge current main into the PR branch without rebasing or force
   pushing, preserving this follow-up and all #9677 halt-guard changes.
3. Regenerate module tiers, metrics, documentation statistics, and docs-site mirrors.
4. Run the cumulative focused suite, lint, type checks, hooks, drift checks, and mutation tests.
5. Run one fresh terminal independent review of the full PR diff.
6. Stop for exact-head OWNER settlement. Do not collect quorum evidence, settle, or merge without
   the separately applicable live gate authorization.

## Non-Negotiables

- Do not touch #9677 or its branch during this fresh-main run.
- Do not resolve a head inside a merge helper after its eligibility/settlement snapshot.
- Do not allow a missing or malformed head to reach a merge subprocess.
- Do not edit workflows, protected governance, branch protection, or required-check configuration.
- Do not mark ready, post evidence, settle, or merge until the final exact-head review and every live
  non-quorum gate are clean. Thereafter use only the separately authorized Tier-4 OWNER path; never
  bypass a failing or unstable gate.
- Never rebase or force-push; stage specific files only.

## Test Strategy

- **Baseline:** `python3 -m pytest tests/scripts/test_merge_codex_automation_prs.py tests/swarm/test_boss_drain.py tests/swarm/test_merge_arbiter.py -q --no-header -p no:randomly --timeout=300` (75 passed at staging); the cumulative touched-surface run also includes `tests/swarm/test_initiative_integrator.py`.
- **Lint:** `python3 -m ruff check` on the four source files and focused tests.
- **Typecheck:** `python3 -m mypy` on the four source files.
- **Structural:** search all relevant callers for head propagation and every merge argv for an
  unconditional exact-head pin.
- **Break tests:** temporarily remove each propagation/pin in turn, confirm the corresponding test
  fails, restore with `apply_patch`, and rerun green.
- **Pre-push:** repository hooks plus `bash scripts/automation_pr_preflight.sh origin/main HEAD`.
- **Review:** fresh read-only independent reviewer after the final push.

## Batch Sizing

```yaml
team-size: 2
sprint-length: 1 day
```

## Notes

- Initial approval covered Tier-4 implementation preparation only. The later OWNER instruction to
  proceed in the recommended order authorizes exact-head readiness, evidence, settlement, and merge
  only if the terminal review and every live gate are clean.
- Main's five non-quorum required contexts were green at staging; main quorum was skipped as
  expected. Recheck live state before every push and readiness claim.
- #9677 moved from `015c69a...` to `13fc885...` during staging in another lane. Treat that as a
  strict ownership boundary, not a head to adopt.
