# Aragora Pipeline Guide

> **Last Updated:** 2026-03-04

The Idea-to-Execution pipeline transforms raw ideas into structured, executable plans in four stages, with a full provenance chain and audit receipt at the end.

## Related Documentation

| Document | Purpose |
|----------|---------|
| **PIPELINE_GUIDE.md** (this) | Idea-to-Execution pipeline usage |
| [MODES_GUIDE.md](MODES_GUIDE.md) | Operational modes (Architect, Coder, etc.) |
| [NOMIC_LOOP_TROUBLESHOOTING.md](NOMIC_LOOP_TROUBLESHOOTING.md) | Self-improvement debugging |

---

## The Four Stages

```
Stage 1: Ideas        Raw input → Ideas Canvas (nodes + clusters)
Stage 2: Goals        Ideas → Goal Graph (prioritized, confidence-scored goals)
Stage 3: Workflow     Goals → Actions Canvas (DAG of concrete tasks)
Stage 4: Orchestration  Actions → Execution Plan (agent assignments + receipts)
```

Each stage transition is recorded in a provenance chain with SHA-256 content hashes. Human-in-the-loop gates can be inserted between stages via `human_approval_required=True`.

The pipeline assigns operational modes per stage by default:

| Stage | Default Mode |
|-------|-------------|
| Ideation | `architect` |
| Goals | `architect` |
| Workflow | `coder` |
| Orchestration | `orchestrator` |

---

## Python API

```python
from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline, PipelineConfig

pipeline = IdeaToExecutionPipeline()

# From raw ideas (comma-separated strings)
result = pipeline.from_ideas([
    "Build rate limiter",
    "Add request caching",
    "Improve error handling",
])

# Access stage outputs
print(result.pipeline_id)           # Unique run identifier
print(result.goal_graph.goals)      # List of extracted Goal objects
print(result.stage_results)         # Per-stage status, duration, errors
print(result.receipt)               # Audit receipt dict (if enable_receipts=True)
print(result.provenance)            # Full provenance chain
```

### PipelineConfig options

```python
config = PipelineConfig(
    stages_to_run=["ideation", "goals", "workflow", "orchestration"],
    debate_rounds=3,
    workflow_mode="quick",          # "quick" or "debate"
    dry_run=False,
    enable_receipts=True,
    human_approval_required=False,  # Pause at each gate for review
    enable_smart_goals=True,        # AI-powered goal extraction
    enable_elo_assignment=True,     # Assign ELO-ranked agents to tasks
    enable_km_precedents=True,      # Pull relevant past decisions from KM
    enable_km_persistence=True,     # Auto-persist results to KnowledgeMound
    use_arena_orchestration=True,   # Stage 4: mini-debate for task prioritization
)
```

### UnifiedOrchestrator (full prompt-to-execution)

For single-prompt entry with research, diversity enforcement, and ELO feedback:

```python
from aragora.pipeline.unified_orchestrator import UnifiedOrchestrator, OrchestratorConfig

orchestrator = UnifiedOrchestrator(
    researcher=my_researcher,       # Optional: all deps are optional
    diversity_filter=my_filter,
    arena_factory=my_arena_factory,
)

result = await orchestrator.run(
    prompt="Design a multi-tenant rate limiter",
    config=OrchestratorConfig(
        preset_name="cto",              # founder | cto | team | non_technical
        autonomy_level="propose_and_approve",
        min_providers=2,                # Enforce multi-provider debate teams
        enable_meta_loop=False,         # Trigger self-improvement on completion
        skip_execution=False,
    ),
)

print(result.succeeded)             # True if debate completed without errors
print(result.quality_score)         # Overall quality score from outcome feedback
print(result.stages_completed)      # e.g. ["research", "extend", "debate", "plan"]
```

---

## CLI

```bash
# Run from raw ideas (comma-separated)
aragora pipeline run "Build rate limiter, Add caching"

# Dry run — preview stages without executing
aragora pipeline run "Improve error handling" --dry-run

# With budget cap and human approval at gates
aragora pipeline run "Redesign auth" --budget-limit 10 --require-approval

# Show active pipelines
aragora pipeline status

# Self-improvement: decompose a high-level goal through the full pipeline
aragora pipeline self-improve "Maximize utility for SMEs"

# Self-improvement with handoff to execution engine
aragora pipeline self-improve "Improve test coverage" --execute --max-goals 3 --max-parallel 4
```

The `self-improve` subcommand chains three steps internally: TaskDecomposer (complexity analysis) → MetaPlanner (priority debate) → IdeaToExecutionPipeline (structure) → SelfImprovePipeline (execution).

---

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/pipeline/:id/execute` | Start Stage 4 execution |
| `GET` | `/api/v1/pipeline/:id/execute` | Get execution status |
| `GET` | `/api/v1/pipeline/:id/graph` | Fetch React Flow canvas graph |
| `GET` | `/api/v1/pipeline/:id/provenance` | Full provenance chain |

Requires `pipeline:read` permission for GET, `pipeline:write` for POST.

---

## WebSocket Streaming

Connect to the pipeline WebSocket to receive real-time events during execution. Events are scoped by `pipeline_id` — each client only receives events for the pipeline it is watching.

| Event type | When emitted |
|------------|-------------|
| `pipeline_started` | Full pipeline run begins |
| `pipeline_stage_started` | Individual stage begins |
| `pipeline_stage_completed` | Individual stage finishes |
| `pipeline_graph_updated` | React Flow canvas updated |
| `pipeline_goal_extracted` | Goal extracted from debate output |
| `pipeline_workflow_generated` | Workflow DAG generated |
| `pipeline_step_progress` | Step-level progress within a stage |
| `pipeline_node_added` | Node added to canvas |
| `pipeline_transition_pending` | Human approval gate waiting |
| `pipeline_completed` | Full pipeline finished |
| `pipeline_failed` | Pipeline failed |

---

## Output Structure

A completed `PipelineResult` contains:

```
pipeline_id          str        Unique run ID
ideas_canvas         Canvas     Stage 1 output (React Flow nodes)
goal_graph           GoalGraph  Stage 2 output (prioritized goals)
actions_canvas       Canvas     Stage 3 output (action DAG)
orchestration_canvas Canvas     Stage 4 output (agent assignments)
stage_results        list       Per-stage status, duration, errors
provenance           list       Full provenance chain (ProvenanceLink objects)
receipt              dict       Audit receipt with SHA-256 integrity hash
duration             float      Total wall-clock seconds
```

`result.to_dict()` returns a JSON-serializable representation including React Flow-compatible canvas data for the frontend.

---

## Frontend Integration

The pipeline feeds the prompt-to-execution canvas UI at `/pipeline`. The frontend:

1. POSTs to `/api/v1/pipeline/:id/execute` to start execution
2. Subscribes to the pipeline WebSocket for live stage updates
3. Renders each stage as a React Flow canvas node
4. Presents human approval gates as interactive dialogs when `pipeline_transition_pending` fires

See `docs/guides/FRONTEND_ROUTES.md` for frontend route details.
