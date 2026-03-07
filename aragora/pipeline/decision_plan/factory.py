"""
DecisionPlan factory - creates plans from debate results.

Stability: STABLE
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.core_types import DebateResult
from aragora.implement.types import ImplementPlan, ImplementTask
from aragora.pipeline.backbone_contracts import DeliberationBundle, SpecBundle
from aragora.pipeline.decision_plan.core import (
    ApprovalMode,
    BudgetAllocation,
    DecisionPlan,
    ImplementationProfile,
    PlanStatus,
)
from aragora.pipeline.risk_register import Risk, RiskCategory, RiskLevel, RiskRegister
from aragora.pipeline.verification_plan import (
    CasePriority,
    VerificationCase,
    VerificationPlan,
    VerificationType,
)

if TYPE_CHECKING:
    from aragora.prompt_engine.spec_validator import ValidationResult

_EXECUTION_MODE_ALIASES = {
    "execute_workflow": "workflow",
    "workflow_execute": "workflow",
    "computer-use": "computer_use",
    "computeruse": "computer_use",
}
_CANONICAL_EXECUTION_MODES = {"workflow", "hybrid", "fabric", "computer_use"}


def normalize_execution_mode(value: str | None) -> str | None:
    """Normalize execution-mode aliases to canonical values.

    Unknown modes are returned in normalized (lowercase, underscore) form so
    callers can still validate and fail fast at API/CLI boundaries.
    """
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("-", "_")
    normalized = _EXECUTION_MODE_ALIASES.get(normalized, normalized)
    if normalized in _CANONICAL_EXECUTION_MODES:
        return normalized
    return normalized


class DecisionPlanFactory:
    """Factory for creating DecisionPlan from DebateResult.

    Generates all sub-artifacts (risk register, verification plan,
    implementation plan) from the debate result and its metadata.

    Usage:
        plan = DecisionPlanFactory.from_debate_result(
            result,
            budget_limit_usd=5.00,
            approval_mode=ApprovalMode.RISK_BASED,
        )
    """

    @staticmethod
    def from_debate_result(
        result: DebateResult,
        *,
        budget_limit_usd: float | None = None,
        approval_mode: ApprovalMode = ApprovalMode.RISK_BASED,
        max_auto_risk: RiskLevel = RiskLevel.LOW,
        repo_path: Path | None = None,
        metadata: dict[str, Any] | None = None,
        implement_plan: ImplementPlan | None = None,
        implementation_profile: ImplementationProfile | dict[str, Any] | None = None,
        specification: Any | None = None,
        validation_result: ValidationResult | Any | None = None,
        fail_closed_spec_validation: bool | None = None,
        deliberation_bundle: DeliberationBundle | None = None,
    ) -> DecisionPlan:
        """Create a DecisionPlan from a DebateResult.

        This is the primary entry point for the gold path. It:
        1. Analyzes the debate result for risks
        2. Generates a verification plan
        3. Decomposes the conclusion into implementation tasks
        4. Sets up budget tracking from debate costs
        5. Configures approval based on risk assessment

        Args:
            result: The completed DebateResult from Arena.run().
            budget_limit_usd: Optional budget cap for the full plan.
            approval_mode: How human approval is determined.
            max_auto_risk: Max risk level for auto-execution.
            repo_path: Repository root for implementation planning.
            metadata: Additional metadata to attach.
            implement_plan: Optional pre-built implementation plan to reuse.
            deliberation_bundle: Optional pre-built deliberation bundle. When not
                provided one is auto-created from the debate result. The bundle's
                quality_verdict gates automated lanes (ApprovalMode.NEVER).

        Returns:
            A fully populated DecisionPlan ready for approval/execution.
        """
        # Build or reuse deliberation bundle (CLB-005 / CLB-006)
        if deliberation_bundle is None:
            deliberation_bundle = DeliberationBundle.from_debate_result(result)

        # Automated lanes must not proceed on a failed quality verdict
        if approval_mode == ApprovalMode.NEVER and deliberation_bundle.quality_verdict == "failed":
            raise ValueError(
                f"Cannot create automated plan: quality verdict is '{deliberation_bundle.quality_verdict}'. "
                "Use a manual approval mode or improve the debate quality before automating."
            )

        merged_metadata: dict[str, Any] = {}
        result_metadata = getattr(result, "metadata", None)
        if isinstance(result_metadata, dict):
            merged_metadata.update(result_metadata)
        if isinstance(metadata, dict):
            merged_metadata.update(metadata)

        # Persist the deliberation bundle so downstream stages can consume it
        merged_metadata["deliberation_bundle"] = deliberation_bundle.to_dict()

        profile: ImplementationProfile | None = None
        if isinstance(implementation_profile, ImplementationProfile):
            profile = implementation_profile
            profile.execution_mode = normalize_execution_mode(profile.execution_mode)
        elif isinstance(implementation_profile, dict):
            profile_payload = dict(implementation_profile)
            profile_payload["execution_mode"] = normalize_execution_mode(
                profile_payload.get("execution_mode")
            )
            profile = ImplementationProfile.from_dict(profile_payload)
        else:
            impl_payload = merged_metadata.get("implementation_profile") or merged_metadata.get(
                "implementation"
            )
            if isinstance(impl_payload, dict):
                impl_payload = dict(impl_payload)
                impl_payload["execution_mode"] = normalize_execution_mode(
                    impl_payload.get("execution_mode")
                )
                profile = ImplementationProfile.from_dict(impl_payload)

        if profile is not None:
            merged_metadata.setdefault("implementation_profile", profile.to_dict())
            if profile.channel_targets and "channel_targets" not in merged_metadata:
                merged_metadata["channel_targets"] = profile.channel_targets
            if profile.thread_id and "thread_id" not in merged_metadata:
                merged_metadata["thread_id"] = profile.thread_id
            if profile.thread_id_by_platform and "thread_id_by_platform" not in merged_metadata:
                merged_metadata["thread_id_by_platform"] = profile.thread_id_by_platform

        if specification is not None:
            spec_bundle = DecisionPlanFactory.validate_execution_grade_specification(
                specification,
                validation_result=validation_result,
                fail_closed=(
                    approval_mode == ApprovalMode.NEVER
                    if fail_closed_spec_validation is None
                    else fail_closed_spec_validation
                ),
            )
            DecisionPlanFactory._attach_spec_metadata(
                merged_metadata,
                spec_bundle=spec_bundle,
                specification=specification,
                validation_result=validation_result,
            )

        plan = DecisionPlan(
            debate_id=result.debate_id,
            task=result.task,
            debate_result=result,
            approval_mode=approval_mode,
            max_auto_risk=max_auto_risk,
            metadata=merged_metadata,
            implementation_profile=profile,
        )

        # Budget setup
        plan.budget = BudgetAllocation(
            limit_usd=budget_limit_usd,
            debate_cost_usd=result.total_cost_usd,
            spent_usd=result.total_cost_usd,
        )

        # Risk analysis from debate result
        plan.risk_register = DecisionPlanFactory._build_risk_register(result)

        # Verification plan from debate result
        plan.verification_plan = DecisionPlanFactory._build_verification_plan(result)

        # Implementation plan from debate conclusion (or reuse provided plan)
        if implement_plan is not None:
            plan.implement_plan = implement_plan
        else:
            plan.implement_plan = DecisionPlanFactory._build_implement_plan(result, repo_path)

        # Set status based on approval needs
        if plan.requires_human_approval:
            plan.status = PlanStatus.AWAITING_APPROVAL
        else:
            plan.status = PlanStatus.APPROVED

        return plan

    @staticmethod
    def from_specification(
        specification: Any,
        *,
        debate_id: str | None = None,
        task: str | None = None,
        budget_limit_usd: float | None = None,
        approval_mode: ApprovalMode = ApprovalMode.RISK_BASED,
        max_auto_risk: RiskLevel = RiskLevel.LOW,
        metadata: dict[str, Any] | None = None,
        implementation_profile: ImplementationProfile | dict[str, Any] | None = None,
        validation_result: ValidationResult | Any | None = None,
        fail_closed_spec_validation: bool = True,
    ) -> DecisionPlan:
        """Create a DecisionPlan directly from a prompt-engine specification."""
        spec_bundle = DecisionPlanFactory.validate_execution_grade_specification(
            specification,
            validation_result=validation_result,
            fail_closed=fail_closed_spec_validation,
        )

        merged_metadata: dict[str, Any] = {}
        if isinstance(metadata, dict):
            merged_metadata.update(metadata)
        DecisionPlanFactory._attach_spec_metadata(
            merged_metadata,
            spec_bundle=spec_bundle,
            specification=specification,
            validation_result=validation_result,
        )

        profile = DecisionPlanFactory._resolve_implementation_profile(
            implementation_profile=implementation_profile,
            metadata=merged_metadata,
        )
        DecisionPlanFactory._attach_profile_metadata(merged_metadata, profile)

        serialized_spec = DecisionPlanFactory._serialize_specification(specification)
        resolved_debate_id = DecisionPlanFactory._resolve_spec_debate_id(
            specification,
            override=debate_id,
            serialized_spec=serialized_spec,
        )
        resolved_task = (
            str(task or "").strip()
            or str(getattr(specification, "title", "")).strip()
            or str(getattr(specification, "problem_statement", "")).strip()
            or "Prompt-engine specification"
        )

        plan = DecisionPlan(
            debate_id=resolved_debate_id,
            task=resolved_task,
            approval_mode=approval_mode,
            max_auto_risk=max_auto_risk,
            metadata=merged_metadata,
            implementation_profile=profile,
        )
        plan.budget = BudgetAllocation(limit_usd=budget_limit_usd)
        plan.risk_register = DecisionPlanFactory._build_risk_register_from_specification(
            specification,
            debate_id=resolved_debate_id,
            spec_bundle=spec_bundle,
            validation_result=validation_result,
        )
        plan.verification_plan = DecisionPlanFactory._build_verification_plan_from_specification(
            specification,
            debate_id=resolved_debate_id,
            spec_bundle=spec_bundle,
        )
        plan.implement_plan = DecisionPlanFactory._build_implement_plan_from_specification(
            specification,
            spec_bundle=spec_bundle,
        )
        plan.status = (
            PlanStatus.AWAITING_APPROVAL if plan.requires_human_approval else PlanStatus.APPROVED
        )
        return plan

    @staticmethod
    def validate_execution_grade_specification(
        specification: Any,
        *,
        validation_result: ValidationResult | Any | None = None,
        fail_closed: bool = False,
    ) -> SpecBundle:
        """Normalize a prompt/interrogation specification to the canonical spec bundle.

        When ``fail_closed`` is true, incomplete execution-grade specifications raise
        ``ValueError`` so automated lanes cannot proceed silently.
        """
        bundle = SpecBundle.from_prompt_spec(specification, validation=validation_result)
        if fail_closed and bundle.missing_required_fields:
            missing = ", ".join(bundle.missing_required_fields)
            raise ValueError(f"Specification is not execution-grade: missing {missing}")
        return bundle

    @staticmethod
    def _attach_spec_metadata(
        metadata: dict[str, Any],
        *,
        spec_bundle: SpecBundle,
        specification: Any | None = None,
        validation_result: ValidationResult | Any | None = None,
    ) -> None:
        metadata["spec_bundle"] = spec_bundle.to_dict()
        if spec_bundle.missing_required_fields:
            metadata["spec_bundle_missing_fields"] = list(spec_bundle.missing_required_fields)
        else:
            metadata.pop("spec_bundle_missing_fields", None)

        artifact_payload: dict[str, Any] = {"spec_bundle": spec_bundle.to_dict()}
        serialized_spec = DecisionPlanFactory._serialize_specification(specification)
        if serialized_spec:
            artifact_payload["specification"] = serialized_spec
        serialized_validation = DecisionPlanFactory._serialize_validation_result(validation_result)
        if serialized_validation is not None:
            artifact_payload["validation"] = serialized_validation
        if artifact_payload:
            metadata["prompt_spec_artifacts"] = artifact_payload

    @staticmethod
    def _resolve_implementation_profile(
        *,
        implementation_profile: ImplementationProfile | dict[str, Any] | None,
        metadata: dict[str, Any],
    ) -> ImplementationProfile | None:
        profile: ImplementationProfile | None = None
        if isinstance(implementation_profile, ImplementationProfile):
            profile = implementation_profile
            profile.execution_mode = normalize_execution_mode(profile.execution_mode)
        elif isinstance(implementation_profile, dict):
            profile_payload = dict(implementation_profile)
            profile_payload["execution_mode"] = normalize_execution_mode(
                profile_payload.get("execution_mode")
            )
            profile = ImplementationProfile.from_dict(profile_payload)
        else:
            impl_payload = metadata.get("implementation_profile") or metadata.get("implementation")
            if isinstance(impl_payload, dict):
                impl_payload = dict(impl_payload)
                impl_payload["execution_mode"] = normalize_execution_mode(
                    impl_payload.get("execution_mode")
                )
                profile = ImplementationProfile.from_dict(impl_payload)
        return profile

    @staticmethod
    def _attach_profile_metadata(
        metadata: dict[str, Any],
        profile: ImplementationProfile | None,
    ) -> None:
        if profile is None:
            return
        metadata.setdefault("implementation_profile", profile.to_dict())
        if profile.channel_targets and "channel_targets" not in metadata:
            metadata["channel_targets"] = profile.channel_targets
        if profile.thread_id and "thread_id" not in metadata:
            metadata["thread_id"] = profile.thread_id
        if profile.thread_id_by_platform and "thread_id_by_platform" not in metadata:
            metadata["thread_id_by_platform"] = profile.thread_id_by_platform

    @staticmethod
    def _serialize_specification(specification: Any | None) -> dict[str, Any]:
        if specification is None:
            return {}

        payload: dict[str, Any] = {}
        if hasattr(specification, "to_dict"):
            raw = specification.to_dict()
            if isinstance(raw, dict):
                payload.update(raw)
        elif isinstance(specification, dict):
            payload.update(specification)

        file_changes: list[dict[str, Any]] = []
        for item in getattr(specification, "file_changes", []) or payload.get("file_changes", []):
            if isinstance(item, dict):
                file_changes.append(dict(item))
                continue
            file_changes.append(
                {
                    "path": getattr(item, "path", ""),
                    "action": getattr(item, "action", ""),
                    "description": getattr(item, "description", ""),
                    "estimated_lines": getattr(item, "estimated_lines", 0),
                }
            )
        if file_changes:
            payload["file_changes"] = file_changes

        risks: list[dict[str, Any]] = []
        for item in getattr(specification, "risks", []) or payload.get("risks", []):
            if isinstance(item, dict):
                risks.append(dict(item))
                continue
            if hasattr(item, "to_dict"):
                risks.append(item.to_dict())
        if risks:
            payload["risks"] = risks

        dependencies = getattr(specification, "dependencies", None)
        if dependencies:
            payload["dependencies"] = list(dependencies)
        return payload

    @staticmethod
    def _serialize_validation_result(
        validation_result: ValidationResult | Any | None,
    ) -> dict[str, Any] | None:
        if validation_result is None:
            return None
        if hasattr(validation_result, "to_dict"):
            raw = validation_result.to_dict()
            if isinstance(raw, dict):
                return raw
        if isinstance(validation_result, dict):
            return dict(validation_result)
        return {
            "passed": getattr(validation_result, "passed", None),
            "overall_confidence": getattr(validation_result, "overall_confidence", None),
        }

    @staticmethod
    def _resolve_spec_debate_id(
        specification: Any,
        *,
        override: str | None,
        serialized_spec: dict[str, Any] | None = None,
    ) -> str:
        explicit = str(override or "").strip()
        if explicit:
            return explicit
        provenance = getattr(specification, "provenance", None)
        provenance_debate_id = str(getattr(provenance, "debate_id", "") or "").strip()
        if provenance_debate_id:
            return provenance_debate_id
        prompt_hash = str(getattr(provenance, "prompt_hash", "") or "").strip()
        if prompt_hash:
            return f"prompt-spec-{prompt_hash[:12]}"
        serialized = serialized_spec or DecisionPlanFactory._serialize_specification(specification)
        digest = hashlib.sha256(
            json.dumps(
                serialized or {"title": getattr(specification, "title", "")}, sort_keys=True
            ).encode()
        ).hexdigest()
        return f"prompt-spec-{digest[:12]}"

    @staticmethod
    def _build_risk_register_from_specification(
        specification: Any,
        *,
        debate_id: str,
        spec_bundle: SpecBundle,
        validation_result: ValidationResult | Any | None = None,
    ) -> RiskRegister:
        register = RiskRegister(debate_id=debate_id)
        confidence = float(
            getattr(
                validation_result, "overall_confidence", getattr(specification, "confidence", 0.0)
            )
            or spec_bundle.confidence
            or 0.0
        )
        if confidence < 0.7:
            register.add_risk(
                Risk(
                    id=f"risk-confidence-{debate_id[:8]}",
                    title="Low specification confidence",
                    description=(
                        f"Specification confidence is {confidence:.0%}; execution may require "
                        "manual review or refinement."
                    ),
                    level=RiskLevel.MEDIUM if confidence >= 0.5 else RiskLevel.HIGH,
                    category=RiskCategory.UNKNOWN,
                    source="specification_confidence",
                    impact=0.6,
                    likelihood=max(0.1, 1.0 - confidence),
                )
            )

        if getattr(validation_result, "passed", None) is False:
            register.add_risk(
                Risk(
                    id=f"risk-validation-{debate_id[:8]}",
                    title="Specification validation failed",
                    description="Execution-grade validation did not pass for this specification.",
                    level=RiskLevel.HIGH,
                    category=RiskCategory.TECHNICAL,
                    source="spec_validation",
                    impact=0.8,
                    likelihood=0.7,
                )
            )

        for idx, item in enumerate(getattr(specification, "risks", []) or [], start=1):
            if isinstance(item, dict):
                description = str(item.get("description", "")).strip()
                mitigation = str(item.get("mitigation", "")).strip()
                likelihood_raw = item.get("likelihood")
                impact_raw = item.get("impact")
            else:
                description = str(getattr(item, "description", "")).strip()
                mitigation = str(getattr(item, "mitigation", "")).strip()
                likelihood_raw = getattr(item, "likelihood", None)
                impact_raw = getattr(item, "impact", None)

            likelihood = _coerce_probability(likelihood_raw)
            impact = _coerce_probability(impact_raw)
            level = _coerce_risk_level(max(likelihood, impact))
            register.add_risk(
                Risk(
                    id=f"risk-spec-{idx}",
                    title=description[:80] or f"Specification risk {idx}",
                    description=description or f"Risk {idx} from specification",
                    level=level,
                    category=_categorize_issue(description or mitigation or "technical risk"),
                    source="prompt_specification",
                    impact=impact,
                    likelihood=likelihood,
                    mitigation=mitigation,
                )
            )
        return register

    @staticmethod
    def _build_verification_plan_from_specification(
        specification: Any,
        *,
        debate_id: str,
        spec_bundle: SpecBundle,
    ) -> VerificationPlan:
        plan = VerificationPlan(
            debate_id=debate_id,
            title=f"Verify: {spec_bundle.title}",
            description=f"Verification plan generated from specification {spec_bundle.title}",
            critical_paths=list(spec_bundle.owner_file_scopes),
        )
        for idx, criterion in enumerate(spec_bundle.acceptance_criteria, start=1):
            plan.add_test(
                VerificationCase(
                    id=f"acceptance-{idx}",
                    title=f"Acceptance: {criterion[:60]}",
                    description=f"Confirm specification acceptance criterion: {criterion}",
                    test_type=VerificationType.INTEGRATION,
                    priority=CasePriority.P1,
                    steps=[
                        "Apply the implementation change",
                        "Run the intended workflow or API path",
                        f"Verify the outcome matches: {criterion}",
                    ],
                    expected_result=criterion,
                    automated=True,
                )
            )

        plan.add_test(
            VerificationCase(
                id="smoke-1",
                title="Smoke test: Prompt-spec execution path",
                description="Confirm the generated implementation is reachable and healthy.",
                test_type=VerificationType.E2E,
                priority=CasePriority.P0,
                steps=["Execute the primary happy path", "Verify the service remains healthy"],
                expected_result="Primary flow succeeds without regression",
            )
        )
        plan.add_test(
            VerificationCase(
                id="regression-1",
                title="Regression: Existing behavior still works",
                description="Run the relevant regression checks for the touched file scopes.",
                test_type=VerificationType.REGRESSION,
                priority=CasePriority.P1,
                steps=["Run targeted regression checks", "Verify existing workflows still pass"],
                expected_result="No regression introduced",
            )
        )
        return plan

    @staticmethod
    def _build_implement_plan_from_specification(
        specification: Any,
        *,
        spec_bundle: SpecBundle,
    ) -> ImplementPlan:
        serialized_spec = DecisionPlanFactory._serialize_specification(specification)
        design_hash = hashlib.sha256(
            json.dumps(serialized_spec, sort_keys=True).encode()
        ).hexdigest()
        tasks: list[ImplementTask] = []
        previous_task_id: str | None = None

        for idx, item in enumerate(getattr(specification, "file_changes", []) or [], start=1):
            if isinstance(item, dict):
                path = str(item.get("path", "")).strip()
                action = str(item.get("action", "")).strip()
                description = str(item.get("description", "")).strip()
                estimated_lines = int(item.get("estimated_lines", 0) or 0)
            else:
                path = str(getattr(item, "path", "") or "").strip()
                action = str(getattr(item, "action", "") or "").strip()
                description = str(getattr(item, "description", "") or "").strip()
                estimated_lines = int(getattr(item, "estimated_lines", 0) or 0)
            task_id = f"task-{idx}"
            tasks.append(
                ImplementTask(
                    id=task_id,
                    description=description or f"{action or 'modify'} {path or 'target file'}",
                    files=[path] if path else [],
                    complexity=_complexity_for_estimated_lines(estimated_lines),
                    dependencies=[previous_task_id] if previous_task_id else [],
                )
            )
            previous_task_id = task_id

        if not tasks:
            for idx, step in enumerate(
                getattr(specification, "implementation_plan", []) or [], start=1
            ):
                text = str(step).strip()
                if not text:
                    continue
                task_id = f"task-{idx}"
                tasks.append(
                    ImplementTask(
                        id=task_id,
                        description=text,
                        files=list(spec_bundle.owner_file_scopes),
                        complexity="moderate",
                        dependencies=[previous_task_id] if previous_task_id else [],
                    )
                )
                previous_task_id = task_id

        if not tasks:
            tasks.append(
                ImplementTask(
                    id="task-1",
                    description=f"Implement specification: {spec_bundle.title}",
                    files=list(spec_bundle.owner_file_scopes),
                    complexity="moderate",
                    dependencies=[],
                )
            )

        return ImplementPlan(design_hash=design_hash, tasks=tasks)

    @staticmethod
    def from_implement_plan(
        implement_plan: ImplementPlan,
        *,
        debate_id: str = "",
        task: str = "",
        implementation_profile: ImplementationProfile | dict[str, Any] | None = None,
    ) -> DecisionPlan:
        """Wrap an existing ImplementPlan as a DecisionPlan for persistence.

        Used when an ImplementPlan was created directly (e.g. via
        create_single_task_plan) and needs to be stored in the plan store.
        """
        profile: ImplementationProfile | None = None
        if isinstance(implementation_profile, ImplementationProfile):
            profile = implementation_profile
            profile.execution_mode = normalize_execution_mode(profile.execution_mode)
        elif isinstance(implementation_profile, dict):
            profile_payload = dict(implementation_profile)
            profile_payload["execution_mode"] = normalize_execution_mode(
                profile_payload.get("execution_mode")
            )
            profile = ImplementationProfile.from_dict(profile_payload)

        return DecisionPlan(
            debate_id=debate_id,
            task=task or "Implementation plan from decision integrity package",
            implement_plan=implement_plan,
            status=PlanStatus.CREATED,
            implementation_profile=profile,
        )

    @staticmethod
    def _build_risk_register(result: DebateResult) -> RiskRegister:
        """Build risk register directly from DebateResult."""
        register = RiskRegister(debate_id=result.debate_id)

        # Low confidence → risk
        if result.confidence < 0.7:
            register.add_risk(
                Risk(
                    id=f"risk-confidence-{result.debate_id[:8]}",
                    title="Low consensus confidence",
                    description=(
                        f"Debate reached {result.confidence:.0%} confidence. "
                        "Implementation may face challenges or require revision."
                    ),
                    level=RiskLevel.MEDIUM if result.confidence >= 0.5 else RiskLevel.HIGH,
                    category=RiskCategory.UNKNOWN,
                    source="consensus_analysis",
                    impact=0.6,
                    likelihood=1.0 - result.confidence,
                )
            )

        # No consensus → risk
        if not result.consensus_reached:
            register.add_risk(
                Risk(
                    id=f"risk-no-consensus-{result.debate_id[:8]}",
                    title="No consensus reached",
                    description="Agents did not reach consensus. Decision may be contested.",
                    level=RiskLevel.HIGH,
                    category=RiskCategory.UNKNOWN,
                    source="consensus_analysis",
                    impact=0.8,
                    likelihood=0.7,
                )
            )

        # High-severity critiques → risks
        for i, critique in enumerate(result.critiques):
            if critique.severity >= 7.0:
                for j, issue in enumerate(critique.issues[:2]):
                    register.add_risk(
                        Risk(
                            id=f"risk-critique-{i}-{j}",
                            title=issue[:60],
                            description=issue,
                            level=RiskLevel.HIGH if critique.severity >= 8.0 else RiskLevel.MEDIUM,
                            category=_categorize_issue(issue),
                            source=f"critique:{critique.agent}",
                            impact=critique.severity / 10.0,
                            likelihood=0.7,
                            mitigation=", ".join(critique.suggestions[:2]),
                        )
                    )

        # Dissenting views → risks
        for i, view in enumerate(result.dissenting_views[:3]):
            register.add_risk(
                Risk(
                    id=f"risk-dissent-{i}",
                    title=f"Dissenting view: {view[:50]}",
                    description=view,
                    level=RiskLevel.MEDIUM,
                    category=RiskCategory.UNKNOWN,
                    source="dissent_analysis",
                    impact=0.5,
                    likelihood=0.4,
                )
            )

        # Debate cruxes → risks
        for i, crux in enumerate(result.debate_cruxes[:3]):
            claim = crux.get("claim", crux.get("text", "Unknown crux"))
            register.add_risk(
                Risk(
                    id=f"risk-crux-{i}",
                    title=f"Unresolved crux: {str(claim)[:50]}",
                    description=f"Key disagreement driver: {claim}",
                    level=RiskLevel.MEDIUM,
                    category=RiskCategory.TECHNICAL,
                    source="belief_network",
                    impact=0.5,
                    likelihood=0.5,
                )
            )

        return register

    @staticmethod
    def _build_verification_plan(result: DebateResult) -> VerificationPlan:
        """Build verification plan directly from DebateResult."""
        plan = VerificationPlan(
            debate_id=result.debate_id,
            title=f"Verify: {result.task[:60]}",
            description=f"Verification plan for debate {result.debate_id}",
        )

        # Extract testable claims from final answer
        test_num = 1
        if result.final_answer:
            for line in result.final_answer.split("\n"):
                line = line.strip()
                if not line or len(line) < 15:
                    continue
                keywords = ["implement", "use", "add", "create", "ensure", "should", "must"]
                if any(kw in line.lower() for kw in keywords):
                    plan.add_test(
                        VerificationCase(
                            id=f"consensus-{test_num}",
                            title=f"Verify: {line[:50]}",
                            description=f"Confirm implementation satisfies: {line}",
                            test_type=VerificationType.INTEGRATION,
                            priority=CasePriority.P1,
                            steps=[
                                "Set up environment",
                                "Execute functionality",
                                "Verify expected behavior",
                            ],
                            expected_result="Functionality works as described",
                        )
                    )
                    test_num += 1
                    if test_num > 5:
                        break

        # Edge cases from high-severity critiques
        for i, critique in enumerate(result.critiques[:5]):
            if critique.severity >= 5.0:
                for j, issue in enumerate(critique.issues[:1]):
                    plan.add_test(
                        VerificationCase(
                            id=f"critique-edge-{i}-{j}",
                            title=f"Edge case: {issue[:50]}",
                            description=f"Verify handling of: {issue}",
                            test_type=VerificationType.UNIT,
                            priority=CasePriority.P2,
                            steps=["Set up edge case", "Execute", "Verify graceful handling"],
                            expected_result="Edge case handled",
                        )
                    )

        # Smoke test
        plan.add_test(
            VerificationCase(
                id="smoke-1",
                title="Smoke test: Basic functionality",
                description="Verify basic functionality after implementation",
                test_type=VerificationType.E2E,
                priority=CasePriority.P0,
                steps=["Deploy changes", "Execute happy path", "Verify success"],
                expected_result="Basic use case succeeds",
            )
        )

        # Regression
        plan.add_test(
            VerificationCase(
                id="regression-1",
                title="Regression: Existing functionality",
                description="Verify no regressions in existing functionality",
                test_type=VerificationType.REGRESSION,
                priority=CasePriority.P1,
                steps=["Run existing test suite", "Verify all pass"],
                expected_result="No regressions",
            )
        )

        return plan

    @staticmethod
    def _build_implement_plan(result: DebateResult, repo_path: Path | None = None) -> ImplementPlan:
        """Build implementation plan from debate conclusion.

        Uses heuristic extraction from the final answer. For richer
        decomposition, callers should use generate_implement_plan()
        from aragora.implement.planner with an LLM.
        """
        design = result.final_answer or result.task
        design_hash = hashlib.sha256(design.encode()).hexdigest()

        tasks: list[ImplementTask] = []
        task_num = 1

        # Extract numbered steps from the final answer
        if result.final_answer:
            for line in result.final_answer.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Match numbered items or bullet points with action verbs
                if line and (line[0].isdigit() or line.startswith("-") or line.startswith("*")):
                    clean = line.lstrip("0123456789.-*) ").strip()
                    if len(clean) > 15:
                        # Infer file paths mentioned
                        import re

                        files = re.findall(r"`([a-zA-Z0-9_/\-\.]+\.[a-z]+)`", clean)

                        tasks.append(
                            ImplementTask(
                                id=f"task-{task_num}",
                                description=clean[:200],
                                files=files[:5],
                                complexity="moderate",
                                dependencies=[f"task-{task_num - 1}"] if task_num > 1 else [],
                            )
                        )
                        task_num += 1
                        if task_num > 10:
                            break

        # Fallback: single task if no structured steps found
        if not tasks:
            tasks.append(
                ImplementTask(
                    id="task-1",
                    description="Implement the debated solution",
                    files=[],
                    complexity="complex",
                    dependencies=[],
                )
            )

        return ImplementPlan(design_hash=design_hash, tasks=tasks)

    @staticmethod
    async def from_debate_result_async(
        result: DebateResult,
        *,
        knowledge_mound: Any | None = None,
        budget_limit_usd: float | None = None,
        approval_mode: ApprovalMode = ApprovalMode.RISK_BASED,
        max_auto_risk: RiskLevel = RiskLevel.LOW,
        repo_path: Path | None = None,
        metadata: dict[str, Any] | None = None,
        implement_plan: ImplementPlan | None = None,
        enrich_from_history: bool = True,
    ) -> DecisionPlan:
        """Async version of from_debate_result with Knowledge Mound enrichment.

        This extended factory method queries the Knowledge Mound for historical
        decisions similar to the current task, enriching the risk register with
        data about past outcomes.

        Args:
            result: The completed DebateResult from Arena.run().
            knowledge_mound: Optional KM instance for historical queries.
            budget_limit_usd: Optional budget cap for the full plan.
            approval_mode: How human approval is determined.
            max_auto_risk: Max risk level for auto-execution.
            repo_path: Repository root for implementation planning.
            metadata: Additional metadata to attach.
            implement_plan: Optional pre-built implementation plan to reuse.
            enrich_from_history: Whether to query KM for historical context.

        Returns:
            A DecisionPlan enriched with historical risk data.
        """
        # Start with synchronous creation
        plan = DecisionPlanFactory.from_debate_result(
            result,
            budget_limit_usd=budget_limit_usd,
            approval_mode=approval_mode,
            max_auto_risk=max_auto_risk,
            repo_path=repo_path,
            metadata=metadata,
            implement_plan=implement_plan,
        )

        if enrich_from_history:
            # Enrich risks with historical data from Knowledge Mound
            if plan.risk_register:
                await DecisionPlanFactory._enrich_risks_from_history(
                    plan.risk_register, result.task, knowledge_mound
                )

            # Retrieve and attach historical lessons to plan metadata
            lessons = await DecisionPlanFactory._retrieve_historical_lessons(
                result.task, knowledge_mound
            )
            if lessons:
                plan.metadata["historical_lessons"] = lessons
                plan.metadata["historical_lessons_count"] = len(lessons)

        return plan

    @staticmethod
    async def _retrieve_historical_lessons(
        task: str,
        knowledge_mound: Any | None = None,
    ) -> list[str]:
        """Retrieve lessons learned from similar historical plans.

        Queries the Knowledge Mound for lessons from past decisions that
        are semantically similar to the current task.

        Args:
            task: The task description for similarity search
            knowledge_mound: Optional KM instance (uses global if not provided)

        Returns:
            List of lesson strings from similar past decisions
        """
        try:
            from aragora.knowledge.mound.adapters.decision_plan_adapter import (
                get_decision_plan_adapter,
            )

            adapter = get_decision_plan_adapter(knowledge_mound)

            # Extract domain keywords for targeted lesson retrieval
            domain_keywords = _extract_keywords(task)
            domain = " ".join(domain_keywords[:5])

            # Get lessons relevant to this domain
            lessons = await adapter.get_lessons_for_domain(domain, limit=5)
            return lessons

        except ImportError:
            return []
        except (KeyError, ValueError, OSError, RuntimeError):
            return []

    @staticmethod
    async def _enrich_risks_from_history(
        register: RiskRegister,
        task: str,
        knowledge_mound: Any | None = None,
    ) -> None:
        """Enrich risk register with historical data from Knowledge Mound.

        Queries KM for similar past decisions and their outcomes, updating
        each risk with historical context (how often similar risks appeared,
        what the success rates were, etc.).

        Args:
            register: The risk register to enrich
            task: The task description for similarity search
            knowledge_mound: Optional KM instance (uses global if not provided)
        """
        try:
            from aragora.knowledge.mound.adapters.decision_plan_adapter import (
                get_decision_plan_adapter,
            )

            adapter = get_decision_plan_adapter(knowledge_mound)

            # Query for similar historical plans
            similar_plans = await adapter.query_similar_plans(task, limit=10)
            if not similar_plans:
                return

            # Aggregate historical data
            total_plans = len(similar_plans)
            successful_plans = sum(1 for p in similar_plans if p.get("success", False))
            failed_plans = total_plans - successful_plans
            overall_success_rate = successful_plans / total_plans if total_plans > 0 else None

            # For each risk, try to find similar patterns in historical plans
            for risk in register.risks:
                # Find plans where similar issues appeared (keyword matching)
                risk_keywords = _extract_keywords(risk.title + " " + risk.description)
                matching_plans: list[dict[str, Any]] = []

                for plan_data in similar_plans:
                    content = plan_data.get("content", "")
                    plan_task = plan_data.get("task", "")

                    # Check if risk keywords appear in historical plan
                    if any(kw.lower() in (content + plan_task).lower() for kw in risk_keywords):
                        matching_plans.append(plan_data)

                if matching_plans:
                    # Update risk with historical data
                    risk.historical_occurrences = len(matching_plans)
                    matching_successes = sum(1 for p in matching_plans if p.get("success", False))
                    risk.historical_success_rate = (
                        matching_successes / len(matching_plans) if matching_plans else None
                    )
                    risk.related_plan_ids = [
                        p.get("plan_id", "") for p in matching_plans if p.get("plan_id")
                    ][:5]

                    # Adjust likelihood based on historical failure rate
                    if risk.historical_success_rate is not None:
                        failure_rate = 1.0 - risk.historical_success_rate
                        # Blend historical failure rate with original estimate
                        risk.likelihood = (risk.likelihood + failure_rate) / 2

            # Add a meta-risk if overall success rate is low
            if overall_success_rate is not None and overall_success_rate < 0.7:
                from aragora.pipeline.risk_register import Risk, RiskCategory, RiskLevel

                register.add_risk(
                    Risk(
                        id=f"risk-history-{register.debate_id[:8]}",
                        title="Historical pattern: Similar tasks had low success",
                        description=(
                            f"Analysis of {total_plans} similar historical decisions shows "
                            f"{overall_success_rate:.0%} success rate. "
                            f"{failed_plans} similar tasks failed previously."
                        ),
                        level=RiskLevel.HIGH if overall_success_rate < 0.5 else RiskLevel.MEDIUM,
                        category=RiskCategory.UNKNOWN,
                        source="knowledge_mound",
                        impact=0.7,
                        likelihood=1.0 - overall_success_rate,
                        historical_occurrences=total_plans,
                        historical_success_rate=overall_success_rate,
                    )
                )

        except ImportError as e:
            # KM adapter not available, skip enrichment
            import logging

            logging.getLogger(__name__).debug("KM enrichment unavailable: %s", e)
        except (OSError, RuntimeError, ValueError) as e:
            import logging

            logging.getLogger(__name__).warning("Historical enrichment failed: %s", e)


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text for matching."""

    # Remove common words and extract meaningful tokens
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "and",
        "or",
        "but",
        "if",
        "because",
        "until",
        "while",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "not",
        "no",
        "yes",
    }

    # Tokenize and filter
    tokens = re.findall(r"\b[a-z]+\b", text.lower())
    keywords = [t for t in tokens if t not in stop_words and len(t) > 3]

    # Return unique keywords (preserve order)
    seen: set[str] = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique[:10]  # Limit to 10 keywords


