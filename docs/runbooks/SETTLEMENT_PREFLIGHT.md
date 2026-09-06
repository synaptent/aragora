# Settlement Gate Preflight

`scripts/settle_preflight.py` is a read-only classifier for conductor queue
selection. It answers one question before a lane spends review or settlement
effort: what is the next legal action for this PR under
`docs/AGENT_OPERATING_CONTRACT.md` §Conductor?

The classifier does not post comments, rerun checks, collect evidence, mark PRs
ready, merge, edit labels, or change branch protection.

## Usage

Classify one PR:

```bash
python3 scripts/settle_preflight.py --pr 8990 --repo synaptent/aragora --json
```

Classify the open queue:

```bash
python3 scripts/settle_preflight.py --queue --repo synaptent/aragora --json
```

`--queue` is intentionally a thin enumerator. It lists open PR numbers, then
classifies each PR through the same single-PR loader used by `--pr`: live PR
metadata, non-empty policy file metadata, required-check state, active-owner
state, and the merge packet all flow through one classification path. Queue mode
must not carry a separate policy or readiness implementation.

Callers must run the main-health check first. If any material required context
on `origin/main` is red or missing, pass `--main-red` only to produce a
`MAIN_RED_HALT` report; do not keep advancing PRs.

Every verdict carries this recheck rule:

> recheck on next origin/main push; never poll in a loop.

## Verdicts

| Verdict | Meaning | Conductor action |
| --- | --- | --- |
| `MAIN_RED_HALT` | `origin/main` required checks are not green. | Stop queue work and enter main-red incident mode. |
| `DRAFT_SKIP` | The PR is draft. | Skip until the PR is explicitly ready for review. |
| `HUMAN_GATED` | Tier is above 2, the packet requires unsettled human risk settlement or preapproval, or repo policy excludes autonomous settlement. | Stop and request exact-head human/operator settlement before evidence or merge. |
| `HEAD_BLOCKED` | The packet head does not match the live head, the head is conflicting, behind, dirty, missing a satisfied packet, or has current-head blockers. | Park this head until the blocker clears or a repair head lands. |
| `GITHUB_UNSTABLE` | The model packet is authorized, but GitHub reports an unstable, unknown, or non-mergeable state. | Do not merge; wait for settlement-stable GitHub state on a future main push. |
| `READY` | The PR is model-authorized and settlement-stable: `MERGEABLE` plus `CLEAN`, or `MERGEABLE` plus `BLOCKED` when packet/check blockers are clear and the only remaining gate is quorum/human-settlement. | Run one final live check, then use normal exact-head protected squash merge. |

## READY Invariant

`READY` is fail-closed. A PR with `mergeStateStatus=BLOCKED` is only
settlement-stable when the live required-check surface proves the block is
quorum-only: `lint`, `typecheck`, `sdk-parity`, `Generate & Validate`, and
`TypeScript SDK Type Check` are successful, `aragora-merge-quorum` is the only
non-success required context, `reviewDecision` is not `CHANGES_REQUESTED`, and
policy metadata includes at least one changed file. Missing live metadata,
missing or empty file scope, missing required-check metadata, unknown required
contexts, or active-owner uncertainty parks the PR as `HEAD_BLOCKED`.

## Park vs. Wait

Park when the blocker is about the PR head: human gate, draft state, missing
model quorum, current-head dissent, dirty/conflicting state, or an unresolved
repair finding.

Wait when the blocker is GitHub's transient merge-state calculation after the
packet is already authorized. `UNSTABLE`, missing/unknown merge state, and
non-`MERGEABLE` live state are not settlement-stable. `BLOCKED` is
settlement-stable only after policy exclusions, packet blockers, and
current-head blockers are clear, because in that case the remaining blocker is
the exact quorum or human-settlement context the packet is meant to satisfy. Do
not poll continuously. Record the exact head, merge packet status, check state,
and next recheck trigger.

This composes with
`docs/plans/2026-07-07-repeat-blocker-park-policy.md`: a current-head park
record remains the source of truth for avoiding repeated evidence attempts, and
the preflight classifier provides the cheap first-pass skip signal before a
conductor spends a cycle.

## Worked Example: #8990

#8990 added `docs/plans/2026-07-07-repeat-blocker-park-policy.md`. The exact
head `427aacc893a1f508690296405e0bbcf233b17c56` first failed
`aragora-merge-quorum` because no countable Tier 0 model signal existed. After
an exact-head OpenAI PASS landed, the merge packet became satisfied and
required checks were green, but GitHub still reported `mergeStateStatus` as
`UNSTABLE`.

Under §Conductor, `UNSTABLE` is not settlement-stable, so the correct
preflight verdict during that interval was `GITHUB_UNSTABLE`: wait for the next
main-push recheck, do not run another evidence cycle, and do not merge by
conductor automation. The PR later merged normally at merge commit
`196bf38d540df5bd37a5a0918d8b8dd54604c2f6` once the unstable state cleared.
