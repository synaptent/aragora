# M0a — Operator-approved advisory-dissent post path

**Epic:** #8747 (Primitive composition) · **Precursor to:** M0 Review Adjudicator (#8748)
**Refs:** #8574 (severity-gated dissent), #8729/#8738/#8741 (advisory-settle gate), #8730/#8755 (proof PR + follow-up)
**Tier:** 2 (tooling; no merge-authority self-modification) · **Status:** implemented in this PR

## Problem (verified 2026-07-01)

The advisory-dissent settlement machinery is wired and live in CI after #8738/#8741:
`advisory_dissent_settle_enabled()` reads `ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE=1`, and
`advisory_settle_surface_clear` makes the verdict reachable inside the enforcing merge-quorum
job. The flag is **not** inert.

But the **evidence-posting layer cannot produce the artifact the gate needs.**
`aragora/swarm/quorum_evidence.py` enforces two invariants that, together, make a *fresh*
quorum-only PR that draws advisory dissent impossible to settle without hand-editing GitHub:

- **L1943** — if `outcome.dissenting_families` is non-empty under `--apply`, the action flips
  `post → prepare` and returns; **nothing is posted.**
- **L1976** — even in the non-dissent branch, the poster loop only posts items where
  `item.supportive` is true. A dissenting evidence comment is **never** posted by this tool.

`settle_pr.py` delegates all posting to `collect_quorum_evidence` (L181-186), so it inherits the
same refusal. **Net:** `advisory_settle` requires a *posted* advisory dissent to compute
`genuine validated-source advisory dissent`, but no tool will post one. It can only fire on
dissent that a prior round or a human already placed on the PR by hand.

### Empirical proof
Ran the western-frontier pair (claude + openai) against #8730 (Tier 2, signal_count=0):
claude → PASS (counts); openai → CHANGES-REQUESTED with genuine `[P2]`s (advisory, zero P0/P1).
`--apply` correctly posted nothing (`action=prepare`, `reason="reviewer dissent present"`).
The PR qualifies for advisory_settle on every substantive axis — but the artifact never lands.

## Why not just relax L1943?

Because the invariant is correct: **you must never blind-post a raw dissenting review.** A raw
`CHANGES-REQUESTED` comment is exactly what a blocking dissent looks like; posting it
unconditionally would let a [P0]/[P1] be laundered, or let the gate misread a genuine block as
advisory. The missing capability is not "post dissent" — it is "post an **adjudicated advisory
settlement record** that the gate recognizes as *considered-and-non-blocking*, gated on the hard
zero-[P0]/[P1] bar and an explicit approval point."

That record is precisely what M0's `DecisionReceipt` will be. M0a is the **posting primitive**
underneath M0: a single, auditable way to emit that record — driven by a human operator now,
and by the M0 adjudicator automatically later.

## Design

### New capability: `--post-advisory-dissent` (opt-in, operator-gated)

Add to `collect_quorum_evidence.py` (and surface via `settle_pr.py`) an opt-in path that, when
**all** of the following hold, composes and posts a single **Advisory Settlement Record**:

1. `severity_gated_dissent_enabled()` AND `advisory_dissent_settle_enabled()` are both ON.
2. Every dissenting family's findings are advisory-only: **zero `[P0]`/`[P1]`** across all items.
   (Reuse the existing severity classifier in `quorum_evidence.py` — do not reimplement.)
3. There is ≥1 supportive **counting** family at head (`has_supportive_quorum`'s counting rule).
4. Tier ≤ 2 for auto-post; Tier 3-4 always prepare-only (unchanged; the record is *surfaced*
   for `settle_tier4_pr.py`, never auto-posted).
5. An explicit approval point is present: operator opt-in flag AND (for CLI) `--operator-login`.
   The flag is the revocable approval — absent it, behavior is byte-identical to today.

Implementation note: `scripts/collect_quorum_evidence.py` and `scripts/settle_pr.py` now expose
`--post-advisory-dissent`, `--operator-login`, and repeatable `--followup-issue`. The lower-level
collector keeps the default path unchanged unless those explicit inputs are present.

### The Advisory Settlement Record (posted comment)

One composed comment whose heading and exact-head grounding the canonical quorum parser recognizes
as a model-review advisory signal. It is not a supportive `would_count` review; it is deliberately a
negative-but-advisory review record that the `advisory_settle` path can see. It carries:

- head SHA + committed-at (exact-head binding; re-verified immediately before posting, as L1954).
- the supportive counting review(s) verbatim (as today).
- an **`Advisory dissent (non-blocking)`** section: each suppressed finding, its severity
  (`[P2]`/`[P3]`), source family, and a required **follow-up issue reference** (see below).
- provenance: `settled_by: <operator-login | review-adjudicator>`, flag state, policy version.
- an explicit machine-readable verdict line the gate keys on (e.g. `advisory_settle: eligible`).

### Follow-up preservation (value never lost)

Auto-file (or require `--followup-issue N`) a tracking issue per suppressed finding before the
record posts — the record links them. No advisory finding is silently dropped; this is the
severity-gated-dissent contract (#8574) made durable. (#8755 is the manual instance of this for #8730.)

### Idempotency & safety

- Exact-head bound: if head moved between collect and post, abort (reuse L1957-1965 recheck).
- Idempotent: if an Advisory Settlement Record for this head already exists, no-op.
- Fail-closed on any [P0]/[P1] → refuse, fall back to prepare-only, surface the blocker.
- `ARAGORA_DISABLE_GITHUB_APP_TOKEN=1` path honored for Tier-4 read-probe skew (existing).

## Files

- `aragora/swarm/quorum_evidence.py` — new `--post-advisory-dissent`-gated branch in the
  action decision (between L1942 dissent check and the supportive-only poster); new
  `compose_advisory_settlement_record()` composer; reuse severity classifier + evidence-lint.
- `scripts/collect_quorum_evidence.py` — CLI flag `--post-advisory-dissent` + `--followup-issue`.
- `scripts/settle_pr.py` — surface the flag; keep Tier 3-4 prepare-only invariant.
- `tests/swarm/test_quorum_evidence.py` — new cases (below).

## Acceptance

- Advisory-only dissent + ≥1 counting supportive at head + flag ON + Tier ≤2 →
  Advisory Settlement Record posts; `advisory_settle` computes eligible; gate settles.
- Any `[P0]`/`[P1]` present → refuses, prepares only, surfaces the blocker (byte-identical to today).
- Flag OFF (default) → behavior byte-identical to today (dissent ⇒ prepare-only).
- Tier 3-4 → never auto-posts; surfaces the record + `settle_tier4_pr.py` command.
- Every suppressed finding has a linked follow-up issue before the record posts.
- Unit coverage validates the composed record against the same advisory-settle signal parser the
  merge packet uses before this path is considered safe to post.

## Relationship to M0 (#8748)

M0a is the **posting primitive**; M0 is the **decider that drives it.** M0's adjudicator
(`ConvergenceDetector` + `EvidenceQualityAnalyzer`) decides *whether* dissent is thin, then calls
this same `compose_advisory_settlement_record()` path with `settled_by: review-adjudicator` and
the receipt attached. Building M0a first means: (a) the current queue unblocks immediately under
operator approval, and (b) M0 has a tested, audited emission path to target instead of inventing one.

## Out of scope

- The stall-detection / evidence-scoring logic itself (that is M0).
- Any change to `advisory_settle_eligible` gate semantics in `review_queue.py` (already correct).
- Tier 3-4 automation (permanently human by design).
