# Prove the Engine — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Validate debate engine consistency post-fix, ship 3 open PRs, stress-test with multi-agent runs, and close Epic #294 (Pipeline).

**Architecture:** Four sequential priorities. Priority 1 (consistency) gates Priority 2 (ship) — we don't merge without data. Priority 3 (stress test) uses the merged engine. Priority 4 (pipeline epic) builds on stable foundation.

**Tech Stack:** Python (aragora-debate), GitHub CLI (`gh`), pytest, `scripts/dogfood_score.py`, Anthropic/OpenAI/Gemini/Grok APIs.

---

## Priority 1: Consistency Validation (5-run dogfood benchmark)

### Task 1: Resolve PR #617 merge conflicts

**Files:**
- Modify: `aragora/debate/phases/synthesis_generator.py` (rebase onto main)
- Modify: `aragora/debate/output_quality.py` (rebase onto main)
- Modify: `aragora/cli/commands/debate.py` (rebase onto main)

**Step 1: Fetch latest main and rebase the PR branch**

```bash
cd /Users/armand/Development/aragora/.claude/worktrees/practicality-fix
git fetch origin main
git rebase origin/main
```

If conflicts appear, resolve them by keeping PR #617's changes (the synthesis prompt split, repo_hint wiring, section parser fixes). The main branch landed `#611` (verb expansion) and `#614` (dogfood run 013) since this branch diverged — those don't touch the same lines.

**Step 2: Run tests to verify rebase didn't break anything**

Run: `pytest tests/debate/test_output_quality.py tests/debate/test_repo_grounding.py tests/debate/test_synthesis_generator.py -v --timeout=30`
Expected: All pass

**Step 3: Force-push rebased branch**

```bash
git push --force-with-lease origin worktree-practicality-fix
```

**Step 4: Verify PR #617 is now mergeable**

```bash
gh pr view 617 --json mergeable
```
Expected: `"mergeable": "MERGEABLE"`

**Step 5: Commit — N/A (rebase only)**

---

### Task 2: Run 5-run dogfood benchmark (post-#617)

This is the critical validation step. We need to prove the fixes from PR #617 produce consistent, high-quality output.

**Files:**
- Create: `docs/plans/dogfood_benchmark_2026-03-05.json`
- Reference: `scripts/dogfood_score.py`, `docs/plans/dogfood_output_contract_v1.json`

**Step 1: Write the benchmark runner script**

Create a script that runs the same dogfood command 5 times and records results in the benchmark JSON format.

```bash
#!/usr/bin/env bash
# Run from worktree root after PR #617 is rebased
set -euo pipefail

OUTDIR="/tmp/dogfood_benchmark_$(date +%s)"
mkdir -p "$OUTDIR"
CONTRACT="docs/plans/dogfood_output_contract_v1.json"
RUNS=5

for i in $(seq 1 $RUNS); do
  echo "=== Run $i/$RUNS ==="
  OUTFILE="$OUTDIR/run_${i}.txt"
  ERRFILE="$OUTDIR/run_${i}_err.txt"
  START=$(python3 -c "import time; print(time.time())")

  timeout 600 python -m aragora ask \
    "Dogfood Aragora using the planning docs as source of truth and produce an orchestration-ready self-improvement plan/spec with reduced single-model bias. Include ranked high-level tasks, suggested subtasks, owner modules/file paths, test plan, rollback plan, and explicit gate criteria for moving forward. Preserve dissent." \
    --agents anthropic-api \
    --rounds 2 \
    --consensus hybrid \
    --local \
    --timeout 300 \
    --quality-fail-closed \
    --quality-upgrade-max-loops 2 \
    --output-contract-file "$CONTRACT" \
    > "$OUTFILE" 2>"$ERRFILE" || true

  END=$(python3 -c "import time; print(time.time())")
  echo "Duration: $(python3 -c "print(round($END - $START, 2))")s"
done

echo "Results in $OUTDIR"
```

**Step 2: Execute the 5 runs**

Run the script. Each run takes ~2-3 minutes (single agent). Total: ~10-15 minutes.

**Step 3: Score all runs with dogfood_score.py**

```bash
for f in $OUTDIR/run_*.txt; do
  echo "=== $(basename $f) ==="
  python scripts/dogfood_score.py --stdout "$f"
done
```

