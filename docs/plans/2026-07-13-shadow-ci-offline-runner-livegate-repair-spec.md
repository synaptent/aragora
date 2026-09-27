# Shadow CI Offline-Runner Live-Gate Repair Spec

**Date:** 2026-07-13
**Status:** draft repair specification
**Tracking issue:** [#9098](https://github.com/synaptent/aragora/issues/9098)
**Observed main:** `a36cad1f060221bae788fd53b4885a76b022757f`
**Blocked PR:** [#9201](https://github.com/synaptent/aragora/pull/9201)
**Blocked head:** `32fc2e88a177fe3fd6340a21af74db1eecef2be9`
**Park record:** [#9201 exact-head handoff](https://github.com/synaptent/aragora/pull/9201#issuecomment-4962954059)

## Scope

This document packages the offline self-hosted-runner failure behind #9201 into
an operator-decidable repair plan. It is intentionally docs-only. It does not
edit workflows, runner configuration, secrets, merge tooling, branch
protection, or the #9201 branch.

Every implementation option below changes either workflow/runner behavior or
merge-authority tooling. Those are approval-required tool changes under
[`docs/AGENT_OPERATING_CONTRACT.md`](../AGENT_OPERATING_CONTRACT.md). This spec
does not authorize an implementation, settlement, or merge.

## Problem Statement

The `Self-Hosted Shadow CI` workflow schedules `Mac TypeScript SDK Shadow` on
this exact label set:

```yaml
runs-on:
  - self-hosted
  - aragora
  - macOS
  - ARM64
  - mac-studio
```

The source is
[`.github/workflows/self-hosted-shadow.yml`](../../.github/workflows/self-hosted-shadow.yml),
lines 60-69 at observed main. The only registered runner matching the complete
set was `mac-studio-m3ultra` (runner id 32), which the GitHub runner inventory
reported `offline`, `busy=false` on 2026-07-13.

For #9201, job `86919795400` has remained queued with `runner_id=0` since
`2026-07-13T19:55:56Z`:

<https://github.com/synaptent/aragora/actions/runs/29280349773/job/86919795400>

The job declares `timeout-minutes: 10`, but that limit did not terminate the
unassigned queue wait because the job never started. The PR has 6/6 required
checks green, countable Claude and OpenAI evidence, and no unresolved dissent,
yet GitHub reports `mergeStateStatus=UNSTABLE`. The merge packet therefore
stops in
`aragora.cli.commands.review_queue._admin_squash_live_gate_blockers()` with:

```text
mergeStateStatus=UNSTABLE; admin squash requires CLEAN or BLOCKED
```

GitHub's
[self-hosted runner reference](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)
imposes a separate 24-hour platform limit on jobs waiting for a matching
self-hosted runner. That bound is still far outside a useful PR settlement
horizon, and repeated workflow events can leave multiple runs pending
concurrently unless the workflow also bounds its own concurrency.

The three other non-green surfaces on #9201 were classified separately:
Metrics Drift, Module Tier Drift, and Portability Lint had each cancelled in
checkout before its verifier ran. Each verifier passed one exact-head rerun.
The queued Mac job remained as a distinct live-gate blocker. See the
[exact-head park record](https://github.com/synaptent/aragora/pull/9201#issuecomment-4962954059)
and the
[`UNSTABLE` settlement runbook](../runbooks/MERGE_STATE_UNSTABLE_SETTLEMENT.md).

## Blast Radius

The workflow's `pull_request.paths` filter is:

```yaml
- 'sdk/typescript/**'
- 'aragora/agents/**'
- 'aragora/cli/**'
- 'aragora/core.py'
- 'aragora/demo/**'
- 'tests/cli/test_offline_golden_path.py'
- 'scripts/ci_install_project.sh'
- 'pyproject.toml'
- 'requirements*.txt'
- '.github/workflows/self-hosted-shadow.yml'
- '.github/actions/pr-scope-classifier/**'
- '.github/actions/setup-node-safe/**'
- '.github/actions/setup-python-safe/**'
```

Docs-only PRs do not select this workflow through the current path filter.
Same-repository product PRs touching any listed path can schedule the Mac job
and remain settlement-blocked while no matching runner is online. Fork PRs and
draft PRs are excluded by the job-level condition.

The workflow also schedules `Hetzner Offline Golden Path Shadow` with labels
`self-hosted, aragora, Linux, X64, hetzner`. The same unassigned queue-wait
analysis applies if every matching Hetzner runner is offline. At the 2026-07-13
snapshot, runner ids 21, 22, and 23 all matched that label set and were online
and idle; the #9201 Hetzner shadow completed successfully.

## Option A: Trusted Base-Revision Runner Preflight

### Proposed Diff

Change the PR trigger to `pull_request_target` so the workflow definition is
loaded from the trusted default branch. GitHub's
[`pull_request_target` security guidance](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
requires least-privilege token and secret handling for this privileged trigger.
Retain an explicit workflow-level `permissions: contents: read` block; this
workflow needs no write-capable `GITHUB_TOKEN`. Split the current hosted work
into two jobs:

1. `capacity` queries runner inventory. It must not checkout any repository
   content, invoke a local action, interpolate PR-controlled strings into a
   shell command, or run on a self-hosted runner. It is the only job that may
   reference the runner-inventory secret.
2. `scope` performs path classification without receiving that secret. It must
   be skipped for fork PRs before any checkout. For same-repository PRs, any
   checkout of the PR merge ref must use `persist-credentials: false`.

The trusted `capacity` job emits:

```yaml
mac_online: ${{ steps.capacity.outputs.mac_online }}
hetzner_online: ${{ steps.capacity.outputs.hetzner_online }}
inventory_ok: ${{ steps.capacity.outputs.inventory_ok }}
```

The capacity step compares each required label set against online runners.
Gate the self-hosted jobs on the corresponding online output and make both jobs
depend on `capacity` and `scope`:

```yaml
if: <existing-condition> && needs.capacity.outputs.mac_online == 'true'
```

and:

```yaml
if: <existing-condition> && needs.capacity.outputs.hetzner_online == 'true'
```

Because `pull_request_target` normally checks out the base revision, each
self-hosted job must explicitly checkout the PR merge ref after the capacity
decision, with `persist-credentials: false`. Neither self-hosted job may receive
the inventory secret. Keep the current same-repository and non-draft guards.

The trusted-base trigger also means a PR change to
`.github/workflows/self-hosted-shadow.yml` does not exercise its proposed
workflow definition before merge: the base revision still supplies the running
workflow. Preserve the workflow path filter so the trusted check still runs,
but treat this as an explicit testability loss and require separate static
workflow-policy fixtures for changes to the workflow itself.

Add an always-completing GitHub-hosted summary job that reports whether each
shadow was run or skipped for unavailable capacity. An unavailable runner at
snapshot time must produce a visible degraded receipt rather than a queue wait
that is not bounded by the job's `timeout-minutes`. Inventory lookup errors must
fail closed and must not be reported as healthy.

The repository `GITHUB_TOKEN` has previously received HTTP 403 from the runner
inventory endpoint. This option therefore needs a dedicated secret, such as
`RUNNER_MONITOR_TOKEN`, whose fine-grained repository permission is exactly
`Administration: read`; an `Actions`-scoped token does not grant the runner
inventory endpoint. The secret must be referenced only by the trusted hosted
`capacity` job. No job that checks out or executes PR-controlled content may
receive it.

This preflight reduces the known-offline case but cannot make an atomic promise
about later capacity. A runner can go offline between the inventory snapshot
and job assignment. Keep the existing out-of-band health monitor and add a
hosted queue-age alert so this race is reported as a runner incident. Do not
claim that the preflight alone makes queued self-hosted jobs impossible.

### Tier and Authority

This is Tier 4 and approval-required because it changes a GitHub Actions
workflow, secret use, and CI scheduling behavior.

Exact implementation authority sentence:

> I authorize a bounded Tier 4 implementation of #9098 Option A from main
> `a36cad1f060221bae788fd53b4885a76b022757f`, limited to
> `.github/workflows/self-hosted-shadow.yml`, a trusted base-revision capacity
> job with no checkout, workflow-level `permissions: contents: read`, an
> `Administration: read` runner-inventory secret reference isolated from every
> PR-code job, a queue-age alert, and focused workflow-policy tests that cover
> the base-workflow testability gap. This does not authorize settlement or
> merge of the resulting exact head.

### Verification

- Validate the workflow with the repo's workflow-policy tests and actionlint.
- Fixture-test online, offline, unauthorized, missing-secret, and malformed
  inventory responses.
- Assert the workflow-level `GITHUB_TOKEN` permissions remain exactly
  `contents: read` and no job broadens them.
- Prove the secret-bearing job uses the base workflow definition, performs no
  checkout, invokes no PR-controlled code, and passes no secret or derived
  credential to downstream jobs.
- Prove offline Mac capacity at snapshot time yields a completed hosted receipt
  and a neutral skipped Mac job, not a queued self-hosted job.
- Prove online Mac capacity preserves the current exact label set and executes
  the TypeScript SDK typecheck against the explicit PR merge ref without
  persisted checkout credentials.
- Prove fork PRs never checkout code in a secret-bearing context.
- Prove a simulated post-snapshot runner outage reaches the queue-age alert and
  remains a blocker rather than being misreported as healthy.
- Prove static policy fixtures reject an unsafe proposed workflow even though
  `pull_request_target` executes the base workflow definition.
- Receive fresh exact-head model review and Tier 4 human settlement.

### Rollback

Revert the workflow commit, restore the `pull_request` trigger, and remove the
dedicated secret reference. Preserve the #9098 issue and run artifacts. Do not
delete or re-label runners as part of rollback.

## Option B: Decouple Shadow Jobs from Pull Requests

### Proposed Diff

Remove the `pull_request` trigger and run the existing shadow jobs after pushes
to `main`, on a nightly schedule, and through `workflow_dispatch`:

```yaml
on:
  push:
    branches: [main]
    paths: <existing path list>
  schedule:
    - cron: '<operator-selected UTC schedule>'
  workflow_dispatch:
```

Add a GitHub-hosted `capacity` job before either self-hosted job on every
trigger. It must query the runner inventory using an `Administration: read`
credential, emit the same per-label-set online outputs as Option A, and pass no
secret or derived credential to downstream jobs. Unknown, unauthorized, or
missing inventory must fail closed. If a label set has no online match, skip
that self-hosted job and emit a completed degraded-capacity summary instead of
creating a queued self-hosted job.

Replace PR-only concurrency with a trigger-appropriate group that bounds push
bursts and repeated dispatches:

```yaml
concurrency:
  group: self-hosted-shadow-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

Remove other PR-only conditions that no longer apply. Keep the exact runner
labels and test commands. The hosted preflight has the same post-snapshot race
as Option A, so retain the queue-age alert and do not claim that this option
eliminates every possible queue wait. GitHub's 24-hour unmatched-runner limit
remains the outer platform bound; the capacity gate and concurrency group are
what prevent a known outage from accumulating a day-long run per main push.

This preserves cross-platform regression signal but moves it after merge. It
eliminates the PR live-gate wall at the cost of losing pre-merge shadow signal.

### Tier and Authority

This is Tier 4 and approval-required because it changes workflow triggers and
the point at which regressions are detected.

Exact implementation authority sentence:

> I authorize a bounded Tier 4 implementation of #9098 Option B from main
> `a36cad1f060221bae788fd53b4885a76b022757f`, limited to moving Self-Hosted
> Shadow CI from pull requests to path-filtered main pushes, nightly schedule,
> and manual dispatch, with a hosted runner-capacity preflight, an isolated
> `Administration: read` inventory credential, bounded concurrency, a degraded
> capacity summary, a queue-age alert, and focused workflow-policy tests. This
> does not authorize settlement or merge of the resulting exact head.

### Verification

- Validate trigger, path-filter, concurrency, and job-condition shapes.
- Prove a matching draft or ready PR does not schedule either shadow job.
- Prove a matching main push schedules both shadows when capacity exists.
- Prove offline, unauthorized, missing, and malformed capacity states schedule
  no self-hosted job and complete with a visible degraded receipt.
- Prove repeated matching pushes and manual dispatches cannot accumulate
  multiple active runs in the same concurrency group.
- Prove the inventory credential is unavailable to every self-hosted step.
- Prove a post-snapshot outage reaches the queue-age alert rather than being
  reported as healthy.
- Prove the nightly and manual paths remain available.
- Receive fresh exact-head model review and Tier 4 human settlement.

### Rollback

Revert the trigger, capacity, summary, and concurrency changes and remove the
inventory-secret reference to restore PR execution. Before rollback, verify a
matching Mac runner is online so the old unassigned queue-wait failure is not
reintroduced immediately.

## Option C: Infra-Class Settlement Predicate

### Proposed Diff

Extend
`aragora.cli.commands.review_queue._admin_squash_live_gate_blockers()` and its
callers so `UNSTABLE` can be classified as infra-only only when every predicate
below holds at the exact head:

1. The PR is open, non-draft, and `MERGEABLE`.
2. Every current branch-protection-required check is green.
3. Model quorum is satisfied and there is no unresolved dissent.
4. Every non-green rollup entry is a queued self-hosted job.
5. Each queued job exposes a complete label set that matches zero online
   runners in a fresh GitHub runner-inventory read.
6. No queued job has an assigned runner, and no failed or cancelled domain
   verifier is hidden by the classification.
7. The packet emits each ignored job id, run URL, labels, inventory timestamp,
   and reason in an explicit receipt.
8. The exact head, required checks, runner inventory, and live gate are re-read
   immediately before the normal merge command.

`scripts/settle_one_pr.py` and the merge executor must continue to consume the
same fail-closed packet. Unknown runner inventory, permission errors, unknown
contexts, online-but-busy runners, head movement, required failures, or dissent
must block.

This option does not change GitHub's `mergeStateStatus`; it changes Aragora's
own merge-authority interpretation. An implementation must prove that the
normal protected non-admin merge path works for this state. If GitHub itself
rejects that path, the option is not viable and must not introduce an admin
bypass.

### Tier and Authority

This is Tier 4 and approval-required. Although the files are Python rather than
workflow YAML, the change modifies merge-quorum and settlement-helper authority
and is ACR-ineligible under the operating contract.

Exact implementation authority sentence:

> I authorize a bounded Tier 4 implementation of #9098 Option C from main
> `a36cad1f060221bae788fd53b4885a76b022757f`, limited to an exact-head,
> receipt-emitting infra-only predicate for queued self-hosted jobs with zero
> online matching runners, plus focused tests. No admin merge path, required
> check relaxation, settlement, or merge is authorized.

### Verification

- Unit-test every predicate and every fail-closed branch listed above.
- Test multiple queued jobs, partial label matches, unknown inventory, HTTP
  authorization failure, runner transitions, and stale head/check snapshots.
- Test that real Metrics Drift, Module Tier Drift, Portability, test, or dissent
  failures remain blockers.
- Verify `settle_one_pr.py`, merge packet, and merge executor emit the same
  ignored-infra receipt.
- Demonstrate the protected non-admin merge in a disposable test PR before the
  policy can be considered viable.
- Receive fresh exact-head model review and Tier 4 human settlement.

### Rollback

Revert the predicate and return to the current `CLEAN`/`BLOCKED` allowlist.
Preserve every emitted receipt and audit any merge that used the predicate.

## Option D: Restore the Existing Runner

### Proposed Operation

On `mac-studio-m3ultra`, inspect the existing GitHub Actions LaunchAgent and
runner logs, then restart only the existing runner service. Do not re-register
the runner, rotate credentials, change labels, install software, or edit fleet
configuration unless separately authorized. Stop if service restoration would
require any of those broader changes.

### Tier and Authority

This is an operational runner-fleet mutation and requires explicit approval.
It is the fastest way to drain the current queue but does not prevent recurrence.

Exact operational authority sentence:

> I authorize restarting only the existing `mac-studio-m3ultra` GitHub Actions
> runner service to drain job `86919795400` for PR #9201 head
> `32fc2e88a177fe3fd6340a21af74db1eecef2be9`. Do not re-register it, change
> labels/configuration/secrets, install software, reboot the host, or merge the
> PR; stop if any broader mutation is required.

### Verification

- Record the pre-operation runner API state and service/log diagnosis.
- Confirm runner id 32 returns online with the unchanged complete label set.
- Confirm job `86919795400` receives that runner and completes or produces a
  real test failure.
- Re-read #9201 required checks and merge state; do not infer merge authority
  from runner recovery.
- Write an operation receipt with timestamps and every command class used,
  without exposing credentials.

### Rollback

If the restarted service is unhealthy or repeatedly corrupts jobs, stop only
that service and preserve logs. Do not remove the runner registration or alter
labels as an improvised rollback.

## Recommendation

Authorize Option D now to restore existing capacity and convert #9201's queued
unknown into either a real Mac test result or a green shadow result. In
parallel, authorize the repaired Option A as the preferred durable experiment.
Its trusted, no-checkout capacity job preserves pre-merge cross-platform signal
without exposing an Administration-read token to PR code, and its hosted
summary makes known-offline capacity visible. Option A still has a
post-snapshot race, which its queue-age alert must expose rather than hide.
Option B's capacity gate and concurrency bound prevent known-offline main-push
bursts from recreating the queue-accumulation failure, but it still discards
pre-merge signal. Option C changes merge authority in response to an
infrastructure problem, so both should remain fallbacks unless Option A proves
infeasible or fails security review.

Implementation and settlement remain separate decisions. After either durable
implementation is complete, a new exact-head Tier 4 review and human settlement
are still required before merge.
