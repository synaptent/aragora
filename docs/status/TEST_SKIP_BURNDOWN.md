# Test Skip Burndown

Last updated: 2026-08-21

This file tracks intentional test-skip debt reduction so `tests/.skip_baseline`
stays actionable and does not hide regressions.

## Current Baseline

- Total skip markers: `86`
- Source command: `python scripts/audit_test_skips.py --json`
- CI baseline file: `tests/.skip_baseline` = `86`
- Marker types:
  - `pytest.skip`: `40`
  - `skipif`: `39`
  - `pytest.importorskip`: `5`
  - `skip`: `2`

> Provenance: re-measured 2026-08-19 via `python3 scripts/audit_test_skips.py --json` on main `6955ab420e` (baseline settled at 86 by PR #9795).

### Category Snapshot

| Category | Count | Weekly target |
|---|---:|---:|
| `integration_dependency` | 29 | hold |
| `uncategorized` | 20 | -2 (until categorized or removed) |
| `missing_feature` | 17 | -2 |
| `optional_dependency` | 9 | -1 |
| `platform_specific` | 6 | hold |
| `performance` | 4 | hold |
| `known_bug` | 1 | 0 (hold until bug fixed) |

> Provenance: `uncategorized` weekly target (-2/week until categorized or removed) assigned by the operator (questionnaire 2026-08-19, question 3).

> Provenance: `known_bug` weekly target (0/week, hold until the bug is fixed) assigned by the operator (questionnaire 2026-08-19, question 3).

## Highest-Skip Files

| File | Count |
|---|---:|
| `tests/integration/test_knowledge_visibility_sharing.py` | 6 |
| `tests/swarm/test_quorum_evidence.py` | 4 |
| `tests/plugins/test_plugin_sandbox.py` | 4 |
| `tests/debate/test_voting_engine.py` | 3 |
| `tests/ranking/test_calibration_engine.py` | 2 |

## Execution Rules

1. Keep `tests/.skip_baseline` synchronized with audited reality after intentional skip changes.
2. Reduce `uncategorized` first, then `missing_feature`, then `optional_dependency`.
3. Any file at `>=5` skips requires an owner and explicit cleanup plan in sprint notes.
4. Do not raise baseline without documenting root cause and expected payoff.

## Weekly Loop

1. Run audit:
   - `python scripts/audit_test_skips.py --json > /tmp/skip-report.json`
2. Review totals and category drift:
   - `jq '.total, .by_category, .high_skip_files[:10]' /tmp/skip-report.json`
3. Update this file and `tests/.skip_baseline` if counts changed intentionally.
4. Re-validate local gate:
   - `python scripts/audit_test_skips.py --count-only`
