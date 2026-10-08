# B0 Proxy Metric Interpretation Guide

**Status:** legibility note, paired with the B0 zero-headline diagnostic.
**Date:** 2026-05-19
**Audience:** anyone reading the B0 scorecard (`docs/status/generated/benchmark_scorecards/.../latest.json`) or status doc (`docs/status/B0_BENCHMARK_TRUTH_STATUS.md`).

---

## The headline confusion

If you read `latest.json` you will see two numbers that look like they
should be close but are very far apart:

```json
{
  "truth_metrics": {
    "truth_success_rate": 0.0,
    "no_rescue_truth_success_rate": 0.0
  },
  "proxy_metrics": {
    "no_rescue_success_rate": 0.769,
    "unique_issues_succeeded": 10,
    "success_classes": {
      "deliverable_pr_created": 10
    }
  }
}
```

Naive read: "We're somewhere between 0% (strict) and 77% (loose). The
truth is probably in the middle." **Wrong.**

The actual situation: **truth = 0%; proxy = mostly bail-events relabeled
as success.** They are not different measurements of the same quantity.

---

## What each metric actually counts

### `truth_metrics.truth_success_rate` — what you think it means

Counts corpus issues where GitHub state shows a mergeable-or-merged PR
linked to the issue, satisfying the success contract
`mergeable_pr_or_merged_pr` from `docs/benchmarks/corpus.json`.

**This is the headline metric.** It is the canonical 30-day target in
`NEXT_STEPS_CANONICAL.md` (≥50%).

As of 2026-05-19: **0/13** corpus issues have a mergeable-or-merged
closing PR linked. All 13 are OPEN with `closedByPullRequestsReferences: []`.

### `proxy_metrics.no_rescue_success_rate` — what it actually means

Counts boss-loop ticks (not issues) where the terminal outcome
was either `deliverable_created` or `pr_adopted`. From
`aragora/swarm/terminal_truth.py:278`:

```python
_SUCCESS_OUTCOMES: frozenset[str] = frozenset({"deliverable_created", "pr_adopted"})
```

**`deliverable_created`** means the worker produced something it
considers a deliverable (a PR, a patch, a fix). This sounds like the
right thing.

**`pr_adopted`** means **the worker bailed with `status: needs_human`,
and its deliverable pointed at a pre-existing PR**. From
`aragora/swarm/boss_loop.py:3585-3603`:

```python
def _try_adopt_pr(worker_result: dict[str, Any]) -> bool:
    deliverable_type = str(deliverable.get("type", "")).strip().lower()
    if deliverable_type not in {"pr", "adopted_pr"}:
        return False
    if str(worker_result.get("status", "")).strip() != "needs_human":
        return False
    # ... promote status: needs_human → completed; outcome → pr_adopted
```

So `pr_adopted` events satisfy three conditions:

1. Worker's `status` was `needs_human` (i.e., "I can't finish this
   autonomously")
2. Worker's `deliverable.type` was `adopted_pr` (i.e., "but here's a
   pre-existing PR you might want to look at")
3. The post-processor *promoted* the status to `completed` and the
   outcome to `pr_adopted`

**These are not events where the agent shipped a PR that closes the
issue.** They are events where the agent bailed out and tagged a hint.

### Why the proxy classifies bail-events as success

`_SUCCESS_OUTCOMES` is used by lane telemetry, scorecard generation,
and the reporter to compute aggregate "success" rates. The label
choice was reasonable when the system was being designed — a worker
that finds an existing PR doing the right work has plausibly closed
its loop (the human can then merge the existing PR).

But in the bounded-execution-corpus context, this labeling produces
the misleading 76.9% headline. The corpus issues are open BECAUSE no
one has shipped a closing PR yet. A worker tagging an unrelated
pre-existing PR as "adopted" doesn't close the corpus issue.

---

## The current B0 picture, properly labeled

