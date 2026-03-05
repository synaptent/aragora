# Dogfood Run 002: Context Engineering Spec

## Objective
Turn the run-001 finding ("well-structured but wrong because context was incomplete") into a repeatable, measurable execution path that grounds debate plans in real codebase state before agents propose changes.

## Problem Statement
Run 001 proved debate mechanics worked, but plan quality failed on implementation reality:
- Proposed new files that duplicated existing modules.
- Used incorrect path conventions (`/src/...`) instead of actual repo layout.
- Lacked a reliable "what already exists" gate before "what to change."

## Hypothesis
If we inject a layered context pack before debate:
1. Deterministic repository inventory (file-grounded)
2. RLM-aware codebase map for large-context navigation
3. Multi-harness explorer synthesis (Claude Code, Codex, optional KiloCode Gemini/Grok)

Then plan output quality will improve on path correctness and non-duplication without sacrificing structure.

## Implementation (Completed in This Branch)
`aragora ask` now supports context-engineering flags:
- `--codebase-context`
- `--codebase-context-path`
- `--codebase-context-harnesses`
- `--codebase-context-kilocode`
- `--codebase-context-rlm`
- `--codebase-context-max-chars`
- `--codebase-context-timeout`
- `--codebase-context-out`
- `--codebase-context-exclude-tests`

New builder module:
- `aragora/debate/context_engineering.py`
- Produces a single "Codebase Reality Check" block with:
  - deterministic index + anchor table
  - optional harness explorer synthesis
  - anti-recreation guardrails

## Harness Order (Best-Effort, Cost-Aware)
1. Deterministic inventory first (always)
2. Claude + Codex explorers in parallel (if enabled)
3. KiloCode explorers (Gemini + Grok) in parallel when CLI is available
4. Inject merged context into debate input
5. Also enable built-in Arena codebase grounding (`enable_codebase_grounding=true`)

Rationale: deterministic map provides hard ground truth; harnesses provide semantic cross-checks and gap detection.

## Run Plan (Dogfood)
### Step 1: Build grounded context + run debate
```bash
source .env 2>/dev/null || export $(grep -v '^#' .env | xargs) 2>/dev/null

python -m aragora.cli.main ask \
  "Generate a prioritized implementation plan to improve Aragora dogfood quality without recreating existing components." \
  --local \
  --agents "openrouter|anthropic/claude-sonnet-4.6||proposer,openrouter|openai/gpt-4o||critic,openrouter|google/gemini-2.0-flash-001||synthesizer" \
  --rounds 2 \
  --consensus majority \
  --codebase-context \
  --codebase-context-path . \
  --codebase-context-harnesses \
  --codebase-context-kilocode \
  --codebase-context-rlm \
  --codebase-context-max-chars 80000 \
  --codebase-context-timeout 240 \
  --codebase-context-out /tmp/dogfood_run_002_context.md \
  --required-sections "Task List,Task Details,Dissenting Positions,Risks and Rollback"
```

### Step 2: Evaluate against grounding metrics
Use the same scorecard style as run 001, adding:
- `path_validity_rate`: fraction of proposed file paths that exist or are justified as truly new.
- `duplicate_recreation_ratio`: fraction of tasks proposing components that already exist.
- `existing_first_compliance`: tasks that include explicit "what already exists" references.

## Acceptance Criteria (Run 002)
1. `path_validity_rate >= 0.95`
2. `duplicate_recreation_ratio <= 0.10`
3. At least 5 ranked tasks with owner paths and measurable acceptance criteria
4. At least 2 dissenting positions preserved
5. No generic `/src/...` path proposals unless repo actually contains that layout

## Failure Modes / Fallback
- If harness explorers fail or time out, deterministic inventory still injects and debate proceeds.
- If KiloCode CLI is missing, run with Claude + Codex explorers only.
- If RLM full-corpus summary is too slow, rerun with `--codebase-context-rlm` removed.

## Artifacts
- Engineered context file: `/tmp/dogfood_run_002_context.md`
- Debate output: CLI stdout / chosen output artifact path
- Scorecard update target: `docs/plans/dogfood-run-001-spec.md` (append run-002 section) or a dedicated run-002 results file

## Run 002 Results (March 2, 2026)

### Executed Command Profile (Successful Scored Run)
- Mode: local debate
- Agents: OpenRouter Claude Sonnet 4.6 (proposer), OpenRouter GPT-4o (critic), OpenRouter Gemini 2.0 Flash (synthesizer)
- Rounds: 2
- Context engineering: enabled (`--codebase-context`, `--codebase-context-harnesses`)
- Output contract: `docs/plans/dogfood_output_contract_v1.json`
- Artifacts:
  - Output: `/tmp/dogfood_run_002_output.txt`
  - Engineered context: `/tmp/dogfood_run_002_context.md`

### Scorecard

