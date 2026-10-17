"""Post-Debate configuration and result data types.

Extracted from ``post_debate_coordinator.py`` to keep data definitions
separate from orchestration logic.  Everything exported here is re-exported
from ``post_debate_coordinator`` for backwards compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aragora.types.execution_mode import ExecutionMode


@dataclass
class PostDebateConfig:
    """Configuration for the post-debate processing pipeline."""

    execution_mode: ExecutionMode = ExecutionMode.AUTONOMOUS
    auto_explain: bool = True
    auto_create_plan: bool = True
    auto_notify: bool = True
    auto_execute_plan: bool = False
    auto_create_pr: bool = False  # Create draft PR for code-related debates
    pr_min_confidence: float = 0.8  # Higher confidence bar for PRs
    auto_build_integrity_package: bool = False
    auto_persist_receipt: bool = True
    auto_gauntlet_validate: bool = False
    gauntlet_min_confidence: float = 0.85
    auto_verify_arguments: bool = False
    auto_queue_improvement: bool = True
    improvement_min_confidence: float = 0.8
    plan_min_confidence: float = 0.7
    plan_approval_mode: str = "risk_based"
    # Calibration → blockchain reputation: push Brier scores to ERC-8004
    auto_push_calibration: bool = False
    calibration_min_predictions: int = 5  # Min predictions before pushing
    # Staking: reward/penalize agents based on epistemic accuracy post-debate
    enable_staking: bool = False
    staking_reward_scale: float = 1.0  # Multiplier for staking rewards
    staking_slash_on_hollow_consensus: bool = True  # Slash when Trickster detects hollow consensus
    # Receipt blockchain anchoring: anchor receipt hash on-chain via ERC-8004
    auto_anchor_receipt: bool = False
    # ELO-to-ReputationRegistry sync: push ELO adjustments as on-chain feedback
    auto_sync_elo_reputation: bool = False
    # Outcome feedback: feed systematic errors back to Nomic Loop
    auto_outcome_feedback: bool = True
    # Canvas pipeline: auto-trigger idea-to-execution visualization
    auto_trigger_canvas: bool = True
    canvas_min_confidence: float = 0.7
    # Execution bridge: auto-trigger downstream actions
    auto_execution_bridge: bool = True
    execution_bridge_min_confidence: float = 0.0  # Bridge has per-rule thresholds
    # Execution safety gate: enforce signed-receipt + diversity + taint checks
    enforce_execution_safety_gate: bool = True
    execution_gate_require_verified_signed_receipt: bool = True
    execution_gate_enforce_receipt_signer_allowlist: bool = False
    execution_gate_allowed_receipt_signer_keys: tuple[str, ...] = ()
    execution_gate_require_signed_receipt_timestamp: bool = True
    execution_gate_receipt_max_age_seconds: int = 86400
    execution_gate_receipt_max_future_skew_seconds: int = 120
    execution_gate_min_provider_diversity: int = 2
    execution_gate_min_model_family_diversity: int = 2
    execution_gate_block_on_context_taint: bool = True
    execution_gate_block_on_high_severity_dissent: bool = True
    execution_gate_high_severity_dissent_threshold: float = 0.7
    # Require receipt to be persisted *before* execution gate (trust-wedge fix).
    # When True the execution safety gate validates a previously-persisted,
    # signed receipt rather than building one inline.
    require_persisted_receipt: bool = True
    # Settlement tracking: extract verifiable claims for future resolution
    auto_settlement_tracking: bool = False
    settlement_min_confidence: float = 0.3  # Min claim confidence for settlement
    settlement_domain: str = "general"  # Default domain for settlement bucketing
    # LLM-as-Judge: quality evaluation of agent contributions
    auto_llm_judge: bool = True
    llm_judge_use_case: str = "debate"
    llm_judge_threshold: float = 4.0
    # Knowledge Mound outcome ingestion: store high-confidence conclusions
    auto_ingest_outcome: bool = True
    ingest_outcome_min_confidence: float = 0.85


@dataclass
class PostDebateResult:
    """Result of the post-debate processing pipeline.

    Each field represents the output of a pipeline step,
    available as context for subsequent steps.
    """

    debate_id: str = ""
    run_id: str | None = None
    explanation: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    notification_sent: bool = False
    execution_result: dict[str, Any] | None = None
    execution_gate: dict[str, Any] | None = None
    pr_result: dict[str, Any] | None = None
    integrity_package: dict[str, Any] | None = None
    receipt_persisted: bool = False
    receipt_id: str | None = None  # ID of persisted signed receipt (trust-wedge)
    gauntlet_result: dict[str, Any] | None = None
    argument_verification: dict[str, Any] | None = None
    improvement_queued: bool = False
    outcome_feedback: dict[str, Any] | None = None
    canvas_result: dict[str, Any] | None = None
    pipeline_id: str | None = None  # ID of auto-triggered canvas pipeline
    bridge_results: list[dict[str, Any]] = field(default_factory=list)
    llm_judge_scores: dict[str, Any] | None = None
    settlement_batch: dict[str, Any] | None = None
    staking_result: dict[str, Any] | None = None
    receipt_settlement: dict[str, Any] | None = None
    cost_breakdown: dict[str, Any] | None = None
    outcome_ingested: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Pipeline succeeded if no errors occurred."""
        return len(self.errors) == 0
