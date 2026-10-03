# Proof And Evidence

Consolidated from:
- `docs/strategy/DECISION_INTEGRITY_PROOF_MEMO_2026_03.md`
- `docs/strategy/PMF_EVIDENCE_LADDER_2026_03.md`
- `docs/outreach/FOUNDER_PROOF_POINTS_LIBRARY.md`

Last updated: 2026-03-25

---

## Part 1: What We Prove

### Core Thesis

Aragora does **not** yet prove that a multi-model workflow is always more
correct than the best single-model workflow.

Aragora **does** already prove a stronger decision process on consequential
work:

- disagreement is surfaced instead of hidden
- receipts preserve who said what, why the system advanced, and why it stopped
- bounded execution can fail closed instead of bluffing past uncertainty
- review and action gates can require more than one model's unchecked judgment

That is the current decision-integrity wedge.

### What Aragora Proves Better Than A Single-Model Workflow

#### 1. Better auditability and replayability

Single-model workflows usually leave chat logs and tool traces. Aragora produces
decision receipts with consensus state, dissent, provenance, and integrity
metadata, and those receipts are now visible on API and dashboard surfaces.

What is materially proven on `main`:

- receipt generation and storage are part of the live product loop
- quickstart receipts persist to the receipt store and are visible via
  API/dashboard/share-link
- the live founder loop passed 5/5 consecutive runs on March 24, 2026, with
  receipts visible on product surfaces

This is stronger than "the model said X." It gives operators an artifact they
can inspect, export, and compare across runs.

#### 2. Better visibility into disagreement and uncertainty

A single-model workflow collapses proposal, critique, and judgment into one
voice. Aragora separates those steps and records dissent as a first-class output.

What is defensible today:

- the debate engine is explicitly adversarial, not only cooperative
- dissent trails and unresolved tensions can survive into the receipt
- hollow-consensus detection, cross-verification, and truth-ratio scoring are
  wired into the debate path
- debate output quality has internal benchmark support: the March 5 diverse
  10-domain benchmark passed 100% with 0.938 average composite quality

External literature strengthens the direction of the claim. The
`aragora-debate` package cites multi-agent debate work reporting a `+13.8`
percentage-point accuracy gain over single-model baselines. That supports the
mechanism, but it is not yet the product's own live partner proof.

#### 3. Better truthful stopping behavior on bounded execution

Single-model workflows often optimize for producing an answer. Aragora is built
to preserve blocker truth and stop explicitly when evidence is insufficient.

What is already proven:

- the live founder loop is repeatable and truthful enough to pass 5/5 runs
- bounded execution paths preserve receipts and explicit blocker handling
- the inbox trust wedge is receipt-before-action by design
- quickstart behavior has fail-closed handling instead of silently continuing on
  broken setup

This is the most practical current proof: Aragora behaves more like a governed
control plane than a persuasive assistant.

#### 4. Better resilience to one model's blind spot or compromise

A single model can be wrong, sycophantic, injected, or compromised with no
internal challenge. Aragora's architecture gives one model's output multiple
opportunities to be challenged by heterogeneous peers before action is allowed.

The structural defense is real:

- provider and model-family diversity are part of the execution-gate logic
- consensus proof plus dissent recording make unilateral model action harder
- security docs already frame this as protection against prompt injection,
  hollow consensus, and some refusal-ablation scenarios

This is a structural advantage over a single-model workflow even where the live
product proof is still partial.

### What Aragora Only Partially Proves Today

#### 1. Quality improvement over the strongest single-model baseline

This is the biggest remaining commercial proof gap.

Aragora has:

- internal debate-quality benchmarks
- external literature supporting adversarial debate
- real dogfood proof that the founder loop is repeatable

Aragora does **not** yet have:

- a published bug/finding catch-rate delta versus a strong single-model review
  workflow on real engineering tasks
- a measured decision-quality delta on partner inbox, spec-review, or merge-gate
  workflows

The repo's own competitive positioning document already names this missing proof:
measure single-model versus multi-model quality deltas on real work and publish
case studies with findings and receipts.

#### 2. Full end-to-end proof across all user-facing surfaces

The repo now proves several important slices, but not yet a continuous external
user journey.

Still explicitly open in the feature gap list:

