"""Helpers for emitting decision integrity packages to channels."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
import uuid

from aragora.pipeline.execution_mode import (
    ExecutionMode as SafetyMode,
    resolve_safety_mode,
)

if TYPE_CHECKING:
    from aragora.pipeline.executor import ExecutionMode

logger = logging.getLogger(__name__)


def extract_execution_overrides(text: str) -> tuple[str, dict[str, Any]]:
    """Extract execution override flags from command text.

    Parses flags like --computer-use, --hybrid, --fabric from the text
    and returns the cleaned text along with execution overrides.

    Args:
        text: Input text potentially containing execution flags

    Returns:
        Tuple of (cleaned_text, overrides_dict)
    """
    overrides: dict[str, Any] = {}
    cleaned_parts: list[str] = []

    parts = text.split()
    i = 0
    while i < len(parts):
        part = parts[i]
        if part == "--computer-use":
            overrides["execution_mode"] = "execute"
            overrides["execution_engine"] = "computer_use"
        elif part == "--hybrid":
            overrides["execution_mode"] = "execute"
            overrides["execution_engine"] = "hybrid"
        elif part == "--fabric":
            overrides["execution_mode"] = "execute"
            overrides["execution_engine"] = "fabric"
        elif part == "--workflow":
            overrides["execution_mode"] = "workflow"
        elif part == "--execute":
            overrides["execution_mode"] = "execute"
        elif part == "--plan-only":
            overrides["execution_mode"] = "plan_only"
        else:
            cleaned_parts.append(part)
        i += 1

    cleaned_text = " ".join(cleaned_parts)
    return cleaned_text, overrides


def _extract_implementation_profile(cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Extract implementation profile settings from a decision-integrity config."""
    profile = cfg.get("implementation_profile")
    if isinstance(profile, dict):
        return profile

    profile = cfg.get("implementation")
    if isinstance(profile, dict):
        return profile

    keys = {
        "execution_mode",
        "implementers",
        "critic",
        "reviser",
        "strategy",
        "max_revisions",
        "parallel_execution",
        "max_parallel",
        "fabric_pool_id",
        "fabric_models",
        "fabric_min_agents",
        "fabric_max_agents",
        "fabric_timeout_seconds",
        "task_type_router",
        "capability_router",
        "channel_targets",
        "thread_id",
        "thread_id_by_platform",
    }
    extracted: dict[str, Any] = {}
    for key in keys:
        if key in cfg:
            extracted[key] = cfg.get(key)

    return extracted or None


def _serialize_approval_request(approval_request: Any) -> dict[str, Any]:
    """Serialize ApprovalRequest into a JSON-friendly payload."""
    return {
        "id": approval_request.id,
        "title": approval_request.title,
        "description": approval_request.description,
        "changes": approval_request.changes,
        "risk_level": approval_request.risk_level,
        "requested_at": approval_request.requested_at.isoformat(),
        "requested_by": approval_request.requested_by,
        "timeout_seconds": approval_request.timeout_seconds,
        "status": approval_request.status.value,
        "approved_by": approval_request.approved_by,
        "approved_at": (
            approval_request.approved_at.isoformat() if approval_request.approved_at else None
        ),
        "rejection_reason": approval_request.rejection_reason,
        "metadata": approval_request.metadata,
    }


