"""
Shared types for the autonomous orchestration system.

Contains enums, dataclasses, and constants used across AgentRouter,
FeedbackLoop, and AutonomousOrchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from aragora.nomic.task_decomposer import SubTask


class BudgetExceededError(RuntimeError):
    """Raised when the orchestration budget limit is exceeded."""

    def __init__(self, limit: float, spent: float):
        self.limit = limit
        self.spent = spent
        super().__init__(f"Budget ${limit:.2f} exceeded (spent ${spent:.2f})")


class Track(Enum):
    """Development tracks for domain-based routing."""

    SME = "sme"  # Small business features
    DEVELOPER = "developer"  # SDK, API, docs
    SELF_HOSTED = "self_hosted"  # Docker, deployment, ops
    QA = "qa"  # Tests, CI/CD
    CORE = "core"  # Core debate engine (requires approval)
    SECURITY = "security"  # Vulnerability scanning, auth hardening, OWASP


# Agents that have dedicated agentic coding harnesses (can edit files autonomously)
AGENTS_WITH_CODING_HARNESS = {"claude", "codex"}

# Mapping from model types to their KiloCode provider_id for coding tasks
# These models don't have dedicated harnesses but can use KiloCode
KILOCODE_PROVIDER_MAPPING = {
    "gemini": "google/gemini-3.1-pro",  # Gemini via OpenRouter
    "gemini-cli": "google/gemini-3.1-pro",
    "grok": "openrouter/x-ai/grok-4.5",  # Grok via OpenRouter
    "grok-cli": "openrouter/x-ai/grok-4.5",
    "deepseek": "openrouter/deepseek/deepseek-v4-pro",  # DeepSeek via OpenRouter
    "qwen": "openrouter/qwen/qwen-2.5-coder-32b-instruct",  # Qwen via OpenRouter
}


@dataclass
class TrackConfig:
    """Configuration for a development track."""

    name: str
    folders: list[str]  # Folders this track owns
    protected_folders: list[str] = field(default_factory=list)  # Cannot modify
    agent_types: list[str] = field(default_factory=list)  # Preferred agents
    max_concurrent_tasks: int = 2
    # Whether to use KiloCode as coding harness for models without one
    use_kilocode_harness: bool = True


# Default track configurations aligned with AGENT_ASSIGNMENTS.md
DEFAULT_TRACK_CONFIGS: dict[Track, TrackConfig] = {
    Track.SME: TrackConfig(
        name="SME",
        folders=["aragora/live/", "aragora/server/handlers/"],
        protected_folders=["aragora/debate/", "aragora/agents/", "aragora/core/"],
        agent_types=["claude", "gemini"],
        max_concurrent_tasks=2,
    ),
    Track.DEVELOPER: TrackConfig(
        name="Developer",
        folders=["sdk/", "docs/", "tests/sdk/"],
        protected_folders=["aragora/debate/", "aragora/live/src/app/"],
        agent_types=["claude", "codex"],
        max_concurrent_tasks=2,
    ),
    Track.SELF_HOSTED: TrackConfig(
        name="Self-Hosted",
        folders=["scripts/", "docker/", "docs/deployment/", "aragora/backup/"],
        protected_folders=["aragora/debate/", "aragora/server/handlers/"],
        agent_types=["claude", "codex"],
        max_concurrent_tasks=1,
    ),
    Track.QA: TrackConfig(
        name="QA",
        folders=["tests/", "aragora/live/e2e/", ".github/workflows/"],
        protected_folders=["aragora/debate/"],
        agent_types=["claude", "gemini"],
        max_concurrent_tasks=3,
    ),
    Track.CORE: TrackConfig(
        name="Core",
        folders=["aragora/debate/", "aragora/agents/", "aragora/memory/"],
        protected_folders=[],  # Can modify core, but requires approval
        agent_types=["claude"],  # Only Claude for core changes
        max_concurrent_tasks=1,
    ),
    Track.SECURITY: TrackConfig(
        name="Security",
        folders=["aragora/security/", "aragora/audit/", "aragora/auth/", "aragora/rbac/"],
        protected_folders=["aragora/debate/"],  # Don't modify core debate
        agent_types=["claude"],  # Claude for security audits
        max_concurrent_tasks=2,
    ),
}


@dataclass
class HierarchyConfig:
    """Configuration for Planner/Worker/Judge agent hierarchy.

    When enabled, the orchestration workflow becomes:
      1. Planner designs the solution (design step)
      2. Plan approval gate: judge reviews the plan before implementation
      3. Workers implement the changes (implement step)
      4. Standard verification (verify step)
      5. Judge reviews the final result before completion

    This separation of concerns ensures no single agent both designs and
    approves its own work, improving quality and catching design flaws early.
    """

    enabled: bool = False

    # The planner agent handles design/decomposition (defaults to orchestrator's choice)
    planner_agent: str = "claude"

    # Worker agents handle implementation (list allows round-robin or selection)
    worker_agents: list[str] = field(default_factory=lambda: ["claude", "codex"])

    # The judge agent reviews plans and final output (should differ from planner)
    judge_agent: str = "claude"

    # Whether the plan approval gate blocks on rejection (vs. warning-only)
    plan_gate_blocking: bool = True

    # Whether the final judge review blocks on rejection
    final_review_blocking: bool = True

    # Maximum plan revision attempts before escalating
    max_plan_revisions: int = 2


@dataclass
class AgentAssignment:
    """Assignment of a subtask to an agent."""

    subtask: SubTask
    track: Track
    agent_type: str
    priority: int = 0
    status: str = "pending"  # pending, running, completed, failed
    attempt_count: int = 0
    max_attempts: int = 3
    result: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_hints: list[str] = field(default_factory=list)


@dataclass
class OrchestrationResult:
    """Result of an orchestration run."""

    goal: str
    total_subtasks: int
    completed_subtasks: int
    failed_subtasks: int
    skipped_subtasks: int
    assignments: list[AgentAssignment]
    duration_seconds: float
    success: bool
    error: str | None = None
    summary: str = ""
    # Measurement layer: objective improvement tracking
    baseline_metrics: dict[str, Any] | None = None
    after_metrics: dict[str, Any] | None = None
    metrics_delta: dict[str, Any] | None = None
    improvement_score: float = 0.0  # 0.0-1.0, from MetricsDelta
    success_criteria_met: bool | None = None  # True if all criteria satisfied