- smart provider routing is shipped, but live proof is pending
- one complete working user journey has mocked proof but still needs repeatable
  live proof
- Knowledge Mound read/write enrichment is shipped, but live visibility and
  trustworthiness in the founder loop remain open
- developer onboarding is improved, but the sub-10-minute live proof is still
  required

So the right claim is "the proof surfaces are real and getting truthful," not
"the entire platform is already proven end to end for external operators."

#### 3. Security completeness for high-impact decisions

Aragora proves that multi-model governance is harder to subvert than a
single-model workflow. It does **not** yet prove that the ensemble is secure
against every high-impact failure mode.

The threat model is explicit about remaining gaps:

- coordinated multi-provider compromise is not addressed with a hard proof
- correlated failure across all models is still possible
- there is no mandatory external verification gate for high-impact decisions
- runtime model attestation remains incomplete for endpoint substitution or
  refusal-ablation scenarios
- receipt-signing key custody is not enforced as an execution prerequisite

For high-impact decisions, Aragora currently proves better process integrity,
not guaranteed truth.

### What Aragora Should Claim Right Now

Aragora should say:

> We prove a better governed AI decision process than a single-model workflow:
> multi-model challenge, explicit dissent, signed receipts, and truthful stopping
> behavior on bounded execution.

Aragora should **not** yet say:

- multi-model is always more correct than single-model
- routing is fully proven in live production conditions
- every user-facing path is already partner-ready
- consensus alone eliminates correlated failure

### The Remaining Proof Agenda

#### Proofs to earn next

1. Publish measured single-model vs Aragora catch-rate deltas on real review
   tasks.
2. Prove one repeatable external user journey with routing, KM, receipt, and UI
   continuity visible end to end.
3. Turn the inbox and repo-review wedges into partner case studies with before /
   after operator outcomes.
4. Add stricter high-impact policy gates: external verification, stronger model
   attestation, and key-custody enforcement.

The bounded execution contract for proof agenda item `1` lives in
`docs/plans/DECISION_QUALITY_DELTA_BENCHMARK_SPEC.md`, with the automation
prompt pack at `docs/examples/decision-quality-delta-benchmark-prompt-pack.yaml`
and the compact reporting shape at
`docs/templates/DECISION_QUALITY_DELTA_BENCHMARK_REPORT_TEMPLATE.md`.

#### Metrics that matter

- bug and finding catch-rate delta vs strong single-model baseline
- override rate after receipt review
- blocked-for-good-reason rate vs false-positive blocker rate
- receipt generation coverage on consequential actions
- partner workflow repetition count with stable outcomes
- outcome-labeled calibration samples by domain

### Bottom Line

Aragora's current proof is strongest on **decision integrity**, not universal
decision correctness.

Today Aragora can credibly prove that consequential AI-assisted work is more
auditable, more challengeable, and more truthfully gated than in a single-model
workflow.

The missing proof is the hardest and most valuable one: quantified real-world
quality lift over the strongest single-model alternative, plus stronger defenses
against correlated ensemble failure on high-impact decisions.

---

## Part 2: PMF Evidence Ladder

### Purpose

Sequence Aragora's go-to-market motion by proof, not optimism.

This section defines the evidence ladder from internal dogfood to repeatable
design partner proof to paid expansion. Each rung exists to answer a different
question. The next rung should stay locked until the current one has receipt-
backed evidence.

### Current Position

As of March 25, 2026, Aragora has already proven the founder loop:

- 5/5 consecutive live founder-loop runs
- 35-62s runtime range
- receipts visible on API/dashboard/share-link surfaces
- `aragora spec` working end-to-end
- inbox trust wedge CLI wired, but not yet proven on a real internal inbox

That is enough to justify internal dogfood. It is not yet enough to claim
repeatable external proof.

### The Ladder

