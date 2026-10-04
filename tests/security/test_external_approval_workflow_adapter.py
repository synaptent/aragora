"""Approval workflow adapters for external (non computer-use) workflows.

Each enforcer operation must consult only the workflow capability it needs:
waiting needs ``wait_for_decision``, token validation needs ``get_request`` and
routing needs ``request_approval``. Unadapted or malformed workflows and
adapters must fail closed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import pytest

from aragora.security import approval_enforcer as ae
from aragora.security.approval_enforcer import (
    EnforcementRequest,
    EnforcementResult,
    UnifiedApprovalEnforcer,
    register_approval_workflow_adapter,
    register_policy_evaluation_adapter,
)


class ExternalStatus(str, Enum):
    PENDING = "pending"
    GRANTED = "granted"
    REJECTED = "rejected"


class ExternalPriority(str, Enum):
    URGENT = "urgent"


class ExternalCategory(str, Enum):
    GATEWAY = "gateway-change"
    OTHER = "other"


@dataclass
class ExternalContext:
    task_id: str
    action_type: str
    action_details: dict[str, Any]
    category: ExternalCategory
    reason: str
    risk_level: str
    user_id: str
    tenant_id: str | None


@dataclass
class ExternalRecord:
    id: str
    status: ExternalStatus
    expired: bool = False

    def is_expired(self) -> bool:
        return self.expired


@dataclass
class ExternalWorkflow:
    """External workflow with its own vocabulary and none of the in-repo metadata."""

    decision: ExternalStatus = ExternalStatus.GRANTED
    records: dict[str, ExternalRecord] = field(default_factory=dict)
    submitted: list[tuple[ExternalContext, ExternalPriority]] = field(default_factory=list)

    async def request_approval(
        self, context: ExternalContext, priority: ExternalPriority
    ) -> ExternalRecord:
        self.submitted.append((context, priority))
        record = ExternalRecord(id=f"ext-{len(self.submitted)}", status=ExternalStatus.PENDING)
        self.records[record.id] = record
        return record

    async def wait_for_decision(self, request_id: str, timeout: float | None = None) -> Any:
        record = self.records.get(request_id)
        if record is not None:
            record.status = self.decision
        return self.decision

    async def get_request(self, request_id: str) -> ExternalRecord | None:
        return self.records.get(request_id)


class MinimalWaitWorkflow:
    """Only decision waiting plus the approved-status marker."""

    approval_status_approved = ExternalStatus.GRANTED

    def __init__(self, decision: ExternalStatus) -> None:
        self.decision = decision
        self.waited: list[tuple[str, float | None]] = []

    async def wait_for_decision(self, request_id: str, timeout: float | None = None) -> Any:
        self.waited.append((request_id, timeout))
        return self.decision


class MinimalLookupWorkflow:
    """Only request lookup plus the approved-status marker."""

    approval_status_approved = ExternalStatus.GRANTED

    def __init__(self, *records: ExternalRecord) -> None:
        self.records = {record.id: record for record in records}

    async def get_request(self, request_id: str) -> ExternalRecord | None:
        return self.records.get(request_id)


class ApproveEverythingAdapter:
    """A global adapter that would approve any workflow if it were consulted."""

    async def request_approval(self, workflow: Any, request: Any, reason: str) -> ae.ApprovalRoute:
        return ae.ApprovalRoute(approval_request_id="global", category="global", priority="global")

    async def wait_for_approval(
        self, workflow: Any, approval_request_id: str, timeout: Any
    ) -> bool:
        return True

    async def is_approval_valid(self, workflow: Any, approval_id: str) -> bool:
        return True


@pytest.fixture(autouse=True)
def isolated_adapter_registry():
    register_policy_evaluation_adapter(None)
    register_approval_workflow_adapter(None)
    yield
    register_policy_evaluation_adapter(None)
    register_approval_workflow_adapter(None)


def _forced_request(**overrides: Any) -> EnforcementRequest:
    values: dict[str, Any] = {
        "action_type": "shell",
        "actor_id": "user-1",
        "source": "gateway",
        "session_id": "session-1",
        "details": {"force_approval": True, "force_reason": "needs a human"},
    }
    values.update(overrides)
    return EnforcementRequest(**values)


def _external_adapter() -> Any:
    return ae.ExternalApprovalWorkflowAdapter(
        approved_status=ExternalStatus.GRANTED,
        context_factory=ExternalContext,
        priority=ExternalPriority.URGENT,
        category_map={"gateway": ExternalCategory.GATEWAY},
        unknown_category=ExternalCategory.OTHER,
    )


class TestMinimalCapabilityWorkflows:
    async def test_wait_needs_only_wait_for_decision(self):
        workflow = MinimalWaitWorkflow(ExternalStatus.GRANTED)
        enforcer = UnifiedApprovalEnforcer(approval_workflow=workflow)

        assert await enforcer.wait_for_approval("req-1", timeout=5.0) is True
        assert workflow.waited == [("req-1", 5.0)]

    @pytest.mark.parametrize("decision", [ExternalStatus.REJECTED, ExternalStatus.PENDING])
    async def test_wait_reports_denied_and_pending_as_not_approved(self, decision):
        enforcer = UnifiedApprovalEnforcer(approval_workflow=MinimalWaitWorkflow(decision))

        assert await enforcer.wait_for_approval("req-1") is False

    async def test_lookup_needs_only_get_request(self):
        workflow = MinimalLookupWorkflow(ExternalRecord("tok-1", ExternalStatus.GRANTED))
        enforcer = UnifiedApprovalEnforcer(approval_workflow=workflow)

        decision = await enforcer.enforce(_forced_request(approval_id="tok-1"))

        assert decision.result == EnforcementResult.ALLOWED
        assert decision.reason == "Pre-approved via tok-1"

    @pytest.mark.parametrize(
        "record",
        [
            ExternalRecord("tok-1", ExternalStatus.GRANTED, expired=True),
            ExternalRecord("tok-1", ExternalStatus.REJECTED),
            ExternalRecord("tok-1", ExternalStatus.PENDING),
        ],
        ids=["expired", "denied", "pending"],
    )
    async def test_lookup_rejects_expired_denied_and_pending_tokens(self, record):
        enforcer = UnifiedApprovalEnforcer(approval_workflow=MinimalLookupWorkflow(record))

        decision = await enforcer.enforce(_forced_request(approval_id="tok-1"))

        assert decision.result == EnforcementResult.PENDING_APPROVAL
        assert decision.approval_request_id is None

    async def test_minimal_workflows_cannot_route_new_requests(self):
        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=MinimalWaitWorkflow(ExternalStatus.GRANTED)
        )

        decision = await enforcer.enforce(_forced_request())

        assert decision.result == EnforcementResult.PENDING_APPROVAL
        assert decision.approval_request_id is None


class TestExplicitExternalAdapter:
    async def test_full_routing_wait_and_token_lookup(self):
        workflow = ExternalWorkflow(decision=ExternalStatus.GRANTED)
        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=workflow, approval_workflow_adapter=_external_adapter()
        )

        routed = await enforcer.enforce(_forced_request())

        assert routed.result == EnforcementResult.PENDING_APPROVAL
        assert routed.approval_request_id == "ext-1"
        assert routed.metadata["approval_context"] == {
            "category": "gateway-change",
            "priority": "urgent",
        }
        context, priority = workflow.submitted[0]
        assert context.category is ExternalCategory.GATEWAY
        assert context.reason == "needs a human"
        assert context.task_id == "session-1"
        assert priority is ExternalPriority.URGENT

        assert await enforcer.wait_for_approval("ext-1") is True
        allowed = await enforcer.enforce(_forced_request(approval_id="ext-1"))
        assert allowed.result == EnforcementResult.ALLOWED

    async def test_unknown_source_uses_unknown_category(self):
        workflow = ExternalWorkflow()
        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=workflow, approval_workflow_adapter=_external_adapter()
        )

        routed = await enforcer.enforce(_forced_request(source="device"))

        assert routed.metadata["approval_context"]["category"] == "other"

    async def test_denied_decision_is_not_approved(self):
        workflow = ExternalWorkflow(decision=ExternalStatus.REJECTED)
        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=workflow, approval_workflow_adapter=_external_adapter()
        )
        routed = await enforcer.enforce(_forced_request())

        assert await enforcer.wait_for_approval(routed.approval_request_id) is False
        retried = await enforcer.enforce(_forced_request(approval_id=routed.approval_request_id))
        assert retried.result == EnforcementResult.PENDING_APPROVAL
        assert retried.reason == "needs a human"

    async def test_explicit_adapter_takes_precedence_over_global_adapter(self):
        register_approval_workflow_adapter(ApproveEverythingAdapter())
        workflow = ExternalWorkflow(decision=ExternalStatus.REJECTED)
        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=workflow, approval_workflow_adapter=_external_adapter()
        )

        routed = await enforcer.enforce(_forced_request())

        assert routed.approval_request_id == "ext-1"
        assert await enforcer.wait_for_approval("ext-1") is False

    async def test_missing_routing_vocabulary_fails_closed(self):
        workflow = ExternalWorkflow()
        adapter = ae.ExternalApprovalWorkflowAdapter(approved_status=ExternalStatus.GRANTED)
        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=workflow, approval_workflow_adapter=adapter
        )

        routed = await enforcer.enforce(_forced_request())

        assert routed.result == EnforcementResult.PENDING_APPROVAL
        assert routed.approval_request_id is None
        assert workflow.submitted == []

    async def test_missing_approved_status_fails_closed(self):
        workflow = ExternalWorkflow(decision=ExternalStatus.GRANTED)
        workflow.records["tok-1"] = ExternalRecord("tok-1", ExternalStatus.GRANTED)
        adapter = ae.ExternalApprovalWorkflowAdapter(
            context_factory=ExternalContext,
            priority=ExternalPriority.URGENT,
            unknown_category=ExternalCategory.OTHER,
        )
        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=workflow, approval_workflow_adapter=adapter
        )

        assert await enforcer.wait_for_approval("tok-1") is False
        decision = await enforcer.enforce(_forced_request(approval_id="tok-1"))
        assert decision.reason != "Pre-approved via tok-1"

    async def test_lookup_record_without_expiry_check_fails_closed(self):
        @dataclass
        class NoExpiryRecord:
            id: str
            status: ExternalStatus

        class Workflow:
            async def get_request(self, request_id: str) -> NoExpiryRecord:
                return NoExpiryRecord(request_id, ExternalStatus.GRANTED)

        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=Workflow(), approval_workflow_adapter=_external_adapter()
        )

        decision = await enforcer.enforce(_forced_request(approval_id="tok-1"))

        assert decision.result == EnforcementResult.PENDING_APPROVAL


class TestInRepoWorkflowWithoutRegisteredAdapter:
    async def test_metadata_path_routes_waits_and_validates_tokens(self):
        from aragora.computer_use.approval import ApprovalConfig, ApprovalWorkflow

        workflow = ApprovalWorkflow(
            config=ApprovalConfig(default_timeout_seconds=1.0, min_timeout_seconds=0.1)
        )
        enforcer = UnifiedApprovalEnforcer(approval_workflow=workflow, audit_enabled=False)

        routed = await enforcer.enforce(_forced_request())
        assert routed.approval_request_id is not None
        assert routed.metadata["approval_context"] == {
            "category": "system_modification",
            "priority": "high",
        }

        await workflow.approve(routed.approval_request_id, "admin")
        assert await enforcer.wait_for_approval(routed.approval_request_id, timeout=1.0) is True
        allowed = await enforcer.enforce(_forced_request(approval_id=routed.approval_request_id))
        assert allowed.result == EnforcementResult.ALLOWED

    async def test_metadata_path_rejects_denied_tokens(self):
        from aragora.computer_use.approval import ApprovalConfig, ApprovalWorkflow

        workflow = ApprovalWorkflow(config=ApprovalConfig())
        enforcer = UnifiedApprovalEnforcer(approval_workflow=workflow, audit_enabled=False)
        routed = await enforcer.enforce(_forced_request())

        await workflow.deny(routed.approval_request_id, "admin", "no")

        token = await enforcer.enforce(_forced_request(approval_id=routed.approval_request_id))
        assert token.result == EnforcementResult.PENDING_APPROVAL


class TestFailClosed:
    async def test_unadapted_workflow_fails_closed(self):
        enforcer = UnifiedApprovalEnforcer(approval_workflow=object())

        routed = await enforcer.enforce(_forced_request())
        assert routed.result == EnforcementResult.PENDING_APPROVAL
        assert routed.approval_request_id is None
        assert await enforcer.wait_for_approval("req-1") is False
        token = await enforcer.enforce(_forced_request(approval_id="tok-1"))
        assert token.result == EnforcementResult.PENDING_APPROVAL

    async def test_adapter_without_operations_fails_closed(self):
        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=ExternalWorkflow(), approval_workflow_adapter=object()
        )

        routed = await enforcer.enforce(_forced_request())
        assert routed.approval_request_id is None
        assert await enforcer.wait_for_approval("ext-1") is False
        token = await enforcer.enforce(_forced_request(approval_id="ext-1"))
        assert token.result == EnforcementResult.PENDING_APPROVAL

    async def test_truthy_non_boolean_adapter_results_are_not_approval(self):
        class TruthyAdapter(ApproveEverythingAdapter):
            async def wait_for_approval(self, workflow: Any, request_id: str, timeout: Any) -> Any:
                return "yes"

            async def is_approval_valid(self, workflow: Any, approval_id: str) -> Any:
                return 1

        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=ExternalWorkflow(), approval_workflow_adapter=TruthyAdapter()
        )

        assert await enforcer.wait_for_approval("ext-1") is False
        token = await enforcer.enforce(_forced_request(approval_id="ext-1"))
        assert token.result == EnforcementResult.PENDING_APPROVAL

    async def test_context_factory_with_wrong_signature_fails_closed(self):
        def task_only_context(task_id: str) -> dict[str, str]:
            return {"task_id": task_id}

        workflow = ExternalWorkflow()
        adapter = ae.ExternalApprovalWorkflowAdapter(
            approved_status=ExternalStatus.GRANTED,
            context_factory=task_only_context,
            priority=ExternalPriority.URGENT,
            unknown_category=ExternalCategory.OTHER,
        )
        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=workflow, approval_workflow_adapter=adapter
        )

        routed = await enforcer.enforce(_forced_request())

        assert routed.result == EnforcementResult.PENDING_APPROVAL
        assert routed.approval_request_id is None
        assert workflow.submitted == []

    async def test_workflow_methods_with_wrong_signatures_fail_closed(self):
        class WrongSignatureWorkflow:
            async def request_approval(self, context: ExternalContext) -> ExternalRecord:
                return ExternalRecord("ext-1", ExternalStatus.PENDING)

            async def wait_for_decision(self, request_id: str) -> ExternalStatus:
                return ExternalStatus.GRANTED

            async def get_request(self) -> ExternalRecord:
                return ExternalRecord("tok-1", ExternalStatus.GRANTED)

        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=WrongSignatureWorkflow(),
            approval_workflow_adapter=_external_adapter(),
        )

        routed = await enforcer.enforce(_forced_request())
        assert routed.result == EnforcementResult.PENDING_APPROVAL
        assert routed.approval_request_id is None
        assert await enforcer.wait_for_approval("ext-1") is False
        token = await enforcer.enforce(_forced_request(approval_id="tok-1"))
        assert token.result == EnforcementResult.PENDING_APPROVAL

    async def test_adapter_methods_with_wrong_signatures_fail_closed(self):
        class WrongArityAdapter:
            async def request_approval(self, workflow: Any) -> ae.ApprovalRoute:
                return ae.ApprovalRoute(approval_request_id="x", category="x", priority="x")

            async def wait_for_approval(self, workflow: Any) -> bool:
                return True

            async def is_approval_valid(self, workflow: Any) -> bool:
                return True

        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=ExternalWorkflow(), approval_workflow_adapter=WrongArityAdapter()
        )

        routed = await enforcer.enforce(_forced_request())
        assert routed.result == EnforcementResult.PENDING_APPROVAL
        assert routed.approval_request_id is None
        assert await enforcer.wait_for_approval("ext-1") is False
        token = await enforcer.enforce(_forced_request(approval_id="ext-1"))
        assert token.result == EnforcementResult.PENDING_APPROVAL


def test_approval_enforcer_does_not_import_computer_use():
    source = Path(ae.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not {name for name in imported if name.startswith("aragora.computer_use")}
