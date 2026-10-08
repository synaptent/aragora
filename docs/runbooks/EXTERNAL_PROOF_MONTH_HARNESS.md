# External-Proof Month — Execution Harness

**Companion to:** `docs/plans/2026-07-09-thirty-day-external-proof-month.md`
**Design goal:** execute the 30-day plan with exactly **three operator-facing
surfaces** — one Claude Code session, one Codex session, one Factory mission —
plus the always-on autonomous substrate. Human input only at the named
touchpoints (§5); everything else is monitoring (§6). Fixed-cost subscriptions
carry the loops; metered spend is confined to one surgical lane (§7).

---

## 1. Architecture

```
                        ┌──────────────────────────────────────────┐
                        │  AUTONOMOUS SUBSTRATE (launchd, no human) │
                        │  merge_executor (10-min tick, armed)      │
                        │  harvest_outcomes (daily 07:15)           │
                        │  boss_loop (issue-shaped work feed)       │
                        │  nightly pristine-main halt-file (#9058)  │
                        │  throughput snapshot + weekly digest      │
                        │  PR watch daemons, worktree maintainer    │
                        └───────▲──────────────────▲───────────────┘
                                │ receipts/ledger   │ issues/PRs
   ┌────────────────┐   ┌───────┴────────┐   ┌──────┴─────────┐
   │ CLAUDE CODE     │   │ CODEX          │   │ FACTORY        │
   │ "Conductor &    │   │ "Builder"      │   │ "Long Builder" │
   │  Settler"       │   │ goal-cycle loop│   │ 1 mission at a │
   │ /loop self-paced│   │ (existing      │   │ time, tightly  │
   │ + fable-goal-   │   │ conductor      │   │ specced, token │
   │ cycle each wake │   │ cadence)       │   │ budget capped  │
   └───────▲────────┘   └───────▲────────┘   └──────▲─────────┘
           │                     │                    │
           └───────────── FOUNDER (§5: ~6 touchpoints, ~2h/week) ─────────────┘
```

**Division of labor by demonstrated strength:**

| Surface | Owns | Why |
|---|---|---|
| **Claude Code** (Claude Max, fixed) | Settlement pipeline (the proven recipe), plan tracking against exit criteria, weekly digest assembly, Tier-4 packet prep, adversarial review passes, Factory mission briefs, replan triggers | This session proved it: orchestration, settlement, verification. The /loop + fable-goal-cycle pattern defeats the stops-after-minutes problem |
| **Codex** (Codex Max, fixed) | Implementation of the week's work items (#8230 pieces, crux-card wiring, quality ratchet: mypy −100/skips shrink, stranger-test frictions), doubles as the openai reviewer harness | The Codex conductor loop already runs (cycles observed at 82/115/175+); it just needs its mission file pointed at this plan |
| **Factory** (metered — surgical) | ONE long-horizon, crisply-specced build per fortnight where days-long persistence beats loop restarts: W2 = #8230 Art.14 attestation end-to-end; W4 = Crucible-hole demo build | Factory excels at single-shot missions and fails at loop-tending (recorded finding); token burn is controlled by giving it *builds*, never review/settlement churn |

