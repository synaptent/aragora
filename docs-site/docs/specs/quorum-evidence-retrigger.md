---
title: Quorum Evidence Re-Trigger (B1, Tier 4 Pre-Approval + Draft Implementation)
description: Quorum Evidence Re-Trigger (B1, Tier 4 Pre-Approval + Draft Implementation)
---

# Quorum Evidence Re-Trigger (B1, Tier 4 Pre-Approval + Draft Implementation)

**Status:** Tier 4 pre-approval artifact WITH the complete draft
implementation in the same PR. **Never merged autonomously.** The PR
carrying this spec stays DRAFT until the operator settles it
(preapproval + exact-head human settlement), per
`docs/REVIEW_AUTHORITY_PRINCIPLES.md` and
`docs/governance/BOSS_LOOP_MERGE_GATE_RESILIENCE.md` §B1 / Phase 2.
This file and `tests/governance/test_quorum_evidence_retrigger.py` are
the pre-approval artifact; `.github/workflows/aragora-merge-quorum.yml`
carries the guarded change itself.

## Problem Statement

`aragora-merge-quorum.yml` is the enforcing, REQUIRED model-quorum
gate. It triggers on `pull_request`
`[opened, synchronize, reopened, ready_for_review]` and
`workflow_dispatch` — never on comments. But the evidence it counts is
PR comments, which are posted *after* every one of those events. The
ready-triggered evaluation therefore always pre-dates the evidence:

1. PR marked ready → gate evaluates → no countable evidence yet →
   FAILURE (correct at that instant).
2. Reviewer evidence comments land minutes later.
3. The gate never re-reads them. The check sits stale-red until someone
   (or the A1 reconciler) issues `gh run rerun`.

This is root cause #1 in
`docs/governance/BOSS_LOOP_MERGE_GATE_RESILIENCE.md` §2. It was
observed on **every settled PR of run-20260610**: each settlement paid
one guaranteed first failure, one wasted Actions evaluation run, and
+5–10 minutes of latency for the rerun cycle (PR #7727 sat stale-red
~2.5 h before the pattern was understood). The A1 reconciler
(`scripts/quorum_rerun_reconciler.py`) papers over this out-of-band;
B1 fixes it at the source. A1 remains the safety net.

## Design

Add a guarded `issue_comment: types: [created]` trigger plus a new
`evidence-retrigger` job to `aragora-merge-quorum.yml`.

### Why re-run instead of evaluating inline

An `issue_comment`-triggered workflow run executes the default-branch
workflow file and its check runs attach to the **default-branch SHA,
not the PR head**. This is the same GitHub mechanic that makes the
existing `workflow_dispatch` path "debug; does not update PR check
status". An inline evaluation in the comment-triggered run therefore
could not move the head-bound required check at all.

The job instead performs the known-safe deterministic recovery — the
exact manual fix used on #7727 and the A1 reconciler motion — at the
source: `gh run rerun <newest surviving head-bound pull_request run>`. The rerun
executes in the original `pull_request` context, so its check run binds
to the PR head and the gate genuinely re-reads the evidence.

### Trigger contract

| Element | Value |
| --- | --- |
| New trigger | `issue_comment: types: [created]` |
| PR resolution | `github.event.issue.number` (dual-event: `pull_request.number` for PR events, `issue.number` for comment events, `inputs.pr_number` for dispatch) |
| New job | `evidence-retrigger` (name `quorum-evidence-retrigger`) — distinct from the required `aragora-merge-quorum` job |
| Enforcing job | unchanged logic; gains `if: github.event_name != 'issue_comment'` so comment events never produce a default-branch-bound evaluation |
| Workflow concurrency | group extended with `github.event.issue.number`; `cancel-in-progress: false` preserved for the enforcing path (the documented anti-doom-loop invariant) |
| Retrigger concurrency | job-scoped group `quorum-evidence-retrigger-<pr>` with `cancel-in-progress: true` (debounce) |

### GUARD step (no-op success unless all hold)

Declarative (no runner scheduled when false):

- `github.event.issue.pull_request` non-null (PR comments only);
- comment author is not `github-actions[bot]` (the evidence parsers
  exclude that author, so such comments can never change the quorum;
  this also breaks any bot-comment retrigger loop).

In-step (read-only `gh api` + `jq`):

1. The comment's **first markdown heading** matches the known reviewer
   family regex (mirrors `review_queue.py` heading inference:
   `claude|anthropic|codex|tesla|harvey|factory|grok|xai|gemini|openai|gpt|mistral|codestral|deepseek|qwen|kimi|moonshot|yi|glm|zhipu|minimax|hermes`,
   word-boundary matched, case-insensitive). Non-evidence-shaped
   comments exit 0 in seconds.
