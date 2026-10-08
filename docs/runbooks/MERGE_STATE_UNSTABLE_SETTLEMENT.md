# Merge-State `UNSTABLE` Settlement Triage

Use this runbook when a PR has green branch-protection checks but GitHub reports
`mergeStateStatus=UNSTABLE`, especially during high-churn automation queues.

## Immediate Rule

Do not collect more model-review evidence or retry settlement until the
`UNSTABLE` source is classified. Model quorum cannot repair a GitHub merge-state
summary that is being held open by cancelled or stale check runs.

## Classification

1. Read required checks from branch protection:

   ```bash
   gh api repos/synaptent/aragora/branches/main/protection/required_status_checks \
     --jq '{strict,contexts,checks}'
   gh pr checks <pr> --repo synaptent/aragora --required
   ```

2. Read the full check list and live merge state:

   ```bash
   gh pr checks <pr> --repo synaptent/aragora
   gh pr view <pr> --repo synaptent/aragora \
     --json headRefOid,mergeable,mergeStateStatus,statusCheckRollup
   ```

3. Classify the blocker:

   | Signal | Meaning | Action |
   | --- | --- | --- |
   | Required check is red | hard gate | Repair the PR or main before settlement. |
   | Required checks pass and only advisory checks are pending | queue churn | Recheck once, then proceed under the merge contract if policy allows. |
   | Latest advisory check is `cancelled` before its command ran | merge-state poison | Apply the verified allowlist predicate below; otherwise park and file or link a CI issue. |
   | Advisory check ran and failed in files touched by the PR | in-scope failure | Repair or explicitly park the PR. |
   | Advisory check ran and failed outside PR scope | possible main regression | Verify on `origin/main`, then open or link a main-health issue. |

## Settlement-Window Head Freeze

Exact-head evidence becomes stale as soon as the PR branch moves. During a
settlement window, treat the head SHA as part of the gate:

1. Record the target `headRefOid` before collecting evidence.
2. Immediately before and after every evidence post, quorum rerun, merge-packet
   read, and final merge attempt, re-read `headRefOid`. Reviewer dry runs also
   need a post-run head check before their artifact can be used.
3. If the head changed, stop the settlement attempt. Do not post stale evidence,
   rerun quorum, or chase the new head in the same cycle.
4. Leave a PR-visible head-churn note naming the old head, the new head, and any
   stale evidence artifact that must not be counted.
5. The session or person that pushed the new head should either run the next
   exact-head evidence pass or leave an explicit handoff. A different
   settlement owner may resume after a fresh owner/steering read and a new
   dry-run artifact for the new head.

This is a coordination guard, not a branch lock. It preserves the exact-head
contract without blocking repair pushes: pushes are allowed, but they invalidate
the current settlement window and transfer responsibility for refreshing
evidence to the pusher or next explicit owner.

## Portability Cancellation Pattern

Issue #9031 tracks the July 8, 2026 instance where `Portability Lint /
portability` cancelled during `actions/checkout` before
`scripts/check_portability.py` ran. The local guard passed on detached
`origin/main`, and main's own portability run was green, but GitHub still
reported `mergeStateStatus=UNSTABLE` for #9027.

This pattern is not evidence that the PR introduced private paths or portability
violations. It is a CI/workflow-concurrency settlement hazard because the
newest check run for the `portability` name can be a cancelled advisory run.

When this pattern appears:

1. Link the affected PR to #9031 or a successor issue.
2. Leave a PR handoff comment with the check name, run URL, and exact
   classification.
3. Stop settlement and evidence-collection loops unless the exact-head packet
   emits the verified allowlisted-cancellation receipt below.
4. Work the CI/runbook/tooling issue as a separate bounded unit.

## Evidence Commands

Use targeted logs to avoid large CI output:

```bash
gh run view <run-id> --repo synaptent/aragora --log \
  | rg -n "operation was canceled|Portability guard|check_portability|fetch --no-tags|##\\[error\\]"
```

Use local reproduction to distinguish a workflow cancellation from a real guard
failure. Check `origin/main` for a possible main regression, then check the
target PR head before clearing the PR source.

```bash
git fetch origin main:refs/remotes/origin/main
main_parent="$(mktemp -d /tmp/aragora-portability-main.XXXXXX)"
main_tmp="$main_parent/worktree"
git worktree add --detach "$main_tmp" origin/main
(cd "$main_tmp" && python3 scripts/check_portability.py)

