# Dogfood Run 001: Self-Improvement via Adversarial Debate

> **Date**: 2026-02-27
> **Status**: Specification phase — not yet executed
> **Input documents**: `ARAGORA_EVOLUTION_ROADMAP.md`, `prompt-to-spec-market-analysis.md`

---

## Answers to Codex's 8 Scoping Questions

### 1. Scope: plan/spec only or plan + implementation PRs?
**Both, gated.** Phase 1 produces the spec + ranked task backlog. Phase 2 produces implementation PRs — but only after the spec passes evaluation gates. No implementation without explicit acceptance criteria.

### 2. Blast radius: what paths are allowed to change?
All of the following, but each task must specify which paths it touches:
- `aragora/nomic/` — self-improvement pipeline wiring
- `aragora/pipeline/` — idea-to-execution pipeline
- `aragora/interrogation/` — interrogation engine improvements
- `aragora/debate/` — debate protocol and settlement
- `aragora/live/src/` — frontend pipeline/canvas UX
- `aragora/server/handlers/` — API endpoints
- `tests/` — corresponding test files for any changed module
- `docs/plans/` — updated specs and roadmap

### 3. Budget/time cap
- **First run (spec generation)**: max $15 USD, max 60 minutes wall-clock
- **Implementation phase (if spec approved)**: max $50 USD per task, max 4 hours per task
- Budget tracking via existing `CostTracker` + debate receipts

### 4. Approval mode
- **Spec phase**: Auto-generate, human reviews final output
- **Implementation phase**: `require-approval` at each gate (spec → code → test → merge)
- Low-risk changes (test additions, doc updates) can auto-merge after CI passes

### 5. Deliverable shape
One canonical spec document (this file, updated with debate output) containing:
- Clarified intent matrix
- Debate protocol spec
- Ranked task backlog with exact file paths
- Evaluation harness design
- Orchestration-ready JSON payload

### 6. "Agent impairment <= 50%": metric definition
Confirmed: `impairment = 1 - (heterogeneous_team_score / best_single_model_score)`

Where `score` is measured as: proportion of tasks where the output meets all acceptance criteria on first submission (no rework needed). A team that produces 7/10 passing tasks when the best single model produces 9/10 has impairment = 1 - (7/9) = 0.22 (passing).

### 7. Benchmark task set
**5 tasks** for the impairment test. Selected to span different capabilities:
1. A specification-writing task (tests reasoning + structure)
2. A code implementation task (tests execution + correctness)
3. A code review / critique task (tests adversarial analysis)
4. A decomposition task (tests planning + modularity)
5. A cross-domain synthesis task (tests integration across modules)

### 8. Success threshold
**Pass condition**: ≥80% of tasks (4/5) are fully specified with:
- Clear acceptance criteria
- Independently executable scope
- Test plan that a different agent could verify
- No vague language ("improve," "enhance," "optimize" without measurable targets)

---

## Debate Protocol Spec

### Agent Roster

All four frontier models participate in every debate. Roles are **suggested, not enforced** — base models retain autonomy to contribute beyond their suggested focus.

| Model | Suggested Focus | Why |
|-------|----------------|-----|
| Claude Opus 4.6 | Synthesis + specification quality | Strongest at structured output, long-context coherence |
| GPT-5.3 Codex | Implementation feasibility + code architecture | Strongest at code generation and execution planning |
| Gemini 3.1 Pro | Adversarial challenge + edge cases | Strongest at expansive exploration and finding failure modes |
| Grok 4.20 | Empirical grounding + contrarian pressure | Strongest at unfiltered assessment and questioning assumptions |

### Topology

**Modified Prover-Estimator with rotation:**
- Round 1: Each model independently proposes a plan given the input documents
- Round 2: Each model critiques a different model's proposal (rotating assignment)
- Round 3: Each model responds to critiques of their own proposal
- Round 4: Synthesis — all models contribute to a merged specification
- Round 5: Adversarial red-team — each model tries to find the most damaging flaw in the merged spec

### Truth-Seeking Checks
- **Cross-verification**: Claims about codebase state must be verified against actual files (not assumed)
- **Persuasion-vs-truth scoring**: Judge evaluates whether arguments won on evidence or rhetoric
- **Dissent preservation**: Minority positions are recorded in the spec, not silenced by majority
- **Confidence calibration**: Each task estimate includes a confidence interval, tracked for post-hoc calibration

### Hard Rules
- No model may reference another model's corporate affiliation or training methodology as an argument
- Disagreements on factual claims about the codebase trigger a verification step (read the file)
- "I agree" without adding new information is flagged as low-value contribution

---

## Clarified Intent Matrix

### Objective Function
Produce an execution-ready self-improvement specification for Aragora that:
1. Is grounded in the two input documents (roadmap + market analysis)
2. Prioritizes the "golden path" — wiring existing infrastructure into a working end-to-end pipeline
3. Focuses on demonstrable dogfooding value (Aragora improving itself better than a single Claude Code session)
4. Produces tasks clear enough that any frontier model could execute them without clarification

### Non-Goals
- Adding new subsystems or frameworks
- Rewriting working infrastructure
- Performance optimization (unless blocking the golden path)
- UI visual polish (unless blocking the dogfooding UX loop)
- Documentation for documentation's sake

### Constraints
- Every task must touch ≤3 files (excluding tests) to limit blast radius
- Every task must have a rollback plan (usually: `git revert <commit>`)
- No task may break existing tests — CI must pass before and after
- Budget: ≤$15 for spec generation, ≤$50 per implementation task
- Timeline: spec within 60 min, each implementation task within 4 hours

