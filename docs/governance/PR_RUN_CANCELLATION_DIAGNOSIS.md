# PR Workflow-Run Cancellation — Diagnosis & Mitigation Plan

## Correction (2026-07-16): the canceller is in-repo — Required Check Priority

The "external cancellation actor" conclusion below is **retracted**. The canceller
is `.github/workflows/required-check-priority.yml` (RCP) itself. RCP runs on every
`pull_request` event and performs 4 sweeps (10 s apart) that cancelled every queued
**and in-progress** advisory `pull_request` run at the PR head not in its
keep-list.

Smoking gun: RCP run **29520862671** cancelled runs 29520863012 / 29520863349 /
29520863087 / 29520862378 on PR #9346 seconds after creation, with no newer push.
Its sweep log reads:

```
Canceled run 29520863012 (Module Tier Drift)
…
Sweep 1/4: considered 14, canceled 4
```

This also explains every "external actor" signature observed below: the raciness
(a fast advisory run survives if it finishes before a sweep reaches it — hence
Portability Lint's ~50/50 split), the selectivity (only non-keep-listed advisory
`pull_request` runs), and why `push`-to-main runs are always green (RCP only
triggers on `pull_request`). M2 ("identify & scope the external canceller") is
resolved: no org-level App or account automation is involved.

