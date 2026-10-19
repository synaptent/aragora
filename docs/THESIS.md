# The Aragora Thesis

> Canonical source of authority. Every other strategic doc links up to this.
> Last updated: 2026-05-06. Status: v4 canonical. v1 → v2 applied codex's
> 5 required changes. v2 → v3 added premise 6 (Triage) and reframed
> commitments around Pareto-efficient attention allocation after
> founder arbitration. v3 → v4 applied codex round-3 findings with
> founder's normative-vs-descriptive reframe: the thesis describes
> the target shape of the product; category-B findings (where code
> does not meet thesis) are named as Implementation gaps rather than
> thesis errors.

> **Operational projection:** the [Agent Operating Loop](architecture/agent-operating-loop.md)
> preserves this thesis's authority and triage rules in one agent-facing read-only contract.

---

## The thesis

Advanced AI creates a new problem. It generates more output than any human
can meaningfully review, while generating output humans cannot safely
trust. The untrustworthiness is systematic, not incidental — it stems
from bad actors, prompt injection, training-data poisoning and bias,
spiky capabilities, hallucinations, knowledge cutoffs, and the ordinary
fact that any single model has blind spots it cannot detect alone.
Human attention becomes the scarce resource, and it cannot be rescued
by delegating review back to AI.

What humans and AI agents both actually need — and they both need this,
not just humans — is **infrastructure for truth-seeking**: tooling that
surfaces the structure of a claim (inputs, outputs, assumptions, values,
cruxes, dependencies, scope), cross-checks it adversarially across
heterogeneous lenses, tests it against outcomes, and distills the result
to a volume and form that informed consent, rejection, or feedback
becomes possible in the time a human actually has.

Aragora is that infrastructure. Its first domain is its own codebase.
Whether the pattern generalizes beyond software execution is a
load-bearing assumption, not a promise (see § Load-bearing assumptions).

---

## The six premises

1. **Bandwidth.** AI produces more output than humans can meaningfully process.
2. **Trust.** AI output is systematically untrustworthy — from adversarial
   inputs, biased or poisoned training data, spiky capabilities,
   hallucinations, knowledge cutoffs, and individual-model blind spots.
3. **No safe single-agent delegation.** Neither humans nor AI agents can
   safely defer to any *single* other agent's judgment, including their
   own. But this does not mean every decision must go to a human.
   Heterogeneous adversarial ensembles with input-diversification and
   dissent preservation can handle decision classes where outcome
   feedback has validated the ensemble's reliability. Where convergence
   is strong and outcomes are well-tracked, auto-handling is preferred;
   where convergence is weak, stakes are high, novelty is high, or
   outcomes are not observable, escalation to human weigh-in is
   required. Convergence across agents only counts as evidence when the
   agents have *different priors*, *different evidence*, and *active
   incentive to dissent* — homogeneous convergence (multiple models
   trained on similar data agreeing) is spurious.
4. **Structure.** Claims, conclusions, and decisions are tractable in
   terms of their inputs, outputs, assumptions, values, cruxes,
   dependencies, and scopes — and making that structure explicit is the
   prerequisite for cross-checking anything.
5. **Outcomes.** Truth-seeking is a process, not an oracle lookup.
   Claims that prove harmful or false get downweighted; claims that
   prove beneficial or true get upweighted. The weights are observable,
   auditable, and subject to revision.
