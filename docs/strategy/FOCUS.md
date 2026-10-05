# Aragora Focus Strategy: Depth Over Breadth

> **Core thesis**: Aragora's defensible value is adversarial decision integrity —
> not general-purpose agent orchestration. This document defines what to invest in,
> what to maintain, and what to deprioritize.

## Sprint 1 — 2026-05-26 → 2026-05-27 — CLOSED

> **Closed early because the four stated goals reached terminal state
> (shipped, satisfied, or honestly falsified) sooner than the 14-day
> window contemplated.** The producer:merger ratio went positive over
> the closing 48 hours; the substrate-overbuild concern flagged at
> sprint-open re-emerged in a new shape (described under Sprint 2
> anti-goals below).

### Sprint 1 outcomes

| # | Goal | Outcome | Evidence |
|---|---|---|---|
| 1 | Settle #7443 (provider bootstrap + receipt repair) | **Shipped** | Merged 2026-05-27T02:25:17Z as `7318af7e5b`. Tier 4 settled via repaired `scripts/settle_tier4_pr.py` (#7469 / #7471 lineage) using the model-quorum + `aragora/human-settlement` chain, normal protected squash with `--match-head-commit`, no admin-fallback needed. |
| 2 | Land #7450 (model-quorum family-expansion pre-approval) | **Shipped** | Merged as `dd144b4a3f`. The recognizer-header gap remains — implementation PR is governed by separate Tier 4 pre-approval #7472 (open, awaiting operator design review). |
| 3 | Land #7451 (model-family bench harness scaffold) | **Evidence satisfied; needs ready/settlement only** | Still open/draft at head `113a706c92831c0fb889d6e3da35ee454ceb6a94`. After repair commit `113a706c92` (addressing the three Codex request-changes blockers), the merge-packet counts `codex` + `factory` and 1 dogfood at the exact head; required checks are green; no unresolved dissent. Remaining blocker is operator/draft boundary, not evidence. |
| 4 | Publish B0 truth result, whatever it is | **Falsified honestly** | Re-ran `scripts/build_benchmark_truth_artifact.py --publish` 2026-05-26T22:51:31Z; verified `truth_success_rate_verified` is **0.0%** at this corpus. The repo-tracked evidence remains the generated B0 truth pointers under `docs/status/generated/benchmark_truth_artifacts/tw-01-bounded-execution-v1/`; local `.aragora/` rerun artifacts are intentionally not tracked. The 0.0% IS the artifact — the public claim must ratchet to what is measured. Legacy/proxy rates (30.8% / 76.9%) are not substitutes. **Reconciled 2026-06-05:** that 0.0% was honest for the corpus snapshot on 2026-05-26, but the benchmark corpus has since advanced (now `tw-01-bounded-execution-v1` rev-5, recorded 2026-05-28, coverage complete). The canonical published surface `docs/status/B0_BENCHMARK_TRUTH_STATUS.md` (last updated 2026-06-02) now measures verified `truth_success_rate_verified` = **100%** and full-corpus `truth_success_rate` = **53.8%** (7/13). The dated 0.0% is retained as the point-in-time Sprint-1 measurement, not the current claim; the live claim is always whatever the B0 status surface publishes. |
| — | Bonus — #7483 follow-up routing fix | **Shipped** | Merged 2026-05-27T17:22:58Z as `12615421be3af363803c1a68a5bb32d5105028b9`. Not a primary sprint goal but adjacent settlement-tooling work that landed cleanly. |

---

## Sprint 2 — 2026-05-27 → 2026-06-10 — CLOSED

> **Operating principle**: settlement / review-queue tooling has
> saturated. Sprint 1 already pushed producer:merger positive; further
> iteration in that surface is yielding diminishing returns. Sprint 2
> deliberately moves the load-bearing work back to *product proof*.
> When in doubt, *do not* spin a new settlement-tooling lane.

### Sprint 2 goals (≤4)

1. **Land #7479 — load-bearing product-proof unblocker.** **Shipped.**
   #7479 (`fix(ask): isolate explicit provider credentials`) merged as
   `d4f488de28877157b3e14156277594f9fe147305` and fixed the strict-
   secrets bug where `is_openrouter_fallback_available()` raised
   `SecretNotFoundError` before the `required=False` path was reached.
   That bug had blocked *all* `aragora ask` calls regardless of provider
   selection. Goal status: complete; no further #7479 action belongs in
   this sprint unless a regression appears.

