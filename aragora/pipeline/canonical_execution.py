"""Canonical DecisionPlan execution helpers for canvas and pipeline surfaces."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, cast

from aragora.core_types import DebateResult
from aragora.implement.types import ImplementPlan, ImplementTask
from aragora.pipeline.backbone_contracts import (
    BackboneStage,
    IntakeBundle,
    RunLedger,
    SpecBundle,
    build_goal_refs_from_implement_plan,
)
from aragora.pipeline.backbone_errors import BackbonePersistenceError
from aragora.pipeline.backbone_runtime import BackboneRuntime
from aragora.pipeline.decision_plan import ApprovalMode, DecisionPlanFactory
from aragora.pipeline.decision_plan.factory import normalize_execution_mode
from aragora.pipeline.execution_mode import (
    ExecutionMode as SafetyMode,
    resolve_safety_mode,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_ACTIONLESS_NODE_TYPES = frozenset({"agent", "label", "note", "group"})


def _flatten_node(node: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    data = node.get("data")
    if isinstance(data, dict):
        flattened.update(data)
    for key, value in node.items():
        if key == "data":
            continue
        flattened.setdefault(key, value)
    return flattened


def _flatten_edge(edge: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    data = edge.get("data")
    if isinstance(data, dict):
        flattened.update(data)
    for key, value in edge.items():
        if key == "data":
            continue
        flattened.setdefault(key, value)
    return flattened


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _extract_files(node: dict[str, Any]) -> list[str]:
    candidates: list[Any] = [
        node.get("files"),
        node.get("file_scope"),
        node.get("paths"),
        node.get("targets"),
        node.get("fileHints"),
        node.get("file_hints"),
        (node.get("metadata") or {}).get("files") if isinstance(node.get("metadata"), dict) else [],
    ]
    files: list[str] = []
    for candidate in candidates:
        files.extend(_normalize_string_list(candidate))
    deduped: list[str] = []
    seen: set[str] = set()
    for file_path in files:
        if file_path not in seen:
            deduped.append(file_path)
            seen.add(file_path)
    return deduped


def _derive_complexity(
    node: dict[str, Any],
    *,
    task_type: str,
) -> Literal["simple", "moderate", "complex"]:
    raw = str(node.get("complexity", "") or "").strip().lower()
    if raw in {"simple", "moderate", "complex"}:
        return cast(Literal["simple", "moderate", "complex"], raw)
    if task_type in {"human", "verification"}:
        return "simple"
    if task_type == "computer_use":
        return "moderate"
    return "moderate"


def _derive_task_shape(node: dict[str, Any]) -> tuple[str | None, list[str]]:
    raw_type = (
        node.get("task_type")
        or node.get("taskType")
        or node.get("orch_type")
        or node.get("orchType")
        or node.get("type")
        or "agent_task"
    )
    orch_type = str(raw_type).strip().lower().replace("-", "_")
    if node.get("computer_use_actions"):
        return "computer_use", ["computer_use"]
    if orch_type in {"human_gate", "manual", "human"}:
        return "human", ["manual"]
    if orch_type in {"browser", "ui", "computer_use", "computeruse"}:
        return "computer_use", ["computer_use", "browser"]
    if orch_type == "verification":
        return "verification", ["verification"]
    if orch_type == "debate":
        return "analysis", ["debate"]
    if orch_type in {"parallel_fan", "merge"}:
        return "coordination", ["coordination"]
    if orch_type in _ACTIONLESS_NODE_TYPES:
        return None, []
    return "implementation", []


def _task_description(node: dict[str, Any], *, index: int) -> str:
    description = (
        node.get("label")
        or node.get("name")
        or node.get("description")
        or node.get("title")
        or f"Task {index}"
    )
    return str(description).strip() or f"Task {index}"


def _task_requires_approval(node: dict[str, Any], *, require_task_approval: bool) -> bool:
    if require_task_approval:
        return True
    orch_type = str(node.get("orch_type") or node.get("orchType") or "").strip().lower()
    return bool(
        node.get("requires_approval")
        or node.get("require_approval")
        or orch_type in {"human_gate", "manual", "human"}
    )


def _extract_actionable_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened = [_flatten_node(node) for node in nodes if isinstance(node, dict)]
    actionable = []
    for node in flattened:
        task_type, _ = _derive_task_shape(node)
        if task_type is None:
            continue
        actionable.append(node)
    if actionable:
        return actionable
    return [
        node
        for node in flattened
        if str(node.get("type") or "").strip().lower() not in _ACTIONLESS_NODE_TYPES
    ]


def _build_dependency_map(tasks: list[ImplementTask], edges: list[dict[str, Any]]) -> None:
    task_ids = {task.id for task in tasks}
    for raw_edge in edges:
        if not isinstance(raw_edge, dict):
            continue
        edge = _flatten_edge(raw_edge)
        source = edge.get("source") or edge.get("from") or edge.get("from_step")
        target = edge.get("target") or edge.get("to") or edge.get("to_step")
        if source not in task_ids or target not in task_ids:
            continue
        for task in tasks:
            if task.id == target and source not in task.dependencies:
                task.dependencies.append(str(source))
                break


def _build_design_hash(
    subject_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> str:
    payload = json.dumps(
        {
            "subject_id": subject_id,
            "nodes": nodes,
            "edges": edges,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _backbone_entrypoint(plan: Any) -> str:
    metadata = getattr(plan, "metadata", None)
    source_surface = (
        str(metadata.get("source_surface", "")).strip() if isinstance(metadata, dict) else ""
    )
    return f"canonical_execution.{source_surface or 'queue_plan_execution'}"


def _build_backbone_intake(plan: Any, *, auth_context: Any | None) -> IntakeBundle:
    metadata = getattr(plan, "metadata", None)
    source_surface = (
        str(metadata.get("source_surface", "")).strip() if isinstance(metadata, dict) else ""
    )
    source_id = str(metadata.get("source_id", "")).strip() if isinstance(metadata, dict) else ""
    taint_flags = (
        [str(flag).strip() for flag in metadata.get("taint_flags", []) if str(flag).strip()]
        if isinstance(metadata, dict) and isinstance(metadata.get("taint_flags"), list | tuple)
        else []
    )
    context_refs: list[dict[str, Any]] = []
    for kind in ("pipeline_id", "canvas_id"):
        if isinstance(metadata, dict):
            resource_id = str(metadata.get(kind, "")).strip()
            if resource_id:
                context_refs.append({"kind": kind.removesuffix("_id"), "id": resource_id})
    if source_id:
        context_refs.append({"kind": "source", "id": source_id})
    scheduled_by = str(getattr(auth_context, "user_id", "") or "").strip()
    trust_tiers = ["authenticated-user"] if scheduled_by else ["service-authored"]
    origin_metadata: dict[str, Any] = {
        "debate_id": str(getattr(plan, "debate_id", "") or "").strip(),
        "source_surface": source_surface or "queue_plan_execution",
    }
    if source_id:
        origin_metadata["source_id"] = source_id
    if scheduled_by:
        origin_metadata["scheduled_by"] = scheduled_by
    return IntakeBundle(
        source_kind=source_surface or "canonical_execution",
        raw_intent=str(getattr(plan, "task", "") or "").strip(),
        context_refs=context_refs,
        trust_tiers=trust_tiers,
        origin_metadata=origin_metadata,
        taint_flags=taint_flags,
    )


def _extract_spec_bundle(plan: Any) -> SpecBundle | None:
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
        return SpecBundle(**payload)
    except TypeError:
        logger.debug("Ignoring malformed spec bundle on plan %s", getattr(plan, "id", ""))
        return None


def _backbone_write_failed(
    safety_mode: SafetyMode,
    message: str,
    *,
    exc: Exception | None = None,
) -> None:
    if safety_mode == SafetyMode.INTERACTIVE:
        raise BackbonePersistenceError(message) from exc
    if exc is not None:
        logger.warning("%s: %s", message, exc)
        return
    logger.warning("%s", message)


def _ensure_backbone_write(
    ok: bool,
    *,
    safety_mode: SafetyMode,
    message: str,
) -> None:
    if not ok:
        _backbone_write_failed(safety_mode, message)


def _plan_has_backbone_receipt(plan: Any) -> bool:
    metadata = getattr(plan, "metadata", None)
    if not isinstance(metadata, dict):
        return False
    receipt_meta = metadata.get("decision_receipt")
    if isinstance(receipt_meta, dict) and str(receipt_meta.get("receipt_id", "") or "").strip():
        return True
    return bool(str(metadata.get("decision_receipt_id", "") or "").strip())


def _ensure_backbone_run(
    plan: Any,
    *,
    auth_context: Any | None,
    execution_mode: str,
    safety_mode: SafetyMode,
    runtime: BackboneRuntime,
) -> str:
    metadata = getattr(plan, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        setattr(plan, "metadata", metadata)

    run_id = (
        str(metadata.get("backbone_run_id", "") or "").strip() or f"run-{uuid.uuid4().hex[:12]}"
    )
    entrypoint = _backbone_entrypoint(plan)
    BackboneRuntime.ensure_plan_metadata(plan, run_id, entrypoint)

    existing_run = runtime.get_run(run_id)
    goal_refs = build_goal_refs_from_implement_plan(getattr(plan, "implement_plan", None))
    source_surface = str(metadata.get("source_surface", "") or "").strip()
    source_id = str(metadata.get("source_id", "") or "").strip()
    scheduled_by = str(getattr(auth_context, "user_id", "") or "").strip()
    run_metadata: dict[str, Any] = {
        "execution_mode": execution_mode,
        "safety_mode": safety_mode.value,
        "source_surface": source_surface or "queue_plan_execution",
    }
    if source_id:
        run_metadata["source_id"] = source_id
    if scheduled_by:
        run_metadata["scheduled_by"] = scheduled_by
    for key in ("pipeline_id", "canvas_id"):
        value = str(metadata.get(key, "") or "").strip()
        if value:
            run_metadata[key] = value

    if existing_run is None:
        intake_bundle = _build_backbone_intake(plan, auth_context=auth_context)
        spec_bundle = _extract_spec_bundle(plan)
        run = RunLedger(
            run_id=run_id,
            entrypoint=entrypoint,
            status="plan_ready",
            intake_bundle=intake_bundle,
            spec_bundle=spec_bundle,
            goal_refs=goal_refs,
            plan_id=str(getattr(plan, "id", "") or "").strip(),
            debate_id=str(getattr(plan, "debate_id", "") or "").strip(),
            taint_flags=list(intake_bundle.taint_flags)
            + (list(spec_bundle.taint_flags) if spec_bundle is not None else []),
            metadata=run_metadata,
        )
        try:
            runtime.create_run(run)
            _ensure_backbone_write(
                runtime.get_run(run_id) is not None,
                safety_mode=safety_mode,
                message=f"Failed to persist backbone run {run_id}",
            )
            _ensure_backbone_write(
                runtime.append_stage_event(
                    run_id,
                    BackboneStage.INTAKE,
                    status="completed",
                    details={
                        "source_surface": source_surface or "queue_plan_execution",
                        "context_ref_count": len(intake_bundle.context_refs),
                    },
                ),
                safety_mode=safety_mode,
                message=f"Failed to record intake stage for backbone run {run_id}",
            )
            _ensure_backbone_write(
                runtime.append_stage_event(
                    run_id,
                    BackboneStage.SPECIFICATION,
                    status="completed" if spec_bundle is not None else "skipped",
                    artifact_ref="spec_bundle" if spec_bundle is not None else "",
                    details={
                        "has_spec_bundle": spec_bundle is not None,
                        "is_execution_grade": spec_bundle.is_execution_grade
                        if spec_bundle
                        else False,
                    },
                ),
                safety_mode=safety_mode,
                message=f"Failed to record specification stage for backbone run {run_id}",
            )
            _ensure_backbone_write(
                runtime.append_stage_event(
                    run_id,
                    BackboneStage.GOALS,
                    status="completed" if goal_refs else "skipped",
                    artifact_ref=str(getattr(plan, "id", "") or "").strip(),
                    details={"goal_refs_count": len(goal_refs)},
                ),
                safety_mode=safety_mode,
                message=f"Failed to record goal stage for backbone run {run_id}",
            )
            _ensure_backbone_write(
                runtime.append_stage_event(
                    run_id,
                    BackboneStage.PLAN,
                    status="completed",
                    artifact_ref=str(getattr(plan, "id", "") or "").strip(),
                    details={
                        "plan_status": getattr(
                            getattr(plan, "status", None),
                            "value",
                            str(plan.status),
                        ),
                        "approval_mode": getattr(
                            getattr(plan, "approval_mode", None),
                            "value",
                            str(getattr(plan, "approval_mode", "")),
                        ),
                    },
                ),
                safety_mode=safety_mode,
                message=f"Failed to record plan stage for backbone run {run_id}",
            )
        except Exception as exc:
            _backbone_write_failed(
                safety_mode,
                f"Failed to seed backbone run {run_id}",
                exc=exc,
            )
    else:
        try:
            _ensure_backbone_write(
                runtime.update_run(
                    run_id,
                    status="plan_ready",
                    goal_refs=goal_refs,
                    plan_id=str(getattr(plan, "id", "") or "").strip(),
                    debate_id=str(getattr(plan, "debate_id", "") or "").strip(),
                    metadata=run_metadata,
                ),
                safety_mode=safety_mode,
                message=f"Failed to update backbone run {run_id}",
            )
        except Exception as exc:
            _backbone_write_failed(
                safety_mode,
                f"Failed to update backbone run {run_id}",
                exc=exc,
            )

    return run_id


def build_decision_plan_from_orchestration(
    *,
    subject_id: str,
    subject_label: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None = None,
    source_surface: str,
    metadata: dict[str, Any] | None = None,
    budget_limit_usd: float | None = None,
    execution_mode: str | None = "workflow",
    require_task_approval: bool = False,
    approval_mode: ApprovalMode = ApprovalMode.NEVER,
) -> tuple[Any, list[ImplementTask]]:
    """Build a canonical DecisionPlan from orchestration nodes/edges."""
    actionable_nodes = _extract_actionable_nodes(nodes)
    if not actionable_nodes:
        raise ValueError(f"No actionable orchestration nodes found for {subject_label}")

    tasks: list[ImplementTask] = []
    for index, node in enumerate(actionable_nodes, start=1):
        task_type, capabilities = _derive_task_shape(node)
        task_id = str(node.get("id") or f"task-{index}")
        tasks.append(
            ImplementTask(
                id=task_id,
                description=_task_description(node, index=index),
                files=_extract_files(node),
                complexity=_derive_complexity(node, task_type=task_type or "implementation"),
                task_type=task_type,
                capabilities=capabilities,
                requires_approval=_task_requires_approval(
                    node,
                    require_task_approval=require_task_approval,
                ),
            )
        )

    _build_dependency_map(tasks, edges or [])

    task_lines = [f"{i}. {task.description}" for i, task in enumerate(tasks, start=1)]
    debate_result = DebateResult(
        debate_id=f"{source_surface}-{uuid.uuid4().hex[:12]}",
        task=subject_label,
        final_answer="\n".join(
            [
                f"Execution plan for {subject_label}",
                *task_lines,
            ]
        ),
        confidence=0.72,
        consensus_reached=True,
        rounds_used=1,
        status="completed",
        participants=[source_surface],
        metadata={
            "source_surface": source_surface,
            "source_id": subject_id,
            "node_count": len(actionable_nodes),
        },
    )

    implement_plan = ImplementPlan(
        design_hash=_build_design_hash(subject_id, actionable_nodes, edges or []),
        tasks=tasks,
    )

    plan_metadata: dict[str, Any] = {
        "source_surface": source_surface,
        "source_id": subject_id,
        "orchestration": {
            "nodes": actionable_nodes,
            "edges": edges or [],
        },
    }
    if isinstance(metadata, dict):
        plan_metadata.update(metadata)

    normalized_mode = normalize_execution_mode(execution_mode) or "workflow"
    plan = DecisionPlanFactory.from_debate_result(
        debate_result,
        budget_limit_usd=budget_limit_usd,
        approval_mode=approval_mode,
        metadata=plan_metadata,
        implement_plan=implement_plan,
        implementation_profile={"execution_mode": normalized_mode},
    )
    return plan, tasks


def queue_plan_execution(
    plan: Any,
    *,
    auth_context: Any | None = None,
    execution_mode: str | None = None,
    safety_mode: SafetyMode | None = None,
) -> dict[str, Any]:
    """Persist a plan and queue a durable execution record."""
    from aragora.pipeline.executor import store_plan
    from aragora.pipeline.plan_store import get_plan_store

    store = get_plan_store()
    runtime = BackboneRuntime(store)
    normalized_mode = normalize_execution_mode(execution_mode) or "workflow"
    resolved_safety_mode = resolve_safety_mode(safety_mode, auth_context=auth_context)
    execution_id = f"exec-{uuid.uuid4().hex[:12]}"
    correlation_id = f"corr-{uuid.uuid4().hex[:12]}"

    existing_metadata = getattr(plan, "metadata", None)
    existing_run_id = (
        str(existing_metadata.get("backbone_run_id", "") or "").strip()
        if isinstance(existing_metadata, dict)
        else ""
    )
    BackboneRuntime.ensure_plan_metadata(
        plan,
        existing_run_id or f"run-{uuid.uuid4().hex[:12]}",
        _backbone_entrypoint(plan),
    )
    if store.get(plan.id) is None:
        store.create(plan)
    else:
        store.save(plan)
    store_plan(plan)
    run_id = _ensure_backbone_run(
        plan,
        auth_context=auth_context,
        execution_mode=normalized_mode,
        safety_mode=resolved_safety_mode,
        runtime=runtime,
    )
    if _plan_has_backbone_receipt(plan):
        _ensure_backbone_write(
            runtime.sync_plan_receipt_to_run(plan, append_event=False),
            safety_mode=resolved_safety_mode,
            message=f"Failed to sync stored plan receipt to backbone run {run_id}",
        )
    else:
        runtime.sync_plan_receipt_to_run(plan, append_event=False)
    store.create_execution_record(
        execution_id=execution_id,
        plan_id=plan.id,
        debate_id=plan.debate_id,
        correlation_id=correlation_id,
        status="queued",
        metadata={
            "backbone_run_id": run_id,
            "execution_mode": normalized_mode,
            "safety_mode": resolved_safety_mode.value,
            "scheduled_by": getattr(auth_context, "user_id", None),
        },
    )
    _ensure_backbone_write(
        store.get_execution_record(execution_id) is not None,
        safety_mode=resolved_safety_mode,
        message=f"Failed to persist queued execution record {execution_id}",
    )
    _ensure_backbone_write(
        runtime.record_execution_stage(
            run_id,
            status="queued",
            artifact_ref=execution_id,
            run_status="execution_queued",
            execution_id=execution_id,
            metadata={
                "execution_mode": normalized_mode,
                "safety_mode": resolved_safety_mode.value,
                "scheduled_by": getattr(auth_context, "user_id", None),
            },
            details={
                "correlation_id": correlation_id,
                "plan_id": str(getattr(plan, "id", "") or "").strip(),
                "safety_mode": resolved_safety_mode.value,
            },
        ),
        safety_mode=resolved_safety_mode,
        message=f"Failed to record queued execution stage for backbone run {run_id}",
    )
    return {
        "plan_id": plan.id,
        "run_id": run_id,
        "execution_id": execution_id,
        "correlation_id": correlation_id,
        "execution_mode": normalized_mode,
        "safety_mode": resolved_safety_mode.value,
        "status": "queued",
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
    }


def build_decision_receipt_payload(
    plan: Any,
    outcome: Any,
) -> dict[str, Any] | None:
    """Build and persist a canonical DecisionReceipt payload."""
    if not getattr(outcome, "receipt_id", None):
        return None

    try:
        from aragora.gauntlet.receipt import DecisionReceipt

        receipt = DecisionReceipt.from_plan_outcome(outcome, plan=plan)
        receipt.receipt_id = outcome.receipt_id
        try:
            receipt.sign()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("Decision receipt signing skipped: %s", exc)
        payload = receipt.to_dict() if hasattr(receipt, "to_dict") else None
        if not isinstance(payload, dict):
            return None
        try:
            from aragora.storage.receipt_store import get_receipt_store

            get_receipt_store().save(payload)
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("Decision receipt persistence skipped: %s", exc)
        return payload
    except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
        logger.debug("Decision receipt payload unavailable: %s", exc)
        return None


async def execute_queued_plan(
    plan: Any,
    *,
    execution_id: str,
    correlation_id: str,
    auth_context: Any | None = None,
    execution_mode: str | None = None,
) -> tuple[Any, dict[str, Any] | None, dict[str, Any] | None]:
    """Execute a queued plan through ExecutionBridge and return artifacts."""
    from aragora.pipeline.execution_bridge import get_execution_bridge
    from aragora.pipeline.plan_store import get_plan_store

    bridge = get_execution_bridge()
    normalized_mode = normalize_execution_mode(execution_mode) or "workflow"
    outcome = await bridge.execute_approved_plan(
        plan.id,
        auth_context=auth_context,
        execution_mode=cast(Any, normalized_mode),
        execution_id=execution_id,
        correlation_id=correlation_id,
    )
    store = get_plan_store()
    stored_plan = store.get(plan.id) or plan
    record = bridge.get_execution_record(execution_id)
    decision_receipt = build_decision_receipt_payload(stored_plan, outcome)
    return outcome, record, decision_receipt


def schedule_coroutine(coro: Any, *, name: str) -> asyncio.Task[Any] | threading.Thread:
    """Schedule *coro* on the current event loop or a dedicated thread."""
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro, name=name)
        return task
    except RuntimeError:

        def _runner() -> None:
            asyncio.run(coro)

        worker = threading.Thread(target=_runner, name=name, daemon=True)
        worker.start()
        return worker