6. **Triage.** Human attention is a scarce, imperfect, and unevenly
   distributed resource — normal humans are time-limited, distracted,
   cognitively bounded, and not equally competent on every decision.
   The substrate's job is not to drag every decision through human
   settlement, which would be productivity-killing red tape that
   violates premise 1 on the very agent — the human — whose bandwidth
   it is supposed to protect. Its job is to triage: route decisions
   to the human only when the human's weigh-in actually adds value,
   and auto-handle (with dissent preserved in receipts) decisions
   where AI ensemble convergence plus outcome history is a better
   allocation.

   The goal is operation on or near the **Pareto-efficient frontier**
   of three core tradeoffs visible to the operator:

   - **Decision velocity vs decision quality** — how fast the system
     decides vs how likely those decisions are to be right and not
     need backtracking. Rushing produces errors; over-deliberating
     produces paralysis.
   - **Autonomy vs human-attention cost** — the *operating point*.
     At any given configuration, what total fraction of decisions
     flows to the human vs gets auto-handled. Under-escalation
     misses decisions the human should have seen; over-escalation
     wastes human attention on decisions the ensemble could have
     handled. (Parameter: overall escalation-rate target.)
   - **Information density vs information completeness** — how
     distilled the brief is vs how much supporting context it
     preserves. Too dense and the human decides blind; too complete
     and the human doesn't decide at all.

   Three further tradeoffs operate at the system-learning level and
   are optimized by the outcome-feedback loop rather than directly
   by operator preference:

   - **Accuracy vs cost of accuracy** — compute, latency, and
     human-time spent per decision against accuracy achieved per
     decision. (Parameters: panel size, verification depth, re-run
     count.)
   - **Coverage vs confidence** — the *selectivity mechanism*. At
     a given operating point (set by autonomy-vs-attention above),
     the tradeoff between handling a broad decision class with
     higher uncertainty (broad coverage, more errors) vs handling
     only a narrow high-confidence subset (narrow coverage, fewer
     errors). Autonomy-vs-attention sets *how much* flows to the
     human; coverage-vs-confidence determines *which decisions
     specifically*. (Parameters: confidence threshold per class,
     decision-class allowlist.)
   - **Exploration vs exploitation** — trying new panel compositions,
     triage thresholds, or brief formats (gains learning) vs using
     known-good configurations (gains reliability). (Parameters:
     config-rotation frequency, A/B-test fraction.)

   A Pareto-efficient point is one where any further improvement on
   one axis necessarily costs another. The operator's job is to
   express where on the frontier they want to operate; the system's
   job is to stay on the frontier given that choice, and to flag
   when it has fallen off it.

---

## What Aragora therefore is

A truth-seeking substrate for **both humans and AI agents**, built on
four coordinated components:

1. **Structural decomposition.** Every consequential claim, conclusion,
   or decision gets decomposed into inputs, assumptions, cruxes,
   dependencies, and scope — before it is evaluated. Unstructured intent
   becomes a structured object that can be reasoned about.
2. **Adversarial cross-checking.** Heterogeneous-model ensembles — each
   with different training, architectures, and blind spots — combined
   with actively engineered input-diversification (rotated prompts,
   separate retrieval paths, provider-differentiated tooling) and
   explicit dissent incentives, surface what single models miss.
   Formal heterogeneity without input diversity is fake heterogeneity
   and does not satisfy premise 3. Dissent is first-class and
   preserved, not collapsed into a false consensus.
3. **Outcome-weighted feedback.** Claims, agents, and decisions carry
   track records. Calibration is measured. What proved harmful or false
   gets downweighted; what proved beneficial or true gets upweighted.
   The downweighting itself is evidence-linked and auditable.
4. **Distillation to human-scale.** Firehoses become briefs. Briefs
   preserve the load-bearing structure (cruxes, dependencies, dissent,
   outcome weights) so informed consent, rejection, or feedback is
   possible in the time a human actually has.

The audience includes AI agents. An agent evaluating whether to defer to
another agent's output needs the same structural decomposition,
adversarial cross-check, outcome weighting, and distilled form a human
does. The substrate serves both populations.

---

## When does the human actually need to weigh in?

Operationalizing premise 6. A decision escalates to human settlement
when **any** of the following triggers fire; otherwise the AI ensemble
auto-handles it with dissent preserved in the receipt.

- **Value tradeoff.** The decision involves contested values or
  priorities where no ensemble can legitimately substitute for the
  principal's preferences (product strategy pivots, hiring, brand
  voice, pricing policy, public commitments).
- **Personal impact.** The decision directly affects the human or
  their stakeholders (compensation, termination, external
  communication, legal exposure, equity dilution).
