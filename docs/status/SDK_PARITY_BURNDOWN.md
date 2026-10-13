# SDK Parity Burndown

Last updated: 2026-08-18

This document describes the committed-ceiling budget contract that
`scripts/check_sdk_parity.py` enforces against
`scripts/baselines/check_sdk_parity_budget.json`. It replaces the retired
weekly-decay contract this page described until March 2026: the budget no
longer shrinks on a clock, and the wall-clock date can never change the
gate's pass/fail result.

## Committed-ceiling contract

The budget file carries schema `check-sdk-parity-committed-budget-v1` and
exactly two enforced ceilings:

| Key | Committed ceiling |
|-----|-------------------|
| `committed_max_missing_from_both_sdks` | `0` |
| `committed_max_stale_python_sdk_paths` | `36` |

- Strict mode (`--strict`) exits `1` when measured debt exceeds either
  committed ceiling; debt at or under both ceilings passes.
- Strict mode fails closed with exit `2` when the budget file is missing.
  A legacy clock-derived budget (cadence keys without committed ceilings)
  or a malformed budget fails closed with exit `2` in both strict and
  non-strict runs.
- `--today` is accepted but advisory-only: it shapes the non-enforcing
  paydown target derived from the optional `advisory_cadence` block (the
  retired cadence is preserved there purely as a reference), never the
  exit status.
- The `schema` field is an informational label. The loader intentionally
  classifies the file by its keys (committed ceilings present, or retired
  cadence keys only) rather than validating the label, so a future schema
  revision can land without a lockstep checker update (forward-compat
  behavior, not an oversight).
- In `--json` mode stdout is always exactly one parseable JSON document
  (the report, including the `budget` block); all human diagnostics go to
  stderr.

## Banking progress with `--tighten`

Ceilings never decay on their own, and the checker never raises them.
After a real paydown lands, someone must bank it:

```bash
python3 scripts/check_sdk_parity.py --tighten \
  --budget scripts/baselines/check_sdk_parity_budget.json
```

- `--tighten` measures current debt and rewrites the ceilings down to the
  measured values. It is idempotent: when the file is already tight it
  reports so and performs no write.
- It refuses to raise a ceiling: if measured debt exceeds a committed
  ceiling it exits `1` and leaves the budget file byte-identical. Raising
  a ceiling is a human-only decision made by hand-editing the budget file
  in a reviewed change; the tool will never do it.
- It bootstraps a missing or legacy budget file from measured debt
  (preserving a legacy cadence as the non-enforcing `advisory_cadence`),
  and exits `2` without writing when route extraction is unavailable or
  the budget path is unwritable.
- When current debt sits below the committed ceilings, the checker prints
  an advisory reminder suggesting `--tighten` so the slack cannot be
  silently consumed by a later regression. The advisory never affects the
  exit status.

## No automatic decay (operational consequences)

Under the retired weekly-decay contract the budget shrank every week, so
the gate could turn red — or green again — with zero code change. The
committed-ceiling contract removes both directions:

- The gate turns red only when debt actually grows past a committed
  ceiling. A red gate can never be fixed by waiting; someone must either
  pay the debt down or (human-only) raise the ceiling in a reviewed edit.
- Paydown does not tighten anything by itself. After real paydown someone
  must run `--tighten`, or the freed headroom remains silently
  consumable.

## Current state (2026-08-18)

- Missing from both SDKs: `0` (ceiling `0`)
- Stale Python SDK paths: `36` (ceiling `36`)
- Gate command and result:
  - `python3 scripts/check_sdk_parity.py --strict --baseline scripts/baselines/check_sdk_parity.json --budget scripts/baselines/check_sdk_parity_budget.json` -> pass
  - `Budget status (committed ceilings): missing_from_both 0/0 | stale_python 36/36`

## Paydown loop

1. Report: `python3 scripts/check_sdk_parity.py --json > /tmp/sdk_parity.json`
2. Gate: `python3 scripts/check_sdk_parity.py --strict --baseline scripts/baselines/check_sdk_parity.json --budget scripts/baselines/check_sdk_parity_budget.json`
3. Pay down stale paths or missing routes for real.
4. Bank it: run `--tighten` and commit the lowered ceilings in the same
   change, so the ratchet holds the new floor.