| Rung | Core question | Evidence that unlocks the next rung | What becomes allowed |
|------|---------------|-------------------------------------|----------------------|
| 1. Internal dogfood | Can Aragora run consequential internal work on two real workflows without founder magic? | Founder loop and inbox wedge both have exact commands, receipts, and visible result surfaces. The inbox wedge completes 10 consecutive live runs over at least 5 business days on a real internal inbox. At least 2 internal operators other than the primary builder can run the workflow from the written runbook and reach first useful result in 10 minutes or less. Over a 2-week window, at least 70% of internal runs end in an accepted action, and every remaining run stops truthfully with a blocker class and next action. Zero false-success incidents. | Start a bounded design partner program, use a repeatable live demo, and package proof assets around the actual workflow. |
| 2. Repeatable design partner proof | Does the wedge transfer to external teams and create measurable value without founder-operated rescue? | 3-5 design partners each complete at least 2 real tasks with receipt bundles. At least 2 partners repeat weekly usage for 4 consecutive weeks without the founder driving the keyboard. Each partner starts with a pre-agreed KPI, and at least 2 partners show a measurable delta of 20% or better on cycle time, finding catch-rate, or manual coordination load. At least 1 publishable case study or 2 private reference packs exist. At least 2 partners ask for a paid next step. | Sell a paid pilot in the same wedge, standardize onboarding and proof-pack collateral, and treat design partner proof as the basis for the first commercial motion. |
| 3. Paid expansion | Is there a repeatable paid land-and-expand motion in one wedge? | At least 2 design partners convert to paid. At least 1 additional paid logo closes in the same wedge from the same proof pack. At least 1 paid customer expands to a second workflow or team within 60 days. The paid cohort shows 8 consecutive weeks of active, receipt-backed usage without founder-operated rescue on the normal path. Procurement objections are stable enough to fit a standard security/compliance checklist. | Pull forward pentest and audit work, invest in procurement packaging, and expand into adjacent teams or workflows from a proven wedge. |

### Evidence Categories

Every rung should be judged across the same four categories:

| Category | What it means | Minimum bar |
|----------|---------------|-------------|
| Repeatability | The same workflow works more than once under realistic conditions | Consecutive live runs with receipts and visible result surfaces |
| Transferability | Someone other than the builder can get the same result | Internal operators first, then partner champions |
| Value | The workflow produces an accepted result, not just a demo | Pre-agreed KPI delta or accepted action rate |
| Truthfulness | The system either succeeds or stops with a direct reason | Zero false-success incidents and explicit blocker capture |

If a candidate proof artifact is missing one of these categories, it does not
unlock the next rung.

### What Does Not Count As Unlock Evidence

The following are supportive, but none of them substitute for rung-closing
proof:

- a single heroic founder demo
- generic waitlist demand or positive calls
- raw receipt counts without repeated useful outcomes
- more provider breadth, more agents, or more orchestration complexity
- pentest, SOC 2, or EU AI Act packaging before paid expansion proof
- unpublished anecdotes without command transcripts, receipts, or KPIs

### Required Proof Artifacts Per Rung

Each rung should leave behind a compact proof pack:

- exact command or workflow transcript
- receipt bundle and visible product-surface evidence
- KPI definition used for that rung
- blocker taxonomy with linked fixes or stop reasons
- short narrative: what changed, what still fails, what the next rung needs

Without this pack, the rung is not auditable and should be treated as
incomplete.

---

## Part 3: Founder-Safe Claims

### Standard For A Claim To Be Founder-Safe

A claim is founder-safe only if all of the following are true:

- it can be rerun on current `main` without narrative hand-waving
- it produces a durable artifact a prospect can inspect
- the artifact explains why the system advanced or stopped
- the boundary is explicit when the proof is not yet a live external workflow

If one of those is missing, downgrade the statement to "wired", "benchmark
proof", or "not yet for founder use."

### Core Claims To Lead With

#### 1. Live decision review is repeatable on current `main`

Use this claim:

> Aragora can run a live multi-agent decision review and produce a stored
> receipt on current `main`.

Minimum proof packet required:

- one live run on current `main`
- resulting receipt ID or share link
- proof that the receipt is visible on operator surfaces
- if you mention repeatability or speed, the March 24, 2026 baseline:
  5/5 consecutive founder-loop runs, 35-62 seconds, all 7 acceptance items pass

Current repo anchors:

- `ROADMAP.md` -- live founder loop proven repeatable, receipt-store visibility
- `docs/FEATURE_GAP_LIST.md` -- repeatability baseline and acceptance summary
- `docs/status/DESIGN_PARTNER_PROGRAM.md` -- default partner surface and live path

