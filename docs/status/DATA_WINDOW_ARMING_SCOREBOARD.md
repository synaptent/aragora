# Data-Window Arming Scoreboard

**Owner:** founder-review
**Last updated:** 2026-07-11T06:37:48Z
**Source issue:** [#8859](https://github.com/synaptent/aragora/issues/8859)
**Status:** report-only snapshot; this document cannot arm a mechanism

This scoreboard replaces the old Jul 29 calendar review with evidence windows.
It answers whether each window has enough data to request a separate arming
decision. It does not grant that decision.

## Decision Contract

- **ARM (data only)** means the stated observation threshold is met. Any code,
  Tier 4, workflow, merge, protection, or operator action still requires its
  normal exact-head authorization.
- **HOLD** means the threshold is unmet, the evidence source is incomplete, or
  the mechanism is intentionally stopped.
- Missing, stale, or transport-limited evidence fails closed to **HOLD**.
- Refreshing this file is report-only. It must not create `boss-ready` work,
  rerun a workflow, modify the merge queue, or change a halt marker.

## Current Window

| Window | Observation threshold | Current observation | Decision | Owner | Last checked |
|---|---|---|---|---|---|
| `adjudicator.step_2` | At least 3 linked review-stall specimens | 5 specimens are named in the [#8811 operator record](https://github.com/synaptent/aragora/pull/8811#issuecomment-4879890045): verbatim-repeat (#8800), two out-of-scope/cross-family cases (#8802), diff-blind grounding (#8824), and the clean-pass boundary (#8808). The implementation follow-up [#8879](https://github.com/synaptent/aragora/pull/8879) remains open and is not settled here. | **ARM (data only)** | review-governance | 2026-07-11T06:37:48Z |
| `lease.strict` | All five fleets carry the preflight and the unreachable-store warning rate is approximately zero for 3-5 quiet days | The v0 rule and strict transition are documented, but there is no canonical fleet-wide coverage or warning-rate ledger. Selective log searches cannot prove a quiet window. | **HOLD** | fleet-coordination | 2026-07-11T06:37:48Z |
| `executor.kill_switch_read` | Roughly 1 week of continuous armed-executor history before reading kill-switch metrics | Live operator state contains one merge-executor receipt dated Jul 4. The merge executor is currently stopped by an active `main_red` halt, so this is not a continuous armed week. | **HOLD** | operator | 2026-07-11T06:37:48Z |
| `issue_close_discipline` | Record trailing-week opened and closed issue counts; do not claim healthy drain while inflow exceeds closure | GitHub date-granularity queries for Jul 4-11 report 101 issues opened and 29 closed: net **+72 open**. Search counts are operational indicators, not an audited issue ledger. | **HOLD** | queue-steward | 2026-07-11T06:37:48Z |
| `cancelled_run_self_heal` | Current-head cancelled runs are observable and the one-rerun self-heal remains bounded; automatic wiring waits for explicit authorization or root-cause removal | A redirected dry run over the latest 300 runs found 0 cancelled candidates and 0 eligible reruns. The external cancellation actor identified by #8849 is still unresolved, so automatic arming is not inferred from a clean sample. | **HOLD** | CI-resilience | 2026-07-11T06:37:48Z |

## Evidence And Refresh Procedure

### Adjudicator step 2

The public record on #8811 is the countable source for the five named stall
specimens. The observation threshold is met, but the open #8879 implementation
and any later Tier 4 action remain separate from this report.

Refresh:

```bash
gh api repos/synaptent/aragora/issues/8811/comments \
  --jq '.[] | select(.body | contains("five stall specimens")) | {created_at, body}'
gh api repos/synaptent/aragora/pulls/8879 \
  --jq '{state, draft, head: .head.sha, mergeable_state}'
```

### Lease strictness

[`docs/coordination/LEASE_RULE.md`](../coordination/LEASE_RULE.md) defines the
v1 transition as all five fleets carrying the preflight and an approximately
zero warning rate. No committed source currently aggregates both facts. Until
one does, a lack of warnings in a partial log set is not evidence of readiness.

Partial diagnostic only:

```bash
rg -n 'WARNING: lease store unreachable' \
  .aragora/conductor_cycles .aragora/goal_cycles .aragora/operator-context
```

Repair/report policy: add a canonical fleet-coverage and warning-rate report;
do not flip callers to `--strict` from this scoreboard.

### Executor history and kill-switch read

The evidence window requires an armed history, not merely seven elapsed
calendar days. A halt or an executor outage breaks continuity.

Refresh:

```bash
find .aragora/merge_executor/receipts -maxdepth 1 -name '*.json' -print
test ! -e .aragora/merge_executor.halt
python3 scripts/throughput_ledger.py show
```

Repair/report policy: remain **HOLD** while the halt exists or the receipt
history is too sparse to support latency, revert-rate, and self-repair reads.
Human re-arm remains a separate action.

### Issue-close discipline

The current snapshot uses GitHub search date granularity, so the endpoints are
calendar dates rather than an exact 168-hour interval:

```bash
gh api --method GET search/issues \
  -f q='repo:synaptent/aragora is:issue created:2026-07-04..2026-07-11' \
  --jq .total_count
gh api --method GET search/issues \
  -f q='repo:synaptent/aragora is:issue closed:2026-07-04..2026-07-11' \
  --jq .total_count
```

Repair/report policy: record the next window with fresh dates and retain the
search-count caveat. Do not close issues merely to improve the delta; every
closure still needs its normal disposition rationale.

### Cancelled-run concurrency

The Jul 11 observation redirected every helper output to `/tmp`, used dry-run
mode, and did not rerun any workflow:

```bash
python3 scripts/retrigger_cancelled_pr_runs.py \
  --repo synaptent/aragora \
  --max-runs 300 \
  --ttl-minutes 10080 \
  --max-attempts 2 \
  --marker-file /tmp/aragora-8859-retrigger/marker.json \
  --receipt-dir /tmp/aragora-8859-retrigger/receipts \
  --operator-packet-dir /tmp/aragora-8859-retrigger/packets
```

Observed result: `scanned=300`, `candidates=0`, `eligible=0`, `applied=0`.
The self-heal remains the bounded manual pattern from
[`PR_RUN_CANCELLATION_DIAGNOSIS.md`](../governance/PR_RUN_CANCELLATION_DIAGNOSIS.md):
current-head check, short TTL, one rerun maximum, and a receipt. Automatic
wiring or external-canceller changes require separate authorization.

## Next Review

Refresh a row when its canonical evidence changes, not on a calendar ritual.
The operator should review only rows that change from **HOLD** to **ARM (data
only)**. A changed row is an input to the normal decision process, never a
substitute for it.