def _categorize_issue(issue: str) -> RiskCategory:
    """Categorize a risk issue by keywords."""
    lower = issue.lower()
    if any(k in lower for k in ["security", "auth", "permission", "vulnerable", "injection"]):
        return RiskCategory.SECURITY
    if any(k in lower for k in ["performance", "slow", "latency", "speed", "timeout"]):
        return RiskCategory.PERFORMANCE
    if any(k in lower for k in ["scale", "load", "capacity", "throughput"]):
        return RiskCategory.SCALABILITY
    if any(k in lower for k in ["maintain", "complex", "readab", "test", "debt"]):
        return RiskCategory.MAINTAINABILITY
    if any(k in lower for k in ["compat", "version", "depend", "integrat", "migrat"]):
        return RiskCategory.COMPATIBILITY
    return RiskCategory.TECHNICAL


def _coerce_probability(value: Any) -> float:
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 1.0:
            numeric = numeric / 10.0
        return max(0.0, min(1.0, numeric))
    text = str(value or "").strip().lower()
    mapping = {
        "low": 0.3,
        "medium": 0.5,
        "med": 0.5,
        "moderate": 0.5,
        "high": 0.75,
        "critical": 0.95,
    }
    return mapping.get(text, 0.5)


def _coerce_risk_level(value: Any) -> RiskLevel:
    numeric = _coerce_probability(value)
    if numeric >= 0.9:
        return RiskLevel.CRITICAL
    if numeric >= 0.7:
        return RiskLevel.HIGH
    if numeric >= 0.45:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _complexity_for_estimated_lines(estimated_lines: int) -> str:
    if estimated_lines >= 200:
        return "complex"
    if estimated_lines >= 50:
        return "moderate"
    return "simple"
