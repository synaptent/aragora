# AI Agent Coordination

**Last updated:** 2026-09-12
**Maintainer:** Update this file when starting/finishing work

> **Operating Contract.** All coordinated work in this repo follows
> [`AGENT_OPERATING_CONTRACT.md`](AGENT_OPERATING_CONTRACT.md): always-allowed vs
> approval-required actions, the "break unreleased branch behavior freely; never
> break main / public API / release flow / CI" rule, and main-red incident mode.
> This document is the *active claims ledger*; the contract is the *rules of
> engagement*. Read the contract before claiming a domain.

---

## Quick Reference

| Track | Focus Area | Key Folders |
|-------|------------|-------------|
| **SME** | Small business features | `aragora/live/`, `aragora/server/handlers/` |
| **Developer** | SDKs, APIs, docs | `sdk/`, `docs/`, `aragora/server/` |
| **Self-Hosted** | Docker, deployment | `docker/`, `scripts/`, `aragora/ops/` |
| **QA** | Tests, CI/CD | `tests/`, `.github/` |
| **Release** | Versioning, changelog | Root files, `docs/` |

---

## Active Work

> **Instructions:** Before starting work, add your session below.
> When done, move to "Recently Completed" section.

### Currently Active

> Since 2026-09-03 the live execution spine is the Receipt-First Mission, epic
> [#9966](https://github.com/synaptent/aragora/issues/9966) (declared the successor gate in
> [`status/NEXT_STEPS_CANONICAL.md`](status/NEXT_STEPS_CANONICAL.md) on 2026-09-07). Mission
> workers record parks, packets and rulings as comments on that epic; this table is the
> cross-lane view for agents that are not mission workers.

