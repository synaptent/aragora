"""Parity tests for the security-owned approval mapping contract.

The structural adapters in ``aragora.security.approval_enforcer`` and the
concrete adapters in ``aragora.ops.security_edge_adapters`` must resolve every
policy action type and approval source the same way. These tests enumerate the
higher-layer enums (``ActionType``, ``ApprovalCategory``, ``ApprovalStatus``),
so a member added on either side fails here instead of diverging silently.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.computer_use.approval import (
    ApprovalCategory,
    ApprovalPriority,
    ApprovalStatus,
    ApprovalWorkflow,
)
from aragora.gateway.openclaw_policy import ActionRequest, ActionType, PolicyDecision
from aragora.ops.security_edge_adapters import (
    ComputerUseApprovalWorkflowAdapter,
    OpenClawPolicyEvaluationAdapter,
)
from aragora.security import approval_enforcer
from aragora.security.approval_enforcer import (
    ApprovalRoute,
    EnforcementRequest,
    EnforcementResult,
    PolicyEvaluation,
)
from aragora.security.approval_mappings import (
    APPROVAL_CATEGORY_UNKNOWN,
    APPROVAL_SOURCE_CATEGORIES,
    POLICY_ACTION_TYPES,
    PolicyActionType,
    approval_category_for_source,
    convert_policy_action_type,
    resolve_policy_action_type,
    unknown_action_type_reason,
)

UNKNOWN_ACTION_TYPES = ("", "SHELL", "Shell", "exec", "file-read", "unknown")
UNKNOWN_SOURCES = ("", "api", "Gateway", "unknown")

KNOWN_SOURCE_CATEGORIES = (
    ("gateway", ApprovalCategory.SYSTEM_MODIFICATION),
    ("device", ApprovalCategory.EXTERNAL_SYSTEM),
    ("computer_use", ApprovalCategory.DESTRUCTIVE_ACTION),
)
SOURCE_CATEGORY_CASES = (
    *KNOWN_SOURCE_CATEGORIES,
    *((source, ApprovalCategory.UNKNOWN) for source in UNKNOWN_SOURCES),
)

EXPECTED_ENFORCEMENT_RESULTS = {
    PolicyDecision.ALLOW: EnforcementResult.ALLOWED,
    PolicyDecision.DENY: EnforcementResult.DENIED,
    PolicyDecision.REQUIRE_APPROVAL: EnforcementResult.PENDING_APPROVAL,
}

STRUCTURAL_POLICY_ADAPTER = approval_enforcer._structural_policy_adapter
CONCRETE_POLICY_ADAPTER = OpenClawPolicyEvaluationAdapter()
STRUCTURAL_APPROVAL_ADAPTER = approval_enforcer._structural_approval_adapter
CONCRETE_APPROVAL_ADAPTER = ComputerUseApprovalWorkflowAdapter()
APPROVAL_ADAPTERS = (
    pytest.param(STRUCTURAL_APPROVAL_ADAPTER, id="structural"),
    pytest.param(CONCRETE_APPROVAL_ADAPTER, id="concrete"),
)


def _enforcement_request(action_type: str = "shell", source: str = "gateway") -> EnforcementRequest:
    return EnforcementRequest(
        action_type=action_type,
        actor_id="user-1",
        source=source,
        resource="resource-1",
        details={
            "path": "/workspace/file.txt",
            "command": "ls -la",
            "url": "https://example.test/page",
            "risk_level": "high",
        },
        session_id="session-1",
        workspace_id="workspace-1",
        tenant_id="tenant-1",
        roles=["admin", "operator"],
    )


def _policy_request_fields(policy_request: Any) -> dict[str, Any]:
    return {
        "action_type": policy_request.action_type.value,
        "user_id": policy_request.user_id,
        "session_id": policy_request.session_id,
        "workspace_id": policy_request.workspace_id,
        "path": policy_request.path,
        "command": policy_request.command,
        "url": policy_request.url,
        "roles": policy_request.roles,
        "tenant_id": policy_request.tenant_id,
    }


class _RecordingPolicy:
    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        self.requests: list[Any] = []

    def evaluate(self, request: Any) -> Any:
        self.requests.append(request)
        return SimpleNamespace(
            decision=self.decision,
            reason=f"decided {self.decision.value}",
            matched_rule=SimpleNamespace(name="rule-1"),
        )


class _RecordingWorkflow:
    approval_context_type = ApprovalWorkflow.approval_context_type
    approval_priority_high = ApprovalWorkflow.approval_priority_high
    approval_category_map = ApprovalWorkflow.approval_category_map
    approval_category_unknown = ApprovalWorkflow.approval_category_unknown
    approval_status_approved = ApprovalWorkflow.approval_status_approved

    def __init__(self, stored_request: Any = None, decision: Any = None) -> None:
        self.calls: list[tuple[Any, Any]] = []
        self._stored_request = stored_request
        self._decision = decision

    async def request_approval(self, *, context: Any, priority: Any) -> Any:
        self.calls.append((context, priority))
        return SimpleNamespace(id=f"approval-{len(self.calls)}")

    async def wait_for_decision(self, approval_request_id: str, timeout: float | None) -> Any:
        return self._decision

    async def get_request(self, approval_id: str) -> Any:
        return self._stored_request


# ---------------------------------------------------------------------------
# Canonical contract values
# ---------------------------------------------------------------------------


def test_contract_values_are_unchanged() -> None:
    assert dict(APPROVAL_SOURCE_CATEGORIES) == {
        "gateway": "system_modification",
        "device": "external_system",
        "computer_use": "destructive_action",
    }
    assert APPROVAL_CATEGORY_UNKNOWN == "unknown"
    assert [member.value for member in PolicyActionType] == [
        "shell",
        "file_read",
        "file_write",
        "file_delete",
        "browser",
        "api",
        "screenshot",
        "keyboard",
        "mouse",
    ]
    assert dict(POLICY_ACTION_TYPES) == {member.value: member for member in PolicyActionType}


def test_contract_tables_are_read_only() -> None:
    with pytest.raises(TypeError):
        APPROVAL_SOURCE_CATEGORIES["gateway"] = "unknown"  # type: ignore[index]
    with pytest.raises(TypeError):
        POLICY_ACTION_TYPES["exec"] = PolicyActionType.SHELL  # type: ignore[index]


def test_known_source_cases_cover_every_contract_source() -> None:
    assert {source for source, _ in KNOWN_SOURCE_CATEGORIES} == set(APPROVAL_SOURCE_CATEGORIES)


# ---------------------------------------------------------------------------
# Enum parity with the higher-layer owners
# ---------------------------------------------------------------------------


def test_policy_action_types_match_gateway_action_type() -> None:
    assert {member.name: member.value for member in PolicyActionType} == {
        member.name: member.value for member in ActionType
    }


def test_approval_categories_are_approval_category_values() -> None:
    category_values = {member.value for member in ApprovalCategory}
    assert set(APPROVAL_SOURCE_CATEGORIES.values()) <= category_values
    assert APPROVAL_CATEGORY_UNKNOWN == ApprovalCategory.UNKNOWN.value


def test_workflow_category_metadata_matches_contract() -> None:
    workflow_map = ApprovalWorkflow.approval_category_map
    assert all(isinstance(category, ApprovalCategory) for category in workflow_map.values())
    assert {source: category.value for source, category in workflow_map.items()} == dict(
        APPROVAL_SOURCE_CATEGORIES
    )
    assert ApprovalWorkflow.approval_category_unknown is ApprovalCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("member", list(ActionType), ids=lambda member: member.value)
def test_every_gateway_action_type_resolves(member: ActionType) -> None:
    canonical = PolicyActionType[member.name]
    assert resolve_policy_action_type(member.value) is canonical
    assert resolve_policy_action_type(member) is canonical
    assert convert_policy_action_type(member.value, ActionType) is member
    assert convert_policy_action_type(member.value, PolicyActionType) is canonical


@pytest.mark.parametrize("action_type", UNKNOWN_ACTION_TYPES)
def test_unknown_action_types_do_not_resolve(action_type: str) -> None:
    assert resolve_policy_action_type(action_type) is None
    assert convert_policy_action_type(action_type, ActionType) is None
    assert unknown_action_type_reason(action_type) == (
        f"Unknown action type '{action_type}'; not policy-controlled"
    )


@pytest.mark.parametrize(
    ("source", "category"), SOURCE_CATEGORY_CASES, ids=lambda value: str(value) or "<empty>"
)
def test_approval_category_for_source(source: str, category: ApprovalCategory) -> None:
    assert approval_category_for_source(source) == category.value


# ---------------------------------------------------------------------------
# Structural and concrete policy adapters agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("decision", list(PolicyDecision), ids=lambda decision: decision.value)
@pytest.mark.parametrize("member", list(ActionType), ids=lambda member: member.value)
def test_policy_adapters_agree_for_every_action_type(
    member: ActionType, decision: PolicyDecision
) -> None:
    request = _enforcement_request(member.value)
    structural_policy = _RecordingPolicy(decision)
    concrete_policy = _RecordingPolicy(decision)

    structural = STRUCTURAL_POLICY_ADAPTER.evaluate(structural_policy, request)
    concrete = CONCRETE_POLICY_ADAPTER.evaluate(concrete_policy, request)

    assert (
        structural
        == concrete
        == PolicyEvaluation(
            result=EXPECTED_ENFORCEMENT_RESULTS[decision],
            reason=f"decided {decision.value}",
            matched_rule="rule-1",
        )
    )
    [structural_request] = structural_policy.requests
    [concrete_request] = concrete_policy.requests
    assert structural_request.action_type is PolicyActionType[member.name]
    assert isinstance(concrete_request, ActionRequest)
    assert concrete_request.action_type is member
    assert _policy_request_fields(structural_request) == _policy_request_fields(concrete_request)

    expected_approval = decision is PolicyDecision.REQUIRE_APPROVAL
    assert STRUCTURAL_POLICY_ADAPTER.requires_approval(structural_policy, request) is (
        expected_approval
    )
    assert CONCRETE_POLICY_ADAPTER.requires_approval(concrete_policy, request) is (
        expected_approval
    )


@pytest.mark.parametrize("action_type", UNKNOWN_ACTION_TYPES)
def test_policy_adapters_agree_on_unknown_action_types(action_type: str) -> None:
    request = _enforcement_request(action_type)
    policy = _RecordingPolicy(PolicyDecision.DENY)
    expected = PolicyEvaluation(
        result=EnforcementResult.ALLOWED,
        reason=f"Unknown action type '{action_type}'; not policy-controlled",
    )

    assert STRUCTURAL_POLICY_ADAPTER.evaluate(policy, request) == expected
    assert CONCRETE_POLICY_ADAPTER.evaluate(policy, request) == expected
    assert STRUCTURAL_POLICY_ADAPTER.requires_approval(policy, request) is False
    assert CONCRETE_POLICY_ADAPTER.requires_approval(policy, request) is False
    assert policy.requests == []


# ---------------------------------------------------------------------------
# Structural and concrete approval adapters agree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "category"), SOURCE_CATEGORY_CASES, ids=lambda value: str(value) or "<empty>"
)
async def test_approval_adapters_agree_for_every_source(
    source: str, category: ApprovalCategory
) -> None:
    request = _enforcement_request(source=source)
    structural_workflow = _RecordingWorkflow()
    concrete_workflow = _RecordingWorkflow()

    structural = await STRUCTURAL_APPROVAL_ADAPTER.request_approval(
        structural_workflow, request, "needs review"
    )
    concrete = await CONCRETE_APPROVAL_ADAPTER.request_approval(
        concrete_workflow, request, "needs review"
    )

    assert (
        structural
        == concrete
        == ApprovalRoute(
            approval_request_id="approval-1",
            category=category.value,
            priority="high",
        )
    )
    [(structural_context, structural_priority)] = structural_workflow.calls
    [(concrete_context, concrete_priority)] = concrete_workflow.calls
    assert structural_context == concrete_context
    assert structural_context.category is category
    assert concrete_context.category is category
    assert structural_priority is ApprovalPriority.HIGH
    assert concrete_priority is ApprovalPriority.HIGH


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", APPROVAL_ADAPTERS)
@pytest.mark.parametrize("status", list(ApprovalStatus), ids=lambda status: status.value)
async def test_wait_for_approval_accepts_only_approved(
    adapter: Any, status: ApprovalStatus
) -> None:
    workflow = _RecordingWorkflow(decision=status)
    approved = await adapter.wait_for_approval(workflow, "approval-1", 1.0)
    assert approved is (status is ApprovalStatus.APPROVED)


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", APPROVAL_ADAPTERS)
@pytest.mark.parametrize("expired", [False, True], ids=["unexpired", "expired"])
@pytest.mark.parametrize("status", list(ApprovalStatus), ids=lambda status: status.value)
async def test_is_approval_valid_requires_approved_and_unexpired(
    adapter: Any, status: ApprovalStatus, expired: bool
) -> None:
    stored = SimpleNamespace(status=status, is_expired=lambda: expired)
    workflow = _RecordingWorkflow(stored_request=stored)
    valid = await adapter.is_approval_valid(workflow, "approval-1")
    assert valid is (status is ApprovalStatus.APPROVED and not expired)


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", APPROVAL_ADAPTERS)
async def test_is_approval_valid_rejects_missing_request(adapter: Any) -> None:
    assert await adapter.is_approval_valid(_RecordingWorkflow(), "approval-1") is False


# ---------------------------------------------------------------------------
# Layer boundary
# ---------------------------------------------------------------------------

_FORBIDDEN_IMPORT_PREFIXES = ("aragora.gateway", "aragora.computer_use", "aragora.ops")


@pytest.mark.parametrize("module_file", ["approval_mappings.py", "approval_enforcer.py"])
def test_security_contract_modules_do_not_import_higher_layers(module_file: str) -> None:
    path = Path(approval_enforcer.__file__).with_name(module_file)
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
    offenders = sorted(
        name
        for name in imported
        if any(
            name == prefix or name.startswith(f"{prefix}.") for prefix in _FORBIDDEN_IMPORT_PREFIXES
        )
    )
    assert offenders == []
