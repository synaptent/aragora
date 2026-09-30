# Two-Lane CI System

Aragora uses a two-lane CI architecture to balance fast feedback for development with thorough validation before merge.

## Control Plane Guardrails

The lane system is automation-assisted, not merge-blocking:

- **PR admission monitor (advisory):** `.github/workflows/pr-admission-controller.yml` runs `scripts/pr_admission_controller.py` to report lane pressure; default mode is non-blocking.
- **Stale-run GC:** `.github/workflows/pr-stale-run-gc.yml` runs `scripts/pr_stale_run_gc.py` to cancel orphaned or stale-SHA runs that consume runner capacity.
- **Auto-revert safety rail:** `.github/workflows/main-required-checks-auto-revert.yml` reverts the latest `main` commit when required checks finish in a failed terminal state.
- **Agent throughput first:** keep parallel PR flow and rely on fast detection + cheap rollback over hard admission gates.

For the autonomy boundary around workflow, runner, release, and main-branch
changes, see [`docs/governance/ci-main-guardrails.md`](governance/ci-main-guardrails.md).

Operator quick commands:

```bash
# Cancel stale PR runs (requires GITHUB_TOKEN)
python3 scripts/pr_stale_run_gc.py --repo synaptent/aragora --max-runs 500

# Prune merged local branches
git branch --merged main | grep -v '^\*' | xargs -r git branch -d
```

## How It Works

| Lane | PR Status | Checks Run | Time |
|------|-----------|------------|------|
| **R&D (Draft)** | Draft PR | 6 required checks, lightweight/advisory lanes, fast-gate no-op | ~10 min |
| **Integrator (Ready)** | Ready for review | PR suites, including the future fast gate; compatibility/debate shards stay off PRs | Varies by suite |

### R&D Lane (Draft PRs)

Draft PRs run the 6 required checks plus lightweight/advisory lanes. Heavy test
workers skip drafts. This keeps CI queues fast for parallel development branches.

**Required checks (always run):**

| Workflow | Check | Purpose |
|----------|-------|---------|
| `lint.yml` | `lint` | Ruff linting and CI policies |
| `lint.yml` | `typecheck` | mypy type checking |
| `sdk-parity.yml` | `sdk-parity` | Python/TypeScript SDK alignment |
| `openapi.yml` | Generate & Validate | OpenAPI spec validation |
| `sdk-test.yml` | TypeScript SDK Type Check | TS SDK compilation |
| `aragora-merge-quorum.yml` | `aragora-merge-quorum` | Merge governance |

### Fast test gate (FUTURE required check)

`test-fast-gate` is a **FUTURE required check**, not active in branch protection
at M4 or M10. Its expected duration is **at most 10 minutes**, subject to
verification on full scheduled runs before activation. In `test.yml`,
`test-fast-gate-run` has a hard 10-minute job timeout, depends only on
`test-shard-scope`, and shares the existing non-debate fast shard matrix and
steps with `test-fast`. `test-fast` retains its longer diagnostic timeouts but
no longer waits for `baseline-determinism`; that job and its other consumers remain.
Runner queue time, classification, and the short umbrella job are not bounded by
the worker timeout, so the end-to-end target must be measured, not inferred.

`Tests` runs on every PR against `main`, with no trigger-level `paths` or
`paths-ignore` filter. The former 19-pattern trigger allowlist now lives in
`test-shard-scope`'s `in_scope` filter, pinned by
`tests/ci/test_fast_gate_workflows.py`. Its `in_scope` output is true on PRs
only when a changed file matches the allowlist, and true on every non-PR event.
The classifier runs on drafts too. Every PR root job and the fast workers
gate on this output; out-of-scope PRs cascade-skip all other work, including
the always-running summaries and audits. The umbrella is green in about one
minute on these PRs. `Tests` keeps its nightly `0 4 * * *` schedule, manual
`workflow_dispatch`, and original concurrency group. It has no push trigger.

The `test-fast-gate` umbrella always runs after the classifier and worker matrix.
It requires successful classification, then accepts successful in-scope workers
on ready PRs or non-PR runs, skipped out-of-scope workers, or skipped in-scope
workers only on drafts. Failure, cancellation, missing/unknown results, and
skipped in-scope workers on ready PRs fail closed. A green draft gate does not
certify that tests executed. On ready PRs, relevance filtering selects matching shards.

A second producer of the `test-fast-gate` check-run name must never be reintroduced.
GitHub's observed latest-completed-wins behaviour honours the most recently
completed same-named check run. It creates an umbrella's check run only after
its `needs` finish, so a companion's early success on a mixed-path PR could
satisfy the required check for minutes before the real gate even exists.
Keeping exactly one producer in `test.yml` closes that window.

`.github/workflows/test-debate-shards.yml`, named **Tests (debate shards)**,
runs `debate-phases`, `debate-1`, `debate-2`, and `debate-3` on pushes to `main`,
nightly at `0 4 * * *`, and manual dispatch, never on PRs. It preserves the shard
resolver boundaries and 30-minute caps. The separate compatibility, integration,
and randomized-order suites retain their existing coverage. The auto-revert
workflow currently listens to `Lint`, `SDK Parity Check`, `OpenAPI Spec`, and
`SDK Tests`, not `Tests`, so no workflow-name migration is needed there. Its
script continues to read required contexts live from branch protection.

#### Prepared protection change (M10 quotes, M11 executes only after settlement)

