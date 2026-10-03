# Quality Bar — the graduated gate for external human proof

**Founder decision (2026-07-10, amended 2026-07-16):** external exposure is
gated by the **ladder** below, not by a single all-or-nothing bar. Founder's
holistic assessment at decision time: **~4/10**. The original decision ("no
external human until ≥8/10 on all dimensions") is retained for **broad
outreach** (rung 3) and bounded for the **single diagnostic outsider run**
(rung 2), which gets its own smaller gate and a decision cadence instead of an
open-ended block.

Rationale: a real stranger's first impression is a scarce resource, and the
project should not spend one on a 4/10 experience. The counterweights
(recorded so they are not forgotten): internal scores drift optimistic, so
every dimension is tied to a repeatable instrument, not a self-assessment;
simulated runs must stay adversarial (the runner's incentive is to find
failures, not to succeed); **and an ungated deferral is itself a known failure
mode** — the measured work-mix history (52% substrate / 8% product, 0/9
product PRs settled in Jun 9–Jul 9) shows this project defaults to internal
work whenever external contact lacks a date. Strangers are also not strictly
one-shot: each new outsider is an independent sample; what is unrepeatable is
a *specific* person's first contact, not first contact itself.

## The ladder

| Rung | Instrument | Gates | Trigger / date |
|------|-----------|-------|----------------|
| 0 | **Agent stranger-sim** (clean VM, public docs only, adversarial persona, failures recorded before fixes) | Nothing — it is the score-moving instrument for dims 1–3, 8 | Repeatable, any time |
| 1 | **Founder cold-run**: the founder personally executes the public path (pip install → demo → signed-prod-receipt verify) on a clean machine, public docs only, uncoached, timed, every failure recorded before any fix | Rung 2 | **By Jul 22** (before W3) |
| 2 | **One bounded outsider run (#8858)**: a single uncoached human, the bounded verify path only, observer records frictions | Nothing downstream — it is diagnostic | **Decision point Jul 30** (with the W3 bundle): runs if rung 1 completed with **zero blocking failures** on the bounded path in <30 min; otherwise deferred by a *recorded decision naming the blocking failures*, re-reviewed at every weekly digest — never silently, never indefinitely |
| 3 | **Broad outreach / promotion / formal external review / design-partner recruiting** | — | **≥8/10 on all dimensions below**, after founder rubric calibration |

Notes on rung 1: the founder is a contributor and does **not** satisfy #8858's
acceptance ("do not use a contributor already familiar with the repo") — but a
founder who has never personally exercised the public install path is the
closest available human proxy, strictly better evidence than an agent sim, and
the natural authority on whether the experience is good enough to spend a
stranger on. Rung 1's artifact lands in `docs/artifacts/` like any other run.

**Recorded deferrals (operator decision, 2026-07-16):** production
(api.aragora.ai) is offline pending an AWS billing resolution. Consequently:
(1) the **Jul 22 founder cold-run executes the offline bounded path only**
(`pip install` → `aragora demo --offline --receipt` → `aragora receipt verify`)
— this still satisfies rung 1, whose gate for the Jul 30 decision is "zero
blocking failures on the bounded path"; (2) the **dimension-4 instrument
(fresh production receipt) and the W1 founder-MFA prod receipt are deferred**
with the blocking failure named: AWS account suspension (billing). Per the
ladder's own rule this deferral is re-reviewed at every weekly digest — never
silently, never indefinitely. Restoration plan and cost diagnosis are tracked
in the AWS billing support case (operator-side) and the Jul 16 run log.

**Kill-switch integrity:** simulated runs (rung 0) and founder cold-runs
(rung 1) are *internal* evidence. They never satisfy the 30-day plan's
"external artifacts ≥1 per 14 days" metric. Only genuinely external artifacts
count: the published W3 bundle, a real outsider's run, a design-partner
session.

Scores are updated only with a fresh instrument run linked in the row.
Baseline scores anchor to the 2026-06-12 codebase-health audit
(`docs/audits/2026-06-12-codebase-health-audit.md`) and to measured settlement
telemetry from 2026-07-09/10. **The ≥8/10 bar (rung 3) becomes binding only
after the founder calibrates the rubric** — assessor, per-dimension evidence
requirements, and re-score cadence (weekly digest) are frozen at calibration
time; until then the bar is advisory and rung 2's smaller gate governs.

| # | Dimension | Instrument (repeatable) | Baseline | Target (what 8 means) |
|---|-----------|-------------------------|---------|------------------------|
| 1 | First-hour stranger experience | Simulated stranger run: clean VM, README/quickstart only, time-to-first-verified-receipt + failure count | **6** ([run 1, 2026-07-10](../artifacts/2026-07-10-stranger-sim-run-1.md)) | 8: zero blocking failures; verified receipt in <15 min; no undocumented step |
| 2 | Packaging & install truthfulness | `pip install aragora` → `aragora demo --offline --receipt` → `aragora receipt verify` on clean env; INSTALL.md vs pyproject consistency diff | **5** ([run 1](../artifacts/2026-07-10-stranger-sim-run-1.md)) | 8: round trip green on macOS+Linux clean envs; zero doc/pyproject contradictions |
| 3 | Docs coherence / single positioning | Docs-consistency CI + positioning-drift scan (README / WHY_ARAGORA / COMMERCIAL_OVERVIEW / EXTENDED_README / CLAUDE.md) | **4** ([run 1](../artifacts/2026-07-10-stranger-sim-run-1.md): 3 verify surfaces, 3 stories) | 8: one canonical positioning; zero contradictory capability or metric claims |
| 4 | Receipt verifiability end-to-end | Fresh production receipt → `aragora-verify` offline, including signature (needs #8809 signing path) | ~5 (unsigned prod receipts) | 8: signed prod receipt verifies offline incl. issuer authenticity, documented key rotation |
| 5 | Settlement signal integrity | Quorum family counting rate; fake-failure (cancellation) incidents/week; `DOES NOT count ()` occurrences | ~4 (claude family invisible; ~6 cancel incidents in one session) | 8: all configured families count when they review; <1 unexplained terminal-cancel/week (#9129, #9133) |
| 6 | Macro-architecture | Import-cycle ratchet count; `aragora.server` imported-by count (shrink-only baselines) | 4 (audit) | 8: cycles <30; server imported-by ≤5; no new layering violations for 30 days |
| 7 | Test trustworthiness | Shard-pollution incidents/week on PR CI; randomized-order lane green streak | ~5 (known pollution class blocking PRs) | 8: zero passes-alone-fails-in-shard incidents in 14 days; randomized lane green |
| 8 | Core workflow utility | `aragora review-pr` / `gauntlet` / `ask` succeed with ONE provider key on a clean env, useful output, no crash | ~5 | 8: all three green on clean env; outputs judged useful in the weekly digest review |

## Operating consequences

- The 30-day plan's W1 exit criterion "#8858 artifact w/ named human" and the
  Jul 16 replan trigger are **replaced by the ladder above** (amended in the
  same PR as this doc): W1's gate became the first simulated stranger run
  (done, [run 1](../artifacts/2026-07-10-stranger-sim-run-1.md)) with its
  failure list converted to issues; the founder cold-run is due **Jul 22**;
  the #8858 outsider decision point is **Jul 30**, gated only on the rung-1
  result — not on the full ≥8/10 bar.
- The EU AI Act bundle (W3, Jul 30) does **not** depend on the outsider run
  and keeps its date.
- Dimensions 5–7 are already in flight (#9129, #9133, swarm-status salvage,
  existing ratchets). Dimensions 1–3 and 8 are the gap: they are product/docs
  work the work-mix governor should prefer — and they are exactly what the
  founder cold-run measures.
- The ≥8/10 bar governs **broad external exposure** (rung 3). It does not gate
  internal dogfooding, receipts, the compliance bundle, or the single
  diagnostic outsider run (rung 2, which has its own smaller gate).
- Every deferral at a decision point is a recorded decision naming the
  blocking failures, revisited at the next weekly digest. There is no state in
  which external contact is blocked without a named blocker and a next review
  date.
