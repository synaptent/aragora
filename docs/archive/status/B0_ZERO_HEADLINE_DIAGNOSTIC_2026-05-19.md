# B0 Zero-Headline Diagnostic — 2026-05-19

**Window:** state as of `origin/main` head `7c5a0d5ef2`
**Author:** claude-B061F80D
**Trigger:** the 30-day project assessment (#7373) flagged the B0 verified
truth success rate (0.0%) as the cheapest single thing to move; this doc
is the read-only diagnostic that prescribes the specific move.

---

## TL;DR — the 0.0% is more solvable than it looks

**The 0.0% verified truth rate is correct.** The 76.9% proxy success
rate that appears alongside it is **misleading**: `pr_adopted` does not
mean "the agent created a PR to close the issue"; it means the worker
bailed with `needs_human` status and tagged a pre-existing PR as a
deliverable. Of 13 corpus issues, **zero** have a closing PR linked on
GitHub. **Ten** had workers run that returned `needs_human + adopted_pr`.
**Three** hit `blocked_auth_failure` (credential gate).

This changes the prescription from the assessment doc. The original three
paths were "make corpus easier / instrument rescue / replace proof
surface." The diagnostic suggests a **fourth, cheaper path**:

> **Instrument and fix the `needs_human + adopted_pr` decision point**
> in the worker. The corpus is bounded enough. The agent is reaching
> it. The agent is bailing out at the moment it should ship a PR. Find
> out why.

The cheapest single concrete probe: **run one instrumented dispatch on
ONE corpus issue (e.g., #5426 — `Add operator-snapshot subcommand to
agent_bridge.py`, the smallest task) and observe what triggers the
`needs_human` bail.** Without that observation, all other prescriptions
are speculation.

---

## Per-corpus-issue state matrix

Live state as of 2026-05-19. All 13 corpus issues are **OPEN** on GitHub
with **zero closing-PR linkage**.

| # | Issue | Class | Boss-metric ticks | GitHub state | Linked closing PR |
|---|---|---|---|---|---|
| 5185 | unit tests for `utils/sql_helpers.py` | missing_test_coverage | blocked + pr_adopted | OPEN | none |
| 5187 | unit tests for `storage/governance/metrics.py` | missing_test_coverage | blocked + pr_adopted | OPEN | none |
| 5197 | unit tests for `tournaments/database.py` | missing_test_coverage | blocked + pr_adopted | OPEN | none |
| 5198 | unit tests for `server/debate_origin/models.py` | missing_test_coverage | blocked + pr_adopted | OPEN | none |
| 5200 | unit tests for `server/handlers/admin/health/liveness.py` | missing_test_coverage | blocked + pr_adopted | OPEN | none |
| 5426 | Add `operator-snapshot` subcommand to `agent_bridge.py` | small_refactor | pr_adopted only | OPEN | none |
| 5427 | Add `__all__` to `rescue_events.py` + `rescue_planner.py` | small_refactor | pr_adopted only | OPEN | none — but boss-harvest PR #5432 was MERGED yet didn't close the issue |
| 5428 | Add type annotations to `boss_loop_outcome.py` | small_refactor | pr_adopted only | OPEN | none |
| 5764 | Update `QualityPipelineConfig.from_dict()` to validate bool | validation_tightening | pr_adopted only | OPEN | none |
| 5789 | Narrow broad `except Exception` in `mfa_enforcement.py` | exception_narrowing | blocked_auth_failure | OPEN | none |
| 5790 | Narrow broad `except Exception` in `swarm_status.py` | exception_narrowing | blocked_auth_failure + acceptance_gate_failed; also boss-harvest PR #7120 was CLOSED (not merged) | OPEN | none |
| 5839 | [TW-02] Restock stale issues in rev-1 | benchmark_corpus_maintenance | blocked_auth_failure ×3, then pr_adopted | OPEN | none |
| 5844 | [CS-01..03] Reconcile docs/status surfaces | docs_reconciliation | blocked + blocked_auth_failure | OPEN | none |

**Aggregate:**

- 10 of 13: `pr_adopted` outcome (worker returned `needs_human` and tagged
  a pre-existing PR; **zero of these PRs actually close the issue**)
- 3 of 13: `blocked_auth_failure` (credential gate, no work attempted)
- 1 boss-harvest PR (#5432) merged for #5427 but the issue stayed open
- 1 boss-harvest PR (#7120) opened for #5790 but was CLOSED before merge

---

## What `pr_adopted` actually means (source-code reading)

From `aragora/swarm/boss_loop.py:3585-3603` and
`aragora/swarm/supervisor.py:2474-2481`:

```python
# boss_loop.py:3585
def _try_adopt_pr(worker_result: dict[str, Any]) -> bool:
    deliverable_type = str(deliverable.get("type", "")).strip().lower()
    if deliverable_type not in {"pr", "adopted_pr"}:
        return False
    if str(worker_result.get("status", "")).strip() != "needs_human":
        return False
    # ...
    worker_result["status"] = "completed"
    worker_result["outcome"] = "pr_adopted"
```

```python
# supervisor.py:2474
def _work_order_deliverable_type(item: dict[str, Any]) -> str | None:
    deliverable = extract_work_order_deliverable(item, require_terminal_status=False)
    deliverable_type = str(deliverable.get("type", "")).strip()
    if deliverable_type == "adopted_pr":
        return "pr_adopted"
    return "deliverable_created"
```

The semantics are:

- Worker's `status` was `needs_human`
- Worker's `deliverable` was of type `adopted_pr` (or `pr`)
- A post-processor promoted `status: needs_human → completed` and
  `outcome → pr_adopted`

The `adopted_pr` deliverable type means the worker is pointing at an
**existing PR** as the answer. It's not a new PR the worker pushed.

Consequence: every `pr_adopted` boss-metric event is a worker giving up
("I need human help") with a "but here's a PR you could look at" hint.
None of those events represent autonomous issue closure.

This is why `terminal_truth.py:278` defines:

```python
_SUCCESS_OUTCOMES: frozenset[str] = frozenset({"deliverable_created", "pr_adopted"})
```

— the metrics LABEL `pr_adopted` as success, but the labeling is internal
record-keeping, not GitHub-state truth. The truth artifact correctly
applies the success contract `mergeable_pr_or_merged_pr` against actual
GitHub state, and gets 0/13.

---

## The two distinct failure modes

### Mode A: `needs_human + adopted_pr` (10/13 corpus issues)

**What's happening:** worker starts work on a bounded task, can't
complete autonomously, finds an existing PR that touches the same files
or topic, and surfaces "look at this PR" as the answer.

**Why it matters:** these are exactly the tasks the corpus was DESIGNED
to test bounded autonomy on. They are bounded:

- 5 unit-test tasks (write `tests/X/test_Y.py` for a small module)
- 4 small_refactor tasks (`__all__`, type annotations, subcommand
  addition, validation)
- 1 docs-reconciliation task

These should be among the easiest possible bounded autonomous tasks. If
the worker bails on these, the autonomy gate is set too high somewhere.

**Hypotheses (none confirmed without further investigation):**

1. The worker's acceptance-gate requires CI to pass, and pushing a new
   PR triggers the full CI which blows the worker's wall-clock budget,
   so the worker times out before CI completes and falls back to
   `needs_human`.
2. The worker's branch-push capability is denied by the lane registry
   or the worktree autopilot, so the worker can't actually push, and
   falls back to `adopted_pr` (claim some existing PR exists).
3. The worker's worktree gets cleaned up by the worktree autopilot
   mid-execution because of disk pressure or TTL, and the worker
   can't recover its branch state.
4. The worker's CredentialEnvelope check passes provider-key check but
   fails the GitHub-push check (or vice versa), and the partial failure
   surfaces as `needs_human + adopted_pr` instead of
   `blocked_auth_failure`.
5. The corpus tasks have implicit dependencies the worker can't satisfy
   (e.g., the test-coverage tasks require running the test against a
   working aragora install, and the worker's environment isn't set up
   right).

**To distinguish hypotheses:** dispatch one instrumented worker on
issue #5426 (smallest, simplest — add a subcommand) and observe the
full worker_result + receipt_metadata at the moment status flips to
`needs_human`.

### Mode B: `blocked_auth_failure` (3/13 corpus issues)

**What's happening:** preflight credential check fails before worker
spawn. This is the dominant 25%-of-ticks failure class.

**Why it matters:** the rescue-productization map at
`docs/benchmarks/rescue_productization.json` **already productizes this
class** as `admission_class_corpus_synthesis_v1` + `blocked_auth_failure`,
bound to PR #7225 (corpus-aware dispatch upgrade) + PR #7228 (gating
repair) + PR #7248 (credential-envelope corpus synthesis). All three
PRs are MERGED.

**So why is it still happening?** Either:

- The productization is real but hasn't been re-tested against these
  3 corpus issues since shipping (boss_metrics.jsonl was last modified
  May 16, ~3 days ago; the most recent productization PR #7248 merged
  May 17). The B0 corpus has not been re-run since the credential
  productization landed.
- The productization addresses a different shape of the
  `blocked_auth_failure` than these 3 corpus issues hit.

**To distinguish:** re-run the B0 boss-loop on these 3 issues since
PR #7248 merged. This is bounded — 3 issues, ~10 min wall-clock each
at most, real provider spend ~$1-5.

---

## Why my assessment was partly wrong

The 30-day project assessment (#7373) said:

> The 0.0% headline is the cheapest single thing that, if moved,
> changes the entire shape of the next 30 days.

That's still true. But the assessment characterized the failure as
"the substrate produces zero output," when the actual situation is
"the substrate produces output, but the worker doesn't ship PRs that
close issues." Different failure mode, different fix.

The assessment recommended three responses:

- (a) make the corpus easier
- (b) instrument the rescue path
- (c) replace the proof surface

The diagnostic suggests a fourth, more specific:

- **(d) instrument the `needs_human + adopted_pr` decision point in
  the worker.** The corpus is fine. The auth productization (Mode B)
  has shipped but hasn't been re-tested. The dominant mode (A) is
  fundamentally about why workers bail on bounded tasks.

This is closer to (b) than (a) or (c), but specifically points at the
worker's done-state logic rather than the rescue path generally.

---

## Recommended next moves

In ascending cost:

### Move 1 (free, ~10 min): re-run B0 boss-loop on the 3 auth-failure issues

The credential-envelope productization (PR #7248) merged on May 17.
The boss_metrics.jsonl is stale since May 16. The 3 `blocked_auth_failure`
issues (5789, 5790, 5844) have not been re-attempted since the
productization shipped.

**Action:** dispatch boss-loop with `--issues 5789,5790,5844` and
observe whether the productization actually closes the auth gate.

**Possible outcome:** if 2 of 3 pass now, B0 jumps from 0/13 to 2/13.
Even one closure starts to move the metric. Real provider spend likely
$2-5.

### Move 2 (cheap, ~30 min): instrumented dispatch on ONE Mode-A corpus issue

Pick the smallest Mode-A issue: **#5426 — Add `operator-snapshot`
subcommand to `agent_bridge.py`**. The file already has the
`operator-snapshot` verb (it's referenced in the lane registry).
Adding one more subcommand variant is a 20-line PR.

**Action:** dispatch a single boss-loop tick on #5426 with full
instrumentation:

- Capture `worker_result` JSON at the moment status flips to
  `needs_human`
- Capture the worker's `acceptance_gate` decision (pass/fail and why)
- Capture the deliverable type and the adopted_pr reference
- Capture the worker's wall-clock + token-budget consumption

**Expected outcome:** one of the five Mode-A hypotheses gets confirmed
or eliminated. Whichever hypothesis confirms becomes the actual fix.

### Move 3 (medium, ~2 hours): fix the confirmed Mode-A root cause

Depending on what Move 2 reveals:

- If the worker is timing out on CI → narrow the acceptance gate
  to "PR opened" not "CI green"
- If the worker can't push → fix the lane-registry / worktree
  permission for boss-harvest branches
- If the worker is being cleaned up mid-run → adjust worktree TTL or
  add a "boss-loop-active" lock that autopilot respects
- If the corpus tasks have implicit deps → document them in
  `corpus.json` `known_constraints` and re-test

### Move 4 (cheap, ~30 min): rename `pr_adopted` to surface the gap

The current metric reports `pr_adopted` as "success." This is technically
correct per the `_SUCCESS_OUTCOMES` definition but operationally
misleading — the proxy success rate of 76.9% suggested healthy
autonomous closure when the truth is zero closure.

**Action:** rename `pr_adopted` in scorecards to `needs_human_with_pr_hint`
(or similar), and split the proxy metric to distinguish "PR created"
from "PR adopted." This is a documentation / labeling fix; no code
change.

**Benefit:** the next observer of B0 won't be misled by the 76.9%
proxy. The 0.0% truth rate becomes legible.

---

## What this diagnostic is NOT

- Not a comprehensive boss-loop audit. The worker bail-out logic is
  reconstructed from source-code reading + boss_metrics aggregation,
  not from running an instrumented dispatch. Move 2 is what would
  produce real instrumented data.
- Not a corpus-design critique. The corpus is bounded and reasonable.
  The 13 tasks are not unfair; they are exactly the bounded-autonomy
  shape the proof loop was built to test.
- Not a claim that the proxy metric is wrong. The proxy metric is
  technically correct under its own definition (`_SUCCESS_OUTCOMES`
  includes `pr_adopted`). It just reports a different thing than
  "issues closed by autonomous work."

---

## Operator decision (one of)

The diagnostic ends with a fork. Operator picks:

- **Authorize Move 1** (re-run 3 auth-failure issues since #7248
  shipped). Cheapest, fastest, may produce non-zero in ~10 min.
- **Authorize Move 2** (instrumented Mode-A dispatch on #5426).
  Reveals the actual root cause; informs the real fix.
- **Authorize Move 4** (rename + split scorecard). Cheapest, fixes the
  legibility problem even before the substantive problem.
- **Authorize all three in parallel** if budget permits. Total real
  provider spend ~$5-10.
- **Hold for further review.** The diagnostic is a docs-only artifact;
  it does not require immediate action.

This doc deliberately does not dispatch any worker, mutate any code, or
change any benchmark surface. It is read-only synthesis.

---

## Methodology notes

Evidence sources read:

- `docs/benchmarks/corpus.json` — full content, 13 issues
- `docs/status/generated/benchmark_truth_artifacts/.../latest.json` —
  per-issue truth_state
- `docs/status/generated/benchmark_scorecards/.../latest.json` —
  failure-class distribution + proxy metrics
- `.aragora/overnight/boss_metrics.jsonl` — 420 lines, last
  modified 2026-05-16 (stale)
- `aragora/swarm/boss_loop.py` lines 3585-3603, 800, 3935-4054
- `aragora/swarm/supervisor.py` lines 2474-2481
- `aragora/swarm/terminal_truth.py` lines 116, 278, 554, 649, 679, 685
- `docs/benchmarks/rescue_productization.json` — productization entries
- `gh issue view` + `gh pr list --search "in:body N"` for all 13
  corpus issues

Not read (deferred / would need Move 2 or further investigation):

- The actual `worker_result` JSON for a recent corpus run
- Acceptance-gate decision logic
- WorkerLauncher / CredentialEnvelope internals
- Per-worker wall-clock + token-budget records

Time used: ~30 minutes of read-only investigation. The doc itself is
~700 lines.

Honesty notes:

- Mode-A root-cause hypotheses are speculative; Move 2 confirms or
  refutes them. Do not act on a hypothesis without that confirmation.
- The 76.9% proxy rate is correctly labeled as success per the
  internal metric definition. Calling it "illusory" is a phrasing
  choice — the metric isn't wrong, it just doesn't mean what casual
  readers might assume.
- This diagnostic is one read pass; deeper investigation would
  involve actually running a worker. That's Move 2.

---

## Addendum 2026-05-19 — Move 1 attempt: blocked on stale runner registry

**TL;DR.** I tried to execute Move 1 (re-run boss-loop on the 3
Mode-B auth-failure issues #5789, #5790, #5844 now that #7248 shipped).
The dry-run blocked before reaching credential resolution because the
**entire registered runner fleet has stale heartbeats**. This is a third
B0 blocker, distinct from `pr_adopted` mislabeling (Move 4) and the
credential gate that #7248 productized.

### What I ran

```
aragora swarm boss-loop \
  --boss-issue-list "5789,5790,5844" \
  --max-ticks 3 --no-loop --dry-run --json
```

### What the dispatch returned

```json
"selected_issue": null,
"worker_status": "blocked",
"stop_reason": "no_fresh_runner",
"needs_human_reasons": ["No fresh runner: no_fresh_registered_runners"],
"next_actions": [
  "Re-register or refresh the Codex runner before resuming the Boss loop.",
  "Blocked reason: no_fresh_registered_runners"
]
```

The selection-basis trace lists ~22 rejected runners (claude-runner-*
and codex-runner-*). Their selection-basis includes
`freshness_status=fresh, availability=available, auth_mode verified` as
the **required** criteria — i.e. the gate is failing the freshness
check, not the auth-mode check that #7248 fixed.

### How stale

`aragora swarm status --json` shows 2,173 runner heartbeat records.
The most recent five are dated **2026-05-14T17:45:31Z** (5 days ago);
the next-most-recent group is dated **2026-04-13T16:57:42Z** (5 weeks
ago). No runner has refreshed in the last 5 days.

### Why this matters for the 30-day assessment

The assessment's Section A/B/C synthesis assumed that **#7248 unblocked
the credential class**. That is still true at the *gate level* — the
sanitization productization is real. But it is **not yet sufficient to
re-run B0**, because the registered runner fleet has aged out
independently. The dispatch path's "is there a runner available" check
fires before the credential gate does. So:

- `blocked_auth_failure` (7/28 ticks): productized in #7248, but
  **un-testable until runners are fresh again**
- `blocked_not_dispatch_bounded` (8/28 ticks): productized in #7225
  — also un-testable for the same reason
- The Mode-A bail pattern (`pr_adopted` for 10/13 issues): can only be
  reproduced once the dispatch substrate is back up

In other words, **B0 cannot be re-measured until the runner registry
is refreshed**, independent of any productization that has shipped
since the last measurement on 2026-05-16.

### Why I am stopping here rather than reviving runners

1. Reviving runners is a separate operational action with its own
   scope (deciding which runners to refresh, in which user/workspace
   context, on which host, with what auth-mode). It was not in the
   Move 1 brief.
2. There is parallel in-flight work that may already be solving this:
   the worktree `codex/b0-proof-loop-freshness-refresh-20260519`
   exists on this machine. Colliding with that work would waste both
   agents' tokens.
3. The user's standing instruction limits autonomous mutations of
   production substrate.

### Recommended next move

A short docs-only ticket / PR that names this blocker explicitly and
points at whoever is doing the freshness-refresh work
(`codex/b0-proof-loop-freshness-refresh-20260519`) as the canonical
owner. Once runners are fresh, Move 1 becomes a 10-minute exercise:
re-run the boss-loop dry-run, then the real dispatch on the 3
auth-failure issues, then diff `.aragora/overnight/boss_metrics.jsonl`
to confirm that `blocked_auth_failure` drops to zero for them.

### Files / commands used

- `aragora swarm boss-loop --dry-run --json` — primary signal
- `aragora swarm status --json` — heartbeat ages
- `.aragora/overnight/boss_metrics.jsonl` — 420 lines, last modified
  2026-05-16T14:22Z (unchanged for 3 days, consistent with no
  recent dispatch activity)
- `git worktree list` — surfaced the parallel codex freshness work
- `aragora.config.secrets.get_secret('ANTHROPIC_API_KEY')` —
  returned None; expected because dispatcher resolves credentials
  per-runner-binding, not from the parent process env
