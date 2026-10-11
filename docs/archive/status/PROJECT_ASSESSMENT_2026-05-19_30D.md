# Aragora — 30-Day Strategic Project Assessment

**Window:** 2026-04-19 → 2026-05-19
**Author:** claude-B061F80D (this session, drafted at operator request)
**Audience:** founder, deciding whether to continue investing time/attention on
the current trajectory or change shape
**Status:** assessment — read carefully; act selectively. Negative findings
are intentionally given more weight than positive ones per the honesty
discipline in the assessment prompt.

---

## Executive verdict

The project is producing genuinely novel infrastructure at a high pace, but
**the headline named goal is at 0.0%** against a ≥50% 30-day target, and the
substrate-to-LBA-test ratio has drifted to roughly **10:1 toward substrate**.
Aragora is increasingly a strong "agent coordination platform" and decreasingly
the stated "decision integrity platform / infrastructure for truth-seeking."

That drift is recoverable. It is not yet a crisis. But it has now persisted
through at least two consecutive review cycles (this assessment + the
April-17 Opus critique recurring across sessions), and the response to date
has been to build more substrate rather than confront the headline metric.

The three things that genuinely differentiate Aragora are real and
defensible. The 30-day question is not "is the work good?" — it is "is the
work pointed at the named goal?" The answer is partly no.

---

## Question 1 — USEFUL

Did the 30 days advance the project's own stated goals?

### Raw activity profile

- **730 commits** on `origin/main` (no merges) across 30 days
- **826 PRs created** in the window by GitHub search:
  668 merged, 56 open, 102 closed-unmerged
- **56 open PRs** at snapshot (39 draft, 17 ready)
- **Author concentration:** 91% of all no-merge commits are attributed to
  the two founder identities (an0mium=546, Armand=117; the remaining
  67 commits include 51 dependabot, 9 Claude, and 7 various
  Droid/Factory identities). Most an0mium commits are agent-authored
  squash-merges credited to the founder's GitHub identity, so the real
  bus factor is still 1. This was Opus's April-17 critique. Thirty days
  later, unchanged.

Verification snapshot (2026-05-19T21:38Z):

```bash
git log origin/main --since="2026-04-19" --pretty=oneline --no-merges | wc -l
# 730

gh pr list --state all --search 'created:>=2026-04-19' --limit 1000 \
  --json number,state,isDraft,mergedAt,createdAt,title,headRefName
# 826 total: 668 MERGED, 56 OPEN, 102 CLOSED
```

### Top commit scopes (last 30 days)

| Scope | Commits | % of total |
|---|---:|---:|
| (automation) | 142 | 19.5% |
| (status) | 62 | 8.5% |
| (deps) | 56 | 7.7% |
| (agent-bridge) | 27 | 3.7% |
| (scripts) | 26 | 3.6% |
| (review) | 23 | 3.2% |
| (swarm) | 22 | 3.0% |
| (heterogeneity) | 16 | 2.2% |
| (ci) | 15 | 2.1% |
| (epistemic) | 13 | 1.8% |
| (plans) | 11 | 1.5% |

Automation-scoped commits alone are **142 commits in 30 days** — ~one automation-tool
hygiene commit every five hours of wall-clock, on average. The substrate
is not "boring" yet, despite NEXT_STEPS_CANONICAL's explicit goal: "make
bounded unattended execution boring."

### LBA-by-LBA assessment

The thesis names six load-bearing assumptions / horizons that need to be
TESTED, not just SUBSTRATED:

#### LBA 1: Heterogeneity ensemble (Tier-1 Defensible Core)

- **Substrate:** `aragora/debate/`, `aragora/gauntlet/`, `aragora/ranking/`,
  `aragora/agents/api_agents/` (multi-provider) — all on `main`.
- **30-day activity:** 16 commits in (heterogeneity) scope.
- **Tested?** Partially. The debate engine is exercised regularly via
  multi-model PR review (codex/factory/claude triangulation across this
  session itself). It's not measured against the canonical proof loop.
- **Verdict:** mature substrate, ad-hoc testing, no formalized success metric.

#### LBA 2: Cryptographic receipts

