# Self-Improve Hard Checks Rollout

## Objective
Roll out live-path and quality-gate hard checks safely, then tighten policy after one week of runtime signals.

## Week 0 (Immediately)
1. Keep `pipeline self-improve` in live-default mode.
2. Enforce fail-closed for CI/dogfood profiles.
3. Keep interactive/manual usage in warn-only mode.
4. Run integration-vague dogfood profile on schedule and manual dispatch.

## Telemetry Signals
Collect and track:
1. `execution_path` distribution (`live`, `heuristic-fallback`, `heuristic`).
2. `provider_calls_detected` rate for live mode.
3. `quality_verdict` pass/fail counts.
4. `quality_score_10` and `practicality_score_10` trend.
5. `avg_objective_fidelity` trend.
6. Improvement queue backlog growth and age.

Source:
`[self-improve-metrics] ...` lines emitted by `aragora pipeline self-improve`.

## Alert Thresholds (Week 0)
1. `heuristic-fallback` > 10% over 24h: investigate provider health/config.
2. quality gate fail rate > 20% over 24h: inspect planner drift and contract fit.
3. `provider_calls_detected=false` in live mode > 5%: investigate canned/non-live paths.
4. improvement queue backlog growth > 2x week baseline: inspect consumer throughput.

## Week 1 Tightening Criteria
Promote fail-closed beyond CI/dogfood only if all are true for 7 days:
1. `execution_path=live` in >= 95% of runs.
2. quality gate pass rate >= 90%.
3. no sustained queue backlog growth (> 1.2x baseline).
4. no recurring objective-fidelity regression incidents.

## Week 1 Actions
1. Raise `plan_quality_min_score` from 6.0 to 7.0 in default profile.
2. Raise `plan_quality_min_practicality` from 5.0 to 6.0 in default profile.
3. Enable fail-closed by default for non-interactive automated runners.
4. Keep manual interactive mode warn-only for one additional cycle, then reassess.
