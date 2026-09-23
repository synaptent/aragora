# Test Skip Marker Audit

**Generated**: 2026-09-13
**Total Skip Markers**: 93

---

## Summary by Category

| Category | Count | Percentage |
|----------|-------|------------|
| integration_dependency | 29 | 31.2% |
| missing_feature | 22 | 23.7% |
| uncategorized | 20 | 21.5% |
| optional_dependency | 9 | 9.7% |
| platform_specific | 8 | 8.6% |
| performance | 4 | 4.3% |
| known_bug | 1 | 1.1% |

## Summary by Marker Type

| Type | Count |
|------|-------|
| `pytest.skip` | 45 |
| `skipif` | 41 |
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
| `tests/server/startup/test_validation.py` | 2 |
| `tests/server/middleware/rate_limit/test_distributed_integration.py` | 2 |
| `tests/verification/test_proofs_root.py` | 2 |
| `tests/ranking/test_calibration_engine.py` | 2 |
| `tests/gauntlet/api/test_export.py` | 2 |

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
