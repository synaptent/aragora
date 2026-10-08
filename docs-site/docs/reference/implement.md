---
title: Implementation Pipeline
description: Implementation Pipeline
---

# Implementation Pipeline

The Implementation module (`aragora/implement/`) provides autonomous code generation capabilities used by the Nomic Loop's Phase 3. It orchestrates multi-model execution with crash recovery, retry logic, and optional code review.

## Overview

| Component | Purpose | Model |
|-----------|---------|-------|
| **Planner** | Decompose designs into tasks | Gemini (1M context) |
| **Executor** | Implement code changes | Claude (fastest) |
| **Reviewer** | Quality gate (optional) | Codex (thorough) |
| **Checkpoint** | Crash recovery | File-based |

```
Design Input
    ↓
┌──────────────────┐
│ Planner (Gemini) │  Generate task list with dependencies
└────────┬─────────┘
         ↓
┌──────────────────┐
│ Save Checkpoint  │  Persist progress to .nomic/
└────────┬─────────┘
         ↓
    ┌────┴────┐
    ↓         ↓
Sequential  Parallel   Execute tasks respecting dependencies
    └────┬────┘
         ↓
┌──────────────────┐
│ Per-Task Loop    │  Retry with timeout escalation
│  Claude → Codex  │  Fallback on continued failure
└────────┬─────────┘
         ↓
┌──────────────────┐
│ Review (Codex)   │  Optional QA phase
└────────┬─────────┘
         ↓
┌──────────────────┐
│ Update Progress  │  Mark complete, capture diff
└──────────────────┘
```

## Core Types

### ImplementTask

Individual unit of work with complexity-based routing.

```python
@dataclass
class ImplementTask:
    id: str                                  # Unique identifier
    description: str                         # What to implement
    files: list[str]                         # Files to create/modify
    complexity: Literal["simple", "moderate", "complex"]
    dependencies: list[str] = []             # Task IDs that must complete first
```

### ImplementPlan

Collection of tasks generated from a design.

```python
@dataclass
class ImplementPlan:
    design_hash: str           # Hash of source design for tracking
    tasks: list[ImplementTask]
    created_at: datetime
```

### TaskResult

Execution outcome for a single task.

```python
@dataclass
class TaskResult:
    task_id: str
    success: bool
    diff: str = ""                 # Git diff of changes
    error: Optional[str] = None
    model_used: Optional[str]      # "claude" or "codex-fallback"
    duration_seconds: float = 0.0
```

### ImplementProgress

Checkpoint state for crash recovery.

```python
@dataclass
class ImplementProgress:
    plan: ImplementPlan
    completed_tasks: list[str]
    current_task: Optional[str]
    git_stash_ref: Optional[str]   # For rollback
    results: list[TaskResult]
```

---

## Usage

### Basic Flow

```python
from pathlib import Path
from aragora.implement import (
    generate_implement_plan,
    HybridExecutor,
    save_progress,
    load_progress,
    clear_progress,
    ImplementProgress,
)

repo_path = Path("/path/to/repo")

# 1. Generate plan from design
design = """
Create a new rate limiter module with:
- Token bucket algorithm
- Redis backend support
- Per-user and per-endpoint limits
"""
plan = await generate_implement_plan(design, repo_path)

# 2. Check for existing progress (crash recovery)
progress = load_progress(repo_path)
completed = set(progress.completed_tasks) if progress else set()

# 3. Execute plan
executor = HybridExecutor(repo_path)
results = await executor.execute_plan(plan.tasks, completed)

# 4. Save progress
progress = ImplementProgress(
    plan=plan,
    completed_tasks=[r.task_id for r in results if r.success],
    results=results,
)
save_progress(progress, repo_path)

# 5. Clear on full success
if all(r.success for r in results):
    clear_progress(repo_path)
```

### With Callbacks

```python
def on_task_complete(task_id: str, result: TaskResult):
    if result.success:
        print(f"[OK] {task_id} ({result.duration_seconds:.1f}s)")
    else:
        print(f"[FAIL] {task_id}: {result.error}")

results = await executor.execute_plan(
    plan.tasks,
    completed,
    on_task_complete=on_task_complete,
)
```

### Parallel Execution

Enable via environment variable for independent tasks:

```bash
export IMPL_PARALLEL_TASKS=1
export IMPL_MAX_PARALLEL=3
```

```python
results = await executor.execute_plan_parallel(
    plan.tasks,
    completed,
    max_parallel=3,
)
```

---

## Timeout Calculation

Timeouts scale based on task complexity and file count:

| Complexity | Base Timeout | Per Extra File | Maximum |
|------------|--------------|----------------|---------|
| Simple | 5 min (300s) | +2 min | 30 min |
| Moderate | 10 min (600s) | +2 min | 30 min |
| Complex | 20 min (1200s) | +2 min | 30 min |

**Formula:** `min(base + (file_count - 1) * 120, 1800)`

**Example:**
- Simple task with 1 file: 300s (5 min)
- Moderate task with 5 files: 600 + 480 = 1080s (18 min)
- Complex task with 10 files: 1200 + 1080 = 1800s (30 min cap)

---

## Retry Strategy

Failed tasks are retried with escalating timeouts and model fallback:

```
Attempt 1: Claude (normal timeout)
    ↓ timeout
Attempt 2: Claude (2x timeout)
    ↓ timeout
Attempt 3: Codex fallback (2x timeout)
```

After the first pass completes, failed tasks are retried once more if their dependencies are now met.

---

## Checkpoint System

Progress is persisted to `.nomic/implement_progress.json` for crash recovery.

### Atomic Writes