- **Substrate:** `aragora.security.context_signing.get_signing_key()`,
  receipt-trio convention, draft ADC v0.4 HMAC signing work, `gauntlet/`
  receipts.
- **30-day activity:** ~15+ receipts produced this week alone; ADC v0.1
  (#7357) is merged, while ADC v0.2-v0.4 (#7358/#7360/#7361) are open
  draft follow-ons and should not be described as shipped/current state.
- **Tested with a buyer?** **No.** Per THESIS § Load-bearing assumptions,
  "Cryptographic receipts produce trust that matters to buyers" is tested
  against design partners. No design-partner activity in 30 days.
- **Verdict:** substrate strong, audit-trail-side validated continuously
  via internal use, **buyer-trust LBA untested**.

#### LBA 3: Outcome-feedback loop

- **Substrate:** `review-queue observe-outcomes --write` shipped pre-window;
  rescue productization mechanism shipped pre-window.
- **30-day activity:**
  - `observe-outcomes --write` first verified **2026-05-13** (#7131)
  - Batch 2 with first FIRED signal **2026-05-14** (#7159)
  - Observer truth probe **2026-05-18** (Q09 receipt)
- **Tested?** Yes, ~3 runs in 30 days. The loop ran. Two productizations
  followed (admission_class_corpus_synthesis_v1 + blocked_auth_failure)
  per `docs/benchmarks/rescue_productization.json` — both real, both
  bound to issue #7209 and PR #7225/#7228.
- **Verdict:** **the most successful LBA closure of the month**. Not many
  runs, but the runs produced real productization work. This deserves
  more weight than the project has been giving it.

#### LBA 4: Design-partner wedge (H2 horizon)

- **Substrate:** historical design-partner and wedge assets exist, including
  `docs/status/DESIGN_PARTNER_PROGRAM.md`,
  `docs/outreach/DESIGN_PARTNER_OPERATIONS_PLAYBOOK.md`,
  `scripts/demo_design_partner.sh`, and
  `docs/examples/inbox-trust-wedge-activation-*.yaml`.
- **30-day activity:** I found substrate, not a recent external test. The
  current 30-day evidence still does not show a design-partner conversation,
  buyer trial, or external-user feedback loop.
- **Tested?** **No.** Not even attempted in 30 days.
- **Verdict:** This is the single largest LBA gap. The cryptographic-
  receipts assumption (LBA 2) is gated on a buyer testing it. No buyers
  → no LBA test → that proof-line is stuck at "scaffolded but never run."

#### LBA 5: EU AI Act readiness (Aug 2 2026 deadline)

- **Substrate:** `aragora/compliance/` exists with EU AI Act surfaces, and
  historical docs/plans exist (`docs/EU_AI_ACT_COMPLIANCE.md`,
  `docs/compliance/EU_AI_ACT_PACKAGE.md`,
  `docs/plans/2026-03-03-eu-ai-act-compliance-ship-design.md`,
  `docs/plans/2026-03-05-eu-ai-act-cli-g1-signing-design.md`).
- **30-day activity:** existing docs are not the same as a current readiness
  test. I found no 30-day external audit or refreshed readiness packet.
- **Tested?** No external audit, no current readiness packet generated.
- **Verdict:** deliberately deferred per Phase-0-first policy in
  NEXT_STEPS_CANONICAL. Defensible *now*, but the Aug 2 deadline is
  ~75 days away. If Phase 0 (proof-loop graduation) doesn't close in
  the next 30 days, the EU AI Act gap becomes urgent in 45 days.

#### LBA 6: ADC authority-chain protocol

- **Substrate:** ADC v0.1 shipped in the last 48 hours; ADC v0.2-v0.4 are
  open draft follow-ons. Stack-coherence audit GREEN. Four agents in parallel
  authored four versions cleanly, but only ADC v0.1 PR (#7357) is already on
  `main`.
- **30-day activity:** intense, concentrated in the last 5 days
- **Tested?** **Partially.** The fact that four agents across two families
  built four versions in parallel without merge conflict is itself a
  test of the protocol-being-built. But the cross-family enforcement
  (v0.8 — the moment when a contract issued in one family is honored
  by another) hasn't shipped or been tested.
- **Verdict:** strongest engineering work of the 30 days; the LBA-test
  side (v0.8 dogfooding) is one merge + one droid mission away.

### B0 canonical truth surface — the headline metric

This is the most important number in this assessment. Per
`docs/status/B0_BENCHMARK_TRUTH_STATUS.md` (last updated 2026-05-19T04:09):

```
Verified truth success rate (primary):  0.0%
Full-corpus truth success rate:         0.0%
No-rescue truth success rate:           0.0%
Merged-only rate:                       0.0%

In-progress expected issues:  13 / 13 attempted
```

The 30-day target stated in NEXT_STEPS_CANONICAL.md was **≥50%** no-rescue
completion of the bounded benchmark corpus. The actual is **0.0% verified
success on 13/13 attempted**.

This is binary. The named goal was specifically operationalized in numeric
terms in the canonical doc, and the actual measurement is zero against
that goal.

The corpus content is mixed but still bounded: the 13 issues span
`missing_test_coverage`, `small_refactor`, `validation_tightening`,
`exception_narrowing`, `benchmark_corpus_maintenance`, and
`docs_reconciliation`, with missing test coverage still the largest class
(5/13). Even if the corpus completes 100% in the next 30 days, it only
tests bounded-execution capability across these maintenance classes. The
cryptographic-receipts LBA is not tested by this corpus.

### Effort-share estimate

Rough split of 730 commits:

- **Direct LBA testing:** ~30-40 commits (observe-outcomes runs, B0
  publication runs, rescue productization landings)
- **LBA-adjacent substrate** (ADC, debate refinements, ranking, rescue
  fixtures): ~80-120 commits
- **Coordination tooling** (lane registry, mailbox, broker, sweepers,
  worktree inventory, dispatch script): ~150-200 commits
- **General automation hygiene** (fix(automation) etc.): ~142 commits
- **Dependency bumps:** 56 commits
- **CI/release/docs hygiene:** ~80-100 commits
- **Other:** rest

**Substrate-to-LBA-test ratio: approximately 10:1.** The named LBAs are
being scaffolded and re-scaffolded more than they are being tested
against the canonical proof surface.

### Verdict on Q1: useful?

**Yes, but unevenly.** Real engineering value is shipping (ADC, rescue
productization, observe-outcomes). The headline LBA gate (B0 0.0%) has
not moved. The Aragora project IS advancing — just not in the direction
its own canonical docs prioritize as the gate.

---

## Question 2 — UNIQUE

What's genuinely unlikely to be developed by others?

Each entry: name the thing, name the closest external equivalent, name
the difference, classify as new-primitive vs new-combination.

### Strongly differentiated (would not be built by frontier labs / OSS)

#### 1. ADC (Aragora Delegation Contract) — scope+budget orthogonality

- **What:** machine-checkable artifact attached to lane claims and
  subagent dispatches that encodes scope (allowed actions, allowed
  surfaces, denied actions) AND budget (tokens, wallclock, PR count,
  destructive actions) AND goal (acceptance criteria as predicate-oracle
  evaluatables) AND chain (parent contract ID, narrowing-enforced).
- **Closest external:**
  - AWS IAM AssumeRole with session policies (similar shape — narrowed
    permissions, time-bounded — but for human/cloud, not agent chains)
  - CHERI hardware capabilities (similar ocap discipline, silicon-level)
  - MCP / A2A protocols (agent tool/communication protocols, but not
    authority chains)
  - object-capability research (E lang, KeyKOS) — theoretical foundation
- **What's different:** **applies ocap to agent-systems with explicit
  separation of scope from budget, with a non-LLM predicate oracle for
  progress evaluation**. The Anthropic-side classifier polarity is
  ocap-only; the Factory-side auto-mode polarity is gas-only. ADC's
  insight is the orthogonality, and the implementation in 4 versions
  in 48 hours validates the schema-first approach.
- **Classification:** **new combination of known primitives, applied to a
  context where the combination is genuinely novel**. The combination is
  load-bearing.
- **Uncertainty flag:** my training data has limited coverage of private
  frontier-lab agent-permission work post-2024. It's plausible Anthropic
  internal tools or OpenAI's planned long-horizon agent has something
  similar. Likely not identical, but not provably unique.
- **Strength:** 7/10.

#### 2. Predicate Oracle (deterministic non-LLM evaluators)

- **What:** `aragora/policy/predicate_oracle.py` — 9 deterministic
  evaluators (`pr_merged`, `pr_open`, `tests_pass`, `file_exists`, etc.)
  that evaluate ADC acceptance criteria without invoking an LLM.
- **Closest external:** SLSA attestations (similar shape, build provenance
  rather than agent-progress). GitHub Actions success checks (similar
  shape, CI-bounded, not agent-bounded).
- **What's different:** **explicit decoupling of "did the agent finish
  the task" from "did an LLM say it finished"** in the agent-systems
  context. Without this, every progress assertion is debugging-by-LLM
  all the way down. Factory's three-way review called this "the largest
  unaddressed gap" in the original ACAP design; it shipped two days
  later.
- **Classification:** new primitive in the agent-systems context (the
  underlying tech — gh CLI, pytest, file system — is mundane).
- **Strength:** 6/10.

#### 3. Proof-loop pipeline (B0 + TW02 + TW03 recurring)

- **What:** a recurring internal proof loop that (a) defines a bounded
  benchmark corpus, (b) auto-publishes truth surface to repo-tracked
  paths, (c) auto-classifies failures into rescue classes, (d) flags
  repeat classes as productization candidates.
- **Closest external:** SWE-bench (external, static, single-shot); Voyager
  skill library (internal, but Minecraft-specific); MetaGPT process
  receipts (similar shape but not bound to a stable corpus).
- **What's different:** **the loop is internal, recurring, and tied to
  productization of repeat failure classes**. The May 16-17 entries in
  `rescue_productization.json` (admission_class_corpus_synthesis_v1 and
  blocked_auth_failure) are real productization work auto-generated by
  the loop. This is the most "actually load-bearing" piece of substrate.
- **Classification:** new combination of known primitives.
- **Strength:** 7/10. (Would be 9/10 if the verified success rate were
  above zero.)

#### 4. Agent-steering primitive (operator-to-session mailbox)

- **What:** `.aragora/operator-steering/<session>/<msg>.json` —
  asynchronous operator-to-session messages surfaced via
  `operator-snapshot.pending_steering_messages`. Schema is FROZEN at
  v1.0. Initial mailbox phases shipped in PRs #7308 #7310 #7311; PR #7370
  has since merged active-owner routing to PR/branch/worktree owners.
- **Closest external:** none I'm aware of. Slack/email/SMS are
  out-of-band; agent-bridge tools (LangChain's HumanInputRun, etc.)
  are synchronous; CrewAI human-in-the-loop is request/response.
- **What's different:** **asynchronous, agent-pickup-driven, fits inside
  the agent's own Phase 0 read pattern**. The operator doesn't interrupt
  the agent; the agent reads its inbox on its own cadence.
- **Classification:** new primitive.
- **Uncertainty flag:** I have lower confidence here because the design
  space is small and someone may have built this in a private codebase.
- **Strength:** 7/10.

### Moderately differentiated (would maybe be built elsewhere; Aragora's
version is better-structured)

#### 5. Heterogeneous-model debate engine (`aragora/debate/`)

- **What:** propose → critique → revise → synthesize across multi-provider
  agents (Claude/GPT/Gemini/Grok/Mistral) with consensus detection,
  calibration tracking, dissent preservation.
- **Closest external:** MetaGPT (multi-agent role play), AutoGen
  (multi-agent conversation patterns), ChatDev (multi-agent software
  dev), CrewAI (multi-agent task delegation). All of these exist.
- **What's different:** **Aragora's debate is structured around
  consensus + calibration + dissent preservation**, not just role-play
  or task division. The output is a `DebateResult` with explicit
  consensus state, not a chat log to read.
- **Classification:** new combination — the primitives (multi-agent, LLM
  ensemble) are known; the assembly into a decision-integrity output is
  more rigorous than peers.
- **Strength:** 5-6/10.

#### 6. Lane registry + claim-release lifecycle

- **What:** atomic single-writer-per-lane file-locked registry for
  multi-family agent coordination. ID-based collision detection,
  token-overlap detection, status state machine.
- **Closest external:** distributed lock primitives (etcd, Consul) —
  general purpose. No agent-specific equivalent I know of.
- **What's different:** **agent-aware semantics (lane ID = agent's
  intended work scope, owner_session = who's doing it)** plus
  cross-family compatibility.
- **Classification:** new combination.
- **Strength:** 5/10.

### Not differentiated (substitutable)

- Worktree isolation per agent — Git primitive, used everywhere
- Receipt-trio convention (session brief + receipt + journal append) — CI
  audit-log analogue, easy to replicate
- Most CLI verb structure — standard `argparse` + lazy import pattern
- Goal conductor / mission wrapper — many OSS frameworks have similar
- Most of `aragora/automation/` — generic CI/release tooling
- Most of `aragora/server/handlers/` — standard FastAPI

### Punch line on Q2

Aragora's unique value concentrates in:

1. **ADC's scope+budget orthogonality** — load-bearing insight, freshly
   implemented, partly validated by parallel-build demonstration
2. **Predicate Oracle** — non-LLM evaluators in the agent-systems
   context, addresses a known gap others haven't shipped
3. **Recurring internal proof loop with productization** — would be
   trivially useful to many projects but no one has built the
   integrated version
4. **Agent-steering primitive** — async operator-to-session mailbox, no
   external equivalent I'm aware of

These four are the differentiation story. **Everything else Aragora
ships in the 30 days is composable infrastructure that other projects
could substitute.**

Notably: the "decision integrity platform" framing in FOCUS.md is NOT
where the 30-day differentiation actually shipped. The 30-day
differentiation shipped in **agent authority and coordination**, which
is adjacent to but distinct from decision integrity. This is part of
the drift signal (see Q3).

---

## Question 3 — DIRECTION

Is the project drifting?

### Comparison 1: stated direction vs actual activity

NEXT_STEPS_CANONICAL.md (updated 2026-05-13, 6 days old) says explicitly:

> The work now is not "add more speculative autonomy." It is "make
> bounded unattended execution boring."

30-day evidence:

- 142 automation-scoped commits — automation is being continuously repaired,
  not stabilizing
- 56 open PRs at snapshot (39 draft, 17 ready)
- 668 PRs merged in the 30-day GitHub search window → throughput is real,
  not vaporware
- ADC v0.1 merged and ADC v0.2-v0.4 opened as drafts in 48 hours → this is
  exactly "more speculative autonomy" unless framed as a safety substrate
  (which it is, but it is also new substrate, not stabilization of an
  existing one)
- Lane registry + steering mailbox + broker + worktree value inventory +
  dispatch script + sweepers → coordination tooling explosion in the last
  10 days

**The 30-day activity is largely a substrate-building track that is in
tension with the stated "make execution boring" direction.** Both the
ADC and the agent-steering primitive are designed in part to make
autonomous execution safer/more legible, which is in service of "boring"
eventually — but the *current* operating cost is high. The boring state
has not arrived.

### Comparison 2: stated 30-day metric vs measured outcome

| Metric | Target | Actual |
|---|---|---|
| No-rescue truth success rate | ≥50% | **0.0%** |
| Verified truth success rate | (implied >0) | **0.0%** |
| Repeated rescue classes productized | (implied >0) | 2 (#7225/#7228 + #7265) |

The first two are zero. The third has real activity. So the proof loop
IS running, but the rescue-side is closing faster than the
bounded-execution-side is graduating.

### Comparison 3: prior month's stated direction vs this month's reality

NEXT_STEPS_CANONICAL's "What is still missing" list (declared current
as of 2026-05-13):

- "proof that operator status surfaces remain truthful when observed
  from a clean current-`main` checkout instead of a dirty founder
  checkout" — **still missing**
- "proof that the B2 guard holds under repeated bounded runs instead
  of one-off success stories" — **still missing**
- "proof that recurring benchmark publication stays complete and fresh
  on `main` without operator babysitting" — **partially closed** (Q09
  observer truth probe + freshness alerts shipped)
- "broader repair-loop coverage on top of the existing audit trail" —
  partially closed (rescue productization #7225/#7228/#7265)
- "lower-rescue unattended operation on bounded backlogs" —
  **measured at 0.0%; still missing**

Three of five "still missing" items in the canonical doc are still
missing. The doc is 6 days old.

### Comparison 4: doc staleness as a drift signal

| Doc | Declared last-update | File-mtime age | Drift |
|---|---|---:|---|
| THESIS.md | 2026-05-06 | 12d | aligned |
| CANONICAL_GOALS.md | April 18, 2026 | 1d (header stale) | mtime says recent but declared date is 31 days old — header drift |
| FOCUS.md | (no declared) | 50d | **stale** |
| NEXT_STEPS_CANONICAL.md | 2026-05-13 | 6d | aligned |
| AGENT_OPERATING_CONTRACT.md | (no declared) | 20d | mild stale |
| OPERATOR_DELEGATION_POLICY.md | (no declared) | 1d | fresh |

FOCUS.md is 50 days old. The Tier-1 list in FOCUS predates much of the
work shipped this month. If FOCUS still says `debate/`, `gauntlet/`,
`knowledge/`, `ranking/` are the defensible core, and 30 days of work
has gone into ADC + coordination primitives + automation, then either
the strategy doc is wrong OR the actual work is drifting from strategy.

The honest read: **strategy doc is stale, actual work has expanded the
defensible-core list with ADC + steering primitive + proof loop, and
strategy doc should reflect this.**

### Comparison 5: external-proof signal

Per THESIS § Load-bearing assumptions, the cryptographic-receipts LBA
requires testing against design partners. Per CANONICAL_GOALS, the
project is "pre-GA" with SOC 2 readiness at 98%, BYOK customer model,
Free/Pro/Enterprise tiers.

**30-day evidence of design-partner / external-user activity: zero.**

This is a claim about recent testing, not about repository substrate: the repo
does contain older design-partner/wedge assets and compliance docs. They do not
by themselves test the buyer-trust LBA in the current 30-day window.

This is the persistent finding across reviews. The April-17 Opus critique
named it. The May-6 Opus reframe named it. The May-14 Opus / Factory
strategic review named it. It is still un-actioned.

### Drift summary

| Drift dimension | Severity | Direction |
|---|---|---|
| Substrate-to-LBA-test ratio | high | drifting toward substrate (10:1) |
| Headline metric (B0 0.0%) | high | flat for 30 days |
| Design-partner gap | high | unchanged across 3+ review cycles |
| Bus factor | high | unchanged at 1 |
| EU AI Act readiness | medium | deferred; deadline 75 days |
| Defensible-core drift | medium | FOCUS doc stale; real work expanding |
| Automation maintenance cost | medium | 142 automation-scoped commits suggest not "boring" yet |
| Coordination tooling growth | mixed | useful in moderation; volume concerning |

**Most important drift signal:** the project's own canonical document
states the 30-day metric as ≥50% no-rescue completion. The measured
metric is 0.0%. The response over 30 days has been to build more
substrate, not to confront the zero. **Either the corpus is wrong, the
loop is broken, or the LBA is harder than expected.** None of those
three hypotheses has been investigated in 30 days. That is the drift.

---

## Recommendations

These are bounded suggestions, not directives. Operator decides.

### Strong recommendations (act on within next 7 days)

1. **Confront the 0.0% headline.** Pick one of three responses:
   (a) make the corpus easier (start with bounded-bug-fix tasks for which
       a known fix exists in git history; verify the loop can succeed);
   (b) instrument the rescue path so failures attribute to specific causes
       and the dominant cause becomes the next productization target;
   (c) declare the corpus design wrong and replace it with a different
       proof surface (e.g., the ADC-itself-as-test).
   The current path — keep running the loop, keep getting zero, keep
   building substrate around it — has 30 days of evidence that it does
   not move the metric.

2. **One real external touch within 14 days.** The cryptographic-receipts
   LBA cannot be tested without a buyer. The cheapest version: write to
   one specific person (e.g., a friend at a startup, a former colleague
   in compliance, an open-source maintainer with reviewer fatigue) and
   ask "would a debate-receipt for X decision be useful?" One email.
   The April-17 Opus critique is now 32 days old. It will keep
   recurring until it is confronted.

3. **Refresh FOCUS.md to match reality.** The 50-day-old doc still names
   `debate/gauntlet/knowledge/...` as defensible core. 30 days of work
   has added ADC + agent-steering primitive + proof-loop pipeline. A
   1-page refresh acknowledging "the defensible core is now also X, Y,
   Z" makes the strategy doc honest and surfaces the drift question for
   founder review.

### Bounded suggestions (act on within next 30 days)

4. **Bus factor mitigation.** Even one durable contributor outside the
   agent-pool — a real human reading PRs once a week, with merge access
   on a narrow scope — changes the bus-factor-1 finding. Hard to do, but
   the value of even tiny external presence is high.

5. **ADC follow-ons — close the dogfood loop.** The strongest
   demonstration in the 30 days was four agents in parallel authoring the
   ADC stack. First settle the open draft follow-ons (#7358/#7360/#7361);
   then consider v0.7 (three-tier reversibility) and v0.8
   (cross-family adapter), followed by a contract-bound Droid mission.
   That would be the first agent action in the project that is provably
   governed by the protocol the project built to govern such actions.
   Formalize that as an LBA closure.

6. **EU AI Act readiness packet.** 75 days to deadline is not yet
   urgent, but a 1-day audit packet generated from existing
   `aragora/compliance/` surfaces would surface the gap before it's
   urgent. Defer if and only if Phase 0 closes in the next 30 days.

### Things to deliberately not do

7. **Don't expand the agent-coordination tooling further.** Lane registry,
   mailbox, broker, sweepers, value inventory, dispatch script — this
   surface is now broad enough. Further additions risk crossing from
   "useful in service of the work" to "the work itself."

8. **Don't add new LBAs.** The thesis already has six. Adding a seventh
   would be scope creep. The discipline is to test the ones already
   named.

---

## Honesty notes (explicit calibration of this assessment)

- **External-landscape comparison**: my training data has a cutoff in
  late 2024 / early 2025. Frontier-lab agent products and private
  permission systems have likely advanced since. Specific uncertainty:
  Anthropic's internal agent-permission work, OpenAI's planned
  long-horizon agent product, recent Cursor / Devin / Aider features.
  Where I claimed differentiation, treat as "likely but not provably"
  unique.

- **Internal evidence**: I read the git log, PR list, canonical docs,
  ADC docs, B0/TW03 status, observe-outcomes receipts, rescue
  productization map, governance docs in full. I did NOT do exhaustive
  code-level inspection of `aragora/debate/`, `aragora/policy/`, or
  `aragora/server/`. Verdicts on those areas rest on doc-level reading
  plus what I touched in this conversation (ADC v0.1 and the v0.2-v0.4
  draft follow-ons specifically).

- **Operator-context boundary**: I did not rely on raw transcripts or private
  operator-state evidence. This assessment is repo-visible founder-decision
  support; claims that depend on non-repo context should be treated as prompts
  for operator judgment, not tracked facts. I have weighted negative findings
  more heavily than positive ones per the assessment prompt's honesty
  discipline; the actual positive-signal-to-negative-signal ratio in the 30
  days is more balanced than this doc reads.

- **What this assessment is NOT**: a comprehensive technical audit, a
  competitive analysis with verified market data, a financial / GTM
  assessment, or an alignment audit. It is a founder-decision-support
  document, time-boxed to a single qualitative judgment pass.

---

## Bottom line

Aragora is producing real, partly novel infrastructure at high velocity.
The headline named goal is at zero. The drift is recoverable but has
now persisted across multiple review cycles. The cheapest single move
that would change the next 30 days is **confronting the 0.0% headline
directly** rather than building more substrate around it.

The second cheapest move is **one external touch in 14 days**.

Everything else can wait.
