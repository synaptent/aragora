# Aragora Modes Guide

> **Last Updated:** 2026-03-04

Operational modes for focused AI agent behavior. Modes control what tools an agent can use and provide specialized system prompts for different tasks.

## Related Documentation

| Document | Purpose |
|----------|---------|
| **MODES_GUIDE.md** (this) | Operational modes (Architect, Coder, etc.) + advanced debate modes |
| [PIPELINE_GUIDE.md](PIPELINE_GUIDE.md) | Idea-to-Execution pipeline (uses modes per stage) |
| [GAUNTLET.md](../debate/GAUNTLET.md) | Comprehensive stress-testing |
| [PROBE_STRATEGIES.md](../debate/PROBE_STRATEGIES.md) | Probing strategies reference |

## Overview

Aragora provides two complementary mode systems:

1. **Operational Modes** (Kilocode-inspired) — Architect, Coder, Reviewer, Debugger, Orchestrator, EpistemicHygiene. Each mode controls tool permissions and sets a focused system prompt.
2. **Debate Modes** — RedTeam, DeepAudit, CapabilityProber. Specialized debate protocols for adversarial testing and high-stakes decisions. Heavy submodules; loaded lazily to avoid scipy/numpy import at startup.

Each mode defines:
- **Tool Permissions**: Which tool groups the agent can access
- **File Patterns**: Optional file access restrictions
- **System Prompt**: Behavioral guidelines for the mode

---

## Standard Operational Modes

### Available Modes

| Mode | Tools | Use Case |
|------|-------|----------|
| **Architect** | Read, Browser | Design and planning |
| **Coder** | Read, Edit, Command | Implementation |
| **Debugger** | Read, Edit, Command | Bug investigation |
| **Reviewer** | Read, Browser | Code review |
| **Orchestrator** | Full access | Complex workflows |
| **EpistemicHygiene** | Read, Browser, Debate | Rigorous reasoning enforcement |

### Activating a Mode

```python
from aragora.modes import load_builtins, ArchitectMode
from aragora.modes.base import ModeRegistry

# Ensure built-ins are registered
load_builtins()

# Activate by instance
mode = ArchitectMode()
agent.set_mode(mode)

# Or look up by name
mode = ModeRegistry.get("architect")
```

---

### Architect Mode

**Purpose**: High-level design and planning without implementation.

**Tools**: `READ`, `BROWSER` (read-only)

**Best For**:
- Understanding codebase architecture
- Designing new features or systems
- Planning refactoring efforts
- Analyzing dependencies and patterns

**Restrictions**: Cannot edit or write files; cannot execute commands.

```python
from aragora.modes.builtin import ArchitectMode

mode = ArchitectMode()
agent.set_mode(mode)
response = agent.run("Analyze the authentication system architecture")
```

---

### Coder Mode

**Purpose**: Implementation with full development capabilities.

**Tools**: `READ`, `EDIT`, `COMMAND`

**Best For**: Writing new features, implementing bug fixes, refactoring, creating tests.

**Guidelines**: Match existing code style, make minimal changes, no over-engineering.

```python
from aragora.modes.builtin import CoderMode

mode = CoderMode()
agent.set_mode(mode)
response = agent.run("Implement the user registration endpoint")
```

---

### Debugger Mode

**Purpose**: Investigation and bug fixing.

**Tools**: `READ`, `EDIT`, `COMMAND`

**Methodology**: Reproduce → Isolate → Understand → Fix (root cause only) → Verify.

```python
from aragora.modes.builtin import DebuggerMode

mode = DebuggerMode()
agent.set_mode(mode)
response = agent.run("Bug: users can't log in after password reset")
```

---

### Reviewer Mode

**Purpose**: Code review and quality analysis.

**Tools**: `READ`, `BROWSER` (read-only)

**Review dimensions**: Correctness, Security (OWASP Top 10), Performance, Maintainability.

**Output**: Per-issue reports with Location, Severity (Critical/High/Medium/Low), Description, Impact, and suggested fix.

```python
from aragora.modes.builtin import ReviewerMode

mode = ReviewerMode()
agent.set_mode(mode)
response = agent.run("Review the authentication handler at auth.py")
```

