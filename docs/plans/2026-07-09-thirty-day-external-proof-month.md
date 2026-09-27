# Thirty-Day Plan: External-Proof Month (Jul 9 → Aug 9, 2026)

**Status:** ACTIVE
**Origin:** Seven-agent month audit (Jun 9 → Jul 9), 2026-07-09. Follows and composes with
`docs/plans/2026-07-08-vision-audit-and-work-mix-governor.md` (epic #9039).
**Thesis served every week:** signed, dissent-preserving, offline-verifiable Decision
Receipts. Focus-don't-amputate: this month's one dormant-engine integration is the
crux finder (ODR-4 #8227); blockchain stays staged at CP-4; marketplace/verticals
untouched.

---

## 1. The month verdict (measured, Jun 9 → Jul 9)

**Yes, the project got better — but lopsidedly.** Two independent measurements agree
on direction:

| Signal | H1 (Jun 9–23) | H2 (Jun 24–Jul 9) | Direction |
|---|---|---|---|
| Loop-machinery share of commits | 55.7% | 33.0% | halved ✅ |
| Product share of commits (runtime+proof) | 9.9% | 36.4% | 3.7× ✅ |
| Product share of merges (line-weighted instrument, weekly) | 14% → 19% | 20% → 30% | monotonic ✅ (target ≥50%) |
| scripts/ vs aragora/ commit touches | scripts-dominant | aragora/ leads | crossover ✅ |
| Open PR queue | 242 (crisis) | 63, 76% under 3d | −74% ✅ |
| Reverts on main | — | 0 in 488 commits | ✅ |
| Issues net | — | +209 (intake:closure 6.5:1) | ❌ |
| Remote branches | 489 after cleanup | 848 | ❌ regrown |
| Skip baseline | 62 | 77 (+24%, zero flake fixes) | ❌ |
| Mypy grandfathered errors | 3,115 | 3,115 (frozen) | ❌ flat |
| The 9 audit-flagged stuck product PRs | 9 open | 9 open | ❌ 0% moved |

**Shipped externally this month:** ODR schema (#8239), Ed25519 signing (#8542),
`aragora-verify` 0.1.0/0.1.1 on PyPI (Jun 29/Jul 4), executable compliance
walkthrough (#8802), dogfooding proof (#8801), `aragora` 2.9.0 (first release in 5
months), merge executor + harvest daemons armed, PR-keyed rerun budget armed
(#9056), work-mix instrument merged (#9047).

**Dimension scores (trajectory judge):** product delivery 5/10↑ · loop/settlement
health 6/10↑ · external proof 5/10↑ (from near-zero) · code quality/main health
6/10 mixed · strategic focus 7/10↑ · commercial readiness 4/10 flat.

**The binding risk:** the settlement bottleneck and the compliance deadline are the
same failure mode. The Aug 2 EU AI Act bundle and the outsider-run gate depend on
exactly the work the system has not settled: #8809 (key serving, ready since Jul 2),
#8230 (Art.14, untouched), signed production receipts, and one real human through
#8858. Loop throughput runs ~105 merges/week while the named product queue converted
at 0%.

## 2. Week-by-week

### W1 (Jul 9–16): "A (simulated) stranger verifies a signed production receipt"

> **Founder amendment (2026-07-10, formal replan; amended 2026-07-16 to a
> graduated ladder):** external exposure is gated by the ladder in
> [`docs/status/QUALITY_BAR.md`](../status/QUALITY_BAR.md) (founder assessment
> at decision time: ~4/10). Rung 0: adversarial **simulated stranger runs**
> (clean VM, public docs only, failures recorded before fixes) move the
> scores. Rung 1: a **founder cold-run** of the public path on a clean
> machine, uncoached, due **Jul 22**. Rung 2: the single diagnostic **#8858
> outsider run** — decision point **Jul 30** with the W3 bundle, gated only on
> the rung-1 result (zero blocking failures on the bounded path in <30 min),
> with any deferral recorded, named, and re-reviewed at each weekly digest.
> Rung 3: **broad outreach** stays behind the full ≥8/10 bar after founder
> rubric calibration. Simulated and founder runs never satisfy the
> external-artifact kill-switch metric.

- **Instrument outcome (amended):** first simulated stranger run executes the
  public quickstart and every receipt-verification path available to a clean
  environment, records whether a signed production receipt is actually
  obtainable, and converts each failure to an issue. The baseline run found
  the signing-key endpoint returning 404 and available receipts unsigned;
  signed production verification remains an unresolved W1 target, not a
  prerequisite for running the baseline instrument. #8858 stays open behind
  the ladder's rung-2 gate — bounded by the Jul 22 founder cold-run and the
  Jul 30 decision point, never deferred without a named blocker and a next
  review date.
- Merge #8809 (`/.well-known` signing-key endpoints; precondition). Enable Ed25519
  on production receipts (closes the #8801 "unsigned" limitation). Fix stranger-test
  frictions #8877, #7401. Close main-red #8930.
- Jul 11 (claude reviewer resets 3am CT): same-day drain of parked #9048 + #9058
  (batched follow-up findings in their park records), arm the nightly pristine-main
  halt-file, ledger begins daily records.
- #9044 round 1: disposition the 4 ready stuck PRs (#8406 Tier-4→founder, #8519,
  #8809, #8823).
- **Exit (amended):** simulated stranger-run artifact + failure issues filed;
  the remaining proof target is prod receipts signed + one verified offline;
  #8809/#9048/#9058 merged; ≥4/9 stuck PRs dispositioned (round 1 — the W2
  round-2 tail takes the cumulative count to ≥8/9); #8930 closed.
- **Founder:** calibrate the QUALITY_BAR.md rubric and run the rung-1 cold-run
  by **Jul 22** (replaces the outsider recruit; the cold-run is the readiness
  evidence for the Jul 30 #8858 decision); settle Tier-4 #8406; approve prod
  signing-key deployment; pentest vendor shortlist.

### W2 (Jul 16–23): "Human oversight is attestable — compliance chain complete"
- **External outcome:** #8230 (Art.14 human-oversight attestation) shipped: schema +
  receipt emission + evidence-pack CLI; walkthrough extended to Art.12/13/14.
- EU AI Act bundle assembled to 100% draft. Crux-finder integration phase 1
  (#8227 via #9046): crux detection into the receipt schema behind
  `enable_crux_cards`.
- #9044 round 2 (draft tail: #8652, #8766 demo-or-park before Jul 29 review, #9022,
  #9030, #9033). Quality ratchet starts: skip baseline shrink-only 77→72, mypy −100,
  HONEST_ASSESSMENT refreshed. Branch cleanup batch 2; `generate_boss_issues`
  throttled to product classes (fix the 6.5:1 intake ratio at the source).
- **Exit:** #8230 merged; bundle 100% draft; crux cards on dogfood debates; ≥8/9
  stuck dispositioned; branches <650; green-main streak ≥7d.
- **Founder:** first ledger-backed weekly digest review (30 min); pentest vendor
  pick + SOW request; Tier-4 preapproval for #8230 surfaces if needed.

### W3 (Jul 23–30): "Publish the bundle; flip the gate to enforcing"
- **External outcome:** EU AI Act GPAI/Art-50 bundle **published by Jul 30** (3-day
  buffer): signed prod receipt + verification artifact (founder cold-run per
  the QUALITY_BAR ladder; upgraded to the real outsider's artifact if the
  rung-2 gate clears at the Jul 30 decision point) + Art.14 pack +
  Rekor note. Close ODR-2 #8225 (PQC hybrid explicitly deferred with rationale).
- Jul 25: record T4 kill-switch proof; #8762 review Jul 29 (T2 re-scope if #8766
  didn't demo).
- **#9045 Phase-2 enforcing work-mix gate — entry criteria, all must hold:** 7
  green-main days under nightly halt-file; ≥14 days of ledger records; ≥6/9 stuck
  dispositioned; ≥10 days advisory with zero false halts; baseline measured. If not
  met: stay advisory, file the named gap — never force the flip.
- Crux cards phase 2 (receipt API + verifier rendering). Quality ratchet: skips
  72→68, mypy −100 more. **Crucible-hole demo build starts IF** bundle published AND
  trailing-week product share ≥40%.
- **Exit:** bundle live and linked; gate enforcing or dated blocker filed; #8762
  reviewed; crux cards in ≥1 published receipt.
- **Founder:** settle the gate-flip PR; sign pentest SOW (kickoff ≤ Aug 15);
  earned-claim review of the bundle; Jul 29 review.

### W4 (Jul 30–Aug 9): "Aug 2 passes live; the Crucible hole is demonstrably filled"
- **External outcome:** enterprise decision-brief demo artifact published — a real
  decision through Arena with signed dissent-preserving receipts + crux cards,
  **timed <10 min question→verified receipt**; positioned for Crucible-orphaned
  users (shutdown Aug 31) and the market-unique quorum merge gate.
- Close ODR-4 #8227 (crux cards default-on); epic #8223 closed except deferred PQC.
  Pentest kickoff. Phase-2 soak week 1. Backlog: branches <500, issue net-delta ≤0
  two weeks, open PRs ≤40 with zero ready >14d. Quality: skips ≤65, mypy ≤2,815,
  truth docs mutually consistent. IF green: scope (not start) the inbox-wedge
  web-GUI retest for next month.
- **Founder:** demo distribution decision (Crucible-orphan outreach), pentest
  kickoff, monthly budget re-tune.

**AMENDMENT 2026-07-28 — founder decision: the demo ships Variant B.**

"signed dissent-preserving receipts" above was written assuming production
signing. The production Ed25519 key lives in AWS Secrets Manager in the
suspended account (#9391), and the operator has stated reinstatement cannot be
resolved on the required timeline, so a production-signed demo receipt is not
reachable before Aug 9.

The founder has decided the W4 demo ships **Variant B** — the same contingency
the W3 bundle already uses: a real receipt signed with a locally generated
Ed25519 key, verifiable offline by the public `aragora-verify` package, carrying
an explicit dated statement that the local key is not the pinned production
identity and that production signing is blocked on #9391.

What this does and does not claim:

- **Proven:** the mechanism end-to-end — question → adversarial debate →
  dissent-preserving receipt with attributed cruxes → third-party offline
  verification, under 10 minutes. None of that depends on which key signed it,
  and it is the whole of the Crucible-orphan pitch.
- **Not proven:** issuer authenticity. A local key says the bytes are intact,
  not that Aragora vouched for them. The demo must not imply otherwise.
- **Upgrade path:** on reinstatement, re-sign the same ODR bytes with the
  production key. Signatures are detached, so the content digest does not
  change and the published artifact stays valid.

Rationale for deciding now rather than waiting: the alternative is contingent on
an event outside the team's control before a hard external date (Crucible
shuts down Aug 31), and the W3 bundle already established that a
locally-signed artifact with an honest gap statement is acceptable external
proof.

**Still gating W4 independently of this decision:** the trailing-week product
share must reach ≥40% (measured 28% on 2026-07-28, down from 33% earlier that
day as merge-tooling and crux-internals fixes landed as substrate), and the W3
bundle must be published, which needs the founder's earned-claim review.

## 3. Kill-switch metrics (weekly, from `.aragora/throughput/ledger.jsonl`)

1. **Product share of merges (7-day):** ≥40% ramping to ≥50%. Trip: <20% two
   consecutive weeks → substrate freeze, drain-only.
2. **External artifacts:** ≥1 per 14 days (W3 bundle → W4 demo → #8858
   outsider run when its rung-2 gate clears). **Simulated stranger runs and
   founder cold-runs are internal instruments and never count here** — an
   external artifact must be visible to or produced with someone outside the
   project. Trip: 0 in 30 days → demote to Phase 1 + human review.
3. **Settlement latency (ready→merged, Tier 0-2, p50):** ≤48h. Trip: >7 days →
   drain-only, no new feature PRs.

## 4. Mid-month replan triggers (any one forces a replan session, never a silent slip)

- ~~#8858 not done by **Jul 16** → W2 collapses to outsider-proof only.~~
  Superseded by the 2026-07-10 founder amendment (graduated 2026-07-16):
  #8858 is gated on the `docs/status/QUALITY_BAR.md` **rung-2 gate** with
  bounded dates. Replacement triggers: no simulated stranger run by **Jul 16**
  → W2 collapses to stranger-sim + quality-bar work only (satisfied by run 1,
  Jul 10). Founder cold-run not executed by **Jul 22** → the Jul 30 #8858
  decision point defaults to *deferred with the cold-run itself as the named
  blocker*, and the deferral question goes to the weekly digest — the date may
  slip only by recorded decision, never silently.
- #8230 not merged by **Jul 23** or bundle not 100% draft → W3 goes
  compliance-only; the demo dies for the month.
- Main red >24h → all lanes to repair; plan resumes at last checkpoint.
- Any kill-switch trip, or product share <20% in any single week after W1.
- Skip baseline rises again or mypy still 3,115 at Jul 23 → quality ratchet gets a
  dedicated lane at maintenance-budget (not product-budget) expense.