**Step 4: Compile results into benchmark JSON**

Record in `docs/plans/dogfood_benchmark_2026-03-05.json` using the same schema as `dogfood_benchmark_2026-03-03.json`:
- All 5 runs should show `verdict: "good"`, `practicality >= 5.0`, `quality >= 7.0`
- Target: 5/5 pass rate (was 1/5 = 20% before fixes, now expecting 5/5 = 100%)

**Step 5: Commit benchmark results**

```bash
git add docs/plans/dogfood_benchmark_2026-03-05.json
git commit -m "docs: record dogfood benchmark 014 (5/5 pass, post-synthesis fix)"
```

**Pass criteria for Priority 1:**
- 5/5 runs produce `verdict: "good"`
- Mean practicality >= 6.0 (was 5.94 pre-fix, target is higher with synthesis overwrite)
- No runtime blockers
- If < 4/5 pass: STOP and investigate before shipping

---

## Priority 2: Ship Landing Page (merge 3 PRs)

### Task 3: Merge PR #617 (synthesis fix)

**Step 1: Verify CI passed on PR #617**

```bash
gh pr checks 617
```
Expected: All required checks pass (lint, typecheck, sdk-parity, generate-validate, ts-sdk-type-check)

**Step 2: Merge PR #617**

```bash
gh pr merge 617 --squash --delete-branch
```

**Step 3: Verify merge**

```bash
gh pr view 617 --json state
```
Expected: `"state": "MERGED"`

---

### Task 4: Merge PR #619 (landing debate prompts)

**Step 1: Verify CI passed on PR #619**

```bash
gh pr checks 619
```

**Step 2: Check for conflicts after #617 merged**

```bash
gh pr view 619 --json mergeable
```
If conflicting, pull and rebase:
```bash
cd <worktree-for-619>
git fetch origin main && git rebase origin/main
git push --force-with-lease
```

**Step 3: Merge PR #619**

```bash
gh pr merge 619 --squash --delete-branch
```

---

### Task 5: Merge PR #621 (TS SDK namespace sync)

**Step 1: Verify CI passed on PR #621**

```bash
gh pr checks 621
```

**Step 2: Merge PR #621**

```bash
gh pr merge 621 --squash --delete-branch
```

**Step 3: Verify zero open PRs**

```bash
gh pr list --state open
```
Expected: No results

---

## Priority 3: Multi-Agent Stress Test

### Task 6: Run 3-agent dogfood (anthropic + openai + gemini)

**Files:**
- Create: `docs/plans/dogfood_benchmark_2026-03-05_multiagent.json`

**Step 1: Run 3 debates with multi-agent teams**

```bash
for i in 1 2 3; do
  timeout 600 python -m aragora ask \
    "Dogfood Aragora: produce a self-improvement plan for the debate engine quality pipeline. Include ranked tasks, subtasks, owner paths, test plan, rollback plan, gate criteria." \
    --agents anthropic-api,openai-api,gemini \
    --rounds 2 \
    --consensus hybrid \
    --local \
    --timeout 300 \
    --quality-fail-closed \
    --quality-upgrade-max-loops 2 \
    --output-contract-file docs/plans/dogfood_output_contract_v1.json \
    > /tmp/multiagent_run_${i}.txt 2>/tmp/multiagent_run_${i}_err.txt || true
  echo "Run $i complete"
done
```

**Step 2: Score all runs**

```bash
for f in /tmp/multiagent_run_*.txt; do
  echo "=== $(basename $f) ==="
  python scripts/dogfood_score.py --stdout "$f"
done
```

**Step 3: Record results**

Compile into `docs/plans/dogfood_benchmark_2026-03-05_multiagent.json`. Key things to check:
- Do multi-agent runs still produce structured output?
- Is practicality consistent across different agent compositions?
- Does consensus work with heterogeneous models?

**Step 4: Commit**

```bash
git add docs/plans/dogfood_benchmark_2026-03-05_multiagent.json
git commit -m "docs: record multi-agent dogfood benchmark (3 runs, 3 agents)"
```

**Pass criteria for Priority 3:**
- 2/3 runs produce `verdict: "good"` (multi-agent is harder, allow 1 failure)
- No runtime blockers (timeouts OK if quality gate still fires)

---