| Lane | Owner / agent | Branches | Open PRs | Touched paths |
|------|---------------|----------|----------|---------------|
| Receipt-First mission (M1–M3) | Codex / Factory workers via `scarmani` | `rf/*`, `codex/*` | [#9979](https://github.com/synaptent/aragora/pull/9979), [#9988](https://github.com/synaptent/aragora/pull/9988), [#10013](https://github.com/synaptent/aragora/pull/10013), [#10051](https://github.com/synaptent/aragora/pull/10051) (all Tier 4, awaiting repair/restack + settlement) | `aragora/gauntlet/`, `aragora-verify/`, `aragora/swarm/`, `scripts/baselines/`, `.github/workflows/metrics-drift.yml`, `deploy/` |
| Reliable SDK consumption (Tier 3, parked drafts) | Codex via `scarmani` | `codex/*` | [#10014](https://github.com/synaptent/aragora/pull/10014), [#10015](https://github.com/synaptent/aragora/pull/10015), [#10056](https://github.com/synaptent/aragora/pull/10056) | `sdk/python/`, `sdk/typescript/` |
| P4B handlers decomposition (batch 1 of 4) | Codex / Factory worker via `scarmani` | `structex/*` | [#10000](https://github.com/synaptent/aragora/pull/10000) (head `03ddc3dc`, needs a fresh quorum collection after the 2026-09-07 repair) | `aragora/server/handlers/` (moves behind `MOVED_MODULES` shim) |
| Readiness mission M1–M7 (stacked drafts, operator review) | `scarmani` | `readiness/*` | [#9982](https://github.com/synaptent/aragora/pull/9982) (M1, grounded P2 on `uv.lock` cooldown), [#9997](https://github.com/synaptent/aragora/pull/9997), [#10005](https://github.com/synaptent/aragora/pull/10005), [#10027](https://github.com/synaptent/aragora/pull/10027), [#10049](https://github.com/synaptent/aragora/pull/10049) (M5, conflicts with `main`), [#10052](https://github.com/synaptent/aragora/pull/10052), [#10060](https://github.com/synaptent/aragora/pull/10060) | `.github/workflows/`, `Makefile`, `scripts/ci/`, `scripts/baselines/`, `aragora/live/`, `docs-site/` |
| Frontier model refresh (Tier 4) | `scarmani` | `feat/frontier-model-refresh*` | [#9989](https://github.com/synaptent/aragora/pull/9989), [#9992](https://github.com/synaptent/aragora/pull/9992) | `aragora/agents/`, `aragora/config/`, model catalog |
| Stage-Gate Conductor (2-hourly log) | Claude Code sessions via `an0mium` | none | log anchor [#9942](https://github.com/synaptent/aragora/issues/9942) | comments only |
| Vision-tier incubator (deferred track, drafts) | Claude Code via `an0mium` | `vision-incubator/*`, `claude/*` | [#10006](https://github.com/synaptent/aragora/pull/10006), [#9956](https://github.com/synaptent/aragora/pull/9956), [#9953](https://github.com/synaptent/aragora/pull/9953), [#10038](https://github.com/synaptent/aragora/pull/10038), [#10040](https://github.com/synaptent/aragora/pull/10040), [#10054](https://github.com/synaptent/aragora/pull/10054), [#10057](https://github.com/synaptent/aragora/pull/10057) | `aragora/reasoning/`, `aragora/genesis/`, `aragora/epistemic/`, `aragora/protocols/a2a/`, `aragora/reputation/`, `aragora/cli/` |
| Operator settlement session | Claude Code via `an0mium` | `claude/project-status-review-*`, `claude/park-*`, `claude/fix-*`, `claude/contract-drift-*` | this doc PR, [#10025](https://github.com/synaptent/aragora/pull/10025), [#10026](https://github.com/synaptent/aragora/pull/10026), [#10033](https://github.com/synaptent/aragora/pull/10033), [#10034](https://github.com/synaptent/aragora/pull/10034) | `docs/status/`, `docs/COORDINATION.md`, `.github/workflows/monitor.yml`, `.github/workflows/contract-drift-governance.yml`, `deploy/Dockerfile.backend`, `aragora/server/validation/entities.py` |

---

### Recently Completed (Last 7 Days)

| Date | Agent | Task | Issue | Commit |
|------|-------|------|-------|--------|
| 2026-09-11 | Codex via scarmani | Receipt CLI hardening: fail-closed export, no-traceback input errors | #9966 | 67ac6ba4, c30b897a |
| 2026-09-11 | Codex via scarmani | Provider-neutral Hetzner production origin (deploy pack, M3) | #9391, #9966 | e3ce08bb |
| 2026-09-11 | Codex via scarmani | Import-cycle ratchet as non-required check (M0/M2) | #9966 | 2d9b664c |
| 2026-09-11 | Codex via scarmani | Cache/reputation regression signals recovered | - | d29df84e |
| 2026-09-10 | Codex via scarmani | Live app dependency advisories (Next.js, sharp, postcss); dialect-aware migrations | - | 79b1be10, c3380f9e, 4c2aabb3 |
| 2026-09-10 | Codex via scarmani | Atlas pairwise summary, Atlas docs-site pages, scoreboard rows 6/8 (M2) | #9966 | a93210f1, e8026c36, 78b3354b |
| 2026-09-08 | Codex via scarmani | Packaging: cryptography in base deps, Python 3.10 quickstart (M1) | #9966 | 8919b620 |
| 2026-09-07 | Codex via scarmani | Advisory dissent summaries + hardening (M2, ruling 11) | #9966 | 187024c8 |
| 2026-09-06 | Codex via scarmani | Test hardening cluster: exact assertions replace blanket `except Exception` (#10002–#10009) | #9966 | 3ee6b445, 20cd29a9, ba72aa50, df1aef4a |
| 2026-09-06 | Codex via scarmani | Dependency advisories patched (aragora/live, webview, docs-site) | - | 83b28699, 1c8307b2, 1b365c88 |
| 2026-09-06 | an0mium | Time-aware truth report for claims | #9215 | df3256a7 |
| 2026-09-05 | Codex via scarmani | ODR file-based signing keys, fail-closed (M1) | #9966 | 3885146d |
| 2026-09-05 | Codex via scarmani | P4B handlers decomposition design doc | - | f64b3858 |
| 2026-09-04 | scarmani | Release v2.10.0 (M0) | #9966 | be07ea5b |
| 2026-09-03 | Codex via scarmani | Disagreement Atlas v1, receipt-first scoreboard, import-cycle repairs 144→138 (M0) | #9966 | b512e130, dd33d01b, f869a70b..eed97a23 |
| 2026-02-16 | Claude Opus 4.7 | Working tree cleanup + worktree consolidation | - | db54711..fa10308 |
| 2026-02-16 | Claude Opus 4.7 | Exception handler narrowing (debate, server, workflow) | - | 93edccef..47c7f89 |
| 2026-02-16 | Claude Opus 4.7 | SDK cost estimation + TS features namespace | - | b301d86 |
| 2026-02-16 | Claude Opus 4.7 | CI: TypeScript SDK type check job | - | 13efc0c |
| 2026-02-16 | Claude Opus 4.7 | Frontend: debate export UX + cost error handling | - | (in b301d86) |
| 2026-02-15 | Claude | Worktree sessions script + dogfood tests (14 tests) | - | 52c7203..9225a99 |
| 2026-02-14 | Claude | Handler routing bug class fixes (10 handlers) | - | various |
| 2026-02-13 | Claude | Handler test suite: 19,776 tests, 0 failures | - | various |

---

## Domain Ownership

To avoid conflicts, agents should stay within their assigned domains:

```
Session 1 claims: aragora/connectors/
Session 2 claims: aragora/server/handlers/
Session 3 claims: tests/
```

### Current Claims

*No domains currently claimed*

---

## Issue Priority by Track (historical, February 2026)

> Superseded for execution priority by the Receipt-First Mission [#9966](https://github.com/synaptent/aragora/issues/9966) and
> [`status/NEXT_STEPS_CANONICAL.md`](status/NEXT_STEPS_CANONICAL.md). Retained because the track
> folders and starter prompts in [`AGENT_ASSIGNMENTS.md`](AGENT_ASSIGNMENTS.md) still reference these issues.

### P0 - Must Do (Blocking Release)

**SME Track:**
- [ ] #100 SME starter pack GA documentation
- [ ] #99 ROI/usage dashboard ← **next up**
- [ ] #92 RBAC-lite for workspace members
- [ ] #91 Workspace admin UI ← **next up**

**Developer Track:**
- [x] #103 API coverage tests (208,000+ tests, 3,000+ API ops)
- [x] #102 SDK parity pass #2 (100% TS/Python parity)
- [ ] #94 SDK docs portal / developer quickstart ← **next up**

**Self-Hosted Track:**
- [ ] #106 Production deployment guide ← **next up**
- [ ] #105 Self-hosted GA sign-off / checklist
- [x] #96 Backup and restore scripts (BackupManager implemented)

**QA Track:**
- [x] #107 E2E smoke tests (CI workflows active)
- [x] #90 Integration test matrix (randomized seeds: 12345, 54321, 99999)

### P1 - Should Do

- [x] #108 Nightly CI smoke test runs (implemented in CI)
- [ ] #104 Developer portal GA
- [ ] #101 User feedback collection
- [ ] #98 Automated changelog generation

---

## How to Use This File

### Starting a Session

1. Check "Currently Active" - avoid working on same files
2. Add your session using the template
3. Claim a domain if doing substantial work
4. Reference an issue number if applicable

### During Work

- Update status if blocked
- Note any files you unexpectedly needed to modify
- If you need files someone else claimed, coordinate first

### Finishing a Session

1. Move your entry to "Recently Completed"
2. Release any domain claims
3. Note the commit hash
4. Update issue status on GitHub if applicable

---

## Conflict Resolution

If you encounter merge conflicts or overlapping work:

1. **Don't force push** - you may overwrite others' work
2. **Pull latest:** `git pull origin main`
3. **Check this file** - see who was working on conflicting files
4. **Ask Claude to resolve** - AI is good at semantic merges
5. **Run tests:** `pytest tests/ -x --timeout=60`

---

## Two-Pass Builder/Verifier Workflow

Every autonomous or high-churn coding lane uses a two-pass workflow:

### 1. Builder pass

- Produce the narrowest draft implementation that satisfies the issue contract.
- Optimize for velocity — draft PR only.
- Bounded scope with explicit tests and acceptance criteria.
- No merge authority.

### 2. Verifier pass

- Independent read-only review by a different agent or model.
- Check for semantic regressions, integration drift, scope violations, stale assumptions.
- Merge blocked until this pass is clean.

### 3. Merge gate

- Only after both passes succeed.
- Required CI checks green.
- No unresolved review findings.

**Key principles:**
- Speed comes from iteration velocity, not from relaxed standards.
- The verifier role is process-defined, not brand-defined — any agent can fill either role.
- The builder should aim to ship on the first pass; the verifier is a safety net, not a license.

**Proof case:** PR #880 (file-scope enforcement). Builder pass found the main fix quickly. Independent review caught two real semantic regressions (glob matcher too narrow, lease metadata not persisted). Second pass repaired both before merge.

---

## Communication Shortcuts

When starting a Claude session, paste this:

```
Check .claude/COORDINATION.md for active work by other agents.
Before making changes, tell me your plan.
Stay within: [YOUR ASSIGNED DOMAIN]
Update COORDINATION.md when done.
```

---

## Test Commands

Quick validation before committing:

```bash
# Fast check (2 min)
pytest tests/ -x --timeout=60 -q -m "not slow"

# Full suite (10+ min)
pytest tests/ --timeout=120

# Specific area
pytest tests/server/ -v --timeout=60
pytest tests/connectors/ -v --timeout=60
```

---

## Autonomous Orchestration (Experimental)

Aragora can orchestrate its own development using the `AutonomousOrchestrator`:

```python
from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

orchestrator = AutonomousOrchestrator()

# Execute a high-level goal
result = await orchestrator.execute_goal(
    goal="Maximize utility for SME SMB users",
    tracks=["sme", "qa"],
    max_cycles=5,
)

# Or focus on a specific track
result = await orchestrator.execute_track(
    track="developer",
    focus_areas=["SDK documentation", "API coverage"],
)
```

**Components:**
- `AgentRouter`: Routes subtasks to appropriate agents based on domain
- `FeedbackLoop`: Handles verification failures with retry/redesign logic
- `TrackConfig`: Defines folders, protected files, and agent preferences per track

**Safety Features:**
- Domain isolation prevents file conflicts
- Core track limited to 1 concurrent task
- Approval gates for dangerous changes
- Checkpoint callbacks for monitoring

See `aragora/nomic/autonomous_orchestrator.py` for full API.

---

## Recent Patterns to Follow

Based on recent commits, follow these patterns:

- **Commit messages:** `type(scope): description` (e.g., `fix(tests): add mock`)
- **Co-author:** Add `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`
- **Test before commit:** Always run tests
- **Small commits:** One logical change per commit
