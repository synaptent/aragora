# Harvest Disposition Rubric

This rubric classifies stale worktree harvest items from issue #8993 before any
conductor adopts, preserves, or cleans up stranded work. It is a read-only
triage layer: a disposition records what live evidence proves, but it is not
permission to bypass ownership, settlement, branch-protection, or deletion
rules.

Use it when a #8993 item has no live owner and a conductor needs one bounded
progress unit. Do not use it for active PR settlement, model evidence, CI reruns,
or broad worktree cleanup.

## Required Inputs

Collect these facts before claiming an item:

- Latest `$HOME/.codex/aragora_steering/mailbox.jsonl` entries.
- `docs/AGENT_OPERATING_CONTRACT.md` §Conductor and
  `docs/REVIEW_AUTHORITY_PRINCIPLES.md`.
- Current `origin/main` SHA and required-context status.
- The #8993 inventory row for the item.
- All #8993 comments whose first line starts with the item id.
- `safe_worktree_cleanup.py inspect <path> --json`.
- `git status --short --branch`, `git rev-parse HEAD`, and
  `git diff --stat origin/main...HEAD` inside the candidate worktree.
- Live GitHub linkage for any branch, open PR, closed merged PR, or closed
  unmerged PR related to the item.

## Claim Then Reverify

#8993 harvest items use issue comments as the per-object lock. The safe sequence
is:

1. Re-read the issue body and comments immediately before claiming.
2. Post one claim comment naming the item id, path, head, lane, a unique
   `claim_id`, `claimed_at`, and `expires_at`. Claims expire after 60 minutes;
   use UTC RFC 3339 timestamps.
3. Use the returned comment id to confirm the claim is readable, then wait at
   least five seconds and re-read all comments for the same item. Require the
   same comment-id set on two reads at least five seconds apart before
   proceeding. Bound convergence at 30 seconds; on timeout, post `RELEASE` if
   the claim is visible and stop. Never inspect or disposition while claim
   visibility is uncertain.
4. Process each `claim_id`'s transitions chronologically by GitHub `createdAt`,
   then comment database id. A `RENEW` is valid only if its preceding state was
   active and unexpired when the renewal comment was created. Invalid or late
   transitions do not change claim state. After replay, `CLAIM` and valid
   `RENEW` states are active only before `expires_at`; `YIELD`, `RELEASE`, and a
   disposition receipt are terminal. Ignore expired and terminal claims.
5. If an earlier active claim exists, post `YIELD` for this lane's `claim_id`
   and do not inspect, mutate, clean up, or disposition that item. Order
   simultaneous claims by GitHub `createdAt`, then comment database id.
6. If this lane holds the earliest active claim, continue with read-only
   inspection and post exactly one disposition receipt before expiry. Include
   the `claim_id` in the receipt so it terminally closes the claim.

Use append-only state comments rather than editing the original claim:

```text
S44 CLAIM harvest-S44-20260708T1627Z
claimed_at: 2026-07-08T16:27:00Z
expires_at: 2026-07-08T17:27:00Z
lane: codex-example
path: /path/to/worktree
head: abc1234

S44 RENEW harvest-S44-20260708T1627Z
expires_at: 2026-07-08T18:12:00Z

S44 YIELD harvest-S44-20260708T1627Z
winner: harvest-S44-20260708T1626Z

S44 YIELD harvest-S44-20260708T1627Z
winner_comment_id: 4916644479
```

Post `RENEW` before expiry if inspection will exceed the current window. A
renewal extends the deadline by at most another 60 minutes; it cannot revive an
already expired or terminal claim. If a lane stops without a disposition,
post `RELEASE`. A crashed lane needs no manual unlock: after `expires_at`, a new
claim may proceed and should cite the expired `claim_id` in its receipt.

For legacy claim comments without `claim_id` or `expires_at`, treat the comment
as active for 60 minutes after its GitHub `createdAt`. A later yield comment or
disposition receipt for the same item ends that legacy claim. This compatibility
rule prevents old issue history from becoming a permanent lock while preserving
recent in-flight claims.

The lock is per item, not global. Another conductor process is not a collision
unless it holds an earlier active claim for the same item.

## Dispositions