2. The PR is open and non-draft (drafts defer the gate by design).
3. Deterministic selection of the ONLY legitimate rerun target
   (PR #9766). A rerun re-executes the run's ORIGINAL frozen event
   payload, so re-running an evaluation created while the PR was
   still a draft replays its draft short-circuit and can resurface a
   stale SUCCESS over the truthful newest ready-state result; and
   when the newest evaluation is busy, falling back to an older
   completed run re-executes exactly such a stale evaluation
   (observed on PR #9754: draft-era run 31772664823 attempt 2 masked
   ready-state run 31772790229). The guard therefore:
   - enumerates ALL head-bound `pull_request`-event evaluations of
     this workflow for the current head SHA via full pagination and
     reconciles the listing against the API's `total_count`; any
     mismatch (incomplete discovery) logs a warning and no-ops;
   - partitions away frozen draft payloads: runs created before the
     PR's newest `ready_for_review` issue event are dropped (the
     timeline is read through the job's read-only `issues: read`
     scope); a PR with no `ready_for_review` transition keeps all
     runs;
   - orders the survivors by
     `((run_started_at // created_at), run_id, run_attempt)` — a
     still-queued run has null `run_started_at`, which must not sort
     the newest evaluation below an older completed one — and
     considers ONLY the newest survivor. No survivor: no-op. Newest
     survivor in-flight or concluded `success`: no-op. The guard
     NEVER falls back to an older run.

Only then: `gh run rerun <newest survivor>`. Concurrent evidence
comments collapse to ONE rerun: every retrigger surface (this job and
the standalone helper workflow `aragora-merge-quorum-retrigger.yml`,
which runs the same shared selection helper) computes the same
target, a fresh status read immediately before the rerun request
makes burst losers see a non-completed run and no-op, and the rerun
API rejecting an already-queued run covers the residual race (a
rejected request logs a warning and exits 0 — comment activity must
never manufacture red noise).

### Single shared selection surface