M10 records this exact command in its PR body but **does not execute it**.
Only the separate M11 Tier-4 settlement may execute it, after explicit operator
authorization, M4 has merged, and at least three scheduled `Tests` runs on
`main` show the fully executed gate green within the target duration. M11 also
verifies the single workflow's out-of-scope PR check. Until then, the six checks above
and `strict: false` remain unchanged.

Write this JSON body to `/tmp/aragora-readiness/required-checks.json` at settlement:

```json
{
  "strict": false,
  "contexts": [
    "lint",
    "typecheck",
    "sdk-parity",
    "Generate & Validate",
    "TypeScript SDK Type Check",
    "aragora-merge-quorum",
    "test-fast-gate"
  ],
  "checks": [
    {"context": "lint", "app_id": 15368},
    {"context": "typecheck", "app_id": 15368},
    {"context": "sdk-parity", "app_id": 15368},
    {"context": "Generate & Validate", "app_id": 15368},
    {"context": "TypeScript SDK Type Check", "app_id": 15368},
    {"context": "aragora-merge-quorum", "app_id": 15368},
    {"context": "test-fast-gate", "app_id": 15368}
  ]
}
```

```bash
gh api -X PATCH repos/synaptent/aragora/branches/main/protection/required_status_checks --input /tmp/aragora-readiness/required-checks.json
```

### Integrator Lane (Ready PRs)

When a PR is marked "Ready for review", heavy PR workflows can trigger via the
`ready_for_review` event type, subject to their path and job filters. These include:

- **Test suites:** test, e2e, integration, integration-gate, core-suites, smoke, smoke-offline, migration-tests
- **Quality gates:** coverage, benchmark, benchmarks, load-tests, capability-gap, new-features
- **Security:** security, security-gate
- **Build/Deploy:** docker, build, lighthouse, release-readiness
- **Governance:** contract-drift-governance, connector-registry, live-deploy-mode-gate, aragora-gauntlet, autopilot-worktree-e2e

## Promoting a PR

To promote a draft PR to the Integrator lane:

1. Go to your PR on GitHub
2. Click **"Ready for review"** at the bottom of the PR page
3. All heavy checks will automatically start running

To demote a PR back to the R&D lane:

1. Click **"Convert to draft"** under the Reviewers section
2. Future pushes skip heavy workers while the 6 required checks and lightweight lanes remain

## Implementation Details

### Draft Gate Condition

Heavy workflows use this condition on every job:

```yaml
if: ${{ github.event_name != 'pull_request' || github.event.pull_request.draft == false }}
```

This allows the job to run on push/schedule/dispatch events normally, but skips it for draft PRs.

### Ready for Review Trigger

Heavy workflows include `ready_for_review` in their trigger types:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
```

This ensures checks automatically start when a PR transitions from draft to ready.

### Concurrency Controls

All PR-triggered workflows have concurrency groups to cancel stale runs:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.head_ref || github.ref }}
  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}
```

### Meta-Workflow

`required-check-priority.yml` coordinates the required checks to ensure they get runner priority.

## Reading main-branch CI telemetry

Reviewers and dashboards sometimes look at `gh run list --branch main` and conclude CI is broken because most runs show as `skipped`. **This is a misread of the telemetry, not a real failure mode.** Where actual test signal lives:

| Where you look | What you see | What it means |
|----------------|--------------|---------------|
| `gh run list --branch main` | ~70% skipped | Background watchdog workflows correctly self-gating |
| `gh run list --event pull_request` | ~90% success, isolated failures | The real lint / test / type-check / SDK-parity signal |
| Branch protection on `main` | 6 required checks, all run on PRs | What actually gates a merge; `test-fast-gate` is still future |

**Why main-branch runs look mostly-skipped:**

1. **`Main Required Checks Auto Revert`** triggers via `workflow_run` (every completion of `Lint` / `SDK Parity Check` / `OpenAPI Spec` / `SDK Tests`). Its job has an `if:` gate that only fires for `push` events on `main`. Every PR-event upstream completion creates a workflow_run that the job correctly skips. This generates the bulk of the apparent skip rate (~57 of 100 runs in a typical week).

2. **`TestFixer Auto`** is explicitly disabled in code (`if: github.event_name == 'workflow_dispatch'`) because the auto-fix loop caused CI thrash (push → cancel → restart). Re-enable via manual `workflow_dispatch` for targeted fix runs only. Generates ~14 skipped runs per 100.

3. **`Tests`** triggers on every PR against `main`, schedule, and manual dispatch,
not push. An out-of-scope docs-only PR runs `test-shard-scope`, cascade-skips
the workers, and gets `test-fast-gate` success from the same workflow.
`Tests (debate shards)` runs on main pushes, schedule,
and dispatch only. Other workflows retain their own event filters.

**Healthy main-branch CI looks like:**

- A small number of `success` runs from deploy/publish workflows (`Branch Discipline`, `Docs Consistency`, `Deploy Frontend`, etc.)
- A larger number of `skipped` runs from `Main Required Checks Auto Revert` (when triggering events weren't pushes to main)
- Zero or near-zero `failure` runs (failures here mean main is actually broken)

**Where to look for real regressions instead:**

```bash
# PR-time CI signal — this is what gates merges
gh run list --event pull_request --limit 100

# Failed runs only (across all events)
gh run list --status failure --limit 20

# Check a specific PR's required checks
gh pr checks <PR-NUMBER>
```

**Outlier patterns worth investigating:**

- `failure` on `Main Required Checks Auto Revert` — the auto-revert script itself broke
- Sustained `failure` on PR-time `Lint` / `SDK Parity Check` — actual quality regression
- `Tests` workflow not running for a PR against `main`, or in-scope workers skipped on a ready PR: trigger or scope-gate drift
