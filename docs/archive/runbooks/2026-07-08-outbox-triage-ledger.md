# 2026-07-08 Outbox Triage Ledger

Snapshot time: 2026-07-08T15:09:50Z

This ledger is a read-only classification of the 20 active files in
`.aragora/automation-outbox`. It does not move, edit, delete, publish, archive,
or release any outbox item, receipt, branch, owner, worktree, issue, or PR.

## Source Evidence

- `python3 scripts/publisher_freshness_check.py --json`: publisher ready; cache age `17.3m`; outbox/cache `20/20`.
- `python3 scripts/fleet_sentinel.py --json --no-ledger`: only breach is `outbox_depth`; depth `20`; oldest item `open-pr-codex-read-steering-thread-receipts-improver-20260614-e946d060.json`; max age `7.0d`; oldest age `24.4d`.
- `python3 scripts/publish_automation_handoffs.py --dry-run --json`: `0` eligible publish decisions; `20` skipped outbox files; reasons: `expired=19`, `missing_required_contract=1`.
- `python3 scripts/classify_handoff_state.py --json`: counts `blocked_by_owner=17`, `blocked_by_human=2`, `unknown=1`.
- `python3 scripts/reconcile_automation_outbox.py --dry-run --json`: `19` kept as still protecting active work; `1` skipped as unparseable/missing required handoff contract.

## Disposition Counts

| Disposition | Count |
| --- | ---: |
| `PUBLISH-READY` | 0 |
| `EXPIRED-ARCHIVE` | 18 |
| `ORPHANED-TARGET` | 0 |
| `BLOCKED-ON-PARKED-PR` | 0 |
| `NEEDS-REPAIR` | 2 |
| **Total** | **20** |

`EXPIRED-ARCHIVE` means the item is skipped by publisher expiration logic and
needs a terminal preservation/owner-release decision before archival. It does
not mean the item is safe to delete.

## Ledger

