# Archival Tier-4 Packet: ReviewAdjudicator quorum-stall path (#8748)

**Status:** ARCHIVAL / PREPARE-ONLY. This packet preserves the B5 design record from the
close-the-loop run (epic #8762). It is not a current implementation prompt: later work shipped
observe-only adjudicator recording, the Codex timeout-family freeze was released, and any packet
consumption remains Tier 4 merge-authority work requiring fresh exact-head human authorization.

## What already exists (verified on main, 2026-07-01)

- `aragora/swarm/review_adjudicator.py` (#8749, merged): pure, flag-gated
  (`ARAGORA_ENABLE_REVIEW_ADJUDICATOR`, default OFF) `adjudicate(items) ->
  SETTLE | BLOCK | ESCALATE | NOT_APPLICABLE`. Hard bar ([P0]/[P1]) evaluated without the
  scorer; single-scoring invariant; conservative bias (SETTLE only when *every* dissent is thin).
- `#8756` (open): M0a operator-approved advisory settlement records — the posting primitive.
- Advisory-settle reachability in the enforcing quorum job (#8741, merged).

## Proposed wiring (exact, for the human to preapprove)

1. **Call site A — `aragora/swarm/quorum_evidence.py`** (historically frozen during this run): in the
   outcome-aggregation step where the collector concludes `action=prepare` with
   `dissenting_families` non-empty AND `supportive_families` non-empty (the stall shape observed
   live on #8389 round-2: claude PASS / openai CHANGES-REQUESTED), call
   `review_adjudicator.adjudicate()` over the reviewer findings when the flag is ON. Record the
   `AdjudicationResult` in the collect outcome JSON (`adjudication` key). This observe-only shape
   is now represented on main; do not treat this packet as permission to change merge behavior.
2. **Call site B — `aragora/cli/commands/review_queue.py` merge-packet** (Tier 4 self-arbiter
   surface): map a recorded `adjudication.verdict == SETTLE` on the exact head SHA to a new
   packet verdict `adjudicated_settle` that satisfies Tier 1-2 settlement *only when* the
   existing advisory_settle_surface_clear predicate also holds. `BLOCK`/`ESCALATE` never weaken
   anything: they add reasons.
   Any future packet-consuming implementation must additionally bind the adjudication to the exact
   PR head, counted reviewer families, and current merge-packet input; must fail closed when the
   recorded adjudication is stale or from an untrusted source; and must preserve the operator/
   creator trust boundary for any settlement status that affects merge authorization.
3. **Receipt**: every adjudication emits a DecisionReceipt (ConsensusBuilder) naming suppressed
   findings + severities; suppressed advisory findings are auto-filed as follow-up issues
   (compose the same WIP-capped filing used by the harvest engine #8760).

## Rollout preconditions (all must hold before implementation)

1. Fresh human Tier-4 preapproval recorded for the current head and current design; this archival
   packet alone is not enough.
2. Live owner/steering check confirms no concurrent edits to `quorum_evidence.py` or
   `review_queue.py`.
3. Step-1 (observe-only) ships first and runs on ≥3 real stalls with the operator eyeballing the
   `adjudication` outputs before step-2 (packet consumption) is enabled.
4. Governance tests in `tests/governance/` pin: flag OFF → byte-identical packet output; [P0]/[P1]
   present → never `adjudicated_settle`; ESCALATE → packet gains a human-crux reason.
5. Packet-consumption tests pin exact-head binding, stale-adjudication rejection, trusted-creator
   recognition, receipt/status audit linkage, and fail-closed behavior whenever quorum remains red
   or the adjudication cannot be tied to the live merge packet.

## Live evidence motivating this (from the run)

- #8389: two full gate cycles; round-2 claude PASS / openai new [P1] — a genuine hard-bar case
  (adjudicator would correctly BLOCK; the [P1] is real, filed as #8765).
- #8519: openai [P2] contradicting an intentional characterization test — a genuine ESCALATE
  case (material two-sided disagreement; human crux).
- #8460: clean 2-0 after evidence — NOT_APPLICABLE case (no stall).
The three verdict classes all occurred naturally within one drain wave, which is strong evidence
the adjudicator's taxonomy carves the space correctly.