- **Low ensemble convergence or high unresolved dissent.** The
  heterogeneous panel disagrees materially and cannot resolve via
  evidence. The disagreement itself is a signal the human should
  arbitrate; collapsing it into majority vote defeats premise 3.
- **Sparse or negative outcome history.** The decision class has not
  yet accumulated enough outcome-validated auto-handling data, or
  prior auto-handled decisions in this class have been invalidated
  by outcomes. Ensembles do not get to self-certify on novel classes.
- **Irreversibility threshold.** The decision produces consequences
  that cannot be cheaply rolled back (production deploys affecting
  external users, signed contracts, paid announcements, schema
  migrations, privacy-affecting data changes).
- **Regulatory requirement.** EU AI Act Article 14 and analogous
  regimes mandate human oversight for defined high-risk classes.
  Compliance is not optional.

Outside these triggers, auto-handling is not only permitted, it is
the **correct** allocation. Forcing human review on every mechanical
chore-bump or low-risk dependency upgrade would violate premise 1
(bandwidth) on the one agent — the human — whose bandwidth the
product is built to protect. The triage layer's failure modes are
symmetric and equally costly:

- **Under-escalation** (missing a decision the human should have
  seen) → bad outcomes, lost trust, regulatory exposure.
- **Over-escalation** (wasting human attention on decisions the
  ensemble could have handled) → review fatigue, lost productivity,
  rubber-stamp drift as the human satisficing heuristic takes over.

The triage layer itself is therefore subject to the outcome feedback
loop of premise 5: its routing decisions are measurable, auditable,
and revisable. An escalation-rate that trends monotonically in
either direction over a rolling window without an explaining
outcome-history change is a signal the layer needs recalibration.

The six triggers above are **principle-level categories**.
Operator-level implementations (e.g., `docs/plans/2026-04-19-pr-
intelligence-brief-addendum.md`) specify concrete operational
triggers such as high-consequence path touches, the manual
`escalate-pdb` label, stale briefs, low synthesis confidence or
cross-lens dissent, and repeated flaky CI. Each operational trigger must map
to at least one principle-level category above. If an operational
trigger cannot be so mapped, either the principle-level list is
incomplete (amend this thesis) or the operational trigger is not
well-founded (amend the operator doc). The mapping itself is
auditable.

---

## What Aragora is NOT

Anti-claims — things the thesis explicitly does *not* commit to:

- **Not an oracle.** Aragora does not claim to know what is true. It
  claims to structure a process that approaches *relatively more true,
  less wrong* through evidence and outcome tests.
- **Not a rubber stamp for consequential decisions.** Approving
  high-stakes, value-laden, or low-confidence bot-generated work on
  "CI green" alone defeats the thesis. For decisions the triage layer
  (premise 6) escalates, human settlement remains the final gate.
  For decision classes where ensemble convergence plus outcome-history
  calibration supports auto-handling, CI-green plus dissent-preserving
  receipts *is* the settlement — by explicit design, not by omission.
- **Not a replacement for human judgment on decisions that actually
  need it.** The goal is to make human decisions faster, more
  informed, and more structured — and to stop wasting human attention
  on decisions that do not actually need it. Removing human judgment
  from the routine and reversible is a feature; removing it from the
  consequential is a bug. The triage layer's job is to know the
  difference.
- **Not value-neutral.** Truth-seeking requires a stance: some outputs
  are worse than others, and the system must take a position by
  downweighting, surfacing dissent, or refusing to proceed.
- **Not an arbiter of contested values.** Claims about which outcomes
  are beneficial versus harmful in hard ethical cases are inputs to the
  system, not its output.

---

## What we mean by "true"

This thesis commits to an operational meaning of "relatively more true,
less wrong" rather than a metaphysical one. Four tiers of claim, each
with a different evidential basis, each separately expressible in a
decision receipt:

1. **Agent-relative belief quality** — internal model output that
   reduces A's surprise and improves A's decisions under A's goals and
   constraints. Colloquially "truth for A," but strictly this is
   instrumental fit, not truth in the correspondence sense. Naming it
   precisely avoids relativist drift.
