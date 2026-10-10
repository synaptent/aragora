# Agent readiness report

This report compares the Factory agent-readiness audit
`85b9e93d-baf1-4c85-94eb-36a387c40877` with the state of branch
`readiness/m10-finalize`, the last milestone of the readiness cascade (M1 to
M10). The audit ran against `synaptent/aragora` at commit
`15cc283a6146cba407650d9c7b2f8e417358965f` (2026-08-29) and passed 115 of 258
evaluated checks (Level 2).

How to read the tables:

- `Signal` and `Before` are copied verbatim from the audit's per-scope export.
  They are never re-derived.
- `After` is a self-assessment against the audit's own criteria at the M10
  head. It is not a new Factory audit; a re-audit after the operator settles the
  cascade is the authority, and this report claims no readiness level.
- `After` describes this branch, not `main`. None of M1 to M10 is merged yet
  (see [Cascade state](#cascade-state)).
- `Evidence` is filled for every row whose `After` differs from `Before`. It is
  either a path that exists in the repository at this head or a command that
  starts with `make `, `npm `, `npx `, `python`, `go `, `gh `, `pytest`, `ruff`
  or `curl`. Rows the audit marked `n/a`, and signals the mission declared out of
  scope for an app (`duplicate_code_detection` for vscode, `structured_logging`
  for operator, `heavy_dependency_detection` for the Python apps), keep their
  `Before` value.
- Observability rows credit wiring that was verified against local capture
  stubs only. No row claims delivery to a real Sentry, PostHog or OpenTelemetry
  backend: that check (VAL-LIVEOBS-018) is deferred to M11 `m11-pr` by contract
  amendment (23).
- `tests/ci/test_readiness_report.py` parses these tables and checks the
  header, the row counts, the allowed cell values, the evidence rule and the
  Summary arithmetic.

## Summary

Score: `115/258` before, `216/258` after. A row counts when its `Before`
or `After` is not `n/a`; the audit's 54 `n/a` rows stay `n/a`, so the
denominator is unchanged. The audit export evaluates 45 repo-level and 213
app-level checks; the contract text's split of 43 and 215 is approximate, and
both add up to the same 258.

| Scope | Rows | Evaluated | Pass before | Pass after |
|---|---|---|---|---|
| `repo` | 46 | 45 | 41 | 45 |
| `root` | 38 | 37 | 29 | 35 |
| `debate` | 38 | 26 | 5 | 22 |
| `verify` | 38 | 25 | 7 | 21 |
| `live` | 38 | 37 | 19 | 32 |
| `docs` | 38 | 26 | 1 | 15 |
| `vscode` | 38 | 29 | 6 | 20 |
| `operator` | 38 | 33 | 7 | 26 |
| **total** | 312 | 258 | 115 | 216 |

102 rows move from `fail` to `pass` and 1 row moves from `pass` to
`fail` (live `alerting_configured`: `main` parked the uptime probe the audit
credited; see the live notes).

- `fast_ci_feedback` is credited for the fail-closed `test-fast-gate` umbrella
  in `.github/workflows/test.yml` (worker job `test-fast-gate-run`, 10-minute
  timeout, non-draft PRs). `test-fast-gate` is not yet a required check: adding
  it to branch protection is the M11 Tier-4 step
  (`m11-branch-protection-patch`), and `docs/CI_LANES.md` still marks it
  FUTURE. Its end-to-end wall time has not been observed on `main`, because M4
  (#10027) is not merged.
- Signals declined on purpose: naming and complexity for docs and vscode
  (their ESLint configs enable neither rule, as VAL-DOCS-002 and VAL-VSCODE-001
  record), naming for operator (no `revive` or `stylecheck`; VAL-OPERATOR-029),
  and duplication for vscode (out of scope). Root `strict_typing` stays `fail`:
  the global `disallow_untyped_defs = true` is ratcheted, but 859 modules are
  still exempted by override and `check_untyped_defs` is off.
- The reds this branch inherits from M9 are listed under
  [Known reds inherited from M9](#known-reds-inherited-from-m9).

## Scope `repo`

| Signal | Before | After | Evidence |
|---|---|---|---|
| `large_file_detection` | pass | pass |  |
| `tech_debt_tracking` | pass | pass |  |
| `n_plus_one_detection` | pass | pass |  |
| `build_cmd_doc` | pass | pass |  |
| `deps_pinned` | pass | pass |  |
| `vcs_cli_tools` | pass | pass |  |
| `automated_pr_review` | pass | pass |  |
| `agentic_development` | pass | pass |  |
| `fast_ci_feedback` | fail | pass | .github/workflows/test.yml |
| `build_performance_tracking` | pass | pass |  |
| `deployment_frequency` | pass | pass |  |
| `single_command_setup` | pass | pass |  |
| `feature_flag_infrastructure` | pass | pass |  |
| `release_notes_automation` | pass | pass |  |
| `progressive_rollout` | pass | pass |  |
| `rollback_automation` | pass | pass |  |
| `monorepo_tooling` | fail | pass | pyproject.toml |
| `version_drift_detection` | pass | pass |  |
| `release_automation` | pass | pass |  |
| `dead_feature_flag_detection` | pass | pass |  |
| `agents_md` | pass | pass |  |
| `readme` | pass | pass |  |
| `automated_doc_generation` | pass | pass |  |
| `skills` | pass | pass |  |
| `documentation_freshness` | pass | pass |  |
| `service_flow_documented` | pass | pass |  |
| `agents_md_validation` | pass | pass |  |
| `devcontainer` | pass | pass |  |
| `env_template` | pass | pass |  |
| `local_services_setup` | pass | pass |  |
| `database_schema` | pass | pass |  |
| `devcontainer_runnable` | n/a | n/a |  |
| `runbooks_documented` | pass | pass |  |
| `branch_protection` | pass | pass |  |
| `secret_scanning` | pass | pass |  |
| `codeowners` | pass | pass |  |
| `automated_security_review` | pass | pass |  |
| `dependency_update_automation` | pass | pass |  |
| `gitignore_comprehensive` | pass | pass |  |
| `privacy_compliance` | pass | pass |  |
| `secrets_management` | pass | pass |  |
| `min_release_age` | fail | pass | .github/dependabot.yml |
| `issue_templates` | pass | pass |  |
| `issue_labeling_system` | pass | pass |  |
| `backlog_health` | fail | pass | gh issue list --state open --limit 50 --json number,title,labels |
| `pr_templates` | pass | pass |  |

Notes:

- `fast_ci_feedback`: see the Summary.
- `monorepo_tooling`: a uv workspace (`[tool.uv.workspace]` in
  `pyproject.toml`, members `aragora-debate`, `aragora-verify`, `sdk/python`)
  plus the `make readiness-lint`, `make readiness-typecheck` and
  `make readiness-test` aggregators, which fan out to all seven apps.
- `min_release_age`: every entry in `.github/dependabot.yml` carries a
  `cooldown` (7 days, 14 for semver-major updates); the root and per-app
  `.npmrc` files set `min-release-age=3`; `scripts/ci/uv_lock_with_cooldown.sh`
  covers uv.
- `backlog_health`, read-only on 2026-10-10: 951 open issues; 46 of the 50
  newest open issues (92 %) have a label and a descriptive title (the bar is
  70 %); 4 open issues have no label (#10123, #10124, #10125, #10134, all opened
  after the one-time labelling run of 2026-09-04); none is older than 365 days.
  `.github/workflows/issue-autolabel.yml` labels new and edited issues from a
  keyword map, and `.github/workflows/stale.yml` handles stale ones.
- `devcontainer_runnable` stays `n/a`: no devcontainer CLI was available.

## Scope `root`

| Signal | Before | After | Evidence |
|---|---|---|---|
| `lint_config` | pass | pass |  |
| `type_check` | pass | pass |  |
| `formatter` | pass | pass |  |
| `pre_commit_hooks` | pass | pass |  |
| `strict_typing` | fail | fail |  |
| `naming_consistency` | fail | pass | scripts/baselines/root-ruff-naming.json |
| `cyclomatic_complexity` | fail | pass | scripts/baselines/root-ruff-complexity.json |
| `dead_code_detection` | fail | pass | scripts/baselines/root-vulture.json |
| `duplicate_code_detection` | fail | pass | .jscpd.json |
| `code_modularization` | pass | pass |  |
| `heavy_dependency_detection` | n/a | n/a |  |
| `unused_dependencies_detection` | fail | pass | pyproject.toml |
| `unit_tests_exist` | pass | pass |  |
| `integration_tests_exist` | pass | pass |  |
| `unit_tests_runnable` | pass | pass |  |
| `test_performance_tracking` | pass | pass |  |
| `flaky_test_detection` | pass | pass |  |
| `test_coverage_thresholds` | pass | pass |  |
| `test_naming_conventions` | pass | pass |  |
| `test_isolation` | pass | pass |  |
| `interactive_qa_exists` | pass | pass |  |
| `interactive_qa_runnable` | pass | pass |  |
| `api_schema_docs` | pass | pass |  |
| `structured_logging` | pass | pass |  |
| `distributed_tracing` | pass | pass |  |
| `metrics_collection` | pass | pass |  |
| `code_quality_metrics` | pass | pass |  |
| `error_tracking_contextualized` | pass | pass |  |
| `alerting_configured` | pass | pass |  |
| `deployment_observability` | pass | pass |  |
| `health_checks` | pass | pass |  |
| `circuit_breakers` | pass | pass |  |
| `profiling_instrumentation` | pass | pass |  |
| `dast_scanning` | fail | pass | .github/workflows/dast.yml |
| `pii_handling` | pass | pass |  |
| `log_scrubbing` | pass | pass |  |
| `product_analytics_instrumentation` | fail | fail |  |
| `error_to_insight_pipeline` | pass | pass |  |

Notes:

- Naming (`N`) and complexity (`C901`, max 15) run as shrink-only ratchets in
  `make readiness-lint-root`, not in the default ruff selection. The naming
  ratchet is red at this head on two classes that landed on `main`; see
  [Known reds inherited from M9](#known-reds-inherited-from-m9).
- Dead code: vulture at confidence 80. Duplication: jscpd 5.1.1 with a 2.1 %
  threshold (`.jscpd.json`). Unused dependencies: `deptry .` with
  `[tool.deptry]` in `pyproject.toml`.
- DAST: `.github/workflows/dast.yml` runs OWASP ZAP against the demo backend
  on non-draft PRs that touch the server or the API spec, and nightly. It is
  advisory (warn-only); see `docs/SECURITY_DAST.md`.
- `strict_typing` stays `fail` (see the Summary). `product_analytics_instrumentation`
  stays `fail`: the root package has no usage telemetry of its own.

## Scope `debate`

| Signal | Before | After | Evidence |
|---|---|---|---|
| `lint_config` | fail | pass | aragora-debate/pyproject.toml |
| `type_check` | fail | pass | make readiness-typecheck-debate |
| `formatter` | fail | pass | make readiness-lint-debate |
| `pre_commit_hooks` | pass | pass |  |
| `strict_typing` | fail | pass | aragora-debate/pyproject.toml |
| `naming_consistency` | fail | pass | aragora-debate/pyproject.toml |
| `cyclomatic_complexity` | fail | pass | aragora-debate/pyproject.toml |
| `dead_code_detection` | fail | pass | scripts/baselines/debate-vulture.json |
| `duplicate_code_detection` | fail | pass | make readiness-lint-debate |
| `code_modularization` | fail | fail |  |
| `heavy_dependency_detection` | n/a | n/a |  |
| `unused_dependencies_detection` | fail | pass | make readiness-lint-debate |
| `unit_tests_exist` | pass | pass |  |
| `integration_tests_exist` | fail | fail |  |
| `unit_tests_runnable` | pass | pass |  |
| `test_performance_tracking` | fail | pass | .github/workflows/packages-ci.yml |
| `flaky_test_detection` | fail | fail |  |
| `test_coverage_thresholds` | fail | pass | aragora-debate/pyproject.toml |
| `test_naming_conventions` | fail | pass | aragora-debate/pyproject.toml |
| `test_isolation` | fail | pass | .github/workflows/packages-ci.yml |
| `interactive_qa_exists` | pass | pass |  |
| `interactive_qa_runnable` | pass | pass |  |
| `api_schema_docs` | n/a | n/a |  |
| `structured_logging` | fail | pass | aragora-debate/src/aragora_debate/_logging.py |
| `distributed_tracing` | n/a | n/a |  |
| `metrics_collection` | n/a | n/a |  |
| `code_quality_metrics` | fail | pass | .github/workflows/packages-ci.yml |
| `error_tracking_contextualized` | n/a | n/a |  |
| `alerting_configured` | n/a | n/a |  |
| `deployment_observability` | n/a | n/a |  |
| `health_checks` | n/a | n/a |  |
| `circuit_breakers` | fail | pass | aragora-debate/src/aragora_debate/_resilience.py |
| `profiling_instrumentation` | n/a | n/a |  |
| `dast_scanning` | n/a | n/a |  |
| `pii_handling` | n/a | n/a |  |
| `log_scrubbing` | fail | pass | aragora-debate/src/aragora_debate/_logging.py |
| `product_analytics_instrumentation` | fail | fail |  |
| `error_to_insight_pipeline` | n/a | n/a |  |

Notes:

- `aragora-debate/pyproject.toml` extends the root ruff config and selects `N`
  and `C901` (max 10), and sets mypy `strict = true`.
  `make readiness-typecheck-debate` runs `mypy --strict src` with mypy 2.1.0.
  `make readiness-lint-debate` runs `ruff check`, `ruff format --check`,
  vulture, deptry, jscpd (threshold 4.06 %) and the file-size check.
- Tests: explicit `python_files` and `python_functions` patterns and coverage
  `fail_under = 90.10`. `.github/workflows/packages-ci.yml` runs
  `pytest -p randomly --randomly-seed=1234 -n 4 --durations=10` with coverage
  and uploads the junit report.
- `src/aragora_debate/_logging.py` adds an env-gated JSON formatter
  (`ARAGORA_LOG_FORMAT=json`) and a redaction filter;
  `src/aragora_debate/_resilience.py` adds timeouts, retries and a circuit
  breaker around provider calls.
- Still `fail`: `code_modularization` (no enforced module boundaries),
  `integration_tests_exist` (unit tests only), `flaky_test_detection` (a fixed
  random-order seed is not flake detection) and
  `product_analytics_instrumentation` (a library without telemetry).

## Scope `verify`

| Signal | Before | After | Evidence |
|---|---|---|---|
| `lint_config` | pass | pass |  |
| `type_check` | fail | pass | make readiness-typecheck-verify |
| `formatter` | pass | pass |  |
| `pre_commit_hooks` | pass | pass |  |
| `strict_typing` | fail | pass | aragora-verify/pyproject.toml |
| `naming_consistency` | fail | pass | aragora-verify/pyproject.toml |
| `cyclomatic_complexity` | fail | pass | aragora-verify/pyproject.toml |
| `dead_code_detection` | fail | pass | scripts/baselines/verify-vulture.json |
| `duplicate_code_detection` | fail | pass | make readiness-lint-verify |
| `code_modularization` | fail | fail |  |
| `heavy_dependency_detection` | n/a | n/a |  |
| `unused_dependencies_detection` | fail | pass | make readiness-lint-verify |
| `unit_tests_exist` | pass | pass |  |
| `integration_tests_exist` | fail | fail |  |
| `unit_tests_runnable` | pass | pass |  |
| `test_performance_tracking` | fail | pass | .github/workflows/packages-ci.yml |
| `flaky_test_detection` | fail | fail |  |
| `test_coverage_thresholds` | fail | pass | aragora-verify/pyproject.toml |
| `test_naming_conventions` | fail | pass | aragora-verify/pyproject.toml |
| `test_isolation` | fail | pass | .github/workflows/packages-ci.yml |
| `interactive_qa_exists` | pass | pass |  |
| `interactive_qa_runnable` | pass | pass |  |
| `api_schema_docs` | n/a | n/a |  |
| `structured_logging` | fail | pass | aragora-verify/src/aragora_verify/_logging.py |
| `distributed_tracing` | n/a | n/a |  |
| `metrics_collection` | n/a | n/a |  |
| `code_quality_metrics` | fail | pass | .github/workflows/packages-ci.yml |
| `error_tracking_contextualized` | n/a | n/a |  |
| `alerting_configured` | n/a | n/a |  |
| `deployment_observability` | n/a | n/a |  |
| `health_checks` | n/a | n/a |  |
| `circuit_breakers` | n/a | n/a |  |
| `profiling_instrumentation` | n/a | n/a |  |
| `dast_scanning` | n/a | n/a |  |
| `pii_handling` | n/a | n/a |  |
| `log_scrubbing` | fail | pass | aragora-verify/src/aragora_verify/_logging.py |
| `product_analytics_instrumentation` | fail | fail |  |
| `error_to_insight_pipeline` | n/a | n/a |  |

Notes:

- `aragora-verify/pyproject.toml` selects `N` and `C901` (max 10) and sets mypy
  `strict = true`. `make readiness-lint-verify` first runs
  `scripts/check_aragora_verify_dependency_policy.py`, then the same ruff,
  vulture, deptry, jscpd (threshold 0.5 %) and file-size checks as debate.
- Tests: explicit discovery patterns, coverage `fail_under = 89.26`, and the
  same randomised, parallel, timed `packages-ci.yml` run with a junit upload.
- `src/aragora_verify/_logging.py` is identical to the debate copy (JSON
  formatter and redaction filter).
- Still `fail`: `code_modularization`, `integration_tests_exist`,
  `flaky_test_detection` and `product_analytics_instrumentation`, for the same
  reasons as debate.

## Scope `live`

| Signal | Before | After | Evidence |
|---|---|---|---|
| `lint_config` | pass | pass |  |
| `type_check` | pass | pass |  |
| `formatter` | fail | pass | aragora/live/.prettierrc |
| `pre_commit_hooks` | pass | pass |  |
| `strict_typing` | pass | pass |  |
| `naming_consistency` | fail | pass | aragora/live/eslint.config.mjs |
| `cyclomatic_complexity` | fail | pass | aragora/live/eslint.config.mjs |
| `dead_code_detection` | fail | pass | scripts/baselines/live-knip.json |
| `duplicate_code_detection` | fail | pass | aragora/live/.jscpd.json |
| `code_modularization` | fail | pass | aragora/live/eslint.config.mjs |
| `heavy_dependency_detection` | pass | pass |  |
| `unused_dependencies_detection` | fail | pass | scripts/baselines/live-knip.json |
| `unit_tests_exist` | pass | pass |  |
| `integration_tests_exist` | pass | pass |  |
| `unit_tests_runnable` | pass | pass |  |
| `test_performance_tracking` | pass | pass |  |
| `flaky_test_detection` | pass | pass |  |
| `test_coverage_thresholds` | fail | pass | aragora/live/jest.config.js |
| `test_naming_conventions` | pass | pass |  |
| `test_isolation` | pass | pass |  |
| `interactive_qa_exists` | pass | pass |  |
| `interactive_qa_runnable` | pass | pass |  |
| `api_schema_docs` | n/a | n/a |  |
| `structured_logging` | fail | pass | aragora/live/src/lib/logger.ts |
| `distributed_tracing` | fail | pass | aragora/live/instrumentation.ts |
| `metrics_collection` | fail | fail |  |
| `code_quality_metrics` | fail | pass | .github/workflows/lint.yml |
| `error_tracking_contextualized` | fail | pass | aragora/live/sentry.server.config.ts |
| `alerting_configured` | pass | fail | .github/workflows/monitor.yml |
| `deployment_observability` | pass | pass |  |
| `health_checks` | pass | pass |  |
| `circuit_breakers` | pass | pass |  |
| `profiling_instrumentation` | fail | fail |  |
| `dast_scanning` | fail | fail |  |
| `pii_handling` | fail | fail |  |
| `log_scrubbing` | fail | pass | aragora/live/src/lib/logger.ts |
| `product_analytics_instrumentation` | fail | pass | aragora/live/instrumentation-client.ts |
| `error_to_insight_pipeline` | pass | pass |  |

Notes:

- Quality gates: Prettier (`aragora/live/.prettierrc`, `npm run format:check`);
  ESLint `@typescript-eslint/naming-convention`, `complexity` (max 15) and
  `eslint-plugin-boundaries`, with existing violations frozen in
  `aragora/live/eslint-suppressions.json`; knip for dead code and unused
  dependencies; jscpd with a 6 % threshold; Jest `coverageThreshold`
  (statements 26.01, branches 21.71, functions 21.98, lines 26.91) and
  `jest-junit`. The `frontend-lint` job in `.github/workflows/lint.yml` runs
  them through the `make readiness-*-live` targets and uploads coverage, junit
  and ratchet reports.
- Duplication: the 6 % jscpd threshold is measured over all of `src/`, where
  the generated `src/types/api.generated.ts` (no clones) is about 46 % of the
  lines and 660 of the 1,625 clones sit in test files. Over product code the
  duplication was 9.86 % at `deb02e61e1`. The gate stays as the contract
  requires, and the figure is disclosed here.
- Observability, verified against local stubs only: `instrumentation.ts`
  registers OpenTelemetry (`@vercel/otel`) when `OTEL_EXPORTER_OTLP_ENDPOINT` is
  set; Sentry initialises from `SENTRY_DSN` or `NEXT_PUBLIC_SENTRY_DSN` with
  `sendDefaultPii: false`; PostHog initialises from `NEXT_PUBLIC_POSTHOG_KEY`
  with pageview capture, `autocapture: false` and session recording off;
  `src/lib/logger.ts` is a pino logger with redaction. The M10 follow-up
  (VAL-LIVEOBS-020 to 025, commits `316b13cc2940` and `13f5256d7cea`) validates
  `LOG_LEVEL`, type-checks the four root instrumentation files, makes PostHog
  clear-text payloads opt-in, reports `global-error` crashes to Sentry, hides
  the Sentry test page in production and corrects the README. Remaining
  limitations are recorded in `docs/TECH_DEBT.md` and under
  [Observations](#live-observability-limitations).
- `alerting_configured` moves from `pass` to `fail`. The audit credited
  `.github/workflows/monitor.yml` probing `https://aragora.ai` every 30 minutes
  and opening an issue on failure. That schedule was parked on `main` on
  2026-09-14 (#10025, operator decision: no production origin since
  2026-08-19), so at this head the probe runs only on manual dispatch and
  nothing alerts automatically. This regression comes from `main`, not from the
  cascade; the schedule returns with the planned provider-neutral canary
  (#9851, #9882).
- `error_to_insight_pipeline` stays `pass` on the env-gated Sentry wiring
  (error grouping), but the audit's other cited paths are idle at this head:
  the `monitor.yml` issue path is parked, and `production-monitor.yml` last ran
  on 2026-07-16.
- Still `fail`: `metrics_collection` (OpenTelemetry is wired for traces only),
  `profiling_instrumentation`, `dast_scanning` (`dast.yml` scans the backend
  only) and `pii_handling` (the telemetry defaults minimise PII, but the app has
  no masking or retention controls for user data).

## Scope `docs`

| Signal | Before | After | Evidence |
|---|---|---|---|
| `lint_config` | fail | pass | docs-site/eslint.config.mjs |
| `type_check` | fail | pass | docs-site/tsconfig.json |
| `formatter` | fail | pass | docs-site/.prettierrc |
| `pre_commit_hooks` | fail | pass | .pre-commit-config.yaml |
| `strict_typing` | fail | pass | docs-site/tsconfig.json |
| `naming_consistency` | fail | fail |  |
| `cyclomatic_complexity` | fail | fail |  |
| `dead_code_detection` | fail | pass | scripts/baselines/docs-knip.json |
| `duplicate_code_detection` | fail | pass | docs-site/.jscpd.json |
| `code_modularization` | n/a | n/a |  |
| `heavy_dependency_detection` | fail | fail |  |
| `unused_dependencies_detection` | fail | pass | scripts/baselines/docs-knip.json |
| `unit_tests_exist` | fail | pass | docs-site/tests/config.test.ts |
| `integration_tests_exist` | fail | fail |  |
| `unit_tests_runnable` | fail | pass | make readiness-test-docs |
| `test_performance_tracking` | fail | fail |  |
| `flaky_test_detection` | fail | fail |  |
| `test_coverage_thresholds` | fail | fail |  |
| `test_naming_conventions` | fail | pass | docs-site/vitest.config.ts |
| `test_isolation` | fail | fail |  |
| `interactive_qa_exists` | pass | pass |  |
| `interactive_qa_runnable` | fail | pass | docs-site/README.md |
| `api_schema_docs` | n/a | n/a |  |
| `structured_logging` | n/a | n/a |  |
| `distributed_tracing` | n/a | n/a |  |
| `metrics_collection` | n/a | n/a |  |
| `code_quality_metrics` | fail | fail |  |
| `error_tracking_contextualized` | n/a | n/a |  |
| `alerting_configured` | fail | fail |  |
| `deployment_observability` | fail | pass | .github/workflows/deploy-docs.yml |
| `health_checks` | n/a | n/a |  |
| `circuit_breakers` | n/a | n/a |  |
| `profiling_instrumentation` | n/a | n/a |  |
| `dast_scanning` | n/a | n/a |  |
| `pii_handling` | n/a | n/a |  |
| `log_scrubbing` | n/a | n/a |  |
| `product_analytics_instrumentation` | fail | pass | docs-site/docusaurus.config.js |
| `error_to_insight_pipeline` | fail | fail |  |

Notes:

- Toolchain: `docs-site/eslint.config.mjs`, Prettier (`docs-site/.prettierrc`),
  `docs-site/tsconfig.json` (`strict: true`), knip (two baselined entries: the
  unused `clsx` dependency and the `vercel` binary), jscpd with a 1 % threshold,
  a Vitest suite in `docs-site/tests/` and the broken-link ratchet
  (`make readiness-heavy-docs`). `.github/workflows/docs-site-ci.yml` runs all
  of them, and the `docs-site-typecheck` hook in `.pre-commit-config.yaml` runs
  the typecheck.
- `strict_typing` is credited for the TypeScript sources (the Vitest suite and
  its config). `checkJs` is off, so the JavaScript sources
  (`docusaurus.config.js`, `sidebars.js`, `scripts/*.js`) are parsed but not
  type-checked; see [Observations](#docs-site).
- `interactive_qa_runnable`: `docs-site/README.md` documents `npm ci` and
  `npm run start` on port 3130, and M7 drove that dev server with Playwright.
  The audit's failure was the missing install.
- `deployment_observability`: `.github/workflows/deploy-docs.yml` checks that
  `https://docs.aragora.ai/` answers after each deploy.
- `product_analytics_instrumentation`: `docs-site/docusaurus.config.js` loads
  the PostHog plugin only when `POSTHOG_API_KEY` is set at build time. This is
  wiring only: the deploy workflow does not set the key today, so the
  published site sends no analytics.
- Declined: `naming_consistency` and `cyclomatic_complexity` (no such rules;
  VAL-DOCS-002). Still `fail`: `heavy_dependency_detection` (no bundle-size
  budget), `integration_tests_exist` (`scripts/sync-atlas.test.js` exists, but
  no script or workflow runs it), `test_performance_tracking`,
  `flaky_test_detection`, `test_coverage_thresholds`, `test_isolation` (Vitest
  defaults only), `code_quality_metrics`, `alerting_configured` (the
  `docs-site-check` job in `monitor.yml` runs only on manual dispatch while the
  schedule is parked) and `error_to_insight_pipeline`.

## Scope `vscode`

| Signal | Before | After | Evidence |
|---|---|---|---|
| `lint_config` | pass | pass |  |
| `type_check` | pass | pass |  |
| `formatter` | fail | pass | ide/vscode-aragora/.prettierrc |
| `pre_commit_hooks` | fail | pass | .pre-commit-config.yaml |
| `strict_typing` | pass | pass |  |
| `naming_consistency` | fail | fail |  |
| `cyclomatic_complexity` | fail | fail |  |
| `dead_code_detection` | fail | pass | scripts/baselines/vscode-knip.json |
| `duplicate_code_detection` | fail | fail |  |
| `code_modularization` | fail | fail |  |
| `heavy_dependency_detection` | fail | fail |  |
| `unused_dependencies_detection` | fail | pass | ide/vscode-aragora/knip.json |
| `unit_tests_exist` | pass | pass |  |
| `integration_tests_exist` | fail | pass | ide/vscode-aragora/src/test/runTest.ts |
| `unit_tests_runnable` | fail | pass | make readiness-test-vscode |
| `test_performance_tracking` | fail | pass | .github/workflows/vscode-extension.yml |
| `flaky_test_detection` | fail | fail |  |
| `test_coverage_thresholds` | pass | pass |  |
| `test_naming_conventions` | pass | pass |  |
| `test_isolation` | fail | fail |  |
| `interactive_qa_exists` | fail | pass | ide/vscode-aragora/README.md |
| `interactive_qa_runnable` | fail | pass | ide/vscode-aragora/.vscode/launch.json |
| `api_schema_docs` | n/a | n/a |  |
| `structured_logging` | fail | fail |  |
| `distributed_tracing` | n/a | n/a |  |
| `metrics_collection` | n/a | n/a |  |
| `code_quality_metrics` | fail | pass | .github/workflows/vscode-extension.yml |
| `error_tracking_contextualized` | fail | pass | ide/vscode-aragora/src/telemetry.ts |
| `alerting_configured` | n/a | n/a |  |
| `deployment_observability` | n/a | n/a |  |
| `health_checks` | n/a | n/a |  |
| `circuit_breakers` | fail | pass | ide/vscode-aragora/src/client.ts |
| `profiling_instrumentation` | n/a | n/a |  |
| `dast_scanning` | n/a | n/a |  |
| `pii_handling` | n/a | n/a |  |
| `log_scrubbing` | fail | pass | ide/vscode-aragora/src/logger.ts |
| `product_analytics_instrumentation` | fail | pass | ide/vscode-aragora/src/telemetry.ts |
| `error_to_insight_pipeline` | fail | fail |  |

Notes:

- ESLint 9 flat config, Prettier, knip, Jest with `jest-junit` and coverage
  thresholds, and a `@vscode/test-electron` integration suite pinned to VS Code
  1.136.1 (`src/test/runTest.ts`, `src/test/suite/`).
  `.github/workflows/vscode-extension.yml` runs the unit tests with coverage
  and uploads junit, runs the integration suite under xvfb, and packages the
  VSIX. The `vscode-typecheck` hook in `.pre-commit-config.yaml` compiles the
  extension.
- `ide/vscode-aragora/README.md` has Run and Debug with F5 sections, backed by
  `.vscode/launch.json`.
- `src/logger.ts` writes timestamped, levelled lines to the OutputChannel with
  secrets redacted. `src/client.ts` adds a per-attempt timeout, exponential
  backoff for idempotent requests and a circuit breaker. `src/telemetry.ts`
  adds opt-in Sentry and PostHog, active only when VS Code telemetry is on,
  `aragora.telemetry.enabled` is true and a DSN or key is set (verified against
  local stubs only).
- `structured_logging` stays `fail`: the lines are levelled plain text, not
  structured records.
- Declined: naming and complexity (VAL-VSCODE-001); `duplicate_code_detection`
  is out of scope. Still `fail`: `code_modularization`,
  `heavy_dependency_detection`, `flaky_test_detection`, `test_isolation` and
  `error_to_insight_pipeline`.

## Scope `operator`

| Signal | Before | After | Evidence |
|---|---|---|---|
| `lint_config` | pass | pass |  |
| `type_check` | pass | pass |  |
| `formatter` | pass | pass |  |
| `pre_commit_hooks` | fail | pass | .pre-commit-config.yaml |
| `strict_typing` | n/a | n/a |  |
| `naming_consistency` | fail | fail |  |
| `cyclomatic_complexity` | fail | pass | aragora-operator/.golangci.yml |
| `dead_code_detection` | fail | pass | aragora-operator/.golangci.yml |
| `duplicate_code_detection` | fail | pass | aragora-operator/.golangci.yml |
| `code_modularization` | pass | pass |  |
| `heavy_dependency_detection` | n/a | n/a |  |
| `unused_dependencies_detection` | fail | pass | .github/workflows/operator-ci.yml |
| `unit_tests_exist` | fail | pass | aragora-operator/internal/httpclient/client_test.go |
| `integration_tests_exist` | fail | pass | aragora-operator/controllers/suite_test.go |
| `unit_tests_runnable` | fail | pass | make readiness-test-operator |
| `test_performance_tracking` | fail | pass | .github/workflows/operator-ci.yml |
| `flaky_test_detection` | fail | fail |  |
| `test_coverage_thresholds` | fail | fail |  |
| `test_naming_conventions` | fail | pass | aragora-operator/controllers/aragorainstance_controller_test.go |
| `test_isolation` | fail | fail |  |
| `interactive_qa_exists` | fail | pass | aragora-operator/README.md |
| `interactive_qa_runnable` | fail | pass | aragora-operator/README.md |
| `api_schema_docs` | fail | pass | aragora-operator/helm/aragora-operator/crds/aragora.ai_aragorainstances.yaml |
| `structured_logging` | pass | pass |  |
| `distributed_tracing` | fail | pass | aragora-operator/internal/observability/otel.go |
| `metrics_collection` | pass | pass |  |
| `code_quality_metrics` | fail | fail |  |
| `error_tracking_contextualized` | fail | pass | aragora-operator/internal/observability/sentry.go |
| `alerting_configured` | fail | pass | aragora-operator/helm/aragora-operator/templates/prometheusrule.yaml |
| `deployment_observability` | fail | fail |  |
| `health_checks` | pass | pass |  |
| `circuit_breakers` | fail | pass | aragora-operator/internal/httpclient/client.go |
| `profiling_instrumentation` | fail | pass | aragora-operator/internal/observability/pprof.go |
| `dast_scanning` | n/a | n/a |  |
| `pii_handling` | n/a | n/a |  |
| `log_scrubbing` | fail | pass | aragora-operator/internal/httpclient/redact.go |
| `product_analytics_instrumentation` | n/a | n/a |  |
| `error_to_insight_pipeline` | fail | fail |  |

Notes:

- `aragora-operator/.golangci.yml` (golangci-lint v2) uses `default: standard`
  plus `errcheck`, `govet`, `staticcheck`, `unused`, `dupl` (threshold 150),
  `gocyclo` (min-complexity 16) and `misspell`, with the gofmt formatter and no
  exclusion rules. `revive` is not enabled, so naming is declined
  (VAL-OPERATOR-029).
- Tests: unit tests and an envtest controller suite
  (`controllers/suite_test.go`, Kubernetes 1.29), run by
  `.github/workflows/operator-ci.yml` with a `gotestsum` junit and JSON upload.
  The same workflow runs `go mod tidy -diff` and fails when
  `make generate manifests` changes the checked-in controller-gen CRDs
  (`helm/aragora-operator/crds/`, with `openAPIV3Schema`).
- `README.md` documents running the binary locally on 127.0.0.1 ports and
  checking `/healthz`, `/readyz` and `/metrics` through envtest.
- Observability: a `--pprof-addr` pprof endpoint, env-gated `otelhttp` tracing
  and `sentry-go` (verified against local stubs only), a `PrometheusRule` chart
  template, and a retrying HTTP client with a circuit breaker and log redaction
  in `internal/httpclient/`.
- Still `fail`: `naming_consistency`, `flaky_test_detection`,
  `test_coverage_thresholds` (`make readiness-heavy-operator` prints coverage
  but sets no floor), `test_isolation`, `code_quality_metrics`,
  `deployment_observability` (`docker.yml` still only builds and pushes the
  image) and `error_to_insight_pipeline`. `structured_logging` is out of scope
  and keeps its `pass`.

## Cascade state

Read-only on 2026-10-10 with `gh pr view <n> --json headRefOid,isDraft,mergeStateStatus`:

| PR | Milestone | Head | State |
|---|---|---|---|
| #9982 | M1 governance | `7c30b5a9367b` | OPEN, Draft, DIRTY |
| #9997 | M2 Python core | `79f4d80e0a7e` | OPEN, Draft, DIRTY |
| #10005 | M3 Python packages | `cb612825fc33` | OPEN, Draft, DIRTY |
| #10027 | M4 CI and DAST | `3ded2205feed` | OPEN, Draft, DIRTY |
| #10049 | M5 live quality | `70c5350ba87c` | OPEN, Draft, DIRTY |
| #10052 | M6 live observability | `0fa5d98932b6` | OPEN, Draft, DIRTY |
| #10060 | M7 docs | `e963a9f00905` | OPEN, Draft, DIRTY |
| #10174 | M8 VS Code | `0f21591bd812` | OPEN, Draft, DIRTY |
| #10526 | M9 operator | `bcb0a72f408b` | OPEN, Draft, DIRTY |

- All nine are open Drafts labelled `operator-review-required` and wait for
  direct operator settlement (log §166 d3). M10 is built on M9 and will be
  published the same way: as a Draft, never readied, settled or merged by an
  agent.
- M4 to M9 are DIRTY against `main` by design, on classified paths: the
  generated docs (including `docs/METRICS.md`), the `aragora/live` paths,
  `docs-site/tsconfig.json` from M7, and `scripts/baselines/file_size_baseline.json`.
  GitHub therefore runs no `pull_request` workflows on them ("not triggered:
  conflicts"), and the local gates recorded for each head are the proof. M1 to
  M3 also report DIRTY on this read, because `main` has moved since their last
  refresh.
- The operator merges them in milestone order with "Create a merge commit": no
  agent merge, no squash and no rebase.
- The planned path to mergeability is the deferred settlement-refresh
  recommendation in the mission record: before settling a PR, the operator
  refreshes it against the `main` of that time (regenerate the generated docs,
  take main's `file_size_baseline.json` keys alongside the branch's, then run
  CI at the refreshed head). That is part of the settlement step, not cascade
  work.
- Two gates stay deferred and independent of each other: real-vendor
  telemetry delivery (VAL-LIVEOBS-018, M11 `m11-pr`, which needs recorded
  telemetry consent and real keys) and the Tier-4 branch-protection PATCH (M11
  `m11-branch-protection-patch`, which needs a recorded `AUTHORIZED`, M1 to M9
  merged and at least three green scheduled `Tests` runs of `test-fast-gate`).

### Lock repair and merge chain

- M5 conflict reconciliation: in the 2026-09-12 lock repair against the main
  pin `c3380f9e728a`, M5 (live quality) was the milestone whose live manifest
  and lockfile conflicted with `main`. It was reconciled by a real two-parent
  merge, `61d3bf278f32` = [`deb02e61e175` (M5), `c3380f9e728a` (main)], subject
  `chore(readiness): reconcile with origin/main @c3380f9e728a`, with the live
  lock seeded from the main pin and regenerated by a real `npm ci`. Its
  exact-head gates passed after a verify-only recovery that quarantined stale
  `.next/types` caches without changing the tree or the parents.
- M6 and M7 forward lock repairs: M6 merged cleanly with that pin, so neither
  M6 nor M7 needed a conflict resolution. Their live lock was carried forward
  from the repaired predecessor through predecessor merges, for example R6d
  `aebf82aa5aac` = [`7bd5eb1a0fec`, M5 `4947f35f54d0`] (#10052) and R7e
  `b9b428b07e25` = [R7d `79a36e547250`, R6d `aebf82aa5aac`] (#10060). The
  planned single-parent lock commits (`m6-live-lock-advisory-pins`,
  `m7-lock-cherry-pick`) were cancelled, and the Candidate A dry-run objects
  (for example lock blob `2b706385f0fc`) were throwaway and never became heads.
- Merge-chain and security evidence at R7e (2026-09-24, against main
  `5fb9b036`): seven direct merge-trees exited 0; an ordered chain of real
  two-parent merges in milestone order, built in isolated scratch objects, had
  each tree equal to its direct tree; the strict full mypy tier found 1,612
  findings and 0 new on four direct and four chain trees; every changed lock had
  0 keys below main, and the chain's live lock equalled R6d and R7e; a real
  `npm ci` in the chain snapshot exited 0; production audits were no worse than
  main (live 0 and 0, docs 39 and 39); `uv lock --check` exited 0.
- Later refreshes superseded those heads. The current heads are the ones in the
  table above; each was validated by its own exact-head gates (for M9, the F9
  head `bcb0a72f408b`).

### Merged readiness PRs

`gh pr list --state merged --search "head:readiness/" --json number,headRefName`
lists seven merged PRs. None is a cascade milestone PR: they are re-slice units
and small main-based PRs, readied and merged with merge commits under the
operator's settlement delegation (log §119, §166, §167).

| PR | Branch | Merged (UTC) |
|---|---|---|
| #10238 | `readiness/s01-accounting-dispatch` (S01) | 2026-10-03 |
| #10293 | `readiness/s04-threat-intel-batch` (S04) | 2026-10-06 |
| #10373 | `readiness/s07-docs-tsconfig` (S07a) | 2026-10-09 |
| #10385 | `readiness/s05-live-toolchain` (S05) | 2026-10-09 |
| #10483 | `readiness/metrics-refresh-20261009` | 2026-10-09 |
| #10485 | `readiness/live-handlebars-override` | 2026-10-09 |
| #10492 | `readiness/landing-dev-api-fix` | 2026-10-09 |

The accounting dispatch, auth-forwarding and date-validation work landed on
`main` through S01 (#10238), so this report credits it to that merged PR, not
to M10.

## Observations

These are recorded facts. M10 changes no code for any of them.

### Dependabot

Read-only on 2026-10-10 (`gh api repos/synaptent/aragora/dependabot/alerts?state=open --paginate`):
67 open alerts (7 critical, 24 high, 30 medium, 6 low), all pre-existing on
`main`, and 21 open Dependabot PRs. M10 does not fix them. The earlier M4 and
M5 push banners (36 and 55 alerts) are history.

### Static export

At this head, `aragora/live/README.md` names one static-export blocker: the
page `src/app/(app)/autonomous/bridge/[run_id]/page.tsx`, which lacks
`generateStaticParams()`. The README on `main` names two: that page and the
edge route `src/app/api/og/debate/[id]/route.tsx`. The edge route
(`export const runtime = 'edge'`) also exists at this head, so main's
two-blocker description most likely applies here as well; the export was not
re-run for this report. No mission workflow runs the export scripts. The README
difference is part of the `aragora/live/README.md` add/add conflict that stays
for the operator's settlement refresh.

### frontend-lint and required checks

- M5's extended `frontend-lint` (lint, format, knip, jscpd, typecheck, Jest
  coverage, build and size-limit): cold duration not yet observed (job skipped
  on draft PRs; M5 not merged).
- The `frontend-lint` job on `main` today runs only ESLint and the API type
  sync. It took 70 to 81 seconds in the five most recent `main` push runs
  checked (`gh run list --workflow lint.yml --branch main`; latest run
  38033699330 at `795d843519f9`, 70 seconds).
- `frontend-lint` is not a required context. `main` requires `lint`,
  `typecheck`, `sdk-parity`, `Generate & Validate`, `TypeScript SDK Type Check`
  and `aragora-merge-quorum` (strict off), and the `frontend` job in `test.yml`
  gates on the narrower `frontend_e2e` scope rule. The live quality gates
  therefore run on non-draft PRs but block merges only once an operator adds
  the context; M11 adds only `test-fast-gate`.

### METRICS

- `docs/METRICS.md` is generated by `python3 scripts/regenerate_metrics.py`
  and drift-checked by `.github/workflows/metrics-drift.yml` (`--check`). It is
  never edited by hand.
- At F9 (`bcb0a72f408b`) `--check` exited 0. At the M10 head before this
  report (`13f5256d7cea`) it exited 1 on
  `@pytest.mark.parametrize decorators 1717 -> 1741`, from tests that earlier
  M10 commits added. The generator output was refreshed in a separate
  `chore(readiness): regenerate METRICS.md` commit; at the M10 head `--check`
  exits 0, and running the generator again leaves `docs/METRICS.md` unchanged.
  No generator change was needed, because M10 adds no metric rows.
- Live `main` at `795d843519f9` also drifts: `--check` exited 1 on
  `@pytest.mark.parametrize decorators 1717 -> 1737` and
  `CLI top-level command modules 86 -> 88` (checked read-only in a temporary
  worktree that was removed afterwards).
- `docs/METRICS.md` is one of the classified conflict paths against `main`. At
  the eventual reconcile it is resolved by regenerating it, never by a hand
  merge.

### docs-site

- `docs-site/package.json` still has `deploy` and `deploy:preview` scripts, and
  `docs-site/DEPLOY.md` still describes a Vercel flow, while
  `.github/workflows/deploy-docs.yml` deploys to GitHub Pages. `vercel` is not
  a dependency (knip baseline entry `package.json::vercel::binaries`).
- `clsx` is a declared runtime dependency that docs-site never imports (knip
  baseline entry `package.json::clsx::dependencies`). Both baseline entries
  shrink when someone removes the scripts or the dependency.
- `docs-site/tsconfig.json` keeps `checkJs` off: enabling it at M7 surfaced 67
  pre-existing type errors, 59 in `docs-site/scripts/sync-docs.js` and 8 in
  `scripts/sync-atlas.test.js`. The count was not re-measured for this report.
- `@docusaurus/core` stays pinned at `^3.9.2`; the latest 3.x release is
  3.10.2 (`npm view @docusaurus/core version`, 2026-10-10). The `docs-links`
  parser in `scripts/ci/tool_baseline_parsers.py` is anchored on the 3.9.x
  broken-link report wording, so whoever bumps Docusaurus must re-capture
  `tests/ci/fixtures/tool_baseline/docs-links.txt` from a fresh build log and
  re-run `make readiness-heavy-docs` before regenerating
  `scripts/baselines/docs-broken-links.json`.

### Live observability limitations

- `capture` in `aragora/live/src/lib/analytics.ts` has no production call
  sites yet. Future callers must await `telemetryReady` (exported by
  `instrumentation-client.ts`) before capturing, or early events can be lost.
- `src/lib/logger.ts` has one importer, the Node `/healthz` route. Keeping it
  out of client and edge bundles relies on a code comment; nothing enforces it
  automatically.
- Real Sentry and PostHog delivery (VAL-LIVEOBS-018) is deferred to M11
  `m11-pr`; every observability row above credits stub-verified wiring only.

### Observed pre-existing operator defects (not fixed here)

- `getResourceRequests` defaults the CPU request to `resourceQuantityPtr(250)`, 250 cores, above the 500m limit, so the Deployment is rejected; the envtest suite sets the cluster's `RequestsCPU`.
- `reconcileDeployment` dereferences `instance.Spec.Scaling` without a nil check (`aragora-operator/controllers/aragorainstance_controller.go`), so an instance without `spec.scaling` panics; `main.go` does not set `RecoverPanic` (only the envtest helper does).
- `AragoraPolicySpec.Enabled` is `omitempty` with CRD default true, so a disabled policy cannot be expressed; zero `resource.Quantity` fields serialize as "0", so the CRD defaults for memory, CPU and storage never apply.
- The chart's `metrics.serviceMonitor` values are unused: there is no ServiceMonitor or metrics Service template, and scraping relies on the `prometheus.io/*` pod annotations.

## Known reds inherited from M9

M10 inherits three reds from F9 (`bcb0a72f408b`). The M10 PR body lists them as
known reds; M10 does not baseline the keys, rename the classes or edit the
test.

- `make readiness-lint` is non-zero only because the root naming ratchet
  reports two NEW keys for classes that landed on `main`:
  `aragora/security/approval_enforcer.py::10bcc6c8ff34::N818`
  (`ApprovalCapabilityUnavailable`) and
  `aragora/swarm/merge_halt.py::6cf76d4f8913::N818` (`MergeHalted`).
- `make readiness-test` is non-zero only because of the root failure
  `tests/ci/test_release_gates.py::TestPipAuditGate::test_allowlist_omits_resolved_pyjwt_debt`.
- `make readiness-typecheck` exits 0.

## Proposed protected-file changes

Text only, for the M10 PR body. This branch does not edit either file; the
operator decides whether to apply them.

`AGENTS.md`, after the Operating Contract note at the top:

```markdown
> **Quality gates:** before opening a PR, run `make readiness-lint`,
> `make readiness-typecheck` and `make readiness-test` (each prints
> `SKIP <app>: <reason>` when a toolchain is missing). Baselines are
> shrink-only; see [`docs/RATCHETS.md`](docs/RATCHETS.md). Before/after
> readiness evidence: [`docs/READINESS_REPORT.md`](docs/READINESS_REPORT.md).
```

`CLAUDE.md`, two new rows in the Key Documentation table:

```markdown
| `docs/RATCHETS.md` | Shrink-only quality ratchets behind the `make readiness-*` gates |
| `docs/READINESS_REPORT.md` | Agent-readiness before/after report (Factory audit 85b9e93d) |
```
