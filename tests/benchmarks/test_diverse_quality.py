"""Diverse debate quality benchmark: validate 80%+ pass rate across 10 domain categories.

This benchmark creates realistic multi-agent debate outputs for each prompt category
and runs them through the real quality scoring pipeline (OutputContract validation +
repo grounding). No LLM calls are made -- outputs are fixed synthetic text that
exercises the full deterministic scoring path.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from aragora.debate.output_quality import (
    OutputContract,
    OutputQualityReport,
    validate_output_against_contract,
)
from aragora.debate.repo_grounding import assess_repo_grounding

logger = logging.getLogger(__name__)

PROMPTS_PATH = Path(__file__).parent / "diverse_quality_prompts.json"
# Use the workspace root for repo grounding so real paths resolve.
REPO_ROOT = str(Path(__file__).resolve().parents[2])

# Composite score formula: normalised quality (0-1) * 0.4 + normalised practicality (0-1) * 0.6
# Mirrors dogfood run 012 weighting: practicality-dominant composite.
COMPOSITE_WEIGHT_QUALITY = 0.4
COMPOSITE_WEIGHT_PRACTICALITY = 0.6
COMPOSITE_PASS_THRESHOLD = 0.5
PASS_RATE_THRESHOLD = 0.80  # 80% of prompts must pass


def _load_prompts() -> list[dict[str, str]]:
    raw = PROMPTS_PATH.read_text(encoding="utf-8")
    prompts = json.loads(raw)
    assert isinstance(prompts, list) and len(prompts) >= 10
    return prompts


def _standard_contract() -> OutputContract:
    """Return the standard 7-section contract used in dogfood benchmarks."""
    return OutputContract(
        required_sections=[
            "Ranked High-Level Tasks",
            "Suggested Subtasks",
            "Owner module / file paths",
            "Test Plan",
            "Rollback Plan",
            "Gate Criteria",
            "JSON Payload",
        ],
        require_json_payload=True,
        require_gate_thresholds=True,
        require_rollback_triggers=True,
        require_owner_paths=True,
        require_repo_path_existence=True,
        require_practicality_checks=True,
    )


# ---------------------------------------------------------------------------
# Synthetic debate outputs -- one per category.
#
# Each output is structured markdown matching the 7-section contract.
# Content includes action verbs, real repo paths, thresholds, and rollback
# triggers so the deterministic quality pipeline scores them realistically.
# ---------------------------------------------------------------------------

_DEBATE_OUTPUTS: dict[str, str] = {
    "strategic": """\
## Ranked High-Level Tasks

1. **Define service boundaries** -- Run `aragora/debate/orchestrator.py` domain analysis to identify bounded contexts and extract three candidate microservice boundaries from the monolith module graph.
2. **Implement API gateway routing** -- Update `aragora/gateway/router.py` to add path-based routing rules that proxy requests to the new service endpoints with circuit-breaker protection via `aragora/resilience/circuit_breaker.py`.
3. **Extract shared data layer** -- Refactor `aragora/storage/postgres_store.py` to expose a shared schema interface and migrate tenant-specific queries into `aragora/tenancy/isolation.py` with backward-compatible fallback.
4. **Deploy canary service** -- Configure `aragora/ops/deployment_validator.py` to validate the first extracted service with traffic-split canary deployment at 5% threshold.

## Suggested Subtasks

- Add integration test in `tests/gateway/test_router.py` verifying round-trip latency under 200ms for proxied routes.
- Create migration script to split `aragora/storage/schema.py` tables into per-service schemas; verify with `pytest tests/storage/test_schema.py -v`.
- Add health check endpoint in `aragora/resilience/health.py` and validate with `pytest tests/resilience/test_health.py -k health_check`.
- Write load test targeting the gateway at 500 rps and assert p99 < 300ms.

## Owner module / file paths

- `aragora/gateway/router.py`
- `aragora/storage/postgres_store.py`
- `aragora/resilience/circuit_breaker.py`
- `aragora/ops/deployment_validator.py`
- `aragora/tenancy/isolation.py`
- `tests/gateway/test_router.py`

## Test Plan

- Run `pytest tests/gateway/ -v --timeout=30` to validate routing changes.
- Run `pytest tests/storage/ -v -k schema` to verify schema migration.
- Run `pytest tests/resilience/ -v -k circuit_breaker` to confirm breaker integration.
- All existing tests must pass with zero regressions.

## Rollback Plan

If error_rate exceeds 2% for 10 minutes after canary deployment, disable the feature flag `ENABLE_MICROSERVICE_ROUTING` in `aragora/gateway/router.py` and revert traffic to the monolith path. Restore the original `aragora/storage/schema.py` from the pre-migration backup.

## Gate Criteria