2. **Convergent truth** — the subset of agent-relative truths that
   remain stable under heterogeneous adversarial cross-checking by
   agents with different priors, different evidence, and active
   incentive to dissent.
3. **Operational objective truth** — the subset of convergent truth
   that continues to predict successfully under out-of-distribution
   interventions and over long time horizons. Today, Aragora can
   plausibly emit tier-3 claims only in narrow domains with short
   feedback loops and observable interventions (bounded software
   tasks). Tier-3 claims in broad or long-horizon domains are
   aspirational and must be flagged as such.
4. **Metaphysical objective truth** — the hypothesized structure of
   reality that best explains why (3) continues to hold. The product
   does not claim direct access to this tier; it bets that (3)
   approximates it.

A finite system can emit claims at tiers (1)–(3). It cannot emit (4).
Aragora commits to labeling which tier any given output occupies
rather than marketing all outputs as unqualified "truth." A receipt
saying *"convergent across five heterogeneous lenses with dissent
preserved"* is a weaker and more honest claim than *"true,"* and also
a more actionable one.

This position has precedent in pragmatism and convergent-inquiry
epistemology; the innovation is architectural, not philosophical,
namely building it as shipping software rather than essay. Readers
who want the academic mapping can see the footnote at the bottom of
this document.

[^philosophy]: Closest precedent: Charles Sanders Peirce's long-run
convergent inquiry (1878). Shares instincts with pragmatism (James,
Dewey) and predictive-processing (Friston). Explicitly not Tarski-style
correspondence — Aragora does not claim agent-independent access to
truth, only convergence under adversarial constraints.

---

## Where this thesis does NOT yet apply

Honest edges — regions the thesis does not claim to cover today:

- **Fundamentally value-laden decisions** (religious, ethical x-risk
  tradeoffs, contested political questions) where adversarial
  cross-check alone does not arbitrate. The system can structure such
  decisions and surface dissent, but cannot conclude them.
- **Decisions without decomposable structure.** Some problems resist
  structural decomposition (aesthetic judgment, novel research
  direction-setting). Truth-seeking machinery is weaker here.
- **Decisions where outcomes are not observable, or are observable only
  after long delays** (strategic bets, hiring, long-horizon R&D).
  Outcome-weighting requires feedback that may not arrive in useful
  time. The system must flag this limit explicitly rather than pretend
  to weight the unweighted.
- **Low-consequence, high-volume decisions** where the overhead of
  structural decomposition exceeds the value of the decision. The
  product's internal rule: structure-first applies to consequential
  decisions; trivial decisions get a fast path. *Experimental
  extension under test:* per-operator local advocate models (small,
  open-weight, locally finetuned on the operator's revealed-preference
  decision history) as a candidate fast-path proposer that escalates
  to the full debate substrate when its calibrated confidence falls
  below threshold. The hypothesis is falsifiable; see
  `docs/specs/ARAGORA_ROADMAP_REVISION_ADVOCATES.md` and the
  pre-registered Advocate Feasibility Test in `scripts/aft_harness.py`.
  This does not weaken the structure-first rule; it adds a measured
  pre-filter for the bucket the rule already excludes.
- **Closed belief systems that maintain surprise-reduction through
  hermeneutic reinterpretation rather than prediction.** A framework
  that explains away anomalies after they occur is not the same as a
  framework that predicts them in advance. Truth-seeking machinery
  works on claims testable under genuine intervention pressure and
  out-of-distribution prediction; it does not adjudicate beliefs that
  survive by being unfalsifiable.
- **Fake heterogeneity from shared context.** Multiple frontier models
  can share correlated failure modes, especially when they consume the
  same context bundle, retrieval sources, tool outputs, or prompt-
  injection vectors. The heterogeneity required by premise 3 degrades
  into theater if the agents are formally diverse but epistemically
  collapsed by shared inputs. Genuinely independent challenge must be
  actively engineered (separate retrieval, rotated prompts, provider-
  differentiated tooling, adversarial prompting across lenses), not
  assumed from the provider list.

Naming the edges honestly is part of the thesis. A truth-seeking
substrate that pretends to cover everything fails premise 2 on itself.

