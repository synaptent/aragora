"""Canonical handoff artifacts for Aragora's closed-loop backbone.

This module is intentionally thin. It does not replace the existing rich
types in prompt_engine, interrogation, debate, planning, or receipts.
It normalizes those shapes into stable handoff artifacts so the stages can
compose without implicit contracts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid


def propagate_taint(
    source_taint: list[str],
    new_taint: list[str] | None = None,
) -> list[str]:
    """Merge taint flags from upstream stages, deduplicating while preserving order.

    This is the canonical way to carry taint forward through pipeline stages.
    Upstream flags come first, followed by any newly-discovered flags.
    """
    seen: set[str] = set()
    merged: list[str] = []
    for flag in list(source_taint) + list(new_taint or []):
        normalized = flag.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _string_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        value = values.strip()
        return [value] if value else []
    if not isinstance(values, list | tuple):
        return [str(values).strip()] if str(values).strip() else []
    output: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
        elif is_dataclass(value) and not isinstance(value, type):
            text = str(asdict(value))
        else:
            text = str(value).strip()
        if text:
            output.append(text)
    return output


def _criterion_to_text(criterion: Any) -> str:
    if criterion is None:
        return ""
    if isinstance(criterion, str):
        return criterion.strip()
    description = getattr(criterion, "description", "") or ""
    measurement = getattr(criterion, "measurement", "") or ""
    target = getattr(criterion, "target", "") or ""
    parts = [str(description).strip(), str(measurement).strip(), str(target).strip()]
    return " | ".join(part for part in parts if part)


def _risk_mitigations(risks: Any) -> list[str]:
    mitigations: list[str] = []
    if not isinstance(risks, list | tuple):
        return mitigations
    for risk in risks:
        if isinstance(risk, dict):
            mitigation = str(risk.get("mitigation", "")).strip()
        else:
            mitigation = str(getattr(risk, "mitigation", "")).strip()
        if mitigation:
            mitigations.append(mitigation)
    return mitigations


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class IntakeBundle:
    source_kind: str
    raw_intent: str
    context_refs: list[dict[str, Any]] = field(default_factory=list)
    trust_tiers: list[str] = field(default_factory=list)
    origin_metadata: dict[str, Any] = field(default_factory=dict)
    taint_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_prompt_intent(
        cls,
        intent: Any,
        *,
        source_kind: str = "prompt_intent",
        trust_tiers: list[str] | None = None,
        taint_flags: list[str] | None = None,
        origin_metadata: dict[str, Any] | None = None,
    ) -> IntakeBundle:
        return cls(
            source_kind=source_kind,
            raw_intent=str(getattr(intent, "raw_prompt", "")).strip(),
            context_refs=list(getattr(intent, "related_knowledge", []) or []),
            trust_tiers=list(trust_tiers or ["operator-authored"]),
            origin_metadata=dict(origin_metadata or {}),
            taint_flags=list(taint_flags or []),
        )


class BackboneStage(str, Enum):
    """Canonical stages for the golden-path run ledger."""

    INTAKE = "intake"
    INTENT = "intent"
    RESEARCH = "research"
    EXTENSION = "extension"
    SPECIFICATION = "specification"
    GOALS = "goals"
    DELIBERATION = "deliberation"
    PLAN = "plan"
    EXECUTION = "execution"
    RECEIPT = "receipt"
    FEEDBACK = "feedback"
    ATTESTATION = "attestation"


@dataclass
class RunStageEvent:
    """Immutable event emitted by one backbone stage."""

    stage: str
    status: str
    event_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:12]}")
    artifact_ref: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        stage: BackboneStage | str,
        *,
        status: str,
        artifact_ref: str = "",
        details: dict[str, Any] | None = None,
    ) -> RunStageEvent:
        stage_name = stage.value if isinstance(stage, BackboneStage) else str(stage).strip()
        return cls(
            stage=stage_name,
            status=str(status).strip() or "unknown",
            artifact_ref=str(artifact_ref).strip(),
            details=dict(details or {}),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunStageEvent:
        return cls(
            stage=str(data.get("stage", "")).strip(),
            status=str(data.get("status", "")).strip(),
            event_id=str(data.get("event_id", "")).strip() or f"evt-{uuid.uuid4().hex[:12]}",
            artifact_ref=str(data.get("artifact_ref", "")).strip(),
            details=dict(data.get("details", {}) or {}),
            created_at=str(data.get("created_at", "")).strip() or _utc_now_iso(),
        )


def build_goal_refs_from_implement_plan(
    implement_plan: Any | None,
    *,
    source_stage: BackboneStage | str = BackboneStage.GOALS,
) -> list[dict[str, Any]]:
    """Project an implementation plan into canonical goal refs."""
    if implement_plan is None:
        return []

    stage_name = (
        source_stage.value if isinstance(source_stage, BackboneStage) else str(source_stage)
    )
    tasks = list(getattr(implement_plan, "tasks", []) or [])
    refs: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        if task is None:
            continue
        task_id = str(getattr(task, "id", "") or f"goal-{index}").strip()
        title = str(getattr(task, "description", "") or task_id).strip()
        refs.append(
            {
                "id": task_id,
                "title": title,
                "source_stage": stage_name,
                "files": list(getattr(task, "files", []) or []),
                "dependencies": list(getattr(task, "dependencies", []) or []),
                "complexity": str(getattr(task, "complexity", "") or ""),
                "task_type": str(getattr(task, "task_type", "") or ""),
                "requires_approval": bool(getattr(task, "requires_approval", False)),
            }
        )
    return refs


@dataclass
class SpecBundle:
    title: str
    problem_statement: str
    objectives: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    verification_plan: list[str] = field(default_factory=list)
    rollback_plan: list[str] = field(default_factory=list)
    owner_file_scopes: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source_kind: str = ""
    provenance_refs: list[dict[str, Any]] = field(default_factory=list)
    taint_flags: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["missing_required_fields"] = list(self.missing_required_fields)
        data["is_execution_grade"] = self.is_execution_grade
        return data

    @property
    def missing_required_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.constraints:
            missing.append("constraints")
        if not self.acceptance_criteria:
            missing.append("acceptance_criteria")
        if not self.verification_plan:
            missing.append("verification_plan")
        if not self.rollback_plan:
            missing.append("rollback_plan")
        if not self.owner_file_scopes:
            missing.append("owner_file_scopes")
        return missing

    @property
    def is_execution_grade(self) -> bool:
        return not self.missing_required_fields

    @classmethod
    def from_prompt_spec(
        cls,
        spec: Any,
        *,
        validation: Any | None = None,
        taint_flags: list[str] | None = None,
    ) -> SpecBundle:
        criteria = [
            text
            for text in (_criterion_to_text(item) for item in getattr(spec, "success_criteria", []))
            if text
        ]
        file_changes = getattr(spec, "file_changes", []) or []
        file_scopes = [
            str(getattr(item, "path", "") or item.get("path", "")).strip()
            for item in file_changes
            if str(getattr(item, "path", "") or item.get("path", "")).strip()
        ]
        provenance = getattr(spec, "provenance", None)
        provenance_to_dict = getattr(provenance, "to_dict", None)
        provenance_refs = [provenance_to_dict()] if callable(provenance_to_dict) else []
        provenance_refs.extend(list(getattr(spec, "provenance_chain", []) or []))

        return cls(
            title=str(getattr(spec, "title", "")).strip() or "Untitled specification",
            problem_statement=str(getattr(spec, "problem_statement", "")).strip(),
            objectives=_string_list(getattr(spec, "proposed_solution", "")),
            constraints=_string_list(getattr(spec, "constraints", [])),
            acceptance_criteria=criteria,
            verification_plan=list(criteria),
            rollback_plan=_risk_mitigations(
                getattr(spec, "risks", []) or getattr(spec, "risk_register", [])
            ),
            owner_file_scopes=file_scopes,
            open_questions=[],
            confidence=float(
                getattr(validation, "overall_confidence", getattr(spec, "confidence", 0.0)) or 0.0
            ),
            source_kind="prompt_engine_spec",
            provenance_refs=provenance_refs,
            taint_flags=list(taint_flags or []),
            extras={"validation_passed": getattr(validation, "passed", None)},
        )

    @classmethod
    def from_interrogation_result(
        cls,
        result: Any,
        *,
        taint_flags: list[str] | None = None,
    ) -> SpecBundle:
        crystallized = getattr(result, "crystallized_spec", None)
        legacy_spec = getattr(result, "spec", None)

        if crystallized is not None and hasattr(crystallized, "requirements"):
            objectives = [
                str(getattr(item, "description", "")).strip()
                for item in getattr(crystallized, "requirements", [])
                if str(getattr(item, "description", "")).strip()
            ]
            constraints = _string_list(getattr(crystallized, "constraints", []))
            rollback_plan = _risk_mitigations(getattr(crystallized, "risks", []))
            title = str(getattr(crystallized, "title", "")).strip() or "Interrogation specification"
            problem_statement = str(getattr(crystallized, "problem_statement", "")).strip()
            acceptance_criteria = _string_list(getattr(crystallized, "success_criteria", []))
        else:
            objectives = [
                str(getattr(item, "description", "")).strip()
                for item in getattr(legacy_spec, "requirements", [])
                if str(getattr(item, "description", "")).strip()
            ]
            constraints = []
            rollback_plan = []
            title = "Interrogation specification"
            problem_statement = str(getattr(legacy_spec, "problem_statement", "")).strip()
            acceptance_criteria = _string_list(getattr(legacy_spec, "success_criteria", []))

        open_questions = []
        for question in getattr(result, "prioritized_questions", []) or []:
            text = str(getattr(question, "question", "")).strip()
            answer = str(getattr(question, "answer", "")).strip()
            if text and not answer:
                open_questions.append(text)

        return cls(
            title=title,
            problem_statement=problem_statement,
            objectives=objectives,
            constraints=constraints,
            acceptance_criteria=acceptance_criteria,
            verification_plan=list(acceptance_criteria),
            rollback_plan=rollback_plan,
            owner_file_scopes=[],
            open_questions=open_questions,
            confidence=0.0,
            source_kind="interrogation_result",
            provenance_refs=[],
            taint_flags=list(taint_flags or []),
            extras={"dimensions": list(getattr(result, "dimensions", []) or [])},
        )

    @classmethod
    def from_interrogation_spec(
        cls,
        spec: Any,
        *,
        open_questions: list[str] | None = None,
        taint_flags: list[str] | None = None,
    ) -> SpecBundle:
        requirements = getattr(spec, "requirements", []) or []
        objectives = [
            str(getattr(item, "description", "")).strip()
            for item in requirements
            if str(getattr(item, "description", "")).strip()
        ]
        acceptance_criteria = _string_list(getattr(spec, "success_criteria", []))
        risks = getattr(spec, "risks", []) or []
        rollback_plan = _string_list(risks)
        return cls(
            title="Interrogation specification",
            problem_statement=str(getattr(spec, "problem_statement", "")).strip(),
            objectives=objectives,
            constraints=[],
            acceptance_criteria=acceptance_criteria,
            verification_plan=list(acceptance_criteria),
            rollback_plan=rollback_plan,
            owner_file_scopes=[],
            open_questions=list(open_questions or []),
            confidence=0.0,
            source_kind="interrogation_spec",
            provenance_refs=[],
            taint_flags=list(taint_flags or []),
            extras={"context_summary": str(getattr(spec, "context_summary", "")).strip()},
        )


@dataclass
class ReceiptEnvelope:
    receipt_id: str
    artifact_hash: str
    verdict: str
    confidence: float = 0.0
    signature: str = ""
    policy_gate_result: dict[str, Any] = field(default_factory=dict)
    provenance_chain: list[dict[str, Any]] = field(default_factory=list)
    taint_summary: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_pipeline_receipt(
        cls,
        receipt: dict[str, Any],
        *,
        policy_gate_result: dict[str, Any] | None = None,
        taint_summary: dict[str, Any] | None = None,
    ) -> ReceiptEnvelope:
        status = str(receipt.get("execution", {}).get("status", "unknown")).strip()
        verdict = "pass" if status in {"completed", "success", "succeeded"} else status or "unknown"
        provenance = receipt.get("provenance", {}) or {}
        flattened_chain: list[dict[str, Any]] = []
        if isinstance(provenance, dict):
            for stage_name, items in provenance.items():
                for item in items or []:
                    if isinstance(item, dict):
                        flattened_chain.append({"stage": stage_name, **item})

        return cls(
            receipt_id=str(receipt.get("receipt_id", "")).strip(),
            artifact_hash=str(
                receipt.get("artifact_hash") or receipt.get("content_hash", "")
            ).strip(),
            verdict=verdict,
            confidence=float(receipt.get("confidence", 0.0) or 0.0),
            signature=str(receipt.get("signature", "")).strip(),
            policy_gate_result=dict(policy_gate_result or {}),
            provenance_chain=flattened_chain,
            taint_summary=dict(taint_summary or {}),
            extras={
                "pipeline_id": receipt.get("pipeline_id"),
                "generated_at": receipt.get("generated_at"),
            },
        )

    @classmethod
    def from_decision_receipt(
        cls,
        receipt: dict[str, Any],
        *,
        policy_gate_result: dict[str, Any] | None = None,
        taint_summary: dict[str, Any] | None = None,
    ) -> ReceiptEnvelope:
        provenance_chain = [
            dict(item)
            for item in list(receipt.get("provenance_chain", []) or [])
            if isinstance(item, dict)
        ]
        return cls(
            receipt_id=str(receipt.get("receipt_id", "")).strip(),
            artifact_hash=str(
                receipt.get("artifact_hash") or receipt.get("input_hash", "")
            ).strip(),
            verdict=str(receipt.get("verdict", "unknown") or "unknown").strip(),
            confidence=float(receipt.get("confidence", 0.0) or 0.0),
            signature=str(receipt.get("signature", "")).strip(),
            policy_gate_result=dict(policy_gate_result or {}),
            provenance_chain=provenance_chain,
            taint_summary=dict(taint_summary or {}),
            extras={
                "gauntlet_id": receipt.get("gauntlet_id"),
                "generated_at": receipt.get("timestamp"),
                "decision_receipt": dict(receipt),
            },
        )


@dataclass
class DeliberationBundle:
    """Stable handoff artifact for debate outputs between pipeline stages.

    Normalizes DebateResult into a shape that preserves provenance, unresolved
    risks, and agent diversity data so downstream stages (planning, receipts,
    outcome feedback) can consume deliberation outputs without depending on the
    full DebateResult object.
    """

    debate_id: str
    verdict: str
    confidence: float = 0.0
    consensus_reached: bool = False
    consensus_strength: str = ""
    quality_verdict: str = "unknown"  # "passed", "failed", "unknown"
    dissenting_views: list[str] = field(default_factory=list)
    unresolved_risks: list[dict[str, Any]] = field(default_factory=list)
    participant_count: int = 0
    diversity_scores: dict[str, float] = field(default_factory=dict)
    provenance_refs: list[dict[str, Any]] = field(default_factory=list)
    trust_tier: str = ""
    taint_flags: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_debate_result(
        cls,
        result: Any,
        *,
        trust_tier: str = "",
        taint_flags: list[str] | None = None,
    ) -> DeliberationBundle:
        """Normalize a DebateResult (or duck-typed equivalent) into a DeliberationBundle."""
        confidence = float(getattr(result, "confidence", 0.0) or 0.0)
        consensus_reached = bool(getattr(result, "consensus_reached", False))
        consensus_strength = str(getattr(result, "consensus_strength", "") or "")

        # Quality verdict: passed when consensus reached and confidence is meaningful
        if consensus_reached and confidence >= 0.5:
            quality_verdict = "passed"
        elif not consensus_reached or confidence < 0.3:
            quality_verdict = "failed"
        else:
            quality_verdict = "unknown"

        dissenting_views = _string_list(getattr(result, "dissenting_views", []))
        # debate_cruxes are contested claims - treat as unresolved risks
        cruxes = list(getattr(result, "debate_cruxes", []) or [])
        unresolved_risks = [c if isinstance(c, dict) else {"claim": str(c)} for c in cruxes]

        participants = list(getattr(result, "participants", []) or [])
        diversity_scores: dict[str, float] = {}
        per_sim = getattr(result, "per_agent_similarity", {}) or {}
        if isinstance(per_sim, dict):
            diversity_scores = {k: float(v) for k, v in per_sim.items()}

        metadata = getattr(result, "metadata", {}) or {}
        provenance_refs = [dict(metadata)] if metadata else []

        return cls(
            debate_id=str(getattr(result, "debate_id", "") or ""),
            verdict=str(getattr(result, "final_answer", "") or ""),
            confidence=confidence,
            consensus_reached=consensus_reached,
            consensus_strength=consensus_strength,
            quality_verdict=quality_verdict,
            dissenting_views=dissenting_views,
            unresolved_risks=unresolved_risks,
            participant_count=len(participants),
            diversity_scores=diversity_scores,
            provenance_refs=provenance_refs,
            trust_tier=str(trust_tier or ""),
            taint_flags=list(taint_flags or []),
            extras={
                "task": str(getattr(result, "task", "") or ""),
                "convergence_status": str(getattr(result, "convergence_status", "") or ""),
                "consensus_variance": float(getattr(result, "consensus_variance", 0.0) or 0.0),
            },
        )


@dataclass
class ExecutionAttemptRecord:
    """Stable handoff artifact for a single execution attempt.

    Normalizes outputs from plan execution and task execution into a compatible
    shape so that receipt generation, outcome feedback, and verification replay
    can consume results without depending on specific executor internals.
    """

    attempt_id: str
    plan_id: str = ""
    status: str = "unknown"  # "succeeded", "failed", "blocked", "unknown"
    tests_passed: int = 0
    tests_failed: int = 0
    files_changed: int = 0
    diff_summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    policy_decision: dict[str, Any] = field(default_factory=dict)
    taint_flags: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    error_message: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_plan_outcome(
        cls,
        outcome: Any,
        *,
        attempt_id: str,
        plan_id: str = "",
        policy_decision: dict[str, Any] | None = None,
        taint_flags: list[str] | None = None,
        artifacts: list[str] | None = None,
        diff_summary: str = "",
    ) -> ExecutionAttemptRecord:
        """Normalize a PipelineOutcome (or duck-typed equivalent) into a stable attempt record."""
        succeeded = bool(getattr(outcome, "execution_succeeded", False))
        status = "succeeded" if succeeded else "failed"

        return cls(
            attempt_id=attempt_id,
            plan_id=plan_id or str(getattr(outcome, "pipeline_id", "") or ""),
            status=status,
            tests_passed=int(getattr(outcome, "tests_passed", 0) or 0),
            tests_failed=int(getattr(outcome, "tests_failed", 0) or 0),
            files_changed=int(getattr(outcome, "files_changed", 0) or 0),
            diff_summary=diff_summary,
            artifacts=list(artifacts or []),
            policy_decision=dict(policy_decision or {}),
            taint_flags=list(taint_flags or []),
            duration_s=float(getattr(outcome, "total_duration_s", 0.0) or 0.0),
            error_message=str(getattr(outcome, "error_message", "") or ""),
            extras={
                "run_type": str(getattr(outcome, "run_type", "") or ""),
                "domain": str(getattr(outcome, "domain", "") or ""),
                "spec_completeness": float(getattr(outcome, "spec_completeness", 0.0) or 0.0),
            },
        )


@dataclass
class OutcomeFeedbackRecord:
    receipt_ref: str
    pipeline_id: str
    run_type: str
    domain: str
    objective_fidelity: float
    quality_outcome: dict[str, Any] = field(default_factory=dict)
    execution_outcome: dict[str, Any] = field(default_factory=dict)
    settlement_hooks: list[dict[str, Any]] = field(default_factory=list)
    calibration_updates: list[dict[str, Any]] = field(default_factory=list)
    next_action_recommendation: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_nomic_goal(self) -> dict[str, str]:
        """Return a MetaLoopTarget-compatible dict for Nomic Loop reprioritization.

        All values are strings so the goal can be consumed directly by MetaPlanner
        without further transformation.
        """
        action = self.next_action_recommendation or "review_manually"

        if action == "run_bug_fix_loop":
            failed = self.execution_outcome.get("tests_failed", 0)
            description = f"Fix {failed} failing test(s) and restore pipeline health"
            priority = "high"
        elif action == "promote_or_settle":
            description = "Verify and promote successful pipeline execution to settlement"
            priority = "low"
        else:
            description = "Review pipeline execution manually and determine next steps"
            priority = "medium"

        fidelity = self.objective_fidelity
        risk = "high" if fidelity < 0.5 else "medium" if fidelity < 0.8 else "low"

        rationale = (
            f"Pipeline {self.pipeline_id!r} completed with fidelity={fidelity:.2f}. "
            f"Receipt: {self.receipt_ref!r}. Recommended action: {action!r}."
        )

        return {
            "module": self.domain or self.run_type or "unknown",
            "description": description,
            "priority": priority,
            "risk": risk,
            "rationale": rationale,
        }

    @classmethod
    def from_pipeline_outcome(
        cls,
        outcome: Any,
        *,
        receipt_ref: str,
        next_action_recommendation: str = "",
    ) -> OutcomeFeedbackRecord:
        quality_score = float(getattr(outcome, "overall_quality_score", 0.0) or 0.0)
        execution_outcome = {
            "execution_succeeded": bool(getattr(outcome, "execution_succeeded", False)),
            "tests_passed": int(getattr(outcome, "tests_passed", 0) or 0),
            "tests_failed": int(getattr(outcome, "tests_failed", 0) or 0),
            "files_changed": int(getattr(outcome, "files_changed", 0) or 0),
            "rollback_triggered": bool(getattr(outcome, "rollback_triggered", False)),
        }
        quality_outcome = {
            "overall_quality_score": quality_score,
            "spec_completeness": float(getattr(outcome, "spec_completeness", 0.0) or 0.0),
            "human_interventions": int(getattr(outcome, "human_interventions", 0) or 0),
        }

        if not next_action_recommendation:
            if execution_outcome["execution_succeeded"]:
                next_action_recommendation = "promote_or_settle"
            elif execution_outcome["tests_failed"] > 0:
                next_action_recommendation = "run_bug_fix_loop"
            else:
                next_action_recommendation = "review_manually"

        return cls(
            receipt_ref=receipt_ref,
            pipeline_id=str(getattr(outcome, "pipeline_id", "")).strip(),
            run_type=str(getattr(outcome, "run_type", "")).strip(),
            domain=str(getattr(outcome, "domain", "")).strip(),
            objective_fidelity=quality_score,
            quality_outcome=quality_outcome,
            execution_outcome=execution_outcome,
            settlement_hooks=[],
            calibration_updates=[],
            next_action_recommendation=next_action_recommendation,
            extras={"total_duration_s": float(getattr(outcome, "total_duration_s", 0.0) or 0.0)},
        )


@dataclass
class RunLedger:
    """Persistent canonical ledger connecting the golden-path stages."""

    run_id: str
    entrypoint: str
    status: str = "received"
    intake_bundle: IntakeBundle | None = None
    spec_bundle: SpecBundle | None = None
    goal_refs: list[dict[str, Any]] = field(default_factory=list)
    deliberation_bundle: DeliberationBundle | None = None
    plan_id: str = ""
    debate_id: str = ""
    execution_id: str = ""
    receipt_id: str = ""
    receipt_envelope: ReceiptEnvelope | None = None
    feedback_record: OutcomeFeedbackRecord | None = None
    attestation: dict[str, Any] = field(default_factory=dict)
    taint_flags: list[str] = field(default_factory=list)
    stage_events: list[RunStageEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def touch(self) -> None:
        self.updated_at = _utc_now_iso()

    def merge_taint(self, taint_flags: list[str] | None = None) -> None:
        self.taint_flags = propagate_taint(self.taint_flags, taint_flags or [])
        self.touch()

    def add_event(self, event: RunStageEvent) -> None:
        self.stage_events.append(event)
        self.updated_at = event.created_at

    def attach_intake(self, bundle: IntakeBundle | None) -> None:
        self.intake_bundle = bundle
        self.merge_taint(getattr(bundle, "taint_flags", []))

    def attach_spec(self, bundle: SpecBundle | None) -> None:
        self.spec_bundle = bundle
        self.merge_taint(getattr(bundle, "taint_flags", []))

    def attach_deliberation(self, bundle: DeliberationBundle | None) -> None:
        self.deliberation_bundle = bundle
        self.merge_taint(getattr(bundle, "taint_flags", []))

    def attach_receipt(self, envelope: ReceiptEnvelope | None) -> None:
        self.receipt_envelope = envelope
        if envelope is not None and envelope.receipt_id:
            self.receipt_id = envelope.receipt_id
        self.touch()

    def attach_feedback(self, record: OutcomeFeedbackRecord | None) -> None:
        self.feedback_record = record
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "entrypoint": self.entrypoint,
            "status": self.status,
            "intake_bundle": self.intake_bundle.to_dict() if self.intake_bundle else None,
            "spec_bundle": self.spec_bundle.to_dict() if self.spec_bundle else None,
            "goal_refs": list(self.goal_refs),
            "deliberation_bundle": (
                self.deliberation_bundle.to_dict() if self.deliberation_bundle else None
            ),
            "plan_id": self.plan_id,
            "debate_id": self.debate_id,
            "execution_id": self.execution_id,
            "receipt_id": self.receipt_id,
            "receipt_envelope": self.receipt_envelope.to_dict() if self.receipt_envelope else None,
            "feedback_record": self.feedback_record.to_dict() if self.feedback_record else None,
            "attestation": dict(self.attestation),
            "taint_flags": list(self.taint_flags),
            "stage_events": [event.to_dict() for event in self.stage_events],
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunLedger:
        intake_payload = data.get("intake_bundle")
        spec_payload = data.get("spec_bundle")
        if isinstance(spec_payload, dict):
            spec_payload = dict(spec_payload)
            spec_payload.pop("missing_required_fields", None)
            spec_payload.pop("is_execution_grade", None)
        return cls(
            run_id=str(data.get("run_id", "")).strip(),
            entrypoint=str(data.get("entrypoint", "")).strip(),
            status=str(data.get("status", "received") or "received").strip(),
            intake_bundle=IntakeBundle(**intake_payload)
            if isinstance(intake_payload, dict)
            else None,
            spec_bundle=SpecBundle(**spec_payload) if isinstance(spec_payload, dict) else None,
            goal_refs=list(data.get("goal_refs", []) or []),
            deliberation_bundle=(
                DeliberationBundle(**data["deliberation_bundle"])
                if isinstance(data.get("deliberation_bundle"), dict)
                else None
            ),
            plan_id=str(data.get("plan_id", "")).strip(),
            debate_id=str(data.get("debate_id", "")).strip(),
            execution_id=str(data.get("execution_id", "")).strip(),
            receipt_id=str(data.get("receipt_id", "")).strip(),
            receipt_envelope=(
                ReceiptEnvelope(**data["receipt_envelope"])
                if isinstance(data.get("receipt_envelope"), dict)
                else None
            ),
            feedback_record=(
                OutcomeFeedbackRecord(**data["feedback_record"])
                if isinstance(data.get("feedback_record"), dict)
                else None
            ),
            attestation=dict(data.get("attestation", {}) or {}),
            taint_flags=list(data.get("taint_flags", []) or []),
            stage_events=[
                RunStageEvent.from_dict(event)
                for event in list(data.get("stage_events", []) or [])
                if isinstance(event, dict)
            ],
            metadata=dict(data.get("metadata", {}) or {}),
            created_at=str(data.get("created_at", "")).strip() or _utc_now_iso(),
            updated_at=str(data.get("updated_at", "")).strip() or _utc_now_iso(),
        )


@dataclass
class ComputerUseActionBundle:
    """Stable handoff artifact for a single computer-use (harness) action.

    Captures the inputs, outputs, and metadata of a harness execution so
    downstream stages (receipt generation, outcome feedback, audit) have a
    normalized view of what happened regardless of which harness was used.
    """

    harness_name: str  # "claude-code", "codex"
    action_type: str  # "implementation", "analysis", "review"
    input_prompt: str
    output_files: list[str] = field(default_factory=list)
    execution_time_seconds: float = 0.0
    exit_code: int = 0
    stdout_summary: str = ""  # Truncated to 2000 chars
    policy_violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComputerUseActionBundle":
        return cls(
            harness_name=str(data.get("harness_name", "")),
            action_type=str(data.get("action_type", "")),
            input_prompt=str(data.get("input_prompt", "")),
            output_files=list(data.get("output_files", [])),
            execution_time_seconds=float(data.get("execution_time_seconds", 0.0)),
            exit_code=int(data.get("exit_code", 0)),
            stdout_summary=str(data.get("stdout_summary", ""))[:2000],
            policy_violations=list(data.get("policy_violations", [])),
        )

    @classmethod
    def from_execution_result(
        cls,
        result: dict[str, Any],
        *,
        harness_name: str = "claude-code",
        action_type: str = "implementation",
        input_prompt: str = "",
    ) -> "ComputerUseActionBundle":
        """Create from a CodeImplementationTask execution result dict."""
        stdout = str(result.get("stdout", ""))
        return cls(
            harness_name=harness_name,
            action_type=action_type,
            input_prompt=input_prompt,
            output_files=[],  # Caller may enrich from git diff
            execution_time_seconds=float(result.get("duration_seconds", 0.0)),
            exit_code=int(result.get("exit_code", 0)),
            stdout_summary=stdout[:2000],
            policy_violations=[],
        )


class TaintChecker:
    """Utility for inspecting taint across backbone bundles.

    Provides a single place to ask "is anything tainted?" and to aggregate
    a taint summary suitable for inclusion in a ReceiptEnvelope.
    """

    @staticmethod
    def has_taint(bundle: Any) -> bool:
        """Return True if *bundle* carries non-empty taint_flags."""
        flags = getattr(bundle, "taint_flags", None)
        if flags is None:
            return False
        return bool(flags)

    @staticmethod
    def collect_taint_summary(
        intake: IntakeBundle | None = None,
        spec: SpecBundle | None = None,
        deliberation: DeliberationBundle | None = None,
        execution: ExecutionAttemptRecord | None = None,
        verification: ReceiptEnvelope | None = None,
    ) -> dict[str, Any]:
        """Aggregate taint information across all pipeline stages.

        Returns a dict suitable for ``ReceiptEnvelope.taint_summary``.
        """
        per_stage: dict[str, list[str]] = {}
        all_flags: list[str] = []

        stages: list[tuple[str, Any]] = [
            ("intake", intake),
            ("spec", spec),
            ("deliberation", deliberation),
            ("execution", execution),
            ("verification", verification),
        ]

        for name, bundle in stages:
            if bundle is None:
                continue
            flags = list(getattr(bundle, "taint_flags", []) or [])
            if not flags:
                # ReceiptEnvelope stores taint in taint_summary, not taint_flags
                ts = getattr(bundle, "taint_summary", None)
                if isinstance(ts, dict):
                    flags = list(ts.get("flags", []) or [])
            if flags:
                per_stage[name] = flags
                all_flags.extend(flags)

        unique_flags = list(dict.fromkeys(all_flags))

        return {
            "tainted": bool(unique_flags),
            "flags": unique_flags,
            "per_stage": per_stage,
        }