- p99 latency <= 300ms for gateway-proxied routes over 15 minutes.
- error_rate < 1% across all service endpoints for 30 minutes.
- All 500+ existing integration tests must pass.
- Zero data inconsistencies between old and new schema after migration.
- Canary traffic split must not exceed 5% until gate criteria are met.

## JSON Payload

```json
{
  "ranked_high_level_tasks": [
    "Define service boundaries via aragora/debate/orchestrator.py domain analysis",
    "Implement API gateway routing in aragora/gateway/router.py",
    "Extract shared data layer from aragora/storage/postgres_store.py",
    "Deploy canary service via aragora/ops/deployment_validator.py"
  ],
  "gate_criteria": {
    "p99_latency_ms": 300,
    "error_rate_pct": 1,
    "test_pass_rate": "100%"
  }
}
```
""",
    "security": """\
## Ranked High-Level Tasks

1. **Implement OIDC token validation** -- Update `aragora/auth/oidc.py` to enforce audience and issuer claims on every incoming JWT, rejecting tokens missing the `aud` field.
2. **Add mTLS for inter-service calls** -- Configure `aragora/gateway/server.py` to require client certificates for all backend service communication via TLS 1.3.
3. **Enforce RBAC on all API routes** -- Wire `aragora/rbac/middleware.py` into `aragora/server/unified_server.py` to check permissions before handler dispatch, using the 360+ permission definitions in `aragora/rbac/types.py`.
4. **Deploy anomaly detection** -- Enable `aragora/security/anomaly_detection.py` to monitor authentication patterns and flag brute-force attempts exceeding 10 failures per minute per IP.

## Suggested Subtasks

- Add unit tests for token validation edge cases in `tests/auth/test_oidc.py` covering expired, missing-aud, and revoked tokens.
- Write integration test in `tests/security/test_anomaly_detection.py` simulating 15 failed logins and asserting alert fires within 60 seconds.
- Add SSRF protection test in `tests/security/test_ssrf_protection.py` verifying all internal IPs are blocked.
- Validate key rotation with `pytest tests/security/test_key_rotation.py -v`.

## Owner module / file paths

- `aragora/auth/oidc.py`
- `aragora/gateway/server.py`
- `aragora/rbac/middleware.py`
- `aragora/rbac/types.py`
- `aragora/security/anomaly_detection.py`
- `aragora/security/ssrf_protection.py`
- `aragora/security/key_rotation.py`

## Test Plan

- Run `pytest tests/auth/ -v --timeout=30` to validate OIDC changes.
- Run `pytest tests/rbac/ -v` to verify middleware integration.
- Run `pytest tests/security/ -v` to confirm anomaly detection and SSRF.
- All tests must pass with no regressions.

## Rollback Plan

If authentication failures exceed 5% of total requests within 15 minutes after deployment, disable the new OIDC validation by reverting `aragora/auth/oidc.py` to the previous commit and redeploy the stable build. Restore the old RBAC middleware configuration from backup.

## Gate Criteria

- Authentication success rate >= 99.5% for legitimate users over 30 minutes.
- Zero SSRF bypass detections in security scan.
- Anomaly detection fires within 60 seconds of brute-force threshold breach.
- All 1200+ RBAC permission tests must pass.
- p95 latency for auth endpoints < 150ms.

## JSON Payload

```json
{
  "ranked_high_level_tasks": [
    "Implement OIDC token validation in aragora/auth/oidc.py",
    "Add mTLS for inter-service calls in aragora/gateway/server.py",
    "Enforce RBAC on all API routes via aragora/rbac/middleware.py",
    "Deploy anomaly detection via aragora/security/anomaly_detection.py"
  ],
  "gate_criteria": {
    "auth_success_rate_pct": 99.5,
    "ssrf_bypasses": 0,
    "anomaly_detection_latency_sec": 60
  }
}
```
""",
    "hiring": """\
## Ranked High-Level Tasks

1. **Audit current DevOps coverage gaps** -- Run `aragora/audit/codebase_auditor.py` against the CI pipeline configuration and identify automation gaps in `aragora/ops/deployment_validator.py` that would benefit from dedicated expertise.
2. **Build self-service deployment tooling** -- Extend `aragora/ops/deployment_validator.py` with a `--dry-run` mode and create a runbook template in `aragora/workflow/templates/` so existing engineers can deploy independently.
3. **Implement monitoring dashboards** -- Configure `aragora/observability/metrics.py` and `aragora/observability/tracing.py` to expose key SRE metrics (error budget, MTTR, deployment frequency) via Prometheus.
4. **Create DevOps training curriculum** -- Document standard operational procedures based on `aragora/resilience/circuit_breaker.py` patterns and `aragora/backup/manager.py` disaster recovery workflows.

## Suggested Subtasks

- Add deployment validation tests in `tests/ops/test_deployment_validator.py` covering dry-run mode.
- Create Prometheus metric exports and verify with `pytest tests/observability/test_metrics.py -v`.
- Build runbook template and validate with `pytest tests/workflow/test_templates.py -k deployment`.
- Measure current MTTR baseline and track with `aragora/observability/slo.py`.

