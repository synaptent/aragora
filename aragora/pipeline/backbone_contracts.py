"""Canonical handoff artifacts for Aragora's closed-loop backbone.

This module is intentionally thin. It does not replace the existing rich
types in prompt_engine, interrogation, debate, planning, or receipts.
It normalizes those shapes into stable handoff artifacts so the stages can
compose without implicit contracts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


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
        elif is_dataclass(value):
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
        provenance_refs = [provenance.to_dict()] if hasattr(provenance, "to_dict") else []
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
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_debate_result(cls, result: Any) -> DeliberationBundle:
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
            extras={
                "task": str(getattr(result, "task", "") or ""),
                "convergence_status": str(getattr(result, "convergence_status", "") or ""),
                "consensus_variance": float(getattr(result, "consensus_variance", 0.0) or 0.0),
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
