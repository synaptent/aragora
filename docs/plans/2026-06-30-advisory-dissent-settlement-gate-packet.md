# Tier-4 Packet: Advisory-Dissent Settlement (unblock substantial new features)

**Status:** awaiting operator (human-risk) sign-off — this modifies merge-authority logic (Tier 4).
**Author:** Claude Code session 2026-06-30. **Owner sign-off required:** scarmani.

## Problem (structural, proven empirically)
The merge-quorum gate requires **2 supportive PASS verdicts** for Tier 1 (`tier_quorum_rule`,
`aragora/swarm/quorum_evidence.py:230`). Two thorough adversarial reviewers (claude, openai)
**can stall for rounds without both reaching PASS on substantial net-new code** — each surfacing a
fresh tail of *advisory* `[P2]/[P3]` robustness nits (often different ones each round). This is a
*bounded-stall risk*, **not** an absolute: a genuinely good PR does converge to a clean 2-0 after
real revisions — verified on #8730, which reached a clean claude+openai PASS after two fix rounds.
The failure mode is the *unbounded* case — a PR that keeps drawing disjoint advisory nits round
after round with **zero [P0]/[P1]** and `unresolved_dissent: false` (seen on #8389, 700-line ODR
verify engine: 3 rounds of disjoint claude/openai advisory sets). Net effect when it happens:
**a valuable feature can be held by advisory churn while trivial changes sail through** — backwards
for velocity *and* for shipping value. `--admin` does **not** bypass it (branch protection enforces
the check against admins), and Tier 1 has no human-settlement path. Clean 2-0 stays the preferred
path after real revisions; the settlement path below is the **bounded fallback** for a genuine
advisory-only stall, not a replacement for earning PASS.

## The change (staged)

### Phase 1 — enable the existing tiered gate (low risk; flag already implemented)
Set `ARAGORA_ENABLE_TIERED_MERGE_GATE: "1"` in `.github/workflows/aragora-merge-quorum.yml`
(alongside the already-enabled `ARAGORA_ENABLE_SEVERITY_GATED_DISSENT: "1"`). Effect:
`tier_quorum_rule` returns `required_signals=1, requires_western_frontier=True` for Tier 1-2
(`quorum_evidence.py:228-229`). A single claude/openai **PASS** settles Tier 1-2. Helps every
recovered feat that earns ≥1 western-frontier PASS. No code change.

### Phase 2 — count advisory-only western-frontier review as a settling signal (the real fix)
For PRs where reviewers nitpick endlessly (#8389: 0 PASS), Phase 1 is insufficient. Narrowly
extend the gate so a PR is settleable when **all** hold:
- all non-quorum required checks green;
- ≥1 **western-frontier** model review collected at the exact head;
- **zero [P0]/[P1] blocking findings** across all reviews (i.e. every CR is severity-gated
  advisory per `EvidenceItem.dissenting`, `quorum_evidence.py:437-452`);
- the advisory findings are **surfaced in the merge-packet (`advisory_findings`)** so a caller can file them as follow-ups (the gate itself does not create issues; wiring a caller is a separate step).

Change site: `tier_quorum_rule` / `TierQuorumRule.is_satisfied` (`quorum_evidence.py:162-208`) and
the packet builder `_build_merge_authorization_packet` (`aragora/cli/commands/review_queue.py:2908`).
Add an `advisory_settle` path: when the only thing missing is PASS verdicts but reviews exist with
no blocking findings, mark `status=satisfied, verdict=advisory_settle` and emit the follow-up issue.

## Risk + mitigations
- **Risk:** lowers the bar from "2 PASS" to "reviewed + no blocking findings + 1 western-frontier".
- **Mitigations:** still requires green CI; still requires a western-frontier reviewer; **still
  hard-blocks on any [P0]/[P1]**; advisory findings are not discarded (surfaced in the packet for a caller to file); applies to
  Tier 0-2 only (Tier 3-4 keep human settlement). Net: nothing crash-unsafe or incorrect merges;
  only *advisory robustness/style* nits stop being merge-blockers.
- This is a **merge-authority self-modification → Tier 4**; it must itself settle via human
  sign-off (this packet), not via the gate it changes.

## Test plan
- `tests/swarm/test_quorum_evidence.py` — add `advisory_settle` cases (advisory-only CR + 1
  western-frontier → satisfied; any [P0]/[P1] → still blocked).
- `tests/cli/commands/test_review_queue.py` — merge-packet emits `verdict=advisory_settle` +
  follow-up-issue payload only when no blocking findings.
- Regression: a PASS-based quorum still settles unchanged; Tier 3-4 unaffected.

## Immediate beneficiary
Unblocks the 19 recovered feats at once (esp. #8389, already hardened crash-safe with advisory
follow-ups in #8725) without per-PR nit-chasing — ends the treadmill, keeps the quality signal.