## Owner module / file paths

- `aragora/audit/codebase_auditor.py`
- `aragora/ops/deployment_validator.py`
- `aragora/observability/metrics.py`
- `aragora/observability/tracing.py`
- `aragora/observability/slo.py`
- `aragora/resilience/circuit_breaker.py`
- `aragora/backup/manager.py`

## Test Plan

- Run `pytest tests/ops/ -v` to validate deployment tooling.
- Run `pytest tests/observability/ -v` to confirm metric exports.
- Run `pytest tests/resilience/ -v -k circuit_breaker` to verify patterns.
- All existing tests must pass with no regressions.

## Rollback Plan

If deployment tooling introduces failures exceeding 3% error rate, disable the new dry-run mode via feature flag and revert to the manual deployment process. Restore previous `aragora/ops/deployment_validator.py` from the last stable commit.

## Gate Criteria

- Deployment dry-run mode succeeds on 100% of test environments.
- Prometheus metrics endpoint responds with all required SRE counters.
- Error budget consumption < 5% during rollout period.
- All 200+ ops and observability tests must pass.
- MTTR measured and baselined at < 60 minutes.

## JSON Payload

```json
{
  "ranked_high_level_tasks": [
    "Audit DevOps coverage gaps via aragora/audit/codebase_auditor.py",
    "Build self-service deployment tooling in aragora/ops/deployment_validator.py",
    "Implement monitoring dashboards via aragora/observability/metrics.py",
    "Create DevOps training curriculum from resilience patterns"
  ],
  "gate_criteria": {
    "dry_run_success_rate": "100%",
    "error_budget_pct": 5,
    "mttr_minutes": 60
  }
}
```
""",
    "legal": """\
## Ranked High-Level Tasks

1. **Scan codebase for GPL dependencies** -- Run `aragora/audit/codebase_auditor.py` with license-scan mode to identify all transitive GPL-licensed packages in `requirements.txt` and `pyproject.toml`.
2. **Implement license compliance checker** -- Add a new validation rule in `aragora/compliance/framework.py` that flags GPL-incompatible dependencies before merge, integrated with the CI pipeline.
3. **Isolate GPL components** -- Refactor `aragora/connectors/` to separate any GPL-tainted connectors into optional plugin packages that are not bundled in the core SaaS distribution.
4. **Add SBOM generation** -- Extend `aragora/compliance/report_generator.py` to produce CycloneDX SBOM artifacts listing all dependencies with license metadata.

## Suggested Subtasks

- Create license scanning test in `tests/compliance/test_framework.py` asserting zero GPL violations in core packages.
- Add SBOM output validation in `tests/compliance/test_report_generator.py` verifying CycloneDX format.
- Write connector isolation test in `tests/connectors/test_plugin_isolation.py` verifying GPL connectors are optional.
- Validate CI integration with `pytest tests/audit/test_codebase_auditor.py -k license`.

## Owner module / file paths

- `aragora/audit/codebase_auditor.py`
- `aragora/compliance/framework.py`
- `aragora/compliance/report_generator.py`
- `aragora/connectors/__init__.py`
- `tests/compliance/test_framework.py`

## Test Plan

- Run `pytest tests/compliance/ -v` to validate license checks and SBOM.
- Run `pytest tests/audit/ -v -k license` to confirm scanner integration.
- Run `pytest tests/connectors/ -v -k isolation` to verify plugin separation.
- All tests must pass with no new GPL violations.

## Rollback Plan

If the license scanner blocks legitimate dependencies during CI, disable the GPL check rule in `aragora/compliance/framework.py` by setting `ENABLE_LICENSE_SCAN=false` and revert to the previous compliance configuration. Restore connector bundling from the pre-isolation commit.

## Gate Criteria

- Zero GPL-licensed packages in core distribution after isolation.
- SBOM generation completes in < 30 seconds for full dependency tree.
- CI license scan runs in < 60 seconds per PR.
- All 300+ compliance tests must pass.
- No regressions in existing connector functionality.

## JSON Payload

```json
{
  "ranked_high_level_tasks": [
    "Scan codebase for GPL dependencies via aragora/audit/codebase_auditor.py",
    "Implement license compliance checker in aragora/compliance/framework.py",
    "Isolate GPL components from aragora/connectors/",
    "Add SBOM generation in aragora/compliance/report_generator.py"
  ],
  "gate_criteria": {
    "gpl_violations_core": 0,
    "sbom_generation_sec": 30,
    "ci_scan_sec": 60
  }
}
```
""",
    "performance": """\
## Ranked High-Level Tasks