---

## Load-bearing assumptions (testable)

The thesis rests on six claims that must prove true in practice or the
product fails on its own terms:

| Claim | How to test | Horizon |
|------|-------------|---------|
| Heterogeneous AI ensembles detect what individual models miss | Per-model vs panel accuracy on benchmark corpus; dissent-surfacing rate | H1 |
| Humans given distilled advisory packets make better decisions than raw output | Decision-quality A/B on matched PR populations; override-correlated-with-outcome rate | H1–H2 |
| Structural decomposition is tractable for most consequential decisions | Percent of intent objects that decompose to testable cruxes; incompletions per class | H1–H2 |
| Ensembles produce genuinely independent challenge in practice, not just formal heterogeneity | Shared-context contamination probe: feed poisoned / adversarial context to a panel; measure percent of lenses that catch it vs correlate on failure. Success: >60% of lenses independently flag; <30% catastrophic correlation | H1–H2 |
| Cryptographic receipts produce trust that matters to buyers | Controlled with-receipt vs without-receipt A/B on identical decisions: approval-latency delta, pilot continuation rate, willingness-to-deploy under matched evidence. Willingness-to-pay alone is confounded and not sufficient. | H2 |
| The pattern generalizes beyond software execution | Success: at least one non-software domain wedge reaches tier-3 (operational objective truth, see § "What we mean by true") under its domain's intervention schedule, without domain-specific hand-tuning that fails to transfer. Failure: wedges either fail to converge or converge only via per-domain engineering that blocks generalization. | H3 |

If any of these fail under test, the corresponding component is wrong
or overreaching and the thesis has to be revised. The point of naming
the assumptions is to make revision cheap.

---

## How outcomes actually close the loop

Premise 5 depends on outcomes being observable and fed back. Concretely:

1. **Every consequential decision is emitted as a receipt** with
   structure, evidence, dissent, and a verdict.
2. **Outcomes are recorded against receipts** — test pass rate, merge
   stability, incident linkage, downstream revert, human override,
   design-partner adoption, compliance findings.
3. **Weights update from outcomes** — per-agent calibration scores,
   per-claim verification rates, per-lens dissent usefulness, per-
   decision-class override rates.
4. **New decisions consult updated weights** — truth-ratio weighting in
   consensus, selection feedback in agent picking, claim staleness in
   belief network, refused-to-proceed flags from repeated harm.

If any link in that chain is missing or unobserved, the outcome loop is
broken and premise 5 holds only in claim, not in practice.

---

## Generalization path (from codebase to wider domains)

The thesis commits to a sequenced rollout from software execution to
organizational substrate. The stages are:

1. **Own codebase (H1).** Aragora maintains Aragora. Dogfood proves
   bandwidth / trust / structure / outcomes on a domain where ground
   truth (code runs, tests pass, merge sticks) is cheap to observe.
2. **External software execution (H2).** Bounded autonomous engineering
   work on design-partner repos. The cryptographic-receipts assumption
   gets tested here.
3. **Consequential non-software decisions (H2→H3).** Risk, compliance,
   incident response, clinical and legal review. Ground truth is more
   expensive to observe; outcome feedback slows. The substrate has to
   flag where it is weaker.
4. **Organization substrate (H3).** Coordinated agentic work across
   functions on one graph with permissioned memory, shared receipts,
   portfolio-level truth-seeking. The endpoint of the thesis, not a
   near-term promise.

Each stage is gated on the previous stage's load-bearing assumption
being validated, not assumed.

---

## Implementation gaps (thesis target vs current code)

This thesis is normative. It describes the target shape of the
product. The current code does not yet fully implement that target.
This section names gaps honestly. **They are not reasons to weaken
the thesis; they are engineering work items that must be completed
for the code to realize the thesis.** Thesis commitments are
evaluated against the target, not the current implementation.

