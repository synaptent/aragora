# H1-04 Phase-5 Autonomy Ledger + Self-Heal — Contract Satisfaction

> **Roadmap:** [docs/plans/2026-04-18-3-horizon-roadmap.md](../plans/2026-04-18-3-horizon-roadmap.md) H1-04
> **Issue:** [#6230](https://github.com/synaptent/aragora/issues/6230)
> **Parent epic:** [#6226](https://github.com/synaptent/aragora/issues/6226)
> **Status:** IN PLACE — ShiftLedger module, FailureThresholds, SessionCircuitBreaker, CLI + FastAPI surfaces satisfy acceptance criteria
> **Last verified:** 2026-04-18

This document pins the contract between the H1-04 deliverable and the existing Autonomy Ledger + Self-Heal implementation, so future reviewers can confirm the deliverable is satisfied without re-deriving the mapping.

## Acceptance criteria vs satisfaction

| Acceptance criterion (from #6230) | Satisfying surface | Evidence |
|---|---|---|
| canonical ledger of probes / contracts / receipts / outcomes | [`aragora/evaluation/shift_ledger.py`](../../aragora/evaluation/shift_ledger.py) `ShiftLedger` class + entry types (`shift_start`, `shift_stop`, `cycle_tick`, `service_restart`, `auth_failure`, `publication_failure`, `rate_limit`, `permission_mismatch`, `runtime_failure`, `service_failure`) | 385-line JSONL append-only ledger at `.aragora/proof_first_shift/shift_ledger.jsonl` |
| automatic quarantine for stale auth | `shift_ledger.py` `FAILURE_THRESHOLDS["auth_failure"] = 2`; `SessionCircuitBreaker` pins session on 401/403 | Lines 22-29 in shift_ledger.py; `aragora/routing/session_circuit_breaker.py` |
| automatic quarantine for permission mismatch | `FAILURE_THRESHOLDS["permission_mismatch"] = 2` | Line 26 in shift_ledger.py; `permission_mismatch` entry counting in `should_stop_shift()` |
| automatic quarantine for rate limits | `FAILURE_THRESHOLDS["rate_limit"] = 2`; OpenRouter fallback on 429 | Line 25 in shift_ledger.py; `aragora/agents/fallback.py` |
| automatic quarantine for publication failures | `FAILURE_THRESHOLDS["publication_failure"] = 2` | Line 24 in shift_ledger.py |
| replace shell-heuristic health checks with ledger-backed truth | [`aragora/cli/commands/shift_status.py`](../../aragora/cli/commands/shift_status.py), [`aragora/cli/commands/swarm_status.py`](../../aragora/cli/commands/swarm_status.py), [`aragora/server/fastapi/routes/swarm_status.py`](../../aragora/server/fastapi/routes/swarm_status.py), [`aragora/swarm/live_shift_status.py`](../../aragora/swarm/live_shift_status.py), [`aragora/swarm/reporter.py`](../../aragora/swarm/reporter.py) | 5 modules consume the ledger directly for status |
| dashboards read from ledger | VIAH metric at [`aragora/metrics/viah.py`](../../aragora/metrics/viah.py) reads ShiftLedger entries | `viah.py` imports `ShiftLedger` |
| ledger persists across process restarts | JSONL append-only format + default path `.aragora/proof_first_shift/shift_ledger.jsonl` | File-backed persistence; restart-safe by construction |
| self-heal automatically quarantines each of the 4 failure classes | `should_stop_shift()` + `recent_summary()` methods emit quarantine decisions per failure class threshold | Lines 229-238, 335-363 in shift_ledger.py |
| no conflicting status between ledger, health API, and operator view | All surfaces consume the same `ShiftLedger.read_entries()` API | Single source of truth contract |

## Entry types and their self-heal semantics

| Entry type | Threshold | Self-heal action |
|---|---|---|
| `auth_failure` | 2 | Stop shift, rotate provider, invoke SessionCircuitBreaker |
| `publication_failure` | 2 | Stop shift, quarantine pending PRs, escalate |
| `rate_limit` | 2 | Stop shift, fall back to OpenRouter, cool-down |
| `permission_mismatch` | 2 | Stop shift, surface mismatched scope, operator review |
| `runtime_failure` | 1 | Immediate stop, service restart eligible |
| `service_failure` | 1 | Immediate stop, quarantine service, operator review |

## Green-shift contract

`GREEN_SHIFT_REQUIRED_HOURS = 12.0` at line 21 defines the minimum continuous window required for a shift to count as green. This feeds the H2-02 soak acceptance criterion: 12h multi-host soak passes require ≥1 continuous green shift per host with no `FAILURE_THRESHOLDS` breach.

## How H1-04 composes with the rest of H1

- **H1-01 rev-4 corpus** feeds task inputs → H1-03 sanitizer gates admission → H1-04 ledger records outcomes → H1-02 scorecard renders daily truth
- Sanitation outcomes (REWRITTEN / DROPPED / QUARANTINED) are dispatched as ledger entries so the feedback loop closes on the same substrate
- Session circuit-breaker auth-state pinning (H2-10) builds on the `auth_failure` ledger entry type

## What H1-04 does not cover

- Multi-host soak publication (H2-02 scope, though green-shift contract is the foundation)
- RunLedger across orchestrator/debate/planning (H2-03 scope — broader than swarm)
- ERC-8004 attestation anchoring of ledger entries (H2-05 shadow mode)
- Chief-of-Staff portfolio-level ledger aggregation (H3 scope)

## Regression test surface

- [`tests/swarm/test_shift_ledger.py`](../../tests/swarm/test_shift_ledger.py) — ShiftLedger unit tests
- [`tests/swarm/test_shift_ledger_integration.py`](../../tests/swarm/test_shift_ledger_integration.py) — integration with boss loop
- [`tests/routing/test_session_circuit_breaker.py`](../../tests/routing/test_session_circuit_breaker.py) — SessionCircuitBreaker
- [`tests/agents/test_session_circuit_breaker_integration.py`](../../tests/agents/test_session_circuit_breaker_integration.py) — auth-state pinning integration
- [`tests/agents/test_fallback.py`](../../tests/agents/test_fallback.py) — OpenRouter fallback on 429

Verified 2026-04-18: `pytest tests/swarm/test_shift_ledger*.py -q` → **16 passed in 1.22s**.

## Closing contract

`H1-04` is satisfied by the in-place implementation above. Issue [#6230](https://github.com/synaptent/aragora/issues/6230) can be closed with this document as the receipt. The epic [#6226](https://github.com/synaptent/aragora/issues/6226) H1-04 checkbox may be marked complete.