1. **Profile hot paths** -- Instrument `aragora/server/unified_server.py` request handling with `aragora/observability/tracing.py` spans to identify the top 3 latency contributors in the p99 path.
2. **Add response caching** -- Implement Redis-backed response caching in `aragora/storage/redis_ha.py` for idempotent GET endpoints, with TTL-based invalidation and cache-hit metrics via `aragora/observability/metrics.py`.
3. **Optimize database queries** -- Refactor `aragora/storage/postgres_store.py` to add covering indexes for the 5 slowest queries identified by EXPLAIN ANALYZE, and batch N+1 queries in `aragora/storage/repositories/`.
4. **Enable connection pooling** -- Configure `aragora/storage/postgres_store.py` with pgbouncer-compatible connection pooling, limiting max connections to 50 with 30-second idle timeout.

## Suggested Subtasks

- Add latency tracing test in `tests/observability/test_tracing.py` verifying span creation for request lifecycle.
- Write cache integration test in `tests/storage/test_redis_ha.py` asserting cache-hit ratio > 60% for repeated queries.
- Create query benchmark in `tests/benchmarks/test_performance.py` measuring p99 before and after index addition.
- Validate connection pool behavior with `pytest tests/storage/test_postgres_store.py -k pool`.

## Owner module / file paths

- `aragora/server/unified_server.py`
- `aragora/observability/tracing.py`
- `aragora/observability/metrics.py`
- `aragora/storage/redis_ha.py`
- `aragora/storage/postgres_store.py`
- `aragora/storage/repositories/__init__.py`

## Test Plan

- Run `pytest tests/storage/ -v --timeout=30` to validate query optimizations.
- Run `pytest tests/observability/ -v` to confirm tracing integration.
- Run `pytest tests/benchmarks/test_performance.py -v` to measure latency improvement.
- All tests must pass with no regressions.

## Rollback Plan

If p99 latency degrades beyond 3 seconds after deploying caching changes, disable the Redis cache layer by setting `CACHE_ENABLED=false` in environment config and revert `aragora/storage/redis_ha.py` to the previous commit. Restore original query patterns from backup.

## Gate Criteria

- p99 latency <= 500ms for API endpoints over 15 minutes (down from 2.3s baseline).
- Cache hit ratio >= 60% for idempotent GET endpoints.
- Database query p95 < 50ms after index optimization.
- Connection pool utilization < 80% under peak load.
- All 1000+ storage tests must pass.

## JSON Payload

```json
{
  "ranked_high_level_tasks": [
    "Profile hot paths in aragora/server/unified_server.py",
    "Add response caching in aragora/storage/redis_ha.py",
    "Optimize database queries in aragora/storage/postgres_store.py",
    "Enable connection pooling with pgbouncer-compatible settings"
  ],
  "gate_criteria": {
    "p99_latency_ms": 500,
    "cache_hit_ratio_pct": 60,
    "query_p95_ms": 50,
    "pool_utilization_pct": 80
  }
}
```
""",
    "product": """\
## Ranked High-Level Tasks

1. **Audit mobile usage patterns** -- Analyze `aragora/analytics/dashboard.py` session data to determine mobile vs desktop traffic split and identify the top 5 mobile-critical user flows.
2. **Implement responsive design system** -- Update `aragora/server/handlers/` endpoint responses to support viewport-adaptive layouts and create mobile-optimized API response formats.
3. **Add PWA manifest** -- Configure `aragora/server/unified_server.py` to serve a Progressive Web App manifest with offline support, enabling install-to-homescreen on mobile browsers.
4. **Build mobile-first debate interface** -- Refactor `aragora/server/stream/voice_stream.py` to support touch-based interaction patterns and optimize WebSocket payload sizes for mobile bandwidth constraints.

## Suggested Subtasks

- Add analytics query test in `tests/analytics/test_dashboard.py` verifying mobile vs desktop session breakdown.
- Write responsive handler test in `tests/server/test_handlers.py` asserting correct Content-Type headers for mobile User-Agents.
- Create PWA manifest validation test verifying offline cache registration.
- Test WebSocket payload compression with `pytest tests/server/test_stream.py -k mobile`.

## Owner module / file paths

- `aragora/analytics/dashboard.py`
- `aragora/server/handlers/__init__.py`
- `aragora/server/unified_server.py`
- `aragora/server/stream/voice_stream.py`
- `tests/analytics/test_dashboard.py`

## Test Plan

- Run `pytest tests/analytics/ -v` to validate usage analytics.
- Run `pytest tests/server/ -v -k handler` to verify responsive endpoints.
- Run `pytest tests/server/ -v -k stream` to confirm mobile WebSocket optimization.
- All tests must pass with no regressions.

## Rollback Plan

If mobile engagement drops below 5% of desktop engagement after PWA deployment, disable the PWA manifest by removing the service worker registration in `aragora/server/unified_server.py` and revert to the server-rendered mobile fallback. Restore original WebSocket payload format.

