"""Decision integrity operations for debates.

Provides the POST /api/v1/debates/{id}/decision-integrity endpoint which:
- Generates a decision receipt (audit trail)
- Creates an implementation plan (for multi-agent execution)
- Optionally captures a context snapshot (memory + knowledge state)
- Persists receipt and plan for later retrieval via /api/v2/receipts/
- Enforces budget limits before execution
- Supports approval flow and parallel execution
- Routes results to originating channel
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol

from aragora.rbac.decorators import require_permission
from aragora.server.http_utils import run_async

from aragora.pipeline.backbone_errors import (
    BackbonePersistenceError,
    FAIL_CLOSED_BACKBONE_MESSAGE,
    ensure_backbone_persisted,
)
from aragora.pipeline.decision_integrity import (
    build_decision_integrity_package,
    coerce_debate_result,
)
from aragora.pipeline.execution_mode import ExecutionMode as SafetyMode
from aragora.pipeline.decision_integrity_utils import (
    ensure_decision_plan_backbone_run,
    execute_decision_plan_with_backbone,
    sync_decision_plan_backbone_receipt,
)
from aragora.server.result_router import route_result
from aragora.implement import HybridExecutor
from aragora.pipeline.execution_notifier import ExecutionNotifier
from aragora.autonomous.loop_enhancement import ApprovalStatus
from aragora.server.handlers.autonomous.approvals import get_approval_flow
from aragora.rbac.checker import get_permission_checker

from ..base import HandlerResult, error_response, handle_errors, json_response, require_storage
from ..openapi_decorator import api_endpoint

if TYPE_CHECKING:
    from aragora.billing.auth.context import UserAuthContext


logger = logging.getLogger(__name__)

_receipt_store_get: Callable[[], Any] | None = None
try:
    from aragora.storage.receipt_store import (
        get_receipt_store as _imported_receipt_store_get,
    )
except (ImportError, AttributeError):
    pass
else:
    _receipt_store_get = _imported_receipt_store_get


def get_receipt_store() -> Any:
    """Compatibility shim for test patching."""
    if _receipt_store_get is None:
        raise RuntimeError("Receipt store unavailable")
    return _receipt_store_get()


def _persist_receipt(receipt: Any, debate_id: str) -> str | None:
    """Persist a DecisionReceipt to the receipt store for later retrieval.

    Returns the receipt_id on success, None on failure.
    """
    try:
        from aragora.storage.receipt_store import get_receipt_store

        store = get_receipt_store()
        receipt_dict = receipt.to_dict()
        receipt_dict.setdefault("debate_id", debate_id)
        return store.save(receipt_dict)
    except (ImportError, KeyError, ValueError, OSError, AttributeError, TypeError) as exc:
        logger.debug("Receipt persistence failed: %s", exc)
        return None


def _persist_plan(plan: Any, debate_id: str) -> None:
    """Store an ImplementPlan in the pipeline plan store for tracking."""
    try:
        from aragora.pipeline.executor import store_plan
        from aragora.pipeline.decision_plan import DecisionPlanFactory

        # Wrap ImplementPlan as a DecisionPlan for the store
        decision_plan = DecisionPlanFactory.from_implement_plan(plan, debate_id=debate_id)
    except (ImportError, KeyError, ValueError, OSError, AttributeError, TypeError) as exc:
        logger.debug("Plan persistence setup failed: %s", exc)
        return

    try:
        ensure_decision_plan_backbone_run(
            decision_plan,
            auth_context=None,
            source_surface="debates_decision_integrity_plan_only",
            source_id=debate_id,
        )
    except (ImportError, KeyError, ValueError, OSError, AttributeError, TypeError) as exc:
        logger.debug("Plan backbone seeding failed: %s", exc)

    try:
        store_plan(decision_plan)
    except (ImportError, KeyError, ValueError, OSError, AttributeError, TypeError) as exc:
        logger.debug("Plan persistence failed: %s", exc)
        return

    try:
        sync_decision_plan_backbone_receipt(decision_plan, append_event=False)
    except (ImportError, KeyError, ValueError, OSError, AttributeError, TypeError) as exc:
        logger.debug("Plan backbone receipt sync failed: %s", exc)


def _check_execution_budget(debate_id: str, ctx: dict[str, Any]) -> tuple[bool, str]:
    """Check budget before executing an implementation plan.

    Returns (allowed, message).
    """
    try:
        cost_tracker = ctx.get("cost_tracker")
        if cost_tracker is None:
            return True, ""  # No tracker configured

        result = cost_tracker.check_debate_budget(debate_id, estimated_cost_usd=Decimal("0.10"))
        if not result.get("allowed", True):
            return False, result.get("message", "Budget exceeded")
        return True, ""
    except (KeyError, ValueError, AttributeError, TypeError, OSError) as exc:
        logger.debug("Budget check failed (allowing): %s", exc)
        return True, ""


def _serialize_approval(approval_request: Any) -> dict[str, Any]:
    """Serialize an ApprovalRequest to a JSON-safe dict."""
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


# ---------------------------------------------------------------------------
# Parsed request config
# ---------------------------------------------------------------------------


@dataclass
class _RequestConfig:
    """Parsed and normalised payload fields for _create_decision_integrity."""

    include_receipt: bool
    include_plan: bool
    include_context: bool
    plan_strategy: str
    execution_mode: str
    execution_engine: str
    effective_engine: str
    parallel_execution: bool
    notify_origin: bool
    risk_level: str
    approval_timeout: Any
    approval_mode: str
    max_auto_risk: str
    budget_limit_usd: Any
    openclaw_actions: Any
    computer_use_actions: Any
    openclaw_session: Any
    implementation_profile: dict[str, Any] | None
    implementers: Any
    critic: Any
    reviser: Any
    strategy: Any
    max_revisions: Any
    fabric_models: Any
    fabric_pool_id: Any
    fabric_min_agents: Any
    fabric_max_agents: Any
    fabric_timeout_seconds: Any
    max_parallel: Any
    complexity_router: Any
    task_type_router: Any
    capability_router: Any
    channel_targets: Any
    thread_id: Any
    thread_id_by_platform: Any
    workflow_mode: bool
    execute_workflow: bool
    repo_path: Path | None


def _parse_request(payload: dict[str, Any], ctx: dict[str, Any]) -> _RequestConfig:
    """Parse and normalise the JSON body into an ``_RequestConfig``."""
    include_receipt = bool(payload.get("include_receipt", True))
    include_plan = bool(payload.get("include_plan", True))
    include_context = bool(payload.get("include_context", False))
    plan_strategy = str(payload.get("plan_strategy", "single_task"))
    execution_mode = str(payload.get("execution_mode", "plan_only")).lower()
    execution_engine = str(payload.get("execution_engine", "")).lower()
    parallel_execution = bool(payload.get("parallel_execution", False))
    notify_origin = bool(payload.get("notify_origin", False))
    risk_level = str(payload.get("risk_level", "medium"))
    approval_timeout = payload.get("approval_timeout_seconds")
    approval_mode = str(payload.get("approval_mode", "risk_based"))
    max_auto_risk = str(payload.get("max_auto_risk", "low"))
    budget_limit_usd = payload.get("budget_limit_usd")
    openclaw_actions = payload.get("openclaw_actions")
    computer_use_actions = payload.get("computer_use_actions")
    openclaw_session = payload.get("openclaw_session")
    implementation_profile = payload.get("implementation_profile")
    implementers = payload.get("implementers")
    critic = payload.get("critic")
    reviser = payload.get("reviser")
    strategy = payload.get("strategy")
    max_revisions = payload.get("max_revisions")
    fabric_models = payload.get("fabric_models")
    fabric_pool_id = payload.get("fabric_pool_id")
    fabric_min_agents = payload.get("fabric_min_agents")
    fabric_max_agents = payload.get("fabric_max_agents")
    fabric_timeout_seconds = payload.get("fabric_timeout_seconds")
    max_parallel = payload.get("max_parallel")
    complexity_router = payload.get("complexity_router") or payload.get("agent_by_complexity")
    task_type_router = payload.get("task_type_router") or payload.get("agent_by_task_type")
    capability_router = payload.get("capability_router") or payload.get("agent_by_capability")
    channel_targets = payload.get("channel_targets") or payload.get("chat_targets")
    thread_id = payload.get("thread_id") or payload.get("origin_thread_id")
    thread_id_by_platform = payload.get("thread_id_by_platform")

    if execution_mode in {"hybrid", "fabric", "computer_use"}:
        execution_engine = execution_mode
        execution_mode = "execute"

    workflow_mode = execution_mode in {"workflow", "workflow_execute", "execute_workflow"}
    execute_workflow = execution_mode in {"workflow_execute", "execute_workflow"}

    if workflow_mode and not include_plan:
        include_plan = True

    effective_engine = execution_engine or (
        "workflow"
        if workflow_mode
        else ("hybrid" if execution_mode in {"execute", "request_approval"} else "")
    )

    repo_root = ctx.get("repo_root")
    repo_path = Path(repo_root) if repo_root else None

    return _RequestConfig(
        include_receipt=include_receipt,
        include_plan=include_plan,
        include_context=include_context,
        plan_strategy=plan_strategy,
        execution_mode=execution_mode,
        execution_engine=execution_engine,
        effective_engine=effective_engine,
        parallel_execution=parallel_execution,
        notify_origin=notify_origin,
        risk_level=risk_level,
        approval_timeout=approval_timeout,
        approval_mode=approval_mode,
        max_auto_risk=max_auto_risk,
        budget_limit_usd=budget_limit_usd,
        openclaw_actions=openclaw_actions,
        computer_use_actions=computer_use_actions,
        openclaw_session=openclaw_session,
        implementation_profile=implementation_profile
        if isinstance(implementation_profile, dict)
        else None,
        implementers=implementers,
        critic=critic,
        reviser=reviser,
        strategy=strategy,
        max_revisions=max_revisions,
        fabric_models=fabric_models,
        fabric_pool_id=fabric_pool_id,
        fabric_min_agents=fabric_min_agents,
        fabric_max_agents=fabric_max_agents,
        fabric_timeout_seconds=fabric_timeout_seconds,
        max_parallel=max_parallel,
        complexity_router=complexity_router,
        task_type_router=task_type_router,
        capability_router=capability_router,
        channel_targets=channel_targets,
        thread_id=thread_id,
        thread_id_by_platform=thread_id_by_platform,
        workflow_mode=workflow_mode,
        execute_workflow=execute_workflow,
        repo_path=repo_path,
    )


class _DebatesHandlerProtocol(Protocol):
    ctx: dict[str, Any]

    def get_storage(self) -> Any | None: ...

    def read_json_body(
        self, handler: Any, max_size: int | None = None
    ) -> dict[str, Any] | None: ...

    def get_current_user(self, handler: Any) -> UserAuthContext | None: ...

    # Implementation methods (defined in the mixin below, but referenced via self)
    def _build_integrity_package(
        self, debate: Any, debate_id: str, rc: _RequestConfig, handler: Any | None = None
    ) -> tuple[Any, dict[str, Any]]: ...
    def _persist_artifacts(
        self, package: Any, debate_id: str, rc: _RequestConfig, response_payload: dict[str, Any]
    ) -> tuple[str | None, Any]: ...
    def _obsidian_writeback(self, package: Any, receipt_id: str | None) -> None: ...
    def _handle_workflow_mode(
        self,
        handler: Any,
        debate: Any,
        debate_id: str,
        package: Any,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
    ) -> HandlerResult: ...
    def _handle_approval_execution(
        self,
        handler: Any,
        debate_id: str,
        package: Any,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
        computer_use_plan: Any,
    ) -> HandlerResult: ...
    def _route_and_respond(
        self, response_payload: dict[str, Any], debate_id: str, notify_origin: bool
    ) -> HandlerResult: ...
    def _check_approval_permission(self, handler: Any) -> HandlerResult | None: ...
    def _build_changes_list(self, plan: Any) -> list[dict[str, Any]]: ...
    def _check_execution_enabled(self, debate_id: str) -> HandlerResult | None: ...
    def _execute_direct(
        self,
        debate_id: str,
        package: Any,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
        approval_request: Any,
        requested_by: str | None,
        computer_use_plan: Any,
    ) -> HandlerResult | None: ...
    def _execute_computer_use(
        self,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
        approval_request: Any,
        requested_by: str | None,
        computer_use_plan: Any,
    ) -> HandlerResult | None: ...
    def _execute_fabric(
        self, debate_id: str, package: Any, rc: _RequestConfig, response_payload: dict[str, Any]
    ) -> None: ...
    def _execute_hybrid(
        self, debate_id: str, package: Any, rc: _RequestConfig, response_payload: dict[str, Any]
    ) -> None: ...
    def _append_review(
        self, executor: Any, payload: dict[str, Any], review_mode: str | None
    ) -> None: ...


class ImplementationOperationsMixin:
    """Mixin providing Decision Integrity endpoints for debates."""

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/{id}/decision-integrity",
        summary="Build decision integrity package",
        description="Generate a decision receipt and implementation plan from a debate.",
        tags=["Debates"],
        responses={
            "200": {"description": "Decision integrity package returned"},
            "400": {"description": "Invalid request"},
            "404": {"description": "Debate not found"},
        },
    )
    @require_permission("debates:write")
    @require_storage
    @handle_errors("build decision integrity package")
    def _create_decision_integrity(
        self: _DebatesHandlerProtocol, handler: Any, debate_id: str
    ) -> HandlerResult:
        """Generate a decision receipt and implementation plan for a debate."""
        storage = self.get_storage()
        debate = storage.get_debate(debate_id) if storage else None
        if not debate:
            return error_response("Debate not found", 404)

        payload = self.read_json_body(handler) or {}
        rc = _parse_request(payload, self.ctx)

        # Build the decision integrity package
        package, response_payload = self._build_integrity_package(debate, debate_id, rc, handler)

        # Persist receipt and plan
        receipt_id, computer_use_plan = self._persist_artifacts(
            package, debate_id, rc, response_payload
        )

        # Optional Obsidian writeback
        self._obsidian_writeback(package, receipt_id)

        # Dispatch to the appropriate execution path
        if rc.workflow_mode:
            return self._handle_workflow_mode(
                handler, debate, debate_id, package, rc, response_payload
            )

        if rc.execution_mode in {"request_approval", "execute"}:
            return self._handle_approval_execution(
                handler, debate_id, package, rc, response_payload, computer_use_plan
            )

        # Default: return the package payload
        return self._route_and_respond(response_payload, debate_id, rc.notify_origin)

    # -- helpers for _create_decision_integrity ------------------------------

    def _build_integrity_package(
        self: _DebatesHandlerProtocol,
        debate: Any,
        debate_id: str,
        rc: _RequestConfig,
        handler: Any | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        """Build the decision integrity package and initial response payload."""
        continuum_memory = self.ctx.get("continuum_memory") if rc.include_context else None
        cross_debate_memory = self.ctx.get("cross_debate_memory") if rc.include_context else None
        knowledge_mound = self.ctx.get("knowledge_mound") if rc.include_context else None
        document_store = self.ctx.get("document_store") if rc.include_context else None
        evidence_store = self.ctx.get("evidence_store") if rc.include_context else None
        if rc.include_context and evidence_store is None:
            try:
                from aragora.evidence.store import EvidenceStore

                evidence_store = EvidenceStore()
                self.ctx["evidence_store"] = evidence_store
            except (ImportError, AttributeError):
                evidence_store = None

        auth_context = getattr(handler, "_auth_context", None) if handler is not None else None
        context_envelope: dict[str, Any] | None = None
        if auth_context is not None:
            try:
                from aragora.memory.access import build_access_envelope

                context_envelope = build_access_envelope(
                    auth_context,
                    source="debates.decision_integrity",
                )
            except (ImportError, AttributeError):
                context_envelope = None

        package = run_async(
            build_decision_integrity_package(
                debate,
                include_receipt=rc.include_receipt,
                include_plan=rc.include_plan,
                include_context=rc.include_context,
                plan_strategy=rc.plan_strategy,
                repo_path=rc.repo_path,
                continuum_memory=continuum_memory,
                cross_debate_memory=cross_debate_memory,
                knowledge_mound=knowledge_mound,
                document_store=document_store,
                evidence_store=evidence_store,
                auth_context=auth_context,
                context_envelope=context_envelope,
            )
        )

        response_payload = package.to_dict()
        if rc.execution_mode != "plan_only" or rc.execution_engine:
            response_payload["execution_mode"] = rc.execution_mode
            if rc.effective_engine:
                response_payload["execution_engine"] = rc.effective_engine

        return package, response_payload

    @staticmethod
    def _persist_artifacts(
        package: Any,
        debate_id: str,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
    ) -> tuple[str | None, Any]:
        """Persist receipt and plan; return ``(receipt_id, computer_use_plan)``."""
        receipt_id = None
        if package.receipt is not None:
            receipt_id = _persist_receipt(package.receipt, debate_id)
            if receipt_id:
                response_payload["receipt_id"] = receipt_id

        computer_use_plan = None
        if package.plan is not None and not rc.workflow_mode:
            if rc.execution_engine == "computer_use":
                try:
                    from aragora.pipeline.decision_plan import DecisionPlanFactory
                    from aragora.pipeline.executor import store_plan

                    # Derive task from the debate if available
                    computer_use_plan = DecisionPlanFactory.from_implement_plan(
                        package.plan,
                        debate_id=debate_id,
                    )
                    run_id = ensure_decision_plan_backbone_run(
                        computer_use_plan,
                        auth_context=None,
                        source_surface="debates_decision_integrity_computer_use",
                        source_id=debate_id,
                    )
                    store_plan(computer_use_plan)
                    sync_decision_plan_backbone_receipt(computer_use_plan, append_event=False)
                    response_payload["plan_id"] = computer_use_plan.id
                    response_payload["run_id"] = run_id
                except (
                    ImportError,
                    KeyError,
                    ValueError,
                    OSError,
                    AttributeError,
                    TypeError,
                ) as exc:
                    logger.debug("Computer use plan persistence failed: %s", exc)
            else:
                _persist_plan(package.plan, debate_id)

        return receipt_id, computer_use_plan

    @staticmethod
    def _obsidian_writeback(package: Any, receipt_id: str | None) -> None:
        """Write the package to Obsidian if the feature is enabled."""
        if os.environ.get("ARAGORA_OBSIDIAN_WRITEBACK", "0") != "1":
            return
        try:
            from aragora.connectors.knowledge.obsidian import (
                ObsidianConfig,
                ObsidianConnector,
            )

            config = ObsidianConfig.from_env()
            verification_payload = None
            if receipt_id:
                try:
                    from aragora.storage.receipt_store import get_receipt_store

                    store = get_receipt_store()
                    signature_result = store.verify_signature(receipt_id)
                    integrity_result = store.verify_integrity(receipt_id)
                    verification_payload = {
                        "signature": signature_result.to_dict()
                        if hasattr(signature_result, "to_dict")
                        else signature_result,
                        "integrity": integrity_result,
                    }
                except (ImportError, KeyError, ValueError, OSError, AttributeError) as exc:
                    logger.debug("Receipt verification for Obsidian writeback failed: %s", exc)

            if config is None:
                logger.debug("Obsidian writeback enabled but vault is not configured")
            else:
                connector = ObsidianConnector(config)
                folder = os.environ.get("ARAGORA_OBSIDIAN_WRITEBACK_FOLDER", "decisions")
                run_async(
                    connector.write_decision_integrity_package(
                        package,
                        folder=folder,
                        verification=verification_payload,
                    )
                )
        except (ImportError, KeyError, ValueError, OSError, AttributeError, TypeError) as exc:
            logger.debug("Obsidian writeback failed: %s", exc)

    def _handle_workflow_mode(
        self: _DebatesHandlerProtocol,
        handler: Any,
        debate: Any,
        debate_id: str,
        package: Any,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
    ) -> HandlerResult:
        """Handle the workflow-based execution path (DecisionPlan + WorkflowEngine)."""
        from aragora.pipeline.decision_plan import ApprovalMode, DecisionPlanFactory
        from aragora.pipeline.executor import PlanExecutor, store_plan
        from aragora.pipeline.risk_register import RiskLevel

        debate_result = coerce_debate_result(debate)
        user = self.get_current_user(handler)

        try:
            approval_mode_enum = ApprovalMode(rc.approval_mode)
        except ValueError:
            approval_mode_enum = ApprovalMode.RISK_BASED

        try:
            max_auto_risk_enum = RiskLevel(rc.max_auto_risk)
        except ValueError:
            max_auto_risk_enum = RiskLevel.LOW

        budget_limit = None
        if rc.budget_limit_usd is not None:
            try:
                budget_limit = float(rc.budget_limit_usd)
            except (TypeError, ValueError):
                budget_limit = None

        metadata: dict[str, Any] = {
            "source": "decision_integrity",
            "debate_id": debate_id,
            "source_surface": "debates_decision_integrity_workflow",
            "source_id": debate_id,
        }
        if isinstance(rc.openclaw_actions, list):
            metadata["openclaw_actions"] = rc.openclaw_actions
        if isinstance(rc.computer_use_actions, list):
            metadata["computer_use_actions"] = rc.computer_use_actions
        if isinstance(rc.openclaw_session, dict):
            metadata["openclaw_session"] = rc.openclaw_session

        implementation_profile = None
        if isinstance(rc.implementation_profile, dict):
            implementation_profile = dict(rc.implementation_profile)
        else:
            implementation_profile = {}

        if rc.fabric_models is not None and "fabric_models" not in implementation_profile:
            implementation_profile["fabric_models"] = rc.fabric_models
        if rc.channel_targets is not None and "channel_targets" not in implementation_profile:
            implementation_profile["channel_targets"] = rc.channel_targets
        if rc.thread_id is not None and "thread_id" not in implementation_profile:
            implementation_profile["thread_id"] = rc.thread_id
        if (
            rc.thread_id_by_platform is not None
            and "thread_id_by_platform" not in implementation_profile
        ):
            implementation_profile["thread_id_by_platform"] = rc.thread_id_by_platform

        if implementation_profile:
            metadata.setdefault("implementation_profile", implementation_profile)
        else:
            implementation_profile = None

        plan = DecisionPlanFactory.from_debate_result(
            debate_result,
            budget_limit_usd=budget_limit,
            approval_mode=approval_mode_enum,
            max_auto_risk=max_auto_risk_enum,
            repo_path=rc.repo_path,
            metadata=metadata,
            implement_plan=package.plan,
            implementation_profile=implementation_profile,
        )
        run_id = ensure_decision_plan_backbone_run(
            plan,
            auth_context=user,
            source_surface="debates_decision_integrity_workflow",
            source_id=debate_id,
        )
        store_plan(plan)
        ensure_backbone_persisted(
            sync_decision_plan_backbone_receipt(plan, append_event=False),
            f"Failed to sync decision-plan receipt for run {run_id}",
        )

        response_payload["decision_plan"] = plan.to_dict()
        response_payload["plan_id"] = plan.id
        response_payload["run_id"] = run_id

        # Approval flow
        approval_request = None
        if plan.requires_human_approval:
            perm_err = self._check_approval_permission(handler)
            if perm_err is not None:
                return perm_err

            requested_by = getattr(user, "user_id", None) if user else "system"
            changes = self._build_changes_list(plan.implement_plan)

            risk_level_for_approval = rc.risk_level
            try:
                risk_level_for_approval = plan.highest_risk_level.value
            except (AttributeError, ValueError, TypeError) as e:
                logger.debug("Could not extract risk level from plan: %s", e)

            approval_flow = get_approval_flow()
            approval_request = run_async(
                approval_flow.request_approval(
                    title=f"Implement debate {debate_id}",
                    description=(
                        "Execute decision plan generated from debate (workflow-based execution)."
                    ),
                    changes=changes,
                    risk_level=risk_level_for_approval,
                    requested_by=requested_by or "system",
                    timeout_seconds=rc.approval_timeout,
                    metadata={"debate_id": debate_id, "plan_id": plan.id},
                )
            )
            response_payload["approval"] = _serialize_approval(approval_request)

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
                store_plan(plan)
                ensure_backbone_persisted(
                    sync_decision_plan_backbone_receipt(plan, append_event=True),
                    f"Failed to sync approved-plan receipt for run {run_id}",
                )

        # Execute workflow if requested
        if rc.execute_workflow:
            exec_err = self._check_execution_enabled(debate_id)
            if exec_err is not None:
                return exec_err

            if plan.is_approved:
                plan_executor = PlanExecutor(
                    continuum_memory=self.ctx.get("continuum_memory"),
                    knowledge_mound=self.ctx.get("knowledge_mound"),
                    parallel_execution=rc.parallel_execution,
                )
                try:
                    launch, outcome = run_async(
                        execute_decision_plan_with_backbone(
                            plan,
                            executor=plan_executor,
                            auth_context=user,
                            execution_mode="workflow",
                            safety_mode=SafetyMode.INTERACTIVE,
                        )
                    )
                except BackbonePersistenceError as exc:
                    logger.warning(
                        "Workflow execution blocked for debate %s: %s",
                        debate_id,
                        exc,
                    )
                    return error_response(FAIL_CLOSED_BACKBONE_MESSAGE, 503)
                response_payload["workflow_execution"] = {
                    "status": "completed" if outcome.success else "failed",
                    "run_id": launch.get("run_id"),
                    "execution_id": launch.get("execution_id"),
                    "correlation_id": launch.get("correlation_id"),
                    "outcome": outcome.to_dict(),
                }
            else:
                response_payload["workflow_execution"] = {
                    "status": "pending_approval",
                    "approval_id": approval_request.id if approval_request else None,
                    "run_id": run_id,
                }

        return self._route_and_respond(response_payload, debate_id, rc.notify_origin)

    def _handle_approval_execution(
        self: _DebatesHandlerProtocol,
        handler: Any,
        debate_id: str,
        package: Any,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
        computer_use_plan: Any,
    ) -> HandlerResult:
        """Handle request_approval / execute modes (non-workflow path)."""
        # Permission check
        user = self.get_current_user(handler)
        if user:
            try:
                checker = get_permission_checker()
                decision = checker.check_permission(user, "autonomous:approve")  # type: ignore[arg-type]
                if not decision.allowed:
                    logger.warning("Permission denied: autonomous:approve")
                    return error_response("Permission denied", 403)
            except (ImportError, AttributeError):
                pass  # Legacy compatibility: permission checker may not be available

        changes = self._build_changes_list(package.plan)
        requested_by = getattr(user, "user_id", None) if user else "system"
        approval_flow = get_approval_flow()
        approval_request = run_async(
            approval_flow.request_approval(
                title=f"Implement debate {debate_id}",
                description="Execute decision implementation plan generated from debate.",
                changes=changes,
                risk_level=rc.risk_level,
                requested_by=requested_by or "system",
                timeout_seconds=rc.approval_timeout,
                metadata={"debate_id": debate_id},
            )
        )
        response_payload["approval"] = _serialize_approval(approval_request)

        if rc.execution_mode == "execute":
            exec_result = self._execute_direct(
                debate_id,
                package,
                rc,
                response_payload,
                approval_request,
                requested_by,
                computer_use_plan,
            )
            if exec_result is not None:
                return exec_result

        return self._route_and_respond(response_payload, debate_id, rc.notify_origin)

    def _execute_direct(
        self: _DebatesHandlerProtocol,
        debate_id: str,
        package: Any,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
        approval_request: Any,
        requested_by: str | None,
        computer_use_plan: Any,
    ) -> HandlerResult | None:
        """Execute plan directly (non-workflow). Returns error response or None on success."""
        exec_err = self._check_execution_enabled(debate_id)
        if exec_err is not None:
            return exec_err

        engine = rc.execution_engine or "hybrid"
        if engine not in {"hybrid", "fabric", "computer_use"}:
            engine = "hybrid"

        if approval_request.status not in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.AUTO_APPROVED,
        }:
            response_payload["execution"] = {
                "status": "pending_approval",
                "approval_id": approval_request.id,
                "run_id": response_payload.get("run_id"),
            }
            return None

        if package.plan is None:
            return error_response("No implementation plan available", 400)

        if engine == "computer_use":
            return self._execute_computer_use(
                rc, response_payload, approval_request, requested_by, computer_use_plan
            )
        elif engine == "fabric":
            self._execute_fabric(debate_id, package, rc, response_payload)
        else:
            self._execute_hybrid(debate_id, package, rc, response_payload)

        return None

    def _execute_computer_use(
        self: _DebatesHandlerProtocol,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
        approval_request: Any,
        requested_by: str | None,
        computer_use_plan: Any,
    ) -> HandlerResult | None:
        """Execute via computer-use engine."""
        try:
            from aragora.pipeline.executor import PlanExecutor, store_plan

            if computer_use_plan is None:
                response_payload["execution"] = {
                    "status": "failed",
                    "mode": "computer_use",
                    "error": "No execution plan available for computer use",
                }
                return None
            computer_use_plan.approve(
                approver_id=approval_request.approved_by or requested_by or "system",
                reason="Approved",
            )
            plan_metadata = dict(getattr(computer_use_plan, "metadata", {}) or {})
            plan_metadata["admin_approved"] = True
            plan_metadata["approved_by"] = approval_request.approved_by or requested_by or "system"
            plan_metadata["requested_by"] = requested_by or "system"
            plan_metadata["approval_request_id"] = getattr(approval_request, "id", "")
            receipt_id = str(response_payload.get("receipt_id") or "").strip()
            if receipt_id:
                plan_metadata["decision_receipt_id"] = receipt_id
            plan_metadata.setdefault("execution_target_resource", f"plan:{computer_use_plan.id}")
            computer_use_plan.metadata = plan_metadata
            store_plan(computer_use_plan)
            ensure_backbone_persisted(
                sync_decision_plan_backbone_receipt(computer_use_plan, append_event=True),
                f"Failed to sync computer-use plan receipt for plan {computer_use_plan.id}",
            )
            plan_executor = PlanExecutor(
                continuum_memory=self.ctx.get("continuum_memory"),
                knowledge_mound=self.ctx.get("knowledge_mound"),
                parallel_execution=rc.parallel_execution,
                execution_mode="computer_use",
                repo_path=rc.repo_path or Path.cwd(),
                sandbox_config=self.ctx.get("sandbox_config"),
            )
            launch, outcome = run_async(
                execute_decision_plan_with_backbone(
                    computer_use_plan,
                    executor=plan_executor,
                    auth_context=getattr(self, "_auth_context", None),
                    execution_mode="computer_use",
                    safety_mode=SafetyMode.INTERACTIVE,
                )
            )
            response_payload["execution"] = {
                "status": "completed" if outcome.success else "failed",
                "mode": "computer_use",
                "run_id": launch.get("run_id"),
                "execution_id": launch.get("execution_id"),
                "correlation_id": launch.get("correlation_id"),
                "outcome": outcome.to_dict(),
                "progress": {
                    "total_steps": outcome.tasks_total,
                    "completed_steps": outcome.tasks_completed,
                    "duration_seconds": outcome.duration_seconds,
                },
            }
        except BackbonePersistenceError as exc:
            logger.warning("Computer-use execution blocked: %s", exc)
            return error_response(FAIL_CLOSED_BACKBONE_MESSAGE, 503)
        except (
            ImportError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            RuntimeError,
        ) as exc:
            response_payload["execution"] = {
                "status": "failed",
                "mode": "computer_use",
                "error": str(exc),
            }
        return None

    def _execute_hybrid(
        self: _DebatesHandlerProtocol,
        debate_id: str,
        package: Any,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
    ) -> None:
        """Execute via hybrid engine with optional code review."""
        hybrid_executor = HybridExecutor(repo_path=rc.repo_path or Path.cwd())
        notifier = ExecutionNotifier(
            debate_id=debate_id,
            notify_channel=rc.notify_origin,
            notify_websocket=rc.notify_origin,
        )
        notifier.set_task_descriptions(package.plan.tasks)
        if rc.parallel_execution:
            results = run_async(
                hybrid_executor.execute_plan_parallel(
                    package.plan.tasks,
                    set(),
                    on_task_complete=notifier.on_task_complete,
                )
            )
        else:
            results = run_async(
                hybrid_executor.execute_plan(
                    package.plan.tasks,
                    set(),
                    on_task_complete=notifier.on_task_complete,
                )
            )
        if rc.notify_origin:
            run_async(notifier.send_completion_summary())

        execution_payload: dict[str, Any] = {
            "status": "completed",
            "results": [r.to_dict() for r in results],
            "progress": notifier.progress.to_dict(),
        }

        review_mode = os.environ.get("ARAGORA_IMPLEMENTATION_REVIEW_MODE", "off").lower()
        if review_mode != "off":
            self._append_review(hybrid_executor, execution_payload, review_mode)

        response_payload["execution"] = execution_payload

    def _execute_fabric(
        self: _DebatesHandlerProtocol,
        debate_id: str,
        package: Any,
        rc: _RequestConfig,
        response_payload: dict[str, Any],
    ) -> None:
        """Execute via fabric engine with multi-agent orchestration."""
        from aragora.fabric import AgentFabric
        from aragora.implement.fabric_integration import (
            FabricImplementationConfig,
            FabricImplementationRunner,
        )

        notifier = ExecutionNotifier(
            debate_id=debate_id,
            notify_channel=rc.notify_origin,
            notify_websocket=rc.notify_origin,
        )
        notifier.set_task_descriptions(package.plan.tasks)

        async def _run() -> list[Any]:
            profile = None
            if isinstance(rc.implementation_profile, dict):
                try:
                    from aragora.pipeline.decision_plan import ImplementationProfile

                    profile = ImplementationProfile.from_dict(rc.implementation_profile)
                except (ImportError, ValueError, KeyError):
                    profile = None

            async with AgentFabric() as fabric:
                runner = FabricImplementationRunner(
                    fabric,
                    repo_path=rc.repo_path or Path.cwd(),
                    implementation_profile=profile,
                )
                models = ["claude"]
                if profile and profile.fabric_models:
                    models = list(profile.fabric_models)
                elif profile and profile.implementers:
                    models = list(profile.implementers)
                return await runner.run_plan(
                    package.plan.tasks,
                    config=FabricImplementationConfig(
                        models=models,
                        min_agents=profile.fabric_min_agents
                        if profile and profile.fabric_min_agents
                        else 1,
                        max_agents=profile.fabric_max_agents if profile else None,
                    ),
                    on_task_complete=notifier.on_task_complete,
                )

        try:
            results = run_async(_run())
            if rc.notify_origin:
                run_async(notifier.send_completion_summary())
            response_payload["execution"] = {
                "status": "completed",
                "mode": "fabric",
                "results": [r.to_dict() for r in results],
                "progress": notifier.progress.to_dict(),
            }
        except (
            ImportError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            RuntimeError,
        ) as exc:
            response_payload["execution"] = {
                "status": "failed",
                "mode": "fabric",
                "error": str(exc),
            }

    @staticmethod
    def _append_review(
        hybrid_executor: Any,
        execution_payload: dict[str, Any],
        review_mode: str,
    ) -> None:
        """Append code-review results to the execution payload."""
        max_chars = int(os.environ.get("ARAGORA_IMPLEMENTATION_REVIEW_MAX_CHARS", "12000"))
        timeout_seconds = int(os.environ.get("ARAGORA_IMPLEMENTATION_REVIEW_TIMEOUT", "2400"))
        try:
            diff = hybrid_executor.get_review_diff(max_chars=max_chars)
            review = run_async(hybrid_executor.review_with_codex(diff, timeout=timeout_seconds))
            review_passed = review.get("approved") if isinstance(review, dict) else None
        except (
            ImportError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            RuntimeError,
        ) as exc:
            review = {"approved": None, "error": str(exc)}
            review_passed = None

        execution_payload["review"] = review
        execution_payload["review_passed"] = review_passed
        if review_mode == "strict" and review_passed is not True:
            execution_payload["status"] = "review_failed"

    # -- shared micro-helpers ------------------------------------------------

    def _check_approval_permission(
        self: _DebatesHandlerProtocol, handler: Any
    ) -> HandlerResult | None:
        """Return an error response if the user lacks autonomous:approve, else None."""
        user = self.get_current_user(handler)
        if user:
            try:
                checker = get_permission_checker()
                decision = checker.check_permission(
                    user,  # type: ignore[arg-type]
                    "autonomous:approve",
                )
                if not decision.allowed:
                    logger.warning("Permission denied: autonomous:approve")
                    return error_response("Permission denied", 403)
            except (ImportError, AttributeError, ValueError, TypeError) as e:
                logger.warning("Permission check for autonomous:approve failed: %s", e)
        return None

    def _check_execution_enabled(
        self: _DebatesHandlerProtocol, debate_id: str
    ) -> HandlerResult | None:
        """Return an error response if execution is disabled or budget exceeded."""
        if os.environ.get("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "0") != "1":
            return error_response(
                "Implementation execution disabled. Set ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION=1.",
                403,
            )
        budget_ok, budget_msg = _check_execution_budget(debate_id, self.ctx)
        if not budget_ok:
            return error_response(f"Budget limit: {budget_msg}", 402)
        return None

    @staticmethod
    def _build_changes_list(impl_plan: Any) -> list[dict[str, Any]]:
        """Build a changes list from an ImplementPlan (or None)."""
        changes: list[dict[str, Any]] = []
        if impl_plan is not None:
            for task in impl_plan.tasks:
                changes.append(
                    {
                        "id": task.id,
                        "description": task.description,
                        "files": task.files,
                        "complexity": task.complexity,
                    }
                )
        return changes

    @staticmethod
    def _route_and_respond(
        response_payload: dict[str, Any],
        debate_id: str,
        notify_origin: bool,
    ) -> HandlerResult:
        """Route the result to the originating channel, then return JSON response."""
        if notify_origin:
            try:
                run_async(
                    route_result(
                        debate_id,
                        {
                            "debate_id": debate_id,
                            "event": "decision_integrity",
                            "package": response_payload,
                        },
                    )
                )
            except (ConnectionError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
                logger.debug("Decision integrity routing failed: %s", exc)
        return json_response(response_payload)