def _extract_spec_bundle(plan: Any) -> Any | None:
    metadata = getattr(plan, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    spec_payload = metadata.get("spec_bundle")
    if not isinstance(spec_payload, dict):
        return None
    payload = dict(spec_payload)
    payload.pop("missing_required_fields", None)
    payload.pop("is_execution_grade", None)
    try:
        from aragora.pipeline.backbone_contracts import SpecBundle

        return SpecBundle(**payload)
    except (ImportError, TypeError):
        logger.debug("Ignoring malformed spec bundle on plan %s", getattr(plan, "id", ""))
        return None


def _normalize_execution_request_for_safety_mode(
    execution_mode: Any,
    *,
    safety_mode: SafetyMode,
) -> str:
    """Downgrade interactive execution requests to approval-first semantics."""
    if not isinstance(safety_mode, SafetyMode):
        raise TypeError("safety_mode must be an ExecutionMode")

    if isinstance(execution_mode, SafetyMode):
        normalized = execution_mode.value
    elif isinstance(execution_mode, str):
        normalized = execution_mode.strip().lower()
    else:
        normalized = ""

    if not normalized:
        normalized = "plan_only"

    if safety_mode == SafetyMode.INTERACTIVE and normalized == "execute":
        return "request_approval"
    return normalized


def ensure_decision_plan_backbone_run(
    plan: Any,
    *,
    auth_context: Any | None,
    source_surface: str,
    source_id: str,
) -> str:
    """Seed a RunLedger for a decision plan before persistence or execution."""
    from aragora.pipeline.backbone_contracts import (
        BackboneStage,
        IntakeBundle,
        RunLedger,
        build_goal_refs_from_implement_plan,
    )
    from aragora.pipeline.backbone_runtime import BackboneRuntime
    from aragora.pipeline.plan_store import get_plan_store

    metadata = getattr(plan, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        setattr(plan, "metadata", metadata)

    metadata.setdefault("source_surface", source_surface)
    if source_id:
        metadata.setdefault("source_id", source_id)

    run_id = (
        str(metadata.get("backbone_run_id", "") or "").strip() or f"run-{uuid.uuid4().hex[:12]}"
    )
    entrypoint = f"decision_integrity.{source_surface}"
    BackboneRuntime.ensure_plan_metadata(plan, run_id, entrypoint)

    runtime = BackboneRuntime(get_plan_store())
    scheduled_by = str(getattr(auth_context, "user_id", "") or "").strip()
    goal_refs = build_goal_refs_from_implement_plan(getattr(plan, "implement_plan", None))
    run_metadata: dict[str, Any] = {"source_surface": source_surface}
    if source_id:
        run_metadata["source_id"] = source_id
    if scheduled_by:
        run_metadata["scheduled_by"] = scheduled_by

    if runtime.get_run(run_id) is None:
        intake = IntakeBundle(
            source_kind=source_surface,
            raw_intent=str(getattr(plan, "task", "") or "").strip(),
            context_refs=(
                [{"kind": "debate", "id": str(getattr(plan, "debate_id", "") or "").strip()}]
                if str(getattr(plan, "debate_id", "") or "").strip()
                else []
            )
            + ([{"kind": "source", "id": source_id}] if source_id else []),
            trust_tiers=["authenticated-user"] if scheduled_by else ["service-authored"],
            origin_metadata={
                "debate_id": str(getattr(plan, "debate_id", "") or "").strip(),
                "source_surface": source_surface,
                **({"source_id": source_id} if source_id else {}),
                **({"scheduled_by": scheduled_by} if scheduled_by else {}),
            },
            taint_flags=[
                str(flag).strip() for flag in metadata.get("taint_flags", []) if str(flag).strip()
            ]
            if isinstance(metadata.get("taint_flags"), list | tuple)
            else [],
        )
        spec_bundle = _extract_spec_bundle(plan)
        run = RunLedger(
            run_id=run_id,
            entrypoint=entrypoint,
            status="plan_ready",
            intake_bundle=intake,
            spec_bundle=spec_bundle,
            goal_refs=goal_refs,
            plan_id=str(getattr(plan, "id", "") or "").strip(),
            debate_id=str(getattr(plan, "debate_id", "") or "").strip(),
            taint_flags=list(intake.taint_flags)
            + (list(spec_bundle.taint_flags) if spec_bundle is not None else []),
            metadata=run_metadata,
        )
        runtime.create_run(run)
        runtime.append_stage_event(
            run_id,
            BackboneStage.INTAKE,
            status="completed",
            details={"source_surface": source_surface},
        )
        runtime.append_stage_event(
            run_id,
            BackboneStage.SPECIFICATION,
            status="completed" if spec_bundle is not None else "skipped",
            artifact_ref="spec_bundle" if spec_bundle is not None else "",
            details={"has_spec_bundle": spec_bundle is not None},
        )
        runtime.append_stage_event(
            run_id,
            BackboneStage.GOALS,
            status="completed" if goal_refs else "skipped",
            artifact_ref=str(getattr(plan, "id", "") or "").strip(),
            details={"goal_refs_count": len(goal_refs)},
        )
        runtime.append_stage_event(
            run_id,
            BackboneStage.PLAN,
            status="completed",
            artifact_ref=str(getattr(plan, "id", "") or "").strip(),
            details={
                "plan_status": getattr(getattr(plan, "status", None), "value", str(plan.status)),
                "approval_mode": getattr(
                    getattr(plan, "approval_mode", None),
                    "value",
                    str(getattr(plan, "approval_mode", "")),
                ),
            },
        )
    else:
        runtime.update_run(
            run_id,
            status="plan_ready",
            goal_refs=goal_refs,
            plan_id=str(getattr(plan, "id", "") or "").strip(),
            debate_id=str(getattr(plan, "debate_id", "") or "").strip(),
            metadata=run_metadata,
        )

    return run_id


def sync_decision_plan_backbone_receipt(
    plan: Any,
    *,
    append_event: bool,
) -> bool:
    """Mirror the current decision receipt state into the RunLedger."""
    from aragora.pipeline.backbone_runtime import BackboneRuntime
    from aragora.pipeline.plan_store import get_plan_store

    return BackboneRuntime(get_plan_store()).sync_plan_receipt_to_run(
        plan,
        append_event=append_event,
    )


async def execute_decision_plan_with_backbone(
    plan: Any,
    *,
    executor: Any,
    auth_context: Any | None,
    execution_mode: str | None,
    safety_mode: SafetyMode | None = None,
) -> tuple[dict[str, Any], Any]:
    """Queue and execute a decision plan through ExecutionBridge with a supplied executor."""
    from aragora.pipeline.canonical_execution import queue_plan_execution
    from aragora.pipeline.execution_bridge import ExecutionBridge
    from aragora.pipeline.plan_store import get_plan_store

    launch = queue_plan_execution(
        plan,
        auth_context=auth_context,
        execution_mode=execution_mode,
        safety_mode=safety_mode,
    )
    bridge = ExecutionBridge(plan_store=get_plan_store(), executor=executor)
    raw_mode = str(launch.get("execution_mode", execution_mode or "")).strip() or None
    outcome = await bridge.execute_approved_plan(
        plan.id,
        auth_context=auth_context,
        execution_mode=cast("ExecutionMode | None", raw_mode),
        safety_mode=resolve_safety_mode(safety_mode, auth_context=auth_context),
        execution_id=str(launch.get("execution_id", "") or ""),
        correlation_id=str(launch.get("correlation_id", "") or ""),
    )
    return launch, outcome


async def build_decision_integrity_payload(
    *,
    result: Any,
    debate_id: str | None,
    arena: Any | None,
    decision_integrity: dict[str, Any] | bool | None,
    document_store: Any | None = None,
    evidence_store: Any | None = None,
    notify_origin_override: bool | None = None,
) -> dict[str, Any] | None:
    """Build a decision integrity payload, optionally executing the plan."""
    if decision_integrity is None:
        return None
    if isinstance(decision_integrity, bool):
        if not decision_integrity:
            return None
        cfg: dict[str, Any] = {}
    elif isinstance(decision_integrity, dict):
        cfg = decision_integrity
    else:
        return None

    execution_mode = str(cfg.get("execution_mode", "plan_only")).lower()
    execution_engine = str(cfg.get("execution_engine", "")).lower()
    if execution_mode in {"hybrid", "fabric", "computer_use"}:
        execution_engine = execution_mode
        execution_mode = "execute"

    auth_context = getattr(arena, "auth_context", None)
    safety_mode = resolve_safety_mode(None, auth_context=auth_context)
    execution_mode = _normalize_execution_request_for_safety_mode(
        execution_mode,
        safety_mode=safety_mode,
    )

    workflow_mode = execution_mode in {"workflow", "workflow_execute", "execute_workflow"}
    execute_workflow = execution_mode in {"workflow_execute", "execute_workflow"}

    include_receipt = bool(cfg.get("include_receipt", True))
    include_plan = bool(cfg.get("include_plan", True))
    include_context = bool(cfg.get("include_context", False))
    plan_strategy = str(cfg.get("plan_strategy", "single_task"))
    notify_origin = (
        bool(cfg.get("notify_origin", True))
        if notify_origin_override is None
        else notify_origin_override
    )

    if execution_mode in {"request_approval", "execute"} or workflow_mode:
        include_plan = True

    if not any([include_receipt, include_plan, include_context]):
        return None

    try:
        from aragora.pipeline.decision_integrity import (
            build_decision_integrity_package,
            coerce_debate_result,
        )
    except (ImportError, AttributeError) as exc:
        logger.debug("Decision integrity pipeline unavailable: %s", exc)
        return None

    debate_payload: dict[str, Any] = {}
    if hasattr(result, "to_dict"):
        try:
            debate_payload = result.to_dict()
        except (AttributeError, TypeError, ValueError):
            debate_payload = {}
    if not debate_payload:
        debate_payload = {
            "debate_id": getattr(result, "debate_id", "") or "",
            "task": getattr(result, "task", "") or "",
            "final_answer": getattr(result, "final_answer", "") or "",
            "confidence": getattr(result, "confidence", 0.0) or 0.0,
            "consensus_reached": getattr(result, "consensus_reached", False) or False,
            "rounds_used": getattr(result, "rounds_used", 0) or 0,
            "participants": getattr(result, "participants", []) or [],
        }
    if debate_id:
        debate_payload["debate_id"] = debate_id

    continuum_memory = getattr(arena, "continuum_memory", None) if include_context else None
    cross_debate_memory = getattr(arena, "cross_debate_memory", None) if include_context else None
    knowledge_mound = getattr(arena, "knowledge_mound", None) if include_context else None
    context_envelope = None
    if auth_context is not None:
        try:
            from aragora.memory.access import build_access_envelope

            context_envelope = build_access_envelope(
                auth_context,
                source="server.decision_integrity_utils",
            )
        except (ImportError, AttributeError):
            context_envelope = None

    try:
        package = await build_decision_integrity_package(
            debate_payload,
            include_receipt=include_receipt,
            include_plan=include_plan,
            include_context=include_context,
            plan_strategy=plan_strategy,
            continuum_memory=continuum_memory,
            cross_debate_memory=cross_debate_memory,
            knowledge_mound=knowledge_mound,
            document_store=document_store,
            evidence_store=evidence_store,
            auth_context=auth_context,
            context_envelope=context_envelope,
        )
    except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
        logger.debug("Decision integrity build failed: %s", exc)
        return None

    payload = package.to_dict()

    # Include execution configuration in the payload
    if execution_mode and execution_mode != "plan_only":
        payload["execution_mode"] = execution_mode
    if execution_engine:
        payload["execution_engine"] = execution_engine

    debate_key = (
        payload.get("debate_id")
        or debate_payload.get("debate_id")
        or debate_id
        or getattr(result, "id", None)
    )

    plan = None
    if execution_mode in {"request_approval", "execute"} or workflow_mode:
        if package.plan is None:
            logger.debug("Decision integrity execution requested but no plan available.")
        else:
            try:
                from aragora.pipeline.decision_plan import ApprovalMode, DecisionPlanFactory
                from aragora.pipeline.executor import store_plan
                from aragora.pipeline.risk_register import RiskLevel

                approval_mode_raw = str(cfg.get("approval_mode", "risk_based"))
                try:
                    approval_mode = ApprovalMode(approval_mode_raw)
                except ValueError:
                    approval_mode = ApprovalMode.RISK_BASED

                max_auto_risk_raw = str(cfg.get("max_auto_risk", "low"))
                try:
                    max_auto_risk = RiskLevel(max_auto_risk_raw)
                except ValueError:
                    max_auto_risk = RiskLevel.LOW

                budget_limit = None
                budget_value = cfg.get("budget_limit_usd")
                if budget_value is not None:
                    try:
                        budget_limit = float(budget_value)
                    except (TypeError, ValueError):
                        budget_limit = None

                metadata: dict[str, Any] = {
                    "source": "decision_integrity",
                    "debate_id": debate_key,
                    "source_surface": "decision_integrity_payload",
                    "source_id": str(debate_key or ""),
                }
                if isinstance(cfg.get("openclaw_actions"), list):
                    metadata["openclaw_actions"] = cfg.get("openclaw_actions")
                if isinstance(cfg.get("computer_use_actions"), list):
                    metadata["computer_use_actions"] = cfg.get("computer_use_actions")
                if isinstance(cfg.get("openclaw_session"), dict):
                    metadata["openclaw_session"] = cfg.get("openclaw_session")

                repo_root = cfg.get("repo_path") or cfg.get("repo_root")
                if not repo_root:
                    repo_root = getattr(arena, "repo_root", None)
                if not repo_root:
                    repo_root = os.environ.get("ARAGORA_REPO_ROOT")
                repo_path = Path(repo_root) if repo_root else None

                implementation_profile = _extract_implementation_profile(cfg)
                if implementation_profile:
                    metadata.setdefault("implementation_profile", implementation_profile)
                    if "channel_targets" not in metadata and isinstance(
                        implementation_profile.get("channel_targets"), list
                    ):
                        metadata["channel_targets"] = implementation_profile.get("channel_targets")
                    if "thread_id" not in metadata and isinstance(
                        implementation_profile.get("thread_id"), str
                    ):
                        metadata["thread_id"] = implementation_profile.get("thread_id")
                    if "thread_id_by_platform" not in metadata and isinstance(
                        implementation_profile.get("thread_id_by_platform"), dict
                    ):
                        metadata["thread_id_by_platform"] = implementation_profile.get(
                            "thread_id_by_platform"
                        )

                plan = DecisionPlanFactory.from_debate_result(
                    coerce_debate_result(debate_payload),
                    budget_limit_usd=budget_limit,
                    approval_mode=approval_mode,
                    max_auto_risk=max_auto_risk,
                    repo_path=repo_path,
                    metadata=metadata,
                    implement_plan=package.plan,
                    implementation_profile=implementation_profile,
                )
                run_id = ensure_decision_plan_backbone_run(
                    plan,
                    auth_context=auth_context,
                    source_surface="decision_integrity_payload",
                    source_id=str(debate_key or ""),
                )
                store_plan(plan)
                sync_decision_plan_backbone_receipt(plan, append_event=False)
                payload["decision_plan"] = plan.to_dict()
                payload["plan_id"] = plan.id
                payload["run_id"] = run_id
            except (ImportError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                logger.debug("Decision plan creation failed: %s", exc)

    approval_request = None
    if plan is not None:
        request_approval = execution_mode in {"request_approval", "execute"}
        if workflow_mode and plan.requires_human_approval:
            request_approval = True

        if request_approval:
            try:
                from aragora.server.handlers.autonomous.approvals import get_approval_flow

                requested_by = str(cfg.get("requested_by") or "system")
                changes = []
                if plan.implement_plan is not None:
                    for task in plan.implement_plan.tasks:
                        changes.append(
                            {
                                "id": task.id,
                                "description": task.description,
                                "files": task.files,
                                "complexity": task.complexity,
                            }
                        )
                approval_flow = get_approval_flow()
                approval_request = await approval_flow.request_approval(
                    title=f"Implement debate {plan.debate_id}",
                    description="Execute decision implementation plan generated from debate.",
                    changes=changes,
                    risk_level=str(cfg.get("risk_level", "medium")),
                    requested_by=requested_by,
                    timeout_seconds=cfg.get("approval_timeout_seconds"),
                    metadata={"debate_id": plan.debate_id, "plan_id": plan.id},
                )
                payload["approval"] = _serialize_approval_request(approval_request)
                try:
                    from aragora.autonomous.loop_enhancement import ApprovalStatus

                    if approval_request.status in {
                        ApprovalStatus.APPROVED,
                        ApprovalStatus.AUTO_APPROVED,
                    }:
                        plan.approve(
                            approver_id=approval_request.approved_by or requested_by or "system",
                            reason="Auto-approved by policy"
                            if approval_request.status == ApprovalStatus.AUTO_APPROVED
                            else "Approved",
                        )
                        from aragora.pipeline.executor import store_plan

                        store_plan(plan)
                        sync_decision_plan_backbone_receipt(plan, append_event=True)
                except (ImportError, OSError, RuntimeError):
                    logger.debug("Failed to store approved plan", exc_info=True)
            except (ImportError, ValueError, TypeError, RuntimeError, OSError) as exc:
                logger.debug("Approval request failed: %s", exc)

    execution_payload: dict[str, Any] | None = None
    should_execute = execution_mode == "execute" or execute_workflow
    if plan is not None and should_execute:
        if os.environ.get("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "0") != "1":
            execution_payload = {
                "status": "disabled",
                "reason": "Set ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION=1 to enable.",
            }
        elif plan.requires_human_approval and not plan.is_approved:
            execution_payload = {
                "status": "pending_approval",
                "approval_id": approval_request.id if approval_request else None,
                "run_id": payload.get("run_id"),
            }
        else:
            try:
                from aragora.pipeline.executor import PlanExecutor
                from aragora.pipeline.execution_notifier import ExecutionNotifier

                engine: str = execution_engine or ("workflow" if workflow_mode else "hybrid")
                parallel_execution = bool(cfg.get("parallel_execution", False))

                notifier = None
                if engine == "hybrid":
                    notifier = ExecutionNotifier(
                        debate_id=plan.debate_id or str(debate_key or ""),
                        plan_id=plan.id,
                        notify_channel=notify_origin,
                        notify_websocket=notify_origin,
                    )
                    if plan.implement_plan is not None:
                        notifier.set_task_descriptions(plan.implement_plan.tasks)

                executor = PlanExecutor(
                    continuum_memory=getattr(arena, "continuum_memory", None),
                    knowledge_mound=getattr(arena, "knowledge_mound", None),
                    parallel_execution=parallel_execution,
                    execution_mode=engine,  # type: ignore[arg-type]
                )
                resolved_safety_mode = resolve_safety_mode(None, auth_context=auth_context)
                launch, outcome = await execute_decision_plan_with_backbone(
                    plan,
                    executor=executor,
                    auth_context=auth_context,
                    execution_mode=engine,
                    safety_mode=resolved_safety_mode,
                )
                if notifier and notify_origin:
                    await notifier.send_completion_summary()
                execution_payload = {
                    "status": "completed" if outcome.success else "failed",
                    "mode": str(launch.get("execution_mode", engine) or engine),
                    "run_id": launch.get("run_id"),
                    "execution_id": launch.get("execution_id"),
                    "correlation_id": launch.get("correlation_id"),
                    "outcome": outcome.to_dict(),
                }
            except (ImportError, ValueError, TypeError, RuntimeError, OSError) as exc:
                execution_payload = {
                    "status": "failed",
                    "mode": execution_engine or ("workflow" if workflow_mode else "hybrid"),
                    "run_id": payload.get("run_id"),
                    "error": str(exc),
                }

    if execution_payload is not None:
        if workflow_mode:
            payload["workflow_execution"] = execution_payload
        else:
            payload["execution"] = execution_payload

    if notify_origin and debate_key:
        try:
            from aragora.server.result_router import route_result

            await route_result(
                debate_key,
                {
                    "debate_id": debate_key,
                    "event": "decision_integrity",
                    "package": payload,
                },
            )
        except (ImportError, ValueError, RuntimeError, OSError, ConnectionError) as exc:
            logger.debug("Decision integrity routing failed: %s", exc)

    return payload


async def maybe_emit_decision_integrity(
    *,
    result: Any,
    debate_id: str | None,
    arena: Any | None,
    decision_integrity: dict[str, Any] | bool | None,
    document_store: Any | None = None,
    evidence_store: Any | None = None,
) -> None:
    """Optionally build and route a decision integrity package."""
    await build_decision_integrity_payload(
        result=result,
        debate_id=debate_id,
        arena=arena,
        decision_integrity=decision_integrity,
        document_store=document_store,
        evidence_store=evidence_store,
    )
