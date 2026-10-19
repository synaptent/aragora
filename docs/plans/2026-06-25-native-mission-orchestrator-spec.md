# Native Mission Orchestrator — Spec (Factory protocol → Aragora)

Mission progress projects into the canonical
[Agent Operating Loop](../architecture/agent-operating-loop.md); the loop does not
replace or duplicate `MissionState`.

**Date:** 2026-06-25
**Status:** Design / buildable backlog
**Author:** distilled from ~13 days operating Factory's Structural Excellence mission (Epic #8257) on this repo
**Thesis:** Aragora already has the autonomous *loops*. It lacks the unglamorous **mission-state + durable-resume + headless-runtime** layer that lets Factory run for days. That layer is mostly *glue over existing modules*, plus one ops change (run on API, not a subscription CLI). Build it and you get the walk-away unlock **and** a differentiated product: autonomous engineering where every change is debate-gated and produces a decision receipt.

---

## 1. Why Aragora can't (yet) do what Factory does

Not a capability gap — a **cohesion + survivability + runtime** gap. Diagnosed in the existing `native mission orchestrator` plan: four overlapping orchestrators, none unified; halting traces to the harness/identity layer, not the loops.

| What Factory has | Why it matters |
|---|---|
| One canonical **mission-state file** reconstructed from disk each tick | Survives 402 / crash / daemon-reap — the orchestrator is **stateless between runs** |
| **Handoff → triage → dismiss** protocol | Discovered work is tracked, never lost; the queue self-extends |
| **Validator injection** on milestone completion | Automatic quality seal; no milestone closes unvalidated |
| A persistent **library** workers read/write each run | Institutional knowledge compounds; later workers are smarter |
| Clean **orchestrator / worker / validator** role split + per-role model routing | Opus judgment, cheap workers, cross-family validation |
| A **runtime that isn't a personal subscription CLI** | No 402 ceilings, no single-account contention |

Aragora has analogues for all six — they're just not wired into one survivable engine.

---

## 2. Factory's mission protocol, distilled to 6 primitives

These are the things to replicate. Everything else is detail.

1. **MissionState (one JSON).** `{goal, milestones[ordered], features[ordered]{id, description, skill, milestone, preconditions, expectedBehavior, fulfills[assertionIds], status, workerSessionIds}}`. The single source of truth. The orchestrator reads it, advances it, writes it — every tick.
2. **Stateless tick loop.** pick next `pending` feature → spawn/resume a worker in an isolated worktree → worker drives the merge-gate → returns a **handoff** → orchestrator triages handoff, mutates MissionState (mark complete / record proposed follow-ups as advisory notes, or insert only explicitly accepted follow-up features), persists durable guidance → repeat. No in-memory state survives a tick; everything is on disk.
3. **Validation contract.** N checkable assertions (`VAL-*`). Features `fulfill` assertions. On milestone completion the orchestrator **injects validator features** (a *scrutiny* gate = lint/typecheck/test + per-feature review, and a *user-testing* gate = assertion verification). Milestone seals only when its assertions pass.
4. **Handoff schema + triage.** Worker returns `{successState, discoveredIssues[], whatWasLeftUndone, skillFeedback}`. Orchestrator must *dispose of every item* (track into a feature / document / dismiss with justification) before advancing. This is the anti-drift mechanism.
5. **Library + approvals ledger.** A shared, mission-scoped knowledge surface (`merge-gate.md`, `environment.md`, gotchas, tech-debt) workers read each run; plus an **append-only operator-approvals ledger** for every human decision.
6. **Operator-escalation fork.** When a worker hits a genuine either/or (Tier-3 settlement, scope decision, contention) it returns to the orchestrator, which surfaces *one* structured question to the operator, records the answer in the ledger, and resumes. Never loops on an operator-gated blocker.

---

## 3. Component mapping (Factory primitive → existing Aragora module → gap)

| # | Factory primitive | Existing Aragora module(s) | Gap to close |
|---|---|---|---|
| 1 | MissionState file | `nomic/task_decomposer.py` (goal→tracks→subtasks), `nomic/meta_planner.py` (debate-driven prioritization), swarm work-orders | **No single canonical state schema** shared across orchestrators. Define `MissionState` + load/save. |
| 2 | Stateless tick loop | `swarm/boss_loop.py` (the tick engine, ~5.3k LOC), `swarm/lane_supervisor.py` / `lane_dispatcher.py` / `lane_cycle.py` | boss_loop drives PRs but is **not goal/milestone-aware** and doesn't reconstruct-from-disk. Wrap its tick with a MissionState advance step. |
| 3 | Worker + worktree + gate | `swarm/boss_worker_lifecycle.py`, `aragora/worktree/`, `swarm/quorum_evidence.py`, `cli/commands/review_queue.py` (~5.5k LOC) | **Gate already excellent** (we operated it all session — this is the *advantage*). Missing: structured **handoff return channel**. |
| 4 | Validation contract + validator injection | `aragora/evaluation/` (LLM-as-judge, 8 dims), `aragora/verification/`, `aragora/audit/` | **No assertion model tied to features; no auto-injection on milestone seal.** Add assertion schema + injection hook. |
| 5 | Handoff triage / dismiss | `nomic/dev_coordination/` (completion receipts, salvage queue) | Closest existing piece. Add the **handoff schema + triage/dismiss loop**. |
| 6 | Library + approvals ledger | `knowledge/mound/` (KM), `memory/continuum/`, `aragora/approvals/` (action tokens) | KM exists; **not wired as the per-mission read/write working library**. Add mission-scoped library surface + append-only ledger. |
| 7 | Operator escalation | `aragora/approvals/`, `control_plane/notifications.py` (~970 LOC) | Have notification + approval primitives; need the **fork→escalate→record→resume** wrapper. |
| 8 | Role-based model routing | `aragora/routing/` (Pareto optimizer), `aragora/agents/` | Have routing; bind **per-role** (orchestrator=flagship, worker=cheap/flagship, validator=cross-family). |
| 9 | Headless runtime (no 402) | `aragora/server/`, EC2 deploy (api.aragora.ai live), `config/secrets.py` (AWS Secrets Manager) | **The key gap is ops, not code:** run orchestrator+workers on **API keys via Secrets Manager, headless on EC2** — not subscription CLIs. |

