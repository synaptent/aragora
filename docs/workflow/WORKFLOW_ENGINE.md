# Workflow Engine

The `aragora/workflow/` module provides a DAG-based workflow execution engine for automating complex multi-step operations.

## Overview

| Component | Description |
|-----------|-------------|
| `engine.py` | Core workflow execution engine |
| `engine_v2.py` | Enhanced engine with parallel execution |
| `schema.py` | Workflow definition schema |
| `types.py` | Type definitions |
| `step.py` | Individual workflow step handling |
| `nodes/` | Workflow node type implementations |
| `patterns/` | Reusable workflow patterns |
| `templates/` | Pre-built workflow templates |
| `presets/` | Common workflow presets |
| `queue/` | Workflow queue management |

## Quick Start

```python
from aragora.workflow import WorkflowEngine, WorkflowDefinition

# Define a workflow
workflow = WorkflowDefinition(
    name="debate_analysis",
    steps=[
        {"id": "extract", "type": "extract_claims", "input": "$debate"},
        {"id": "verify", "type": "verify_claims", "input": "$extract.claims"},
        {"id": "report", "type": "generate_report", "input": "$verify.results"},
    ]
)

# Execute
engine = WorkflowEngine()
result = await engine.execute(workflow, {"debate": debate_data})
```

## Workflow Definition

Workflows are defined as directed acyclic graphs (DAGs) of steps.

### Schema

```python
from aragora.workflow.schema import (
    WorkflowDefinition,
    StepDefinition,
    InputRef,
    OutputMapping,
)

workflow = WorkflowDefinition(
    name="my_workflow",
    description="Process and analyze debate data",
    version="1.0.0",

    # Input parameters
    inputs={
        "debate_id": {"type": "string", "required": True},
        "options": {"type": "object", "default": {}},
    },

    # Workflow steps
    steps=[
        StepDefinition(
            id="step_1",
            type="fetch_debate",
            inputs={"id": InputRef("$inputs.debate_id")},
            outputs={"debate": "result.debate"},
        ),
        StepDefinition(
            id="step_2",
            type="analyze",
            inputs={"data": InputRef("$step_1.debate")},
            depends_on=["step_1"],
        ),
    ],

    # Final outputs
    outputs={
        "analysis": "$step_2.result",
    }
)
```

### Step Types

| Type | Description |
|------|-------------|
| `fetch_debate` | Load debate from storage |
| `extract_claims` | Extract claims from text |
| `verify_claims` | Verify claims formally |
| `score_evidence` | Score evidence quality |
| `generate_report` | Create analysis report |
| `notify` | Send notifications |
| `conditional` | Branch based on condition |
| `parallel` | Execute steps in parallel |
| `loop` | Iterate over collection |

## Node Types

The `nodes/` directory contains implementations for each step type.

### Custom Node

```python
from aragora.workflow.nodes.base import BaseNode, NodeResult

class MyCustomNode(BaseNode):
    """Custom workflow node."""

    node_type = "my_custom"

    async def execute(self, inputs: dict) -> NodeResult:
        # Process inputs
        result = await self.process(inputs["data"])

        return NodeResult(
            success=True,
            outputs={"processed": result},
            metadata={"duration_ms": 150}
        )
```

Register in `nodes/__init__.py`:

```python
from .my_custom import MyCustomNode

NODE_REGISTRY["my_custom"] = MyCustomNode
```

## Patterns

The `patterns/` directory contains reusable workflow patterns.

### Fan-Out/Fan-In

```python
from aragora.workflow.patterns import fan_out_fan_in

workflow = fan_out_fan_in(
    name="parallel_analysis",
    fan_out_step="split_data",
    parallel_step="analyze_chunk",
    fan_in_step="merge_results",
)
```

### Retry Pattern

```python
from aragora.workflow.patterns import with_retry

step = with_retry(
    step=verify_step,
    max_retries=3,
    backoff="exponential",
    retry_on=["timeout", "rate_limit"],
)
```

### Conditional Branching

```python
from aragora.workflow.patterns import conditional

workflow = conditional(
    condition="$input.score > 0.8",
    if_true=[publish_step],
    if_false=[review_step, escalate_step],
)
```

## Templates

Aragora ships two template sources:

1. **YAML templates** loaded via `aragora.workflow.template_loader.TemplateLoader`
   from `aragora/workflow/templates/**.yaml`.
2. **Python templates** registered in `aragora.workflow.templates.WORKFLOW_TEMPLATES`
   from `aragora/workflow/templates/*.py` (includes marketing, support, ecommerce,
   and cross-platform workflows).

Selected YAML templates:

