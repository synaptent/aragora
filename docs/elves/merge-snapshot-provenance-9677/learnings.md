# Project Learnings

## Repo Conventions

- 2026-08-29: Merge-authority changes are Tier 4 even when small. Implementation preparation is allowed only with explicit operator approval; exact-head OWNER settlement remains separate.
- 2026-08-29: Use a dedicated worktree and a branch-scoped `check_work_lease.py` lease. A concurrent lane on #9677 does not block a separate fresh-main branch, but it makes #9677 strictly off-limits.

## Validation and Tooling

- 2026-08-29: The focused baseline is 75 tests across `test_merge_codex_automation_prs.py`, `test_boss_drain.py`, and `test_merge_arbiter.py`; use `-p no:randomly --timeout=300` for deterministic bounded runs.
- 2026-08-29: Main required contexts are `lint`, `typecheck`, `sdk-parity`, `Generate & Validate`, `TypeScript SDK Type Check`, and `aragora-merge-quorum`; main quorum is normally skipped.

## Review Heuristics

- 2026-08-29: `--match-head-commit` is necessary but insufficient. The pinned SHA must be the same SHA that produced eligibility, settlement, required-check, changed-file, and approval evidence.
- 2026-08-29: Tests that compare a freshly fetched head to the guard and merge command can still codify a TOCTOU. They must connect the merge head back to the earlier decision snapshot.
- 2026-08-30: A pinned merge head does not prove required-check provenance. Fetch the check rollup
  with its `headRefOid` in one response, compare that head to the decision snapshot, and fail closed
  before settlement or merge when they differ.
- 2026-08-30: A same-head check rollup can contain duplicate names from reruns. Do not reduce it by
  last-write-wins list order; use the repository's recency-aware reducer so a stale success cannot
  hide a newer failure, pending run, or unrankable non-success.
- 2026-08-30: Snapshot corruption for one PR should make that PR explicitly ineligible without
  hiding later independently inspectable PRs. Keep identity mismatches lane-wide, but carry file
  completeness errors on the affected snapshot and continue enumeration.
- 2026-08-30: Dry-run output is still control-plane output. It must not report `would_merge` unless
  the same valid full snapshot head required by the apply path is present and surfaced in the result.
- 2026-08-30: The focused preflight does not prove generated documentation statistics are current.
  Python/test-count changes must also run `python3 scripts/doc_stats.py --write` followed by
  `node docs-site/scripts/sync-docs.js`; the ready-only docs build is otherwise genuinely unstable.
- 2026-08-30: The terminal Claude P3 about a possible 100-row `statusCheckRollup` cap was checked
  live at exact head `55fe80e36277b870d206aee0c87e66845bb11fb4`; `gh pr view` returned 138 rows,
  so the suspected cap was not present in the installed CLI/GitHub response for this PR.

## Product and Domain Invariants

- 2026-08-29: Exact-head provenance is end-to-end: decision snapshot head equals halt/review/settlement authorization head equals merge-command head.
- 2026-08-29: A missing, malformed, changed, or unavailable trusted head blocks before any normal or admin merge subprocess.

## Known Traps

- 2026-08-29: Reducing a settlement report to a boolean destroys the exact head it authorized; carry a typed result or full SHA instead.
- 2026-08-29: A helper that performs its own last-second head lookup may protect only the command, while silently discarding the checks and file scan from the earlier snapshot.
- 2026-08-29: A private merge helper can still have cross-module consumers. Before making it fail closed, survey imports as well as local call sites and propagate the caller's existing snapshot head rather than adding a compatibility lookup.
- 2026-08-29: `gh pr view --json files` can truncate the files connection at 100 entries. A security-sensitive file scan must include `changedFiles` in the same snapshot and reject any count/path mismatch rather than treating the returned list as complete.
- 2026-08-29: Snapshot completeness must be checked against the raw `files` list before transforming it. Filtering malformed members before count comparison can make an uninspectable file disappear; validate every raw member and its path fail-closed before selection.

## Retired Learnings

- None.
