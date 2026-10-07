# Test Skip Marker Audit

**Generated**: 2026-09-21
**Total Skip Markers**: 93

---

## Summary by Category

| Category | Count | Percentage |
|----------|-------|------------|
| integration_dependency | 28 | 30.1% |
| missing_feature | 21 | 22.6% |
| uncategorized | 21 | 22.6% |
| optional_dependency | 9 | 9.7% |
| platform_specific | 9 | 9.7% |
| performance | 4 | 4.3% |
| known_bug | 1 | 1.1% |

## Summary by Marker Type

| Type | Count |
|------|-------|
| `pytest.skip` | 46 |
| `skipif` | 40 |
| `pytest.importorskip` | 5 |
| `skip` | 2 |

## High-Skip Files (Top 10)

| File | Skip Count |
|------|------------|
| `tests/integration/test_knowledge_visibility_sharing.py` | 6 |
| `tests/debate/test_voting_engine.py` | 5 |
| `tests/swarm/test_quorum_evidence.py` | 4 |
| `tests/plugins/test_plugin_sandbox.py` | 4 |
| `tests/debate/test_convergence_root.py` | 3 |
| `tests/inbox/test_inbox_receipt_convergence.py` | 2 |
| `tests/integration/test_postgres.py` | 2 |
| `tests/server/middleware/rate_limit/test_distributed_integration.py` | 2 |
| `tests/server/startup/test_validation.py` | 2 |
| `tests/triage/test_auto_handle_calibration.py` | 2 |

---

## Category Definitions

| Category | Description |
|----------|-------------|
| optional_dependency | Missing optional Python package |
| missing_feature | Feature not yet implemented |
| integration_dependency | Requires external service (Redis, Postgres) |
| platform_specific | OS-specific limitation |
| flaky_test | Test has intermittent failures |
| known_bug | Known issue being tracked |
| performance | Too slow or resource-intensive |
| uncategorized | Reason did not match any pattern |

---

## Remediation Guidelines

1. **optional_dependency**: Add to `[project.optional-dependencies.test]` in pyproject.toml
2. **missing_feature**: Create GitHub issue and link in skip reason
3. **integration_dependency**: Ensure CI runs integration tests with services
4. **flaky_test**: Fix root cause or add retry mechanism
5. **known_bug**: Link to GitHub issue in skip reason
6. **uncategorized**: Review and add appropriate category pattern

---

## Skip Count Baseline

Current baseline: **93** skips

CI will warn if skip count exceeds this baseline.
Update `tests/.skip_baseline` when intentionally adding skips.