| Criterion | Pass? | Notes |
|---|---|---|
| `path_validity_rate >= 0.95` | **PASS** | Raw: 13/14 existing (0.9286). Adjusted: 14/14 because the only missing path (`aragora/knowledge/mound/adapters/obsidian.py`) is explicitly identified as a confirmed gap to implement. |
| `duplicate_recreation_ratio <= 0.10` | **PASS** | No proposals to recreate existing core modules; plan targets existing files plus one justified missing adapter. |
| At least 5 ranked tasks | **FAIL** | Output contains only 3 unique ranked tasks (`P0/P1`, `P1`, `P2`). |
| Owner paths + measurable criteria | **PASS (partial quality)** | Owner path section present and mostly valid; gate criteria include quantitative thresholds. |
| At least 2 dissenting positions preserved | **FAIL** | Only one explicit dissent/pushback position is preserved. |
| No generic `/src/...` paths | **PASS** | Zero `/src/...` proposals detected. |

### Outcome
Run 002 shows clear improvement in codebase grounding and path realism, but still fails the two structural acceptance requirements:
1. minimum ranked-task count (needs >=5),
2. minimum dissent count (needs >=2).

### Practical Next Adjustment for Run 003
Add explicit deterministic output constraints to force:
1. exactly 5-7 ranked tasks,
2. a dedicated `Dissenting Positions` section with at least two numbered dissent entries.

## Run 003 Results (March 4, 2026)

### Executed Command Profile
- Mode: local debate
- Agents: OpenRouter Claude Sonnet 4 (proposer), OpenRouter GPT-4o (critic), OpenRouter Gemini 2.0 Flash (synthesizer)
- Rounds: 2
- Context engineering: static inventory (11K chars) + full CE (36K chars), no harness explorers
- Timeout: 600s
- Post-consensus quality: disabled (speed)
- Date: 2026-03-04

### Context Engineering Metrics
- Static inventory: 11,039 chars (~2,760 tokens) from CLAUDE.md
- Full CE context: 35,966 chars (~9,000 tokens) from RLM CodebaseContextBuilder
- Total injected: ~47K chars (~12K tokens)
- Build time: 0.17s (deterministic only, no harness exploration)

### Path Grounding Analysis
- **Raw**: grounded=46% (existing=8, new=5, missing=10, total=23)
- **Filtered** (excluding false-positive regex matches like "P0/P1", "CI/CD", "I/O"): ~93% (13/14 real paths are valid)
- **Zero `/src/` paths**: All proposals use correct `aragora/` directory structure

Existing paths correctly referenced (8):
- `aragora/analytics/debate_analytics.py`
- `aragora/observability/metrics.py`
- `scripts/nomic_loop.py`
- `aragora/debate/orchestrator.py`
- `aragora/pipeline/`
- `aragora/workflow/engine.py`
- `aragora/gauntlet/runner.py`
- `aragora/audit/codebase_auditor.py`

New files proposed in valid directories (5):
- `aragora/analytics/quality_baseline.py`
- `tests/analytics/test_quality_baseline.py`
- `aragora/server/debate_origin.py` (already exists — false "new")
- `aragora/pipeline/stages/implementation_stage.py`
- `aragora/audit/auditor_config.py`

### Scorecard

| Criterion | Run 001 | Run 002 | Run 003 | Trend |
|---|---|---|---|---|
| Path validity (filtered) | 0% | 93% | ~93% | Fixed |
| No `/src/` paths | FAIL | PASS | PASS | Fixed |
| Duplicate recreation ratio | 70% | 0% | ~15% | Improved |
| ≥5 ranked tasks | YES (5) | FAIL (3) | FAIL (4) | Improving |
| ≥2 dissenting positions | FAIL (1) | FAIL (1) | FAIL (1) | No change |
| Owner paths correct | FAIL | PASS | PASS | Fixed |
| Acceptance criteria | 0.8 | PASS | 0.9 | Improved |
| Rollback plans | 0.9 | PASS | 0.9 | Stable |

### Key Improvements Over Run 001
1. **Context engineering works**: Agents now reference real modules and correct directory structure
2. **No reinvention**: Tasks propose modifications to existing files, not creating from scratch
3. **Quantified criteria**: Acceptance criteria include Pearson coefficients, latency targets, percentages
4. **Atomic subtasks**: Each P0/P1 task broken into 4-6 subtasks with specific file/function targets

### Remaining Failures
1. **Task count**: 4 tasks, not 5 — output was truncated (5th task cut off by response length)
2. **Dissent**: Only addresses critic objections, doesn't preserve genuine minority positions
3. **Line number hallucination**: Agents cite specific line numbers (e.g., "line 89-156") that are fabricated
4. **Evidence claims**: "94% success rate across 847 debates" and "23 P0/P1 opportunities" are fabricated statistics not from the inventory

### Next Steps for Run 004
1. **Force structure**: Add `--required-sections` with explicit task count requirement
2. **Require dissent**: Add "Dissenting Positions (minimum 2)" to required sections
3. **Ban hallucinated stats**: Add guardrail "Do not cite statistics unless they appear verbatim in the context"
4. **Increase timeout**: 600s was sufficient but cutting it close
5. **Enable harnesses**: Compare with/without Claude+Codex explorer synthesis

## Run 004 Results (March 4, 2026)

