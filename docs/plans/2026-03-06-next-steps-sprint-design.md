# Next Steps Sprint Design

> 6 workstreams ordered by impact. Each is independent and can be parallelized.

## Execution Order

| # | Workstream | Priority | Effort | Risk |
|---|-----------|----------|--------|------|
| 1 | Activate pre-merge review gate | P1 | ~15 min | Low — workflow exists, just uncomment trigger |
| 2 | OpenClaw orchestrator wiring | P2 | ~2 hr | Med — touches unified_orchestrator.py |
| 3 | Provider routing Arena integration | P2 | ~1 hr | Low — ProviderRouter API already exists |
| 4 | Inbox trust wedge dogfood prep | P1 | ~30 min | Low — CLI exists, just needs OAuth setup script run |
| 5 | Swarm supervisor dogfood | P2 | ~30 min | Low — smoke test existing CLI |
| 6 | EU AI Act appendix gap | P1 | ~1 hr | Low — documentation only |

---

## 1. Activate Pre-Merge Review Gate

**Goal:** Enable `aragora-review-gate.yml` to trigger on PRs, putting the 12-runner fleet to work.

**Approach:** Uncomment the `pull_request` trigger in `.github/workflows/aragora-review-gate.yml`. The workflow already has path filters (`aragora/**`, `tests/**`, `scripts/**`), concurrency groups, and the full review logic.

**Changes:**
- Uncomment lines 6-8 in `aragora-review-gate.yml` (the `pull_request:` trigger block)
- Keep `workflow_dispatch` as fallback for manual runs
- Add `if: github.event.pull_request.draft == false` to the review job to respect the draft PR convention

**Validation:** Push a test PR to confirm the workflow triggers and runs.

---

## 2. OpenClaw Orchestrator Wiring

**Goal:** Wire `UnifiedOrchestrator` to use the PR #727 building blocks so the debate-to-execution flow works end-to-end.

**Current state:**
- `ImplementationSpecExtractor` exists at `aragora/pipeline/spec_extractor.py`
- `CodeImplementationTask` exists at `aragora/workflow/nodes/code_implementation.py`
- `ComputerUseActionBundle` exists at `aragora/pipeline/backbone_contracts.py`
- `UnifiedOrchestrator` has `plan_executor` slot but no spec extraction or computer-use integration

**Approach:** Add an optional `spec_extractor` parameter to `UnifiedOrchestrator.__init__()` and wire it between the debate result (Stage 3) and the plan creation (Stage 4). When a spec extractor is provided, the orchestrator extracts an implementation spec from the debate result, then uses `CodeImplementationTask` as the execution backend instead of the generic plan executor.

**Changes:**
- `aragora/pipeline/unified_orchestrator.py`:
  - Add `spec_extractor: Any | None = None` constructor param
  - Add `_do_spec_extraction()` method between debate and plan stages
  - When spec exists and execution_mode is `"openclaw"`, route to `CodeImplementationTask`
  - After execution, create `ComputerUseActionBundle` and attach to receipt
- `OrchestratorConfig`: add `execution_mode: str = "workflow"` already exists; add `"openclaw"` as documented option
- `OrchestratorResult`: add `spec_bundle: Any | None = None` and `action_bundle: Any | None = None`

**Validation:** Unit test: mock spec extractor + CodeImplementationTask, verify stages_completed includes `spec_extraction` and `execute`.

---

## 3. Provider Routing Arena Integration

**Goal:** Wire `ProviderRouter.select_providers_for_debate()` into the Arena's team selection so cost-aware model routing actually works.

**Current state:**
- `ProviderRouter` at `aragora/routing/provider_router.py` — fully functional with `select_providers_for_debate()`, `record_outcome()`
- `get_provider_router()` singleton factory exists
- Arena's `_select_debate_team()` in `orchestrator.py:969` delegates to `team_selector.py`
- `team_selector.py` uses ELO + calibration + domain capability map but not cost/quality optimization
- `UnifiedOrchestrator` has a `diversity_filter` slot but no router integration

**Approach:** Add `ProviderRouter` as an optional dependency in `UnifiedOrchestrator`, used to select providers BEFORE the diversity filter runs. The router's provider list becomes the agent pool that team_selector draws from.

**Changes:**
- `aragora/pipeline/unified_orchestrator.py`:
  - Add `provider_router: Any | None = None` constructor param
  - In Stage 3 (debate), call `provider_router.select_providers_for_debate()` to get preferred models
  - Pass preferred models to arena_factory as a hint
  - After debate, call `provider_router.record_outcome()` for each provider
- Keep it opt-in: when no router is provided, behavior is unchanged

**Validation:** Unit test: mock router returns `["claude-sonnet-4", "gpt-4o", "deepseek-r1"]`, verify these are passed to arena_factory.

---

## 4. Inbox Trust Wedge Dogfood Prep

**Goal:** Ensure everything needed for the first real Gmail triage run is in place.

**Current state:**
- `aragora triage run --batch 5` CLI exists
- `scripts/gmail_oauth_setup.py` exists for one-time OAuth
- `DurableFileSigner` at `~/.aragora/signing.key` for receipt signing
- All 5 blocking gaps closed (PRs #730-742 merged)

**Approach:** Verify the OAuth setup script runs cleanly, create a dogfood checklist, and do a dry-run with `--auto-approve` disabled to confirm the CLI-review flow works without actually executing any actions.

**Changes:**
- No code changes needed — this is validation and documentation
- Document the dogfood run procedure in `docs/plans/2026-03-06-inbox-dogfood-checklist.md`

---

## 5. Swarm Supervisor Dogfood

**Goal:** Exercise the newly shipped swarm supervisor (#744-750) on a real multi-file task.

**Current state:**
- `aragora/swarm/supervisor.py` — bounded work orders, managed worktrees, lease coordination
- `aragora/swarm/worker_launcher.py` — spawns Claude/Codex processes
- `aragora/swarm/reconciler.py` — periodic lease renewal and result collection

**Approach:** Run `aragora swarm dispatch` with a simple 2-worker task (e.g., "add type annotations to aragora/routing/") to validate the full lifecycle: spec -> decompose -> dispatch -> workers -> reconcile -> collect.

**Changes:**
- No code changes — smoke test and bug report
- Document any issues found

---

## 6. EU AI Act Appendix Gap

**Goal:** Fill Art. 10/11/43/49 appendix in the customer playbook to move score from 85 to 90+.

**Current state:**
- `aragora compliance eu-ai-act generate|status|report|check` CLI exists
- Score is 85/100 with explicit gaps in data governance (Art. 10), technical docs (Art. 11), conformity assessment (Art. 43), and registration (Art. 49)

**Approach:** Add appendix sections to the existing compliance playbook covering:
- Art. 10: Data governance procedures (training data quality, bias testing)
- Art. 11: Technical documentation template (system description, risk management)
- Art. 43: Self-assessment checklist for limited-risk AI
- Art. 49: EU database registration steps

**Changes:**
- `docs/compliance/EU_AI_ACT_GUIDE.md` — add 4 appendix sections
- `aragora/compliance/` — update scoring if appendix detection is automated

---

## Dependencies

None between workstreams — all 6 are independent and parallelizable.

## Success Criteria

- Pre-merge gate fires on a real PR
- `UnifiedOrchestrator.run()` with `execution_mode="openclaw"` produces spec + action bundle
- `ProviderRouter` selections flow through to Arena debates
- Gmail triage dry-run completes without error
- Swarm dispatches and collects at least one worker result
- EU AI Act score >= 90/100
