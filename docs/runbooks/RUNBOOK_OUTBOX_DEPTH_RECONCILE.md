# Outbox Depth Reconcile Runbook

This runbook records the bounded queue-health disposition for the live
`outbox_depth` sentinel breach observed on 2026-07-08. It is intentionally
read-only: it does not authorize archive, receipt, owner-lane, PR, or worktree
mutation.

## Original Live Snapshot

- Repository: checked-out Aragora repository root
- Root head: `32e692ed2162cea7abf36ea83c1843d30d684007`
- Publisher: ready, outbox/cache `20/20`
- Fleet sentinel: one breach, `outbox_depth`
- Active outbox count: 20
- Terminal receipt count: 1196
- Oldest item:
  `open-pr-codex-read-steering-thread-receipts-improver-20260614-e946d060.json`
- GitHub status cache: App auth/API ready; heavy GraphQL detail degraded with
  HTTP 504, but lightweight queue cache reports open PR cap not reached
  (`27/120`)
- Disk free: healthy, about 337 GiB
- Boss heartbeat: healthy, about 30h old

## Current Validation Note

Fresh validation on 2026-07-11 at
`1605f175b1fe709997d1b96bf056f3599cd82077` kept the no-archive conclusion,
but the probe surface no longer exactly matches the original snapshot:

- `publisher_freshness_check.py --json`: degraded because the launchd service
  is absent and the GitHub status cache is 6.4 hours stale; the outbox/cache
  counts still agree at `20/20`.
- `fleet_sentinel.py --json --no-ledger`: one breach, `outbox_depth`;
  GitHub auth and API health are healthy. Three checks remain blind or unknown:
  legacy lane-ledger parsing, stale-terminal-owner GraphQL reads, and trail
  reconciliation.
- `reconcile_automation_outbox.py --dry-run --json --summary-only`:
  `archived=0`, `outbox_count=20`, `still_protecting_active_work=8`,
  `blocked_missing_branch_open_pr_unknown=11`, `skipped_unparseable=1`.
- `classify_handoff_state.py --json --summary-only`:
  `blocked_by_owner=17`, `blocked_by_human=2`, `unknown=1`. Per-item GitHub
  reads are healthy, while queue-cap classification is degraded because the
  cached count is expired and the heavy GraphQL refresh returned HTTP 504.

Treat the counts in the original snapshot as a historical observation, not as
current exact counts. The stable operational fact is that a dry-run still finds
no archive-ready item, so this runbook remains read-only and does not authorize
`--apply`.

## Commands

All GitHub reads used the GitHub App token.

```bash
git status --short --branch --untracked-files=all
REMOTE_MAIN=$(git ls-remote --exit-code origin refs/heads/main | cut -f1)
test "$(git rev-parse HEAD)" = "$REMOTE_MAIN"
${PY:-python3} scripts/publisher_freshness_check.py --json
${PY:-python3} scripts/fleet_sentinel.py --json --no-ledger
env GH_TOKEN="$(${PY:-python3} scripts/gh_app_env.py --print-token --quiet)" \
  ARAGORA_GITHUB_AUTH_SOURCE=github_app_installation \
  ${PY:-python3} scripts/reconcile_automation_outbox.py --dry-run --json
env GH_TOKEN="$(${PY:-python3} scripts/gh_app_env.py --print-token --quiet)" \
  ARAGORA_GITHUB_AUTH_SOURCE=github_app_installation \
  ${PY:-python3} scripts/classify_handoff_state.py --json
```

## Result

The original reconciler snapshot did not find any safe archive action:

- `still_protecting_active_work`: 19
- `skipped_unparseable`: 1
- `archived`: 0

The current dry-run also finds no safe archive action, but classifies the
protected set differently under degraded GitHub/open-PR lookups:

- `still_protecting_active_work`: 8
- `blocked_missing_branch_open_pr_unknown`: 11
- `skipped_unparseable`: 1
- `archived`: 0

The classifier reported:

- `blocked_by_owner`: 17
- `blocked_by_human`: 2
- `unknown`: 1

Therefore the correct conductor action is not to run `--apply`. The current
breach is real queue pressure, but every branch-shaped item is explicitly
protected by owner, human, exact-remote-branch, unique-work, or exact-open-PR
evidence.

## Disposition Table

