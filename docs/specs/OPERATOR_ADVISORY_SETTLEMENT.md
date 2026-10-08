# Operator Advisory Settlement — constitutional relief valve for the merge-quorum gate

Status: proposed (Tier 4 merge-authority self-modification; requires human
preapproval to implement and to merge, per `docs/REVIEW_AUTHORITY_PRINCIPLES.md`).

Origin: the #8933 typecheck-false-green incident (PR #8939), 2026-07-11.

## Problem: unreachable quorum, not merely unmet

The merge-quorum gate can reach a state where model quorum is **structurally
unreachable** rather than simply not yet collected:

- Severity-gated dissent (`docs/specs/FINDING_SEVERITY_GATE.md`) makes a review
  carrying only advisory `[P2]`/`[P3]` notes **non-blocking but also
  non-counting**.
- For changes to the governance/CI machinery itself, the advisory-objection
  space does not converge: each round's fixes become the next round's surface,
  and a `[P2]` costs a reviewer nothing to assign.
- PR #8939 demonstrated this empirically: four evidence rounds, **zero**
  `[P0]`/`[P1]` findings in any round, claude PASS every round — and **zero**
  countable signals, because every review carried advisory notes.

The result is a constitutional defect: **any fix to the merge-quorum gate must
pass through the merge-quorum gate it fixes.** A self-hosting governance system
needs an amendment path that does not route through the component being amended.
Before this valve, the only mechanical escape was disabling a branch-protection
safeguard — precisely the action the gate exists to make unnecessary.

## The valve

At packet status `needs_model_review_quorum`, a new verdict
`operator_advisory_settlement` authorizes the merge when **all** of the
following hold (any failure → fail closed, verdict unchanged):

1. Flag `ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT` is on (default OFF).
2. Tier is **3 or 4** — the incident class. At Tier 0-2 an unmet quorum means
   "not reviewed yet"; the answer there stays "collect reviews" or qualify for
   the existing Tier 0-2 `advisory_settle` path.
3. No unresolved dissent, **and** no blocking `[P0]`/`[P1]` finding in any
   grounded review — reusing the same fail-closed permissive blocking scan
   `advisory_settle` uses (`_advisory_settle_review_signals`, hardened in
   #8729 against spoofed-identity / bot-author laundering). **Blocking model
   dissent still stops everyone, including the operator.**
   3a. **A genuine advisory dissent must be present** — a validated-source
   `changes_requested` carrying only `[P2]`/`[P3]` (no `[P0]`/`[P1]`). This is
   the load-bearing distinction (openai #9203 P1): `signal_count == 0` alone
   cannot tell "every review was severity-gated to advisory" (the case this
   valve is *for*) apart from "reviews failed to count for INFRA reasons" — a
   missing receipt artifact, a reviewer CLI outage, an unrecognized heading.
   The genuine-dissent requirement is evidence of severity-gating, not proof
   that no infra failure also occurred (claude #9203 round-7 P3). **Infra
   failures must be repaired (re-collect, restore the reviewer), never settled
   over** — the operator settles over the advisory dissent only. A PR whose
   reviews were all *passes* that merely failed to count for infra reasons
   settles through the NORMAL front door (get the passes to count), not this
   valve.
4. A validated western-frontier review is present at head, and **≥2 distinct
   canonical model families** were heard — computed from a strict validated
   pass: grounded, non-bot, countable identity, **and authored by a trusted
   evidence-poster login** (`ARAGORA_TRUSTED_EVIDENCE_POSTERS`, default: the
   operator's settlement + collector accounts). Authorship is the load-bearing
   guard: it is API-real (GitHub sets it from the authenticated token), so no
   comment BODY can establish a heard family from an untrusted account — any
   body text, including a fabricated `Receipt artifact:` line, is forgeable
   (openai #9203 round-5 P1). The strict pass deliberately does NOT require a
   receipt artifact: `compose_evidence_comment` never emits one, so a receipt
   requirement would make the valve unfireable against every real
   collector-posted review (openai #9203 round-6 P2). Comment-side records
   remain corroborating, not unforgeable (write-access collaborators can edit
   bodies with `author.login` preserved); the creator-pinned commit status
   (condition 5) is the sole unforgeable authorization root.
5. An `aragora/human-settlement` commit status = success at the exact head,
   created by the **trusted settlement operator login**
   (`ARAGORA_SETTLEMENT_CREATOR`, default `scarmani`) — the unforgeable
   authorization spine (GitHub sets status creator from the authenticated
   token; no repo workflow holds `statuses: write`).
6. A `Tier-4 Human Settlement Authorization` marker comment **authored by the
   trusted settlement operator**, naming the exact head, carrying an
   authorized-merge token and the risk-acceptance phrase.

Only the model quorum requirement is relaxed; every other blocker (failing or
pending checks, blocking workflow state, `[P0]`/`[P1]`, unresolved dissent) is
untouched. The settled verdict is a **distinct, auditable value**
(`operator_advisory_settlement`, not `admin_squash_allowed`), and the workflow
emits a `::notice::OPERATOR-SETTLED-OVER-ADVISORY` line naming the PR, head,
tier, and validated families.

Inside the enforcing job, the required-check surface is also fetched whenever its own quorum row was excluded from the rollup summary, keeping the valve reachable when every other check is green.

Packet reporting claims non-required non-green checks only when the rollup's
required-check membership classification identifies them. An unavailable required
surface remains unknown, not a failed rollup. Raw pending self rows are preserved;
the existing self-row exclusions still apply to summaries and diagnostic counts.
Controlled in-job fixtures, including mocked settlement-creator checks, prove
unit reachability only, not live CI execution or authorization.

## What is preserved

- `[P0]`/`[P1]` model dissent blocks the operator exactly as before.
- Tier 0-2 behavior is unchanged (the valve is Tier 3-4 only).
- The blocking-finding bar is the same one `advisory_settle` uses — the valve
  is never laxer than the machine advisory path.
- Authorization is a trusted-creator commit status; comments are corroborating
  record, not the auth root (and the marker author is verified too).

## Revert

Single env flip: `ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT` back to unset in
`.github/workflows/aragora-merge-quorum.yml` (itself a Tier-4 edit).

## Follow-ups

- Consolidate the flag helper into `aragora.swarm.quorum_evidence` beside
  `advisory_dissent_settle_enabled` once PRs #9129/#9147 (which contest that
  file) land.
- This valve is the amendment path the constitutional-circle finding of the
  #8933 incident identified; the incident postmortem should reference it.