## Gate Criteria

- Mobile page load time < 3 seconds on 3G connection simulation.
- PWA lighthouse score >= 90 for installability and offline support.
- WebSocket payload size reduced by >= 40% for mobile clients.
- All 500+ server tests must pass.
- No regressions in desktop user experience metrics.

## JSON Payload

```json
{
  "ranked_high_level_tasks": [
    "Audit mobile usage patterns via aragora/analytics/dashboard.py",
    "Implement responsive design system in aragora/server/handlers/",
    "Add PWA manifest to aragora/server/unified_server.py",
    "Build mobile-first debate interface in aragora/server/stream/"
  ],
  "gate_criteria": {
    "mobile_load_time_sec": 3,
    "lighthouse_score": 90,
    "payload_size_reduction_pct": 40
  }
}
```
""",
    "data": """\
## Ranked High-Level Tasks

1. **Define retention policies per data category** -- Update `aragora/privacy/retention.py` to implement tiered retention rules: 30 days for session data, 1 year for audit logs, 7 years for financial records, with automatic purge scheduling.
2. **Implement right-to-erasure workflow** -- Extend `aragora/privacy/deletion.py` to support GDPR Article 17 deletion requests with cascading deletion across `aragora/storage/postgres_store.py` and `aragora/memory/continuum/`.
3. **Add consent management** -- Wire `aragora/privacy/consent.py` into `aragora/server/unified_server.py` request pipeline to track and enforce per-purpose consent with granular opt-out for analytics vs core functionality.
4. **Build compliance audit trail** -- Extend `aragora/compliance/monitor.py` to log all data access, retention actions, and deletion events with tamper-evident hashing via `aragora/gauntlet/receipts.py`.

## Suggested Subtasks

- Add retention policy tests in `tests/privacy/test_retention.py` verifying purge triggers at correct intervals.
- Write deletion cascade test in `tests/privacy/test_deletion.py` confirming all related records are removed.
- Create consent tracking test in `tests/privacy/test_consent.py` asserting per-purpose granularity.
- Validate audit trail integrity with `pytest tests/compliance/test_monitor.py -k audit_trail`.

## Owner module / file paths

- `aragora/privacy/retention.py`
- `aragora/privacy/deletion.py`
- `aragora/privacy/consent.py`
- `aragora/compliance/monitor.py`
- `aragora/gauntlet/receipts.py`
- `aragora/storage/postgres_store.py`

## Test Plan

- Run `pytest tests/privacy/ -v --timeout=30` to validate retention and deletion.
- Run `pytest tests/compliance/ -v -k monitor` to confirm audit trails.
- Run `pytest tests/gauntlet/ -v -k receipts` to verify tamper-evident hashing.
- All tests must pass with no regressions.

## Rollback Plan

If the retention purge job deletes data prematurely, disable the automatic purge scheduler in `aragora/privacy/retention.py` and restore affected records from the latest backup via `aragora/backup/manager.py`. Revert consent enforcement to permissive mode.

## Gate Criteria

- Retention purge executes within 5 minutes of scheduled trigger.
- Right-to-erasure completes cascade deletion across all stores in < 120 seconds.
- Consent state changes are logged with < 1 second latency.
- All 400+ privacy and compliance tests must pass.
- Zero orphaned records after deletion cascade.

## JSON Payload

```json
{
  "ranked_high_level_tasks": [
    "Define retention policies in aragora/privacy/retention.py",
    "Implement right-to-erasure in aragora/privacy/deletion.py",
    "Add consent management via aragora/privacy/consent.py",
    "Build compliance audit trail in aragora/compliance/monitor.py"
  ],
  "gate_criteria": {
    "purge_latency_min": 5,
    "erasure_latency_sec": 120,
    "consent_log_latency_sec": 1
  }
}
```
""",
    "ml": """\
## Ranked High-Level Tasks

1. **Evaluate managed vs custom trade-offs** -- Analyze `aragora/agents/api_agents/` integration patterns to determine which model providers already offer managed ML pipelines and calculate the cost delta using `aragora/billing/cost_tracker.py`.
2. **Build model versioning layer** -- Implement version tracking in `aragora/rlm/factory.py` to tag each model deployment with a semantic version, enabling A/B testing and rollback to previous model versions.
3. **Add feature store integration** -- Extend `aragora/knowledge/bridges.py` to serve as a lightweight feature store, caching computed features in `aragora/storage/redis_ha.py` with TTL-based invalidation.
4. **Implement model monitoring** -- Wire `aragora/observability/metrics.py` to track prediction latency, drift detection, and accuracy degradation for all models registered in `aragora/rlm/handler.py`.

## Suggested Subtasks

