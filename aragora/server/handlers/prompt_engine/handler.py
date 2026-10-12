"""Prompt Engine API Handler.

Endpoints:
- GET /api/prompt-engine/runs       - List persisted backbone runs
- GET /api/prompt-engine/runs/{id}  - Fetch one persisted backbone run
- POST /api/prompt-engine/run        - Full pipeline (decompose → interrogate → research → specify)
- POST /api/prompt-engine/decompose  - Decompose a vague prompt into structured intent
- POST /api/prompt-engine/interrogate - Generate clarifying questions for an intent
- POST /api/prompt-engine/research   - Research context for an intent
- POST /api/prompt-engine/specify    - Build a specification from intent + questions + research
- POST /api/prompt-engine/validate   - Validate a specification via SpecValidator
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, cast

from aragora.pipeline.backbone_contracts import (
    BackboneStage,
    IntakeBundle,
    RunLedger,
    RunStageEvent,
    SpecBundle,
    build_goal_refs_from_implement_plan,
)
from aragora.pipeline.backbone_errors import (
    BackbonePersistenceError,
    FAIL_CLOSED_BACKBONE_MESSAGE,
    ensure_backbone_persisted,
)
from aragora.pipeline.backbone_runtime import BackboneRuntime
from aragora.pipeline.decision_plan.factory import normalize_execution_mode
from aragora.pipeline.execution_mode import ExecutionMode as SafetyMode
from aragora.pipeline.execution_ownership import resolve_execution_owner
from aragora.pipeline.executor import ExecutionMode as ExecutorExecutionMode

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..secure import SecureHandler

logger = logging.getLogger(__name__)

_MAX_BODY = 1 * 1024 * 1024  # 1 MB


class PromptEngineHandler(SecureHandler):
    """Handler for the prompt-to-specification engine."""

    ROUTES = [
        "/api/prompt-engine/run",
        "/api/prompt-engine/decompose",
        "/api/prompt-engine/interrogate",
        "/api/prompt-engine/research",
        "/api/prompt-engine/specify",
        "/api/prompt-engine/validate",
        "/api/prompt-engine/runs",
        "/api/prompt-engine/runs/{run_id}",
    ]

    _ROUTE_MAP = {
        "POST /api/prompt-engine/run": "handle_post",
        "POST /api/prompt-engine/decompose": "handle_post",
        "POST /api/prompt-engine/interrogate": "handle_post",
        "POST /api/prompt-engine/research": "handle_post",
        "POST /api/prompt-engine/specify": "handle_post",
        "POST /api/prompt-engine/validate": "handle_post",
        "GET /api/prompt-engine/runs": "handle",
        "GET /api/prompt-engine/runs/{run_id}": "handle",
    }

    def can_handle(self, path: str, method: str | None = None) -> bool:
        # Backward-compatible signature: can_handle(method, path)
        if method is not None and not path.startswith("/") and method.startswith("/"):
            path, method = method, path
        if not path.startswith("/api/prompt-engine/"):
            return False
        if method is None:
            return True
        resolved_method = method.upper()
        if resolved_method == "GET":
            return path == "/api/prompt-engine/runs" or path.startswith("/api/prompt-engine/runs/")
        return resolved_method == "POST"

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Router-compatible GET entrypoint."""
        method = getattr(handler, "command", "GET") if handler else "GET"
        if method != "GET":
            return None
        return self._handle_get(path, query_params)

    @handle_errors
    def handle_post(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Router-compatible POST entrypoint."""
        if getattr(handler, "command", "POST") != "POST":
            return None
        return self.handle_POST(handler)

    @handle_errors("prompt engine")
    def handle_POST(self, handler: Any) -> HandlerResult:
        path = getattr(handler, "path", "")

        if path.endswith("/run"):
            return self._handle_run(handler)
        if path.endswith("/decompose"):
            return self._handle_decompose(handler)
        if path.endswith("/interrogate"):
            return self._handle_interrogate(handler)
        if path.endswith("/research"):
            return self._handle_research(handler)
        if path.endswith("/specify"):
            return self._handle_specify(handler)
        if path.endswith("/validate"):
            return self._handle_validate(handler)

        return error_response("Unknown prompt-engine endpoint", 404)

    @handle_errors("prompt engine")
    def handle_GET(
        self,
        handler: Any,
        query_params: dict[str, Any] | None = None,
    ) -> HandlerResult:
        path = getattr(handler, "path", "")
        return self._handle_get(path, query_params or {})

    # ------------------------------------------------------------------
    # Body parsing helper
    # ------------------------------------------------------------------

    def _read_body(self, handler: Any) -> dict[str, Any] | None:
        """Read and parse JSON body from the request."""
        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > _MAX_BODY:
                return None
            body = handler.rfile.read(content_length).decode("utf-8")
            return json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            logger.warning("Invalid request body: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Conductor / component factories (lazy imports)
    # ------------------------------------------------------------------

    def _make_conductor(self, data: dict[str, Any]) -> Any:
        from aragora.prompt_engine import ConductorConfig, PromptConductor
        from aragora.prompt_engine.types import AutonomyLevel

        profile = data.get("profile")
        if profile:
            config = ConductorConfig.from_profile(profile)
        else:
            config = ConductorConfig()

        autonomy = data.get("autonomy")
        if autonomy:
            try:
                config.autonomy = AutonomyLevel(autonomy)
            except ValueError:
                pass

        config.skip_research = data.get("skip_research", config.skip_research)
        config.skip_interrogation = data.get("skip_interrogation", config.skip_interrogation)

        return PromptConductor(config=config)

    @staticmethod
    def _component_timing_payload(
        stage: str,
        *,
        total_duration_ms: float,
        operation_timings: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Build a timing payload for a single prompt-engine component."""
        from aragora.prompt_engine.timing import PipelineTiming

        return PipelineTiming(
            total_duration_ms=total_duration_ms,
            stage_durations_ms={stage: total_duration_ms},
            operation_timings=list(operation_timings or []),
        ).to_dict()

    @staticmethod
    def _derive_backbone_taint_flags(context: Any) -> list[str]:
        if context in (None, "", {}, [], ()):
            return []
        return ["user_context_supplied"]

    @classmethod
    def _derive_backbone_trust_tiers(
        cls,
        context: Any,
        intent: Any | None = None,
    ) -> list[str]:
        tiers = ["operator-authored"]
        if list(getattr(intent, "related_knowledge", []) or []):
            tiers.append("internal-retrieved")
        if cls._derive_backbone_taint_flags(context):
            tiers.append("user-supplied-context")
        return list(dict.fromkeys(tiers))

    @staticmethod
    def _run_payload(
        *,
        run_id: str,
        status: str,
        plan_id: str = "",
        execution_id: str = "",
        receipt_id: str = "",
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "status": status,
            "plan_id": plan_id,
            "execution_id": execution_id,
            "receipt_id": receipt_id,
        }

    @staticmethod
    def _backbone_failure_response(exc: BackbonePersistenceError) -> HandlerResult:
        logger.warning("Prompt-engine interactive execution blocked: %s", exc)
        return error_response(FAIL_CLOSED_BACKBONE_MESSAGE, 503)

    @staticmethod
    def _query_limit(value: Any, default: int = 20) -> int:
        try:
            return max(1, min(int(value), 100))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _query_offset(value: Any, default: int = 0) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default

    def _handle_get(self, path: str, query_params: dict[str, Any]) -> HandlerResult:
        from aragora.pipeline.plan_store import get_plan_store

        store = get_plan_store()
        if path == "/api/prompt-engine/runs":
            runs = store.list_runs(
                status=str(query_params.get("status", "")).strip() or None,
                plan_id=str(query_params.get("plan_id", "")).strip() or None,
                debate_id=str(query_params.get("debate_id", "")).strip() or None,
                execution_id=str(query_params.get("execution_id", "")).strip() or None,
                limit=self._query_limit(query_params.get("limit", 20), default=20),
                offset=self._query_offset(query_params.get("offset", 0), default=0),
            )
            runs = cast(list[RunLedger], runs)
            return json_response({"runs": [run.to_dict() for run in runs]})

        prefix = "/api/prompt-engine/runs/"
        if path.startswith(prefix):
            run_id = path[len(prefix) :].strip()
            if not run_id:
                return error_response("run_id is required", 400)
            run = store.get_run(run_id)
            if run is None:
                return error_response("Run not found", 404)
            return json_response({"run": run.to_dict()})

        return error_response("Unknown prompt-engine endpoint", 404)

    # ------------------------------------------------------------------
    # Endpoint handlers
    # ------------------------------------------------------------------

    def _normalize_decision_plan_request(
        self,
        handler: Any,
        data: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, HandlerResult | None]:
        plan_data = data.get("decision_plan")
        if plan_data is None:
            return None, None
        if not isinstance(plan_data, dict):
            return None, error_response("decision_plan must be an object", 400)

        create_requested = bool(plan_data.get("create"))
        schedule_requested = bool(plan_data.get("schedule_execution"))
        if schedule_requested and not create_requested:
            return None, error_response(
                "decision_plan.schedule_execution requires decision_plan.create", 400
            )
        if not create_requested:
            return None, None

        from aragora.pipeline.decision_plan import ApprovalMode
        from aragora.pipeline.risk_register import RiskLevel

        approval_mode_raw = str(plan_data.get("approval_mode", ApprovalMode.RISK_BASED.value))
        try:
            approval_mode = ApprovalMode(approval_mode_raw)
        except ValueError:
            return None, error_response(
                f"Invalid decision_plan.approval_mode: {approval_mode_raw}",
                400,
            )

        max_auto_risk_raw = str(plan_data.get("max_auto_risk", RiskLevel.LOW.value))
        try:
            max_auto_risk = RiskLevel(max_auto_risk_raw)
        except ValueError:
            return None, error_response(
                f"Invalid decision_plan.max_auto_risk: {max_auto_risk_raw}",
                400,
            )

        budget_limit_usd = plan_data.get("budget_limit_usd")
        if budget_limit_usd is not None:
            try:
                budget_limit_usd = float(budget_limit_usd)
            except (TypeError, ValueError):
                return None, error_response("decision_plan.budget_limit_usd must be numeric", 400)

        metadata = plan_data.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            return None, error_response("decision_plan.metadata must be an object", 400)

        implementation_profile = plan_data.get("implementation_profile") or plan_data.get(
            "implementation"
        )
        if implementation_profile is not None and not isinstance(implementation_profile, dict):
            return None, error_response(
                "decision_plan.implementation_profile must be an object",
                400,
            )

        user, perm_err = self.require_permission_or_error(handler, "plans:write")
        if perm_err:
            return None, perm_err
        if schedule_requested:
            _, perm_err = self.require_permission_or_error(handler, "plans:approve")
            if perm_err:
                return None, perm_err

        return (
            {
                "create": True,
                "schedule_execution": schedule_requested,
                "approval_mode": approval_mode,
                "max_auto_risk": max_auto_risk,
                "budget_limit_usd": budget_limit_usd,
                "debate_id": str(plan_data.get("debate_id", "") or "").strip() or None,
                "task": str(plan_data.get("task", "") or "").strip() or None,
                "metadata": metadata,
                "implementation_profile": implementation_profile,
                "owner": resolve_execution_owner(user),
            },
            None,
        )

    def _handle_run(self, handler: Any) -> HandlerResult:
        """Run the full prompt-to-specification pipeline."""
        import asyncio
        from aragora.pipeline.plan_store import get_plan_store
        from aragora.prompt_engine.timing import elapsed_ms, start_timer

        request_start = start_timer()
        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        prompt = data.get("prompt", "").strip()
        if not prompt:
            return error_response("prompt is required", 400)

        plan_request, plan_error = self._normalize_decision_plan_request(handler, data)
        if plan_error:
            return plan_error

        context = data.get("context")
        store = get_plan_store()
        runtime = BackboneRuntime(store)
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        initial_taint_flags = self._derive_backbone_taint_flags(context)
        initial_intake = IntakeBundle(
            source_kind="prompt_engine_request",
            raw_intent=prompt,
            context_refs=[],
            trust_tiers=self._derive_backbone_trust_tiers(context),
            origin_metadata={
                "entrypoint": "prompt_engine.run",
                "profile": data.get("profile"),
                "autonomy": data.get("autonomy"),
                "skip_research": bool(data.get("skip_research", False)),
                "skip_interrogation": bool(data.get("skip_interrogation", False)),
            },
            taint_flags=initial_taint_flags,
        )
        run = RunLedger(
            run_id=run_id,
            entrypoint="prompt_engine.run",
            status="running",
            intake_bundle=initial_intake,
            taint_flags=list(initial_taint_flags),
            metadata={
                "decision_plan_requested": bool(plan_request),
                "schedule_execution_requested": bool(
                    plan_request and plan_request["schedule_execution"]
                ),
                "has_context": context not in (None, "", {}, [], ()),
            },
        )
        run.add_event(
            RunStageEvent.create(
                BackboneStage.INTAKE,
                status="received",
                details={
                    "prompt_length": len(prompt),
                    "has_context": context not in (None, "", {}, [], ()),
                },
            )
        )
        try:
            runtime.create_run(run)
            ensure_backbone_persisted(
                runtime.get_run(run_id) is not None,
                f"Failed to persist prompt-engine backbone run {run_id}",
            )
        except BackbonePersistenceError as exc:
            return self._backbone_failure_response(exc)

        conductor = self._make_conductor(data)

        result = asyncio.run(conductor.run(prompt, context=context))

        # Run heuristic validation on the spec
        from aragora.prompt_engine import SpecValidator

        validator = SpecValidator()
        validation_start = start_timer()
        validation = validator.validate_heuristic(result.specification)
        validation_duration_ms = elapsed_ms(validation_start)
        spec_bundle_start = start_timer()
        spec_bundle = SpecBundle.from_prompt_spec(result.specification, validation=validation)
        spec_bundle_duration_ms = elapsed_ms(spec_bundle_start)
        timing_payload = (
            result.timing.to_dict()
            if hasattr(result, "timing") and hasattr(result.timing, "to_dict")
            else {}
        )
        timing_payload["post_pipeline"] = {
            "validate": self._component_timing_payload(
                "validate",
                total_duration_ms=validation_duration_ms,
                operation_timings=validator.last_operation_timings,
            ),
            "spec_bundle": {
                "duration_ms": round(spec_bundle_duration_ms, 2),
            },
        }

        canonical_intake = IntakeBundle.from_prompt_intent(
            result.intent,
            source_kind="prompt_engine_run",
            trust_tiers=self._derive_backbone_trust_tiers(context, result.intent),
            taint_flags=initial_taint_flags,
            origin_metadata={
                "entrypoint": "prompt_engine.run",
                "question_count": len(result.questions),
                "auto_approved": bool(result.auto_approved),
                "stages_completed": list(result.stages_completed),
            },
        )
        try:
            ensure_backbone_persisted(
                runtime.update_run(
                    run_id,
                    status="spec_ready",
                    intake_bundle=canonical_intake,
                    spec_bundle=spec_bundle,
                    metadata={
                        "prompt_engine": {
                            "question_count": len(result.questions),
                            "auto_approved": bool(result.auto_approved),
                            "stages_completed": list(result.stages_completed),
                            "validation_passed": bool(getattr(validation, "passed", False)),
                        }
                    },
                ),
                f"Failed to update prompt-engine backbone run {run_id}",
            )
            ensure_backbone_persisted(
                runtime.append_stage_event(
                    run_id,
                    BackboneStage.INTENT,
                    status="completed",
                    details={
                        "intent_type": result.intent.to_dict().get("intent_type"),
                        "ambiguity_count": len(getattr(result.intent, "ambiguities", []) or []),
                    },
                ),
                f"Failed to record intent stage for backbone run {run_id}",
            )
            if "research" in result.stages_completed or result.research is not None:
                ensure_backbone_persisted(
                    runtime.append_stage_event(
                        run_id,
                        BackboneStage.RESEARCH,
                        status="completed" if result.research is not None else "skipped",
                    ),
                    f"Failed to record research stage for backbone run {run_id}",
                )
            ensure_backbone_persisted(
                runtime.append_stage_event(
                    run_id,
                    BackboneStage.SPECIFICATION,
                    status="completed",
                    artifact_ref="spec_bundle",
                    details={
                        "execution_grade": spec_bundle.is_execution_grade,
                        "missing_required_fields": list(spec_bundle.missing_required_fields),
                        "validation_passed": bool(getattr(validation, "passed", False)),
                    },
                ),
                f"Failed to record specification stage for backbone run {run_id}",
            )
        except BackbonePersistenceError as exc:
            return self._backbone_failure_response(exc)

        payload = {
            "specification": result.specification.to_dict(),
            "spec_bundle": spec_bundle.to_dict(),
            "intent": result.intent.to_dict(),
            "questions": [q.to_dict() for q in result.questions],
            "research": result.research.to_dict() if result.research else None,
            "auto_approved": result.auto_approved,
            "stages_completed": result.stages_completed,
            "validation": validation.to_dict(),
            "timing": timing_payload,
        }

        if not plan_request:
            payload["run"] = self._run_payload(run_id=run_id, status="spec_ready")
            payload["timing"]["request_total_duration_ms"] = round(elapsed_ms(request_start), 2)
            return json_response(payload)

        from aragora.pipeline.decision_plan import DecisionPlanFactory
        from aragora.pipeline.decision_plan.core import ApprovalMode, PlanStatus
        from aragora.pipeline.executor import store_plan
        from aragora.pipeline.execution_bridge import get_execution_bridge

        plan_metadata = dict(plan_request["metadata"] or {})
        plan_metadata["backbone_run_id"] = run_id
        plan_metadata["backbone_entrypoint"] = "prompt_engine.run"
        try:
            plan = DecisionPlanFactory.from_specification(
                result.specification,
                debate_id=plan_request["debate_id"],
                task=plan_request["task"],
                budget_limit_usd=plan_request["budget_limit_usd"],
                approval_mode=plan_request["approval_mode"],
                max_auto_risk=plan_request["max_auto_risk"],
                metadata=plan_metadata,
                implementation_profile=plan_request["implementation_profile"],
                validation_result=validation,
                fail_closed_spec_validation=True,
            )
        except ValueError as exc:
            try:
                ensure_backbone_persisted(
                    runtime.append_stage_event(
                        run_id,
                        BackboneStage.PLAN,
                        status="blocked",
                        details={
                            "reason": "spec_not_execution_grade",
                            "missing_required_fields": list(spec_bundle.missing_required_fields),
                        },
                    ),
                    f"Failed to record blocked plan stage for backbone run {run_id}",
                )
                ensure_backbone_persisted(
                    runtime.update_run(
                        run_id,
                        status="spec_ready",
                        metadata={"decision_plan_error": str(exc)},
                    ),
                    f"Failed to update decision-plan error state for backbone run {run_id}",
                )
            except BackbonePersistenceError as backbone_exc:
                return self._backbone_failure_response(backbone_exc)
            payload["decision_plan_error"] = {
                "message": str(exc),
                "missing_required_fields": list(spec_bundle.missing_required_fields),
            }
            payload["run"] = self._run_payload(run_id=run_id, status="spec_ready")
            payload["timing"]["request_total_duration_ms"] = round(elapsed_ms(request_start), 2)
            return json_response(payload, status=422)

        execution_gate_decision = runtime.evaluate_execution_gate(plan)
        if execution_gate_decision.requires_human_approval:
            plan.approval_mode = ApprovalMode.ALWAYS
            plan.status = PlanStatus.AWAITING_APPROVAL
            if not isinstance(plan.metadata, dict):
                plan.metadata = {}
            plan.metadata["execution_gate"] = execution_gate_decision.gate

        plan.org_id, plan.created_by = plan_request["owner"]
        store.create(plan)
        try:
            ensure_backbone_persisted(
                runtime.sync_plan_receipt_to_run(plan, append_event=False),
                f"Failed to sync decision-plan receipt for backbone run {run_id}",
            )
        except BackbonePersistenceError as exc:
            return self._backbone_failure_response(exc)
        store_plan(plan)
        payload["decision_plan"] = plan.to_dict()
        goal_refs = build_goal_refs_from_implement_plan(plan.implement_plan)
        decision_receipt = (
            plan.metadata.get("decision_receipt", {}) if isinstance(plan.metadata, dict) else {}
        )
        receipt_id = str(decision_receipt.get("receipt_id", "") or "").strip()
        run_status = (
            "plan_pending_approval"
            if plan.requires_human_approval and not plan.is_approved
            else "plan_ready"
        )
        try:
            ensure_backbone_persisted(
                runtime.update_run(
                    run_id,
                    status=run_status,
                    plan_id=plan.id,
                    debate_id=plan.debate_id,
                    receipt_id=receipt_id,
                    goal_refs=goal_refs,
                    metadata={
                        "decision_plan_status": plan.status.value,
                        "decision_plan_requires_human_approval": plan.requires_human_approval,
                        "goal_refs_count": len(goal_refs),
                        "execution_gate": execution_gate_decision.gate,
                    },
                ),
                f"Failed to update decision-plan state for backbone run {run_id}",
            )
            ensure_backbone_persisted(
                runtime.append_stage_event(
                    run_id,
                    BackboneStage.GOALS,
                    status="completed" if goal_refs else "skipped",
                    artifact_ref=plan.id,
                    details={"goal_refs_count": len(goal_refs)},
                ),
                f"Failed to record goals stage for backbone run {run_id}",
            )
            ensure_backbone_persisted(
                runtime.append_stage_event(
                    run_id,
                    BackboneStage.PLAN,
                    status="completed",
                    artifact_ref=plan.id,
                    details={
                        "plan_status": plan.status.value,
                        "approval_mode": plan.approval_mode.value,
                        "requires_human_approval": plan.requires_human_approval,
                        "execution_gate_reasons": list(execution_gate_decision.reason_codes),
                    },
                ),
                f"Failed to record plan stage for backbone run {run_id}",
            )
            if receipt_id:
                ensure_backbone_persisted(
                    runtime.append_stage_event(
                        run_id,
                        BackboneStage.RECEIPT,
                        status=str(decision_receipt.get("state", "created") or "created"),
                        artifact_ref=receipt_id,
                        details={"source": "decision_plan_receipt"},
                    ),
                    f"Failed to record receipt stage for backbone run {run_id}",
                )
        except BackbonePersistenceError as exc:
            return self._backbone_failure_response(exc)

        execution_id = ""
        if plan_request["schedule_execution"]:
            if (
                not execution_gate_decision.allow_execution
                or execution_gate_decision.requires_human_approval
                or (plan.requires_human_approval and not plan.is_approved)
            ):
                run_status = (
                    "pending_approval"
                    if execution_gate_decision.requires_human_approval
                    or (plan.requires_human_approval and not plan.is_approved)
                    else "blocked"
                )
                try:
                    ensure_backbone_persisted(
                        runtime.update_run(
                            run_id,
                            status=run_status,
                            metadata={
                                "safety_mode": SafetyMode.INTERACTIVE.value,
                                "execution_pending_approval": run_status == "pending_approval",
                                "execution_gate_blocked": run_status == "blocked",
                                "execution_gate": execution_gate_decision.gate,
                            },
                        ),
                        f"Failed to update execution gate state for backbone run {run_id}",
                    )
                    ensure_backbone_persisted(
                        runtime.append_stage_event(
                            run_id,
                            BackboneStage.EXECUTION,
                            status=run_status,
                            artifact_ref=plan.id,
                            details={
                                "requires_human_approval": run_status == "pending_approval",
                                "execution_gate_reasons": list(
                                    execution_gate_decision.reason_codes
                                ),
                                "safety_mode": SafetyMode.INTERACTIVE.value,
                            },
                        ),
                        f"Failed to record execution gate stage for backbone run {run_id}",
                    )
                except BackbonePersistenceError as exc:
                    return self._backbone_failure_response(exc)
                payload["execution"] = {
                    "status": run_status,
                    "plan_id": plan.id,
                    "requires_human_approval": run_status == "pending_approval",
                    "execution_gate": execution_gate_decision.gate,
                }
            else:
                bridge = get_execution_bridge()
                execution_mode = normalize_execution_mode(
                    plan.implementation_profile.execution_mode
                    if plan.implementation_profile
                    else None
                )
                run_status = "execution_requested"
                try:
                    ensure_backbone_persisted(
                        runtime.update_run(
                            run_id,
                            status=run_status,
                            metadata={
                                "execution_mode": execution_mode or "default",
                                "safety_mode": SafetyMode.INTERACTIVE.value,
                                "execution_requested": True,
                            },
                        ),
                        f"Failed to update execution request state for backbone run {run_id}",
                    )
                    ensure_backbone_persisted(
                        runtime.append_stage_event(
                            run_id,
                            BackboneStage.EXECUTION,
                            status="requested",
                            artifact_ref=plan.id,
                            details={
                                "execution_mode": execution_mode or "default",
                                "safety_mode": SafetyMode.INTERACTIVE.value,
                            },
                        ),
                        f"Failed to record requested execution stage for backbone run {run_id}",
                    )
                    bridge.schedule_execution(
                        plan.id,
                        execution_mode=cast(ExecutorExecutionMode | None, execution_mode),
                        safety_mode=SafetyMode.INTERACTIVE,
                    )
                except BackbonePersistenceError as exc:
                    return self._backbone_failure_response(exc)
                record = next(iter(bridge.list_execution_records(plan_id=plan.id, limit=1)), None)
                execution_payload: dict[str, Any] = {
                    "status": "scheduled",
                    "plan_id": plan.id,
                    "execution_mode": execution_mode or "default",
                }
                if record:
                    execution_payload["record"] = record
                    execution_id = str(record.get("execution_id", "") or "").strip()
                    try:
                        ensure_backbone_persisted(
                            runtime.update_run(
                                run_id,
                                status="execution_scheduled",
                                execution_id=execution_id,
                                metadata={
                                    "safety_mode": SafetyMode.INTERACTIVE.value,
                                    "scheduled_execution_status": str(
                                        record.get("status", "queued") or "queued"
                                    ),
                                },
                            ),
                            f"Failed to update scheduled execution state for backbone run {run_id}",
                        )
                        ensure_backbone_persisted(
                            runtime.append_stage_event(
                                run_id,
                                BackboneStage.EXECUTION,
                                status=str(record.get("status", "queued") or "queued"),
                                artifact_ref=execution_id,
                                details={
                                    "execution_mode": execution_mode or "default",
                                    "safety_mode": SafetyMode.INTERACTIVE.value,
                                },
                            ),
                            f"Failed to record scheduled execution stage for backbone run {run_id}",
                        )
                    except BackbonePersistenceError as exc:
                        return self._backbone_failure_response(exc)
                    run_status = "execution_scheduled"
                payload["execution"] = execution_payload

        payload["run"] = self._run_payload(
            run_id=run_id,
            status=run_status,
            plan_id=plan.id,
            execution_id=execution_id,
            receipt_id=receipt_id,
        )
        payload["timing"]["request_total_duration_ms"] = round(elapsed_ms(request_start), 2)
        return json_response(payload)

    def _handle_decompose(self, handler: Any) -> HandlerResult:
        """Decompose a vague prompt into structured intent."""
        import asyncio
        from aragora.prompt_engine.timing import elapsed_ms, start_timer

        request_start = start_timer()
        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        prompt = data.get("prompt", "").strip()
        if not prompt:
            return error_response("prompt is required", 400)

        from aragora.prompt_engine import PromptDecomposer

        decomposer = PromptDecomposer()
        context = data.get("context")
        intent = asyncio.run(decomposer.decompose(prompt, context))

        return json_response(
            {
                "intent": intent.to_dict(),
                "timing": self._component_timing_payload(
                    "decompose",
                    total_duration_ms=elapsed_ms(request_start),
                    operation_timings=decomposer.last_operation_timings,
                ),
            }
        )

    def _handle_interrogate(self, handler: Any) -> HandlerResult:
        """Generate clarifying questions for an intent."""
        import asyncio
        from aragora.prompt_engine.timing import elapsed_ms, start_timer

        request_start = start_timer()
        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        intent_data = data.get("intent")
        if not intent_data:
            return error_response("intent is required", 400)

        from aragora.prompt_engine import PromptInterrogator
        from aragora.prompt_engine.types import (
            IntentType,
            InterrogationDepth,
            PromptIntent,
        )

        intent = PromptIntent(
            raw_prompt=intent_data.get("raw_prompt", ""),
            intent_type=IntentType(intent_data.get("intent_type", "feature")),
            domains=intent_data.get("domains", []),
            ambiguities=intent_data.get("ambiguities", []),
            assumptions=intent_data.get("assumptions", []),
            scope_estimate=intent_data.get("scope_estimate", "medium"),
            summary=intent_data.get("summary", ""),
        )

        depth_str = data.get("depth", "thorough")
        try:
            depth = InterrogationDepth(depth_str)
        except ValueError:
            depth = InterrogationDepth.THOROUGH

        interrogator = PromptInterrogator()
        questions = asyncio.run(interrogator.interrogate(intent, depth=depth))

        return json_response(
            {
                "questions": [q.to_dict() for q in questions],
                "timing": self._component_timing_payload(
                    "interrogate",
                    total_duration_ms=elapsed_ms(request_start),
                    operation_timings=interrogator.last_operation_timings,
                ),
            }
        )

    def _handle_research(self, handler: Any) -> HandlerResult:
        """Research context for an intent."""
        import asyncio
        from aragora.prompt_engine.timing import elapsed_ms, start_timer

        request_start = start_timer()
        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        intent_data = data.get("intent")
        if not intent_data:
            return error_response("intent is required", 400)

        from aragora.prompt_engine import PromptResearcher
        from aragora.prompt_engine.types import IntentType, PromptIntent

        intent = PromptIntent(
            raw_prompt=intent_data.get("raw_prompt", ""),
            intent_type=IntentType(intent_data.get("intent_type", "feature")),
            domains=intent_data.get("domains", []),
            ambiguities=intent_data.get("ambiguities", []),
            assumptions=intent_data.get("assumptions", []),
            scope_estimate=intent_data.get("scope_estimate", "medium"),
            summary=intent_data.get("summary", ""),
        )

        researcher = PromptResearcher()
        context = data.get("context")
        research = asyncio.run(researcher.research(intent, context=context))

        return json_response(
            {
                "research": research.to_dict(),
                "timing": self._component_timing_payload(
                    "research",
                    total_duration_ms=elapsed_ms(request_start),
                    operation_timings=researcher.last_operation_timings,
                ),
            }
        )

    def _handle_specify(self, handler: Any) -> HandlerResult:
        """Build a specification from intent + questions + research."""
        import asyncio
        from aragora.prompt_engine.timing import elapsed_ms, start_timer

        request_start = start_timer()
        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        intent_data = data.get("intent")
        if not intent_data:
            return error_response("intent is required", 400)

        from aragora.prompt_engine import SpecBuilder
        from aragora.prompt_engine.types import (
            ClarifyingQuestion,
            IntentType,
            PromptIntent,
            ResearchReport,
        )

        intent = PromptIntent(
            raw_prompt=intent_data.get("raw_prompt", ""),
            intent_type=IntentType(intent_data.get("intent_type", "feature")),
            domains=intent_data.get("domains", []),
            ambiguities=intent_data.get("ambiguities", []),
            assumptions=intent_data.get("assumptions", []),
            scope_estimate=intent_data.get("scope_estimate", "medium"),
            summary=intent_data.get("summary", ""),
        )

        questions_data = data.get("questions", [])
        questions = [
            ClarifyingQuestion(
                question=q.get("question", ""),
                why_it_matters=q.get("why_it_matters", ""),
                options=q.get("options", []),
                answer=q.get("answer"),
            )
            for q in questions_data
        ]

        research_data = data.get("research")
        research = None
        if research_data:
            research = ResearchReport(
                summary=research_data.get("summary", ""),
                current_state=research_data.get("current_state", ""),
                recommendations=research_data.get("recommendations", []),
            )

        builder = SpecBuilder()
        context = data.get("context")
        spec = asyncio.run(builder.build(intent, questions, research, context))
        spec_bundle = SpecBundle.from_prompt_spec(spec)

        return json_response(
            {
                "specification": spec.to_dict(),
                "spec_bundle": spec_bundle.to_dict(),
                "timing": self._component_timing_payload(
                    "specify",
                    total_duration_ms=elapsed_ms(request_start),
                    operation_timings=builder.last_operation_timings,
                ),
            }
        )

    def _handle_validate(self, handler: Any) -> HandlerResult:
        """Validate a specification via SpecValidator."""
        from aragora.prompt_engine.timing import elapsed_ms, start_timer

        request_start = start_timer()
        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        spec_data = data.get("specification")
        if not spec_data:
            return error_response("specification is required", 400)

        from aragora.prompt_engine import SpecValidator
        from aragora.prompt_engine.types import RiskItem, SpecFile, Specification

        risks = []
        for r in spec_data.get("risks", []) + spec_data.get("risk_register", []):
            if isinstance(r, dict):
                risks.append(
                    RiskItem(
                        description=r.get("description", ""),
                        likelihood=r.get("likelihood", "medium"),
                        impact=r.get("impact", "medium"),
                        mitigation=r.get("mitigation", ""),
                    )
                )
        file_changes = []
        for item in spec_data.get("file_changes", []):
            if isinstance(item, dict):
                file_changes.append(
                    SpecFile(
                        path=item.get("path", ""),
                        action=item.get("action", "modify"),
                        description=item.get("description", ""),
                        estimated_lines=int(item.get("estimated_lines", 0) or 0),
                    )
                )

        spec = Specification(
            title=spec_data.get("title", ""),
            problem_statement=spec_data.get("problem_statement", ""),
            proposed_solution=spec_data.get("proposed_solution", ""),
            implementation_plan=spec_data.get("implementation_plan", []),
            success_criteria=spec_data.get("success_criteria", []),
            estimated_effort=spec_data.get("estimated_effort", ""),
            file_changes=file_changes,
            risks=risks,
            confidence=spec_data.get("confidence", 0.0),
        )
        spec.constraints = spec_data.get("constraints", [])

        validator = SpecValidator()
        result = validator.validate_heuristic(spec)
        spec_bundle = SpecBundle.from_prompt_spec(spec, validation=result)

        return json_response(
            {
                "validation": result.to_dict(),
                "spec_bundle": spec_bundle.to_dict(),
                "timing": self._component_timing_payload(
                    "validate",
                    total_duration_ms=elapsed_ms(request_start),
                    operation_timings=validator.last_operation_timings,
                ),
            }
        )