head_sha="$(gh pr view <pr> --repo synaptent/aragora --json headRefOid --jq .headRefOid)"
git fetch origin "pull/<pr>/head:refs/remotes/pr/<pr>/head"
pr_parent="$(mktemp -d /tmp/aragora-portability-pr.XXXXXX)"
pr_tmp="$pr_parent/worktree"
git worktree add --detach "$pr_tmp" "$head_sha"
test "$(git -C "$pr_tmp" rev-parse HEAD)" = "$head_sha"
(cd "$pr_tmp" && python3 scripts/check_portability.py)
```

If local `origin/main` and the exact PR head both pass, or the exact PR head
already has a prior green portability run and the failed workflow never reached
the guard command, classify the target PR as parked on CI/merge-state noise
rather than source correctness.

## Verified Settlement-Stability Predicate for Cancelled Non-Required Contexts

Issue #9034 tracks the wider July 8, 2026 pattern where completed/cancelled
non-required check runs left otherwise-ready PRs in `mergeStateStatus=UNSTABLE`.
`review-queue merge-packet` may ignore this narrow cancellation class only when
it verifies every predicate below and emits an exact-head receipt. Any missing
or unverifiable field fails closed on the normal live-state gate.

The settlement helper treats a completed/cancelled non-required context as
settlement-stable only when all of these exact-head predicates are true:

1. The PR is open, non-draft, and `mergeable=MERGEABLE`.
2. The exact `headRefOid` has not changed since model evidence was collected.
3. Every branch-protection-required context is green, including
   `aragora-merge-quorum` when the action is a merge.
4. Model quorum is satisfied for the current head and `unresolved_dissent=false`.
5. The cancelled context is non-required under the current branch-protection
   context list.
6. The cancelled context is on this allowlist:
   - `Build Documentation (PR Check)` / `build`
   - `Portability Lint` / `portability`
   - `Docs Consistency` / `Docs Consistency`
   - `Self-Hosted Shadow CI` / `Mac TypeScript SDK Shadow`
7. The latest cancelled run and job belong to the exact PR head and every known
   substantive verifier step for that context is present and `SKIPPED`. A run
   with missing job metadata, unknown verifier steps, or a verifier step that
   started fails closed.
8. Every step from the first verifier step onward — whatever its name — was
   `SKIPPED` or `CANCELLED` (GitHub-injected wrap-up steps such as `Post *` and
   `Complete job` exempt). Enumerated verifier names alone would be fail-open
   under additive workflow drift; `scripts/check_required_check_priority_policy.py`
   additionally pins each allowlisted job's pre-verifier `run:` steps in CI so a
   new substantive step cannot appear without review.
9. The PR does not modify any receipt-guarded path (the four allowlisted
   workflow files, `required-check-priority.yml`, `review_queue_unstable.py`,
   or the policy check script). A PR editing those surfaces could smuggle
   substantive work behind its own cancellation, so it never qualifies for the
   exception; its cancelled advisory runs must be rerun instead.
10. The helper emits an explicit receipt field naming each ignored non-required
    cancelled context, run URL, and reason so the merge record does not silently
    hide GitHub rollup noise.

### July 8, 2026 Observations

The cycle that opened #9034 confirmed two non-draft PRs with green required
checks and model quorum, but GitHub still reported `mergeStateStatus=UNSTABLE`:

| PR | Head | Required checks | Cancelled non-required contexts |
| --- | --- | --- | --- |
| #9049 | `9790df5ae848b9a5458eed2cfc7edd34c3c85072` | all green, including `aragora-merge-quorum` | Build Documentation, Docs Consistency, Portability Lint |
| #9053 | `e4083d0b415648bd341b342b4d4228d8cf8a45c4` | all green, including `aragora-merge-quorum` | Build Documentation, Portability Lint |

Contexts outside the allowlist, required-check failures, incomplete model
quorum, unresolved dissent, head movement, or unverifiable Actions metadata
remain blocking. Do not rerun cancelled workflows from conductor automation
without exact operator authorization for that cycle.

### Receipt Contract

The merge packet consumes the branch-protection required-check list, the exact
PR `statusCheckRollup`, and Actions run/job step metadata. When the predicate
succeeds, the packet reports the ignored contexts and the complete receipt:

```json
{
  "merge_state_status": "UNSTABLE",
  "unstable_non_required_contexts_ignored": [
    {
      "workflow": "Build Documentation (PR Check)",
      "name": "build",
      "url": "https://github.com/synaptent/aragora/actions/runs/...",
      "head_sha": "<exact-pr-head>",
      "reason": "allowlisted non-required current-head run cancelled before substantive verifier command"
    }
  ],
  "check_surfaces": {
    "unstable_non_required_cancellation_receipt": {
      "schema_version": "unstable_non_required_cancellation.v1",
      "head_sha": "<exact-pr-head>",
      "required_checks_summary": "6/6 required green"
    }
  }
}
```

The receipt is recomputed from live GitHub state on every merge-packet build
and is bound to that packet's exact head; it is never cached across
invocations. Merge/apply consumers must build a fresh packet at apply time and
pass `--match-head-commit <head>` on the merge itself, so GitHub rejects the
merge if the head moves between packet build and merge. The conductor report
must include this receipt.
