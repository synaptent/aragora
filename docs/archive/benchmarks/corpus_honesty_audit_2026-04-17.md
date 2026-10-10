# Benchmark Corpus Honesty Audit — 2026-04-17

*Auditor: Droid (independent review, read-only).*
*Scope: `tw-01-bounded-execution-v1` rev-2, published in
`docs/benchmarks/corpus.json` on 2026-04-15, with the companion truth artifact
under `docs/status/generated/benchmark_truth_artifacts/tw-01-bounded-execution-v1/latest.json`
(generated 2026-04-16T15:09:19Z).*

---

## Executive summary

**Aggregate honesty rating: 1/10.**

The rev-2 corpus does **not** measure autonomous execution quality. It measures
"was this GitHub issue eventually closed and linked to any merged PR, regardless
of authorship?"  For every one of the five entries the autonomy system either
(a) never attempted the issue at all, or (b) attempted it, failed, and the
issue was subsequently fixed by the founder running Claude Code / Codex CLI
sessions by hand. The headline `truth_success_rate: 1.0` in
`docs/status/generated/benchmark_scorecards/tw-01-bounded-execution-v1/latest.json:56`
is therefore an artifact of PR-linkage bookkeeping, not of the swarm's work.

The decisive evidence is inside the same scorecard JSON the project is using to
open the "Foreman reliability" gate. Its own `proxy_metrics` block
(`docs/status/generated/benchmark_scorecards/tw-01-bounded-execution-v1/latest.json:28-50`)
records the ground truth:

```
neutral_classes: { "issue_already_resolved": 5 }
success_classes: {}
no_rescue_success_rate: 0.0
tick_success_rate: 0.0
unique_issues_succeeded: 0
```

Five attempts, five short-circuits to `issue_already_resolved`, zero worker
successes. The "100% no-rescue success" headline is produced downstream by a
`truth_success_rate` that counts any merged PR that textually references the
issue as a success signal. Cross-referenced against 305 recorded ticks in
`.aragora/overnight/boss_metrics.jsonl`, the autonomous loop has produced
**zero `worker_outcome: merged_pr`** events in its entire history — while
accumulating 72 `blocked_auth_failure`, 55 `blocked_not_dispatch_bounded`, 52
`rescue_no_deliverable`, and 35 `blocked_sanitation_failed` outcomes. The gate
that `docs/status/NEXT_STEPS_CANONICAL.md:13` says must be "complete, fresh,
and trustworthy" is currently complete and fresh but not trustworthy.

### Count

| Class | N | Entries |
|-------|---|---------|
| Genuine autonomous closure | **0** | none |
| Artifact (closed manually / by Dependabot / by founder-driven Claude-Code PR) | **5** | #873, #1064, #1641, #2712, #5756 |
| Edge case | 0 | — |

### Top 3 corrections recommended

1. **Retire the five-entry rev-2 corpus wholesale.** Publish `revision: 3` with
   zero issues and mark the scorecard status `empty` until the autonomy loop
   actually dispatches a worker that merges a PR. Reporting `1.0` against an
   empty corpus is more honest than reporting `1.0` against five closed issues.
2. **Rewrite the freshness invariant in `tests/benchmarks/test_corpus_freshness.py`.**
   The current invariant (lines 44, 62-63, 66-69) requires every entry to be
   `CLOSED`, `linkage_status == "verified"`, and `truth_success == true`. That
   is inside-out: it forces the corpus to contain only already-solved issues,
   which is exactly the failure mode we are measuring. Replace it with an
   invariant that requires every entry to be `OPEN` at corpus authoring time
   **and** to have been dispatched at least once to the boss loop with a
   recorded `worker_outcome`.
3. **Stop crediting forensic-reference PRs as closure evidence.** The truth
   artifact at `docs/status/generated/benchmark_truth_artifacts/tw-01-bounded-execution-v1/latest.json:30-131`
   lists ten "linked_prs" for #873, nine of which are unrelated swarm hardening
   PRs that merely mention #873 as a forensic case study. Only the
   `closedByPullRequestsReferences` edge from GitHub's GraphQL API (which for
   #873 is **empty** — the issue was closed manually as stale) should count as
   closure evidence.

---

## Per-entry analysis

For every entry I cross-referenced the corpus row
(`docs/benchmarks/corpus.json:11-54`), the truth artifact record
(`docs/status/generated/benchmark_truth_artifacts/tw-01-bounded-execution-v1/latest.json`),
the GitHub issue state (`gh issue view <N>`), the closing-PR metadata
(`gh pr view <M>`), and any boss-loop ticks for that issue in
`.aragora/overnight/boss_metrics.jsonl`.

### #1064 — Boss-loop execution: bump @supabase/supabase-js from 2.99.1 to 2.99.3 in /aragora/live