---

### Orchestrator Mode

**Purpose**: Coordinate complex multi-step workflows.

**Tools**: `FULL` (Read, Edit, Command, Browser, MCP, Debate)

**Best For**: Tasks requiring multiple modes, workflows with dependencies, synthesizing results from multiple agents.

```python
from aragora.modes.builtin import OrchestratorMode

mode = OrchestratorMode()
agent.set_mode(mode)
response = agent.run("""
Build a user notification system:
1. Design the architecture
2. Implement the backend
3. Review for security issues
4. Fix any problems found
""")
```

---

### EpistemicHygiene Mode

**Purpose**: Enforce rigorous reasoning standards in debates.

**Tools**: `READ`, `BROWSER`, `DEBATE`

**Best For**: High-stakes decisions where sloppy reasoning is costly; debates that need to surface hidden assumptions.

When activated, this mode requires every agent response to include:
1. **Alternatives Considered** — at least one rejected alternative with explicit reasoning
2. **Falsifiability** — conditions under which the claim would be proven wrong
3. **Confidence Bounds** — numeric or qualitative uncertainty acknowledgment
4. **Explicit Unknowns** — what the agent does not know

Protocol flags trigger prompt injection and consensus penalties for proposals that skip these sections.

```python
from aragora.modes.builtin import EpistemicHygieneMode

mode = EpistemicHygieneMode()
agent.set_mode(mode)
```

---

## Advanced Debate Modes

These modules are lazily imported — they pull in `aragora.debate.orchestrator` (scipy/numpy) only when accessed.

### RedTeam Mode

**Purpose**: Adversarial attack/defend cycles to stress-test proposals.

**Attack types**: logical fallacy detection, edge case exposure, unstated assumption extraction, counterexamples, scalability stress, security vulnerabilities, adversarial inputs, resource exhaustion, race conditions, dependency failures.

**Structure**: Each `RedTeamRound` has a phase (`attack`, `defend`, `steelman`, `strawman`). Attacks have `severity` and `exploitability` scores; defenses are classified as `refute`, `acknowledge`, `mitigate`, or `accept`.

```python
from aragora.modes import RedTeamMode, RedTeamProtocol

protocol = RedTeamProtocol(rounds=3)
mode = RedTeamMode(protocol=protocol)

# Convenience functions for common cases
from aragora.modes import redteam_code_review, redteam_policy

result = await redteam_code_review(agents, code_diff)
result = await redteam_policy(agents, policy_text)
```

---

### DeepAudit Mode

**Purpose**: Six-round intensive debate with cognitive role rotation for high-stakes decisions.

**Inspired by**: Heavy3.ai protocol.

**Cognitive roles**: Analyst, Skeptic, Lateral Thinker, Advocate — rotated across rounds, with a Synthesizer cross-examination in the final round.

**Best For**: Strategy decisions, contract review, code architecture audits, legal documentation.

**Preset audit types**:
- `CODE_ARCHITECTURE_AUDIT` — architectural soundness, coupling, scalability
- `CONTRACT_AUDIT` — clause risk, obligation gaps, termination conditions
- `STRATEGY_AUDIT` — market assumptions, competitive risk, execution feasibility

```python
from aragora.modes import (
    DeepAuditOrchestrator,
    DeepAuditConfig,
    run_deep_audit,
    CODE_ARCHITECTURE_AUDIT,
    CONTRACT_AUDIT,
    STRATEGY_AUDIT,
)

# Use a preset
verdict = await run_deep_audit(
    subject="Proposed microservices migration",
    agents=my_agents,
    config=CODE_ARCHITECTURE_AUDIT,
)

# Custom config
config = DeepAuditConfig(
    rounds=6,
    enable_research=True,       # Web research between rounds
    require_citations=True,
    risk_threshold=0.7,         # Flag findings above this severity
    cross_examination_depth=3,  # Questions per finding
)
verdict = await run_deep_audit(subject=my_subject, agents=my_agents, config=config)

print(verdict.findings)         # List[AuditFinding]
print(verdict.consensus_score)
```

---

