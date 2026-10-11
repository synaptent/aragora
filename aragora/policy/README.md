# Policy Module

Per-tool and per-task policy enforcement for enterprise trust and safety.

## Quick Start

```python
from aragora.policy import PolicyEngine, Tool, RiskLevel

engine = PolicyEngine()

# Register a tool with its capabilities
engine.register_tool(Tool(
    name="code_writer",
    capabilities=["write_file", "create_file", "delete_file"],
    risk_level=RiskLevel.HIGH,
    requires_human_approval=True,
))

# Check if an action is allowed
result = engine.check_action(
    agent="claude",
    tool="code_writer",
    capability="write_file",
    context={"file_path": "src/core.py"},
)

if result.allowed:
    # Proceed
    pass
elif result.requires_human_approval:
    await request_human_approval(result)
else:
    raise PolicyViolation(result.reason)
```

## Key Components

| File | Purpose |
|------|---------|
| `engine.py` | PolicyEngine, Policy, PolicyResult, PolicyViolation |
| `tools.py` | Tool definitions, ToolCapability, ToolRegistry |
| `risk.py` | RiskLevel, BlastRadius, RiskBudget |

## Architecture

```
policy/
├── engine.py        # Core policy evaluation engine
│   ├── PolicyEngine     # Main engine class
│   ├── Policy           # Individual policy rules
│   ├── PolicyResult     # Evaluation result
│   ├── PolicyDecision   # ALLOW, DENY, ESCALATE
│   └── PolicyViolation  # Exception for violations
├── tools.py         # Tool definitions
│   ├── Tool             # Tool with capabilities
│   ├── ToolCapability   # Named capability
│   └── ToolRegistry     # Central tool registry
└── risk.py          # Risk assessment
    ├── RiskLevel        # LOW, MEDIUM, HIGH, CRITICAL
    ├── BlastRadius      # Impact scope
    └── RiskBudget       # Cumulative risk tracking
```

## Core Concepts

### Policy Decisions

| Decision | Description |
|----------|-------------|
| `ALLOW` | Action is permitted |
| `DENY` | Action is forbidden |
| `ESCALATE` | Requires human approval |
| `BUDGET_EXCEEDED` | Risk budget exhausted |

### Risk Levels

| Level | Score | Description |
|-------|-------|-------------|
| `LOW` | 1 | Read-only operations |
| `MEDIUM` | 5 | Reversible changes |
| `HIGH` | 15 | Significant changes |
| `CRITICAL` | 50 | Irreversible/dangerous |

### Blast Radius

| Scope | Multiplier | Description |
|-------|------------|-------------|
| `SINGLE_FILE` | 1x | One file affected |
| `DIRECTORY` | 3x | Directory affected |
| `REPOSITORY` | 10x | Entire repo affected |
| `INFRASTRUCTURE` | 25x | External systems |

## Usage Examples

### Define Policies

```python
from aragora.policy import PolicyEngine, Policy

engine = PolicyEngine()

# Block modifications to protected files
engine.add_policy(Policy(
    name="protect_core_files",
    condition="file_path in protected_files",
    decision="deny",
    reason="Core files require admin approval",
    context={
        "protected_files": ["core.py", "CLAUDE.md", "__init__.py"],
    },
))

# Require approval for deletions
engine.add_policy(Policy(
    name="approve_deletions",
    condition="capability == 'delete_file'",
    decision="escalate",
    reason="File deletion requires human approval",
))
```

### Register Tools

```python
from aragora.policy import Tool, ToolCapability, RiskLevel

# Define a tool with its capabilities
file_tool = Tool(
    name="file_manager",
    description="File system operations",
    capabilities=[
        ToolCapability("read_file", RiskLevel.LOW),
        ToolCapability("write_file", RiskLevel.MEDIUM),
        ToolCapability("delete_file", RiskLevel.HIGH),
    ],
    default_risk_level=RiskLevel.MEDIUM,
)

engine.register_tool(file_tool)
```

### Risk Budgets

```python
from aragora.policy import RiskBudget

# Create a budget for a session
budget = RiskBudget(
    total=100,  # Total risk units allowed
    warn_threshold=0.7,  # Warn at 70% usage
    hard_limit=0.95,  # Block at 95% usage
)

engine.set_budget(session_id="sess_123", budget=budget)

# Actions consume risk budget based on:
# risk_cost = risk_level.score * blast_radius.multiplier

# Budget remaining is tracked in PolicyResult
result = engine.check_action(...)
print(f"Budget remaining: {result.budget_remaining}")
```

### Human Approval Flow

```python
result = engine.check_action(
    agent="claude",
    tool="code_writer",
    capability="write_file",
    context={"file_path": "aragora/__init__.py"},
)

if result.requires_human_approval:
    # Create approval request
    approval = await create_approval_request(
        action=result,
        reason=result.reason,
        agent=result.agent,
        tool=result.tool,
    )

    # Wait for human decision
    decision = await wait_for_approval(approval.id)

    if decision.approved:
        # Record approval and proceed
        engine.record_approval(result, decision)
    else:
        raise PolicyViolation(f"Rejected: {decision.reason}")
```

## Integration Points

| Module | Integration |
|--------|-------------|
| `aragora.skills` | Skills check policy before executing |
| `aragora.nomic` | Nomic loop respects policy boundaries |
| `aragora.rbac` | RBAC provides user context |
| `aragora.audit` | Policy decisions are logged |

## Enterprise Features

The policy engine supports enterprise requirements:

- **Auditability**: All policy checks are logged
- **Reversibility**: High-risk actions can require undo plans
- **Escalation**: Configurable approval workflows
- **Risk Budgets**: Prevent runaway agent actions
- **Protected Files**: Absolute blocks on critical files

## Related

- `aragora/rbac/` - Role-based access control
- `aragora/audit/` - Audit logging
- `aragora/nomic/` - Self-improvement safety
- `docs/TRUST_ARCHITECTURE.md` - Enterprise trust design