Uses temp-file + rename pattern to prevent corruption:

```python
# Write to temp file
fd, temp_path = tempfile.mkstemp(...)
with os.fdopen(fd, "w") as f:
    json.dump(progress.to_dict(), f)

# Atomic rename
os.rename(temp_path, progress_path)
```

### Recovery on Restart

```python
progress = load_progress(repo_path)
if progress:
    # Resume from checkpoint
    completed = set(progress.completed_tasks)
    results = await executor.execute_plan(progress.plan.tasks, completed)
else:
    # Start fresh
    plan = await generate_implement_plan(design, repo_path)
    results = await executor.execute_plan(plan.tasks, set())
```

---

## Optional Codex Review

After implementation, optionally run Codex code review:

```python
# Get combined diff
diff = "\n".join(r.diff for r in results if r.success)

# Run review (may take 5-20 minutes)
review = await executor.review_with_codex(diff)

if review.get("approved"):
    print("Changes approved")
else:
    print("Issues found:", review.get("issues"))
```

### Review Checklist

Codex evaluates:
1. Bugs or logic errors
2. Security vulnerabilities (injection, XSS)
3. Code style consistency
4. Missing error handlers
5. Unnecessary complexity

---

## Feature Flags

Control behavior via environment variables:

| Flag | Default | Description |
|------|---------|-------------|
| `IMPL_COMPLEXITY_TIMEOUT` | `1` (ON) | Use complexity for timeout calculation |
| `IMPL_DECOMPOSE_FAILED` | `0` (OFF) | Decompose failed tasks into subtasks |
| `IMPL_PARALLEL_TASKS` | `0` (OFF) | Execute independent tasks in parallel |
| `IMPL_MAX_PARALLEL` | `2` | Max concurrent tasks when parallel |

---

## Safety Guarantees

### Present

- **Timeout enforcement** - Maximum 30 min prevents runaway tasks
- **Atomic checkpoints** - No corruption on process death
- **Git stash support** - Rollback points tracked
- **Prompt instructions** - "Only make changes that are safe and reversible"
- **Retry with fallback** - Model redundancy for resilience

### Recommended Additions

For production use, add these validations after task execution:

```python
import ast
import subprocess

result = await executor.execute_task(task)

# 1. Syntax validation
for file in task.files:
    with open(file) as f:
        ast.parse(f.read())

# 2. Import validation
subprocess.run(["python", "-c", "import aragora"], check=True)

# 3. Test execution
subprocess.run(["pytest", "tests/", "-x"], check=True)
```

---

## API Reference

### HybridExecutor

```python
class HybridExecutor:
    def __init__(
        self,
        repo_path: Path,
        claude_timeout: int = 1200,   # 20 min default
        codex_timeout: int = 1200,
        max_retries: int = 2,
    ): ...

    async def execute_task(
        self,
        task: ImplementTask,
        attempt: int = 1,
        use_fallback: bool = False,
    ) -> TaskResult: ...

    async def execute_task_with_retry(
        self,
        task: ImplementTask,
    ) -> TaskResult: ...

    async def execute_plan(
        self,
        tasks: list[ImplementTask],
        completed: set[str],
        on_task_complete=None,
        stop_on_failure: bool = False,
    ) -> list[TaskResult]: ...

    async def execute_plan_parallel(
        self,
        tasks: list[ImplementTask],
        completed: set[str],
        max_parallel: int | None = None,
        on_task_complete=None,
    ) -> list[TaskResult]: ...

    async def review_with_codex(
        self,
        diff: str,
        timeout: int = 2400,
    ) -> dict: ...
```

### Planner Functions

```python
async def generate_implement_plan(
    design: str,
    repo_path: Path,
) -> ImplementPlan: ...

def create_single_task_plan(
    description: str,
    files: list[str],
) -> ImplementPlan: ...
```

### Checkpoint Functions

```python
def save_progress(progress: ImplementProgress, repo_path: Path) -> None: ...
def load_progress(repo_path: Path) -> Optional[ImplementProgress]: ...
def clear_progress(repo_path: Path) -> None: ...
```

---

## Troubleshooting

### Task Hanging

```bash
# Check agent processes
ps aux | grep claude

# Kill and resume
python scripts/run_nomic_with_stream.py run --resume
```

### Timeout Errors

1. Check task file count (each adds 2 min)
2. Increase `IMPL_COMPLEXITY_TIMEOUT`
3. Break large tasks into smaller ones

### Corrupted Progress File

```bash
# Remove corrupted checkpoint
rm .nomic/implement_progress.json

# Restart fresh
python scripts/run_nomic_with_stream.py run
```

### Dependency Deadlock

If parallel execution reports deadlock:

1. Check task dependency graph for cycles
2. Verify all referenced task IDs exist
3. Run with `IMPL_PARALLEL_TASKS=0` to debug

---

## Metrics

Track implementation performance:

```python
results = await executor.execute_plan(tasks, set())

success_rate = sum(1 for r in results if r.success) / len(results)
avg_duration = sum(r.duration_seconds for r in results) / len(results)
total_time = sum(r.duration_seconds for r in results)

print(f"Success: {success_rate:.1%}")
print(f"Average: {avg_duration:.1f}s per task")
print(f"Total: {total_time:.1f}s")

# Model usage breakdown
from collections import Counter
models = Counter(r.model_used for r in results)
print(f"Models: {dict(models)}")
```

---

## See Also

- [NOMIC_LOOP.md](../admin/nomic-loop) - Phase 3 context
- [ARCHITECTURE.md](../core-concepts/architecture) - System overview
- [RESILIENCE.md](../advanced/resilience) - Circuit breaker patterns
