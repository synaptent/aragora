# Documentation Hygiene And Gap Register

Last updated: 2026-03-07

This register is the working record for documentation cleanup, roadmap extraction, and code-vs-doc drift found during the March 2026 hygiene pass.

The live execution backlog now tracks in [ACTIVE_EXECUTION_ISSUES.md](ACTIVE_EXECUTION_ISSUES.md) and the linked GitHub issues. Current-source docs should point there for execution status instead of carrying standalone operational backlog.

## Scope

- Keep current-source docs organized and discoverable.
- Reconcile prominent claims against the codebase and validation scripts.
- Track roadmap goals that remain future-state.
- Keep a running list of features that are partial, brittle, placeholder-backed, or under-documented.

## Completed In This Pass

- Fixed broken links in `docs/status/FEATURE_DISCOVERY.md` and `docs/status/STATUS.md`.
- Verified `docs/status/NEXT_STEPS_CANONICAL.md` points at `EXECUTION_NEXT_6_WEEKS_2026-03-05.md`.
- Reconciled `docs/EU_AI_ACT_COMPLIANCE.md` against `aragora/compliance/eu_ai_act.py`, including Article 9 artifact generation and current March 2026 timeline language.
- Regenerated `docs/CAPABILITY_MATRIX.md` and `docs-site/docs/contributing/capability-matrix.md` from the YAML source of truth.
- Added discoverability links for status, roadmap, gap, and hygiene docs from the main indexes.
- Marked legacy snapshot docs as non-canonical where they were being presented as live status.
- Canonicalized the current execution program into GitHub issues and added `docs/status/ACTIVE_EXECUTION_ISSUES.md` as the issue map for epics `#804`-`#806`, execution lanes `#807`-`#820`, and assurance issues `#273`, `#274`, `#509`.
- Updated the issue map and canonical execution summary after `#809` and `#810` landed so current-source docs reflect the active `#811` / `#812` kernel tranche.
- Corrected the root README's Knowledge Mound adapter count from `45` to the current verified `42`.

## Validation Snapshot

- `python3 scripts/validate_doc_links.py` -> pass
- `python3 scripts/reconcile_status.py` -> pass
- `python3 scripts/reconcile_status_docs.py --strict` -> pass after capability-matrix regeneration
- `python3 scripts/check_agent_registry_sync.py` -> pass (`43` registered, `34` allowlisted)
- `python3 scripts/validate_openapi_routes.py --spec docs/api/openapi.json` -> `99.6%` route coverage

## Current Canonical Metrics Used In This Pass

- Version: `2.8.0`
- Python modules under `aragora/`: `3,803`
- Tests (`def test_` across repo): `210,215`
- Test files under `tests/`: `5,069`
- OpenAPI paths (generated spec): `2,666`
- OpenAPI operations (generated spec): `3,155`
- SDK namespaces: `186` Python / `185` TypeScript
- Registered agent types: `43`
- Allowlisted agent types: `34`
- Knowledge Mound adapter specs in `aragora/knowledge/mound/adapters/factory.py`: `42`
- Unique `@require_permission(...)` strings in `aragora/`: `423`

## Roadmap And Goals Extracted From Current Docs

### Current Focus (March 2026)

- Closed-loop backbone, inbox trust wedge, swarm supervision, provider routing phase 1, Comms Hub completion, and OpenClaw core-loop delivery are treated as shipped in `docs/status/STATUS.md`.
- Canonical execution priorities are now linked directly to the GitHub backlog: truthfulness/backlog canonicalization is complete on `main` through `#809`, the first kernel bridge tranche `#810` is complete, and the active M1 kernel work is now `#811` and `#812` in `docs/status/NEXT_STEPS_CANONICAL.md` and `docs/status/ACTIVE_EXECUTION_ISSUES.md`.
- The active six-week plan is wedge/PMF-focused: first receipt quickly, parity hard-close, reliability cleanup, surface simplification, and status consolidation in `docs/status/EXECUTION_NEXT_6_WEEKS_2026-03-05.md`.

### Near-Term Goals (Q2 2026)

- Agent-first beta, GitHub review gate, public demo, EU AI Act package completion, enterprise pilots, and validated fast onboarding remain active in `docs/FEATURE_GAP_LIST.md` and `ROADMAP.md`.
- The August 2, 2026 EU AI Act deadline remains a major external forcing function across roadmap and compliance docs.

### Longer-Term Goals

