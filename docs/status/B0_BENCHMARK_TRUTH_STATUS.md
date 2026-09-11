# B0 Benchmark Truth Status

Last updated: 2026-09-01T13:38:29Z

This is the repo-tracked recurring `TW-02` publication surface for the fixed benchmark corpus.

## Corpus

- Corpus manifest: `docs/benchmarks/corpus.json`
- Corpus id: `tw-01-bounded-execution-v1`
- Revision: `7`
- Recorded on: `2026-08-19`
- Success contract: `mergeable_pr_or_merged_pr`
- Verified expected issues: `5`
- In-progress expected issues: `5`
- Coverage status: `complete`
- Coverage: `10`/`10` issues attempted

## Published Paths

- Corpus-scoped truth pointer: `docs/status/generated/benchmark_truth_artifacts/tw-01-bounded-execution-v1/latest.json`
- Corpus-scoped scorecard pointer: `docs/status/generated/benchmark_scorecards/tw-01-bounded-execution-v1/latest.json`
- Revision-scoped truth pointer: `docs/status/generated/benchmark_truth_artifacts/tw-01-bounded-execution-v1/rev-7/latest.json`
- Revision-scoped scorecard pointer: `docs/status/generated/benchmark_scorecards/tw-01-bounded-execution-v1/rev-7/latest.json`

## Truth Metrics

| Metric | Value |
| --- | --- |
| Verified truth success rate (primary) | 100.0% |
| Full-corpus truth success rate (legacy/context) | 50.0% |
| No-rescue truth success rate | 50.0% |
| Merged-only rate | 50.0% |

## In-Flight Graduation Metrics

| Metric | Value |
| --- | --- |
| In-progress expected issues | 5 |
| In-progress attempted issues | 5 |
| In-progress successful issues | 0 |
| In-progress graduation rate | 0.0% |
| Expected in-progress issue numbers | `#5749`, `#5751`, `#5753`, `#5754`, `#5755` |
| Live-open expected issue numbers | `#5749`, `#5751`, `#5753`, `#5754`, `#5755` |
| Live-closed expected issue numbers | none |

## Proxy Metrics

| Metric | Value |
| --- | --- |
| Proxy no-rescue success rate | 0.0% |
| Unique issues attempted | 10 |
| Unique issues succeeded | 0 |
| Unique issues failed | 5 |
| Unique issues neutral | 5 |
| Total ticks | 11 |

Proxy note: neutral issue outcomes are current-corpus rows that were neither fresh success nor failure, such as `issue_already_resolved`.

## Proxy Neutral Class Distribution

- `issue_already_resolved`: 5

## Failure Class Distribution

- `blocked_not_dispatch_bounded`: 5
- `rescue_worker_crash`: 1

## Rescue Counts By Type

- `rescue_worker_crash`: 1

## Previous Published Artifact

- Previous artifact path: `docs/status/generated/benchmark_scorecards/tw-01-bounded-execution-v1/rev-7/scorecard-20260819T151955Z.json`
- Previous generated_at: `2026-08-19T15:19:55Z`

## Deltas

- Merged-only rate (`merged_only_rate`): 0.0000
- No-rescue truth success rate (`no_rescue_truth_success_rate`): 0.0000
- Proxy no-rescue success rate (`proxy_no_rescue_success_rate`): -0.5000
- Full-corpus truth success rate (legacy/context) (`truth_success_rate`): 0.0000
- Unique issues attempted (`unique_issues_attempted`): 0.0000
