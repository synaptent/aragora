# Fresh-call launch prompt

Launch the staged Aragora Agent Operating Tower run.

Use the `elves-aragora` skill and the governed run already staged in
`$HOME/.codex/worktrees/agent-operating-tower-20260831/aragora`. This is a
continuation of the same conductor cycle: the one allowed Fable goal cycle has
already completed through VibeProxy, so do not run another consult before Batch
1. Its advice is recorded and remains advisory only.

Before any mutation:

1. Change to the dedicated worktree and read, in order:
   `docs/elves/agent-operating-tower-20260831/plan.md`,
   `survival-guide.md`, `execution-log.md`, `learnings.md`, and
   `.aragora/run-agent-operating-tower-20260831/session.json`.
2. Confirm the branch is `codex/agent-operating-tower-20260831`, HEAD equals the
   exact `staging_head` in runtime state, the worktree is clean, and the shared
   checkout remains untouched.
3. Read operator steering, record outcomes for any messages, refresh the
   heartbeat, and verify lane `agent-operating-tower-20260831` and lease
   `82e882f4-7f4` are still held by
   `codex-agent-operating-tower-20260831` with the intended scope.
4. Refresh exact `origin/main`, halt state, main health, protected required
   contexts, ownership, and the branch-tip tripwire. If the base moved, follow
   the plan's additive-restack rule before product work and invalidate any stale
   proof. Stop on a conflict or any stop condition.

Then execute only Batch 1 as the first bounded unit: establish the canonical
Agent Operating Loop contract, additive `aragora.orientation.v1` JSON Schema,
and executable trace fixtures for fresh orientation, interrupted resumption,
uncertain high-risk action, and quiet no-change recheck. Do not wire runtime
source adapters, implement `aragora orient`, add mutation behavior, change a
protected surface, introduce a database/service, launch a model implicitly, or
modify existing `nomic run` behavior.

Keep the batch at or below 800 changed lines. Tag the pre-batch tip and record the
checkpoint. Run focused tests, Ruff check and format check, touched-module MyPy,
all-files pre-commit, normal pre-push hooks, diff/ownership checks, automation
preflight, protected CI, direct grounded Claude and Codex exact-head review, and
a verified canonical DecisionReceipt. VibeProxy/Fable cannot count toward
quorum. Use no `--admin`, force-push, rebase, amend of a published tip, or branch
protection mutation.

Treat Batch 1 as Tier 1 but operator-review-required because it is the first PR
of a new architectural pattern. Prepare the exact-head evidence and settlement
packet, then stop for that human review rather than merging it automatically.
After future authorized settlement, continue the remaining batches serially
according to the plan and its tier gates. At most two gate attempts are allowed
per batch; stop on the documented drift, health, lease, scope, dissent,
infrastructure, elapsed-time, line-count, or human-gate conditions.
