"""
Unified Approval Enforcer for Gateway, Device, and Computer-Use Actions.

Provides a single enforcement path for all sensitive actions that require
human approval, ensuring:
- Consistent policy evaluation via OpenClaw policy engine
- Unified audit trail for all approval decisions
- Bypass prevention with mandatory enforcement checks
- Integration with both device pairing and computer-use workflows

Stage 6 (#177): Security/approval consolidation.

Usage:
    from aragora.security.approval_enforcer import (
        UnifiedApprovalEnforcer,
        ApprovalDecision,
        enforce_action,
    )

    enforcer = UnifiedApprovalEnforcer(policy=my_policy)
    decision = await enforcer.enforce(action_request)
    if decision.approved:
        # proceed with action
        ...
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class EnforcementResult(str, Enum):
    """Outcome of an enforcement decision."""

    ALLOWED = "allowed"
    DENIED = "denied"
    PENDING_APPROVAL = "pending_approval"
    BYPASSED_DETECTED = "bypass_detected"


@dataclass
class EnforcementRequest:
    """Unified request for any action requiring enforcement.

    Normalizes gateway, device, and computer-use action requests into
    a single structure for policy evaluation and audit.
    """

    action_type: str
    actor_id: str
    source: str  # "gateway", "device", "computer_use"
    resource: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    workspace_id: str = "default"
    tenant_id: str | None = None
    roles: list[str] = field(default_factory=list)
    approval_id: str | None = None  # Pre-existing approval token


@dataclass
class EnforcementDecision:
    """Result of an enforcement evaluation."""

    id: str
    result: EnforcementResult
    reason: str
    request: EnforcementRequest
    matched_rule: str | None = None
    approval_request_id: str | None = None
    evaluation_time_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.result == EnforcementResult.ALLOWED

    @property
    def denied(self) -> bool:
        return self.result in (
            EnforcementResult.DENIED,
            EnforcementResult.BYPASSED_DETECTED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "result": self.result.value,
            "reason": self.reason,
            "source": self.request.source,
            "action_type": self.request.action_type,
            "actor_id": self.request.actor_id,
            "matched_rule": self.matched_rule,
            "approval_request_id": self.approval_request_id,
            "evaluation_time_ms": self.evaluation_time_ms,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class PolicyEvaluation:
    """Layer-neutral result returned by a registered policy adapter."""

    result: EnforcementResult
    reason: str
    matched_rule: str | None = None


@dataclass(frozen=True)
class ApprovalRoute:
    """Layer-neutral approval request metadata."""

    approval_request_id: str
    category: str
    priority: str


class PolicyEvaluationAdapter(Protocol):
    """Adapter contract for evaluating higher-layer policy objects."""

    def evaluate(self, policy: Any, request: EnforcementRequest) -> PolicyEvaluation:
        """Evaluate a policy request."""
        ...

    def requires_approval(self, policy: Any, request: EnforcementRequest) -> bool:
        """Return whether the policy requires approval."""
        ...


class ApprovalWorkflowAdapter(Protocol):
    """Adapter contract for higher-layer approval workflow objects."""

    async def request_approval(
        self,
        workflow: Any,
        request: EnforcementRequest,
        reason: str,
    ) -> ApprovalRoute:
        """Create an approval request."""
        ...

    async def wait_for_approval(
        self,
        workflow: Any,
        approval_request_id: str,
        timeout: float | None,
    ) -> bool:
        """Wait for and normalize an approval decision."""
        ...

    async def is_approval_valid(self, workflow: Any, approval_id: str) -> bool:
        """Check whether an approval exists, is approved, and is unexpired."""
        ...


@dataclass(frozen=True)
class PolicyActionRequest:
    """Layer-neutral policy request compatible with action policy engines."""

    action_type: _PolicyActionType
    user_id: str
    session_id: str
    workspace_id: str
    path: str | None
    command: str | None
    url: str | None
    roles: list[str]
    tenant_id: str | None


class _PolicyActionType(str, Enum):
    """Enum-compatible action types expected by policy implementations."""

    SHELL = "shell"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    BROWSER = "browser"
    API = "api"
    SCREENSHOT = "screenshot"
    KEYBOARD = "keyboard"
    MOUSE = "mouse"


class _StructuralPolicyEvaluationAdapter:
    """Evaluate policy objects through their existing structural interface."""

    @staticmethod
    def _request(request: EnforcementRequest) -> PolicyActionRequest | None:
        action_type_map = {
            "shell": _PolicyActionType.SHELL,
            "file_read": _PolicyActionType.FILE_READ,
            "file_write": _PolicyActionType.FILE_WRITE,
            "file_delete": _PolicyActionType.FILE_DELETE,
            "browser": _PolicyActionType.BROWSER,
            "api": _PolicyActionType.API,
            "screenshot": _PolicyActionType.SCREENSHOT,
            "keyboard": _PolicyActionType.KEYBOARD,
            "mouse": _PolicyActionType.MOUSE,
        }
        action_type = action_type_map.get(request.action_type)
        if action_type is None:
            return None
        return PolicyActionRequest(
            action_type=action_type,
            user_id=request.actor_id,
            session_id=request.session_id,
            workspace_id=request.workspace_id,
            path=request.details.get("path"),
            command=request.details.get("command"),
            url=request.details.get("url"),
            roles=request.roles,
            tenant_id=request.tenant_id,
        )

    def evaluate(self, policy: Any, request: EnforcementRequest) -> PolicyEvaluation:
        policy_request = self._request(request)
        if policy_request is None:
            return PolicyEvaluation(
                result=EnforcementResult.ALLOWED,
                reason=f"Unknown action type '{request.action_type}'; not policy-controlled",
            )

        result = policy.evaluate(policy_request)
        decision = getattr(result.decision, "value", result.decision)
        if decision == "allow":
            enforcement_result = EnforcementResult.ALLOWED
        elif decision == "deny":
            enforcement_result = EnforcementResult.DENIED
        else:
            enforcement_result = EnforcementResult.PENDING_APPROVAL
        return PolicyEvaluation(
            result=enforcement_result,
            reason=result.reason,
            matched_rule=result.matched_rule.name if result.matched_rule else None,
        )

    def requires_approval(self, policy: Any, request: EnforcementRequest) -> bool:
        policy_request = self._request(request)
        if policy_request is None:
            return False
        result = policy.evaluate(policy_request)
        return getattr(result.decision, "value", result.decision) == "require_approval"


class _StructuralApprovalWorkflowAdapter:
    """Use approval workflows that expose layer-neutral construction metadata."""

    async def request_approval(
        self,
        workflow: Any,
        request: EnforcementRequest,
        reason: str,
    ) -> ApprovalRoute:
        context_type = workflow.approval_context_type
        category = workflow.approval_category_map.get(
            request.source,
            workflow.approval_category_unknown,
        )
        context = context_type(
            task_id=request.session_id or str(uuid.uuid4()),
            action_type=request.action_type,
            action_details=request.details,
            category=category,
            reason=reason,
            risk_level=request.details.get("risk_level", "medium"),
            user_id=request.actor_id,
            tenant_id=request.tenant_id,
        )
        approval_request = await workflow.request_approval(
            context=context,
            priority=workflow.approval_priority_high,
        )
        return ApprovalRoute(
            approval_request_id=approval_request.id,
            category=category.value,
            priority=workflow.approval_priority_high.value,
        )

    async def wait_for_approval(
        self,
        workflow: Any,
        approval_request_id: str,
        timeout: float | None,
    ) -> bool:
        status = await workflow.wait_for_decision(
            approval_request_id,
            timeout=timeout,
        )
        return status == workflow.approval_status_approved

    async def is_approval_valid(self, workflow: Any, approval_id: str) -> bool:
        request = await workflow.get_request(approval_id)
        if not request:
            return False
        return request.status == workflow.approval_status_approved and not request.is_expired()


_structural_policy_adapter = _StructuralPolicyEvaluationAdapter()
_structural_approval_adapter = _StructuralApprovalWorkflowAdapter()
_policy_evaluation_adapter: PolicyEvaluationAdapter | None = None
_approval_workflow_adapter: ApprovalWorkflowAdapter | None = None


def _resolve_approval_workflow_adapter(workflow: Any) -> ApprovalWorkflowAdapter | None:
    if _approval_workflow_adapter is not None:
        return _approval_workflow_adapter
    required_metadata = (
        "approval_context_type",
        "approval_priority_high",
        "approval_category_map",
        "approval_category_unknown",
        "approval_status_approved",
    )
    if all(hasattr(workflow, name) for name in required_metadata):
        return _structural_approval_adapter
    return None


def register_policy_evaluation_adapter(adapter: PolicyEvaluationAdapter | None) -> None:
    """Register the concrete higher-layer policy adapter."""
    global _policy_evaluation_adapter
    _policy_evaluation_adapter = adapter


def register_approval_workflow_adapter(adapter: ApprovalWorkflowAdapter | None) -> None:
    """Register the concrete higher-layer approval workflow adapter."""
    global _approval_workflow_adapter
    _approval_workflow_adapter = adapter


class UnifiedApprovalEnforcer:
    """Single enforcement path for gateway, device, and computer-use actions.

    Evaluates all sensitive actions against the OpenClaw policy engine and
    routes REQUIRE_APPROVAL decisions to the appropriate approval workflow.
    Emits structured audit events for every decision.
    """

    def __init__(
        self,
        policy: Any | None = None,
        approval_workflow: Any | None = None,
        audit_enabled: bool = True,
    ) -> None:
        self._policy = policy
        self._approval_workflow = approval_workflow
        self._audit_enabled = audit_enabled
        self._decision_log: list[EnforcementDecision] = []
        self._max_log_size = 10_000

    async def enforce(self, request: EnforcementRequest) -> EnforcementDecision:
        """Evaluate an action request and return an enforcement decision.

        This is the single entry point for all sensitive actions. It:
        1. Checks for pre-existing approval tokens
        2. Evaluates the action against the OpenClaw policy
        3. Routes REQUIRE_APPROVAL to the approval workflow
        4. Emits audit events for the decision
        5. Returns the enforcement decision

        Args:
            request: Unified enforcement request

        Returns:
            EnforcementDecision with the outcome
        """
        start = time.time()
        decision_id = str(uuid.uuid4())

        # Step 1: Check pre-existing approval token
        if request.approval_id:
            decision = await self._verify_approval_token(decision_id, request, start)
            if decision:
                await self._record_decision(decision)
                return decision

        # Step 2: Evaluate against policy
        decision = await self._evaluate_policy(decision_id, request, start)

        # Step 3: If policy requires approval, route to workflow
        if decision.result == EnforcementResult.PENDING_APPROVAL:
            decision = await self._route_to_approval(decision, request)

        # Step 4: Emit audit event
        await self._record_decision(decision)

        return decision

    async def wait_for_approval(
        self,
        approval_request_id: str,
        timeout: float | None = None,
    ) -> bool:
        """Wait for an approval decision and return True if approved."""
        if not self._approval_workflow:
            return False

        adapter = _resolve_approval_workflow_adapter(self._approval_workflow)
        if adapter is None:
            return False

        try:
            return await adapter.wait_for_approval(
                self._approval_workflow,
                approval_request_id,
                timeout,
            )
        except ImportError:
            return False

    async def verify_not_bypassed(
        self,
        request: EnforcementRequest,
        claimed_approval_id: str | None = None,
    ) -> EnforcementDecision:
        """Verify that an action has not bypassed the approval flow.

        Used as a secondary check to detect bypass attempts where
        code paths might skip the main enforce() call.

        Args:
            request: The action being performed
            claimed_approval_id: Approval ID claimed by the caller

        Returns:
            EnforcementDecision - BYPASSED_DETECTED if no valid approval
        """
        start = time.time()
        decision_id = str(uuid.uuid4())

        # Check if this action requires approval per policy
        requires_approval = await self._action_requires_approval(request)

        if not requires_approval:
            return EnforcementDecision(
                id=decision_id,
                result=EnforcementResult.ALLOWED,
                reason="Action does not require approval per policy",
                request=request,
                evaluation_time_ms=(time.time() - start) * 1000,
            )

        # Verify the claimed approval
        if not claimed_approval_id:
            decision = EnforcementDecision(
                id=decision_id,
                result=EnforcementResult.BYPASSED_DETECTED,
                reason="Sensitive action performed without approval token",
                request=request,
                evaluation_time_ms=(time.time() - start) * 1000,
            )
            await self._record_decision(decision)
            return decision

        # Verify approval is valid
        valid = await self._is_approval_valid(claimed_approval_id)
        if not valid:
            decision = EnforcementDecision(
                id=decision_id,
                result=EnforcementResult.BYPASSED_DETECTED,
                reason=f"Invalid or expired approval token: {claimed_approval_id}",
                request=request,
                approval_request_id=claimed_approval_id,
                evaluation_time_ms=(time.time() - start) * 1000,
            )
            await self._record_decision(decision)
            return decision

        return EnforcementDecision(
            id=decision_id,
            result=EnforcementResult.ALLOWED,
            reason=f"Valid approval: {claimed_approval_id}",
            request=request,
            approval_request_id=claimed_approval_id,
            evaluation_time_ms=(time.time() - start) * 1000,
        )

    def get_recent_decisions(
        self, limit: int = 100, source: str | None = None
    ) -> list[EnforcementDecision]:
        """Get recent enforcement decisions for audit review."""
        decisions = self._decision_log
        if source:
            decisions = [d for d in decisions if d.request.source == source]
        return decisions[-limit:]

    def get_bypass_attempts(self, limit: int = 100) -> list[EnforcementDecision]:
        """Get detected bypass attempts."""
        return [d for d in self._decision_log if d.result == EnforcementResult.BYPASSED_DETECTED][
            -limit:
        ]

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _verify_approval_token(
        self,
        decision_id: str,
        request: EnforcementRequest,
        start: float,
    ) -> EnforcementDecision | None:
        """Verify a pre-existing approval token."""
        valid = await self._is_approval_valid(request.approval_id)
        if valid:
            return EnforcementDecision(
                id=decision_id,
                result=EnforcementResult.ALLOWED,
                reason=f"Pre-approved via {request.approval_id}",
                request=request,
                approval_request_id=request.approval_id,
                evaluation_time_ms=(time.time() - start) * 1000,
            )
        # Invalid token - fall through to policy evaluation
        logger.warning(
            "Invalid approval token %s for %s action by %s",
            request.approval_id,
            request.action_type,
            request.actor_id,
        )
        return None

    async def _evaluate_policy(
        self,
        decision_id: str,
        request: EnforcementRequest,
        start: float,
    ) -> EnforcementDecision:
        """Evaluate request against the OpenClaw policy engine."""
        if request.details.get("force_approval"):
            return EnforcementDecision(
                id=decision_id,
                result=EnforcementResult.PENDING_APPROVAL,
                reason=request.details.get("force_reason", "Approval required by upstream policy"),
                request=request,
                evaluation_time_ms=(time.time() - start) * 1000,
            )
        if not self._policy:
            # No policy configured - allow by default with audit
            return EnforcementDecision(
                id=decision_id,
                result=EnforcementResult.ALLOWED,
                reason="No policy configured; action allowed by default",
                request=request,
                evaluation_time_ms=(time.time() - start) * 1000,
            )

        adapter = _policy_evaluation_adapter or _structural_policy_adapter

        try:
            result = adapter.evaluate(self._policy, request)
            eval_time = (time.time() - start) * 1000

            return EnforcementDecision(
                id=decision_id,
                result=result.result,
                reason=result.reason,
                request=request,
                matched_rule=result.matched_rule,
                evaluation_time_ms=eval_time,
            )

        except ImportError:
            logger.warning("OpenClaw policy module not available")
            return EnforcementDecision(
                id=decision_id,
                result=EnforcementResult.ALLOWED,
                reason="Policy module unavailable; action allowed",
                request=request,
                evaluation_time_ms=(time.time() - start) * 1000,
            )

    async def _route_to_approval(
        self,
        decision: EnforcementDecision,
        request: EnforcementRequest,
    ) -> EnforcementDecision:
        """Route a REQUIRE_APPROVAL decision to the approval workflow."""
        if not self._approval_workflow:
            # No workflow configured - keep as pending
            return decision

        adapter = _resolve_approval_workflow_adapter(self._approval_workflow)
        if adapter is None:
            logger.warning("Approval workflow adapter not available")
            return decision

        try:
            route = await adapter.request_approval(
                self._approval_workflow,
                request,
                decision.reason,
            )

            decision.approval_request_id = route.approval_request_id
            decision.metadata["approval_context"] = {
                "category": route.category,
                "priority": route.priority,
            }

            return decision

        except ImportError:
            logger.warning("Computer-use approval module not available")
            return decision

    async def _action_requires_approval(self, request: EnforcementRequest) -> bool:
        """Check if an action requires approval per policy."""
        if not self._policy:
            return False

        adapter = _policy_evaluation_adapter or _structural_policy_adapter

        try:
            return adapter.requires_approval(self._policy, request)

        except ImportError:
            return False

    async def _is_approval_valid(self, approval_id: str | None) -> bool:
        """Check if an approval token is valid and not expired."""
        if not approval_id:
            return False

        if not self._approval_workflow:
            return False

        adapter = _resolve_approval_workflow_adapter(self._approval_workflow)
        if adapter is None:
            return False

        try:
            return await adapter.is_approval_valid(self._approval_workflow, approval_id)
        except (ImportError, AttributeError):
            return False

    async def _record_decision(self, decision: EnforcementDecision) -> None:
        """Record decision in log and emit audit event."""
        # Append to in-memory log
        self._decision_log.append(decision)
        if len(self._decision_log) > self._max_log_size:
            self._decision_log = self._decision_log[-self._max_log_size :]

        # Emit structured audit event
        if self._audit_enabled:
            await self._emit_audit_event(decision)

    async def _emit_audit_event(self, decision: EnforcementDecision) -> None:
        """Emit a structured audit event for the enforcement decision."""
        try:
            from aragora.observability.security_audit import (
                audit_rbac_decision,
            )

            granted = decision.result == EnforcementResult.ALLOWED

            await audit_rbac_decision(
                user_id=decision.request.actor_id,
                permission=f"enforce:{decision.request.source}:{decision.request.action_type}",
                granted=granted,
                resource_type=decision.request.source,
                resource_id=decision.request.resource or decision.request.action_type,
                workspace_id=decision.request.workspace_id,
                enforcement_id=decision.id,
                result=decision.result.value,
                reason=decision.reason,
                matched_rule=decision.matched_rule,
                approval_request_id=decision.approval_request_id,
            )
        except (ImportError, TypeError, RuntimeError) as e:
            logger.debug("Audit event emission skipped: %s", e)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_enforcer: UnifiedApprovalEnforcer | None = None


def get_approval_enforcer() -> UnifiedApprovalEnforcer:
    """Get or create the default unified approval enforcer."""
    global _default_enforcer
    if _default_enforcer is None:
        _default_enforcer = UnifiedApprovalEnforcer()
    return _default_enforcer


def set_approval_enforcer(enforcer: UnifiedApprovalEnforcer) -> None:
    """Set the default unified approval enforcer."""
    global _default_enforcer
    _default_enforcer = enforcer


async def enforce_action(request: EnforcementRequest) -> EnforcementDecision:
    """Convenience function to enforce an action via the default enforcer."""
    return await get_approval_enforcer().enforce(request)


__all__ = [
    "EnforcementResult",
    "EnforcementRequest",
    "EnforcementDecision",
    "PolicyEvaluation",
    "ApprovalRoute",
    "PolicyEvaluationAdapter",
    "ApprovalWorkflowAdapter",
    "UnifiedApprovalEnforcer",
    "register_policy_evaluation_adapter",
    "register_approval_workflow_adapter",
    "enforce_action",
    "get_approval_enforcer",
    "set_approval_enforcer",
]
