"""Composition adapters for security-owned dependency boundaries."""

from __future__ import annotations

import uuid
from typing import Any

from aragora.security.approval_enforcer import (
    ApprovalRoute,
    EnforcementRequest,
    EnforcementResult,
    PolicyEvaluation,
    register_approval_workflow_adapter,
    register_policy_evaluation_adapter,
)
from aragora.security.approval_mappings import (
    approval_category_for_source,
    convert_policy_action_type,
    unknown_action_type_reason,
)
from aragora.security.migration import register_migration_audit_provider


def _to_policy_request(
    request: EnforcementRequest,
    action_request_type: Any,
    action_types: Any,
) -> Any | None:
    action_type = convert_policy_action_type(request.action_type, action_types)
    if action_type is None:
        return None

    return action_request_type(
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


class OpenClawPolicyEvaluationAdapter:
    """Translate security requests to OpenClaw policy evaluations."""

    def evaluate(self, policy: Any, request: EnforcementRequest) -> PolicyEvaluation:
        from aragora.gateway.openclaw_policy import (
            ActionRequest,
            ActionType,
            PolicyDecision,
        )

        policy_request = _to_policy_request(request, ActionRequest, ActionType)
        if policy_request is None:
            return PolicyEvaluation(
                result=EnforcementResult.ALLOWED,
                reason=unknown_action_type_reason(request.action_type),
            )

        result = policy.evaluate(policy_request)
        if result.decision == PolicyDecision.ALLOW:
            enforcement_result = EnforcementResult.ALLOWED
        elif result.decision == PolicyDecision.DENY:
            enforcement_result = EnforcementResult.DENIED
        else:
            enforcement_result = EnforcementResult.PENDING_APPROVAL

        return PolicyEvaluation(
            result=enforcement_result,
            reason=result.reason,
            matched_rule=result.matched_rule.name if result.matched_rule else None,
        )

    def requires_approval(self, policy: Any, request: EnforcementRequest) -> bool:
        from aragora.gateway.openclaw_policy import (
            ActionRequest,
            ActionType,
            PolicyDecision,
        )

        policy_request = _to_policy_request(request, ActionRequest, ActionType)
        if policy_request is None:
            return False

        result = policy.evaluate(policy_request)
        return result.decision == PolicyDecision.REQUIRE_APPROVAL


class ComputerUseApprovalWorkflowAdapter:
    """Translate security requests to computer-use approval workflows."""

    async def request_approval(
        self,
        workflow: Any,
        request: EnforcementRequest,
        reason: str,
    ) -> ApprovalRoute:
        from aragora.computer_use.approval import (
            ApprovalCategory,
            ApprovalContext,
            ApprovalPriority,
        )

        category = ApprovalCategory(approval_category_for_source(request.source))
        context = ApprovalContext(
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
            priority=ApprovalPriority.HIGH,
        )
        return ApprovalRoute(
            approval_request_id=approval_request.id,
            category=category.value,
            priority="high",
        )

    async def wait_for_approval(
        self,
        workflow: Any,
        approval_request_id: str,
        timeout: float | None,
    ) -> bool:
        try:
            from aragora.computer_use.approval import ApprovalStatus
        except ImportError:
            return False

        status = await workflow.wait_for_decision(
            approval_request_id,
            timeout=timeout,
        )
        return status == ApprovalStatus.APPROVED

    async def is_approval_valid(self, workflow: Any, approval_id: str) -> bool:
        request = await workflow.get_request(approval_id)
        if not request:
            return False

        from aragora.computer_use.approval import ApprovalStatus

        return request.status == ApprovalStatus.APPROVED and not request.is_expired()


def _audit_security(**kwargs: Any) -> Any:
    from aragora.audit.unified import audit_security

    return audit_security(**kwargs)


def register_security_migration_adapters() -> None:
    """Register the audit provider used by security migration."""
    register_migration_audit_provider(_audit_security)


def register_security_approval_adapters() -> None:
    """Register policy and approval adapters used by security enforcement."""
    register_policy_evaluation_adapter(OpenClawPolicyEvaluationAdapter())
    register_approval_workflow_adapter(ComputerUseApprovalWorkflowAdapter())


def register_security_edge_adapters() -> None:
    """Register all higher-layer adapters consumed by security."""
    register_security_migration_adapters()
    register_security_approval_adapters()


__all__ = [
    "ComputerUseApprovalWorkflowAdapter",
    "OpenClawPolicyEvaluationAdapter",
    "register_security_approval_adapters",
    "register_security_edge_adapters",
    "register_security_migration_adapters",
]