- Add cost comparison test in `tests/billing/test_cost_tracker.py` verifying managed vs custom pipeline cost calculation.
- Write version tracking test in `tests/rlm/test_factory.py` asserting correct version tagging and retrieval.
- Create feature caching test in `tests/storage/test_redis_ha.py` validating TTL eviction behavior.
- Add model monitoring test in `tests/observability/test_metrics.py` verifying drift detection alerts.

## Owner module / file paths

- `aragora/agents/api_agents/__init__.py`
- `aragora/billing/cost_tracker.py`
- `aragora/rlm/factory.py`
- `aragora/rlm/handler.py`
- `aragora/knowledge/bridges.py`
- `aragora/storage/redis_ha.py`
- `aragora/observability/metrics.py`

## Test Plan

- Run `pytest tests/billing/ -v -k cost` to validate cost analysis.
- Run `pytest tests/rlm/ -v` to verify version tracking and model management.
- Run `pytest tests/observability/ -v -k metrics` to confirm monitoring.
- All tests must pass with no regressions.

## Rollback Plan

If the new model versioning layer causes inference latency to exceed 500ms, disable the version tracking middleware in `aragora/rlm/factory.py` and revert to direct model dispatch. Restore the previous feature caching configuration from backup.

## Gate Criteria

- Model inference p95 latency < 200ms with versioning overhead.
- Feature store cache hit ratio >= 75% for repeated predictions.
- Drift detection alerts fire within 5 minutes of distribution shift.
- Cost tracking accuracy within 2% of actual provider billing.
- All 300+ RLM and billing tests must pass.

## JSON Payload

```json
{
  "ranked_high_level_tasks": [
    "Evaluate managed vs custom via aragora/billing/cost_tracker.py",
    "Build model versioning in aragora/rlm/factory.py",
    "Add feature store via aragora/knowledge/bridges.py",
    "Implement model monitoring in aragora/observability/metrics.py"
  ],
  "gate_criteria": {
    "inference_p95_ms": 200,
    "cache_hit_ratio_pct": 75,
    "drift_alert_latency_min": 5,
    "cost_accuracy_pct": 2
  }
}
```
""",
    "culture": """\
## Ranked High-Level Tasks

1. **Define review workflow template** -- Create a code review workflow in `aragora/workflow/templates/` that enforces two-reviewer approval with automated assignment rotation using `aragora/workflow/engine.py`.
2. **Implement review metrics tracking** -- Extend `aragora/analytics/debate_analytics.py` to track review cycle time, comment density, and first-response latency per engineer with dashboards in `aragora/analytics/dashboard.py`.
3. **Add automated review checks** -- Wire `aragora/audit/codebase_auditor.py` into the pre-merge pipeline to run lint, type-check, and security scan automatically before human review begins.
4. **Build review assignment rotation** -- Implement round-robin reviewer assignment in `aragora/control_plane/scheduler.py` with expertise-based weighting derived from `aragora/ranking/elo.py` skill ratings.

## Suggested Subtasks

- Create workflow template test in `tests/workflow/test_templates.py` verifying two-reviewer enforcement.
- Add analytics test in `tests/analytics/test_debate_analytics.py` asserting cycle time and comment density calculation.
- Write audit integration test in `tests/audit/test_codebase_auditor.py` validating pre-merge check execution.
- Test reviewer rotation with `pytest tests/control_plane/test_scheduler.py -k rotation`.

## Owner module / file paths

- `aragora/workflow/engine.py`
- `aragora/workflow/templates/__init__.py`
- `aragora/analytics/debate_analytics.py`
- `aragora/analytics/dashboard.py`
- `aragora/audit/codebase_auditor.py`
- `aragora/control_plane/scheduler.py`
- `aragora/ranking/elo.py`

## Test Plan

- Run `pytest tests/workflow/ -v -k template` to validate review workflow.
- Run `pytest tests/analytics/ -v` to verify metrics tracking.
- Run `pytest tests/control_plane/ -v -k scheduler` to confirm rotation.
- All tests must pass with no regressions.

## Rollback Plan

If the automated review assignment causes review bottlenecks exceeding 48-hour average cycle time, disable the rotation scheduler in `aragora/control_plane/scheduler.py` and revert to manual reviewer assignment. Restore the previous workflow template from the stable commit.

## Gate Criteria

- Average review cycle time < 24 hours for PRs under 500 lines.
- First-response latency < 4 hours during business hours.
- Automated pre-merge checks complete in < 5 minutes per PR.
- All 1500+ control plane tests must pass.
- No increase in review abandonment rate.

## JSON Payload

```json
{
  "ranked_high_level_tasks": [
    "Define review workflow template in aragora/workflow/templates/",
    "Implement review metrics in aragora/analytics/debate_analytics.py",
    "Add automated review checks via aragora/audit/codebase_auditor.py",
    "Build review assignment rotation in aragora/control_plane/scheduler.py"
  ],
  "gate_criteria": {
    "review_cycle_time_hours": 24,
    "first_response_hours": 4,
    "premerge_check_minutes": 5
  }
}
```
""",
    "crisis": """\
