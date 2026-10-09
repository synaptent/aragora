# SDK Cross-Parity Debt Plan (2026-02-25)

## Scope

This plan tracks reduction of *existing* Python-only and TypeScript-only route
imbalances reported by strict cross-SDK parity checks.

Reference command:

```bash
python scripts/check_cross_sdk_parity.py --strict --baseline scripts/baselines/cross_sdk_parity.json
```

Current baseline snapshot:
- Python-only: `22`
- TypeScript-only: `232`
- New regressions allowed: `0`

## Baseline Buckets

Top Python-only buckets:
- `/api/workspaces/{param}`: 3
- `/api/backups/schedules`: 2
- `/api/decisions/{param}`: 2
- `/api/services/{param}`: 2

Top TypeScript-only buckets:
- `/api/debates/{param}`: 41
- `/api/codebase/{param}`: 29
- `/api/tournaments/{param}`: 13
- `/api/webhooks/{param}`: 10

## Execution Schedule

### Wave 1 (2026-02-26 to 2026-03-04)

Owner: SDK Platform

Targets:
- Reduce Python-only from `22` to `<= 15`
- Reduce TypeScript-only from `232` to `<= 200`

Focus:
- Python: workspaces/backups/decisions/services
- TypeScript: debates/codebase

Acceptance:
- Strict cross-SDK parity remains green (no regressions).
- Net reduction reflected in `scripts/baselines/cross_sdk_parity.json`.

### Wave 2 (2026-03-05 to 2026-03-12)

Owner: API + SDK Joint

Targets:
- Reduce Python-only to `<= 10`
- Reduce TypeScript-only to `<= 160`

Focus:
- TypeScript: tournaments/webhooks/admin/connectors
- Python: inbox/marketplace/matches

Acceptance:
- No newly introduced parity regressions.
- Added SDK namespace tests for touched areas.

### Wave 3 (2026-03-13 to 2026-03-20)

Owner: API + SDK Joint

Targets:
- Reduce Python-only to `<= 5`
- Reduce TypeScript-only to `<= 120`

Focus:
- Long-tail endpoint buckets and hard-to-model paths.

Acceptance:
- Updated baseline committed with documented remaining exceptions.
- Release gate remains strict and passing.

## Delivery Rules

1. Every parity PR must reduce at least one bucket or unblock a known bottleneck.
2. No PR may add new cross-SDK regressions.
3. PR descriptions must include before/after counts from `check_cross_sdk_parity.py --json`.