**Dogfooding**: every merge flows through the quorum gate with receipts; goal
selection runs under the armed work-mix budget (`ARAGORA_PR_ROUND_BUDGET=6`
live; advisory gate now, enforcing at W3 per #9045 entry criteria); deadlocks
route to the adjudicator; outcomes fold back via harvest; the plan's own
progress is measured by the throughput ledger the plan shipped.

## 2. The three prompts (paste-ready)

### 2a. Claude Code — start once, self-sustains via /loop

```
/loop Run one conductor cycle for the External-Proof Month
(docs/plans/2026-07-09-thirty-day-external-proof-month.md). Each cycle:
(0) STEER — check the operator-steering mailbox first
    (python3 scripts/read_operator_steering.py --lane-id <LANE_ID> --json;
    use --pr/--branch when that is the only selector you know). If a
    message was read, write an outcome receipt
    (--outcome obeyed|held|stale|superseded|blocked|completed) BEFORE
    mutating any lane state, per AGENTS.md.
(1) SENSE — read the current week's exit criteria; once #9048 has merged,
    run scripts/throughput_ledger.py snapshot + work_mix_gate check (those
    CLIs ship with #9048 — skip them while it is unmerged); check
    gh pr/issue state for the week's named items and any replan triggers.
(2) SETTLE — drain anything settlement-stable using the proven recipe
    (3 settlement flags + collect --json → --prepared-json --apply →
    reconcile_merge_quorum → auto_merge_quorum_green). Respect park policy
    (≤3 attempts/head) and reviewer quota policy (claude reviewer only for
    product PRs and Tier 3-4; openai for routine).
(3) DISPATCH — if the Codex conductor's queue is empty, write its next work
    order (one bounded item from the current week); if a Factory mission
    slot is open per the harness runbook, draft the mission brief and queue
    it in the founder decision queue for launch approval.
(4) ACCOUNT — append cycle notes to the month scoreboard issue; escalate at
    most ONE named crux to the founder decision queue; never batch nits.
Tier 3-4 always prepares packets, never settles. If a replan trigger from
plan §4 has fired, stop the loop and page the founder instead of continuing.
```

Claude Code's /loop self-pacing keeps the session alive for days: each wake is
one bounded cycle, background tasks bridge the gaps, and the harness re-invokes
on completion. When a heavy overnight batch is wanted instead, switch to the
`elves-aragora` skill (its batches gate on receipt-backed quorum natively).

### 2b. Codex — update the existing conductor mission file

The Codex conductor loop already runs on launchd. Point it at the plan by
replacing its operator-context mission statement with:

```
MISSION (Jul 9 – Aug 9): execute the CURRENT WEEK of
docs/plans/2026-07-09-thirty-day-external-proof-month.md. Work ONLY items
from the week's supporting list or work orders dropped by the Claude
conductor. One bounded item per cycle: check the operator-steering mailbox
first (python3 scripts/read_operator_steering.py --lane-id <LANE_ID> --json,
or --pr/--branch) and write an outcome receipt for any message read BEFORE
mutating lane state (AGENTS.md protocol); then implement in an isolated
worktree, tests first, draft PR, hand to settlement (never merge yourself;
the merge-quorum gate is the sole settlement authority). Standing constraints:
work-mix budget applies (product-class work preferred; substrate only from
explicit work orders); ≤800 LOC per PR; regenerate METRICS.md + doc_stats in
the SAME commit as any test-count change; merge origin/main before
regenerating (drift gate computes on the merge commit). Consult Fable
(scripts/consult_claude.py) when blocked >2 cycles, then park with a receipt.
```

### 2c. Factory — one mission per fortnight, budget-capped

Launch (founder, ~2 min, after reviewing the brief the Claude conductor
drafts): `python3 scripts/agent_bridge.py launch --name external-proof-month-build --agent factory --autonomous --file <brief.md>`
with a brief of this shape:

```
MISSION: <W2: implement #8230 Art.14 human-oversight attestation end-to-end |
W4: build the Crucible-hole enterprise decision-brief demo>.
FILES: <named modules from the plan>.
ACCEPTANCE: <the week's exit criteria verbatim, incl. tests + draft PR(s)
≤800 LOC each + docs regenerated per drift-gate rule>.
CONSTRAINTS: check the operator-steering mailbox before mutating lane state
and write an outcome receipt for any message read
(python3 scripts/read_operator_steering.py --lane-id <LANE_ID> --json);
never merge or mark ready; never touch merge-authority code,
workflows, or protected files; park-with-receipt on any blocker; stop at
<N> hours or <token budget> — partial work committed to branch is fine,
the harvest daemon collects strands.
```

Factory's quota exhaustion is handled by design: missions are scoped so that
running out mid-mission leaves committed branch work that harvest reclaims and
Codex can finish. Never give Factory open-ended or review-loop work.

## 3. Autonomous substrate — schedule (all fixed-cost or free)

| Daemon | Cadence | State |
|---|---|---|
| merge_executor (Tier 0-2, receipted, halt-file guarded) | 10 min | ARMED |
| harvest_outcomes | daily 07:15 | ARMED |
| boss_loop worker feed | continuous | running |
| PR-keyed rerun budget (`ARAGORA_PR_ROUND_BUDGET=6`) | per reconcile | ARMED |
| nightly pristine-main full-shard → halt-file | nightly | arm on #9058 merge (Jul 11) |
| `throughput_ledger.py snapshot` | daily | arm on #9048 merge (Jul 11) |
| `weekly_digest.py` → founder | weekly Fri | arm on #9048 merge |
| steering_conductor (1 operator message/cycle max) | per cycle | running |

## 4. Reviewer & quota policy (the lesson of Jul 9)

- **claude reviewer** (shares the Claude Max sub with the conductor): reserve
  for product PRs and Tier 3-4 packets; never spend on docs/tooling PRs.
  Weekly cap awareness: the wall resets ~3am CT on its weekly window
  boundary (this window: Jul 11).
- **openai reviewer** (Codex Max): the routine western-frontier signal.
- **grok/deepseek via OpenRouter** (small metered): redundancy only, enabled by
  `ARAGORA_ENABLE_OPENROUTER_REVIEWER_FALLBACK=1`.
- Evidence-last discipline: CI fully green → freeze head → one collect → post →
  reconcile → merge. Never collect against a moving head.

## 5. Human touchpoints (the complete list, ~2 h/week)

| When | What | Est. |
|---|---|---|
| Jul 9-10 (once) | Recruit the #8858 outsider human; approve prod signing-key deployment | 30 min |
| Jul 11+ (as queued) | Tier-4 exact-head settlements (#8406, W3 gate-flip PR, anything touching merge authority) | 5 min each |
| ~Jul 14 (once) | Approve + launch Factory mission 1 (#8230 brief) | 10 min |
| Weekly Fri | Digest review: throughput table, work-mix, kill-switch state, ONE escalated crux, next-week goals | 30 min |
| W2-W3 (once) | Pentest vendor pick → SOW signature | 45 min |
| ~Jul 30 (once) | Earned-claim review of the EU AI Act bundle before publication | 30 min |
| W4 (once) | Demo distribution decision (Crucible-orphan outreach) + Factory mission 2 launch | 20 min |

Everything else that looks like it needs you is a bug in the harness: the
adjudicator escalates one named crux, the steering conductor sends at most one
message per cycle, and replan triggers stop the loop rather than improvising.

## 6. Monitoring (visible progress, ~5 min/day)

- **The month scoreboard issue** (created at kickoff, linked from epic #9039):
  the Claude conductor appends one status comment per cycle — week, exit
  criteria checked off, ledger numbers, parked items.
- **Weekly digest** (Fri): the single authoritative artifact — product share
  WoW, external artifacts published, settlement latency, freeze state,
  spot-audit sample.
- Ad hoc: `gh pr list` any time; `python3 scripts/work_mix_gate.py check`
  and `python3 scripts/weekly_digest.py` are read-only and available once
  #9048 merges (they ship with it — see §3 arm dates).

## 7. Cost model

- **Fixed (carries ~95% of the work):** Claude Max (conductor + claude
  reviewer, budgeted per §4), Codex Max (builder loop + openai reviewer).
  No account pooling; one claude reviewer per PR (TOS-clean).
- **Metered (capped):** Factory — two missions this month, each with explicit
  hour/token stop conditions and harvest-recoverable output; OpenRouter
  fallback reviewers (cents per review, redundancy only).
- **Rule:** anything that loops lives on a subscription; anything metered gets
  a single-shot brief with a stop condition.

## 8. Failure protocol

- Reviewer wall / API quota → park-with-receipt (≤3 attempts/head), continue
  other lanes; never spin on a walled resource.
- Main red → halt-file stops all merging (already wired); lanes switch to
  repair; founder paged only if >24 h.
- Factory quota out → strands committed to branch; harvest files salvage;
  Codex finishes from the receipt.
- Any plan §4 replan trigger → the Claude conductor STOPS looping and
  escalates; the plan is renegotiated with the founder, never silently bent.