- **Auto-handle path calibration.** `fire_and_forget` in
  `aragora/swarm/tranche_integrate.py` and the
  `admin_merge_allowed` review-gate bypass in
  `aragora/ralph/supervisor.py` are now governed by a SQLite-backed
  calibration layer keyed on coarse decision classes, with per-event
  drift gating, drift receipts under `.aragora/review-queue/drift/`,
  and active-alert surfacing in `aragora review-queue` output.
  Remaining refinement work is narrower: richer invalidation sources
  beyond merge-confirmed success, and more expressive decision-class
  fingerprints once enough samples accumulate.

- **Triage metrics.** Commitment 5 — rolling-window triage metrics
  (escalation rate, auto-handle override rate, human-override-outcome
  correlation, time-per-settlement) — shipped via #6440 (gap #6373).
  `aragora/server/handlers/review_queue.py` now exposes
  `GET /api/v1/review-queue/triage-metrics` over a 7-day default
  window (configurable; 30-day window also computed for the
  Commitment 3 revision trigger). The metrics surface in
  `review-queue status` CLI output and in settlement receipts.
  Remaining refinement work: dashboard surfacing, per-class
  breakdown stability once enough samples accumulate.

- **PR review source-of-truth alignment.** Premise 3 is now exercised
  on the active PDB / brief-engine path
  (`aragora/pdb/real_invoker.py`, `aragora/pdb/invoker_factory.py`,
  `aragora/pdb/protocol.py`, `aragora/pdb/worker.py`; shipped via
  `#6404`, `#6425`, and dogfooded via `#6421`). That path invokes
  heterogeneous providers, preserves real `dissenting_views`, and
  emits execution statuses such as `STATUS_PANEL_EXECUTED` rather than
  the schema fallback. The remaining gap is alignment of legacy
  schema-only surfaces:
  `aragora/swarm/pr_review_protocol.py` still keeps
  `PROTOCOL_STATUS = "metadata_heuristic"` as the default for packets
  constructed without execution. Work needed: keep that fallback
  explicit, de-emphasize schema-only callers, and update status/docs
  surfaces so they treat the PDB execution path as the canonical PR
  review realization.

- **Empirical threshold grounding.** Commitment 3's invalidation threshold now requires
  complete v2 outcome observation coverage across the counted human-settled
  window before a zero invalidation numerator can emit a non-insufficient
  threshold update. When coverage is complete and zero invalidations are
  observed, the threshold uses the 1.0% minimum-meaningful floor
  (`max(0 * 0.5, 0.01)` = 0.01) and recalibrates upward as real invalidation
  events accrue; partial or absent coverage remains an insufficiency/schema-gap
  state instead of a measured zero.

Each gap is a tracked product backlog item. The gap-closing work is
what the product roadmap is for; it is not a reason to update the
thesis.

---

## How existing capabilities map

Every load-bearing subsystem should answer a premise. If it doesn't,
it's either redundant or should be reframed.

Each substrate item is tagged `[shipped]`, `[scaffolded]`, `[docs-only]`,
`[planned]`, or `[in progress]`. The table must survive skeptical
reading; status is explicit rather than implied.

