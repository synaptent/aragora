# Agent Operating Tower survival guide

Read this file and `plan.md` before every batch or after any compaction.

## Mission identity

- Run ID: `agent-operating-tower-20260831`
- Active goal thread: `019ffdc4-2443-77e1-9ba4-b323bf07f824`
- Branch: `codex/agent-operating-tower-20260831`
- Worktree: `$HOME/.codex/worktrees/agent-operating-tower-20260831/aragora`
- Owner session: `codex-agent-operating-tower-20260831`
- Lane: `agent-operating-tower-20260831`
- Lease: `82e882f4-7f4`
- Starting base: `2b94459bc0e316c3c0c1eb285695bf2a0c73c647`
- Deadline: `2026-09-01T13:10:47Z`
- Runtime state: `.aragora/run-agent-operating-tower-20260831/session.json`
- Receipts: `.aragora/run-agent-operating-tower-20260831/receipts/`

## Resume protocol

1. Confirm the current directory is the dedicated worktree, never the shared
   checkout.
2. Read `plan.md`, `execution-log.md`, `learnings.md`, and runtime `session.json`.
3. Read operator steering for the lane and write an outcome receipt for every
   message before mutation.
4. Refresh the heartbeat and verify the lane claim and scoped lease still name
   this session, worktree, branch, and next action.
5. Re-read repository instructions and live halt/main-health state.
6. Resolve exact local HEAD, remote branch head, and `origin/main`; compare them
   with the latest checkpoint. Drift invalidates prepared evidence and
   authorization.
7. Run the branch-tip tripwire and diff/ownership check before changing files.
8. Resume only the single `next_batch` from `session.json`. Never fan out
   implementation or start a downstream batch before its parent gate settles.

## Current phase

Batch 1 is implemented and additively restacked on base
`552da7de4ab040f49870dc83b06de11d17170493` at draft PR `#9932`. Local gates
are green; protected CI and exact-head review remain. Use the live PR head from
GitHub and ignored runtime `session.json`, never a copied short SHA.

Batch 1 is Tier 1 but is the first PR of a new architectural pattern, so it
requires operator review before merge. Batch 6 is Tier 3. Batch 7 is Tier 3
only if it remains a dry-run internal seam and becomes Tier 4 if it changes
mutation authority or protected behavior. Batch 8 must split and park any
durable learning change as Tier 3.

## Operating invariants

- One serial coordinator; no parallel implementation agents.
- Higher layers summarize but never strengthen lower-layer authority.
- `orient` is read-only and model-free; `nomic plan` is explicit and
  commit-addressed; `nomic run` remains unchanged.
- No new database/service, implicit model call, autonomous memory promotion, or
  governance bypass.
- Never edit the dirty shared checkout.
- Never amend, rebase, force-push, use `--admin`, or mutate branch protection.
- Keep every batch at or below 800 changed lines and two gate attempts.
- Evidence is last, direct, grounded, exact-head, and two-family. VibeProxy/Fable
  is advisory only.
- Tier 3-4 stops for exact-head human settlement; Tier 4 additionally requires
  explicit preapproval before implementation.

## Required batch record

For each batch append: pre-tip tag, start/end SHAs, base SHA, tier, changed
paths/lines, tests, Ruff/format/MyPy/hooks/preflight results, protected checks,
Claude and Codex evidence artifact/digest/verdict, DecisionReceipt ID and verify
result, merge packet, settlement authority, outcome, elapsed time, and the next
legal action. Store machine-readable proof under the ignored receipt directory.

## Stop and handoff

On any stop condition, preserve the worktree and unique commits, release or
finalize the lane only when truly handing off, write an exact receipt, update
`execution-log.md` and runtime state, and give the operator one precise next
authorization or repair request. Do not continue status-only cycling after two
failed gates or three identical infrastructure failures.