| Outcome | Count (last refresh) | What it means |
|---|---:|---|
| `deliverable_pr_created` (10) | 10 | Boss-loop ran a worker tick that ended with `pr_adopted` terminal outcome. **Worker bailed**, tagged a pre-existing PR. None of these tagged PRs actually close their corpus issue. |
| `blocked_auth_failure` | 7 ticks | Worker dispatch blocked at credential gate (productized in PRs #7225/#7228/#7248 since May 17; not yet re-tested) |
| `blocked_not_dispatch_bounded` | 8 ticks | Worker dispatch blocked because task was not declared bounded (productized via `ARAGORA_CORPUS_AWARE_DISPATCH` in #7225) |
| `blocked_sanitation_failed` | 2 ticks | Worker dispatch blocked at input sanitization |
| `rescue_no_deliverable` | 1 tick | Rescue path attempted but produced no deliverable |

**Truth: 0/13 unique corpus issues have a closing PR.**
**Proxy "success": 10 ticks with `pr_adopted`, on 10 unique issues.**

The 10 unique issues are the same issues that show OPEN with no closing
PR. The proxy success rate is high because the metric counts bail-events
as success; it goes to zero when you check whether bail-events actually
closed any issues.

---

## How to read the scorecard without being misled

When reading `latest.json` scorecards:

1. **Trust `truth_metrics`, not `proxy_metrics`** for "did autonomy
   actually close issues?" The truth_metrics apply the corpus's
   declared success contract against GitHub state.

2. **Treat `pr_adopted` as a soft signal**, not a success. It tells
   you the worker found a related PR but bailed. The PR may or may
   not actually solve the corpus issue; the worker doesn't verify
   that.

3. **`deliverable_created` ≠ `pr_adopted`.** The former means the
   worker produced a new deliverable. The latter means the worker
   pointed at an existing one. Both currently roll up into "success"
   in the proxy metric.

4. **If the truth metric is at 0.0% and the proxy is high**, the
   gap is almost always `pr_adopted` events. Confirm by looking at
   `success_classes.deliverable_pr_created` vs the breakdown of how
   many of those were `pr_adopted` vs newly-authored — currently
   the scorecard does not distinguish these and that is the legibility
   bug this doc names.

5. **`tick_success_rate` is even noisier.** It counts every boss-loop
   tick (multiple ticks per issue when the loop retries). The current
   B0 has 28 total ticks across 13 issues; tick_success_rate of 0.357
   means 10 of 28 ticks were "successful" in the labeling sense
   above, not that 35.7% of issues were closed.

---

## What a clean follow-up would look like

The current scorecard mixes two distinct outcomes under one label.
A cleaner data model would split:

```python
# current
_SUCCESS_OUTCOMES = frozenset({"deliverable_created", "pr_adopted"})

# proposed
_PR_AUTHORED_OUTCOMES = frozenset({"deliverable_created"})
_PR_HINT_OUTCOMES = frozenset({"pr_adopted"})
_SUCCESS_OUTCOMES = _PR_AUTHORED_OUTCOMES  # restrict to actual shipping
```

Scorecard updates to expose:

```json
"proxy_metrics": {
  "pr_authored_rate": 0.0,           // issues where worker pushed a new PR
  "pr_hint_rate": 0.769,             // issues where worker tagged existing PR
  "no_rescue_success_rate": 0.0,     // collapsed to truth definition
  "_legacy_no_rescue_success_rate": 0.769  // for backward compat
}
```

This is a code change requiring tests in
`tests/swarm/test_terminal_truth.py` and
`tests/swarm/test_lane_telemetry.py`. **Out of scope for this
legibility doc.** Tracked as Move 4c in the B0 zero-headline
diagnostic (`B0_ZERO_HEADLINE_DIAGNOSTIC_2026-05-19.md`, archived dated
snapshot).

---

## Why not just edit the auto-generated B0 status doc?

`docs/status/B0_BENCHMARK_TRUTH_STATUS.md` is regenerated by
`scripts/measure_b0_scorecard.py`. Edits to it get overwritten on
the next publication run.

This doc lives at `docs/benchmarks/B0_PROXY_METRIC_INTERPRETATION.md`
— a stable hand-written explainer that the auto-generated doc can
link to but doesn't overwrite.

If the publisher were to be updated to include a "How to read this"
section pointing at this explainer, that would be a small follow-up
(a one-line addition to `scripts/measure_b0_scorecard.py` to inject
a link in the generated markdown). Not done in this PR; tracked as
Move 4b in the diagnostic.

---

## Provenance

This doc is paired with (both now archived dated snapshots):

- `B0_ZERO_HEADLINE_DIAGNOSTIC_2026-05-19.md` — the
  full diagnostic that prescribes 3 moves; Move 4 is this doc
- `PROJECT_ASSESSMENT_2026-05-19_30D.md` — the 30-day
  strategic assessment that flagged the 0.0% as the cheapest thing
  to move

Source-code reading:

- `aragora/swarm/boss_loop.py:3585-3603` — `_try_adopt_pr()`
- `aragora/swarm/supervisor.py:2474-2481` —
  `_work_order_deliverable_type()`
- `aragora/swarm/terminal_truth.py:278` — `_SUCCESS_OUTCOMES`
  definition
- `aragora/swarm/lane_telemetry.py:23,260` — telemetry SUM filter
  on the outcomes
- `aragora/swarm/reporter.py:733,1449,1456,1632,1643,1650` —
  multiple reporter sites that fold `pr_adopted` into success
