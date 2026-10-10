"""Planning data models for ``MetaPlanner``: prioritized goals, the evidence-bearing
repository planning result, cross-cycle learnings, planning context and planner config.

Import them from ``aragora.nomic.meta_planner``, which re-exports every name here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.nomic.types import Track

if TYPE_CHECKING:
    from aragora.core_types import DebateResult
    from aragora.gauntlet.receipt_models import DecisionReceipt
    from aragora.nomic.repository_profile import ContextPack


@dataclass
class PrioritizedGoal:
    """A prioritized improvement goal."""

    id: str
    track: Track
    description: str
    rationale: str
    estimated_impact: str  # high, medium, low
    priority: int  # 1 = highest
    focus_areas: list[str] = field(default_factory=list)
    file_hints: list[str] = field(default_factory=list)
    criterion_scores: dict[str, float] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the additive planning-goal shape."""
        return {
            "id": self.id,
            "track": self.track.value,
            "description": self.description,
            "rationale": self.rationale,
            "estimated_impact": self.estimated_impact,
            "priority": self.priority,
            "focus_areas": list(self.focus_areas),
            "file_hints": list(self.file_hints),
            "criterion_scores": dict(sorted(self.criterion_scores.items())),
            "evidence_refs": sorted(self.evidence_refs),
            "metadata": dict(self.metadata),
        }


@dataclass
class MetaPlanningResult:
    """Evidence-bearing result from generic repository planning."""

    objective: str
    context_pack: ContextPack
    goals: list[PrioritizedGoal]
    receipt: DecisionReceipt
    evidence_coverage: float
    substantive_debate: bool
    receipt_json_path: Path
    receipt_markdown_path: Path
    debate_result: DebateResult = field(repr=False)

    @property
    def status(self) -> str:
        return "planned" if self.receipt.verdict != "NO_EVIDENCE" else "no_evidence"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "objective": self.objective,
            "repository_id": self.context_pack.repository.repository_id,
            "commit_sha": self.context_pack.revision.commit_sha,
            "profile_hash": self.context_pack.profile_hash,
            "pack_id": self.context_pack.pack_id,
            "pack_reference": self.context_pack.reference,
            "goals": [goal.to_dict() for goal in self.goals],
            "evidence_coverage": self.evidence_coverage,
            "substantive_debate": self.substantive_debate,
            "verdict": self.receipt.verdict,
            "receipt": self.receipt.to_dict(),
            "receipt_json_path": str(self.receipt_json_path),
            "receipt_markdown_path": str(self.receipt_markdown_path),
        }


@dataclass
class HistoricalLearning:
    """Learning from a past Nomic cycle."""

    cycle_id: str
    objective: str
    was_success: bool
    lesson: str
    relevance: float  # 0-1, how relevant to current objective


@dataclass
class PlanningContext:
    """Context for meta-planning decisions."""

    recent_issues: list[str] = field(default_factory=list)
    test_failures: list[str] = field(default_factory=list)
    user_feedback: list[str] = field(default_factory=list)
    recent_changes: list[str] = field(default_factory=list)
    # Externally supplied candidate goals the debate must evaluate and rank.
    # Unlike recent_issues (background context, capped at 5 in the topic),
    # every candidate is rendered into the debate topic.
    candidate_goals: list[str] = field(default_factory=list)
    # Cross-cycle learning
    historical_learnings: list[HistoricalLearning] = field(default_factory=list)
    past_failures_to_avoid: list[str] = field(default_factory=list)
    past_successes_to_build_on: list[str] = field(default_factory=list)
    # CI feedback
    ci_failures: list[str] = field(default_factory=list)
    ci_flaky_tests: list[str] = field(default_factory=list)
    # Debate-sourced improvement suggestions
    recent_improvements: list[dict[str, Any]] = field(default_factory=list)
    # Codebase metrics snapshot (from MetricsCollector)
    metric_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetaPlannerConfig:
    """Configuration for MetaPlanner."""

    agents: list[str] = field(default_factory=lambda: ["claude", "gemini", "deepseek"])
    debate_rounds: int = 2
    max_goals: int = 5
    consensus_threshold: float = 0.6
    # Optional proposal-only timeout; None preserves the Arena default.
    proposal_timeout_seconds: float | None = None
    # Cross-cycle learning
    enable_cross_cycle_learning: bool = True
    max_similar_cycles: int = 5
    min_cycle_similarity: float = 0.5
    # Quick mode: skip debate, use heuristic for concrete goals
    quick_mode: bool = False
    # Use introspection data to select agents for planning debates
    use_introspection_selection: bool = True
    # Trickster: detect hollow consensus in self-improvement debates
    enable_trickster: bool = True
    trickster_sensitivity: float = 0.7
    # Convergence detection for semantic consensus
    enable_convergence: bool = True
    # Generate DecisionReceipts for self-improvement decisions
    enable_receipts: bool = True
    # Inject codebase metrics into planning context
    enable_metrics_collection: bool = True
    # Scan mode: prioritize from codebase signals without LLM calls
    scan_mode: bool = False
    # Auto-execute low-risk goals (test fixes, doc updates, lint) without approval
    auto_execute_low_risk: bool = False
    # Risk threshold: goals scoring below this are considered "low risk"
    low_risk_threshold: float = 0.3
    # Generate self-explanations for planning decisions
    explain_decisions: bool = True
    # Use business context to re-rank goals by impact
    use_business_context: bool = True
    # Objective fidelity recovery
    enforce_objective_fidelity: bool = True
    objective_fidelity_threshold: float = 0.2
    # Opt-in: include OpenRouter Fusion (multi-model council+judge) as an extra
    # participant in planning debates. Default OFF -- Fusion is ~4-5x cost. Also
    # gated globally by the enable_fusion feature flag and a positive
    # fusion_cost_budget_per_debate (set the budget to 0 to hard-disable).
    enable_fusion: bool = False
    # Repository root used by every local scan and by generic planning publication.
    repo_path: str = "."


__all__ = [
    "HistoricalLearning",
    "MetaPlannerConfig",
    "MetaPlanningResult",
    "PlanningContext",
    "PrioritizedGoal",
]
