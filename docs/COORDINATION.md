# AI Agent Coordination

**Last updated:** 2026-03-05
**Maintainer:** Update this file when starting/finishing work

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

*(No sessions currently claimed — update when starting work on a domain)*

---

### Recently Completed (Last 7 Days)

| Date | Agent | Task | Issue | Commit |
|------|-------|------|-------|--------|
| 2026-02-16 | Claude Opus 4.6 | Working tree cleanup + worktree consolidation | - | db54711..fa10308 |
| 2026-02-16 | Claude Opus 4.6 | Exception handler narrowing (debate, server, workflow) | - | 93edccef..47c7f89 |
| 2026-02-16 | Claude Opus 4.6 | SDK cost estimation + TS features namespace | - | b301d86 |
| 2026-02-16 | Claude Opus 4.6 | CI: TypeScript SDK type check job | - | 13efc0c |
| 2026-02-16 | Claude Opus 4.6 | Frontend: debate export UX + cost error handling | - | (in b301d86) |
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

## Issue Priority by Track

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
- **Co-author:** Add `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`
- **Test before commit:** Always run tests
- **Small commits:** One logical change per commit