Do not say:

- "every onboarding path is live-proven"
- "provider routing quality is already live-proven"
- "KM read/write visibility is already proven in live partner runs"

#### 2. Aragora can show why the system advanced or stopped

Use this claim:

> Aragora does not just return an answer; it returns a receipt that shows the
> consensus, dissent, provenance, and next human action.

Minimum proof packet required:

- one exported or stored receipt artifact
- one verification surface, such as `aragora receipt verify` or a receipt API
- evidence that the receipt records outcome shape: approved, blocked, or needs human
- one example where dissent, provenance, or blocker handling is visible

Current repo anchors:

- `docs/integration/decision-receipts.md` -- receipt model and storage/verification path
- `aragora-debate/src/aragora_debate/receipt.py` -- receipt construction and integrity hashing
- `README.md` -- product path from debate to receipt

Do not say:

- "the system is always correct"
- "the receipt replaces human judgment"
- "cryptographic receipt" unless you can show the actual receipt artifact or verification step

#### 3. Aragora can gate bounded actions on persisted receipts and explicit policy

Use this claim:

> Aragora keeps automation bounded: receipt first, then explicit approval policy.

Minimum proof packet required:

- one action path with a narrow allowed-action set
- proof that a receipt is persisted before the action gate opens
- one policy surface, such as CLI approval mode, dry-run, or merge gate behavior
- if using the inbox wedge, show the current CLI path:
  `aragora triage auth` and `aragora triage run --dry-run`

Current repo anchors:

- `ROADMAP.md` -- inbox trust wedge CLI ready on March 24, 2026
- `docs/status/DESIGN_PARTNER_PROGRAM.md` -- receipt-before-action path and allowed inbox actions
- `tests/trust_wedge/test_attestation.py` -- receipt persisted before execution gate runs

Do not say:

- "broad autonomous actioning is proven"
- "the inbox wedge is already proven on a live customer inbox"
- "no human approval is needed"

### Reserve Claims, Not Default Openers

These are real, but they should stay secondary until the prospect asks for them
or the matching artifact pack is already in hand.

#### EU AI Act artifact generation

Safe claim:

> Aragora can generate EU AI Act artifact bundles from real decision receipts.

Proof required:

- compliance export generated from a real receipt
- bundle artifact or screenshots
- explicit boundary that this is artifact generation, not a certification claim

Current anchors:

- `ROADMAP.md` -- compliance bundle verified end-to-end with real quickstart receipts
- `docs/compliance/COMPLIANCE_BUNDLE.md`
- `docs/compliance/EU_AI_ACT_CUSTOMER_PLAYBOOK.md`

#### Ralph autonomous benchmark

Safe claim:

> Aragora has benchmark evidence that it can complete bounded repo work under
> explicit merge policy.

Proof required:

- benchmark artifact or result log
- exact policy boundary for the run
- resulting PR or merge metadata

Current anchors:

- `docs/FEATURE_GAP_LIST.md` -- Ralph V14 benchmark summary
- `docs/status/DESIGN_PARTNER_PROGRAM.md` -- how to pitch the benchmark truthfully

Boundary:

Use this as bounded autonomy evidence, not as proof of unrestricted external
autonomy.

### Facts That Support Claims But Should Not Be The Claim

These are supporting facts. They should appear after the proof point, not as the
opening line:

- 46 agent types
- 42 adapter counts
- SDK namespace counts
- broad connector breadth
- generic "multi-model" or "orchestration" language
- prompt-to-spec timing
- Prover-Estimator and truth-ratio internals

They help explain the system. They do not prove the wedge by themselves.

### Claims To Avoid Until New Proof Exists

- "Smart provider routing is live-proven in production workflows."
- "Knowledge Mound read/write is visibly proven in the live loop."
- "10+ agent coordination is proven at enterprise operating scale."
- "Aragora is already pentested / SOC 2 audited."
- "Aragora delivers broad autonomous execution without human gates."

### Founder Talk Track

Use this sequence:

1. We can run a live review and produce a stored receipt.
2. The receipt shows why the system advanced or stopped.
3. We can put bounded actions behind that receipt and an explicit approval policy.

Everything else is support, extension, or future proof.