| Disposition | Use when live evidence proves | Allowed action in the harvest cycle |
| --- | --- | --- |
| `FOLD` | The item is represented by an existing PR branch or merged PR. The item head is an ancestor of that surviving head, or the diff is otherwise proven contained. | Post a receipt linking the surviving PR/head. Cleanup is separate and only allowed through `safe_worktree_cleanup.py` after the receipt if the helper reports no blockers. |
| `RETIRE/PRESERVE` | The useful content is already superseded by `origin/main` or a merged PR, but the helper still reports a preservation blocker such as `dirty_worktree` or `branch_ahead_of_origin_main`. | Post a receipt and preserve the source checkout or branch. Do not delete, reset, or force-clean. |
| `PARK` | The item contains significant unmerged work or a closed-unmerged PR lineage that is not safe to adopt inside the current lane. | Post a receipt explaining why deliberate revival, closure, or owner review is required. Do not clean up. |
| `ADOPT` | The item has unique useful work, no open PR representation, no active owner, no blocking steering, and can be restacked into an isolated branch without mutating the source worktree. | Create a disposable worktree from current `origin/main`, apply only the selected item value, validate, claim a branch lease before push, and open a draft PR. Preserve the source checkout until the adoption PR is terminal. |

## Dirty Worktrees

Dirty worktrees are not cleanup candidates. A dirty item may still receive a
RETIRE/PRESERVE receipt when the committed and dirty changes are proven
superseded, but the source must remain untouched. The S39 receipt is the worked
example: helper inspection reported `dirty_worktree`, current `origin/main`
already contained the stronger #8726 transport handling, and the receipt
explicitly preserved the dirty source instead of removing it.

## Receipt Wording

Use a disposition-first first line:

```text
S43 FOLD receipt (2026-07-08T16:17Z)
claim_id: harvest-S43-20260708T1617Z
S36 PARK receipt (2026-07-08T16:00Z)
claim_id: harvest-S36-20260708T1600Z
S40 RETIRE/PRESERVE receipt (2026-07-08T16:11Z)
claim_id: harvest-S40-20260708T1611Z
S44 ADOPT receipt (2026-07-08T16:27Z)
claim_id: harvest-S44-20260708T1627Z
```

For a legacy winner without a `claim_id`, identify it in `YIELD` with
`winner_comment_id`, using the GitHub comment database id. New disposition
receipts always include this lane's `claim_id` immediately after the first line.

Avoid local guard logic that searches for the word `receipt` anywhere in the
claim body. Cycle 81 hit false duplicate detection because the S36 claim said it
would later post a receipt. Guards should match the first line against an
explicit disposition pattern, not a body-wide substring.

## Worked Examples

- S34 FOLD: the detached timeout-followup head was an ancestor of merged PR
  #8726, so the receipt linked the merged PR and did not delete the source
  checkout. Receipt:
  `https://github.com/synaptent/aragora/issues/8993#issuecomment-4916644479`.
- S36 PARK: the compliance oversight pack belonged to closed-unmerged PR #8289
  lineage and was not contained in `origin/main`, so the receipt preserved it
  for deliberate revival or retirement. Receipt:
  `https://github.com/synaptent/aragora/issues/8993#issuecomment-4916753760`.
- S39 RETIRE/PRESERVE: the transport retry work was superseded by #8726, but the
  helper reported a dirty worktree, so the receipt preserved the source.
  Receipt:
  `https://github.com/synaptent/aragora/issues/8993#issuecomment-4916787719`.
- S40 RETIRE/PRESERVE: the SDK workflow dependency setup was superseded by
  merged PR #8951, but the helper reported `branch_ahead_of_origin_main`, so the
  receipt preserved the branch worktree. Receipt:
  `https://github.com/synaptent/aragora/issues/8993#issuecomment-4916816045`.
- S43 FOLD: the receipt proved the detached head was contained in merged PR
  #8669 before a separate helper cleanup receipt removed the now-represented
  checkout. Receipts:
  `https://github.com/synaptent/aragora/issues/8993#issuecomment-4916869141`
  and
  `https://github.com/synaptent/aragora/issues/8993#issuecomment-4916872720`.
- S44 ADOPT: the source branch had unique work and no open PR, so the conductor
  restacked it into a disposable worktree, validated focused tests, claimed the
  branch lease, and opened draft PR #9023 while preserving the source worktree.
  Receipt:
  `https://github.com/synaptent/aragora/issues/8993#issuecomment-4916928378`.

## Hard Stops

- Do not clean up if `safe_worktree_cleanup.py inspect` reports blockers.
- Do not mutate the shared root or the source worktree during triage.
- Do not adopt workflow, branch-protection, settlement, or merge-authority
  changes without the required Tier 4 human authorization.
- Do not post evidence, settle, mark ready, rerun CI, merge, force-push, or use
  `--admin` as part of a harvest disposition.
- Do not infer ownership from old transcript state. Re-read comments, steering,
  branch state, and PR state immediately before mutation.