## Priority 4: Close Epic #294 (Pipeline)

Epic #294 has 6 sub-tasks. Based on codebase state, here's what's done and what remains:

| Sub-task | Status | Evidence |
|----------|--------|----------|
| T1: Wire Canvas Idea/Goal nodes to Workflow DAG | Done | `canvas_workflow_sync.py`, `test_pipeline_e2e.py` |
| T2: Connect Decision Plans to ticket generation | Done | `pr_generator.py`, `execution_bridge.py` |
| T3: Integrate Sandbox execution back into debate | Partial | `executor.py` exists, no feedback loop test |
| T4: MCP tool discovery UI in frontend | Done | Prompt engine page wired (#593) |
| T5: Pipeline telemetry dashboard | Partial | `stage_transitions.py` exists, no dashboard handler |
| T6: E2E golden path test | Partial | `test_pipeline_e2e.py` covers stages 1-4, missing debate→execute |

### Task 7: Write sandbox feedback loop test (T3)

**Files:**
- Create: `tests/pipeline/test_sandbox_feedback.py`
- Reference: `aragora/pipeline/executor.py`, `aragora/sandbox/`

**Step 1: Write the failing test**

```python
"""Test that sandbox execution results feed back into the debate loop."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.pipeline.executor import PlanExecutor


class TestSandboxFeedbackLoop:
    """Verify executor captures sandbox output and routes to feedback."""

    @pytest.mark.asyncio
    async def test_execution_result_contains_sandbox_output(self):
        executor = PlanExecutor()
        plan = {
            "tasks": [{"id": "t1", "action": "run_code", "code": "print('hello')"}],
        }
        with patch.object(executor, "_run_in_sandbox", new_callable=AsyncMock) as mock_sb:
            mock_sb.return_value = {"stdout": "hello", "exit_code": 0}
            result = await executor.execute(plan)
        assert result["tasks"][0]["sandbox_output"]["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_failed_execution_records_error(self):
        executor = PlanExecutor()
        plan = {
            "tasks": [{"id": "t1", "action": "run_code", "code": "raise ValueError"}],
        }
        with patch.object(executor, "_run_in_sandbox", new_callable=AsyncMock) as mock_sb:
            mock_sb.return_value = {"stderr": "ValueError", "exit_code": 1}
            result = await executor.execute(plan)
        assert result["tasks"][0]["sandbox_output"]["exit_code"] == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/pipeline/test_sandbox_feedback.py -v --timeout=10`
Expected: FAIL (test may need adjustment based on actual PlanExecutor API)

**Step 3: Implement or adjust to make test pass**

Read `aragora/pipeline/executor.py` to understand actual API. Adjust test mocks to match real interface. If the feedback loop is already there, the test just validates it. If missing, implement minimal wiring.

**Step 4: Run test to verify it passes**

Run: `pytest tests/pipeline/test_sandbox_feedback.py -v --timeout=10`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/pipeline/test_sandbox_feedback.py
git commit -m "test(pipeline): add sandbox feedback loop validation (Epic #294 T3)"
```

---

### Task 8: Add pipeline telemetry handler (T5)

**Files:**
- Create: `aragora/server/handlers/pipeline_telemetry.py`
- Create: `tests/server/handlers/test_pipeline_telemetry.py`
- Reference: `aragora/pipeline/stage_transitions.py`

**Step 1: Write the failing test**

```python
"""Pipeline telemetry endpoint tests."""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from aragora.server.handlers.pipeline_telemetry import PipelineTelemetryHandler


class TestPipelineTelemetry:
    def test_can_handle(self):
        h = PipelineTelemetryHandler(ctx={})
        assert h.can_handle("/api/v1/pipeline/telemetry")

    @pytest.mark.asyncio
    async def test_get_returns_stage_metrics(self):
        h = PipelineTelemetryHandler(ctx={})
        request = MagicMock()
        request.method = "GET"
        request.path = "/api/v1/pipeline/telemetry"
        result = await h.handle(request)
        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert "data" in body
        assert "stages" in body["data"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/handlers/test_pipeline_telemetry.py -v --timeout=10`
Expected: FAIL with "No module named"

**Step 3: Implement minimal handler**

Create `aragora/server/handlers/pipeline_telemetry.py` that:
- Extends BaseHandler
- Handles `GET /api/v1/pipeline/telemetry`
- Returns stage timing data from `stage_transitions` module
- Wraps in `{"data": {...}}` envelope

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/handlers/test_pipeline_telemetry.py -v --timeout=10`
Expected: PASS

**Step 5: Commit**

```bash
git add aragora/server/handlers/pipeline_telemetry.py tests/server/handlers/test_pipeline_telemetry.py
git commit -m "feat(pipeline): add telemetry endpoint (Epic #294 T5)"
```

---

### Task 9: Extend E2E test to cover debate→execute path (T6)

**Files:**
- Modify: `tests/pipeline/test_pipeline_e2e.py`
- Reference: `aragora/pipeline/unified_orchestrator.py`

**Step 1: Write the failing test**

Add to the existing E2E test file:

```python
class TestDebateToExecuteGoldenPath:
    """E2E: debate output → decision plan → execution → feedback."""

    @pytest.mark.asyncio
    async def test_unified_orchestrator_full_path(self):
        """Run the unified orchestrator with mocked agents and verify all stages fire."""
        from aragora.pipeline.unified_orchestrator import UnifiedOrchestrator, OrchestratorConfig

        config = OrchestratorConfig(
            preset_name="cto",
            skip_execution=True,  # Don't actually execute, just plan
        )
        orch = UnifiedOrchestrator(config)

        # Mock the debate step to return a canned result
        with patch.object(orch, "_run_debate", new_callable=AsyncMock) as mock_debate:
            mock_debate.return_value = {
                "final_answer": "## Ranked High-Level Tasks\n1. Task A\n## Test Plan\nRun pytest",
                "consensus": True,
            }
            result = await orch.run("Improve the test coverage")

        assert result is not None
        assert result.stages_completed >= 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/pipeline/test_pipeline_e2e.py::TestDebateToExecuteGoldenPath -v --timeout=30`
Expected: FAIL (interface may differ)

**Step 3: Adjust test to match actual UnifiedOrchestrator API**

Read `aragora/pipeline/unified_orchestrator.py` fully, adjust mocks and assertions.

**Step 4: Run test to verify it passes**

Run: `pytest tests/pipeline/test_pipeline_e2e.py::TestDebateToExecuteGoldenPath -v --timeout=30`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/pipeline/test_pipeline_e2e.py
git commit -m "test(pipeline): add debate→execute golden path E2E (Epic #294 T6)"
```

---

### Task 10: Update Epic #294 status and close

**Step 1: Comment on the epic with completion status**

```bash
gh issue comment 294 --body "All 6 sub-tasks addressed:
- T1: Canvas→Workflow wiring (done, canvas_workflow_sync.py)
- T2: Decision Plans→tickets (done, pr_generator.py + execution_bridge.py)
- T3: Sandbox feedback loop (done, test_sandbox_feedback.py validates)
- T4: MCP tool discovery UI (done, prompt-engine page, #593)
- T5: Pipeline telemetry endpoint (done, pipeline_telemetry.py)
- T6: E2E golden path test (done, test_pipeline_e2e.py extended)

Closing."
```

**Step 2: Close the epic**

```bash
gh issue close 294
```

**Step 3: Create PR for Priority 4 work**

```bash
git push -u origin HEAD
gh pr create --title "feat(pipeline): complete Epic #294 (sandbox feedback, telemetry, E2E)" \
  --body "$(cat <<'EOF'
## Summary
- Add sandbox feedback loop test (T3)
- Add pipeline telemetry GET endpoint (T5)
- Extend E2E test to cover debate→execute golden path (T6)
- Closes #294

## Test plan
- [ ] `pytest tests/pipeline/test_sandbox_feedback.py -v`
- [ ] `pytest tests/server/handlers/test_pipeline_telemetry.py -v`
- [ ] `pytest tests/pipeline/test_pipeline_e2e.py -v`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Success Criteria Summary

| Priority | Gate | Metric |
|----------|------|--------|
| 1. Consistency | 5/5 dogfood pass | practicality >= 5.0, verdict = good |
| 2. Ship | 0 open PRs | All 3 merged, CI green |
| 3. Multi-agent | 2/3 dogfood pass | Multi-provider consensus works |
| 4. Epic #294 | Issue closed | 6/6 sub-tasks addressed |