2. **Run fresh-agent product-proof sequence end-to-end.** **Operator
   proof and strict non-operator demo receipt proof passed.** A local
   post-#7479 operator proof run recorded under
   `.aragora/proof/post-7479/20260528T035207Z/` shows
   `aragora validate-env --json`, `aragora doctor --validate`,
   `aragora ask --agents grok --decision-integrity`, and
   `aragora receipt verify` all exiting 0 on current main. The receipt
   `~/.aragora/receipts/9e2e072d-04e7-4968-8475-a2d134b85656_b6f334a28539822d.json`
   verified successfully. After #7496 (`933c82b183404eaf92e30bbbbf50a0e4afea3dd7`)
   landed, the strict non-operator/fresh-user demo proof recorded under
   `.aragora/proof/post-7496-demo/20260528T061018Z/` shows provider keys
   unset, Secrets Manager disabled, `aragora demo --receipt` exiting 0,
   and `aragora receipt verify` exiting 0 for receipt `DR-20260528-fac8d2`
   (`VALID (3/3 checks passed)`). These `.aragora/` proof files are local
   operator-held evidence, not repo-tracked public artifacts. Goal status:
   core product capability and outreach-gate clause (b) are satisfied.
   After the rev-5 B0 graduation, clause (a) is also satisfied by
   `docs/status/B0_BENCHMARK_TRUTH_STATUS.md`: `truth_success_rate_verified`
   is 100.0% across five strict verified entries. Clause (c) is satisfied by
   the unmodified Claude frontier adversarial review on product-scope SDK PR
   #7513 at exact head `6531ebad2968ae9e2888f08ba237473c41eb0e21`
   ([comment](https://github.com/synaptent/aragora/pull/7513#issuecomment-4567004963)).
   All three outreach evidence gates are now satisfied; actually performing
   outreach remains an operator decision, not an autonomous action.

3. **Operator design-review of #7472 (advisory-review recognizable
   header pre-approval).** #7472 is the Tier 4 design doc + 18 passing
   governance tests for plumbing per-family-named headers through the
   advisory review workflow. Without an operator yes/no on the design
   doc, the implementation PR cannot be scoped, and every future
   `## Aragora Code Review` advisory comment continues to resolve to
   `unknown_model_reviewer`. Goal acceptance: operator posts a design-
   review decision (approve / reject / request-changes) on #7472.
   Falsification: the design review reveals a structural problem with
   the per-family attribution contract itself; that is itself a useful
   signal and ends the lane cleanly.

4. **Substrate triage — decide which open review-queue /
   settlement-tooling PRs survive sprint 2.** **Triage target reached;
   keep pressure on net-closing behavior.** The initial surface had
   11+ open `codex/...` branches and ~8 PRs (#7480, #7476, #7473,
   #7448, #7453, #7481, #7484, plus open settle-tooling drafts). After
   the triage/merge cycle, the remaining governance/tooling surface is
   small enough for deliberate handling: #7472 remains the advisory-
   review recognizable-header pre-approval, #7480 remains the Tier 4
   pre-merge settlement-recording fix, and #7487 shipped as
   `08bbd426e0` (`fix(review-queue): block cancelled merge quorum
   checks`). Goal status: the ≤3 open-surface target is met after #7487
   merged; future process work must still close or supersede an existing
   open item or directly unblock the remaining product-proof/demo path.

### Sprint 2 anti-goals

- **No new review-queue, settlement, merge-quorum, or steering meta-
  tooling unless it (a) directly unblocks the remaining non-operator
  demo/product-proof path, OR (b) explicitly closes or supersedes an
  existing open PR in the same surface.** This is the explicit anti-
  substrate guardrail for sprint 2. Any PR in
  `aragora/cli/commands/review_queue.py`,
  `scripts/settle_*.py`, `scripts/*steering*.py`, `scripts/*harvest*.py`,
  `.github/workflows/aragora-merge-quorum.yml`, or
  `.github/workflows/aragora-review-gate.yml` must, in its PR body,
  EITHER state which remaining product-proof/demo gate it unblocks — by
  file:line — OR cite the open PR number it closes/supersedes, or stand
  down. Rationale: post-saturation process work in this surface is the
  dominant form of substrate-overbuild this sprint, and the close-or-
  supersede clause makes the rule self-policing — every new PR must
  either advance a load-bearing target or net-close the queue, not
  extend it.
- **No premature external outreach.** Same gate as sprint 1: outreach
  is unlocked only when *all* of these are true: (a) B0
  `truth_success_rate_verified ≥ 50%` (verified-by-PR-link metric, not
  legacy/proxy), (b) `aragora demo --receipt` round-trips for a non-
  operator user (satisfied by the local post-#7496 proof under
  `.aragora/proof/post-7496-demo/20260528T061018Z/`), (c) at least one
  frontier-model adversarial review of a real PR survives unmodified
  (satisfied by the Claude frontier adversarial review on product-scope
  SDK PR #7513 at exact head
  `6531ebad2968ae9e2888f08ba237473c41eb0e21`). Clauses (a), (b), and
  (c) are satisfied; external outreach execution still requires an
  explicit operator decision.
- **No Tier 4 self-mods without pre-approval discipline.** Unchanged
  from sprint 1. Any change to `scripts/settle_tier4_pr.py`,
  `aragora-merge-quorum.yml`, `aragora-review-gate.yml`, or the family
  recognizer in `aragora/cli/commands/review_queue.py` requires a
  design doc in `docs/specs/` and failing governance tests in
  `tests/governance/` *before* the implementation.

### Sprint 2 exit condition

End of sprint 2 = (a) all four goals reach terminal state (shipped,
satisfied, or honestly falsified) — same discipline as sprint 1 — or
(b) explicit operator decision to extend, replace, or abandon a goal.
The sprint does *not* extend by drift, and substrate-tooling work
that violates the anti-goal does *not* count toward any sprint goal
even if it lands successfully.

### Sprint 2 closure — 2026-06-10

| # | Goal | Outcome |
|---|---|---|
| 1 | Land #7479 (product-proof unblocker) | **Shipped** (`d4f488de28`, recorded above) |
| 2 | Fresh-agent product-proof sequence | **Satisfied** — operator proof + strict non-operator demo receipt proof passed; all three outreach evidence gates (a)(b)(c) satisfied. Outreach execution remains an operator decision. |
| 3 | Operator design-review of #7472 | **Not terminal** — the pre-approval spec merged, but the operator design-review decision (approve / reject / request-changes) was not posted within the window. Carried into Sprint 3 as an **operator-action item**, not an autonomous lane. |
| 4 | Substrate triage (≤3 open surface) | **Satisfied** — target met after #7487 merged; net-closing pressure held. |

Bonus movement during the window: B0 full-corpus truth rose 38.5% → **69.2%**
and in-progress graduation 0% → **50.0%** (4/8) — see
`docs/status/B0_BENCHMARK_TRUTH_STATUS.md`; the remaining ungraduated cohort is
`#5182 #5183 #5184 #5186` (bounded unit-test issues).

---

## Sprint 3 — 2026-06-10 → 2026-06-24 — CLOSED (same-day)

> **Operating principle**: the loop is now demonstrably netting product truth
> (69.2% full-corpus, 50% graduation). Sprint 3 spends loop capacity on the
> product, not the loop: finish the cohort, cap substrate self-work at the
> source, fix the two known merge-gate liveness stalls, and ship one dated
> commercial artifact. Process work outside the four named goals stands down.

### Sprint 3 goals (≤4)

1. **Graduate the remaining 4 B0-cohort issues** — `#5182`
   (server/handlers/orchestration/protocols), `#5183`
   (control_plane/workers/testfixer_task_worker), `#5184`
   (server/handlers/bots/slack/signature), `#5186` (agents/errors) — to
   verified truth under the existing `mergeable_pr_or_merged_pr` success
   contract, then republish `docs/status/B0_BENCHMARK_TRUTH_STATUS.md`.
   Target: in-progress graduation ≥ 87.5% (7/8), with honest falsification
   recorded if any issue proves mis-scoped.
2. **Ship the loop-steering substrate cap.** The boss issue generator gains a
   product:substrate classification and a `--substrate-cap` (default 0.3) so
   at most ~30% of generated issues target loop/meta surfaces. Acceptance:
   one before/after queue-composition measurement published in this file.
   (Sanctioned steering-surface work — it exists to redirect the queue toward
   product; anti-goal clause (a).)
3. **Merge-gate liveness Phase 1** per
   `docs/governance/BOSS_LOOP_MERGE_GATE_RESILIENCE.md`: (i) quorum-rerun
   reconciler (A1 — re-runs stale-but-satisfiable `aragora-merge-quorum`
   checks; kills the observed 2.5h stall class, e.g. #7727), (ii) boss PR
   dedupe janitor (closes duplicate draft PRs per issue — live duplicates at
   sprint open: #8061 ×2, #8002 ×3, #7818 ×2). Both are sanctioned under
   anti-goal clause (b): they net-close or unblock existing queue items.
4. **EU AI Act wedge artifact.** One polished, dated end-to-end walkthrough
   (`aragora compliance classify` → `eu-ai-act generate` → `report`) published
   under `docs/compliance/`, with honest "known gaps" recorded for any step
   that fails. The Aug 2, 2026 enforcement date is 7.5 weeks out; this is the
   one dated commercial wedge with shipped tooling.

**Carried operator item (not an autonomous lane):** post the design-review
decision on #7472 (advisory-review recognizable header).

### Sprint 3 anti-goals

Sprint 2 anti-goals carry forward verbatim (no new review-queue / settlement /
merge-quorum / steering meta-tooling outside clause (a)/(b); no premature
external outreach without an explicit operator decision; no Tier 4 self-mods
without spec + failing governance tests first). The four named goals above are
the **only** sanctioned settlement/steering-surface work this sprint.

### Sprint 3 exit condition

Same discipline: every goal reaches terminal state (shipped, satisfied, or
honestly falsified) or an explicit operator decision extends/replaces it. No
drift extensions.

### Sprint 3 closure — 2026-06-10 (same-day; run-20260610)

| # | Goal | Outcome |
|---|---|---|
| 1 | Graduate remaining 4 B0-cohort issues | **Shipped** — #5182 #5183 #5184 #5186 closed via merged issue-linked PRs (#8097 #8100 #8102 #8103); cohort 8/8. Truth-metric republication registers at the next recurring TW-02 pass. |
| 2 | Loop-steering substrate cap | **Shipped** — #8095 merged; live in the boss-loop launchd env (`ARAGORA_SUBSTRATE_CAP=0.3`). Trailing acceptance (before/after queue composition at next real refill) carried into Sprint 4 as a measurement item, per operator decision. |
| 3 | Merge-gate liveness Phase 1 | **Shipped** — reconciler #8092 (incl. live circular-stall fix) + janitor #8093 merged; reconciler live (`ARAGORA_QUORUM_RECONCILER=1`); 4 duplicate drafts closed at sprint open, duplicate groups now zero. |
| 4 | EU AI Act wedge artifact | **Shipped** — #8096 merged (dated walkthrough, live CLI outputs, honest PARTIAL grades). |

Carried operator item resolved: #7472 design review **APPROVED** (recorded 2026-06-10; the
lineage-bound implementation was already live on main — see the record correction on #7472).
Closure authority: exit condition (b), explicit operator decision of 2026-06-10 instructing
adoption of the steering-leverage operating plan's Phase 0 as Sprint 4.

---

## Sprint 4 — 2026-06-10 → 2026-06-24 — Phase 0: Instruments

> **Operating principle**: the two-week steering audit
> (run-20260610) found every loss shared one shape — *a cheap signal existed
> on disk, nothing was contracted to read it, and the human was the only
> fallback reader.* Sprint 4 ships the instruments before any further
> features, per `docs/superpowers/plans/2026-06-10-steering-leverage-operating-plan-v2.md`
> Phase 0, adopted by explicit operator decision (2026-06-10).

### Sprint 4 goals (≤4)

1. **Dead Man's Signals sentinel live.** `scripts/fleet_sentinel.py` +
   launchd unit: reads publisher-status freshness/auth, `boss_metrics.jsonl`
   mtime, launchd plist validity + daemon liveness, gh/codex auth state,
   main-checkout-on-main invariant, outbox depth/age, disk free; breaches
   emit to a JSONL ledger + notification channel; silence recorded as an
   incident. Acceptance: replaying the May-18→Jun-08 on-disk state raises
   the publisher alarm; ≥48h live with no human-discovered incident it
   missed.
2. **Leverage + waste instruments published.** `scripts/measure_leverage_ratio.py`
   (refuses to invent operator-minutes; steering-integrity honestly null
   until instrumented) + `scripts/measure_work_loss.py` (waste ratio from
   outbox archive × origin refs × PR refs — the 2026-06-10 harvest logic,
   productized) → `docs/status/LEVERAGE.md` with LR, waste ratio, and a
   blind-period log. Acceptance: first publication with real numbers,
   baseline = run-20260610.
3. **Net-closure floor in the issue generator.** Weekly closed:created
   below a configurable floor throttles `generate_boss_issues.py` (the
   substrate-cap pattern applied to appetite; audit basis: 215 created : 0
   closed in the window). Acceptance: floor enforced in one real refill or
   throttle observed, skips reported never silent.
4. **Substrate-cap composition measurement** (carried Sprint 3 goal 2
   acceptance): publish the before/after queue composition at the first
   real refill with the cap active. **Satisfied (2026-06-11)** — published in
   `docs/status/LEVERAGE.md` § "Queue Composition (substrate cap)". The live
   generator yields **0 valid candidates at both cap settings** (proof-first
   canonical-priority filter empties the queue upstream of the cap, same as
   2026-06-10), so no real refill reached the cap to compose. The measurement
   is therefore **synthetic — the cap's mathematical effect proven by unit**
   (`select_with_substrate_cap`, 7/7 tests passing): on a 10-substrate +
   10-product set at the default `cap=0.3`, composition shifts from 100%
   substrate (cap disabled) to **30% substrate / 70% product** (3 substrate /
   7 product, 7 substrate skipped, never silently). The synthetic-vs-live
   distinction is stated explicitly in the published section; it is to be
   replaced with an observed live composition at the next real refill that
   reaches the cap with mixed candidates.

### Sprint 4 anti-goals

Sprint 2/3 anti-goals carry forward verbatim. Additionally: **no Phase 1+
work** (attention exchange, crux cards, intents, ledger, receipt standard)
this sprint — instruments first, features after the instruments exist; and
no settlement-surface changes (`review_queue.py`, quorum workflows,
`settle_*.py`) — the three green settlement-surface PRs from the outbox
harvest (#8122, #8126, #8140) await operator settlement and are not
superseded by anything here.

### Sprint 4 exit condition

Every goal terminal (shipped / satisfied / honestly falsified) or explicit
operator decision; no drift extensions. Sentinel goal additionally requires
the 48h live-soak clause before it counts as shipped.

---

## The Problem

The codebase has grown to **3,296 Python files / 1.48M LOC** across 120+ top-level modules.
This breadth creates:
- Maintenance burden that outpaces development capacity
- Unclear product identity ("is this a chat bot? a workflow engine? a blockchain project?")
- Difficulty for contributors to understand where to focus

## The One-Line Product

> **Aragora is the open-source adversarial vetting layer for AI-assisted decisions.**

When the decision matters — architecture, compliance, hiring, strategy — one model's
opinion isn't enough. Aragora orchestrates structured adversarial debates across
heterogeneous models, tracks calibrated confidence, and produces cryptographic
decision receipts for your audit file.

---

## Tier 1: Defensible Core (Invest Heavily)

These components are **genuinely unique** — no open-source equivalent exists.
They constitute Aragora's product-market fit.

| Module | Files | LOC | What It Does | Uniqueness |
|--------|-------|-----|--------------|------------|
| `debate/` | 230 | 104K | Adversarial debate engine: propose → critique → revise → synthesize | 9/10 — No OSS equivalent |
| `gauntlet/` | 32 | 14K | Red-team stress testing + cryptographic decision receipts | 8/10 — Novel receipt system |
| `knowledge/` | 161 | 89K | Knowledge Mound: 28-adapter institutional memory hub | 8/10 — Adapter factory unique |
| `ranking/` | 23 | 9K | ELO rankings + Brier calibration + domain-specific trust | 7/10 — Runtime calibration rare |
| `memory/` | 46 | 22K | 4-tier Continuum memory with red-line protection | 7/10 — Tier architecture novel |
| `reasoning/` | 16 | 8K | Belief networks, provenance tracking, claim graphs | 8/10 — Debate-integrated unique |
| `verification/` | 7 | 4K | ThinkPRM process reward model verification | 9/10 — Research paper impl |
| `explainability/` | 3 | 1K | Decision explanation: evidence chains, vote pivots | 6/10 — Useful, not unique |
| `evidence/` | 7 | 6K | Evidence collection and provenance tracking | 7/10 — Integrated with debate |

**Total: 525 files / 257K LOC (17% of codebase, 100% of unique value)**

### Investment priority
- Harden debate engine reliability and performance
- Expand ThinkPRM usage beyond single call site
- Make decision receipts the primary output artifact
- Improve explainability depth (counterfactuals, factor decomposition)

---

## Tier 2: Essential Infrastructure (Maintain)

These components are necessary to make the core accessible but are not
differentiators themselves.

| Module | Files | LOC | Role |
|--------|-------|-----|------|
| `agents/` | 80 | 36K | Agent implementations (Claude, GPT, Gemini, Grok, etc.) |
| `server/` | 946 | 410K | API layer — **oversized, needs pruning** |
| `storage/` | 101 | 52K | PostgreSQL/SQLite/Redis persistence |
| `cli/` | 56 | 23K | Command-line interface |
| `config/` | 14 | 7K | Configuration management |
| `core/` | 20 | 6K | Core types and protocols |
| `resilience/` | 12 | 4K | Circuit breakers, retry, timeout |
| `utils/` | 17 | 4K | Shared utilities |
| `protocols/` | 14 | 4K | Protocol definitions |

**Total: 1,260 files / 546K LOC (37% of codebase)**

### Action items
- **`server/` (946 files, 410K LOC)** is 28% of the entire codebase alone.
  Audit for dead handlers, consolidate, remove unused routes.
- Keep agent implementations lean — the value is in orchestration, not individual agents.
- CLI should prioritize `aragora debate`, `aragora review`, `aragora receipt` commands.

---

## Tier 3: Enterprise Features (Keep, Don't Lead With)

These features are table-stakes for enterprise adoption but don't differentiate.
Every framework adds them eventually.

| Module | Files | LOC | Role |
|--------|-------|-----|------|
| `rbac/` | 35 | 19K | Role-based access control (360+ permissions) |
| `audit/` | 43 | 24K | Audit logging |
| `billing/` | 34 | 23K | Cost tracking, metering, forecasting |
| `security/` | 9 | 7K | Encryption, key rotation, anomaly detection |
| `auth/` | 12 | 7K | OIDC/SAML SSO, MFA, API keys |
| `compliance/` | 5 | 4K | SOC 2, GDPR frameworks |
| `tenancy/` | 8 | 3K | Multi-tenant isolation |
| `privacy/` | 8 | 5K | Anonymization, consent, deletion, retention |
| `backup/` | 6 | 4K | Disaster recovery |
| `observability/` | 59 | 27K | Prometheus, Grafana, OpenTelemetry |
| `events/` | 26 | 10K | Event dispatcher, dead letter queue |

**Total: 245 files / 133K LOC (9% of codebase)**

### Guidance
- Maintain but don't expand unless customer-driven
- RBAC and audit are important for regulated industry positioning
- Observability is useful but 59 files / 27K LOC is oversized for monitoring

---

## Tier 4: Connectors (Necessary, Commodity)

Chat/platform connectors that make the core accessible. Important for adoption
but not differentiating — every platform has these.

| Module | Files | LOC | Role |
|--------|-------|-----|------|
| `connectors/` | 251 | 127K | Chat (8 platforms), enterprise, accounting, legal, medical |
| `integrations/` | 29 | 16K | Slack, email, Discord, Teams, Zapier, LangChain |
| `gateway/` | 73 | 31K | API gateway, routing, protocol |
| `mcp/` | 22 | 8K | Model Context Protocol tools |

**Total: 375 files / 182K LOC (12% of codebase)**

### Guidance
- 8 chat connectors is sufficient. Don't add more.
- `connectors/` at 127K LOC is bloated — many connectors have thin usage.
  Prioritize Slack, Teams, Discord. Consider making others community-maintained.
- Gateway is oversized at 31K LOC. Evaluate what's actually used.

---

## Tier 5: Deprioritize (Scope Creep)

These modules either duplicate functionality available in better-maintained
projects, are too experimental for GA, or don't serve the core product thesis.

| Module | Files | LOC | Why Deprioritize |
|--------|-------|-----|-----------------|
| `workflow/` | 83 | 32K | LangGraph does this better with larger community |
| `nomic/` | 86 | 40K | Self-improvement loop — experimental, safety concerns |
| `control_plane/` | 44 | 25K | Agent registry/scheduler — overkill for current stage |
| `rlm/` | 28 | 13K | Recursive Language Models — niche research |
| `services/` | 43 | 25K | Service layer — evaluate overlap with server/ |
| `blockchain/` | 10 | 2K | ERC-8004 — interesting research, not a product feature |
| `computer_use/` | 9 | 5K | Browser automation — Anthropic's tool, not our value-add |
| `training/` | 12 | 5K | Training pipelines — not core to decision integrity |
| `ml/` | 8 | 4K | ML utilities — use standard libraries instead |
| `voice/` + `speech/` + `transcription/` | 11 | 2K | Audio — not core |
| `canvas/` | 5 | 2K | Visual canvas — not core |
| `genesis/` | 7 | 3K | "Agent evolution" — experimental |
| `evolution/` | 6 | 3K | Evolution system — experimental |
| `sandbox/` | 5 | 3K | Docker sandbox — useful but not differentiating |
| `harnesses/` | 5 | 2K | External tool integration |
| `broadcast/` | 9 | 4K | Broadcasting — commodity |
| `channels/` | 18 | 4K | Channel management — overlaps with connectors/ |
| `bots/` | 7 | 3K | Bot framework — overlaps with connectors/ |
| `documents/` | 18 | 7K | Document handling — commodity |
| `marketplace/` | 4 | 1K | Agent marketplace — premature |
| `fabric/` | 12 | 5K | Fabric system |
| `coordination/` | 2 | 1K | Cross-workspace — premature |
| `coding/` | 2 | 1K | Code generation — not core |
| `replay/` | 6 | 1K | Debate replay |
| `spectate/` | 3 | 0.3K | Spectating |
| `introspection/` | 4 | 0.4K | Agent self-awareness |
| `learning/` | 2 | 0.5K | Continual learning |
| Various small modules | ~30 | ~10K | Misc |

**Total: ~490 files / ~200K LOC (25% of codebase)**

### Recommendations
- **`workflow/`**: Consider replacing with LangGraph integration. 83 files for a
  workflow engine competes with a VC-backed project with 10x the team.
- **`nomic/`**: Keep as experimental/internal. Do not market as production feature.
  Safety implications of self-improving AI are serious.
- **`control_plane/`**: Evaluate actual usage. 25K LOC for agent scheduling may be
  premature for current adoption stage.
- **`blockchain/`**: Interesting research. Keep in `experimental/` namespace but
  don't invest further until there's user demand.
- **Audio/visual/canvas**: Remove from main package or move to `contrib/`.

---

## The Math

| Tier | Files | LOC | % of Codebase | Investment |
|------|-------|-----|---------------|------------|
| 1. Defensible Core | 525 | 257K | 17% | **Invest heavily** |
| 2. Essential Infrastructure | 1,260 | 546K | 37% | Maintain, prune server/ |
| 3. Enterprise Features | 245 | 133K | 9% | Keep, don't expand |
| 4. Connectors | 375 | 182K | 12% | Maintain top 3 platforms |
| 5. Scope Creep | ~490 | ~200K | 25% | Deprioritize or extract |

**Key insight**: 25% of the codebase (Tier 5) doesn't serve the core product thesis.
The remaining 75% can be further optimized by pruning `server/` (410K LOC is excessive).

---

## Standalone Library Strategy

The highest-leverage move is extracting the Tier 1 core as a standalone library:

```bash
pip install aragora-debate
```

This package should contain:
1. **Debate orchestration** — `Arena`, `DebateProtocol`, phases
2. **Agent interface** — Protocol/ABC that any LLM wrapper can implement
3. **Consensus detection** — Majority, weighted, semantic similarity
4. **Decision receipts** — Cryptographic signing, dissent tracking
5. **Calibration** — ELO rankings, Brier scores

It should **not** contain: server, connectors, enterprise features, workflow,
blockchain, self-improvement, or any other Tier 3-5 module.

**Target**: Under 50 files, under 10K LOC, zero infrastructure dependencies.
A developer should be able to run an adversarial debate in 10 lines of code.

---

## Success Metrics

1. **Can a new user run a debate in under 5 minutes?** (Currently: no)
2. **Can someone explain what Aragora does in one sentence?** (Currently: unclear)
3. **Does every PR serve the core thesis?** (Currently: often no)
4. **Is the test suite focused on the core?** (130K tests, but how many test Tier 1?)
