"""Unified Pipeline Orchestrator.

Composes all Wave 1-4 modules into a single execution path:

    prompt → extend → research → debate (diverse team) → plan → execute → feedback → ELO

This is the "one function" entry point that wires together:
- InputExtensionEngine (enriches user prompts)
- UnifiedResearcher (gathers context from KM/Obsidian/web)
- ProviderDiversityFilter (ensures multi-provider debate teams)
- Arena (debate orchestration)
- DecisionPlanFactory (creates execution plans from debate)
- AutonomyGate (human-in-the-loop controls)
- PlanExecutor (executes approved plans)
- OutcomeFeedbackRecorder (records outcomes to KM/ELO/calibrator)
- PhaseELOTracker (phase-tagged agent ratings)
- MetaLoopTrigger (self-improvement detection)
"""

from __future__ import annotations

import inspect
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from aragora.pipeline.backbone_contracts import (
    BackboneStage,
    DeliberationBundle,
    IntakeBundle,
    OutcomeFeedbackRecord,
    ReceiptEnvelope,
    RunLedger,
    RunStageEvent,
    SpecBundle,
    build_goal_refs_from_implement_plan,
)
from aragora.pipeline.backbone_runtime import BackboneRuntime

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """Configuration for the unified pipeline orchestrator."""

    # User preset (founder, cto, team, non_technical)
    preset_name: str = "cto"

    # Domain context for input extension
    domain: str = ""

    # Debate settings (overridable, defaults come from preset)
    debate_rounds: int | None = None
    agent_count: int | None = None
    consensus_threshold: float | None = None

    # Autonomy
    autonomy_level: str = "propose_and_approve"

    # Provider diversity
    min_providers: int = 2

    # Self-improvement
    enable_meta_loop: bool = False

    # Execution
    execution_mode: str = "workflow"
    skip_execution: bool = False

    # Quality gate (post-debate validation)
    enable_quality_gate: bool = False
    quality_min_score: float = 6.0
    quality_contract_path: str | None = None

    # Bug-fix loop (post-execution self-repair)
    enable_bug_fix_loop: bool = False
    bug_fix_max_retries: int = 3


@dataclass
class OrchestratorResult:
    """Result from a unified pipeline run."""

    run_id: str
    prompt: str

    # Stage outputs
    extended_input: Any | None = None
    research_context: Any | None = None
    diversity_report: Any | None = None
    debate_result: Any | None = None
    quality_report: Any | None = None
    decision_plan: Any | None = None
    plan_outcome: Any | None = None
    bug_fix_result: Any | None = None
    pipeline_outcome: Any | None = None
    spec_bundle: Any | None = None
    action_bundle: dict[str, Any] | None = None
    meta_loop_result: Any | None = None

    # Tracking
    stages_completed: list[str] = field(default_factory=list)
    stages_skipped: list[str] = field(default_factory=list)
    approvals_needed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def succeeded(self) -> bool:
        return len(self.errors) == 0 and "debate" in self.stages_completed

    @property
    def quality_score(self) -> float:
        if self.pipeline_outcome is not None and hasattr(
            self.pipeline_outcome, "overall_quality_score"
        ):
            return self.pipeline_outcome.overall_quality_score
        return 0.0


