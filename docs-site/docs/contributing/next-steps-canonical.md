---
title: Next Steps (Canonical)
description: Next Steps (Canonical)
---

# Next Steps (Canonical)

Last updated: 2026-07-20

This is the single source of truth for short-horizon execution priorities.
[CANONICAL_GOALS](./canonical-goals) defines what Aragora is and why.
[ARAGORA_EVOLUTION_ROADMAP](./aragora-evolution-roadmap) defines the multi-stage architecture.
[ACTIVE_EXECUTION_ISSUES](./active-execution-issues) holds the epic/milestone/issue tree.
[COMMERCIAL_OVERVIEW](../enterprise/commercial-overview) translates proof into market language.

## Current Gate

**The live execution spine is the Open Decision Receipt (ODR) tranche — ODR-1..7, epic [#8223](https://github.com/synaptent/aragora/issues/8223)** — adopted 2026-06-11 in [FEATURE_GAP_LIST — Active Direction](./feature-gap-list#active-direction--open-decision-receipt-odr-june-2026). That pivot supersedes the earlier framing of this section, which named the Foreman/`B0` proof loop as the sole gate. The Foreman/`B0` obligations are not cancelled: they are held open in the background (see the subsection below) and must not regress, but they are maintenance truth, not the execution priority.

ODR tranche state (checked 2026-07-20):

| Code | Issue | State as of 2026-07-20 |
|------|-------|------------------------|
| ODR-1 vendor-neutral receipt content profile (JSON Schema + JCS) | [#8224](https://github.com/synaptent/aragora/issues/8224) | Closed (schema shipped via [#8239](https://github.com/synaptent/aragora/pull/8239)) |
| ODR-2 Ed25519 public-key signing for DecisionReceipts | [#8225](https://github.com/synaptent/aragora/issues/8225) | Open — signing shipped ([#8542](https://github.com/synaptent/aragora/pull/8542)); close targeted with the W3 bundle by Jul 30, PQC hybrid explicitly deferred |
| ODR-3 `aragora-verify` offline verifier (PyPI) + `/api/receipts/verify` | [#8226](https://github.com/synaptent/aragora/issues/8226) | Closed (`aragora-verify` 0.1.x published on PyPI) |
| ODR-4 expose the crux finder (API, CLI, SDK, crux set in receipts) | [#8227](https://github.com/synaptent/aragora/issues/8227) | Open — crux cards phase 1 merged behind `enable_crux_cards` ([#9414](https://github.com/synaptent/aragora/pull/9414)); default-on targeted for W4 |
| ODR-5 calibration report API + calibrated confidence in receipts | [#8229](https://github.com/synaptent/aragora/issues/8229) | Closed |
| ODR-6 human-oversight attestation + EU AI Act Art.14 / NIST evidence pack | [#8230](https://github.com/synaptent/aragora/issues/8230) | Open — Art.14 attestation + oversight-pack generator merged ([#9417](https://github.com/synaptent/aragora/pull/9417)) |
| ODR-7 Sigstore Rekor public anchoring | [#8231](https://github.com/synaptent/aragora/issues/8231) | Closed |

`aragora review` now emits ODR receipts on `main` ([#9343](https://github.com/synaptent/aragora/pull/9343)).

**The dated near-term gate is the thirty-day external-proof month (Jul 9 → Aug 9), [2026-07-09-thirty-day-external-proof-month](../plans/2026-07-09-thirty-day-external-proof-month.md) (plan merged as [#9061](https://github.com/synaptent/aragora/pull/9061)).** As of 2026-07-20 the W2 external outcomes (Art.14 attestation [#9417](https://github.com/synaptent/aragora/pull/9417), crux cards phase 1 [#9414](https://github.com/synaptent/aragora/pull/9414)) are merged, and the live gate is **W3 (Jul 23–30): publish the EU AI Act GPAI/Art-50 bundle by Jul 30** (signed prod receipt + verification artifact + Art.14 pack + Rekor note), close ODR-2 [#8225](https://github.com/synaptent/aragora/issues/8225), and flip the work-mix gate to enforcing only if its entry criteria hold. W4 targets the enterprise decision-brief demo and closing ODR-4, after which epic [#8223](https://github.com/synaptent/aragora/issues/8223) closes except deferred PQC. External exposure remains gated by the [QUALITY_BAR](QUALITY_BAR.md) ladder.

Stage-Gate Conductor rule: ODR / m6 / external-proof-month work **is execution against the current gate, not drift**. Foreman-substrate work remains in scope only as "keep the proof loop truthful" maintenance under the background subsection below.

Stage-Gate Conductor logging rule (**binding**): the recurring run log MUST be posted with
`python scripts/stage_gate_drift.py log --repo synaptent/aragora --month YYYY-MM --body-file <summary> --apply`,
which appends a comment to the single rolling monthly anchor `[automation] Stage-Gate Conductor Log (YYYY-MM)`.
Never open the run log with a bare `gh issue create`. Drift findings go through
`stage_gate_drift.py file --fingerprint <slug>`, which comments on the existing anchor for that finding class
instead of opening a near-duplicate each cycle. Rationale: between 2026-04-17 and 2026-07-27 the Conductor
opened **41 issues carrying the byte-identical title** `[automation] Stage-Gate Conductor Log`, because it
called `gh issue create` directly and never used the dedup helper — which had already been written and tested
for exactly this failure (see #9490). Those 41 were closed down to one anchor in the 2026-07-29 triage pass.

### Held open in the background — proof-loop must not regress (formerly the sole gate)

The standing background obligation is operating the proof loop that already exists: keep recurring benchmark truth publication complete, fresh, and trustworthy on current `main`; keep `CS-01..03` narrower than measured proof; and do not expand the `B2` guard until repeated runs support it. The execution epics [#804](https://github.com/synaptent/aragora/issues/804), [#805](https://github.com/synaptent/aragora/issues/805), and [#806](https://github.com/synaptent/aragora/issues/806) are closed; the background obligation is operationalizing the proof-first loop, not adding new roadmap scope.

Current proof-loop state for `CS-01..03` reconciliation is delegated to the live recurring `B0`/`TW-03` proof surfaces:

- `docs/THESIS.md` is v4 canonical.
- H1-01 rev-4 was promoted into the canonical corpus and rev-5 now graduates the first five strict linked successes.
- `docs/status/B0_BENCHMARK_TRUTH_STATUS.md` and `docs/status/TW03_RESCUE_PRODUCTIZATION_STATUS.md` are the live measured proof surfaces. Do not copy volatile percentages into this file; require those surfaces to be fresh, complete for their current corpus/ledger window, and no broader than current proof before expanding `CS-01..03` or the `B2` guard.
- The remaining Sprint 2 outreach proof gate now has product-scope frontier evidence: Claude reviewed SDK websocket PR [#7513](https://github.com/synaptent/aragora/pull/7513) at exact head `6531ebad2968ae9e2888f08ba237473c41eb0e21`, preserved unmodified in [the PR comment](https://github.com/synaptent/aragora/pull/7513#issuecomment-4567004963), and approved with non-blocking follow-ups. This satisfies the frontier/adversarial-review evidence gate; actual outreach remains an operator decision.
- The first settlement receipt exists for `#7060`, and `review-queue observe-outcomes --window-days 14 --max-receipts 5 --json` dry-runs over it successfully with all five v2 outcome signals false and no receipt JSON writes.
- The first `observe-outcomes --write` remains a separate Tier-4 operator decision over a bounded manually verifiable receipt slice.

Operator commands only count as proof when they are run from a clean, current `origin/main` observer. A dirty or diverged founder checkout is planning context, not runtime truth.

### Governance-substrate freeze (promoted from Sprint 2 anti-goals)

Treat process tooling as saturated. Do **not** open new review-queue,
settlement, merge-quorum, or steering meta-tooling work unless it either
(a) directly unblocks B0 truth, external receipt proof, or the non-operator
demo/product-proof path, **or** (b) explicitly closes or supersedes an
existing open PR in the same surface. This rule is enforced operationally
by the Sprint 2 anti-goals in [FOCUS.md](../FOCUS.md); it is recorded here
because it outlives any single sprint window. Post-saturation process work
is the dominant form of substrate-overbuild — every new PR in
`aragora/cli/commands/review_queue.py`, `scripts/settle_*.py`,
`scripts/*steering*.py`, or `.github/workflows/aragora-*-quorum.yml` must
name the load-bearing target it advances or the open PR it net-closes, or
stand down.

### Model-quorum evidence is exact-head and countable, or it does not exist

A model-review signal only counts toward `aragora-merge-quorum` when it is
posted as an **exact-head PR comment** that the `review-queue merge-packet`
parsers can read: a family-named first heading, a head-SHA citation
(>= 7 chars), and a review/dogfood trigger phrase. Advisory
`review-pr --no-publish-review` artifacts are persisted but **not** counted,
and a *published* `review-pr` GitHub review object is also not counted
(merge-packet fetches issue `comments`, not `reviews`, and the
`## Aragora review-pr:` heading resolves to `unknown_model_reviewer`).
Reaching quorum therefore requires genuinely distinct model **lineages** —
router/product markers such as `codex` or `factory` do not count as separate
families. The Tier 4 recognizable-header pre-approval
[#7472](https://github.com/synaptent/aragora/pull/7472) and its lineage-counting
implementation [#7561](https://github.com/synaptent/aragora/pull/7561) are both
merged. Current evidence must disclose its model family and pass
`review-queue evidence-lint` for the exact PR head; an uncountable signal with
no diagnostic reason is a tooling defect to investigate, not permission to
hand-fabricate evidence or bypass the human merge gate.

### `B2` guard expansion criteria

`B2` stays closed by default. Do not widen it based on a single green anecdote or a one-off publish.

Treat "repeated bounded runs" as **at least 3 consecutive weekly green corpus runs on current `main`**. For this gate, a weekly run is green only when all of the following remain true:

- `docs/status/B0_BENCHMARK_TRUTH_STATUS.md` is fresh for the current corpus revision and reports complete coverage for that revision
- `docs/status/TW03_RESCUE_PRODUCTIZATION_STATUS.md` is fresh and reports `0` repeated rescue classes in the current ledger window
- the recurring publication completed on current `main` without gaps that would make the proof surface incomplete, stale, or misleading

If any weekly run is missing, incomplete, stale, or introduces a repeated rescue-class regression, reset the count and keep `B2` closed.

The only execution classes currently safe enough for `B2` guard consideration are:

- dependency bumps with bounded surface area and existing validation already in the repo
- config changes that are additive, reversible, and stay inside already-proven live paths
- fail-closed fixes that narrow unsafe behavior without widening execution scope

Meeting the 3-run gate only permits guarded expansion inside those three classes. It does not permit broader scope widening, new product surfaces, or speculative autonomy work.

What is already true:

- boss, supervisor, tranche, and swarm infrastructure exist
- host-side install and preflight scripts exist
- bounded product wedges such as prompt-to-spec and inbox workflows exist
- the approved reliability substrate spec identifies the missing layer clearly
- terminal-truth taxonomy, benchmark fixtures, and the benchmark scoring lane are now on `main`
- the recurring B0 benchmark truth surface is repo-tracked at `docs/status/B0_BENCHMARK_TRUTH_STATUS.md`; operator decisions should read the live published surface there instead of hardcoding percentages in this document
- `WorkerContract` and `CredentialEnvelope` primitives exist on the live swarm path
- launcher-side contract admission, dispatch gating, and module-level contract-aware preflight are on `main`
- receipt-backed preflight is now the default operator and live dispatch admission truth on `main` via [#5514](https://github.com/synaptent/aragora/pull/5514)
- scratch and remote-publish preflight validation now run through the production preflight path and emit canonical terminal truth on `main`
- task sanitizer outcomes and success-rate filtering are shaping safer boss-loop intake
- original versus sanitized task text is already preserved for audit on `main`
- session state now persists across the live supervisor lease/dispatch lifecycle on `main` via [#5503](https://github.com/synaptent/aragora/pull/5503)
- retry dispatch now carries prior session resume context on `main` via [#5384](https://github.com/synaptent/aragora/pull/5384)
- failed and `needs_human` lanes now persist normalized `blocker_evidence` on `main` via [#5512](https://github.com/synaptent/aragora/pull/5512)
- the rescue loop can now record interventions, plan bounded recovery, and execute safe followups on `main` via [#5379](https://github.com/synaptent/aragora/pull/5379), [#5380](https://github.com/synaptent/aragora/pull/5380), and [#5383](https://github.com/synaptent/aragora/pull/5383)
- recurring benchmark scorecards are now bound to the frozen corpus revision on `main` via [#5582](https://github.com/synaptent/aragora/pull/5582) and [#5583](https://github.com/synaptent/aragora/pull/5583)
- repo-tracked recurring truth publication now lands in `docs/status/generated/benchmark_truth_artifacts/` and `docs/status/generated/benchmark_scorecards/`, with the stable status summary at `docs/status/B0_BENCHMARK_TRUTH_STATUS.md`
- repeated rescue-class reports now include fixture-or-issue productization status on `main` via [#5535](https://github.com/synaptent/aragora/pull/5535)
- repo-tracked recurring rescue productization now lands in `docs/status/generated/rescue_productization/`, with the stable status summary at `docs/status/TW03_RESCUE_PRODUCTIZATION_STATUS.md`
- the recurring `TW-03` harvest can now relink repeated rescue classes to tracked fixture/issue targets and auto-create bounded follow-on issues when a repeated class is still unlinked
- proof-first runtime truth is now persisted in `ShiftLedger` on `main` via [#5857](https://github.com/synaptent/aragora/pull/5857)
- proof-first shifts now fail closed after repeated recovery failures for the implemented failure classes via [#5867](https://github.com/synaptent/aragora/pull/5867)
- `swarm status`, FastAPI swarm-status routes, and `studio-health.sh` now prefer ledger-backed operator truth on `main` via [#5861](https://github.com/synaptent/aragora/pull/5861) and [#5868](https://github.com/synaptent/aragora/pull/5868)
- the future Decision Integrity expansion is now tracked as an additive Epistemic CI / Crux Engine / Epistemic Runtime tranche in [EPISTEMIC_CI_AND_CRUX_ENGINE](../plans/EPISTEMIC_CI_AND_CRUX_ENGINE.md) and issues [#6023](https://github.com/synaptent/aragora/issues/6023)-[#6028](https://github.com/synaptent/aragora/issues/6028) plus [#6030](https://github.com/synaptent/aragora/issues/6030)-[#6033](https://github.com/synaptent/aragora/issues/6033); it is planning truth, not current live queue scope
- the Dialectical Runtime synthesis layer (DIC-23..28) is tracked as an additive extension of the same tranche in [2026-04-18-dialectical-runtime-synthesis](../plans/2026-04-18-dialectical-runtime-synthesis.md); it is planning truth only, activation-gated on DIC-20/21/22 production-green, and no issues under it may carry `boss-ready` until the proof-first Foreman gate opens — with one carve-out: public exposure of the crux finder now proceeds under ODR-4 [#8227](https://github.com/synaptent/aragora/issues/8227) as part of the current gate
- the thesis-aligned full-horizon roadmap (Phase 0 H1 closure → Phase 1 LBA tests → Phase 2 H2 design-partner wedge → Phase 3 H3 non-software wedge → Phase 4 marketplace + receipt-tier monetization → Phase 5 organization substrate) is captured in [2026-04-25-aragora-next-steps-roadmap-aligned-to-thesis](../plans/2026-04-25-aragora-next-steps-roadmap-aligned-to-thesis.md); **only Phase 0 is canonical / on the live queue from that roadmap** — it is the four named Implementation gaps already in `docs/THESIS.md` (#6372, #6373, #6374, #6375). Phases 1–5 are planning truth only, gated on Phase 0 closure plus the proof-first Foreman gate, and no issue under those phases may carry `boss-ready` until that gate opens. (Since 2026-06-11 the ODR tranche in the Current Gate section above is the live execution priority alongside this.)

What is still missing:

- proof that operator status surfaces remain truthful when observed from a clean current-`main` checkout instead of a dirty founder checkout
- proof that the B2 guard holds under repeated bounded runs instead of one-off success stories
- proof that recurring benchmark publication stays complete and fresh on `main` without operator babysitting
- broader repair-loop coverage on top of the existing audit trail
- lower-rescue unattended operation on bounded backlogs
- ongoing discipline so actual external outreach stays no broader than the recurring proof surfaces and the preserved frontier-review evidence
- delayed decision-integrity work that turns important claims into executable evidence-linked objects and debates into ranked `CruxSet` outputs, after the proof-first Foreman gate is stable

For this background lane, the work is not “add more speculative autonomy.” It is “make bounded unattended execution boring.” The forward-execution work happens in the ODR tranche above.

Queue rule for this background tranche:

- only roadmap codes in the **Do now** set may carry or be auto-created with `boss-ready`
- delayed-track issues may stay open for planning truth, but restock and auto-decomposition should strip them from the live dispatch queue

Observer rule for this tranche:

- run `swarm shift-status`, `swarm status`, benchmark publication, and operator proofs from a clean worktree reconciled to current `origin/main`
- treat a dirty or diverged root checkout as non-authoritative for runtime truth, even when it is useful for local founder notes or in-flight security work
- if the observer reports itself as dirty, ahead, or behind, fix the observer before widening roadmap scope or restocking the live queue

## 30-Day Success Metric

The current dated 30-day frame is the external-proof month (Jul 9 → Aug 9) in [2026-07-09-thirty-day-external-proof-month](../plans/2026-07-09-thirty-day-external-proof-month.md), including its weekly kill-switch metrics. The metric below is the standing Foreman/proof-loop target that predates it and remains the background truth bar:

- fixed benchmark corpus of bounded issues
- context-enriched workers complete **>=50%** of that corpus without human rescue
- **100%** of failures land in truthful canonical buckets
- repeated rescue classes become explicit product work

Current status: `docs/status/B0_BENCHMARK_TRUTH_STATUS.md` and `docs/status/TW03_RESCUE_PRODUCTIZATION_STATUS.md` are the live recurring proof surfaces. When benchmark publication drifts, lags, or lands incomplete corpus coverage, restoring that publication becomes the immediate gate again before any scope widening.

Primary truth metric:

- issue-level truth success remains `mergeable_pr OR merged_pr`
- merged-only rate is a secondary truth metric, not the primary gate
- PR-signal counts and iteration counts are proxies only

If a task does not improve that metric, it is not first-tranche work.

## TW-01/TW-02: Benchmark Corpus and No-Rescue Scorecard ([#5329](https://github.com/synaptent/aragora/issues/5329))

`TW-01` (fixed benchmark corpus) and `TW-02` (no-rescue scorecard) are the measurement backbone for the execution wedge. Without them, progress claims are anecdotal.

### Benchmark corpus requirements (TW-01)

- The corpus is a fixed, versioned list of bounded issues checked into the repo (e.g. `docs/benchmarks/corpus.json`).
- Issues in the corpus are not swapped ad hoc between runs; additions and removals are tracked as explicit corpus revisions.
- Each corpus entry includes: issue identifier, expected execution class, and any known constraints.
- The corpus runs against current `main` on a recurring basis (at minimum weekly) using the existing benchmark scoring lane.
- Corpus membership criteria: issues must be bounded (clear scope, single-PR resolution, no external dependency chain).

### No-rescue scorecard requirements (TW-02)

The recurring scorecard records the following per corpus run:

| Metric | Definition | Primary or proxy |
|--------|-----------|-----------------|
| Truth success rate | `mergeable_pr OR merged_pr` per issue | **primary** |
| No-rescue success rate | Truth successes with zero human intervention | **primary** |
| Verification pass rate | Fraction of runs where `verify` stage passes without repair | secondary |
| Failure-class distribution | Count of failures per canonical terminal-truth class | secondary |
| Merged-only rate | Fraction where the PR is actually merged (not just mergeable) | secondary |
| Rescue count | Number of runs requiring human intervention, broken out by rescue type | secondary |

Scorecard output rules:

- Each run produces a timestamped scorecard artifact that is diffable against prior runs for week-over-week comparison.
- Human rescue is distinguished from autonomous completion at the issue level — a rescued issue is never counted as no-rescue success.
- Proxy metrics (PR count, iteration count, token spend) are reported separately and never mixed with truth metrics.
- The scorecard links back to the corpus revision it was run against.

### Current state

- Terminal-truth taxonomy, benchmark fixtures, and the benchmark scoring lane are on `main`.
- The latest recurring benchmark status must be read from `docs/status/B0_BENCHMARK_TRUTH_STATUS.md`, not copied into this document as a hardcoded percentage.
- The frozen corpus manifest now lives at `docs/benchmarks/corpus.json`.
- The diffable truth artifact path is `scripts/build_benchmark_truth_artifact.py`, with GitHub-truth reconciliation provided by `scripts/reconcile_b0_pr_truth.py`.
- The stable recurring status surface is `docs/status/B0_BENCHMARK_TRUTH_STATUS.md`, backed by the latest JSON pointers under `docs/status/generated/benchmark_truth_artifacts/` and `docs/status/generated/benchmark_scorecards/`.

## 30-Day Canonical Backlog

This is the executable backlog for the next 30 days. Keep it to one bounded lane at a time for a founder budget of 5-10 hours per week.

| Order | Code | Why it matters to the wedge | Acceptance criteria | Proof metric | Layer | GitHub coverage |
|---|---|---|---|---|---|---|
| 1 | `CS-01..03` | The wedge fails commercially if external claims outrun measured proof. | Roadmap, status, and positioning docs keep the wedge-first story and gate claims on measured proof. | External-facing docs stay narrower than current truth metrics and current gate status. | trust | Epics #804 and #806 are closed; enforcement is now via proof-first queue governance and recurring publication surfaces. |
| 2 | Observer truth | Runtime truth is not credible if it is read from a dirty or stale checkout. | `swarm shift-status` and sibling operator surfaces report whether the observer itself is dirty, ahead, or behind `origin/main`. | Operators can distinguish product regressions from bad observer state without shell forensics. | trust | Implement on live status surfaces before widening proof-first queue scope. |

## Do Now / Delay / Avoid

### Do now

- ODR tranche closure per the external-proof month plan: ODR-2 ([#8225](https://github.com/synaptent/aragora/issues/8225)), ODR-4 ([#8227](https://github.com/synaptent/aragora/issues/8227)), ODR-6 ([#8230](https://github.com/synaptent/aragora/issues/8230))
- EU AI Act GPAI/Art-50 bundle published by Jul 30 (W3 gate)
- `CS-01..03` (background)
- observer truth on current `main` (background)
- benchmark publication freshness and completeness (background)

### Delay

- `BC-07..09` until the repair loop is truthful, resumable, and consolidated into one operator model
- `RS-11..12` until recovery-budget coverage extends to the remaining failure classes and the remaining status/reporter surfaces are ledger-backed
- `DIC-13..22` until BC-12/Foreman reliability is proven; Epistemic CI, Crux Engine, and Epistemic Runtime issues may stay open for planning but must not enter the live boss-ready queue
- `AGT-01..06` until the proof-first Foreman gate permits the upper-layer tranche; agent-civilization substrate, A2A consumer surface, prediction-market validation, skin-in-the-game reputation flow, and the productivity metric (VIAH) replacing empty-queue idle soaks may stay open for planning but must not enter the live boss-ready queue
- `TW-07..09` until the bounded execution wedge is boringly reliable
- `UDW-01..06` except for thin read-only queue, receipt, lineage, replay, retry, pause, resume, and override views backed by live runtime truth
- `MCF-01..03` until the wedge needs permissioned memory to improve bounded execution instead of broad retrieval ambition

### Avoid in this tranche

- `UDW-07..12`
- `MCF-04..12`
- `CS-04..12`
- broad provider-surface expansion
- heavy DAG workbench work that is not backed by live runtime truth
- generalized memory fabric work that is not directly improving the execution wedge

## Live Boss-Ready Queue

The active execution lane is the ODR tranche (epic [#8223](https://github.com/synaptent/aragora/issues/8223)) plus the external-proof month plan; the rules below govern the Foreman/proof-loop background queue only.

- There is no dedicated open boss-ready trust-loop issue right now.
- Keep the live queue empty unless the recurring `TW-01/TW-02/TW-03` publication surfaces expose a fresh repeated rescue class or a concrete regression.
- Keep `CS-01..03` enforced through the docs/status surfaces while the live queue remains empty.
- Do not restock queue work to compensate for stale or dirty observer surfaces; fix the observer and the publication path first.

`TW-01` ([#5539](https://github.com/synaptent/aragora/issues/5539)), `TW-02` ([#5540](https://github.com/synaptent/aragora/issues/5540)), and `TW-03` ([#5330](https://github.com/synaptent/aragora/issues/5330)) now publish through repo-tracked recurring status surfaces at `docs/status/B0_BENCHMARK_TRUTH_STATUS.md` and `docs/status/TW03_RESCUE_PRODUCTIZATION_STATUS.md`. `RS-07`, `BC-01`, `BC-02`, and `BC-03` are already on `main`; do not recycle them as active blockers unless new evidence shows a concrete regression.

## Reverse-Staged Rocket Bootstrap

### Booster 0 — Corpus

Build the fixed benchmark corpus, enrich worker context, and record rescues honestly. This booster only counts as above target while the recurring B0 surface stays complete and fresh on current `main`; if publication drifts, restoring that surface takes priority over scope widening.

### Booster 1 — Assist

Have the system draft work orders, scope, and validation plans for the safest classes of tasks. Humans approve or edit the draft instead of writing everything from scratch.

### Booster 2 — Guard

Add worker contracts and production-equivalent preflight for the safe classes that already benchmark well: dependency bumps, additive/reversible config changes, and fail-closed fixes. Auto-run only when those guards pass and the explicit `B2` gate above has been met.

### Booster 3 — Repair

Add resumable sessions, retry/repair paths, salvage, and quarantine so common failure classes stop requiring repeated prompt surgery.

### Booster 4 — Multi

Extend the proven loops across hosts with truthful operator state. This is the bridge into early `Foreman` behavior.

## Execution Order

### 1) Corpus and context first

- benchmark corpus plus terminal-truth taxonomy
- context enrichment for the safest bounded issue classes
- honest measurement of no-rescue success rate

### 2) Assisted dispatch second

- auto-drafted work orders and validator plans
- human approval on the safe classes
- clearer issue/task shapes before execution starts

### 3) Guarded autonomy third

- `WorkerContract` plus `CredentialEnvelope`
- contract-aware preflight
- admission gates for the already-proven classes

### 4) Repair and salvage fourth

- resumable session journal
- verify/repair loop
- precise blocker evidence
- sanitizer outcomes persisted for audit

### 5) Multi-host truthful state fifth

- ledger-backed lane, host, and run status
- pause, resume, retry, and salvage controls
- first control-plane or DAG view backed by live state

## Stop / Go Rules

- Do not expand claims if the benchmark corpus is not moving.
- Do not ship GUI surfaces that are not backed by live receipts and contracts.
- Do not treat human rescue as success; convert it into benchmark cases or substrate work.
- If humans intervene twice for the same failure class, the next change should productize that rescue.
- Do not create broad GitHub tasks when the blocker can be stated narrowly.
- Do not let commercial positioning outrun measured proof.

## Done Criteria for This Tranche

This tranche is complete when:

1. a fixed benchmark corpus exists and runs regularly
2. context-enriched workers complete **>=50%** of it without rescue
3. all failures map to truthful canonical classes
4. at least one guarded admission path is real for the safest task class
5. repeated rescue classes are captured as explicit product work instead of hidden labor

## Vision-Layer Planning Track (`AGT-01..06`)

The agent-civilization substrate work is now tracked as a parallel planning lane, mirroring the pattern used for `DIC-13..22`. Issues may be open and design work may proceed; **no `AGT-*` issue may carry `boss-ready` until the proof-first Foreman gate explicitly permits this tranche**, and the proof-first reconciler MUST strip `boss-ready` from any AGT-* issue restocked outside the permitted lane.

| Code | Title | Detailed plan | Activation gate |
|------|-------|---------------|-----------------|
| `AGT-01` | Activate CruxDetector in live Arena debates | [crux-mode design](../plans/2026-04-16-crux-mode-design.md), Issue [#6035](https://github.com/synaptent/aragora/issues/6035), [agent-civilization substrate](../plans/AGENT_CIVILIZATION_SUBSTRATE.md) | DIC-15 CruxSet contract landed; substrate gate permits debate-path flag flip |
| `AGT-02` | A2A consumer surface (registration, capability discovery, billing, agent receipts) | [agent consumer surface](../plans/AGENT_CONSUMER_SURFACE.md) | substrate gate permits upper-layer tranche; existing A2A and marketplace primitives stable |
| `AGT-03` | Manifold integration with rolling Brier scoring | [prediction-market validation](../plans/2026-04-17-prediction-market-validation.md) | AGT-02 stable; rate-limit / GitHub-app token strategy in place for non-Manifold dependencies |
| `AGT-04` | Synthetic GitHub prediction markets | [prediction-market validation](../plans/2026-04-17-prediction-market-validation.md) | none (internal); proof-first reconciler stable enough not to be disrupted by added market objects |
| `AGT-05` | Skin-in-the-game reputation flow wiring | [skin-in-the-game reputation](../plans/SKIN_IN_THE_GAME_REPUTATION.md) | AGT-03 and AGT-04 producing resolved outcomes; DIC-16 receipt/KM provenance landed |
| `AGT-06` | Verifiable improvements per agent-hour (VIAH) metric | [agent-civilization substrate](../plans/AGENT_CIVILIZATION_SUBSTRATE.md) §4 | RS-10 ShiftLedger stable on `main` (already true); BC-12 substrate gate decision to retire empty-queue soaks in favour of VIAH |

Capability checkpoints for the booster-rocket thesis (CP-1..CP-5) live in [agent-civilization substrate §5](../plans/AGENT_CIVILIZATION_SUBSTRATE.md). Failing a checkpoint downscales the next investment rather than pausing the whole vision.

## References

- [Feature gap list — Active Direction (ODR)](./feature-gap-list)
- [Thirty-day external-proof month plan](../plans/2026-07-09-thirty-day-external-proof-month.md)
- [Quality bar / external-exposure ladder](QUALITY_BAR.md)
- [Evolution roadmap](./aragora-evolution-roadmap)
- [Active execution issues](./active-execution-issues)
- [Commercial overview](../enterprise/commercial-overview)
- [Agent-civilization substrate](../plans/AGENT_CIVILIZATION_SUBSTRATE.md)
- [Agent consumer surface](../plans/AGENT_CONSUMER_SURFACE.md)
- [Skin-in-the-game reputation](../plans/SKIN_IN_THE_GAME_REPUTATION.md)
- [Prediction-market validation](../plans/2026-04-17-prediction-market-validation.md)
- [Epistemic CI and Crux Engine](../plans/EPISTEMIC_CI_AND_CRUX_ENGINE.md)
