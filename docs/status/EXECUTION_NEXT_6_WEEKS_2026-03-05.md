# Execution Plan (Next 6 Weeks)

Last updated: 2026-03-05  
Owner: Platform program (Product, Backend, SDK, QA, SRE)

This is the active short-horizon plan in the agreed priority order.
It complements (does not replace) `docs/status/NEXT_STEPS_CANONICAL.md`.

## Priority Order

1. Product wedge focus (SME first receipt in <15 minutes)
2. SDK parity hard-close and drift prevention
3. Reliability debt burn-down (skip debt + smoke warnings + determinism)
4. Surface simplification (core command set first)
5. Canonical status stream and doc-drift control
6. Design-partner PMF loop with weekly scorecard gates

## Immediate Wins Completed (2026-03-05)

1. SDK parity gaps closed:
   - Added Python SDK bots Slack status route in `sdk/python/aragora_sdk/namespaces/bots.py`.
   - Added TypeScript SDK inbox auto-debate route in `sdk/typescript/src/namespaces/unified-inbox.ts`.
2. CLI deprecation-noise reduction:
   - Added grouped Arena config coalescing in `aragora/cli/commands/debate.py` so offline/demo runs no longer emit deprecated `knowledge_*`, `rlm_*`, `cross_debate_memory`, `ml_*` warnings.
3. Week 1 instrumentation baseline shipped:
   - Onboarding analytics events now include `flow_id` and step snapshots.
   - Analytics endpoint now reports:
     - `time_to_first_debate_seconds`
     - `time_to_first_receipt_seconds`
     - `step_drop_off` by onboarding step
   - Onboarding receipt generation now emits `first_receipt_generated` events.
4. Week 2 offline smoke cleanliness shipped:
   - Offline/demo debates now disable post-debate coordinator pipeline (`disable_post_debate_pipeline=True`) to avoid network-backed canvas/judge workflows.
   - Offline/demo quality pipeline now skips provider-backed repair loops while keeping deterministic contract checks.
   - `scripts/run_offline_golden_path.sh` now completes without `ResourceWarning` transport leaks.
5. Execution safety observability + calibration shipped:
   - Added execution-gate telemetry metrics (`aragora_execution_gate_*`) for decision outcomes, deny reasons, receipt verification, taint, and diversity.
   - Added reproducible threshold tuning sweep script: `scripts/tune_execution_gate.py`.
   - Published calibration report: `docs/status/EXECUTION_GATE_TUNING_2026-03-05.md`.

## Week-by-Week Execution

### Week 1: Wedge Lock + Instrumentation Baseline

Issue-sized tasks:
1. Freeze SME starter golden path (`quickstart` -> first debate -> receipt) and publish exact happy path.
2. Add/verify telemetry for:
   - `time_to_first_debate`
   - `time_to_first_receipt`
   - onboarding drop-off by step
3. Define launch metric board for p50/p95 activation and weekly active teams.

Acceptance:
1. One documented SME flow is canonical and referenced by onboarding docs.
2. Activation telemetry is queryable in one dashboard endpoint/report.

### Week 2: Reliability Lane 1 (Skip Debt + Offline Smoke Cleanliness)

Issue-sized tasks:
1. Reduce skip baseline from 54 to <=48 without raising baseline.
2. Triage and fix offline smoke `ResourceWarning` transports so smoke output is clean.
3. Add CI assertion that deprecation warnings from legacy Arena kwargs stay at zero for offline golden path.

Acceptance:
1. `python scripts/audit_test_skips.py --count-only` <= 48.
2. `scripts/run_offline_golden_path.sh` passes without new warning classes.

### Week 3: Surface Simplification

Issue-sized tasks:
1. Define core command lane in docs/CLI UX: `quickstart`, `ask`, `review`, `gauntlet`, `serve`.
2. Mark long-tail commands as advanced in help/docs.
3. Add docs sanity test that first-time path uses only core lane.

Acceptance:
1. New-user docs route through core lane only.
2. Advanced surfaces remain available but not default-discovery.

### Week 4: Canonical Status Consolidation

Issue-sized tasks:
1. Convert stale/competing status docs into pointer docs where possible.
2. Add lightweight CI check: short-horizon file link must match canonical next-steps reference.
3. Ensure roadmap/status pages do not contradict active KPI targets.

Acceptance:
1. Single active short-horizon execution doc is linked from canonical next-steps.
2. Doc drift check runs in lint/docs lane.

### Week 5: Design Partner Pilot Start

Issue-sized tasks:
1. Select 3-5 design partners matching PMF rubric.
2. Run one guided activation session per partner using SME starter flow.
3. Capture weekly PMF scorecards in a single structured report.

Acceptance:
1. Every partner has baseline + week-1 PMF score.
2. Activation and first receipt metrics are attached per partner.

### Week 6: PMF Decision Gate

Issue-sized tasks:
1. Run 3 consecutive weekly score reviews.
2. Decide scale/iterate/narrow using documented thresholds.
3. Promote successful wedge metrics into default product/program dashboard.

Acceptance:
1. At least 3 partners sustain scale-threshold trajectory, or scope is explicitly narrowed.
2. Next 6-week plan is generated from measured outcomes, not backlog volume.

## CI/Gate Commands (Required Weekly)

1. `python scripts/check_sdk_parity.py --strict --baseline scripts/baselines/check_sdk_parity.json --budget scripts/baselines/check_sdk_parity_budget.json`
2. `python scripts/audit_test_skips.py --count-only`
3. `python scripts/check_agent_registry_sync.py`
4. `python scripts/check_connector_exception_handling.py`
5. `python scripts/check_self_host_compose.py`
6. `python scripts/check_pentest_findings.py`
7. `bash scripts/run_offline_golden_path.sh`
