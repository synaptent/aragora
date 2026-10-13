# Multi-Model Issue Triage (Calibration v1)

This guide covers `scripts/triage_issues_via_debate.py`, the
calibration-only multi-model triage tool that dogfoods Aragora's
heterogeneous-panel differentiator on its own GitHub issue backlog.

The report is designed to TEACH the founder how each verdict was
reached, not to assume the founder already knows whether an issue is
good. Each card carries: evidence summary, per-model verdicts with
rationale and evidence anchors, dissent block (when applicable),
founder-facing recommendation (action / safety / what-to-inspect /
refined-title-body / consolidate-with), and a confidence class
(`easy-call` / `needs-spot-check` / `do-not-act-without-human`).

## What this does

1. Fetches open issues from `synaptent/aragora` via `gh`.
2. Picks a stratified sample (default 30 issues) across label and author
   buckets so the calibration set isn't dominated by a single source.
3. Gathers **evidence first**, before any model invocation:
   - Issue body, labels, author, timestamps
   - File references in the body, checked against the repo HEAD
   - Referenced issue / PR numbers with their state
   - Duplicate candidates by title-shingle Jaccard similarity
4. Runs a heterogeneous frontier panel (Claude Opus 4.7 + GPT-4.1 +
   Gemini 3.1 Pro) against the same locked rubric, in parallel.
5. Aggregates verdicts with explicit dissent reporting.
6. Writes two artifacts per run:
   - `receipts.jsonl` – one full audit receipt per issue (prompt, model
     id, raw response, parsed verdict, confidence, cost, latency).
   - `report.md` – human-readable recommendations grouped by verdict
     with the automation-value cross-tab.

## What this does NOT do (v1)

- **Never closes issues.** Closing remains a founder action.
- **Never posts comments.**
- **Never applies labels.**
- **Does not pause Stage-Gate Conductor or any other automation.**
- Does not scale beyond the 30-issue calibration sample without a
  separate founder approval.

These constraints exist because v1 is a calibration audit: founder
reviews the rubric's precision on a stratified sample before any
mutation surface is enabled.

## Rubric

Each model independently emits a strict JSON object with seven verdict
categories plus orthogonal `automation_value`. The standard is
**substantive value, not authorship**: automation-generated issues are
not penalized by origin.

| Verdict             | Meaning                                                                   |
| ------------------- | ------------------------------------------------------------------------- |
| `keep`              | substantively valuable, leave open as-is.                                 |
| `refine`            | valuable but needs scope tightening, repro steps, or an owner.            |
| `consolidate`       | should be merged with a referenced or duplicate issue.                    |
| `close-obsolete`    | referenced code/feature/file no longer exists in HEAD.                    |
| `close-duplicate`   | exact duplicate of an existing open issue.                                |
| `close-malformed`   | empty body, template only, no actionable content.                         |
| `flag-for-human`    | panel uncertain or dissent is real; defer to a human reviewer.            |

| `automation_value`  | Meaning                                                                   |
| ------------------- | ------------------------------------------------------------------------- |
| `valuable`          | automation produced something worth keeping or refining (positive!).      |
| `neutral`           | automation neither strengthened nor weakened the issue.                   |
| `noise`             | automation produced low-signal output that wastes attention.              |
| `n/a`               | issue is not automation-generated.                                        |

`valuable` is an explicit positive outcome of the rubric. It exists to
acknowledge that the boss loop, stage-gate conductor, and other
automation can produce excellent issues; the calibration aims to find
them, not delete them by association.

## Receipt-equivalent artifacts

Every panel invocation persists:

- The full prompt sent to the model.
- The model id and panel-member metadata (`agent_type`, `nickname`).
- The raw response (verbatim, before parsing).
- Parsed verdict, confidence, automation value, rationale, suggested
  action, evidence anchors cited.
- Cost (tokens × per-model rate) and per-call latency.
- Aggregate verdict, consensus kind (unanimous/majority/split/unclear),
  and a rationale that explicitly cites dissenting members in split
  cases.

Schema version: `triage-receipt/1.1`. The receipt schema mirrors
Aragora debate-receipt surface area so future upgrades to a full
`Arena.run()` integration are a schema-compatible swap, not a rewrite.

## Aggregation

- **Unanimous**: all models agreed on the verdict.
- **Majority**: strict majority chose one verdict; the verdict is
  reported with averaged confidence over winners.
- **Split with high confidence (avg ≥ 0.55)**: the highest-confidence
  model wins; dissent is surfaced in the rationale.