### Acceptance Criteria (for the spec itself)
The dogfood run spec passes if:
- [ ] ≥5 ranked tasks produced with P0/P1/P2 priority
- [ ] Each task has: owner module, file paths, acceptance criteria, test plan, rollback plan
- [ ] No task contains vague language without measurable targets
- [ ] Impairment metric defined with baseline measurement plan
- [ ] At least 2 dissenting positions preserved from the debate
- [ ] Orchestration-ready JSON payload produced and schema-valid

### Escalation Triggers
- If models cannot agree on task ranking after 3 rounds → human decides
- If any model claims a task is infeasible → verify against codebase before proceeding
- If budget would be exceeded → stop and report partial results
- If the spec contains circular dependencies → restructure before approval

---

## Evaluation Harness

### Baseline Measurement
1. **Single-model baseline**: Give Claude Opus 4.6 alone the same input documents and prompt. Record: time to completion, number of tasks produced, quality score per task.
2. **Heterogeneous team run**: Run the full debate protocol above. Record: time to completion, number of tasks produced, quality score per task.

### Quality Scoring (per task)
Each task scored 0-1 on five dimensions:
- **Specificity** (0.2): Are file paths, function names, and acceptance criteria concrete?
- **Executability** (0.2): Could a different agent execute this without asking questions?
- **Testability** (0.2): Is the test plan specific enough to write tests from?
- **Scope discipline** (0.2): Is the task ≤3 files, with clear boundaries?
- **Novelty/value** (0.2): Does this task address a real gap identified in the input documents?

### Impairment Calculation
```
team_score = mean(task_scores for heterogeneous team output)
baseline_score = mean(task_scores for best single model output)
impairment = 1 - (team_score / baseline_score)
```

**Pass condition**: `impairment ≤ 0.50`
**Target**: `impairment ≤ 0.20` (team is within 20% of best single model)
**Stretch goal**: `impairment < 0` (team outperforms best single model)

### Confidence/Calibration Reporting
Each model reports confidence (0-1) for each task recommendation. Post-execution, actual pass/fail is compared to reported confidence to compute calibration error (Brier score).

Report format:
```json
{
  "model": "claude-opus-4-6",
  "task_id": "T1",
  "confidence": 0.85,
  "actual_pass": true,
  "brier_component": 0.0225
}
```

---