Guards 2–3 — gate-deferral, deterministic selection, burst dedup +
rerun — live in ONE checked-in helper,
`scripts/quorum_evidence_retrigger_select.sh`, run by BOTH retrigger
surfaces from a BASE-repo default-branch checkout (the enforcing
evaluation job's existing ref pin): comment events still never
execute PR-author-controlled code, and the surfaces cannot drift
apart. Only the by-design different comment-shape guards (Guard 1
here; the heading-marker plus head-SHA-citation pre-filter in the
standalone helper) remain in the workflow files.

### Comment-shape filter boundary (intentional)

Both retrigger surfaces fire only on evidence-shaped comments: this
job requires the comment's first markdown heading to name a known
reviewer family (Guard 1), and the standalone helper workflow
(`aragora-merge-quorum-retrigger.yml`) requires a known
reviewer-heading marker plus a 7+-hex head-SHA citation in the body.
A Tier-4 human-settlement comment ("Tier-4 Human Settlement
Authorization ...") is deliberately NOT evidence-shaped — it opens
with no reviewer-family heading and carries no reviewer-heading
marker — so posting it never auto-fires either surface, even though
its operator author passes the author gates. This is a boundary, not
a gap: the distinct post-settlement quorum execution required by
Tier-4 chronology is produced by the sanctioned manual `gh run rerun`
of the newest head-bound quorum run, which is the permanent
post-settlement step in every Tier-4 settlement chronology (proven on
PR #9770, 2026-08-16 UTC).

### Permissions

Workflow-level permissions are **unchanged** (contents/pull-requests/
statuses: read), and the enforcing `merge-quorum` job inherits them
unchanged.

**Deliberate deviation from the one-line B1 sketch** ("permissions
unchanged"): the `evidence-retrigger` job carries job-scoped
`permissions: { actions: write, contents: read, pull-requests: read,
issues: read }` (`issues: read` exists solely for Guard 3's read-only
`ready_for_review` timeline read; `contents: read` solely to check
out the default-branch shared selection helper). A purely
read-permission comment-triggered run cannot move the head-bound
required check (see "Why re-run instead of evaluating inline"), so
`actions: write` — the capability to re-run this workflow's own prior
read-only evaluation — is the minimum that makes B1 do anything at
all. It cannot approve, merge, push, comment, or set statuses. The
write scope is confined to the retrigger job; the evaluation path's
permissions are byte-identical to before.

## Threat Model

**Comment-DoS.** Every repo comment fires the trigger.
Mitigations: declarative job `if` (non-PR and bot comments skip without
scheduling a runner); the heading guard exits in seconds for
non-evidence comments; workflow concurrency serializes per-PR (GitHub
keeps at most one running + one pending run per group, collapsing
floods); the job-scoped `cancel-in-progress: true` group cancels
superseded pending retriggers; Guard 3 makes the rerun itself
idempotent (once a rerun is in flight, subsequent comments no-op
because the latest run is no longer `completed`+non-success).
Residual: bounded Actions minutes from short guard executions,
proportional to comment rate on open non-draft PRs.

**Spoofed headings.** A spoofed evidence heading can trigger a
recount, never a pass. The rerun executes the same read-only
`merge-packet` evaluation with the full lint rules — exact-head SHA
grounding, `github-actions` author exclusion, lineage disclosure
requirements, heading/metadata conflict rejection, unknown-reviewer
fail-closed. Critically, **B1 does not widen the evidence-acceptance
surface**: any comment that would count after a B1 recount would count
identically at the next `synchronize` event or manual rerun today. The
trigger adds recount opportunities, not acceptance.

**Shell injection via comment body.** Attacker-controlled comment
markdown reaches the job only through `env:` (`COMMENT_BODY`), never
via inline `${{ }}` interpolation inside `run:`. The body is only ever
grepped; it is never evaluated, and no other event field
(title/branch/login) is interpolated into script text either.

**Fork-PR permissions.** `issue_comment` workflows run **on the base
repository**, from the default-branch workflow file, with the base
repo's `GITHUB_TOKEN` — stated explicitly per the B1 caveat. The
retrigger job checks out only the BASE repo's default branch (the
shared selection helper, `ref: default_branch`) and executes no
PR-author-controlled code; the rerun it requests also checks out only
the default branch (the evaluation job pins `ref: default_branch`)
and is read-only. A fork commenter therefore gets no code execution
with the token; worst case is triggering a read-only recount.

**Cancellation abuse.** `cancel-in-progress: true` is scoped to the
retrigger job's own per-PR group. The required evaluation runs keep
`cancel-in-progress: false`, so comment activity cannot cancel an
enforcing run into a red "cancelled" conclusion (the documented doom
loop this workflow already defends against).

**Retrigger loops.** Reruns are not new events and fire no triggers;
`github-actions[bot]` comments are skipped declaratively; the
no-op-unless-stale-failure guard means even a pathological commenter
converges to one rerun per genuinely stale failure per head.

**Gate weakening.** None of the enforcing logic changes: same packet
evaluation, same fail-closed branches, same Tier 3-4
`aragora/human-settlement` requirement, `enforce_admins` untouched.
Re-running a read-only evaluation can never pass a genuinely failing
PR (`BOSS_LOOP_MERGE_GATE_RESILIENCE.md` §6).

## Tier Policy

This change edits `.github/workflows/aragora-merge-quorum.yml`, which
is by its own header a **Tier 4 merge-authority self-modification**:
explicit human preapproval before implementation and before merge.

This PR is the pre-approval artifact *and* the draft implementation:

- design doc (this file)
- governance tests pinning the trigger contract
  (`tests/governance/test_quorum_evidence_retrigger.py`)
- the guarded workflow change itself

It performs **no merge or settlement action**. The PR remains DRAFT;
operator settlement requires explicit preapproval plus exact-head
model evidence and the `aragora/human-settlement` commit status before
merge, per `docs/governance/MERGE_GATE_RECONCILIATION.md`.

## Governance Test Intent

`tests/governance/test_quorum_evidence_retrigger.py` parses the
workflow with `yaml.safe_load` and pins:

- `issue_comment: [created]` is a trigger;
- the retrigger job is declaratively guarded on
  `github.event.issue.pull_request`;
- dual-event PR resolution (`github.event.issue.number` reaches both
  the workflow concurrency group and the retrigger job);
- per-PR retrigger concurrency with `cancel-in-progress: true`,
  while the workflow-level group keeps `cancel-in-progress: false`;
- the enforcing job is excluded from `issue_comment` events and gains
  no write permission; the retrigger job's write surface is exactly
  `actions: write` (its `contents` scope stays read-only, present
  solely for the helper checkout);
- the comment body enters only via `env:`, never inline in `run:`;
- the guard step references the known-reviewer-family heading match;
- both surfaces delegate Guards 2–3 to the single default-branch
  shared helper with no inline selection copy left in either
  workflow; the helper carries the stale-run conditions and the
  coalesced ordering, and behavioral fixture tests execute it
  against a fake `gh`.

The suite FAILS against the pre-change workflow (RED) and PASSES with
the change (GREEN); the RED proof is captured in the PR body.

## Operational Notes

- **Rehearsal is post-merge only.** A pre-merge rehearsal of either
  retrigger surface via a branch-ref `workflow_dispatch` fails at the
  helper invocation step: both surfaces deliberately check out
  `scripts/quorum_evidence_retrigger_select.sh` from the BASE repo's
  **default branch** (the fork-PR safety pin above), so until the PR
  carrying the helper lands, the checked-out tree does not contain it.
  This is a property of the pin, not a defect (observed on the PR #9772
  rehearsal attempt, 2026-08-16). Pre-merge behavioral coverage comes
  from the fixture-backed governance suite (`TestSelectionBehavior`
  runs the real helper against a fake `gh`); live rehearsal happens
  after merge.
- **Helper checkouts are sparse.** Both retrigger checkouts exist
  solely to fetch the helper, so they use a non-cone sparse checkout
  of exactly that file. Per-comment retrigger runs materialize a
  single script instead of the full tree.

## Operator Settlement Requested

Approving and settling the carrying PR constitutes the Tier 4
preapproval and merge settlement for this exact change at its exact
head SHA. Until then nothing changes in CI: the file on `main` is
authoritative, and `issue_comment` runs only exist after merge.