- **Split with low confidence (avg < 0.55)**: verdict flips to
  `flag-for-human`.
- **All errors**: `flag-for-human` with the error trail in the
  rationale.

## Recommended founder review sequence

1. Print a synthetic sample card to learn the report shape (no model
   calls, no GitHub calls, no cost):

   ```bash
   python scripts/triage_issues_via_debate.py --sample-card
   ```

   Read the rendered card to confirm the evidence-summary / per-model /
   founder-facing-recommendation layout matches what you want to act on.

2. Estimate cost on a real stratified sample:

   ```bash
   python scripts/triage_issues_via_debate.py \
     --repo synaptent/aragora --sample 30 --limit-pool 200 --estimate
   ```

3. Print the first issue's full prompt (still no model calls) to verify
   the evidence block looks correct:

   ```bash
   python scripts/triage_issues_via_debate.py \
     --repo synaptent/aragora --sample 30 --limit-pool 200 --dry-run-prompt
   ```

4. Only after the shape is acceptable, run the real calibration:

   ```bash
   python scripts/triage_issues_via_debate.py \
     --repo synaptent/aragora --sample 30 --limit-pool 200 \
     --budget-usd 5 \
     --output-dir .aragora/triage/calibration/$(date -u +%Y%m%dT%H%M%SZ)
   ```

5. Review `report.md`. For each issue:
   - Check the evidence summary matches the real issue.
   - Check the per-model rationale uses concrete evidence anchors.
   - For `easy-call` cards: confirm the action is reversible.
   - For `needs-spot-check` cards: quickly verify the inspect block.
   - For `do-not-act-without-human` cards: read the dissent and decide.
6. If the rubric is good, scale (separate spec). If not, adjust
   `PANEL_PROMPT_RUBRIC` in `aragora/triage/issue_evaluator.py` and
   re-run targeted issues via `--issues N1,N2,...`.

## Usage

### Estimate cost without invoking models

```bash
python scripts/triage_issues_via_debate.py \
  --repo synaptent/aragora \
  --sample 30 \
  --estimate
```

Prints the projected cost broken down by panel member. No model is
invoked, no artifacts are written.

### Run the 30-issue calibration sample

```bash
mkdir -p .aragora/triage/runs/$(date +%Y%m%dT%H%M%S)
python scripts/triage_issues_via_debate.py \
  --repo synaptent/aragora \
  --sample 30 \
  --output-dir .aragora/triage/runs/$(date +%Y%m%dT%H%M%S) \
  --budget-usd 10
```

Writes `receipts.jsonl`, `report.md`, and `summary.json` into the
output directory. Reruns into the same directory skip already-evaluated
issues (resume safety).

### Re-evaluate specific issues

```bash
python scripts/triage_issues_via_debate.py \
  --issues 7172,7171,7169 \
  --output-dir .aragora/triage/calibration/focused
```

Useful for re-running the panel after a rubric tweak on a known set of
issues.

### Print the first issue's prompt (no model invocation)

```bash
python scripts/triage_issues_via_debate.py \
  --repo synaptent/aragora \
  --sample 5 \
  --dry-run-prompt
```

Use this to inspect what evidence the panel will actually see for a
given issue before paying for the call.

## Flags

| Flag                  | Default                                  | Notes                                            |
| --------------------- | ---------------------------------------- | ------------------------------------------------ |
| `--repo`              | `synaptent/aragora`                      | GitHub owner/name slug.                          |
| `--sample`            | `30`                                     | Stratified sample size (ignored if `--issues`).  |
| `--issues`            | `""`                                     | Comma-separated issue numbers; overrides sample. |
| `--seed`              | `1337`                                   | Sampling RNG seed for reproducibility.           |
| `--panel`             | `""`  (= default 3-member panel)         | Comma-separated agent types.                     |
| `--output-dir`        | `.aragora/triage/runs/<timestamp>`       | All artifacts land here.                         |
| `--budget-usd`        | `10.0`                                   | Hard cap; run aborts if projection exceeds.      |
| `--max-concurrent`    | `3`                                      | Parallel panel evaluations.                      |
| `--estimate`          | off                                      | Print projection and exit.                       |
| `--dry-run-prompt`    | off                                      | Print first-issue prompt and exit.               |
| `--sample-card`       | off                                      | Render a synthetic founder-facing card, no costs.|
| `--limit-pool`        | `1000`                                   | Max issues fetched before sampling.              |
| `--log-level`         | `INFO`                                   | Standard logging level.                          |

Environment overrides: `ARAGORA_TRIAGE_SEED`, `ARAGORA_TRIAGE_LOG_LEVEL`.