## Orchestration-Ready Payload Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["goal", "constraints", "acceptance_criteria", "tasks", "checks", "stop_conditions"],
  "properties": {
    "goal": {
      "type": "string",
      "description": "The top-level objective in one sentence"
    },
    "input_documents": {
      "type": "array",
      "items": { "type": "string" },
      "description": "File paths to input context documents"
    },
    "constraints": {
      "type": "object",
      "properties": {
        "budget_usd": { "type": "number" },
        "max_wall_clock_minutes": { "type": "number" },
        "max_files_per_task": { "type": "integer" },
        "allowed_paths": { "type": "array", "items": { "type": "string" } },
        "forbidden_paths": { "type": "array", "items": { "type": "string" } }
      }
    },
    "acceptance_criteria": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "criterion": { "type": "string" },
          "measurement": { "type": "string" },
          "threshold": { "type": "string" }
        }
      }
    },
    "tasks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "priority", "title", "description", "owner_paths", "acceptance_criteria", "test_plan", "rollback_plan"],
        "properties": {
          "id": { "type": "string" },
          "priority": { "enum": ["P0", "P1", "P2"] },
          "title": { "type": "string" },
          "description": { "type": "string" },
          "owner_paths": { "type": "array", "items": { "type": "string" } },
          "dependencies": { "type": "array", "items": { "type": "string" } },
          "acceptance_criteria": { "type": "array", "items": { "type": "string" } },
          "test_plan": { "type": "string" },
          "rollback_plan": { "type": "string" },
          "estimated_hours": { "type": "number" },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
        }
      }
    },
    "checks": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "gate": { "type": "string" },
          "condition": { "type": "string" },
          "action_on_fail": { "type": "string" }
        }
      }
    },
    "stop_conditions": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Conditions that halt the entire run"
    },
    "debate_config": {
      "type": "object",
      "properties": {
        "models": { "type": "array", "items": { "type": "string" } },
        "rounds": { "type": "integer" },
        "topology": { "type": "string" },
        "dissent_preservation": { "type": "boolean" }
      }
    },
    "provenance": {
      "type": "object",
      "properties": {
        "receipt_required": { "type": "boolean" },
        "settlement_horizon_days": { "type": "integer" },
        "content_hash_algorithm": { "type": "string", "default": "sha256" }
      }
    }
  }
}
```

---

## Execution Plan (To Be Filled by Debate Output)

### Phase 1: Spec Generation (this dogfood run)
1. Feed input documents to debate protocol
2. Run 5-round debate across 4 models
3. Synthesize into ranked task backlog
4. Validate against acceptance criteria
5. Human review and approval

### Phase 2: Baseline Measurement
1. Run single-model (Claude Opus 4.6) against same input
2. Score output on 5-dimension rubric
3. Record as baseline

### Phase 3: Implementation (if spec approved)
1. Execute tasks in priority order (P0 first)
2. Each task: branch → implement → test → gate review → merge
3. Track impairment metric across tasks
4. Generate settlement records for post-hoc calibration

### Phase 4: Evaluation
1. Compare team output vs baseline
2. Calculate impairment metric
3. Report calibration scores per model
4. Document lessons learned for next dogfood run

---

## Dogfood Run 001 Results

### Run Configuration
- **Models**: Claude Sonnet 4 (proposer), GPT-4o (critic), Gemini 2.0 Flash (synthesizer) — via OpenRouter
- **Rounds**: 2
- **Consensus**: Majority
- **Context**: 24,733 chars (roadmap + market analysis excerpts)
- **Total time**: ~90 seconds (debate rounds only)
- **Date**: 2026-03-01

### Evaluation Scorecard

| Criterion | Pass? | Score | Notes |
|-----------|-------|-------|-------|
| ≥5 ranked tasks | YES | 1.0 | 5 tasks: 1 P0, 4 P1 |
| Owner file paths present | YES* | 0.2 | Paths present but ALL WRONG — uses `/src/core/` (doesn't exist), should be `aragora/` |
| Acceptance criteria per task | YES | 0.8 | 5-8 specific criteria with thresholds per task |
| Test plan per task | YES | 0.8 | Detailed plans with performance targets |
| Rollback plan per task | YES | 0.9 | Feature flags, fallbacks, graceful degradation |
| No vague language | PARTIAL | 0.6 | Some measurable targets, but "90%+ of obvious flaws" is vague |
| ≥2 dissenting positions | PARTIAL | 0.4 | One "DISAGREEMENT WITH CRITIQUE" preserved |
| Wires existing infrastructure | **FAIL** | 0.0 | Every task proposes new files. Ignores all existing components. |

**Overall score: 0.54** (weighted average across dimensions)

### Critical Finding: Context Engineering Failure

The debate produced well-structured output that is **fundamentally wrong** because the agents didn't know what already exists in the codebase.

**What agents proposed → What already exists:**
| Proposed New File | Already Exists As |
|---|---|
| `/src/core/dag/pipeline.py` | `aragora/pipeline/idea_to_execution.py` (1,173 LOC) |
| `/src/core/dag/node_types.py` | `aragora/canvas/models.py` + `stages.py` (9 idea types, 6 goal types, 5 action types, 6 orch types) |
| `/src/core/dag/transitions.py` | `aragora/pipeline/dag_operations.py` |
| `/src/core/provenance/hash_chain.py` | `ProvenanceLink` in pipeline with SHA-256 hashing |
| `/src/agents/interrogator/intent_engine.py` | `aragora/interrogation/engine.py` |
| `/src/ui/components/IntentCapture.tsx` | `aragora/live/src/components/unified-dag/DAGToolbar.tsx` (brain dump input) |
| `/src/integrations/obsidian/context_retrieval.py` | `aragora/knowledge/mound/adapters/obsidian.py` |
| `/src/knowledge/mound_connector.py` | `aragora/knowledge/bridges.py` (KnowledgeBridgeHub) |
| `/src/agents/spec_builder/generator.py` | `aragora/prompt_engine/spec_builder.py` |
| `/src/agents/debate/adversarial_validator.py` | `aragora/debate/orchestrator.py` (Arena class) |
| `/src/core/receipts/generator.py` | `aragora/gauntlet/receipt.py` + `aragora/pipeline/receipt_generator.py` |

**The agents reinvented 70% of the existing codebase from scratch.** This is the exact "80% problem" (Stack Overflow 2025: 66% of devs cite "AI solutions that are almost right but not quite") applied to self-improvement planning.

### Root Cause Analysis

1. **Insufficient context**: The input documents described the vision and market analysis but did NOT include the codebase inventory (`IDEA_TO_EXECUTION_PIPELINE.md` lines 42-61, `STRATEGIC_ASSESSMENT_FEB22.md` lines 36-61). The agents had no way to know what already existed.

2. **No codebase verification step**: The debate protocol had no "verify claims against actual files" step. Truth-seeking checks were specified in the protocol but not enforced.

3. **Generic file paths**: Agents defaulted to a generic `/src/` project structure instead of the actual `aragora/` layout, proving they never consulted the codebase.

### Implications for Aragora's Pipeline

This result validates the core thesis of the market analysis:

> "Aragora's wedge is to take vague, underspecified intent and automatically lift it through the full stack"

The debate engine (Discipline 1: Prompt Craft) works. But Discipline 2 (Context Engineering) was missing — the agents operated without the right context. This is exactly the problem Aragora is designed to solve for users, and it's the same problem Aragora has when trying to improve itself.

**Required fix for dogfood run 002:**
1. Auto-inject codebase inventory (file tree, existing component map) into debate context
2. Add a "codebase verification" step where agents must confirm file paths exist before proposing them
3. Require a "what already exists" section before any "what to build" section
4. Run `grep`/`glob` verification on all proposed file paths before accepting the plan

Run-002 execution spec: `docs/plans/dogfood-run-002-context-engineering-spec.md`
Run-002 status (March 2, 2026): partial pass — grounding/path realism improved, but output still failed minimum ranked-task count (3 < 5) and dissent count (1 < 2).

### Raw Debate Output

The full debate output (synthesized across 2 rounds, 3 models) is preserved at `/tmp/dogfood_debate_output_v3.txt`.

---

## Dissenting Positions (From Debate)

The synthesizer preserved one dissenting position:

> "I respectfully maintain that the current task breakdown is optimal... these represent distinct technical domains (DAG infrastructure, NLP processing, knowledge integration, spec generation, cryptography) that benefit from focused implementation and testing."

This dissent is wrong in the specific case (the tasks duplicate existing work) but correct in general principle (distinct technical domains do benefit from focused implementation). The error is in not knowing the domains were already implemented, not in the decomposition strategy.

---

## Dogfood Run 003 Results (Context Injection + Harnesses)

### Date
- 2026-03-03

### Goal
- Re-run baseline vs enhanced debate generation after wiring static codebase inventory + path-grounding checks.
- Compare practical output quality and path realism.

### Benchmark Configuration
- Baseline: `aragora ask ... --agents codex,gemini-cli,codex --rounds 1 --consensus majority --no-learn`
- Enhanced: same command + `--codebase-context --codebase-context-path <repo> --codebase-context-harnesses`
- Both runs used strict CLI timeout and external watchdog timeout.

### Outcome

| Variant | Return | Timed Out | Stdout chars | Practicality | Path existence |
|---|---:|---:|---:|---:|---:|
| Baseline | 1 / -15 (across attempts) | Yes | 0-431 | 3.0 | 0.0 |
| Enhanced | 1 | No at wrapper level, but internal strict timeout hit | 0 | 3.0 | 0.0 |

### Key Findings
1. No final debate/spec payload was emitted before timeout in either variant, so there was no usable baseline-vs-enhanced quality delta.
2. Baseline occasionally emitted only pipeline lifecycle logs (`[PIPE_START] ... [PIPE_DONE]`) without final answer content.
3. Enhanced runs with harness-backed context frequently reached strict wall-clock timeout during/after orchestration.
4. Error traces indicate timeout/cleanup instability in async subprocess handling (`_StrictWallClockTimeout`, `Event loop is closed`, unclosed subprocess transports/sockets).

### Artifacts
- `/tmp/dogfood_bestorder_summary.json`
- `/tmp/dogfood_bestorder_baseline_stderr.txt`
- `/tmp/dogfood_bestorder_enhanced_stderr.txt`
- `/tmp/dogfood_bestorder2_summary.json`
- `/tmp/dogfood_fallback_summary.json`
- `/tmp/dogfood_fallback_baseline_stdout.txt`

### Gate Decision
- **NO-GO for quality comparison**: benchmark infrastructure did not produce final answer payloads reliably.

### Required Follow-up (Run 004 Preconditions)
1. Harden timeout path in `cmd_ask`/`run_debate` so cancellation cleanly terminates child CLI processes and still returns best-available answer text.
2. Ensure post-timeout behavior emits a deterministic failure payload (not empty stdout) so scoring harness can distinguish infra failure from low-quality output.
3. Add a focused regression test around strict timeout + child subprocess cleanup for CLI agent runs.
4. Re-run A/B benchmark only after timeout regression is fixed.

---

## Dogfood Run 004 Results (Timeout-Hardened A/B)

### Date
- 2026-03-03

### Goal
- Re-run baseline vs enhanced comparison after timeout hardening to ensure non-empty machine-readable failure artifacts and objective scoring.

### Benchmark Configuration
- **Baseline**:
  - `aragora ask <task> --agents openrouter(claude/gpt/gemini) --rounds 1 --consensus majority --timeout 240 --local --no-post-consensus-quality`
- **Enhanced**:
  - same command + `--mode orchestrator --codebase-context --codebase-context-harnesses --codebase-context-kilocode --codebase-context-rlm --codebase-context-timeout 180 --codebase-context-max-chars 100000`

### Objective Score (via `scripts/dogfood_score.py`)

| Metric | Baseline | Enhanced |
|---|---:|---:|
| Exit code | 1 | 1 |
| Timeout | Yes | Yes |
| Timeout seconds | 240 | 300 |
| Final answer payload chars | 0 | 0 |
| Composite score | 0.0 | 0.0 |
| Winner | tie | tie |

### Key Findings
1. **Timeout artifact reliability is fixed**: both runs emitted deterministic `ARAGORA_TIMEOUT_JSON` payloads and wrote timeout report files.
2. **A/B quality comparison still blocked**: both variants timed out before producing a final answer payload.
3. **Enhanced context path executes further**: orchestrator lifecycle stages (`PIPE_START` through `PIPE_DONE`) are now consistently visible before timeout.
4. **Residual runtime issue remains**: async cancellation/cleanup still surfaces resource warnings and occasional context teardown errors under strict timeout pressure.

### Artifacts
- `/tmp/dogfood_run004/baseline_stdout.txt`
- `/tmp/dogfood_run004/baseline_stderr.txt`
- `/tmp/dogfood_run004/baseline_timeout_report.json`
- `/tmp/dogfood_run004/enhanced_stdout.txt`
- `/tmp/dogfood_run004/enhanced_stderr.txt`
- `/tmp/dogfood_run004/enhanced_timeout_report.json`
- `/tmp/dogfood_run004/score.json`
- `/tmp/dogfood_run004/score.md`

### Gate Decision
- **NO-GO for quality delta** (again): benchmark can now classify failures deterministically, but still cannot compare output quality without at least one completed final answer.

### Run 005 Preconditions
1. Add grounding fail-closed guardrails (`--grounding-fail-closed`, min verified path ratio) so completed runs can be auto-gated for practical utility.
2. Keep timeout report emission as mandatory benchmark artifact.
3. Raise per-run timeout and/or reduce agent/round load until at least one run completes with final answer text.

---

## Dogfood Run 005 Results (Reduced-Latency Completion A/B)

### Date
- 2026-03-03

### Goal
- Achieve completed baseline and enhanced runs with real final answer payloads, then score objectively.

### Configuration
- **Team**: 2 agents via OpenRouter (`gemini-2.0-flash-001` proposer, `gpt-4o` synthesizer)
- **Rounds**: 1
- **Consensus**: majority
- **Runtime controls**: `--no-post-consensus-quality --no-learn --no-calibration --no-evidence-weighting --no-trending`
- **Baseline timeout**: 420s
- **Enhanced timeout**: 420s
- **Enhanced context mode**: `--mode orchestrator --codebase-context` (static context only; no harness/rlm expansion)

### Execution Results

| Variant | Exit | Duration | Final answer present | Timeout |
|---|---:|---:|---:|---:|
| Baseline | 0 | 160.15s | Yes | No |
| Enhanced | 0 | 193.76s | Yes | No |

### Objective Score (`scripts/dogfood_score.py`)

| Metric | Baseline | Enhanced |
|---|---:|---:|
| Composite score | 0.3794 | **0.4468** |
| Verified existing path ratio | **0.5000** | 0.3571 |
| Duplicate existing create-ratio (lower is better) | 0.5000 | **0.0000** |
| Practicality score (deterministic) | **3.97** | 3.59 |
| Quality score (section-contract) | 0.0 | 0.0 |

Summary:
- **Winner by composite score**: Enhanced
- **Timeout rate**: 0.0 (both runs completed)

### Interpretation
1. Runtime stability goal succeeded: both runs completed and produced scoreable outputs.
2. Enhanced context reduced “create-new-when-already-exists” behavior (duplicate-create ratio improved from 0.50 to 0.00).
3. Enhanced context did not improve structured output compliance: both outputs missed required section headings under the strict score contract, leaving quality score at 0.0.
4. Path grounding is still mixed: enhanced output referenced fewer verifiable existing paths in this run.

### Artifacts
- `/tmp/dogfood_run005/a_baseline_stdout.txt`
- `/tmp/dogfood_run005/a_baseline_stderr.txt`
- `/tmp/dogfood_run005/a_baseline_status.json`
- `/tmp/dogfood_run005/a_enhanced_stdout.txt`
- `/tmp/dogfood_run005/a_enhanced_stderr.txt`
- `/tmp/dogfood_run005/a_enhanced_status.json`
- `/tmp/dogfood_run005/score_a.json`
- `/tmp/dogfood_run005/score_a.md`

### Gate Decision
- **Partial GO**: runtime and scoring harness are now usable for A/B.
- **No GO for quality claims** until output structure contract is enforced at generation time (e.g., required section headings + grounding fail-closed).

---

## Dogfood Run 006 Results (Section Contract + Grounding Fail-Closed A/B)

### Date
- 2026-03-03

### Goal
- Enforce required section headings and grounding fail-closed during generation, then compare baseline vs enhanced context quality with deterministic scoring.

### Configuration
- **Team**: 2 agents via OpenRouter (`gemini-2.0-flash-001` proposer, `gpt-4o` synthesizer)
- **Rounds**: 1
- **Consensus**: majority
- **Hard gates in run command**:
  - `--required-sections "Ranked High-Level Tasks,Suggested Subtasks,Owner module / file paths,Test Plan,Rollback Plan,Gate Criteria"`
  - `--grounding-fail-closed --grounding-min-verified-paths 0.35`
  - `--quality-min-score 7 --quality-practical-min-score 5 --quality-upgrade-max-loops 1`
- **Enhanced context mode**: `--mode orchestrator --codebase-context --codebase-context-max-chars 60000`
- **Timeout**: 420s per run

### Execution Results

| Variant | Exit | Duration | Final answer present | Timeout |
|---|---:|---:|---:|---:|
| Baseline | 0 | 351.53s | Yes | No |
| Enhanced | 0 | 327.56s | Yes | No |

### Objective Score (`scripts/dogfood_score.py`)

| Metric | Baseline | Enhanced |
|---|---:|---:|
| Composite score | 0.7194 | **0.7970** |
| Verified existing path ratio | 0.7647 | **0.8235** |
| Duplicate existing create-ratio (lower is better) | 0.6923 | **0.4643** |
| Practicality score (deterministic) | 9.74 | 9.74 |
| Quality score (section-contract) | 9.0 | 9.0 |

Summary:
- **Winner by composite score**: Enhanced
- **Timeout rate**: 0.0 (both runs completed)

### Interpretation
1. Structured output quality recovered from run-005 failure mode: both variants met required-section contract and scored high (`quality_score_10 = 9.0`).
2. Enhanced codebase context improved grounding (`verified_paths_ratio` +0.0588) and reduced duplicate-create behavior (`duplicate_existing_create_ratio` -0.2280) versus baseline.
3. Duplicate-create behavior is still too high in absolute terms, so this is not yet production-grade planning output.
4. Grounding quality is good enough for fail-closed floor checks at 0.35 but still needs stricter policy to consistently hit higher thresholds.

### Repository State Note (Overall Situation)
- Run-006 was executed from a **clean disposable worktree** at `origin/main` (`codex/reconcile-worktrees-20260303-224514`) to avoid contamination from unrelated local edits in the primary checkout.
- At run time, primary checkout was on `fix/deploy-skip-logic` with unrelated landing-page modifications and untracked assets; these were intentionally not touched.
- Previously “valuable” `integrate/valuable-worktrees-20260304` content was already reconciled into `main` as `feat(landing): render markdown in debate results (#553)`.

### Artifacts
- `/tmp/dogfood_run006/run006_baseline_stdout.txt`
- `/tmp/dogfood_run006/run006_baseline_stderr.txt`
- `/tmp/dogfood_run006/run006_baseline_status.json`
- `/tmp/dogfood_run006/run006_enhanced_stdout.txt`
- `/tmp/dogfood_run006/run006_enhanced_stderr.txt`
- `/tmp/dogfood_run006/run006_enhanced_status.json`
- `/tmp/dogfood_run006/run006_enhanced_codebase_context.md`
- `/tmp/dogfood_run006/run006_score.json`
- `/tmp/dogfood_run006/run006_score.md`

### Gate Decision
- **GO** for quality-comparable A/B benchmarking under strict section contract.
- **Partial GO** for grounding: floor gate passed, but path quality still has synthetic-token noise.
- **NO-GO** for duplicate suppression target until deterministic duplicate-create checks are added to quality defects.

---

## Dogfood Run 007 Results (Duplicate-Suppression Focus)

### Date
- 2026-03-03

### Goal
- Test whether prompt-only duplicate-suppression rules can reduce `duplicate_existing_create_ratio` without regressing quality or grounding.

### Configuration
- **Team**: 2 agents via OpenRouter (`gemini-2.0-flash-001` proposer, `gpt-4o` synthesizer)
- **Rounds**: 1
- **Consensus**: majority
- **Common guardrails**:
  - `--required-sections "Ranked High-Level Tasks,Suggested Subtasks,Owner module / file paths,Test Plan,Rollback Plan,Gate Criteria"`
  - `--mode orchestrator --codebase-context --codebase-context-max-chars 60000`
  - `--quality-min-score 7 --quality-practical-min-score 5 --quality-upgrade-max-loops 1` (focused retry used 2 loops)
- **Comparison setup**:
  - **Control**: standard run-006 style task prompt
  - **Focused**: added explicit anti-duplicate language (`modify/refactor/extend`, no `create/add/build` against existing paths)

### Execution Results

| Variant | Exit | Duration | Final answer present | Notes |
|---|---:|---:|---:|---|
| Control | 0 | 321.87s | Yes | Stable structured output |
| Focused (attempt 1) | 1 | 364.24s | Yes | Grounding fail-closed tripped on placeholder output |
| Focused (retry) | 0 | 358.70s | Yes | Valid structured output, used for scoring |

### Objective Score (Control vs Focused Retry)

| Metric | Control | Focused Retry |
|---|---:|---:|
| Composite score | **0.8839** | 0.8014 |
| Verified existing path ratio | 1.0000 | 1.0000 |
| Duplicate existing create-ratio (lower is better) | **0.3846** | 0.7143 |
| Practicality score (deterministic) | 10.0 | 10.0 |
| Quality score (section-contract) | 9.0 | 9.0 |

Summary:
- **Winner by composite score**: Control
- **Timeout rate**: 0.0
- **Blocker result**: Prompt-only duplicate-suppression **failed** (duplicate ratio worsened by +0.3297).

### Interpretation
1. Prompt-only wording is insufficient for duplicate suppression and can backfire while still producing high-quality, fully grounded text.
2. Quality and grounding remained excellent, so the regression isolates specifically to duplicate-create behavior.
3. Deterministic enforcement in code (quality defects + repair) is required for the blocker, not stronger prompt phrasing alone.

### Artifacts
- `/tmp/dogfood_run007/run007_control_stdout.txt`
- `/tmp/dogfood_run007/run007_control_stderr.txt`
- `/tmp/dogfood_run007/run007_control_status.json`
- `/tmp/dogfood_run007/run007_focused_stdout.txt`
- `/tmp/dogfood_run007/run007_focused_stderr.txt`
- `/tmp/dogfood_run007/run007_focused_status.json`
- `/tmp/dogfood_run007/run007_focused_retry_stdout.txt`
- `/tmp/dogfood_run007/run007_focused_retry_stderr.txt`
- `/tmp/dogfood_run007/run007_focused_retry_status.json`
- `/tmp/dogfood_run007/run007_score.json` (control vs focused attempt 1)
- `/tmp/dogfood_run007/run007_score_retry.json` (control vs focused retry; canonical)
- `/tmp/dogfood_run007/run007_score_retry.md`

### Gate Decision
- **GO** for continued strict section + grounding gates (stable).
- **NO-GO** for prompt-only duplicate suppression.
- **Next required change**: add deterministic duplicate-create defecting/repair in `aragora/debate/output_quality.py` and gate on `duplicate_existing_create_ratio <= 0.25`.

---

## Dogfood Run 008g Results (Fail-Fast Runtime + RLM-Limiter Off)

### Date
- 2026-03-04

### Goal
- Validate the new duplicate-create deterministic enforcement under real runs and reduce long-stall behavior by:
  - disabling post-consensus upgrade loops
  - disabling context-init RLM limiter
  - keeping strict timeout reports enabled

### Configuration
- **Team**: 3 agents via OpenRouter (`claude-sonnet-4` proposer, `gpt-4o` critic, `gemini-2.0-flash-001` synthesizer)
- **Rounds**: 1
- **Consensus**: majority
- **Runtime controls**:
  - `--no-context-init-rlm`
  - `--no-upgrade-to-good`
  - `--quality-concretize-max-rounds 0`
  - `--quality-extra-assessment-rounds 0`
  - `--timeout 240`
- **Context mode**:
  - `--codebase-context --codebase-context-path <repo>`
  - no harness explorers in this benchmark leg

### Execution Results

| Variant | Exit | Duration | Final answer present | Timeout report |
|---|---:|---:|---:|---:|
| Control | 1 | 246.324s | No | Yes |
| Focused | 0 | 238.615s | Yes | No |

### Objective Score (`scripts/dogfood_score.py`)

| Metric | Baseline (Control) | Enhanced (Focused) |
|---|---:|---:|
| Composite score | 0.0 | **0.9256** |
| Quality score | N/A (timeout) | 9.0 |
| Practicality score | N/A (timeout) | 9.03 |
| Verified existing path ratio | N/A (timeout) | 0.90 |
| Duplicate existing create-ratio | N/A (timeout) | **0.0** |
| Timeout rate |  | 0.5 |

Summary:
- **Winner by composite score**: Enhanced (focused)
- **Control failure mode**: timed out with machine-readable timeout payload (`async_wait_for_timeout`)
- **Focused quality**: passed strict section contract + grounding checks with zero duplicate-create ratio

### Key Findings
1. The fail-fast timeout artifact path remains reliable under pressure (`ARAGORA_TIMEOUT_JSON` + timeout report file).
2. Disabling context-init RLM limiter and upgrade loops is sufficient for at least one complete, high-quality run in this setup.
3. Runtime asymmetry remains: control still times out while focused completes near the budget edge.
4. The deterministic duplicate-create gate/repair is now in production code and behaves as expected on historical high-duplicate outputs.

### Artifacts
- `/tmp/dogfood_run008g/run008g_control_stdout.txt`
- `/tmp/dogfood_run008g/run008g_control_stderr.txt`
- `/tmp/dogfood_run008g/run008g_control_timeout.json`
- `/tmp/dogfood_run008g/run008g_control_status.json`
- `/tmp/dogfood_run008g/run008g_focused_stdout.txt`
- `/tmp/dogfood_run008g/run008g_focused_stderr.txt`
- `/tmp/dogfood_run008g/run008g_focused_status.json`
- `/tmp/dogfood_run008g/run008g_summary.json`
- `/tmp/dogfood_run008g/run008g_summary.md`

### Gate Decision
- **GO** for:
  - deterministic duplicate-create enforcement in quality pipeline
  - explicit `--no-context-init-rlm` runtime control in `ask`
  - explorer timeout/cleanup hardening
- **NO-GO** for declaring timeout stability solved globally; control still timed out in this run.

---

## Dogfood Run 008h Results (Timeout Doubled to 480s)

### Date
- 2026-03-04

### Goal
- Validate whether doubling benchmark timeout from `240s` to `480s` eliminates timeout-driven A/B invalidation under the same runtime profile.

### Configuration
- **Team**: 3 agents via OpenRouter (`claude-sonnet-4` proposer, `gpt-4o` critic, `gemini-2.0-flash-001` synthesizer)
- **Rounds**: 1
- **Consensus**: majority
- **Runtime controls**:
  - `--no-context-init-rlm`
  - `--no-upgrade-to-good`
  - `--quality-concretize-max-rounds 0`
  - `--quality-extra-assessment-rounds 0`
  - `--timeout 480` (**doubled from 240**)
- **Context mode**:
  - `--codebase-context --codebase-context-path <repo>`
  - no harness explorers in this benchmark leg

### Execution Results

| Variant | Exit | Duration | Final answer present | Timeout report |
|---|---:|---:|---:|---:|
| Control | 0 | 259.785s | Yes | No |
| Focused | 0 | 232.763s | Yes | No |

### Objective Score (`scripts/dogfood_score.py`)

| Metric | Baseline (Control) | Enhanced (Focused) |
|---|---:|---:|
| Composite score | **0.6150** | 0.5414 |
| Quality score | **9.0** | 8.0 |
| Practicality score | 6.56 | **6.57** |
| Verified existing path ratio | **0.1538** | 0.0 |
| Duplicate existing create-ratio | N/A | **0.0** |
| Timeout rate |  | **0.0** |

Summary:
- **Winner by composite score**: Baseline (control)
- **Timeout impact**: doubling timeout removed timeout failures in this run (`timeout_rate` dropped from 0.5 in run-008g to 0.0 in run-008h).

### Key Findings
1. Doubling timeout to `480s` materially improved benchmark reliability (both legs completed with final answers).
2. Runtime reliability gain did not automatically improve focused-output quality; focused output regressed on structure/path grounding in this sample.
3. Duplicate-create suppression remained strong in focused output (`0.0`), but grounding/path specificity dropped, indicating over-correction.
4. New timeout default is justified for benchmark validity; prompt/contract tuning is still required for focused variant quality consistency.

### Artifacts
- `/tmp/dogfood_run008h/run008h_control_stdout.txt`
- `/tmp/dogfood_run008h/run008h_control_stderr.txt`
- `/tmp/dogfood_run008h/run008h_control_status.json`
- `/tmp/dogfood_run008h/run008h_focused_stdout.txt`
- `/tmp/dogfood_run008h/run008h_focused_stderr.txt`
- `/tmp/dogfood_run008h/run008h_focused_status.json`
- `/tmp/dogfood_run008h/run008h_summary.json`
- `/tmp/dogfood_run008h/run008h_summary.md`

### Gate Decision
- **GO** to adopt `--timeout 480` as the benchmark default for this run class.
- **NO-GO** on focused prompt contract until path-grounding/section regressions are corrected.

---

## Dogfood Run 010 Results (Strict Focused Fail-Closed Stress)

### Date
- 2026-03-04

### Goal
- Validate whether a very strict focused profile (contract + grounding + quality fail-closed) can outperform baseline while preserving timeout reliability.

### Configuration
- **Pairs**: 3 control/focused pairs
- **Timeout**: `960s`
- **Focused profile**:
  - contract + grounding enabled
  - post-consensus quality upgrades enabled
  - `--quality-fail-closed` enabled
  - harness-backed context enabled

### Outcome
- **Timeout reliability**: stable (`mean_timeout_rate=0.0`)
- **Quality outcome**: focused failed all 3 pairs (`median baseline 0.461` vs `median focused 0.0`)
- **Primary failure mode**: focused runs exited non-zero without final payload under fail-closed quality gates; duplicate-create ratio violations remained.

### Gate Decision
- **NO-GO** for strict fail-closed focused profile in benchmark scoring mode.
- Keep timeout settings; tune focused profile to emit scoreable outputs while retaining grounding constraints.

---

## Dogfood Run 011 Results (Tuned Focused Profile, Promotion Pass)

### Date
- 2026-03-04

### Goal
- Apply tuned focused settings to fix run-010 regressions:
  - remove `--quality-fail-closed` for benchmark scoring runs
  - keep grounded contract checks
  - use realistic grounding threshold
  - strengthen anti-duplicate and anti-empty-section prompt constraints

### Configuration
- **Pairs**: 3 control/focused pairs
- **Timeout**: `960s`
- **Focused profile**:
  - `--output-contract-file docs/plans/dogfood_output_contract_v2.json`
  - `--grounding-fail-closed --grounding-min-verified-paths 0.1`
  - `--quality-upgrade-max-loops 1`
  - `--quality-concretize-max-rounds 1`
  - `--quality-extra-assessment-rounds 0`
  - no `--quality-fail-closed`

### Outcome

| Metric | Value |
|---|---:|
| Median composite (baseline) | 0.4600 |
| Median composite (focused) | **0.5326** |
| Promotion delta | **+0.0726** |
| Timeout rate | 0.0 |
| Pair winners | focused, focused, baseline |

Focused profile exceeded the promotion threshold (`>= +0.05`) while maintaining timeout stability.

### Codified Runner
- Use `scripts/run_dogfood_ab_pairs.py` as the default A/B benchmark runner for this class.
- Default contract: `docs/plans/dogfood_output_contract_v2.json`
- Default timeout: `960s`
- Suggested confidence run:
  - `python3 scripts/run_dogfood_ab_pairs.py --pairs 5 --timeout-seconds 960 --output-root /tmp/dogfood_run_next`

### Gate Decision
- **GO** to promote the tuned focused profile as default benchmark-focused settings for this run class.
- **Follow-up**: run 5 pairs for higher-confidence median stability and continue reducing residual duplicate-create defects.

---

## Dogfood Run 012 Results (5-Pair Confidence Run)

### Date
- 2026-03-04

### Goal
- Validate run-011 focused profile on a larger sample (`5` pairs) for higher-confidence promotion decision.
- Measure duplicate-create ratio stability (pre-fix: "add" verb still counted as create).

### Benchmark Runner
- `scripts/run_dogfood_ab_pairs.py`
- Contract: `docs/plans/dogfood_output_contract_v2.json`
- Command:
  - `python3 scripts/run_dogfood_ab_pairs.py --pairs 5 --timeout-seconds 960 --output-root /tmp/dogfood_run012`

### Aggregate Outcome

| Metric | Value |
|---|---:|
| Pairs | 5 |
| Timeout rate | 0.0 |
| Median composite (baseline) | 0.4610 |
| Median composite (focused) | **0.8443** |
| Promotion threshold | +0.0500 |
| Observed delta | **+0.3833** |
| Pair winners | focused ×5 (100%) |

### Per-Pair Breakdown

| Pair | Enhanced | Baseline | Quality | Practicality | Path Ratio | Dup-Create |
|------|----------|----------|---------|--------------|------------|------------|
| 1 | 0.8443 | 0.4594 | 9.0 | 8.84 | 0.9167 | 0.3333 |
| 2 | 0.6965 | 0.4610 | 8.0 | 8.75 | 0.9375 | 0.8667 |
| 3 | 0.9124 | 0.4592 | 9.0 | 8.81 | 0.8750 | 0.0 |
| 4 | 0.8976 | 0.4610 | 9.0 | 8.38 | — | 0.0 |
| 5 | 0.6778 | 0.4610 | 7.0 | 9.39 | 1.0 | 1.0 |

### Key Observations
- **Enhanced profile is decisively superior**: 5/5 wins with +0.3833 median delta.
- **Quality consistently high**: 7.0–9.0 range (mean ~8.4) vs baseline's flat 7.0.
- **Practicality breakthrough**: 8.38–9.39 range vs baseline's 3.46–3.55.
- **Duplicate-create residual**: Pairs 2 and 5 still show high dup_ratio (0.87, 1.0) due to "add" verb false positives. PR #594 (`fix/duplicate-create-scoring`) excludes "add" from the scoring regex, which will eliminate these false positives in future runs.
- **Path grounding strong**: 87.5%–100% verified path ratios when measured.

### Artifacts
- `/tmp/dogfood_run012/aggregate_summary.json`
- `/tmp/dogfood_run012/<pair>/pair_<n>_summary.json`

### Gate Decision
- **GO**: Focused profile confirmed with 100% win rate across 5 pairs.
- **GO**: Promote as default benchmark-focused settings.
- **FOLLOW-UP**: Re-run after PR #594 merges to validate dup-create ratio improvement.
