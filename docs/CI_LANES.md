# Two-Lane CI System

Aragora uses a two-lane CI architecture to balance fast feedback for development with thorough validation before merge.

## Control Plane Guardrails

The lane system is automation-assisted, not merge-blocking:

- **PR admission monitor (advisory):** `.github/workflows/pr-admission-controller.yml` runs `scripts/pr_admission_controller.py` to report lane pressure; default mode is non-blocking.
- **Stale-run GC:** `.github/workflows/pr-stale-run-gc.yml` runs `scripts/pr_stale_run_gc.py` to cancel orphaned or stale-SHA runs that consume runner capacity.
- **Agent throughput first:** keep parallel PR flow and rely on fast detection + cheap rollback over hard admission gates.

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
| **R&D (Draft)** | Draft PR | 5 required checks only | ~10 min |
| **Integrator (Ready)** | Ready for review | Full suite (58 workflows) | ~150 min |

### R&D Lane (Draft PRs)

Draft PRs run only the 5 required checks. This keeps CI queues fast for parallel development branches.

**Required checks (always run):**

| Workflow | Check | Purpose |
|----------|-------|---------|
| `lint.yml` | Lint | Ruff linting |
| `lint.yml` | Typecheck | mypy type checking |
| `sdk-parity.yml` | SDK Parity | Python/TypeScript SDK alignment |
| `openapi.yml` | Generate & Validate | OpenAPI spec validation |
| `sdk-test.yml` | TypeScript SDK Type Check | TS SDK compilation |

### Integrator Lane (Ready PRs)

When a PR is marked "Ready for review", all 25 heavy workflows automatically trigger via the `ready_for_review` event type. These include:

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
2. Future pushes will only run the 5 required checks

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