| # | File | Observed age | Type | Disposition | Target state | Blocking cause | Safe next action | Owner session | Pending steering | Expires |
| ---: | --- | ---: | --- | --- | --- | --- | --- | --- | ---: | --- |
| 1 | `open-pr-codex-benchmark-debate-cli-import-improver-20260615-5314aa90.json` | 16.2d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/benchmark-debate-cli-import-improver-20260615` at `e0d83e696709`; no open PR | Branch has unique commits not on main, no open PR; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q650-benchmark-debate-current-main-refresh-20260622T1008Z` | 1 | `2026-06-29T10:10:45Z` |
| 2 | `open-pr-codex-cache-status-same-origin-state-root-improver-20260614-aff5f824.json` | 23.1d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/cache-status-same-origin-state-root-improver-20260614` at `2c22d1879b3b`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q569-cache-status-refresh-r4-20260615T1207Z` | 1 | `2026-06-29T12:13:00Z` |
| 3 | `open-pr-codex-collect-evidence-rest-fallback-20260623-d9d49c24.json` | 15.4d | `open_or_update_pr` | `NEEDS-REPAIR` | Branch `codex/collect-evidence-rest-fallback-20260623`; no open PR; remote `69220c1bc460` != desired `d9d49c24f214` | Expired plus stale desired-head mismatch under human gate | Re-ground branch/head under human-owner settlement; then publish or terminally archive with proof. | `human-operator-pr8570-collect-evidence-rest-fallback-20260624T033357Z` | 0 | `2026-06-30T04:56:42Z` |
| 4 | `open-pr-codex-essay-synthesis-cli-help-improver-20260615-5dc1f877.json` | 19.6d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/essay-synthesis-cli-help-improver-20260615` at `cfdbf4f4711c`; no open PR | Branch has unique commits not on main, no open PR; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q617-essay-synthesis-current-main-refresh-20260619T0016Z` | 1 | `2026-06-22T21:08:58Z` |
| 5 | `open-pr-codex-github-health-cli-no-app-auth-primary-20260615-ef6dd7c6.json` | 15.8d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/github-health-cli-no-app-auth-primary-20260615` at `949baaa0444b`; no open PR | Branch has unique commits not on main, no open PR; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q666-github-health-current-main-refresh-20260622T201054Z` | 1 | `2026-06-23T20:13:05Z` |
| 6 | `open-pr-codex-identify-lane-owner-stale-proof-primary-20260614-a6c938f4.json` | 24.4d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/identify-lane-owner-stale-proof-primary-20260614` at `a6c938f422e6`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q627-identify-lane-owner-current-main-refresh-20260621T1916Z` | 1 | `2026-06-28T06:29:06Z` |
| 7 | `open-pr-codex-odr-consistency-guard-primary-20260615-8381fed4.json` | 20.5d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/odr-consistency-guard-primary-20260615` at `c44bc5961656`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q580-odr-consistency-current-refresh-20260618T030454Z` | 1 | `2026-06-22T21:20:57Z` |
| 8 | `open-pr-codex-publisher-inferable-outbox-contract-improver-20260614-fe99d16a.json` | 24.0d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/publisher-inferable-outbox-contract-improver-20260614` at `fe99d16abafc`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-3-2-Q542-publisher-inferable-outbox-contract-20260614T1533Z` | 1 | `2026-06-28T15:42:00Z` |
| 9 | `open-pr-codex-publisher-issue-cap-default-improver-20260614-71e55ace.json` | 24.2d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/publisher-issue-cap-default-improver-20260614` at `71e55ace1ace`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-3-2-Q537-publisher-issue-cap-default-20260614T1020Z` | 1 | `2026-06-28T10:55:57Z` |
| 10 | `open-pr-codex-publisher-related-lookup-budget-repair-20260615-117d6507.json` | 16.8d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/publisher-related-lookup-budget-repair-20260615` at `46de04f2f73d`; no open PR | Branch has unique commits not on main, no open PR; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q627-publisher-related-current-main-refresh-20260621T1917Z` | 1 | `2026-06-29T08:32:08Z` |
| 11 | `open-pr-codex-rbac-openapi-coverage-primary-20260615-dd112baf.json` | 22.0d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | PR #8652 draft at exact head `3628f5c14e95` | Branch has open PR #8652 | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `codex-desktop-20260704T064701Z` | 1 | `2026-06-22T16:13:20Z` |
| 12 | `open-pr-codex-read-steering-thread-receipts-improver-20260614-e946d060.json` | 24.4d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/read-steering-thread-receipts-improver-20260614` at `e946d0604745`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `aragora-owner-gate-resolver-Q530-read-steering-thread-receipts-20260624T035756Z` | 2 | `2026-06-28T05:21:43Z` |
| 13 | `open-pr-codex-receipt-terminal-statuses-primary-20260614-29f893c8.json` | 16.7d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/receipt-terminal-statuses-primary-20260614` at `b4eabebaa2e7`; no open PR | Branch has unique commits not on main, no open PR; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q628-receipt-terminal-current-main-refresh-20260621T2207Z` | 1 | `2026-06-28T12:57:32Z` |
| 14 | `open-pr-codex-reconcile-issue-state-rest-fallback-primary-20260614-879ea1a2.json` | 24.4d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/reconcile-issue-state-rest-fallback-primary-20260614` at `157c3f2e345d`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q531-reconcile-issue-rest-fallback-pr-open-20260614T0516Z` | 1 | `2026-06-28T04:30:23Z` |
| 15 | `open-pr-codex-reconcile-merged-pr-commit-proof-20260614-9b7888d7.json` | 24.2d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/reconcile-merged-pr-commit-proof-20260614` at `9b7888d7a4bc`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q536-reconcile-merged-pr-commit-proof-20260614T1015Z` | 1 | `2026-06-28T10:29:34Z` |
| 16 | `open-pr-codex-reconcile-shared-state-default-improver-20260614-a45548e1.json` | 24.1d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/reconcile-shared-state-default-improver-20260614` at `8964741b0f65`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q537-reconcile-shared-state-default-refresh-20260614T1118Z` | 1 | `2026-06-28T07:31:39Z` |
| 17 | `open-pr-codex-replay-cli-import-improver-20260615-7d319f82.json` | 16.4d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/replay-cli-import-improver-20260615` at `1e95eab031b6`; no open PR | Branch has unique commits not on main, no open PR; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-Q642-replay-cli-current-main-refresh-20260622T051043Z` | 1 | `2026-06-29T05:14:39Z` |
| 18 | `open-pr-codex-report-code-quality-pipe-improver-20260614-faee82e2.json` | 23.9d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/report-code-quality-pipe-improver-20260614` at `faee82e2c77c`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-3-2-Q544-report-code-quality-pipe-20260614T1700Z` | 1 | `2026-06-28T17:03:43Z` |
| 19 | `open-pr-codex-report-code-quality-summary-only-improver-20260614-de44688d.json` | 23.5d | `open_or_update_pr` | `EXPIRED-ARCHIVE` | Branch `codex/report-code-quality-summary-only-improver-20260614` at `de44688d2de5`; no open PR | Desired head preserved by exact remote branch; local ref unavailable; actively protecting | Archive only after explicit owner release or terminal preservation proof; otherwise keep protected. | `engineering-autopilot-3-2-Q554-report-code-quality-summary-only-20260615T0155Z` | 1 | `2026-06-29T01:56:25Z` |
| 20 | `queue-drain-park-reconciliation-20260708T121926Z.json` | 0.1d | `missing` | `NEEDS-REPAIR` | Queue-drain reconciliation payload; no branch target | Missing required handoff contract; publisher skips it | Move to a purpose-built report/receipt path or add schema support; do not archive as an open-PR handoff. | none | 0 | none |

## Recommended Next Unit

The next executor should not mutate the outbox from this ledger alone. The
highest-leverage follow-up is a narrow `NEEDS-REPAIR` unit for
`queue-drain-park-reconciliation-20260708T121926Z.json`: move this non-handoff
payload to a purpose-built conductor report or add a supported schema so future
publisher/reconcile passes do not classify it as an outbox contract failure.

After that, use the rubric to handle the `EXPIRED-ARCHIVE` set in small batches
only after owner release or terminal preservation proof is available.