| Template | Description |
|----------|-------------|
| `legal/contract_review.yaml` | Contract review workflow |
| `legal/due_diligence.yaml` | Due diligence workflow |
| `healthcare/clinical_review.yaml` | Clinical review workflow |
| `healthcare/hipaa_compliance.yaml` | HIPAA compliance workflow |
| `software/security_audit.yaml` | Software security audit |
| `software/code_review.yaml` | Code review workflow |
| `accounting/financial_audit.yaml` | Financial audit workflow |
| `regulatory/compliance_assessment.yaml` | Regulatory compliance |
| `academic/citation_verification.yaml` | Citation verification |
| `finance/investment_analysis.yaml` | Investment analysis |
| `general/research.yaml` | Research workflow |
| `maintenance/knowledge_maintenance.yaml` | Knowledge maintenance |

Selected Python templates (registry IDs):

| Template ID | Description |
|-------------|-------------|
| `marketing/ad-performance-review` | Multi-agent ad performance analysis |
| `marketing/lead-to-crm-sync` | Lead enrichment + CRM sync |
| `marketing/cross-platform-analytics` | Unified analytics reporting |
| `support/ticket-triage` | Support triage + response suggestions |
| `ecommerce/order-sync` | Cross-platform order sync |

### Using Templates

```python
from aragora.workflow.template_loader import get_template_loader
from aragora.workflow.templates import get_template

# YAML template (WorkflowDefinition)
loader = get_template_loader()
yaml_template = loader.get_template("template_legal_contract_review")

# Python template (dict-based registry)
workflow = get_template("marketing/ad-performance-review")

result = await engine.execute(workflow, inputs)
```

## Engine Features

### Parallel Execution

```python
from aragora.workflow import WorkflowEngineV2

engine = WorkflowEngineV2(
    max_parallel=10,
    timeout_per_step=300,
)

# Steps without dependencies run in parallel
result = await engine.execute(workflow, inputs)
```

### Checkpointing

```python
from aragora.workflow.checkpoint_store import CheckpointStore

store = CheckpointStore(storage_path="./checkpoints")

# Resume from checkpoint
result = await engine.execute(
    workflow,
    inputs,
    checkpoint_store=store,
    resume_from="step_3"  # Skip completed steps
)
```

### Persistent Storage

```python
from aragora.workflow.persistent_store import get_workflow_store, get_async_workflow_store

# SQLite (sync)
store = get_workflow_store()
store.save_execution(
    {
        "id": "exec_123",
        "workflow_id": "wf_123",
        "status": "completed",
        "inputs": {"doc": "example"},
        "outputs": {"summary": "ok"},
    }
)

# PostgreSQL (async, requires DATABASE_URL + asyncpg)
store = await get_async_workflow_store()
await store.save_execution(
    {
        "id": "exec_456",
        "workflow_id": "wf_123",
        "status": "completed",
        "inputs": {"doc": "example"},
        "outputs": {"summary": "ok"},
    }
)
```

## Safe Evaluation

The `safe_eval.py` module provides sandboxed expression evaluation:

```python
from aragora.workflow.safe_eval import safe_eval

# Evaluate expressions safely
result = safe_eval(
    expression="$data.score > 0.8 and $data.verified",
    context={"data": {"score": 0.9, "verified": True}}
)
# Returns: True
```

Supported operations:
- Arithmetic: `+`, `-`, `*`, `/`, `%`
- Comparison: `>`, `<`, `>=`, `<=`, `==`, `!=`
- Logical: `and`, `or`, `not`
- Access: `$var`, `$var.field`, `$var[index]`

## API Endpoints

The workflow engine is exposed via WorkflowHandler:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/workflows` | GET | List workflow templates |
| `/api/workflows` | POST | Create workflow execution |
| `/api/workflows/{id}` | GET | Get execution status |
| `/api/workflows/{id}/cancel` | POST | Cancel execution |
| `/api/workflows/{id}/retry` | POST | Retry failed execution |

## Configuration

```python
engine = WorkflowEngine(
    # Execution limits
    max_parallel_steps=10,
    step_timeout_seconds=300,
    total_timeout_seconds=3600,

    # Retry settings
    default_retries=3,
    retry_backoff="exponential",

    # Storage
    checkpoint_enabled=True,
    checkpoint_interval=5,  # Every 5 steps
)
```

## See Also

- [HANDLERS.md](../reference/HANDLERS.md) - WorkflowHandler documentation
- [QUEUE.md](../resilience/QUEUE.md) - Job queue management
- [OPERATIONS.md](../operations/OPERATIONS.md) - Operational workflows