class UnifiedOrchestrator:
    """Composes Wave 1-4 modules into a single execution path.

    All dependencies are optional — the orchestrator gracefully degrades
    when components are unavailable. This allows incremental adoption:
    pass only what you have, and the orchestrator uses what it gets.
    """

    def __init__(
        self,
        # Wave 1: Truth-seeking
        input_extension: Any | None = None,
        researcher: Any | None = None,
        diversity_filter: Any | None = None,
        # Wave 2: Learning
        elo_tracker: Any | None = None,
        calibrator: Any | None = None,
        feedback_recorder: Any | None = None,
        # Wave 3: Self-improvement
        meta_loop: Any | None = None,
        # Wave 4: Closed-loop integration
        quality_validator: Any | None = None,
        bug_fixer: Any | None = None,
        # Existing infrastructure
        arena_factory: Any | None = None,
        plan_factory: Any | None = None,
        plan_executor: Any | None = None,
        knowledge_mound: Any | None = None,
        # Wave 5: OpenClaw execution
        spec_extractor: Any | None = None,
        code_task_factory: Any | None = None,
        # Provider routing
        provider_router: Any | None = None,
        backbone_runtime: BackboneRuntime | None = None,
    ) -> None:
        self._input_extension = input_extension
        self._researcher = researcher
        self._diversity_filter = diversity_filter
        self._elo_tracker = elo_tracker
        self._calibrator = calibrator
        self._feedback_recorder = feedback_recorder
        self._meta_loop = meta_loop
        self._quality_validator = quality_validator
        self._bug_fixer = bug_fixer
        self._arena_factory = arena_factory
        self._plan_factory = plan_factory
        self._plan_executor = plan_executor
        self._km = knowledge_mound
        self._spec_extractor = spec_extractor
        self._code_task_factory = code_task_factory
        self._provider_router = provider_router
        self._backbone_runtime = backbone_runtime

    @property
    def backbone_runtime(self) -> BackboneRuntime:
        if self._backbone_runtime is None:
            self._backbone_runtime = BackboneRuntime()
        return self._backbone_runtime

    def _create_backbone_run(self, result: OrchestratorResult, cfg: OrchestratorConfig) -> None:
        intake = IntakeBundle(
            source_kind="unified_orchestrator",
            raw_intent=result.prompt,
            context_refs=[],
            trust_tiers=["operator-authored"],
            origin_metadata={
                "entrypoint": "unified_orchestrator.run",
                "domain": cfg.domain,
                "preset_name": cfg.preset_name,
                "execution_mode": cfg.execution_mode,
            },
            taint_flags=[],
        )
        run = RunLedger(
            run_id=result.run_id,
            entrypoint="unified_orchestrator.run",
            status="running",
            intake_bundle=intake,
            metadata={"skip_execution": cfg.skip_execution},
        )
        run.add_event(
            RunStageEvent.create(
                BackboneStage.INTAKE,
                status="received",
                details={"prompt_length": len(result.prompt), "domain": cfg.domain or "general"},
            )
        )
        self.backbone_runtime.create_run(run)

    def _append_backbone_event(
        self,
        result: OrchestratorResult,
        stage: BackboneStage | str,
        *,
        status: str,
        artifact_ref: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.backbone_runtime.append_stage_event(
            result.run_id,
            stage,
            status=status,
            artifact_ref=artifact_ref,
            details=details,
        )

    def _update_backbone_run(
        self,
        result: OrchestratorResult,
        *,
        status: str | None = None,
        spec_bundle: SpecBundle | None | object = None,
        deliberation_bundle: DeliberationBundle | None | object = None,
        goal_refs: list[dict[str, Any]] | None = None,
        plan_id: str | None = None,
        debate_id: str | None = None,
        receipt_id: str | None = None,
        receipt_envelope: ReceiptEnvelope | None | object = None,
        feedback_record: OutcomeFeedbackRecord | None | object = None,
        attestation: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        update_kwargs: dict[str, Any] = {}
        if status is not None:
            update_kwargs["status"] = status
        if spec_bundle is not None:
            update_kwargs["spec_bundle"] = spec_bundle
        if deliberation_bundle is not None:
            update_kwargs["deliberation_bundle"] = deliberation_bundle
        if goal_refs is not None:
            update_kwargs["goal_refs"] = goal_refs
        if plan_id is not None:
            update_kwargs["plan_id"] = plan_id
        if debate_id is not None:
            update_kwargs["debate_id"] = debate_id
        if receipt_id is not None:
            update_kwargs["receipt_id"] = receipt_id
        if receipt_envelope is not None:
            update_kwargs["receipt_envelope"] = receipt_envelope
        if feedback_record is not None:
            update_kwargs["feedback_record"] = feedback_record
        if attestation is not None:
            update_kwargs["attestation"] = attestation
        if metadata is not None:
            update_kwargs["metadata"] = metadata
        if update_kwargs:
            self.backbone_runtime.update_run(result.run_id, **update_kwargs)

    @staticmethod
    def _coerce_float(value: Any, default: float = 0.0) -> float:
        """Normalize numeric telemetry so run-ledger event payloads stay JSON-safe."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _ensure_plan_backbone_metadata(plan: Any, run_id: str) -> None:
        BackboneRuntime.ensure_plan_metadata(plan, run_id, "unified_orchestrator.run")

    async def _attach_backbone_receipt(
        self,
        result: OrchestratorResult,
        plan: Any,
        outcome: Any,
    ) -> str:
        return await self.backbone_runtime.attach_execution_receipt(result.run_id, plan, outcome)

    def _attach_backbone_feedback(
        self,
        result: OrchestratorResult,
        *,
        receipt_ref: str,
    ) -> None:
        if result.pipeline_outcome is None:
            return
        record = OutcomeFeedbackRecord.from_pipeline_outcome(
            result.pipeline_outcome,
            receipt_ref=receipt_ref or result.run_id,
        )
        self.backbone_runtime.attach_feedback_record(
            result.run_id,
            record,
            artifact_ref=record.receipt_ref,
        )

    async def run(
        self,
        prompt: str,
        config: OrchestratorConfig | None = None,
        agents: list[Any] | None = None,
        approval_callback: Any | None = None,
    ) -> OrchestratorResult:
        """Execute the full pipeline from prompt to outcome.

        Args:
            prompt: User's natural language input.
            config: Pipeline configuration (defaults to CTO preset).
            agents: Pre-selected agents for debate (optional).
            approval_callback: Called when human approval is needed.
                Signature: async (stage: str, artifact: Any) -> bool

        Returns:
            OrchestratorResult with outputs from each stage.
        """
        cfg = config or OrchestratorConfig()
        result = OrchestratorResult(run_id=str(uuid.uuid4()), prompt=prompt)
        start = time.monotonic()
        try:
            self._create_backbone_run(result, cfg)
        except Exception:  # noqa: BLE001 — injected backbone_runtime
            logger.debug("Backbone run initialization failed", exc_info=True)

        # Load preset defaults
        preset_config = self._load_preset(cfg.preset_name)

        # Merge preset with explicit overrides
        debate_rounds = cfg.debate_rounds or preset_config.get("debate", {}).get("rounds", 3)
        agent_count = cfg.agent_count or preset_config.get("debate", {}).get("agent_count", 5)
        consensus_threshold = cfg.consensus_threshold or preset_config.get("debate", {}).get(
            "consensus_threshold", 0.6
        )

        # Build autonomy gates
        gates = self._build_gates(cfg.autonomy_level)

        # --- Stage 1: Research ---
        try:
            result.research_context = await self._do_research(prompt)
            result.stages_completed.append("research")
            self._append_backbone_event(
                result,
                BackboneStage.RESEARCH,
                status="completed",
            )
        except Exception:  # noqa: BLE001 — injected researcher
            logger.warning("Research stage failed, continuing without context")
            result.stages_skipped.append("research")
            self._append_backbone_event(
                result,
                BackboneStage.RESEARCH,
                status="skipped",
            )

        # --- Stage 2: Extend Input ---
        try:
            result.extended_input = await self._do_extend(
                prompt, cfg.domain, result.research_context
            )
            result.stages_completed.append("extend")
            self._append_backbone_event(
                result,
                BackboneStage.EXTENSION,
                status="completed",
            )
        except Exception:  # noqa: BLE001 — injected input_extension
            logger.warning("Input extension failed, using raw prompt")
            result.stages_skipped.append("extend")
            self._append_backbone_event(
                result,
                BackboneStage.EXTENSION,
                status="skipped",
            )

        # --- Stage 3: Debate ---
        try:
            debate_prompt = prompt
            if result.extended_input is not None and hasattr(
                result.extended_input, "to_context_block"
            ):
                context_block = result.extended_input.to_context_block()
                if context_block:
                    debate_prompt = f"{prompt}\n\n{context_block}"

            # Apply diversity filter to agents
            debate_agents = agents
            if debate_agents and self._diversity_filter is not None:
                debate_agents, report = self._diversity_filter.enforce(debate_agents)
                result.diversity_report = report

            # Select providers via router if available
            provider_hints = None
            if self._provider_router is not None:
                try:
                    provider_hints = self._provider_router.select_providers_for_debate(
                        num_agents=agent_count,
                    )
                except Exception:  # noqa: BLE001 — injected provider_router
                    logger.warning("Provider routing failed, using default selection")

            result.debate_result = await self._do_debate(
                debate_prompt,
                debate_agents,
                rounds=debate_rounds,
                agent_count=agent_count,
                consensus_threshold=consensus_threshold,
                provider_hints=provider_hints,
                min_providers=cfg.min_providers,
            )
            self._annotate_provider_metadata(
                result.debate_result,
                provider_hints=provider_hints,
                diversity_report=result.diversity_report,
            )
            result.stages_completed.append("debate")
            deliberation_bundle = DeliberationBundle.from_debate_result(result.debate_result)
            self._update_backbone_run(
                result,
                status="deliberation_ready",
                deliberation_bundle=deliberation_bundle,
                debate_id=str(getattr(result.debate_result, "debate_id", "") or ""),
            )
            self._append_backbone_event(
                result,
                BackboneStage.DELIBERATION,
                status="completed",
                artifact_ref=str(getattr(result.debate_result, "debate_id", "") or ""),
                details={
                    "confidence": self._coerce_float(
                        getattr(result.debate_result, "confidence", 0.0)
                    ),
                    "consensus_reached": bool(
                        getattr(result.debate_result, "consensus_reached", False)
                    ),
                },
            )

            # Update phase ELO from debate
            if self._elo_tracker is not None and result.debate_result is not None:
                self._update_phase_elo(result.debate_result, cfg.domain)

            # Record provider outcomes
            if self._provider_router is not None and result.debate_result is not None:
                try:
                    consensus_reached = bool(
                        getattr(
                            result.debate_result,
                            "consensus",
                            getattr(result.debate_result, "consensus_reached", False),
                        )
                    )
                    for name in self._provider_names_for_outcome(
                        result.debate_result,
                        provider_hints=provider_hints,
                    ):
                        self._provider_router.record_outcome(
                            name,
                            consensus_reached=consensus_reached,
                        )
                except Exception:  # noqa: BLE001 — injected provider_router
                    logger.debug("Failed to record provider outcomes")

        except Exception as exc:  # noqa: BLE001 — injected arena/debate deps
            logger.error("Debate stage failed: %s", exc)
            result.errors.append(f"Debate failed: {exc}")
            result.duration_s = time.monotonic() - start
            self._update_backbone_run(
                result, status="failed", metadata={"errors": list(result.errors)}
            )
            self._append_backbone_event(
                result,
                BackboneStage.DELIBERATION,
                status="failed",
                details={"error": str(exc)},
            )
            return result

        # --- Stage 3b: Quality Gate ---
        if (
            cfg.enable_quality_gate
            and result.debate_result is not None
            and hasattr(result.debate_result, "final_answer")
        ):
            try:
                result.quality_report = await self._do_quality_gate(result.debate_result, cfg)
                result.stages_completed.append("quality_gate")

                # If quality gate rejects, stop early
                if result.quality_report is not None:
                    verdict = getattr(result.quality_report, "verdict", "good")
                    if verdict == "fail":
                        result.errors.append(
                            f"Quality gate rejected: score {getattr(result.quality_report, 'quality_score_10', 'n/a')}"
                        )
                        result.duration_s = time.monotonic() - start
                        return result
            except Exception:  # noqa: BLE001 — injected quality_validator
                logger.warning("Quality gate failed, continuing without validation")
                result.stages_skipped.append("quality_gate")

        # --- Stage 3c: Spec Extraction (OpenClaw) ---
        if (
            cfg.execution_mode == "openclaw"
            and self._spec_extractor is not None
            and result.debate_result is not None
        ):
            try:
                result.spec_bundle = self._spec_extractor(result.debate_result)
                result.stages_completed.append("spec_extraction")
                spec_bundle = result.spec_bundle
                if isinstance(spec_bundle, SpecBundle):
                    self._update_backbone_run(
                        result,
                        status="spec_ready",
                        spec_bundle=spec_bundle,
                    )
                    self._append_backbone_event(
                        result,
                        BackboneStage.SPECIFICATION,
                        status="completed",
                        details={"execution_grade": spec_bundle.is_execution_grade},
                    )
            except Exception:  # noqa: BLE001 — injected spec_extractor
                logger.warning("Spec extraction failed")
                result.stages_skipped.append("spec_extraction")
                self._append_backbone_event(
                    result,
                    BackboneStage.SPECIFICATION,
                    status="skipped",
                )

        # --- Stage 4: Create Decision Plan ---
        if result.debate_result is not None and self._plan_factory is not None:
            try:
                result.decision_plan = self._plan_factory.from_debate_result(result.debate_result)
                self._ensure_plan_backbone_metadata(result.decision_plan, result.run_id)
                goal_refs = build_goal_refs_from_implement_plan(
                    getattr(result.decision_plan, "implement_plan", None)
                )
                self._update_backbone_run(
                    result,
                    status="plan_ready",
                    plan_id=str(getattr(result.decision_plan, "id", "") or ""),
                    debate_id=str(getattr(result.decision_plan, "debate_id", "") or ""),
                    goal_refs=goal_refs,
                )
                self._append_backbone_event(
                    result,
                    BackboneStage.GOALS,
                    status="completed" if goal_refs else "skipped",
                    artifact_ref=str(getattr(result.decision_plan, "id", "") or ""),
                    details={"goal_refs_count": len(goal_refs)},
                )
                result.stages_completed.append("plan")
                self._append_backbone_event(
                    result,
                    BackboneStage.PLAN,
                    status="completed",
                    artifact_ref=str(getattr(result.decision_plan, "id", "") or ""),
                )
            except Exception:  # noqa: BLE001 — injected plan_factory
                logger.warning("Plan creation failed")
                result.stages_skipped.append("plan")
                self._append_backbone_event(
                    result,
                    BackboneStage.PLAN,
                    status="failed",
                )

        # --- Stage 5: Approval Gate ---
        if result.decision_plan is not None and gates.get("spec") is not None:
            gate = gates["spec"]
            if gate.needs_approval():
                if approval_callback is not None:
                    approved = await approval_callback("spec", result.decision_plan)
                    if not approved:
                        result.approvals_needed.append("spec")
                        result.duration_s = time.monotonic() - start
                        self._update_backbone_run(
                            result,
                            status="pending_approval",
                            metadata={"approvals_needed": list(result.approvals_needed)},
                        )
                        self._append_backbone_event(
                            result,
                            BackboneStage.PLAN,
                            status="pending_approval",
                            artifact_ref=str(getattr(result.decision_plan, "id", "") or ""),
                        )
                        return result
                else:
                    result.approvals_needed.append("spec")
                    result.duration_s = time.monotonic() - start
                    self._update_backbone_run(
                        result,
                        status="pending_approval",
                        metadata={"approvals_needed": list(result.approvals_needed)},
                    )
                    self._append_backbone_event(
                        result,
                        BackboneStage.PLAN,
                        status="pending_approval",
                        artifact_ref=str(getattr(result.decision_plan, "id", "") or ""),
                    )
                    return result

        # --- Stage 5b: Trust/Taint Execution Gate ---
        if result.decision_plan is not None:
            execution_gate = self.backbone_runtime.evaluate_execution_gate(result.decision_plan)
            metadata = getattr(result.decision_plan, "metadata", None)
            if isinstance(metadata, dict):
                metadata["execution_gate"] = execution_gate.gate
            self._update_backbone_run(
                result,
                metadata={"execution_gate": execution_gate.gate},
            )
            if not execution_gate.allow_execution:
                result.approvals_needed.append("execution")
                result.duration_s = time.monotonic() - start
                pending_status = (
                    "pending_approval" if execution_gate.requires_human_approval else "blocked"
                )
                self._update_backbone_run(
                    result,
                    status=pending_status,
                    metadata={"approvals_needed": list(result.approvals_needed)},
                )
                self._append_backbone_event(
                    result,
                    BackboneStage.EXECUTION,
                    status=pending_status,
                    artifact_ref=str(getattr(result.decision_plan, "id", "") or ""),
                    details={"reason_codes": list(execution_gate.reason_codes)},
                )
                return result

        # --- Stage 6: Execute Plan ---
        backbone_receipt_ref = ""
        if not cfg.skip_execution:
            if (
                cfg.execution_mode == "openclaw"
                and self._code_task_factory is not None
                and result.spec_bundle is not None
            ):
                try:
                    self._append_backbone_event(
                        result,
                        BackboneStage.EXECUTION,
                        status="running",
                        artifact_ref=str(getattr(result.decision_plan, "id", "") or ""),
                        details={"execution_mode": cfg.execution_mode},
                    )
                    spec = result.spec_bundle
                    exec_result = await self._code_task_factory(
                        implementation_prompt=spec.implementation_prompt
                        if hasattr(spec, "implementation_prompt")
                        else str(spec),
                        files_to_modify=getattr(spec, "files_to_modify", []),
                    )
                    result.plan_outcome = exec_result
                    result.action_bundle = {
                        "harness_name": "claude-code",
                        "action_type": "implementation",
                        "input_prompt": getattr(spec, "implementation_prompt", ""),
                        "exit_code": exec_result.get("exit_code", 0)
                        if isinstance(exec_result, dict)
                        else 0,
                    }
                    result.stages_completed.append("execute")
                    if (
                        result.decision_plan is not None
                        and result.plan_outcome is not None
                        and hasattr(result.plan_outcome, "receipt_id")
                    ):
                        backbone_receipt_ref = await self._attach_backbone_receipt(
                            result,
                            result.decision_plan,
                            result.plan_outcome,
                        )
                    self._update_backbone_run(result, status="execution_completed")
                    self._append_backbone_event(
                        result,
                        BackboneStage.EXECUTION,
                        status="succeeded",
                    )
                except Exception:  # noqa: BLE001 — injected code_task_factory
                    logger.warning("OpenClaw execution failed")
                    result.stages_skipped.append("execute")
                    self._update_backbone_run(result, status="execution_failed")
                    self._append_backbone_event(
                        result,
                        BackboneStage.EXECUTION,
                        status="failed",
                    )
            elif result.decision_plan is not None and self._plan_executor is not None:
                try:
                    self._append_backbone_event(
                        result,
                        BackboneStage.EXECUTION,
                        status="running",
                        artifact_ref=str(getattr(result.decision_plan, "id", "") or ""),
                        details={"execution_mode": cfg.execution_mode},
                    )
                    result.plan_outcome = await self._plan_executor.execute(
                        result.decision_plan,
                        execution_mode=cfg.execution_mode,
                    )
                    result.stages_completed.append("execute")
                    if result.plan_outcome is not None:
                        backbone_receipt_ref = await self._attach_backbone_receipt(
                            result,
                            result.decision_plan,
                            result.plan_outcome,
                        )
                    self._update_backbone_run(result, status="execution_completed")
                    self._append_backbone_event(
                        result,
                        BackboneStage.EXECUTION,
                        status="succeeded",
                    )
                except Exception:  # noqa: BLE001 — injected plan_executor
                    logger.warning("Execution failed")
                    result.stages_skipped.append("execute")
                    self._update_backbone_run(result, status="execution_failed")
                    self._append_backbone_event(
                        result,
                        BackboneStage.EXECUTION,
                        status="failed",
                    )

        # --- Stage 6b: Bug-Fix Loop (CLB-008) ---
        # Auto-trigger when tests fail, even without explicit enable_bug_fix_loop.
        # This makes self-repair first-class after verification failure.
        _has_test_failures = int(getattr(result.plan_outcome, "tests_failed", 0) or 0) > 0
        if (
            result.plan_outcome is not None
            and self._bug_fixer is not None
            and (cfg.enable_bug_fix_loop or _has_test_failures)
        ):
            try:
                result.bug_fix_result = await self._do_bug_fix_loop(result.plan_outcome, cfg)
                result.stages_completed.append("bug_fix")
            except Exception:  # noqa: BLE001 — injected bug_fixer
                logger.warning("Bug-fix loop failed")
                result.stages_skipped.append("bug_fix")

        # --- Stage 7: Record Outcome ---
        if self._feedback_recorder is not None and result.debate_result is not None:
            try:
                outcome = self._build_outcome(result, cfg)
                self._feedback_recorder.record(outcome)
                result.pipeline_outcome = outcome
                result.stages_completed.append("feedback")
                self._attach_backbone_feedback(
                    result,
                    receipt_ref=backbone_receipt_ref
                    or str(getattr(result.plan_outcome, "receipt_id", "") or ""),
                )
            except Exception:  # noqa: BLE001 — injected feedback_recorder
                logger.warning("Feedback recording failed")
                result.stages_skipped.append("feedback")
                self._append_backbone_event(
                    result,
                    BackboneStage.FEEDBACK,
                    status="failed",
                )

        # --- Stage 8: Meta-Loop Check ---
        if cfg.enable_meta_loop and self._meta_loop is not None:
            try:
                self._meta_loop.increment_cycle()
                if self._meta_loop.should_trigger():
                    targets = self._meta_loop.identify_targets()
                    result.meta_loop_result = self._meta_loop.execute(targets)
                result.stages_completed.append("meta_loop")
            except Exception:  # noqa: BLE001 — injected meta_loop
                logger.warning("Meta-loop check failed")
                result.stages_skipped.append("meta_loop")

        result.duration_s = time.monotonic() - start
        final_status = "completed"
        if result.errors:
            final_status = "failed"
        elif result.approvals_needed:
            final_status = "pending_approval"
        elif (
            not cfg.skip_execution
            and result.decision_plan is not None
            and "execute" in result.stages_skipped
        ):
            final_status = "execution_failed"
        self._update_backbone_run(
            result,
            status=final_status,
            metadata={"duration_s": result.duration_s},
        )
        return result

    def _load_preset(self, preset_name: str) -> dict[str, Any]:
        """Load a user preset configuration."""
        try:
            from aragora.pipeline.user_presets import get_preset

            preset = get_preset(preset_name)
            return preset.to_pipeline_config()
        except (ImportError, ValueError):
            return {}

    def _build_gates(self, autonomy_level: str) -> dict[str, Any]:
        """Build autonomy gates for the pipeline."""
        try:
            from aragora.pipeline.autonomy import AutonomyLevel, create_gates

            level = AutonomyLevel.from_string(autonomy_level)
            return create_gates(level)
        except (ImportError, ValueError):
            return {}

    async def _do_research(self, prompt: str) -> Any:
        """Run research phase."""
        if self._researcher is None:
            return None
        return await self._researcher.research(prompt)

    async def _do_extend(self, prompt: str, domain: str, research_context: Any) -> Any:
        """Run input extension phase."""
        if self._input_extension is None:
            return None
        return await self._input_extension.extend(
            prompt, domain=domain, research_context=research_context
        )

    async def _do_debate(
        self,
        prompt: str,
        agents: list[Any] | None,
        rounds: int,
        agent_count: int,
        consensus_threshold: float,
        provider_hints: list[str] | None = None,
        min_providers: int | None = None,
    ) -> Any:
        """Run debate phase."""
        if self._arena_factory is not None:
            kwargs = {
                "agents": agents,
                "rounds": rounds,
                "agent_count": agent_count,
                "consensus_threshold": consensus_threshold,
            }
            if provider_hints and self._accepts_keyword_arg(self._arena_factory, "provider_hints"):
                kwargs["provider_hints"] = provider_hints
            if min_providers is not None and self._accepts_keyword_arg(
                self._arena_factory, "min_providers"
            ):
                kwargs["min_providers"] = min_providers
            return await self._arena_factory(
                prompt,
                **kwargs,
            )
        return None

    @staticmethod
    def _accepts_keyword_arg(callable_obj: Any, keyword: str) -> bool:
        """Best-effort check for optional keyword support on injected callables."""
        try:
            sig = inspect.signature(callable_obj)
        except (TypeError, ValueError):
            return True
        if keyword in sig.parameters:
            return True
        return any(param.kind is inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values())

    @staticmethod
    def _provider_names_for_outcome(
        debate_result: Any,
        *,
        provider_hints: list[str] | None = None,
    ) -> list[str]:
        """Return provider identifiers suitable for router feedback recording."""
        metadata = getattr(debate_result, "metadata", {}) or {}
        for key in ("provider_names", "providers", "provider_hints"):
            value = metadata.get(key)
            if isinstance(value, list):
                names = [str(item) for item in value if str(item)]
                if names:
                    return names
        if provider_hints:
            return [str(item) for item in provider_hints if str(item)]
        return []

    @staticmethod
    def _annotate_provider_metadata(
        debate_result: Any,
        *,
        provider_hints: list[str] | None = None,
        diversity_report: Any | None = None,
    ) -> None:
        """Persist routed provider choices into debate metadata when available.

        Some injected arena factories already surface provider routing in their
        result metadata, while others only consume ``provider_hints`` during
        selection. Stamping the selected providers here makes routing decisions
        observable to downstream receipts and telemetry without overwriting
        richer metadata from the debate runtime itself.
        """
        if debate_result is None or not provider_hints:
            return
        metadata = getattr(debate_result, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            try:
                setattr(debate_result, "metadata", metadata)
            except (AttributeError, TypeError):
                return
        provider_names = [str(item) for item in provider_hints if str(item)]
        if not provider_names:
            provider_names = []
        if provider_names:
            metadata.setdefault("provider_hints", list(provider_names))
            metadata.setdefault("provider_names", list(provider_names))

        if diversity_report is None:
            return

        if hasattr(diversity_report, "to_receipt_payload"):
            receipt_payload = diversity_report.to_receipt_payload()
            if isinstance(receipt_payload, dict):
                metadata.setdefault("provider_diversity_report", receipt_payload)

        if getattr(diversity_report, "roster_size", 0) < 10:
            return

        if hasattr(diversity_report, "to_runtime_summary"):
            runtime_summary = diversity_report.to_runtime_summary()
            if isinstance(runtime_summary, dict):
                metadata.setdefault("large_roster_runtime", runtime_summary)

    def _update_phase_elo(self, debate_result: Any, domain: str) -> None:
        """Update phase ELO ratings from debate results."""
        elo_tracker = self._elo_tracker
        if elo_tracker is None or not hasattr(debate_result, "participants"):
            return
        domain_key = domain or "general"
        for participant in debate_result.participants:
            name = participant if isinstance(participant, str) else str(participant)
            won = hasattr(debate_result, "final_answer") and debate_result.final_answer
            elo_tracker.record_match(
                agent_name=name,
                domain=domain_key,
                phase="debate",
                won=won,
            )

    async def _do_quality_gate(self, debate_result: Any, cfg: OrchestratorConfig) -> Any:
        """Run quality gate validation on debate output."""
        if self._quality_validator is not None:
            return await self._quality_validator(
                debate_result,
                contract_path=cfg.quality_contract_path,
                min_score=cfg.quality_min_score,
            )
        # Fallback: use built-in output_quality if available
        try:
            from aragora.debate.output_quality import (
                OutputContract,
                validate_output_against_contract,
            )
            from aragora.debate.repo_grounding import assess_repo_grounding

            answer = (
                debate_result.final_answer
                if hasattr(debate_result, "final_answer")
                else str(debate_result)
            )

            # Load contract if path given
            contract = None
            if cfg.quality_contract_path:
                import json
                from pathlib import Path

                contract_data = json.loads(Path(cfg.quality_contract_path).read_text())
                contract = OutputContract(**contract_data)

            report = validate_output_against_contract(answer, cast(OutputContract, contract))

            # Enrich with repo grounding
            grounding = assess_repo_grounding(answer)
            report.practicality_score_10 = grounding.practicality_score_10

            return report
        except ImportError:
            logger.debug("Quality gate modules not available")
            return None

    async def _do_bug_fix_loop(self, plan_outcome: Any, cfg: OrchestratorConfig) -> dict[str, Any]:
        """Run bug-fix loop on execution results.

        Returns a summary dict with fix attempts and final status.
        """
        test_output = getattr(plan_outcome, "test_output", None)
        diff = getattr(plan_outcome, "diff", None)

        if test_output is None:
            return {"status": "skipped", "reason": "no test output"}

        bug_fixer = self._bug_fixer
        plan_executor = self._plan_executor
        if bug_fixer is None:
            return {"status": "skipped", "reason": "bug fixer unavailable"}

        fixes_applied: list[dict[str, Any]] = []
        for attempt in range(cfg.bug_fix_max_retries):
            diagnosis = bug_fixer.diagnose_failure(test_output, diff=diff)
            if diagnosis is None or getattr(diagnosis, "confidence", 0) < 0.3:
                break

            fix = bug_fixer.suggest_fix(diagnosis)
            if fix is None:
                break

            fixes_applied.append(
                {
                    "attempt": attempt + 1,
                    "failure_type": str(getattr(diagnosis, "failure_type", "unknown")),
                    "fix_description": getattr(fix, "description", ""),
                    "confidence": getattr(fix, "confidence", 0.0),
                }
            )

            # If executor supports re-run, apply fix and re-test
            if plan_executor is not None and hasattr(plan_executor, "apply_fix_and_retest"):
                test_output = await plan_executor.apply_fix_and_retest(fix)
                if test_output is None or "FAILED" not in str(test_output).upper():
                    return {
                        "status": "fixed",
                        "fixes_applied": fixes_applied,
                        "attempts": attempt + 1,
                    }
            else:
                break

        return {
            "status": "unfixed" if fixes_applied else "no_failures_detected",
            "fixes_applied": fixes_applied,
            "attempts": len(fixes_applied),
        }

    async def goals_to_workflow(self, goals: list[dict]) -> dict:
        """Convert a list of goal dicts into a basic workflow DAG.

        Each goal dict should have at least a ``title`` key. Optional keys:

        - ``id``          — Unique identifier for the goal (auto-generated if absent).
        - ``description`` — Human-readable description.
        - ``goal_type``   — One of ``goal``, ``milestone``, ``strategy``,
                            ``principle``, ``metric``, ``risk`` (default: ``goal``).
        - ``priority``    — ``high``, ``medium``, or ``low`` (default: ``medium``).
        - ``measurable``  — Measurable success criterion string.
        - ``dependencies``— List of goal ``id``s that must complete first.

        Returns a WorkflowDefinition-compatible dict with ``steps``,
        ``transitions``, ``entry_step``, ``id``, and ``name``.

        Example::

            orch = UnifiedOrchestrator()
            dag = await orch.goals_to_workflow([
                {"title": "Set up CI", "goal_type": "goal"},
                {"title": "Deploy to prod", "goal_type": "milestone"},
            ])
            # dag["steps"] contains the decomposed workflow steps
            # dag["transitions"] encodes the DAG edges
        """
        import uuid as _uuid

        # Decomposition templates by goal type (mirrors IdeaToExecutionPipeline)
        _DECOMPOSITION: dict[str, list[tuple[str, str, str]]] = {
            "goal": [
                ("research", "task", "Research: {title}"),
                ("implement", "task", "Implement: {title}"),
                ("test", "verification", "Test: {title}"),
                ("review", "human_checkpoint", "Review: {title}"),
            ],
            "milestone": [
                ("checkpoint", "human_checkpoint", "Checkpoint: {title}"),
                ("verify", "verification", "Verify: {title}"),
            ],
            "principle": [
                ("define", "task", "Define: {title}"),
                ("validate", "verification", "Validate: {title}"),
            ],
            "strategy": [
                ("research", "task", "Research: {title}"),
                ("design", "task", "Design: {title}"),
                ("implement", "task", "Implement: {title}"),
            ],
            "metric": [
                ("instrument", "task", "Instrument: {title}"),
                ("baseline", "verification", "Baseline: {title}"),
                ("monitor", "task", "Monitor: {title}"),
            ],
            "risk": [
                ("assess", "task", "Assess: {title}"),
                ("mitigate", "task", "Mitigate: {title}"),
                ("verify", "verification", "Verify mitigation: {title}"),
            ],
        }
        _DEFAULT_TEMPLATE: list[tuple[str, str, str]] = [("execute", "task", "{title}")]

        steps: list[dict] = []
        transitions: list[dict] = []

        # Normalise goal dicts and assign stable IDs
        normalised: list[dict] = []
        for g in goals:
            goal_id = str(g.get("id") or _uuid.uuid4())
            normalised.append(
                {
                    "id": goal_id,
                    "title": str(g.get("title", "Untitled goal")),
                    "description": str(g.get("description", "")),
                    "goal_type": str(g.get("goal_type", "goal")).lower(),
                    "priority": str(g.get("priority", "medium")).lower(),
                    "measurable": str(g.get("measurable", "")),
                    "dependencies": list(g.get("dependencies") or []),
                }
            )

        for goal in normalised:
            template = _DECOMPOSITION.get(goal["goal_type"], _DEFAULT_TEMPLATE)

            goal_step_ids: list[str] = []
            for phase, step_type, name_fmt in template:
                step_id = f"step-{goal['id']}-{phase}"
                steps.append(
                    {
                        "id": step_id,
                        "name": name_fmt.format(title=goal["title"]),
                        "description": goal["description"],
                        "step_type": step_type,
                        "source_goal_id": goal["id"],
                        "phase": phase,
                        "config": {
                            "priority": goal["priority"],
                            "measurable": goal["measurable"],
                        },
                        "timeout_seconds": 3600,
                        "retries": 1,
                        "optional": goal["priority"] == "low",
                    }
                )

                # Chain phases within a goal sequentially
                if goal_step_ids:
                    transitions.append(
                        {
                            "id": f"seq-{goal_step_ids[-1]}-{step_id}",
                            "from_step": goal_step_ids[-1],
                            "to_step": step_id,
                            "condition": "",
                            "label": "then",
                            "priority": 0,
                        }
                    )
                goal_step_ids.append(step_id)

            # Link dep goals (last step of dependency → first step of this goal)
            for dep_goal_id in goal["dependencies"]:
                dep_steps = [s for s in steps if s.get("source_goal_id") == dep_goal_id]
                if dep_steps and goal_step_ids:
                    transitions.append(
                        {
                            "id": f"dep-{dep_goal_id}-{goal['id']}",
                            "from_step": dep_steps[-1]["id"],
                            "to_step": goal_step_ids[0],
                            "condition": "",
                            "label": "after",
                            "priority": 0,
                        }
                    )

        # Chain independent goal groups sequentially
        prev_last_step: str | None = None
        for goal in normalised:
            g_steps = [s for s in steps if s.get("source_goal_id") == goal["id"]]
            if not g_steps:
                continue
            first_id = g_steps[0]["id"]
            last_id = g_steps[-1]["id"]
            has_dep = any(t["to_step"] == first_id for t in transitions)
            if not has_dep and prev_last_step:
                transitions.append(
                    {
                        "id": f"seq-{prev_last_step}-{first_id}",
                        "from_step": prev_last_step,
                        "to_step": first_id,
                        "condition": "",
                        "label": "then",
                        "priority": 0,
                    }
                )
            prev_last_step = last_id

        workflow_id = str(_uuid.uuid4())
        return {
            "id": f"wf-{workflow_id}",
            "name": "Goal Implementation Workflow",
            "steps": steps,
            "transitions": transitions,
            "entry_step": steps[0]["id"] if steps else None,
        }

    def _build_outcome(self, result: OrchestratorResult, cfg: OrchestratorConfig) -> Any:
        """Build a PipelineOutcome from the orchestrator result."""
        from aragora.pipeline.outcome_feedback import PipelineOutcome

        outcome = PipelineOutcome(
            pipeline_id=result.run_id,
            run_type="user_project",
            domain=cfg.domain or "general",
            execution_succeeded="execute" in result.stages_completed,
        )

        if result.plan_outcome is not None:
            if hasattr(result.plan_outcome, "tests_passed"):
                outcome.tests_passed = result.plan_outcome.tests_passed
            if hasattr(result.plan_outcome, "tests_failed"):
                outcome.tests_failed = result.plan_outcome.tests_failed
            if hasattr(result.plan_outcome, "files_changed"):
                outcome.files_changed = result.plan_outcome.files_changed

        outcome.total_duration_s = result.duration_s
        return outcome
