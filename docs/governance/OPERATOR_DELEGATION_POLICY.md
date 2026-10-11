# Operator Delegation Policy

**Status:** active (additive — does not replace
`docs/AGENT_OPERATING_CONTRACT.md`; specializes it for the routine
operator review workload).

**Scope:** how to allocate decisions between the human operator and
frontier-model agents on this repo so the operator is not a bottleneck
on the kinds of judgment frontier models do better, while remaining
the sole authority on the kinds of judgment only the operator can
make.

## Why this exists

The operator on this repo (`@an0mium`) ships ~30 PRs/day and has
~14 open at any given time. The operator's stated comparative
advantage is **high-level intent articulation** ("here in a vague way
is what I want"), not line-by-line PR review. Frontier models
demonstrably make better technical judgments on this codebase than
the operator's manual review can. Treating the operator as the
default PR reviewer therefore wastes their highest-leverage capacity
and creates queue backpressure.

This document codifies a four-bucket delegation policy that lets
agents do almost all judgment, surfaces only the irreducible
operator-only decisions, and produces an audit trail the operator
can review in aggregate rather than per-PR.

## The four buckets

Every open PR lands in exactly one bucket at evaluation time. An
agent (or the future `scripts/triage_open_prs.py` automation) runs
the classification; the operator only sees Buckets C and D.

### Bucket A — Auto-merge (agent decides; operator never sees it per-PR)

**All of these MUST be true:**

- `mergeable: MERGEABLE`
- PR is not draft
- `mergeStateStatus` is `CLEAN`, or branch protection is blocking
  only on review while Aragora's merge packet authorizes admin squash
- CI: all checks `SUCCESS`; zero `FAILURE`; zero `IN_PROGRESS` /
  `QUEUED`
- `python3 -m aragora.cli.main review-queue merge-packet --pr <N>
  --json` reports, at the exact current head SHA:
  - `admin_squash_allowed: true`
  - `not_ready: []`
  - `unresolved_dissent: false`
  - green check summary
- Tier 3 and Tier 4 PRs are never Bucket A unless the merge packet
  shows the required human risk settlement or preapproval has already
  been recorded for that exact head SHA
- Diff is additive only:
  - No edits to protected files
    (`CLAUDE.md`, `aragora/__init__.py`, `.env`, `.envrc`,
    `scripts/nomic_loop.py`, `docs/AGENT_OPERATING_CONTRACT.md`,
    `automation.toml`)
  - No flag flips (no `default=True` for previously `default=False`
    feature flags; no `enable_*` defaults changed)
  - No new `boss-ready` / `autonomous` labels
- Tests added or updated alongside any new behavior
- `bash scripts/automation_pr_preflight.sh origin/main HEAD` → `ok`
- Doesn't touch any held PR (see hold list below)
- Author is on the trusted-authors list (currently: `@an0mium`)
- Net LOC ≤ 1500 (large-diff escape valve to Bucket C)

If all hold, an automation may merge the PR after a brief settling
window (default: 30 min after the last commit; configurable). The
automation must re-run the merge packet immediately before merge and
use `--match-head-commit`; head drift demotes the PR out of Bucket A
until it is reclassified.

### Bucket B — Auto-close (agent decides; operator never sees it per-PR)

**Any of these triggers close:**

- A newer open PR replaces the same surface (`changedFiles`
  intersection ≥ 80%) AND the newer PR is in Bucket A or already
  merged
- > 60 days old + still draft + zero activity in last 30 days + no
  reference from any canonical doc (`docs/CANONICAL_GOALS.md`,
  `docs/strategy/FOCUS.md`, `docs/status/NEXT_STEPS_CANONICAL.md`,
  `docs/AGENT_ASSIGNMENTS.md`)
- CI red for >7 consecutive days with zero fix-attempt commits

The closing comment MUST include the classification reason and a
pointer to the superseding PR (if any), so the operator can recover
the work later if they disagree.

### Bucket C — Flag for one-line operator y/n

**Any of these triggers Bucket C:**

- Touches a held PR or held lane
- Touches a protected file
- Includes a flag flip / label add / `mark-ready` on held
- Net diff > 1500 LOC
- CI red and isn't a known-flake (matches `tests/.known_flakes`)
- Has unresolved review comments from another agent
- Introduces a new external dependency / network call / secret read
- New CI lane / runner-label / workflow change

For each Bucket C PR, the agent emits **one line** in this exact
shape, ordered by recommended action:

```
#N — RECOMMEND <ACTION> — <≤120-char justification>
```

Example:
```
#7245 — RECOMMEND DEFER — codex-insights signed digest, 22/63 CI with
        19 still pending — wait for CI complete then re-bucket
```

The operator answers in batch with single-letter responses:
`y` (do recommendation) / `n` (do opposite) / `d` (defer / no action).
Total operator review time: ~3 seconds per PR.

### Bucket D — Strategic check-in (operator gets a paragraph)

Reserved for PRs that work technically but plausibly conflict with
canonical direction. Examples:

- PR widens scope while `docs/status/NEXT_STEPS_CANONICAL.md`
  currently says "do not widen scope"
- PR ships infrastructure that the canonical goals don't reference,
  in a phase where the canonical gate is "operate what's already
  shipped"
- PR introduces a public API surface the operator hasn't publicly
  committed to

Cap: ≤1 Bucket-D escalation per day. If agents see more, they're
mis-classifying (almost everything technical belongs in A/B/C).

## Irreducible operator-only decisions

These tripwires MUST stop the agent and require explicit operator
input, regardless of any other criteria:

| Action | Why operator-only |
|---|---|
| Edit `CLAUDE.md`, `aragora/__init__.py`, `.env`, `.envrc`, `scripts/nomic_loop.py`, `docs/AGENT_OPERATING_CONTRACT.md` | Protected per repo guide |
| Lift a hold (`#7173`, `#7215`, `#7240`, `#7243`, `#7245`, `#7249`, `#7252`, `#4990`, BC-12 soak, `#7209` lane) | Operator wrote the hold; only operator lifts it |
| Add `boss-ready` / `autonomous` labels | Labels gate downstream automation |
| `mark-ready` on a held PR | Held PRs must not advance |
| Force-push / rebase / delete on `main` | Destructive |
| Force-push to `main` (any branch) | Destructive |
| Deploy to production | External system mutation |
| Spend AI-provider quota above per-session threshold | Cost control |
| Close a PR opened by another agent | Each agent owns its own PRs |
| Add a new external dependency / secret read | Supply-chain & risk |
| Change public API contract (`aragora/server/`, `aragora/client/`) | External commitments |
| Change marketing / public docs (`docs/COMMERCIAL_OVERVIEW.md`, `docs/WHY_ARAGORA.md`) | Reputational |

Hitting any tripwire: agent stops, posts an inline question, awaits
single-line operator response. Never works around. Never silently
defers.

## What the operator still does

The operator's authoritative role under this policy:

1. **Direction-setting** — "here in a vague high level way is what
   I want." Sets project intent, business priorities, vertical bets.
2. **Risk-tripwire ownership** — names what bad things must not
   happen; updates the irreducible list above as posture evolves.
3. **Bucket C y/n batch** — once per day, processes the Bucket C
   list. ~3 seconds per PR.
4. **Bucket D check-in** — reads any escalation paragraph and
   responds within a session.
5. **Aggregate review** — weekly skim of merged PRs; monthly review
   of session receipts (`docs/status/SESSION_RECEIPT_*.md` /
   `docs/status/*_RECEIPT_*.md`) for trajectory.
6. **Policy revision** — periodic update of bucket criteria as the
   project scales.

The operator does **not** do: line-by-line code review, technical
correctness assessment, convention checking, test-coverage judgment,
merge-cleanliness verification, canonical-doc compliance. Those are
agent work.

## Hold list (canonical reference)

PRs and lanes the operator has explicitly held; agents must NOT
advance any of these by even one byte without explicit operator
authorization:

- PRs: `#7173`, `#7215`, `#7240`, `#7243`, `#7245`, `#7249`,
  `#7252`, `#4990`
- Lanes: `#7209` lane, BC-12 soak

This list lives here as the canonical reference and is duplicated in
`scripts/apply_operator_decisions.py` (`HELD_PR_NUMBERS`). Whoever
updates the hold list updates both.

## Rollout

See `docs/roadmap/OPERATOR_DELEGATION_ROLLOUT.md` for the staged
implementation. Tracking issues are filed under the
`operator-delegation` label.

## Relationship to other governance docs

| Doc | Relationship |
|---|---|
| `docs/AGENT_OPERATING_CONTRACT.md` | Parent contract; this doc specializes its review-workload section. The contract remains authoritative on anything not addressed here. |
| `docs/CANONICAL_GOALS.md` | Sets project intent; Bucket D escalations check PRs against it. |
| `docs/strategy/FOCUS.md` / `docs/THESIS.md` | Strategic direction inputs to Bucket D classification. |
| `docs/status/NEXT_STEPS_CANONICAL.md` | Active gate; the policy explicitly does not auto-merge PRs that widen scope while the canonical gate says otherwise. |
| `docs/REVIEW_AUTHORITY_PRINCIPLES.md` | 5-tier merge classification; Bucket A is only possible when the review-queue merge packet says admin squash is allowed at the exact current head. |
| `scripts/apply_operator_decisions.py` | Implements the operator-decisions JSON consumption side of Bucket A/B/C; honors the hold list above. |