- **Closure mechanism**: Closed by PR **#1066**, authored and merged by the
  founder `@an0mium` on 2026-03-19T17:21:15Z. Branch name
  `claude/bump-supabase-js-1064` and PR body footer
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)` show this
  was a manual Claude Code session driven by the founder, **not** a dispatch
  from `aragora.swarm.boss_loop`.
- **Attempt evidence**: `.aragora/overnight/boss_metrics.jsonl` contains
  **zero** ticks with `issue_number == 1064` — the autonomous boss loop never
  even attempted this issue. The `docs/examples/boss-lane-manifest-2026-03-19.yaml`
  manifest names #1064 as the "first bounded live Boss-loop proof target", but
  the recorded metrics show the founder hand-wrote the fix without letting the
  boss loop run. The scorecard's `proxy_metrics.neutral_classes.issue_already_resolved`
  counts simply reflect post-hoc `--no-dispatch` probes, not work attempts.
- **Success attribution**: The scorecard credits #1064 as a success
  (`truth_success: true` at latest.json:140) because PR #1066 merged and
  referenced the issue. That is pure bookkeeping — it attributes success to
  the human-driven Claude Code session, not to anything the autonomy substrate
  did.
- **Verdict**: **RETIRE**.

### #873 — Bump @eslint/eslintrc from 3.2.0 to 3.3.0 in /aragora/live *(corpus title is misleading — actual title is "Boss-loop execution: resolve aragora/live @eslint/eslintrc bump for Dependabot #857")*

- **Closure mechanism**: Closed as **stale** by `@an0mium` on 2026-03-19T15:24:06Z
  with the comment *"Closing as stale. PR #857 merged on 2026-03-18, so this
  issue no longer points at an open dependency lane."* GitHub's
  `closedByPullRequestsReferences` for #873 is empty (confirmed via
  `gh issue view 873 --json closedByPullRequestsReferences`). Dependabot PR
  **#857** (bot-authored, founder-merged) resolved the underlying dependency
  *before* the boss loop ever produced a deliverable.
- **Attempt evidence**: `.aragora/overnight/boss_metrics.jsonl` records **four
  attempts** on #873: three `rescue_no_deliverable` and one
  `blocked_sanitation_failed`. Every single tick failed. The retrospective
  forensic PR #880 (`fix(swarm): enforce file-scope constraints`) explicitly
  documents the failure mode: the dispatched Codex worker edited
  `.codex_session_meta.json`, `README.md`, and five `docs/*.md` files instead
  of `aragora/live/package.json`, and the supervisor waited the full 30-minute
  commander timeout without killing it. #873 is in fact a concrete record of
  the autonomous system failing.
- **Success attribution**: The truth artifact lists **ten** "linked_prs" for
  #873 (latest.json:30-131). **Nine of them** (#880, #881, #882, #885, #886,
  #887, #890, #893, #900) are unrelated swarm hardening PRs that merely cite
  #873 as a forensic case study in their PR bodies; none of them closed the
  issue, and most of them landed *before* the issue was even closed. The
  success signal is therefore purely textual-reference noise. Truth metrics
  report `truth_success: true` for #873 (latest.json:139) — that is
  dishonest on its face.
- **Verdict**: **RETIRE**. This entry is the single most misleading member of
  the corpus; its own forensic record shows the autonomy system burned 1978s
  of commander time producing nothing, yet it is reported as a clean
  no-rescue success.

### #1641 — Wire prompt refiner env *(issue title: "Wire prompt refiner files into worker subprocess env vars")*

- **Closure mechanism**: Closed by PR **#1714**, authored and merged by
  `@an0mium` on 2026-03-30T18:37:50Z. Branch `codex/prompt-refiner-worker-env`
  and test-plan invocation of `python3 -m pytest … -k refine` indicate a
  founder-driven Codex CLI session, not an autonomous boss-loop dispatch.
- **Attempt evidence**: **Zero** ticks in `.aragora/overnight/boss_metrics.jsonl`
  with `issue_number == 1641`. The boss loop never touched this issue.
- **Success attribution**: Credited as `truth_success: true`
  (latest.json:159) entirely on the strength of founder-authored PR #1714.
- **Verdict**: **RETIRE**. Adds nothing to the measurement.

### #2712 — Fail closed on string booleans in QualityPipelineConfig.from_dict

- **Closure mechanism**: Closed by PR **#5763**, authored and merged by
  `@an0mium` on 2026-04-15T05:27:49Z. Branch
  `fix/quality-pipeline-string-booleans-2712`, body includes
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Issue
  label is `overnight-founder`, not `boss-ready` — this issue was explicitly
  scoped as founder tranche, not autonomous tranche. It was then added to the
  autonomous benchmark corpus *after* the founder had already closed it.
- **Attempt evidence**: **Zero** ticks with `issue_number == 2712`. The
  autonomous boss loop never dispatched a worker to this issue.
- **Success attribution**: `truth_success: true` (latest.json:179), entirely
  from the founder's PR #5763. Worse, #2712's younger siblings
  (#2710, #2711, #2713-#2723 in the same `overnight-founder` tranche — see
  `gh issue list --label overnight-founder`) are still open with essentially
  identical shape; those open siblings would be honest corpus members and
  were passed over in favour of the one the founder already solved.
- **Verdict**: **RETIRE** and **REPLACE-WITH-#2723** (or any still-open
  `overnight-founder` sibling). Replacement rationale below.

### #5756 — Fail closed on 8 silent except-Exception-pass in boss_loop.py

- **Closure mechanism**: Closed by PR **#5766**, authored and merged by
  `@an0mium` on 2026-04-15T05:35:33Z (eight minutes after the founder closed
  #2712 via #5763). Branch `fix/boss-loop-silent-catches`, body:
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- **Attempt evidence**: `.aragora/overnight/boss_metrics.jsonl` contains
  **one** tick with `issue_number == 5756`, terminal class
  `blocked_auth_failure`. The autonomy system tried once, was blocked by an
  auth failure, and the founder then solved the issue by hand via Claude Code.
  The rev-2 corpus adds the issue as a replacement for #1733 (see
  `docs/benchmarks/corpus.json:30` `revision_note`) *after* #5756 was already
  closed, on the same day.
- **Success attribution**: `truth_success: true` (latest.json:199) because
  the founder's PR #5766 is linked. This is the cleanest example of the
  pattern: the scorecard credits the autonomy system with a success on the
  same run where the sole recorded autonomy attempt was
  `blocked_auth_failure`.
- **Verdict**: **RETIRE**. (The issue's existence is still useful as a record
  of an auth-failure blocker, but not as a member of an execution-quality
  benchmark.)

---

## Cross-cutting findings

### Invariant effects — the freshness test is actively harmful

`tests/benchmarks/test_corpus_freshness.py:44` asserts
`freshness["status"] == "fresh"` and lines 62-69 assert that every corpus
record must be `CLOSED`, have `linkage_status == "verified"`, and
`truth_success == true`. Read literally, this invariant **requires** that
every corpus entry be an already-closed, already-merged issue — which is
exactly the artifact class this audit flags. The practical consequence is that
the only way to keep the freshness test green is to repeatedly swap entries
out for closed issues after they close; open issues with in-progress
autonomous work are structurally inadmissible.

This inverts the design intent described in
`docs/status/NEXT_STEPS_CANONICAL.md:63-64`:

> - fixed benchmark corpus of bounded issues
> - context-enriched workers complete **>=50%** of that corpus **without
>   human rescue**

If every corpus entry is post-hoc closed by a founder Claude Code session,
the ">=50% without human rescue" target is trivially satisfied at 100% —
the human rescue already happened before the benchmark ran.

### Distribution

| Dimension | Finding |
|-----------|---------|
| Issues closed by swarm-dispatched worker PR | 0 / 5 |
| Issues closed by founder-authored Claude Code / Codex PR | 4 / 5 (#1064, #1641, #2712, #5756) |
| Issues closed manually as stale after an upstream bot PR | 1 / 5 (#873, superseded by Dependabot #857) |
| Issues ever dispatched to the autonomous boss loop | 2 / 5 (#873 × 4 attempts, #5756 × 1 attempt) |
| Issues where a boss-loop attempt produced a mergeable deliverable | 0 / 5 |
| Boss-loop recorded ticks with `worker_outcome == merged_pr` | **0 / 305** (entire metrics history) |
| Scorecard `truth_success_rate` reported | **1.0** |
| Scorecard `proxy_metrics.no_rescue_success_rate` reported | **0.0** |

The gap between the reported truth rate (1.0) and the proxy rate (0.0) is the
honesty gap. `proxy_metrics` is the internal tell-tale; the downstream
consumers in `docs/status/B0_BENCHMARK_TRUTH_STATUS.md` and the "Foreman
reliability" gate narrative read the truth rate.

### Candidate replacements (open, bounded, not-yet-resolved)

A legitimate corpus would be composed of *open* issues the autonomy loop can
be given a real chance to solve. Candidates harvested from
`gh issue list --search "is:open label:autonomous -label:boss-stuck"` and
`gh issue list --search "is:open label:overnight-founder"`, filtered for
"bounded / single-file fail-closed / targeted regression test" shape:

| # | Title | Why it qualifies |
|---|-------|------------------|
| 2710 | Fail closed on string-valued `auto_synthesize` in voice stream config | Sibling of #2712; open; `overnight-founder` label; single-file fail-closed. |
| 2711 | Fail closed on string-valued `consensus_reached` in inbox triage runner | Same shape as #2712; open. |
| 2713 | Fail closed on string execution-gate flags in receipt_gate | Same shape as #2712; open. |
| 2717 | Validate string and plan fields in signup and org-setup helpers | Bounded per-module validation. |
| 2720 | Fail closed on suspended budgets in billing/budget_manager.py | Single-file fail-closed. |
| 2722 | Harden `parse_score_response` against malformed score payloads | Bounded regression-test-sized. |
| 2723 | Enforce `max_uses_per_session` in policy/engine.py | Has search anchors and validation commands already in the issue body — ideal autonomous workload. |
| 5818 | Add unit tests for `utils/error_sanitizer.py` | Bounded test-authoring workload. |
| 5825–5829 | Replace silent exception swallowing in bridges.py / belief.py / etc. | Family of bounded hardening tasks, currently `boss-stuck` — i.e. the autonomy loop **has** been dispatched to them and failed, which is exactly the kind of stressful-but-honest signal the benchmark needs. |
| 5839 | Restock stale issues in `tw-01-bounded-execution-v1` rev-1 | Meta-fix that would itself be a measurable benchmark task. |

Note that several of the above (#5839, #5893, #5894, #5962, #5999) are
already labeled `boss-stuck` — the autonomy loop has provably attempted them
and hit its retry budget. Those are the *ideal* benchmark members: they
directly measure whether continued work on the substrate is moving those
failures into successes.

### Related weaknesses worth flagging

- **`docs/benchmarks/benchmark_corpus_freshness.json` is empty**
  (`{"schema_version": 1, "entries": []}`). The freshness map that the test
  at `tests/benchmarks/test_corpus_freshness.py` references has never been
  populated, so there is no machine-readable record of which entries were
  swapped in, which were retired, or why.
- **`docs/status/generated/rescue_productization/latest.json`** shows every
  telemetry aggregation is zero
  (`total_unique_classes: 0`, `recent_limit: 500`). Either no rescue events
  are being published, or the linkage pipeline is not pointed at
  `~/.aragora/rescue_events.jsonl` correctly.

Both reinforce the same finding: the instrumentation surface is plumbed for
publication but is not yet publishing anything derived from real autonomous
work.

---

## Concrete next steps

### 1. Immediate (corpus.json edits)

- Replace `docs/benchmarks/corpus.json` with `revision: 3` that lists **zero
  issues** (empty `issues: []`). This honestly reflects current state:
  no autonomously-resolvable issue has been proven resolved by the swarm.
- As soon as the boss loop produces its first `worker_outcome == merged_pr`
  on `main`, add that single issue as the initial rev-3 corpus member with
  full attempt provenance (worker run_id, worktree path, PR number).

### 2. Short-term (freshness-test invariant changes)

Rewrite `tests/benchmarks/test_corpus_freshness.py` so that per-entry
invariants measure **attempt and authorship**, not closure. Required fields
per corpus entry should include at least:

- `first_dispatch_at` — ISO timestamp the boss loop first opened a work
  order for this issue.
- `worker_run_id` — concrete swarm run the closing PR came from.
- `closing_pr_author` — must be a known swarm worker bot identity (not
  `@an0mium`, not `app/dependabot`).
- `closing_pr_head_branch` — must match the swarm branch convention
  (`codex/...` or `claude/...` generated by `worker_launcher`, not
  founder-authored `fix/...` branches).

Add one new failing test that asserts every corpus entry's closing PR was
authored by a non-founder bot identity, and that there is at least one
successful `worker_outcome == merged_pr` tick for the issue in
`.aragora/overnight/boss_metrics.jsonl`.

### 3. Long-term (process changes)

- **Separate "the corpus" from "the scorecard truth surface."** Today the
  scorecard reads `truth_success` purely from PR-linkage heuristics. The
  primary success signal should be the `boss_metrics.jsonl`
  `worker_outcome` + `terminal_class` pair, not GraphQL closing-references.
  Let `truth_success` require both: closing PR provenance + a matching
  autonomous attempt ledger.
- **Freeze authorship identity.** `worker_launcher` should publish PRs from a
  dedicated machine identity (e.g. `aragora-swarm[bot]`). That single change
  makes the honesty audit trivially automatable: a closing PR authored by a
  human counts as a rescue, period.
- **Do not open the Foreman-reliability gate** (the gate described in
  `docs/status/NEXT_STEPS_CANONICAL.md:13`) until the corpus contains at
  least one entry whose closing PR is authored by the swarm identity and
  whose corresponding tick in `boss_metrics.jsonl` is
  `terminal_class: deliverable_pr_merged` (or the equivalent successful
  class). Until then, the "complete, fresh, and trustworthy" clause is
  falsified on the "trustworthy" axis.

---

*End of audit.*