## Ranked High-Level Tasks

1. **Assess data loss scope** -- Run `aragora/backup/manager.py` inventory check to determine the last successful backup timestamp and calculate the exact recovery point objective (RPO) gap.
2. **Execute point-in-time recovery** -- Use `aragora/backup/manager.py` restore function targeting the most recent incremental backup, with verification via `aragora/storage/postgres_store.py` consistency checks.
3. **Replay write-ahead logs** -- Extract and replay WAL segments from `aragora/storage/postgres_store.py` to recover transactions between the last backup and the failure point, minimizing data loss to < 15 minutes.
4. **Implement post-recovery validation** -- Run `aragora/ops/deployment_validator.py` integrity checks across all critical tables and verify data consistency with `aragora/compliance/monitor.py` audit trail comparison.

## Suggested Subtasks

- Run backup inventory with `pytest tests/backup/test_manager.py -k inventory` to verify backup catalog is intact.
- Execute restore dry-run with `pytest tests/backup/test_manager.py -k restore` to validate recovery procedure.
- Write WAL replay verification test in `tests/storage/test_postgres_store.py` asserting transaction continuity.
- Add post-recovery integrity test in `tests/ops/test_deployment_validator.py` validating table checksums.

## Owner module / file paths

- `aragora/backup/manager.py`
- `aragora/storage/postgres_store.py`
- `aragora/ops/deployment_validator.py`
- `aragora/compliance/monitor.py`
- `tests/backup/test_manager.py`

## Test Plan

- Run `pytest tests/backup/ -v --timeout=60` to validate backup and restore.
- Run `pytest tests/storage/ -v -k postgres` to verify data consistency.
- Run `pytest tests/ops/ -v -k validator` to confirm integrity checks.
- All critical path tests must pass before declaring recovery complete.

## Rollback Plan

If the point-in-time recovery introduces data corruption detectable by checksum mismatch, abandon the partial restore and fall back to the last known-good full backup from `aragora/backup/manager.py`. Notify all affected tenants via `aragora/notifications/service.py` and initiate manual data reconciliation for the gap period.

## Gate Criteria

- Recovery point objective (RPO) gap < 15 minutes of data loss.
- Recovery time objective (RTO) < 2 hours from incident declaration.
- Data integrity checksum match rate >= 99.99% across all critical tables.
- Zero orphaned foreign key references after recovery.
- All 200+ backup and storage tests must pass post-recovery.

## JSON Payload