| Premise | Existing Aragora substrate | Measurable property |
|---------|----------------------------|---------------------|
| Bandwidth | Batched-triage advisory packets (#6279) `[shipped]`; review-queue CLI (#6280, #6288) `[shipped]`; PDB UI v0 (#6328) `[scaffolded]`; settlement loop (#6297) `[shipped]` | PRs settled per session; time-per-settlement |
| Trust | Heterogeneous-model ensembles `[shipped]`; Arena debate engine `[shipped]`; circuit breaker, airlock, task sanitizer, trickster, cross-verification `[shipped]` | Dissent-surfacing rate; hallucination-catch rate |
| No safe delegation | Human settlement gate in merge-arbiter `[shipped]`; advisory-only machine review (#6279) `[shipped]`; EU AI Act Article 14 wedge (H1-05) `[docs-only]` | Percent of review-queue-path merges with human settlement; override-correlated-with-outcome rate |
| Structure | Belief network (claims + provenance) `[shipped]`; reasoning module `[shipped]`; `ReviewBrief` schema in `aragora/review/protocol.py` `[shipped]`; `BriefReceipt` + `SettlementLinkage` (#6353) `[shipped]`; PR review protocol packet scaffold (#6355) `[scaffolded]` | Percent of decisions with decomposed cruxes; structure-completeness score |
| Outcomes | ELO tracking `[shipped]`; persona evolution `[shipped]`; calibration tracker `[shipped]`; outcome feedback loop `[shipped]`; selection feedback `[shipped]`; receipt store `[shipped]` | Calibration error; per-agent track record; outcome-weight half-life |
| Tested against reality | Benchmark corpus rev-4 `[shipped]`; B0 truth publication `[shipped]`; proof-first queue `[shipped]`; gauntlet receipts `[shipped]`; evidence staleness `[shipped]` | Zero-rescue rate on bounded tasks; claim verification rate |
| Adversarial cross-check | Arena topologies `[shipped]`; Prover-Estimator consensus `[shipped]`; rhetorical observer `[shipped]`; trickster `[shipped]`; Recursive Language Models `[shipped]` | Ensemble-vs-single-model delta; dissent preservation rate |
| Distillation | Batched review-queue (#6288) `[shipped]`; PDB UI v0 (#6328) `[scaffolded]`; receipt summaries `[shipped]`; progressive disclosure (brief A/B/C densities) `[planned]` | Time-to-decision; brief-coverage-of-load-bearing-structure |
| Informed consent / feedback | Settlement signals (#6297) `[shipped]`; `BriefReceipt` + `SettlementLinkage` (#6353) `[shipped]`; dissent preservation in receipts `[shipped]` | Signal-to-settlement rate; human-override outcome correlation |
| Self-test on own codebase | Nomic loop `[shipped]`; self-develop CLI `[shipped]`; H1 dogfood wedge `[in progress]`; this review-queue rollout `[in progress]` | H1 exit criteria; dogfood session cadence |
| Triage (premise 6) | Review-queue triage buckets (`ready_now`, `needs_attention`, `repairable`, `parked`) in review-queue CLI `[shipped]`; machine recommendation packets (#6279) `[shipped]`; `fire_and_forget` low-risk auto-handle path in `aragora/swarm/tranche_integrate.py` with calibration + drift gating (#6468, #6448, gap #6372) `[shipped]`; `admin_merge_allowed` green-CI path in `aragora/ralph/supervisor.py` with same calibration layer `[shipped]`; `merge_arbiter` human-settlement gate `[shipped]`; rolling-window triage metrics per commitment #5 (#6440, gap #6373) `[shipped]` | Escalation rate; auto-handle override rate; human-override-outcome correlation; time-per-settlement; drift per rolling window |

**The strongest proof point is that the product is being applied to
itself.** The arc from problem statement → heterogeneous critique →
declaw of the auto-approver → design-doc-first discipline → settlement-
loop rollout is a worked example of the thesis in action. This very
document was produced by the same loop: multiple AI agents in
adversarial dialogue (including a codex review that requested changes
and was applied as a third commit), human arbitration, structured
output, committed as evidence.

---

## Commitments this thesis makes

Five concrete commitments follow from taking the thesis seriously:

1. **Decisions are routed by a triage layer, not uniformly by the
   human.** The thesis is not "always involve the human." The thesis
   is "allocate human attention where it actually helps." Concretely:

   - **High-stakes, novel, value-laden, low-confidence, or
     irreversibility-threshold-crossing decisions → human settlement
     required.** Ensemble outcome history is not yet a substitute for
     human judgment in these classes.
   - **Low-stakes, well-tracked, high-confidence, mechanical,
     reversible decisions → AI ensemble auto-handles with dissent
     preserved in receipts.** The `fire_and_forget` low-risk path in
     `aragora/swarm/tranche_integrate.py` and the
     `admin_merge_allowed` green-CI path in `aragora/ralph/supervisor.py`
     (documented in `docs/STATUS.md`) are the current implementations
     of this commitment. They are now governed by (a) outcome-history
     calibration over coarse decision classes and (b) per-event drift
     gating that disables narrowed classes when invalidation rises.
     The current classing remains intentionally conservative
     (review-tier, changed-file scope bucket, lane count for
     `fire_and_forget`; base branch, required-check bucket, merge-
     target kind for `admin_merge_allowed`) so sample sizes stay
     meaningful. Future work is refinement, not absence of governance:
     richer post-merge invalidation producers and finer-grained class
     features as history accrues, not the static-heuristic form.
   - **The triage layer itself is auditable and revisable.** It must
     report, per rolling window: percent of decisions auto-handled,
     escalated, and human-overridden; which decision classes are
     drifting toward under- or over-escalation; and which outcomes
     validated or invalidated prior triage choices.

   EU AI Act Article 14 alignment continues to follow: human
   oversight applies to the decision classes the triage layer
   escalates, not uniformly to every mechanical chore-bump. The
   commitment is about *correct routing*, not *maximal human
   involvement*.
2. **Dissent is preserved in receipts, not collapsed into majority.**
   Majority rule without a dissent trail is indistinguishable from
   false consensus.
3. **Outcome feedback is the measurement of whether the thesis holds.**
   Specifically, over any rolling 30-day window on the benchmark
   corpus:
   - if per-agent calibration error does not decrease; or
   - if, among decisions the triage layer *escalates to a human*, the
     fraction where dissent materially changes the human's verdict
     drops below 15% (suggesting the panel is converging on the human's
     prior rather than adding independent signal); or
   - if, among decisions the triage layer *auto-handles*, the
     outcome-invalidation rate rises above the current grounded threshold —
     provisionally the 1.0% minimum-meaningful floor only after complete v2
     outcome observation coverage over the counted human-settled window shows
     zero invalidations, and otherwise held in an insufficiency/schema-gap state
     until coverage is complete — suggesting auto-handling has drifted outside
     its validated scope,
   the product has failed its own test on that window and must be
   revised (architecturally via input-diversification; operationally
   via expanded panel heterogeneity; or in triage policy via tighter
   auto-handle gating) before shipping further capability on top.
   Thresholds are provisional and subject to recalibration after 30
   days of real settlement data.
4. **The limits named in "Where this thesis does NOT yet apply" are
   respected in product scope.** Aragora will not claim to arbitrate
   what it cannot arbitrate, even when asked.
5. **The triage layer is itself subject to outcome feedback.** The
   product's decisions about what to auto-handle vs escalate must be
   tracked and revised on the same basis as any other claim. A triage
   layer that under-escalates (misses decisions the human should have
   seen) or over-escalates (wastes human attention on decisions the
   ensemble could have handled) is failing the Pareto goal and must
   be recalibrated. The triage layer MUST emit, per rolling window:
   escalation rate, auto-handle override rate, human-override-outcome
   correlation, and time-per-settlement. Drift in any of them without
   a matching change in decision mix is a revision trigger. The
   current code (`aragora/server/handlers/review_queue.py`) emits
   only daily counts plus total decision seconds; the full rolling-
   window metric set is a tracked implementation gap (see
   § Implementation gaps). The triage layer does not get a free pass
   on the commitments the rest of the system is held to.

---

## What this replaces and what it does not

- **Replaces:** the scattered top-level framing across
  `WHY_ARAGORA.md`, `CANONICAL_GOALS.md` intros, `EXTENDED_README.md`
  openers, and `FEATURE_DISCOVERY.md` preambles. Those remain for
  operational detail; their introductions should cite this doc as
  source of authority.
- **Does not replace:** the 3-horizon roadmap, architecture references,
  feature catalogs, or operational runbooks. Those encode *how*. This
  doc encodes *why*.

---

## Single sentence

**Aragora is infrastructure for truth-seeking and Pareto-efficient
attention allocation when AI output outpaces human review and cannot
be safely trusted — decomposing claims into structure, cross-checking
them adversarially across heterogeneous lenses, weighting them by
outcomes, triaging which decisions need human weigh-in and which can
be auto-handled with dissent preserved, and distilling the result to
a form humans and AI agents can actually use — starting with its own
codebase and generalizing on evidence, not promise.**
