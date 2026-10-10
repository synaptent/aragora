"""Execution Bridge - connects approved DecisionPlans to the workflow engine.

When a plan is approved, the bridge:
1. Converts the DecisionPlan into a WorkflowDefinition (via plan.to_workflow_definition)
2. Hands it off to the PlanExecutor
3. Persists status transitions to PlanStore
4. Reports outcome back through the plan

Usage:
    bridge = ExecutionBridge()
    outcome = await bridge.execute_approved_plan(plan_id)

    # Or trigger execution as a fire-and-forget background task
    bridge.schedule_execution(plan_id)
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
import uuid

from aragora.pipeline.backbone_errors import BackbonePersistenceError
from aragora.pipeline.backbone_runtime import BackboneRuntime
from aragora.pipeline.decision_plan import PlanOutcome, PlanStatus
from aragora.pipeline.execution_mode import (
    ExecutionMode as SafetyMode,
    resolve_safety_mode,
)
from aragora.pipeline.execution_ownership import owner_for_plan

if TYPE_CHECKING:
    from aragora.pipeline.executor import ExecutionMode, PlanExecutor
    from aragora.pipeline.plan_store import PlanStore
    from aragora.rbac.models import AuthorizationContext

logger = logging.getLogger(__name__)


class ExecutionBridge:
    """Bridges plan approval to workflow execution.

    Loads a plan from the persistent PlanStore, validates it, runs it through
    PlanExecutor, and records status/outcome back to PlanStore.
    """

    def __init__(
        self,
        plan_store: PlanStore | None = None,
        executor: PlanExecutor | None = None,
        backbone_runtime: BackboneRuntime | None = None,
    ) -> None:
        self._plan_store = plan_store
        self._executor = executor
        self._backbone_runtime = backbone_runtime

    @property
    def plan_store(self) -> PlanStore:
        if self._plan_store is None:
            from aragora.pipeline.plan_store import get_plan_store

            self._plan_store = get_plan_store()
        return self._plan_store

    @property
    def executor(self) -> PlanExecutor:
        if self._executor is None:
            from aragora.pipeline.executor import PlanExecutor

            self._executor = PlanExecutor()
        return self._executor

    @property
    def backbone_runtime(self) -> BackboneRuntime:
        if self._backbone_runtime is None:
            self._backbone_runtime = BackboneRuntime(self.plan_store)
        return self._backbone_runtime

    @staticmethod
    def _extract_backbone_run_id(plan: Any) -> str:
        metadata = getattr(plan, "metadata", None)
        if not isinstance(metadata, dict):
            return ""
        return str(metadata.get("backbone_run_id", "") or "").strip()

    @staticmethod
    def _metadata_safety_mode(metadata: Any) -> SafetyMode | None:
        if not isinstance(metadata, dict):
            return None
        raw_value = metadata.get("safety_mode")
        if raw_value in (None, ""):
            return None
        try:
            return resolve_safety_mode(raw_value)
        except ValueError:
            logger.debug("Ignoring invalid persisted safety_mode: %s", raw_value)
            return None

    def _resolve_execution_safety_mode(
        self,
        explicit_mode: SafetyMode | None,
        *,
        auth_context: AuthorizationContext | None = None,
        execution_id: str | None = None,
        backbone_run_id: str = "",
    ) -> SafetyMode:
        if explicit_mode is not None or auth_context is not None:
            return resolve_safety_mode(explicit_mode, auth_context=auth_context)

        if execution_id:
            record = self.plan_store.get_execution_record(execution_id)
            persisted_mode = self._metadata_safety_mode(
                record.get("metadata") if isinstance(record, dict) else None
            )
            if persisted_mode is not None:
                return persisted_mode

        if backbone_run_id:
            run = self.backbone_runtime.get_run(backbone_run_id)
            persisted_mode = self._metadata_safety_mode(
                getattr(run, "metadata", None) if run is not None else None
            )
            if persisted_mode is not None:
                return persisted_mode

        return resolve_safety_mode(explicit_mode, auth_context=auth_context)

    @staticmethod
    def _backbone_required(safety_mode: SafetyMode) -> bool:
        return safety_mode == SafetyMode.INTERACTIVE

    def _backbone_failure(
        self,
        safety_mode: SafetyMode,
        message: str,
        *,
        exc: Exception | None = None,
    ) -> None:
        if self._backbone_required(safety_mode):
            raise BackbonePersistenceError(message) from exc
        if exc is not None:
            logger.warning("%s: %s", message, exc)
            return
        logger.warning("%s", message)

    def _ensure_backbone_write(
        self,
        ok: bool,
        *,
        safety_mode: SafetyMode,
        message: str,
    ) -> None:
        if not ok:
            self._backbone_failure(safety_mode, message)

    def _ensure_backbone_run(
        self,
        backbone_run_id: str,
        *,
        plan_id: str,
        safety_mode: SafetyMode,
    ) -> None:
        if backbone_run_id:
            return
        self._backbone_failure(
            safety_mode,
            f"Interactive execution requires a backbone run for plan {plan_id}",
        )

    def _ensure_execution_record(
        self,
        execution_id: str,
        *,
        safety_mode: SafetyMode,
        message: str,
    ) -> None:
        self._ensure_backbone_write(
            self.plan_store.get_execution_record(execution_id) is not None,
            safety_mode=safety_mode,
            message=message,
        )

    def _ensure_receipt_recorded(
        self,
        backbone_run_id: str,
        *,
        receipt_id: str,
        safety_mode: SafetyMode,
    ) -> None:
        if not backbone_run_id or not receipt_id:
            return
        run = self.backbone_runtime.get_run(backbone_run_id)
        self._ensure_backbone_write(
            run is not None and str(getattr(run, "receipt_id", "") or "").strip() == receipt_id,
            safety_mode=safety_mode,
            message=f"Failed to persist execution receipt {receipt_id} for backbone run {backbone_run_id}",
        )

    async def execute_approved_plan(
        self,
        plan_id: str,
        *,
        auth_context: AuthorizationContext | None = None,
        execution_mode: ExecutionMode | None = None,
        safety_mode: SafetyMode | None = None,
        execution_id: str | None = None,
        correlation_id: str | None = None,
    ) -> PlanOutcome:
        """Execute an approved plan end-to-end.

        1. Load plan from store
        2. Validate it is in an executable state
        3. Transition to EXECUTING
        4. Run through PlanExecutor
        5. Record outcome and transition to COMPLETED/FAILED

        Args:
            plan_id: ID of the plan to execute.
            auth_context: Optional RBAC context for permission checks.
            execution_mode: Override default execution mode.

        Returns:
            PlanOutcome with execution results.

        Raises:
            ValueError: If plan not found or not in executable state.
        """
        store = self.plan_store
        plan = store.get(plan_id)

        if plan is None:
            raise ValueError(f"Plan not found: {plan_id}")

        if plan.status == PlanStatus.REJECTED:
            raise ValueError(f"Plan {plan_id} was rejected and cannot be executed")
        if plan.status == PlanStatus.EXECUTING:
            raise ValueError(f"Plan {plan_id} is already executing")
        if plan.status in (PlanStatus.COMPLETED, PlanStatus.FAILED):
            raise ValueError(f"Plan {plan_id} has already been executed ({plan.status.value})")
        if plan.requires_human_approval and not plan.is_approved:
            raise ValueError(f"Plan {plan_id} requires approval before execution")

        resolved_execution_id = execution_id or f"exec-{uuid.uuid4().hex[:12]}"
        resolved_correlation_id = correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        backbone_run_id = self._extract_backbone_run_id(plan)
        resolved_safety_mode = self._resolve_execution_safety_mode(
            safety_mode,
            auth_context=auth_context,
            execution_id=resolved_execution_id,
            backbone_run_id=backbone_run_id,
        )
        self._ensure_backbone_run(
            backbone_run_id,
            plan_id=plan.id,
            safety_mode=resolved_safety_mode,
        )

        gate_decision = self.backbone_runtime.evaluate_execution_gate(plan)
        if not gate_decision.allow_execution:
            blocked_status = (
                "pending_approval" if gate_decision.requires_human_approval else "blocked"
            )
            if store.get_execution_record(resolved_execution_id) is None:
                store.create_execution_record(
                    execution_id=resolved_execution_id,
                    plan_id=plan.id,
                    debate_id=plan.debate_id,
                    correlation_id=resolved_correlation_id,
                    status=blocked_status,
                    metadata={
                        "execution_mode": execution_mode or "default",
                        "safety_mode": resolved_safety_mode.value,
                        "backbone_run_id": backbone_run_id or None,
                        "execution_gate": gate_decision.gate,
                    },
                    **owner_for_plan(plan, auth_context),
                )
            else:
                self._ensure_backbone_write(
                    store.update_execution_record(
                        resolved_execution_id,
                        status=blocked_status,
                        metadata={
                            "execution_gate": gate_decision.gate,
                            "safety_mode": resolved_safety_mode.value,
                        },
                    ),
                    safety_mode=resolved_safety_mode,
                    message=f"Failed to update blocked execution record {resolved_execution_id}",
                )
            self._ensure_execution_record(
                resolved_execution_id,
                safety_mode=resolved_safety_mode,
                message=f"Failed to persist blocked execution record {resolved_execution_id}",
            )
            if backbone_run_id:
                self._ensure_backbone_write(
                    self.backbone_runtime.record_execution_stage(
                        backbone_run_id,
                        status=blocked_status,
                        artifact_ref=resolved_execution_id,
                        run_status=blocked_status,
                        execution_id=resolved_execution_id,
                        metadata={
                            "execution_gate": gate_decision.gate,
                            "safety_mode": resolved_safety_mode.value,
                        },
                        details={
                            "plan_id": plan.id,
                            "reason_codes": gate_decision.reason_codes,
                            "safety_mode": resolved_safety_mode.value,
                        },
                    ),
                    safety_mode=resolved_safety_mode,
                    message=f"Failed to record blocked execution stage for backbone run {backbone_run_id}",
                )
            raise ValueError(
                f"Plan {plan_id} blocked by execution gate ({', '.join(gate_decision.reason_codes)})"
            )

        expected_statuses = [PlanStatus.APPROVED]
        if not plan.requires_human_approval:
            expected_statuses.append(PlanStatus.CREATED)

        # Atomic claim: ensures exactly one execution worker can transition the plan.
        claimed = store.update_status_if_current(
            plan_id,
            expected_statuses=expected_statuses,
            new_status=PlanStatus.EXECUTING,
        )
        if not claimed:
            current = store.get(plan_id)
            if current is None:
                raise ValueError(f"Plan not found: {plan_id}")
            if current.status == PlanStatus.EXECUTING:
                raise ValueError(f"Plan {plan_id} is already executing")
            if current.status in (PlanStatus.COMPLETED, PlanStatus.FAILED):
                raise ValueError(
                    f"Plan {plan_id} has already been executed ({current.status.value})"
                )
            raise ValueError(
                f"Plan {plan_id} is not in an executable state ({current.status.value})"
            )

        # The store is already claimed atomically above. Keep the local plan in
        # its pre-execution status so PlanExecutor can perform its own
        # transition and bookkeeping without tripping its duplicate-state guard.
        plan.execution_started_at = datetime.now()
        if store.get_execution_record(resolved_execution_id) is None:
            store.create_execution_record(
                execution_id=resolved_execution_id,
                plan_id=plan.id,
                debate_id=plan.debate_id,
                correlation_id=resolved_correlation_id,
                status="running",
                metadata={
                    "execution_mode": execution_mode or "default",
                    "safety_mode": resolved_safety_mode.value,
                    "started_by": getattr(auth_context, "user_id", None),
                    "backbone_run_id": backbone_run_id or None,
                    "execution_gate": gate_decision.gate,
                },
                **owner_for_plan(plan, auth_context),
            )
        else:
            self._ensure_backbone_write(
                store.update_execution_record(
                    resolved_execution_id,
                    status="running",
                    metadata={
                        "execution_mode": execution_mode or "default",
                        "safety_mode": resolved_safety_mode.value,
                        "started_by": getattr(auth_context, "user_id", None),
                        "backbone_run_id": backbone_run_id or None,
                        "execution_gate": gate_decision.gate,
                    },
                ),
                safety_mode=resolved_safety_mode,
                message=f"Failed to update running execution record {resolved_execution_id}",
            )
        self._ensure_execution_record(
            resolved_execution_id,
            safety_mode=resolved_safety_mode,
            message=f"Failed to persist running execution record {resolved_execution_id}",
        )
        if backbone_run_id:
            self._ensure_backbone_write(
                self.backbone_runtime.record_execution_stage(
                    backbone_run_id,
                    status="running",
                    artifact_ref=resolved_execution_id,
                    run_status="execution_running",
                    execution_id=resolved_execution_id,
                    metadata={
                        "execution_mode": execution_mode or "default",
                        "execution_gate": gate_decision.gate,
                        "safety_mode": resolved_safety_mode.value,
                    },
                    details={
                        "plan_id": plan.id,
                        "execution_mode": execution_mode or "default",
                        "safety_mode": resolved_safety_mode.value,
                    },
                ),
                safety_mode=resolved_safety_mode,
                message=f"Failed to record running execution stage for backbone run {backbone_run_id}",
            )

        logger.info("Executing plan %s (debate: %s)", plan_id, plan.debate_id)

        try:
            outcome = await self.executor.execute(
                plan,
                auth_context=auth_context,
                execution_mode=execution_mode,
            )
        except Exception as exc:  # noqa: BLE001 - intentional broad catch to record failure before re-raising
            logger.error("Plan %s execution failed: %s", plan_id, exc)
            store.update_status(plan_id, PlanStatus.FAILED)
            self._ensure_backbone_write(
                store.update_execution_record(
                    resolved_execution_id,
                    status="failed",
                    error={
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "at": datetime.now(timezone.utc).isoformat(),
                    },
                    metadata={
                        "execution_mode": execution_mode or "default",
                        "safety_mode": resolved_safety_mode.value,
                        "terminal_state": "failed",
                    },
                ),
                safety_mode=resolved_safety_mode,
                message=f"Failed to record failed execution {resolved_execution_id}",
            )
            if backbone_run_id:
                self._ensure_backbone_write(
                    self.backbone_runtime.record_execution_stage(
                        backbone_run_id,
                        status="failed",
                        artifact_ref=resolved_execution_id,
                        run_status="execution_failed",
                        execution_id=resolved_execution_id,
                        metadata={
                            "execution_terminal_state": "failed",
                            "safety_mode": resolved_safety_mode.value,
                        },
                        details={
                            "error": str(exc),
                            "plan_id": plan.id,
                            "safety_mode": resolved_safety_mode.value,
                        },
                    ),
                    safety_mode=resolved_safety_mode,
                    message=f"Failed to record failed execution stage for backbone run {backbone_run_id}",
                )
            raise

        # Persist final status
        final_status = PlanStatus.COMPLETED if outcome.success else PlanStatus.FAILED
        store.update_status(plan_id, final_status)
        updated_plan = store.get(plan_id) or plan
        if getattr(updated_plan, "metadata", None):
            receipt_synced = self.backbone_runtime.sync_plan_receipt_to_run(
                updated_plan,
                append_event=True,
            )
            if isinstance(getattr(updated_plan, "metadata", None), dict) and (
                updated_plan.metadata.get("decision_receipt")
                or updated_plan.metadata.get("decision_receipt_id")
            ):
                self._ensure_backbone_write(
                    receipt_synced,
                    safety_mode=resolved_safety_mode,
                    message=f"Failed to sync plan receipt for backbone run {backbone_run_id or plan.id}",
                )
        failure_error = None
        if not outcome.success:
            failure_error = {
                "type": "ExecutionFailure",
                "message": outcome.error or "Execution returned unsuccessful outcome",
                "at": datetime.now(timezone.utc).isoformat(),
            }
        self._ensure_backbone_write(
            store.update_execution_record(
                resolved_execution_id,
                status="succeeded" if outcome.success else "failed",
                error=failure_error,
                metadata={
                    "execution_mode": execution_mode or "default",
                    "safety_mode": resolved_safety_mode.value,
                    "duration_seconds": outcome.duration_seconds,
                    "tasks_completed": outcome.tasks_completed,
                    "tasks_total": outcome.tasks_total,
                    "terminal_state": "succeeded" if outcome.success else "failed",
                },
            ),
            safety_mode=resolved_safety_mode,
            message=f"Failed to finalize execution record {resolved_execution_id}",
        )
        if backbone_run_id:
            self._ensure_backbone_write(
                self.backbone_runtime.record_execution_stage(
                    backbone_run_id,
                    status="succeeded" if outcome.success else "failed",
                    artifact_ref=resolved_execution_id,
                    run_status="execution_succeeded" if outcome.success else "execution_failed",
                    execution_id=resolved_execution_id,
                    metadata={
                        "execution_terminal_state": "succeeded" if outcome.success else "failed",
                        "execution_duration_seconds": outcome.duration_seconds,
                        "safety_mode": resolved_safety_mode.value,
                    },
                    details={
                        "plan_id": plan.id,
                        "duration_seconds": outcome.duration_seconds,
                        "tasks_completed": outcome.tasks_completed,
                        "tasks_total": outcome.tasks_total,
                        "safety_mode": resolved_safety_mode.value,
                    },
                ),
                safety_mode=resolved_safety_mode,
                message=f"Failed to record terminal execution stage for backbone run {backbone_run_id}",
            )
            receipt_ref = await self.backbone_runtime.attach_execution_receipt(
                backbone_run_id,
                updated_plan,
                outcome,
            )
            self._ensure_receipt_recorded(
                backbone_run_id,
                receipt_id=str(getattr(outcome, "receipt_id", "") or "").strip(),
                safety_mode=resolved_safety_mode,
            )
            feedback_record = self.backbone_runtime.build_feedback_record(
                updated_plan,
                outcome,
                receipt_ref=receipt_ref,
                execution_mode=str(execution_mode or "default"),
            )
            self._ensure_backbone_write(
                self.backbone_runtime.attach_feedback_record(
                    backbone_run_id,
                    feedback_record,
                    artifact_ref=receipt_ref,
                    details={
                        "execution_mode": str(execution_mode or "default"),
                        "safety_mode": resolved_safety_mode.value,
                    },
                ),
                safety_mode=resolved_safety_mode,
                message=f"Failed to persist feedback record for backbone run {backbone_run_id}",
            )

        logger.info(
            "Plan %s execution %s (%.1fs, %d/%d tasks)",
            plan_id,
            "succeeded" if outcome.success else "failed",
            outcome.duration_seconds,
            outcome.tasks_completed,
            outcome.tasks_total,
        )

        return outcome

    def get_execution_record(self, execution_id: str) -> dict[str, Any] | None:
        """Fetch one execution record."""
        return self.plan_store.get_execution_record(execution_id)

    def list_execution_records(
        self,
        *,
        plan_id: str | None = None,
        debate_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List execution records for plan/debate lookups."""
        return self.plan_store.list_execution_records(
            plan_id=plan_id,
            debate_id=debate_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    def schedule_execution(
        self,
        plan_id: str,
        *,
        auth_context: AuthorizationContext | None = None,
        execution_mode: ExecutionMode | None = None,
        safety_mode: SafetyMode | None = None,
    ) -> None:
        """Schedule plan execution as a background asyncio task.

        Non-blocking: returns immediately. Autonomous errors are logged; interactive
        preflight failures raise so user-triggered execution remains fail-closed.
        """

        record_execution_id = f"exec-{uuid.uuid4().hex[:12]}"
        record_correlation_id = f"corr-{uuid.uuid4().hex[:12]}"
        resolved_safety_mode = resolve_safety_mode(safety_mode, auth_context=auth_context)
        plan = self.plan_store.get(plan_id)
        backbone_run_id = self._extract_backbone_run_id(plan) if plan is not None else ""
        if plan is not None:
            self._ensure_backbone_run(
                backbone_run_id,
                plan_id=plan.id,
                safety_mode=resolved_safety_mode,
            )
            gate_decision = self.backbone_runtime.evaluate_execution_gate(plan)
            if not gate_decision.allow_execution:
                blocked_status = (
                    "pending_approval" if gate_decision.requires_human_approval else "blocked"
                )
                self.plan_store.create_execution_record(
                    execution_id=record_execution_id,
                    plan_id=plan.id,
                    debate_id=plan.debate_id,
                    correlation_id=record_correlation_id,
                    status=blocked_status,
                    metadata={
                        "execution_mode": execution_mode or "default",
                        "safety_mode": resolved_safety_mode.value,
                        "scheduled_by": getattr(auth_context, "user_id", None),
                        "backbone_run_id": backbone_run_id or None,
                        "execution_gate": gate_decision.gate,
                    },
                    **owner_for_plan(plan, auth_context),
                )
                self._ensure_execution_record(
                    record_execution_id,
                    safety_mode=resolved_safety_mode,
                    message=f"Failed to persist blocked execution record {record_execution_id}",
                )
                if backbone_run_id:
                    self._ensure_backbone_write(
                        self.backbone_runtime.record_execution_stage(
                            backbone_run_id,
                            status=blocked_status,
                            artifact_ref=record_execution_id,
                            run_status=blocked_status,
                            execution_id=record_execution_id,
                            metadata={
                                "execution_gate": gate_decision.gate,
                                "safety_mode": resolved_safety_mode.value,
                            },
                            details={
                                "plan_id": plan.id,
                                "reason_codes": gate_decision.reason_codes,
                                "safety_mode": resolved_safety_mode.value,
                            },
                        ),
                        safety_mode=resolved_safety_mode,
                        message=f"Failed to record blocked scheduling stage for backbone run {backbone_run_id}",
                    )
                logger.warning(
                    "Execution scheduling blocked for plan %s: %s",
                    plan.id,
                    gate_decision.reason_codes,
                )
                return
            self.plan_store.create_execution_record(
                execution_id=record_execution_id,
                plan_id=plan.id,
                debate_id=plan.debate_id,
                correlation_id=record_correlation_id,
                status="queued",
                metadata={
                    "execution_mode": execution_mode or "default",
                    "safety_mode": resolved_safety_mode.value,
                    "scheduled_by": getattr(auth_context, "user_id", None),
                    "backbone_run_id": backbone_run_id or None,
                },
                **owner_for_plan(plan, auth_context),
            )
            self._ensure_execution_record(
                record_execution_id,
                safety_mode=resolved_safety_mode,
                message=f"Failed to persist queued execution record {record_execution_id}",
            )
            if backbone_run_id:
                self._ensure_backbone_write(
                    self.backbone_runtime.record_execution_stage(
                        backbone_run_id,
                        status="queued",
                        artifact_ref=record_execution_id,
                        run_status="execution_queued",
                        execution_id=record_execution_id,
                        metadata={
                            "execution_mode": execution_mode or "default",
                            "safety_mode": resolved_safety_mode.value,
                        },
                        details={
                            "plan_id": plan.id,
                            "execution_mode": execution_mode or "default",
                            "safety_mode": resolved_safety_mode.value,
                        },
                    ),
                    safety_mode=resolved_safety_mode,
                    message=f"Failed to record queued scheduling stage for backbone run {backbone_run_id}",
                )

        async def _run() -> None:
            try:
                await self.execute_approved_plan(
                    plan_id,
                    auth_context=auth_context,
                    execution_mode=execution_mode,
                    safety_mode=resolved_safety_mode,
                    execution_id=record_execution_id,
                    correlation_id=record_correlation_id,
                )
            except Exception as exc:  # noqa: BLE001 - intentional broad catch for fire-and-forget background task
                logger.error("Background execution of plan %s failed: %s", plan_id, exc)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
            logger.info("Scheduled background execution for plan %s", plan_id)
        except RuntimeError:

            def _run_in_thread() -> None:
                asyncio.run(_run())

            worker = threading.Thread(
                target=_run_in_thread,
                name=f"plan-exec-{plan_id[:8]}",
                daemon=True,
            )
            worker.start()
            logger.info(
                "Scheduled background execution for plan %s via dedicated thread",
                plan_id,
            )


# Module-level singleton
_bridge: ExecutionBridge | None = None


def get_execution_bridge() -> ExecutionBridge:
    """Return module-level ExecutionBridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = ExecutionBridge()
    return _bridge


def reset_execution_bridge() -> None:
    """Reset the singleton (for testing)."""
    global _bridge
    _bridge = None