```json
{
  "ranked_high_level_tasks": [
    "Assess data loss scope via aragora/backup/manager.py",
    "Execute point-in-time recovery from incremental backup",
    "Replay write-ahead logs from aragora/storage/postgres_store.py",
    "Implement post-recovery validation via aragora/ops/deployment_validator.py"
  ],
  "gate_criteria": {
    "rpo_minutes": 15,
    "rto_hours": 2,
    "checksum_match_pct": 99.99
  }
}
```
""",
}


def _compute_composite(report: OutputQualityReport) -> float:
    """Compute composite score: quality_score_10 and practicality_score_10 normalised to 0-1."""
    quality_norm = report.quality_score_10 / 10.0
    practicality_norm = report.practicality_score_10 / 10.0
    return round(
        COMPOSITE_WEIGHT_QUALITY * quality_norm + COMPOSITE_WEIGHT_PRACTICALITY * practicality_norm,
        4,
    )


@pytest.fixture(scope="module")
def prompts() -> list[dict[str, str]]:
    return _load_prompts()


@pytest.fixture(scope="module")
def contract() -> OutputContract:
    return _standard_contract()


@pytest.fixture(scope="module")
def benchmark_results(
    prompts: list[dict[str, str]], contract: OutputContract
) -> list[dict[str, Any]]:
    """Run all prompts through the scoring pipeline and collect results."""
    results: list[dict[str, Any]] = []
    for prompt_entry in prompts:
        pid = prompt_entry["id"]
        category = prompt_entry["category"]
        prompt_text = prompt_entry["prompt"]
        debate_output = _DEBATE_OUTPUTS.get(pid, "")
        assert debate_output, f"No synthetic debate output for prompt id={pid}"

        report = validate_output_against_contract(
            debate_output,
            contract,
            repo_root=REPO_ROOT,
        )
        grounding = assess_repo_grounding(
            debate_output,
            repo_root=REPO_ROOT,
        )
        composite = _compute_composite(report)

        result = {
            "id": pid,
            "category": category,
            "prompt": prompt_text,
            "quality_score_10": report.quality_score_10,
            "practicality_score_10": report.practicality_score_10,
            "path_existence_rate": report.path_existence_rate,
            "first_batch_concreteness": report.first_batch_concreteness,
            "placeholder_rate": report.placeholder_rate,
            "composite": composite,
            "verdict": report.verdict,
            "defects": report.defects,
            "existing_paths": report.existing_repo_paths,
            "missing_paths": report.missing_repo_paths,
            "passed": composite >= COMPOSITE_PASS_THRESHOLD,
        }
        results.append(result)

        logger.info(
            "Prompt [%s/%s] quality=%.2f practicality=%.2f composite=%.4f verdict=%s defects=%d",
            pid,
            category,
            report.quality_score_10,
            report.practicality_score_10,
            composite,
            report.verdict,
            len(report.defects),
        )
        if report.defects:
            for defect in report.defects:
                logger.info("  defect: %s", defect)

    return results


class TestDiverseQualityBenchmark:
    """Validate that 80%+ of diverse prompts pass the composite quality threshold."""

    def test_all_prompts_loaded(self, prompts: list[dict[str, str]]) -> None:
        """All 10 diverse prompts are loaded from JSON."""
        assert len(prompts) == 10
        ids = {p["id"] for p in prompts}
        expected = {
            "strategic",
            "security",
            "hiring",
            "legal",
            "performance",
            "product",
            "data",
            "ml",
            "culture",
            "crisis",
        }
        assert ids == expected

    def test_pass_rate_above_threshold(self, benchmark_results: list[dict[str, Any]]) -> None:
        """At least 80% of prompts must score above 0.5 composite."""
        total = len(benchmark_results)
        passed = sum(1 for r in benchmark_results if r["passed"])
        pass_rate = passed / total if total else 0.0

        logger.info(
            "BENCHMARK SUMMARY: %d/%d passed (%.1f%%), threshold=%.0f%%",
            passed,
            total,
            pass_rate * 100,
            PASS_RATE_THRESHOLD * 100,
        )
        for r in benchmark_results:
            status = "PASS" if r["passed"] else "FAIL"
            logger.info(
                "  [%s] %s: quality=%.2f practicality=%.2f composite=%.4f verdict=%s",
                status,
                r["id"],
                r["quality_score_10"],
                r["practicality_score_10"],
                r["composite"],
                r["verdict"],
            )

        assert pass_rate >= PASS_RATE_THRESHOLD, (
            f"Pass rate {passed}/{total} ({pass_rate:.0%}) is below "
            f"threshold {PASS_RATE_THRESHOLD:.0%}. "
            f"Failing prompts: {[r['id'] for r in benchmark_results if not r['passed']]}"
        )

    def test_no_zero_scores(self, benchmark_results: list[dict[str, Any]]) -> None:
        """No prompt should score exactly 0 on quality or practicality."""
        for r in benchmark_results:
            assert r["quality_score_10"] > 0, f"Prompt {r['id']} has zero quality score"
            assert r["practicality_score_10"] > 0, f"Prompt {r['id']} has zero practicality score"

    def test_average_composite_above_minimum(self, benchmark_results: list[dict[str, Any]]) -> None:
        """Average composite score should be meaningfully above the threshold."""
        composites = [r["composite"] for r in benchmark_results]
        avg = sum(composites) / len(composites) if composites else 0.0
        logger.info("Average composite score: %.4f", avg)
        assert avg >= 0.6, f"Average composite {avg:.4f} is too low (expected >= 0.6)"

    def test_practicality_scores_above_5(self, benchmark_results: list[dict[str, Any]]) -> None:
        """At least 80% of prompts should achieve practicality >= 5.0/10."""
        above_5 = sum(1 for r in benchmark_results if r["practicality_score_10"] >= 5.0)
        rate = above_5 / len(benchmark_results) if benchmark_results else 0.0
        assert rate >= 0.80, (
            f"Only {above_5}/{len(benchmark_results)} prompts have practicality >= 5.0. "
            f"Failing: {[r['id'] for r in benchmark_results if r['practicality_score_10'] < 5.0]}"
        )

    @pytest.mark.parametrize(
        "prompt_id",
        [
            "strategic",
            "security",
            "hiring",
            "legal",
            "performance",
            "product",
            "data",
            "ml",
            "culture",
            "crisis",
        ],
    )
    def test_individual_prompt_quality(
        self,
        prompt_id: str,
        benchmark_results: list[dict[str, Any]],
    ) -> None:
        """Each prompt should produce a non-trivial quality report."""
        result = next((r for r in benchmark_results if r["id"] == prompt_id), None)
        assert result is not None, f"No result for prompt {prompt_id}"

        # Quality should be above 5/10 for well-structured outputs.
        assert result["quality_score_10"] >= 5.0, (
            f"Prompt {prompt_id} quality {result['quality_score_10']:.2f}/10 is too low. "
            f"Defects: {result['defects']}"
        )
        # Composite above minimum.
        assert result["composite"] >= 0.4, (
            f"Prompt {prompt_id} composite {result['composite']:.4f} is below 0.4"
        )