### CapabilityProber

**Purpose**: Systematically probe agents to detect reliability failures before promoting them.

**Probe types**: ContradictionTrap, HallucinationBait, SycophancyTest, PersistenceChallenge, ConfidenceCalibrationProbe, ReasoningDepthProbe, EdgeCaseProbe, InstructionInjectionProbe, CapabilityExaggerationProbe.

**ELO integration**: Probe results feed into ELO adjustments, creating evolutionary pressure for more robust agents.

```python
from aragora.modes import (
    CapabilityProber,
    ProbeBeforePromote,
    ContradictionTrap,
    HallucinationBait,
    SycophancyTest,
    VulnerabilityReport,
    generate_probe_report_markdown,
)

# Probe before adding an agent to a high-stakes debate
prober = CapabilityProber()
report: VulnerabilityReport = await prober.probe(
    agent=candidate_agent,
    strategies=[ContradictionTrap(), HallucinationBait(), SycophancyTest()],
)

# Gate on results
gate = ProbeBeforePromote(threshold=0.7)
if gate.should_promote(report):
    arena.add_agent(candidate_agent)

# Generate markdown report
print(generate_probe_report_markdown(report))
```

---

## Tool Groups

| Group | Capabilities |
|-------|--------------|
| `READ` | Read files, glob, grep |
| `EDIT` | Edit, write files |
| `COMMAND` | Execute shell commands |
| `BROWSER` | Web fetch, web search |
| `MCP` | MCP server tools |
| `DEBATE` | Debate participation |

```python
from aragora.modes.tool_groups import ToolGroup

READONLY  = ToolGroup.READ | ToolGroup.BROWSER
DEVELOPER = ToolGroup.READ | ToolGroup.EDIT | ToolGroup.COMMAND
FULL      = ToolGroup.READ | ToolGroup.EDIT | ToolGroup.COMMAND | ToolGroup.BROWSER | ToolGroup.MCP | ToolGroup.DEBATE
```

---

## Creating Custom Modes

```python
from dataclasses import dataclass, field
from aragora.modes.base import Mode
from aragora.modes.tool_groups import ToolGroup

@dataclass
class SecurityAuditorMode(Mode):
    name: str = "security_auditor"
    description: str = "Security audit mode with read-only access"
    tool_groups: ToolGroup = field(
        default_factory=lambda: ToolGroup.READ | ToolGroup.BROWSER
    )
    file_patterns: list[str] = field(default_factory=list)

    def get_system_prompt(self) -> str:
        return """## Security Auditor Mode
Focus on OWASP Top 10, authentication gaps, and input validation.
DO NOT edit files — produce a security report only.
"""
```

Custom modes can also be loaded from YAML via `CustomModeLoader`.

---

## Mode Registry

```python
from aragora.modes.base import ModeRegistry

modes = ModeRegistry.list_all()
# ['architect', 'coder', 'debugger', 'reviewer', 'orchestrator', 'epistemic_hygiene']

mode = ModeRegistry.get("architect")
mode = ModeRegistry.get_or_raise("invalid")  # Raises KeyError
```

---

## Best Practices

| Starting Task | Recommended Mode |
|---------------|------------------|
| "Add feature X" | Architect → Coder |
| "Fix bug in Y" | Debugger |
| "Review PR #123" | Reviewer |
| "Build entire system" | Orchestrator |
| "Evaluate vendor contract" | DeepAudit (CONTRACT_AUDIT) |
| "Red-team this policy" | RedTeam |
| "Test this new agent" | CapabilityProber → ProbeBeforePromote |
| "High-stakes strategy debate" | EpistemicHygiene |

For complex tasks, transition through modes:

```
Architect (understand/plan) → Coder (implement) → Reviewer (verify) → Debugger (if issues found)
```

---

## See Also

- [PROBE_STRATEGIES.md](../debate/PROBE_STRATEGIES.md) — Red-teaming and capability testing
- [AGENT_SELECTION.md](../debate/AGENT_SELECTION.md) — Choosing agents for debates
- [PIPELINE_GUIDE.md](PIPELINE_GUIDE.md) — Pipeline mode assignments per stage