**Read this table as good news:** 7 of 9 rows are "wire existing module," 1 is "the gate is already your moat," and only the runtime row is a genuine new build (and it's ops wiring, not new algorithms).

---

## 4. The 4 real gaps (everything else is glue)

1. **Canonical `MissionState` + stateless reconstruct-from-disk.** The spine. Without it, no survivability.
2. **Validator injection + assertion contract.** The quality seal. Reuse `evaluation/` LLM-judge.
3. **Handoff schema + triage/dismiss loop.** The anti-drift mechanism. Build on `nomic/dev_coordination/`.
4. **Headless API runtime.** Kills the 402/contention class entirely. Ops wiring on existing EC2 + Secrets Manager.

---

## 5. Buildable backlog (phased — each phase ships something usable)

### Phase A — The spine (MVP: a mission that survives a kill)
- **A1.** Define `aragora/missions/state.py`: `MissionState` dataclass + JSON load/save (schema = §2.1). Mirror Factory's `features.json` exactly — it's a proven schema.
- **A2.** `aragora/missions/orchestrator.py`: stateless tick — `next_pending() → dispatch → await handoff → triage → advance → persist`. **Wrap `swarm/boss_loop.py`'s tick**, don't replace it.
- **A3.** Handoff schema (`{successState, discoveredIssues, whatWasLeftUndone, skillFeedback}`) returned by `boss_worker_lifecycle.py`; triage/dismiss loop on `nomic/dev_coordination/`.
- **A4.** Resume: orchestrator re-derives live state (open PRs, worktrees, branch heads) from GitHub + disk at the start of every tick — never trusts in-memory carry-over. (This is *exactly* what made Factory survive every 402 this week.)
- **Exit test:** `kill -9` the orchestrator mid-feature; relaunch; it resumes from the checkpoint with zero lost work.

### Phase B — The quality seal
- **B1.** Assertion contract: `aragora/missions/contract.py` — `VAL-*` assertions, `validation-state.json`, feature `fulfills` mapping.
- **B2.** Validator-injection hook: on milestone completion, inject a *scrutiny* feature (lint/typecheck/test + per-feature review via `evaluation/` judge) and a *user-testing* feature (assertion verification). Milestone seals only when assertions pass.
- **Exit test:** a feature that "passes" but breaks an assertion is caught by the injected validator and reopened.

### Phase C — Knowledge + escalation
- **C1.** Mission library surface on `knowledge/mound/` — workers read `merge-gate.md` / `environment.md` / gotchas each run, write learnings back. Append-only `operator-approvals.md` ledger.
- **C2.** Operator-escalation fork: worker → orchestrator → one structured question (`control_plane/notifications.py` + `approvals/`) → record in ledger → resume. Hard rule: never loop on an operator-gated blocker.

### Phase D — The runtime (the walk-away unlock)
- **D1.** Per-role model routing via `aragora/routing/`: orchestrator=flagship, worker=cheap-or-flagship per tier, validator=cross-family.
- **D2.** **Headless on EC2 via API keys** (Secrets Manager through `config/secrets.py`) — *not* subscription CLIs. This removes the 402 ceiling and single-account contention class entirely. Relay-with-timeout instead of hard-halt.
- **Exit test:** launch a mission, close your laptop, it runs for days and only pings you at genuine operator forks.

### Phase E — The moat (differentiation)
- **E1.** Every feature ships with the merge-quorum gate result **as a signed decision receipt** (`gauntlet/receipts.py` + `review_queue.py` already produce these). Surface a mission scorecard: "N features, each adversarially vetted + receipted."
- **E2.** Product framing: *"Autonomous engineering where every change is debate-gated and produces an audit receipt."* This is the thing Factory/Devin/Cursor do **not** have — it's your tagline applied to code.

---

## 6. The wedge

Factory has the mission engine; you already built the governance layer it lacks (adversarial merge-quorum gate + debate + signed receipts). Don't build a Factory clone — build **Factory with provenance**: the only autonomous-engineering system where every merge is heterogeneous-model-vetted and produces a tamper-evident decision receipt. That's defensible. It's also dogfood: *Aragora governs Aragora's own development*, which is itself the demo.

---

## 7. Sequencing recommendation

1. **Finish/park the current Factory mission at the P4a boundary** (P0–P3 value is banked; P5–P7 is low-ROI hygiene).
2. **Phase A is the whole game** — a mission that survives a kill is 80% of Factory's magic. Build it on `boss_loop.py`'s tick. Ship it; run a *small* real mission on it (e.g. "land the 3 misc-2 cleanup PRs") as the proving ground.
3. **Phase D (headless API runtime) in parallel** — it's ops, not code, and it's what ends the babysitting. Worth doing early.
4. B, C, E layer on once A+D prove out.

**The 13 days you spent operating Factory were free requirements research for Phase A–C.** Every pain (handoff dismissal, validator injection, the bright-line settlement, the foreign-commit guard, single-fleet discipline) is a spec line above. Harvest it.