## Calibration loop (intended)

1. Run `--sample 30 --estimate` to confirm cost projection.
2. Run the same with model invocations under `--budget-usd 10`.
3. Founder reviews `report.md`. For each issue, decide whether the
   panel verdict matches your judgement.
4. If precision is acceptable, propose scale (more issues, additional
   verdict actions) in a separate spec.
5. If precision is not acceptable, adjust the rubric in
   `aragora/triage/issue_evaluator.py::PANEL_PROMPT_RUBRIC` and re-run
   the same issues via `--issues N1,N2,...` to compare.

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/scripts/test_triage_issues_via_debate.py -v
```

The suite stubs every external surface (`gh`, agent generators) so
nothing hits GitHub or model providers.

## Library entry points

```python
from aragora.triage import (
    DEFAULT_PANEL,
    PANEL_PROMPT_RUBRIC,
    VERDICT_CATEGORIES,
    AUTOMATION_VALUE_VALUES,
    build_panel,
    build_panel_prompt,
    estimate_cost_usd,
    evaluate_issue,
    gather_evidence,
    is_automation_generated,
    parse_model_response,
    aggregate_verdicts,
    IssueRecord,
    IssueEvidence,
    IssueDebateReceipt,
    PanelMember,
    PerModelVerdict,
    write_jsonl_receipt,
    write_markdown_report,
)
```

The library is also useful from notebooks or from a future Arena-backed
integration: feed in your own panel + generator and you get the same
receipt shape.

## Mechanical triage pass (2026-07-29)

Separate from the calibration tool above, a one-off **mechanical** pass was run
against the full open backlog. It is recorded here so the rules are auditable
and repeatable.

### Why it was needed

`gh issue list --limit 500` reports "500+" and silently truncates. The real
open count was **1,379**, and the largest cohort — 770 issues created in
2026-04, 56% of the backlog — sat entirely behind that cap. Any triage driven
by the capped query is reasoning about the visible tail, not the backlog.

### Disposition labels

| Label | Meaning |
|---|---|
| `triage:superseded` | Work verified already present on `main`; closed |
| `triage:duplicate` | Duplicate of a rolling anchor issue; closed |
| `triage:verified-real` | Verified still outstanding on `main`; keep |
| `triage:protected` | Load-bearing; never auto-close |
| `triage:defer-salvage` | Live branch with an unmerged delta; belongs to a branch-salvage pass |
| `triage:unverified` | No mechanical verdict available; needs a human read |

### Rules that produced them

1. **Protect first.** Never close: named load-bearing issues (#274, #509 pentest /
   SOC 2; #9391 P0 outage; #8858 outsider verification), anything human-authored,
   and anything labelled `epic`, `program:execution-2026`, `priority:critical`,
   or `priority:high`.
2. **Superseded requires proof on `main`, not title similarity.** For exception-
   handling issues, the named file must contain no broad `except Exception` /
   bare `except:` outside a documented `# noqa: BLE001`. For "add unit tests for
   X" issues, `test_X.py` must exist.
3. **Ambiguity yields no verdict.** If a basename resolves to more than one file,
   or the issue names a directory path that the found test file does not mirror,
   the issue is left `triage:unverified` rather than closed.
4. **Branch survival is not evidence either way.** Dispatch rows ("Open a PR
   for …") were checked against the remote: of 6 surviving branches sampled, 6
   carried real unmerged deltas vs `main`. They are deferred, not closed.

### What the sampling caught

The rules were validated before applying, and the validation changed them twice:

- A first-cut classifier ran the exception check on *every* issue naming a
  `.py` file, so "Add unit tests for `approvals.py`" was being marked superseded
  because that file had no broad `except`. Gating the check on the issue's own
  subject cut the close set from 338 to 88.
- Cohorts are roughly half-done, not uniformly stale: of 209 exception issues,
  **115 cleared and 69 were still real**; of 137 unit-test issues, **68 existed
  and 45 were missing**. Age predicted nothing. A blanket close by age or by
  cohort would have destroyed the real half.

### Result

1,379 open → 1,250 open, all labelled. 128 closed (88 verified-superseded,
40 duplicate run-logs), each with a comment citing the `main` commit and the
specific file checked, and each inviting reopen.

### Known gap

The `stale-close` rule is **not** implemented as applied. It was authorized at a
120-day inactivity threshold, but the candidate cohort's maximum inactivity is
111 days, so the rule matched zero issues. Thresholds that would bite:
>90d → 303 issues, >105d → 257. Re-run with a lower threshold to enable it.