The rerun side of the loop is by design, not a gap: the cancelled-run guardian
(`.github/workflows/pr-cancelled-run-guardian.yml`, driven by
`scripts/ci/required_workflow_manifest.json`) deliberately reruns **only**
manifest/keep-listed workflows — advisory cancellations "are that system working
and stay cancelled" (see below). So every RCP-cancelled advisory run persisted as
a red `cancelled` conclusion until a human rerun, which blocked the conservative
merge executor on every long-lived PR (repeated manual reruns observed on
PRs #9170, #9322, #9346 on 2026-07-15/16).

**Fix applied:** RCP's sweep now cancels **queued runs only**
(`if (run.status !== 'queued') continue;`). In-progress runs already hold a
runner, so cancelling them saved nothing; queued advisory runs still yield to
required checks, preserving all queue-pressure relief. The queued-only invariant
is enforced by `scripts/check_required_check_priority_policy.py`.

---

Status: **diagnosis + plan (no code/CI changes in this doc).** Companion to
`docs/governance/MODULE_TIER_DRIFT_GUARDIAN.md`, which established that the recurring
`check`/`portability` reds on PRs are **cancellations, not drift**. This doc pins
*what does the cancelling* and proposes a safe, minimal mitigation for a human to approve.

## TL;DR

- On a freshly-opened PR, a **subset of advisory workflows is cancelled at the
  Checkout/Set-up step within ~6 s**, while required/core checks on the *same SHA,
  same single `opened` event* succeed. Observed cancelled set: **Portability Lint,
  Docs Consistency, Build Documentation (PR Check), Module Tier Drift, Metrics Drift**.
- **It is not self-cancellation, not the in-repo stale-run GC, not the workflows'
  own `concurrency:` config, and not a spending cap / runner outage.** All four are
  ruled out with evidence below.
- It is therefore an **external cancellation actor** (a GitHub App / org-level
  automation with `actions: write`, or an account-level canceller) that targets
  non-required advisory `pull_request` runs, intermittently (~50 % of Portability
  Lint PR runs repo-wide; `push`-to-main runs are 100 % green).
- **Mitigation:** because the workflows' own config is not the cause, the fix is
  *not* a `concurrency:` edit. The lowest-risk, already-proven pattern is a
  **re-trigger guardian** that re-runs cancelled, non-superseded `pull_request`
  runs once — mirroring the existing `.github/workflows/aragora-merge-quorum-retrigger.yml`.
  The guardian is **approval-required** (new workflow), so it is proposed here, not
  implemented. The *better* long-term fix is to identify and scope the external
  canceller (decision point below).

## Evidence (all reproducible via `gh`/API, captured at origin/main `3102e25be5`)

### 1. One run per workflow per SHA — no superseding run (rules out self-cancellation)

All runs for PR #7874 head `ea7b13c5ed…`, every one created at the same instant from
a single `opened` event:

```
Portability Lint           pull_request   cancelled
Docs Consistency           pull_request   cancelled
Build Documentation (PR)   pull_request   cancelled
Aragora Merge Quorum       pull_request   failure     (expected — no quorum evidence)
Lint                       pull_request   success
SDK Tests                  pull_request   success
SDK Parity Check           pull_request   success
OpenAPI Spec               pull_request   success
Required Check Priority    pull_request   success
PR Admission Controller    pull_request   success
Aragora Code Review        pull_request   success
Aragora PR Review          pull_request_target  success
```

`gh run list --workflow "<wf>" --branch <branch>` returns **exactly one** run per
workflow. `cancel-in-progress` cancels an *older* run only when a *newer* run is
queued in the same group; there is no newer run, so this is not self-cancellation.

### 2. The stale-run GC was not running then (rules out the in-repo canceller)

The only in-repo code that cancels runs is `scripts/pr_stale_run_gc.py`
(`POST /actions/runs/{id}/cancel`), driven by `.github/workflows/pr-stale-run-gc.yml`
(cron `*/10`, in practice throttled to ~every 28-30 min). Cancellations occurred at
`20:59:26Z` and `21:30:26Z`; the GC ran at `20:42:38Z` and `21:11:42Z` — **not** at
either cancellation time. Moreover the GC only cancels runs whose branch has
**no open PR** (`no-active-pr-head`) or whose SHA is **not the PR head** (`stale-sha`);
neither applies to a fresh, single-push, open PR whose run SHA *is* the head.

### 3. Cancelled and successful workflows share identical concurrency config

Every workflow above keys concurrency on `…-${{ github.event.pull_request.number || github.ref }}`
with `cancel-in-progress` on PRs (unique per PR). The cancelled set and the
successful set are **structurally identical** here, so the workflows' own config does
not explain why some cancel and some pass.

### 4. Intermittent + selective (rules out spending cap / outage)

Repo-wide over the last 30 runs each:

```
Portability Lint:  pull_request cancelled: 10 | pull_request success: 10 | push success: 10
Module Tier Drift: pull_request cancelled:  2 | pull_request skipped: 28
Metrics Drift:     pull_request cancelled:  2 | pull_request skipped: 28
```

`push`-to-main runs are 100 % green; only `pull_request` runs cancel, ~half the time,
and only for a specific advisory subset while required checks on the same commit pass.
A spending cap or runner outage would not be this selective.

## Conclusion

The cancellations are issued by an **external actor** (outside these workflow files)
that targets non-required advisory `pull_request` runs. It is racy: a run survives if
it finishes its ~4-6 s work before the actor reaches it (hence Portability Lint's
~50/50 split and `push` runs always passing). This is consistent with a GitHub App or
org/account automation holding `actions: write`; it is **not** addressable by editing
the affected workflows' `concurrency:` blocks.

## Mitigation options

### M1. Re-trigger guardian — RECOMMENDED, approval-required (plan only here)
A new scheduled workflow + `scripts/retrigger_cancelled_pr_runs.py` that:
- lists recent `pull_request` runs with `conclusion == cancelled`;
- keeps only those whose `head_sha` **equals the PR's current head** (not superseded)
  **and** for which no newer run of the same workflow+branch exists;
- excludes draft PRs and runs older than a short TTL;
- calls `gh run rerun <id>` **once** per run, recording a marker to avoid re-run loops.

This mirrors the existing, accepted `.github/workflows/aragora-merge-quorum-retrigger.yml`
(whose "only privileged action is `gh run rerun`"). The Python script is *not* workflow
config and can ship with unit tests; the workflow YAML that invokes it **is**
approval-required and must be human-authorized.

Risk: a re-run loop if the external actor keeps cancelling — bounded by the
once-per-run marker and TTL. Cost: extra runner minutes for re-runs.

### M2. Identify & scope the external canceller — BEST long-term (decision/prereq)
Determine the actor (org Actions settings → installed Apps with `actions: write`; org
rulesets; any account-level canceller). If found, scope it to **skip non-required
advisory workflows** so they are never cancelled. This fixes the cause rather than
re-running around it. Requires org-admin visibility this lane does not have.

### M3. Accept advisory reds as non-blocking — STOPGAP
These workflows are already **non-required**, so the cancellations do not block merges.
Document them as "advisory; cancellation ≠ failure" and rely on the weekly `schedule`
runs (Module Tier Drift / Metrics Drift already run Monday) plus `push`-to-main runs
(Portability Lint) for real coverage. Zero engineering cost; leaves PR UI noisy.

## How to run in the transport loop

Use the Python guardian manually from a conductor or executor lane before treating
cancelled protected checks as a human transport task. The tool is repo-scoped (it
inspects recent workflow runs and open PR heads itself) and is **dry-run by
default**:

```bash
python3 scripts/retrigger_cancelled_pr_runs.py \
  --repo synaptent/aragora \
  --max-runs 300 \
  --ttl-hours 6
```

The helper uses `GITHUB_TOKEN` (or `GH_TOKEN`); run `gh auth status` first if the
local credential state is unclear.

Eligibility is provenance-aware: a cancelled run is rerun-eligible ONLY when its
workflow **path** is in `scripts/ci/required_workflow_manifest.json` (the versioned
protected manifest mirroring required-check-priority.yml's keep-list — advisory
cancellations are that system working and stay cancelled), its head SHA equals the
PR's current head, no newer run of the same workflow+branch+head exists, the PR is
open and non-draft, the cancellation is younger than `--ttl-hours`, and
`run_attempt == 1`. The attempt counter is the loop guard: a rerun bumps it, so a
run is never retriggered twice. Repeat with `--apply` to perform the reruns; the
JSON report lists every candidate with its applied/detail status, and any rerun
API failure exits 1 so a scheduled invocation cannot fail silently.

Do not use this tool to bypass real failures. A rerun that comes back failed, such
as a docs-sync/build failure, is a repair packet for the PR branch.

## Decision points

1. Pursue **M2 first** (identify the canceller) before building **M1**? Re-running
   around an unknown canceller treats the symptom.
2. If **M1**: approve the new workflow's `actions: write` (or `gh run rerun`) scope,
   the TTL, and the loop-guard marker.
3. Owner: this lane, or the CI-resilience lane (`docs/governance/ci-main-guardrails.md`)?