- ERC-8004 mainnet deployment, Decision-Integrity UI Workbench expansion, federation, Prover-Estimator, market resolution, and the 8-stage visual canvas remain future-state goals and should stay documented as such.

## Running List: Partial Or Weakly Implemented Features

### Code-Backed Gaps

- OpenAPI drift remains: `9` handler routes are missing from the spec and `11` OpenAPI routes have no handler according to `scripts/validate_openapi_routes.py`.
- OpenAPI and SDK parity claims are still inflated by spec-only endpoints defined in `aragora/server/openapi/endpoints/sdk_missing.py`.
- `aragora/server/handlers/agent_evolution_dashboard.py` still raises `NotImplementedError("No real pending changes store yet")` for pending-change retrieval.
- `aragora/server/handlers/goal_canvas.py` still returns placeholder data for advancing a canvas into the actions stage.
- `aragora/server/handlers/spectate_ws.py` still serves `/api/v1/spectate/stream` as an SSE snapshot stub rather than full real-time streaming.
- `aragora/server/handlers/sme/slack_workspace.py` has placeholder channel listing plus placeholder SME OAuth start/callback endpoints.
- `aragora/server/handlers/sme/teams_workspace.py` has placeholder channel listing plus placeholder SME OAuth start/callback endpoints.
- `aragora/inbox/triage_runner.py` can still fall back to stub debates when agents or engine wiring are unavailable.
- `aragora/server/handlers/gauntlet/receipts.py` and the compliance UI still have placeholder or optional anchor-verification paths.
- `aragora/server/handlers/security_debate.py` exposes an async-status endpoint that is explicitly a placeholder because debates are synchronous and not persisted.
- `aragora/server/handlers/features/documents_batch.py` returns placeholder chunk retrieval output pending vector-store integration.
- `aragora/server/handlers/features/connectors.py` still carries `coming_soon` / stubbed connector flows (`gdrive` and related enterprise sync/test paths).
- `aragora/server/handlers/computer_use_handler.py` does not implement the full action/policy detail surface advertised by the OpenAPI computer-use endpoints.
- Self-host compose smoke can still fail because `/readyz` returns `503` when `system.health.read` is denied in the composed runtime, even while `/healthz` succeeds. The gating/docs work is landed, but the runtime permission model still needs follow-through.
- FastAPI receipts currently expose `json`/`markdown`/`sarif`, while legacy handlers still own `html`/`pdf` exports.
- Receipt delivery is only wired for `slack`, `teams`, `email`, and `discord`, not the broader connector/channel footprint implied elsewhere in the docs.
- Unified and progressive memory handlers remain backend-conditional and still return `501` when optional backends or methods are unavailable.
- `aragora/server/fastapi/routes/knowledge.py` can still return `501` when the configured KM backend lacks delete support.
- `aragora/server/fastapi/routes/workflows.py` can still return `501` when the configured workflow backend lacks step-approval support.
- `aragora/server/fastapi/routes/pipeline.py` still falls back to in-memory storage or create-without-start behavior when workflow-engine wiring is absent.

### Documentation Positioning Needed

- Slack and Teams integration docs should distinguish between shipped general integrations and still-placeholder SME workspace onboarding/channel enumeration surfaces.
- `docs/status/FEATURE_DISCOVERY.md` still contains some optimistic `Stable` labels for backend-conditional or placeholder-backed surfaces and should continue to be tightened.
- RLM and unified memory inventory entries need to reference current file paths (`aragora/server/handlers/rlm.py`, `aragora/memory/gateway.py`, related modules) rather than stale package layouts.
- Knowledge Mound adapter counts need a dedicated normalization sweep: many current docs still say `45`, while the current factory registry exposes `42` adapter specs.
- Root-level compatibility mirrors such as `docs/STATUS.md` and `docs/FEATURE_DISCOVERY.md` should remain clearly marked as mirrors so `docs/status/*` stays the canonical current-state surface.

## Remaining Documentation Debt After This Pass

- Historical, pricing, investor, and outreach collateral still contains stale counts in places and was not bulk-rewritten in this pass.
- Duplicate current-status surfaces still exist for compatibility and should eventually be consolidated into pointer docs once inbound links are audited.
- A follow-up sweep should normalize current SDK, RBAC, and adapter counts across commercial and enterprise collateral.
- Future execution-lane changes should update the GitHub issues first, then refresh `ACTIVE_EXECUTION_ISSUES.md` and the linked planning summaries.