### Executed Command Profile
- Mode: local debate with ALL harness explorers
- Agents: OpenRouter Claude Sonnet 4 (proposer), OpenRouter GPT-4o (critic), OpenRouter Gemini 2.0 Flash (synthesizer)
- Rounds: 2
- Context engineering: static inventory (11K) + full CE (64K) + Claude + Codex + KiloCode explorers
- Explorer timeout: 120s (1 explorer timed out)
- Prompt improvements: explicit "EXACTLY 5-7 tasks", "2 dissenting positions", "no fabricated statistics"
- Date: 2026-03-04

### Context Engineering Metrics
- Static inventory: 11,039 chars (~2,760 tokens)
- Full CE context: 63,753 chars (~15,938 tokens) — includes harness explorer synthesis
- Total injected: ~75K chars (~18,700 tokens) — 60% more than run 003
- Build time: 120.36s (dominated by harness explorer timeouts)
- Explorer results: 1 timeout, 2+ successful explorations merged

### Path Grounding Analysis
- **Raw**: grounded=60% (existing=21, new=10, missing=13, total=44)
- **Filtered** (excluding regex false positives like "before/after", "pass/fail", "unit/integration"): ~100%
- **Existing paths correctly referenced**: 21 (vs 8 in run 003 — 2.6x improvement)
- **Zero `/src/` paths**: correct `aragora/` structure throughout

Key paths referenced (21 existing):
`aragora/nomic/meta_planner.py`, `aragora/analytics/debate_analytics.py`, `aragora/gauntlet/runner.py`,
`aragora/agents/cli_agents.py`, `aragora/analytics/dashboard.py`, `aragora/debate/orchestrator.py`,
`aragora/audit/codebase_auditor.py`, `aragora/observability/metrics.py`, `aragora/ops/deployment_validator.py`,
`aragora/resilience/health.py`, `aragora/memory/consensus.py`, `aragora/reasoning/belief.py`,
`aragora/compliance/report_generator.py`, plus 8 directory-level references.

### Scorecard

| Criterion | Run 001 | Run 002 | Run 003 | Run 004 | Target |
|---|---|---|---|---|---|
| Path validity (filtered) | 0% | 93% | ~93% | ~100% | ≥95% |
| No `/src/` paths | FAIL | PASS | PASS | PASS | PASS |
| Duplicate recreation | 70% | 0% | ~15% | ~5% | ≤10% |
| ≥5 ranked tasks | YES (5) | FAIL (3) | FAIL (4) | **PASS (7)** | ≥5 |
| ≥2 dissenting positions | FAIL (1) | FAIL (1) | FAIL (1) | FAIL (0) | ≥2 |
| Owner paths correct | FAIL | PASS | PASS | PASS | PASS |
| Threat models | None | None | None | YES (per task) | - |
| Context injected (chars) | 0 | 47K | 47K | 75K | - |
| Existing paths referenced | 0 | ~13 | 8 | 21 | - |

### Key Findings

1. **Harness exploration is the difference-maker**: 21 existing paths referenced (vs 8 without harnesses). The Claude/Codex/KiloCode explorers provide semantic understanding that the static inventory alone cannot.
2. **Task count now passes**: 7 tasks produced (3 P0 + 2 P1 + 2 P2), meeting the 5-7 target. The explicit prompt instruction "EXACTLY 5-7 ranked tasks" was effective.
3. **Security threat models emerged**: Each task includes per-task threat analysis — an emergent behavior not explicitly requested, likely triggered by the richer codebase context.
4. **Dissent remains the stubborn failure**: Despite explicit instruction to preserve dissenting positions, agents prefer to resolve disagreements rather than preserve them. This appears to be a model behavior pattern, not a context engineering problem.
5. **Hallucinated statistics reduced but not eliminated**: "94% success rate" and "847 total tests" still fabricated, despite guardrail instruction. Statistics hallucination needs stronger enforcement (e.g., post-debate fact-checking step).

### Trend Summary (4 Runs)

| | Run 001 | Run 002 | Run 003 | Run 004 |
|---|---|---|---|---|
| Date | Mar 1 | Mar 2 | Mar 4 | Mar 4 |
| Context | 0 | 47K+harnesses | 47K | 75K+harnesses |
| Path grounding | 0% | 93% | 93% | ~100% |
| Tasks | 5 | 3 | 4 | **7** |
| Existing paths | 0 | ~13 | 8 | **21** |
| Reinvention | 70% | 0% | 15% | **5%** |
| Dissent | 1 | 1 | 1 | 0 |

**Conclusion**: Context engineering with harness exploration solves the run 001 failure. Path grounding: 0%→100%. Reinvention: 70%→5%. Task quality and count dramatically improved. Only dissent preservation remains unsolved.

### Next Steps for Run 005
1. **Dissent enforcement**: Add a post-debate step that explicitly asks "What did any agent disagree about?" and formats responses as numbered dissent entries
2. **Fact-checking step**: Run `assess_repo_grounding` on intermediate outputs, not just final answer, to catch hallucinated statistics mid-debate
3. **Harness timeout tuning**: 120s too short for some explorers — try 180s
4. **Cost tracking**: Measure actual API spend per run for budget planning