| Outbox file | Reconcile decision | Classifier state | Next bounded action |
| --- | --- | --- | --- |
| `open-pr-codex-benchmark-debate-cli-import-improver-20260615-5314aa90.json` | Keep: branch has unique commits not on main, no open PR | `blocked_by_owner` | Owner handoff or supported publication path must represent the unique branch work before archive. |
| `open-pr-codex-cache-status-same-origin-state-root-improver-20260614-aff5f824.json` | Keep: desired head preserved by exact remote branch | `blocked_by_owner` | Consume owner release, completion, or supersession before mutation. |
| `open-pr-codex-collect-evidence-rest-fallback-20260623-d9d49c24.json` | Keep: branch has unique commits not on main, no open PR | `blocked_by_human` | Human gate must provide explicit disposition before non-owner movement. |
| `open-pr-codex-essay-synthesis-cli-help-improver-20260615-5dc1f877.json` | Keep: branch has unique commits not on main, no open PR | `blocked_by_owner` | Owner handoff or supported publication path must represent the unique branch work before archive. |
| `open-pr-codex-github-health-cli-no-app-auth-primary-20260615-ef6dd7c6.json` | Keep: branch has unique commits not on main, no open PR | `blocked_by_owner` | Owner handoff or supported publication path must represent the unique branch work before archive. |
| `open-pr-codex-identify-lane-owner-stale-proof-primary-20260614-a6c938f4.json` | Keep: desired head preserved by exact remote branch | `blocked_by_owner` | Consume owner release, completion, or supersession before mutation. |
| `open-pr-codex-odr-consistency-guard-primary-20260615-8381fed4.json` | Keep: desired head preserved by exact remote branch | `blocked_by_owner` | Consume owner release, completion, or supersession before mutation. |
| `open-pr-codex-publisher-inferable-outbox-contract-improver-20260614-fe99d16a.json` | Keep: desired head preserved by exact remote branch | `blocked_by_owner` | Consume owner release, completion, or supersession before mutation. |
| `open-pr-codex-publisher-issue-cap-default-improver-20260614-71e55ace.json` | Keep: desired head preserved by exact remote branch | `blocked_by_human` | Human gate must provide explicit disposition before non-owner movement. |
| `open-pr-codex-publisher-related-lookup-budget-repair-20260615-117d6507.json` | Keep: branch has unique commits not on main, no open PR | `blocked_by_owner` | Owner handoff or supported publication path must represent the unique branch work before archive. |
| `open-pr-codex-rbac-openapi-coverage-primary-20260615-dd112baf.json` | Keep: branch has open PR #8652 | `blocked_by_owner` | Resolve owner gate for exact open PR representation before any archive. |
| `open-pr-codex-read-steering-thread-receipts-improver-20260614-e946d060.json` | Keep: desired head preserved by exact remote branch | `blocked_by_owner` | Consume owner release, completion, or supersession before mutation. |
| `open-pr-codex-receipt-terminal-statuses-primary-20260614-29f893c8.json` | Keep: branch has unique commits not on main, no open PR | `blocked_by_owner` | Owner handoff or supported publication path must represent the unique branch work before archive. |
| `open-pr-codex-reconcile-issue-state-rest-fallback-primary-20260614-879ea1a2.json` | Keep: desired head preserved by exact remote branch | `blocked_by_owner` | Consume owner release, completion, or supersession before mutation. |
| `open-pr-codex-reconcile-merged-pr-commit-proof-20260614-9b7888d7.json` | Keep: desired head preserved by exact remote branch | `blocked_by_owner` | Consume owner release, completion, or supersession before mutation. |
| `open-pr-codex-reconcile-shared-state-default-improver-20260614-a45548e1.json` | Keep: desired head preserved by exact remote branch | `blocked_by_owner` | Consume owner release, completion, or supersession before mutation. |
| `open-pr-codex-replay-cli-import-improver-20260615-7d319f82.json` | Keep: branch has unique commits not on main, no open PR | `blocked_by_owner` | Owner handoff or supported publication path must represent the unique branch work before archive. |
| `open-pr-codex-report-code-quality-pipe-improver-20260614-faee82e2.json` | Keep: desired head preserved by exact remote branch | `blocked_by_owner` | Consume owner release, completion, or supersession before mutation. |
| `open-pr-codex-report-code-quality-summary-only-improver-20260614-de44688d.json` | Keep: desired head preserved by exact remote branch | `blocked_by_owner` | Consume owner release, completion, or supersession before mutation. |
| `queue-drain-park-reconciliation-20260708T121926Z.json` | Skipped: unparseable payload, no branch | `unknown` | Inspect the payload intent and either repair it into a branch-shaped handoff or explicitly retire it through a supported human disposition. |

## Operator Rubric

Use this order when the outbox-depth breach is the only live sentinel breach:

1. Run a scoped reconciler dry-run for the oldest item.
2. Archive only when the same scoped dry-run proves the item is satisfied and
   owner/liveness/steering/open-PR gates all pass.
3. If the item is exact-remote-branch preserved but owner-gated, wait for or
   consume one owner release/completion/supersession. Do not duplicate owner
   requests.
4. If the item has unique commits and no open PR, publish or represent it only
   through a supported branch publication path or explicit owner handoff.
5. If the item is human-gated, stop until the human disposition is explicit.
6. If the item has no branch, do not guess. Repair the payload or retire it
   through an explicit supported disposition.

## Next Single-Cycle Prompt

```text
Start from live repo truth in the Aragora repository root. Operating
contract: re-read docs/AGENT_OPERATING_CONTRACT.md §Conductor this cycle.

Target: outbox_depth breach, oldest live active outbox item. Last: reconciler
dry-run at 1605f175b1fe709997d1b96bf056f3599cd82077 still found no safe
archive action: 8 active-work protected items, 11 missing-branch/open-PR-unknown
items, and one unparseable payload. Next: target exactly one bounded unit:
inspect queue-drain-park-reconciliation-20260708T121926Z.json and determine
whether it can be repaired into a branch-shaped handoff or needs explicit human
retirement. Do not archive outbox, write receipts, release owners, merge,
settle, close PRs, delete worktrees, or touch protected scripts.

Run on Tier 0-2 rails per §Conductor; continue through progressing units
autonomously. Approval-required items, Auto-halt triggers, and Tier 3/4
settlement remain hard stops. If the cycle accomplishes no incremental
progress, make the next prompt one that does.
```
