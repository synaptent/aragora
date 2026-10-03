"""
Unified Approval Enforcer tests.

Validates the single enforcement path for gateway, device, and computer-use
actions, including:
- Policy evaluation routing
- Approval workflow integration
- Audit event emission
- Bypass detection and prevention

Stage 6 (#177): Security/approval consolidation.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.security.approval_enforcer import (
    EnforcementDecision,
    EnforcementRequest,
    EnforcementResult,
    UnifiedApprovalEnforcer,
    enforce_action,
    get_approval_enforcer,
    register_approval_workflow_adapter,
    register_policy_evaluation_adapter,
    set_approval_enforcer,
)
from aragora.ops.security_edge_adapters import register_security_approval_adapters


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_policy():
    """Create a policy with correct rule semantics for testing.

    The enterprise policy has a quirk where ``block_dangerous_commands``
    uses ``command_deny_patterns`` which causes it to match ALL non-dangerous
    shell commands. This test policy uses ``command_patterns`` (allowlist-style)
    so each rule only matches its intended commands.
    """
    from aragora.gateway.openclaw_policy import OpenClawPolicy

    return OpenClawPolicy(
        policy_dict={
            "version": 1,
            "default_decision": "deny",
            "rules": [
                {
                    "name": "block_system_directories",
                    "action_types": ["file_read", "file_write", "file_delete"],
                    "decision": "deny",
                    "priority": 100,
                    "path_patterns": [
                        "/etc/**",
                        "/sys/**",
                        "/proc/**",
                        "/root/**",
                    ],
                },
                {
                    "name": "block_dangerous_commands",
                    "action_types": ["shell"],
                    "decision": "deny",
                    "priority": 100,
                    "command_patterns": [
                        r"rm\s+-rf\s+/",
                        r"mkfs\.",
                        r"dd\s+if=.*of=/dev/",
                    ],
                },
                {
                    "name": "approve_elevated_commands",
                    "action_types": ["shell"],
                    "decision": "require_approval",
                    "priority": 50,
                    "command_patterns": [r"^sudo\s+", r"^su\s+", r"^doas\s+"],
                },
                {
                    "name": "allow_safe_commands",
                    "action_types": ["shell"],
                    "decision": "allow",
                    "priority": 10,
                    "command_patterns": [
                        r"^(ls|cat|head|tail|grep|find|wc|echo|pwd|cd)\s*",
                        r"^(python|node|npm|pip|git)\s+",
                    ],
                },
                {
                    "name": "allow_workspace_files",
                    "action_types": ["file_read", "file_write", "file_delete"],
                    "decision": "allow",
                    "priority": 10,
                    "workspace_only": True,
                },
                {
                    "name": "allow_screenshots",
                    "action_types": ["screenshot"],
                    "decision": "allow",
                    "priority": 5,
                },
                {
                    "name": "allow_browser",
                    "action_types": ["browser"],
                    "decision": "allow",
                    "priority": 5,
                },
            ],
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def registered_security_approval_adapters():
    """Register concrete higher-layer adapters and isolate global state."""
    register_security_approval_adapters()
    yield
    register_policy_evaluation_adapter(None)
    register_approval_workflow_adapter(None)


@pytest.fixture
def enforcer():
    """Create a basic enforcer without policy (allow-all)."""
    return UnifiedApprovalEnforcer(audit_enabled=False)


@pytest.fixture
def policy_enforcer():
    """Create an enforcer with a well-defined test policy."""
    return UnifiedApprovalEnforcer(policy=_create_test_policy(), audit_enabled=False)


@pytest.fixture
def make_request():
    """Factory for creating enforcement requests."""

    def _make(
        action_type: str = "shell",
        actor_id: str = "user-1",
        source: str = "computer_use",
        **kwargs,
    ) -> EnforcementRequest:
        return EnforcementRequest(
            action_type=action_type,
            actor_id=actor_id,
            source=source,
            session_id="session-1",
            workspace_id="default",
            **kwargs,
        )

    return _make


# ---------------------------------------------------------------------------
# EnforcementRequest tests
# ---------------------------------------------------------------------------


class TestEnforcementRequest:
    """Test the EnforcementRequest dataclass."""

    def test_create_request(self, make_request):
        req = make_request()
        assert req.action_type == "shell"
        assert req.actor_id == "user-1"
        assert req.source == "computer_use"
        assert req.workspace_id == "default"

    def test_request_with_details(self, make_request):
        req = make_request(details={"command": "ls -la"})
        assert req.details["command"] == "ls -la"

    def test_request_sources(self, make_request):
        for source in ("gateway", "device", "computer_use"):
            req = make_request(source=source)
            assert req.source == source


# ---------------------------------------------------------------------------
# EnforcementDecision tests
# ---------------------------------------------------------------------------


class TestEnforcementDecision:
    """Test the EnforcementDecision dataclass."""

    def test_allowed_decision(self, make_request):
        decision = EnforcementDecision(
            id="d-1",
            result=EnforcementResult.ALLOWED,
            reason="Policy allows",
            request=make_request(),
        )
        assert decision.approved is True
        assert decision.denied is False

    def test_denied_decision(self, make_request):
        decision = EnforcementDecision(
            id="d-1",
            result=EnforcementResult.DENIED,
            reason="Policy denies",
            request=make_request(),
        )
        assert decision.approved is False
        assert decision.denied is True

    def test_pending_decision(self, make_request):
        decision = EnforcementDecision(
            id="d-1",
            result=EnforcementResult.PENDING_APPROVAL,
            reason="Requires approval",
            request=make_request(),
        )
        assert decision.approved is False
        assert decision.denied is False

    def test_bypass_detected(self, make_request):
        decision = EnforcementDecision(
            id="d-1",
            result=EnforcementResult.BYPASSED_DETECTED,
            reason="Bypass attempt",
            request=make_request(),
        )
        assert decision.approved is False
        assert decision.denied is True

    def test_to_dict(self, make_request):
        decision = EnforcementDecision(
            id="d-1",
            result=EnforcementResult.ALLOWED,
            reason="OK",
            request=make_request(),
        )
        d = decision.to_dict()
        assert d["id"] == "d-1"
        assert d["result"] == "allowed"
        assert d["source"] == "computer_use"
        assert d["action_type"] == "shell"


# ---------------------------------------------------------------------------
# No-policy enforcer (allow-all baseline)
# ---------------------------------------------------------------------------


class TestNoPolicyEnforcer:
    """Test enforcer behavior when no policy is configured."""

    @pytest.mark.asyncio
    async def test_allows_all_without_policy(self, enforcer, make_request):
        decision = await enforcer.enforce(make_request())
        assert decision.approved is True
        assert "No policy configured" in decision.reason

    @pytest.mark.asyncio
    async def test_allows_all_action_types(self, enforcer, make_request):
        for action in ("shell", "file_read", "file_write", "browser", "api"):
            decision = await enforcer.enforce(make_request(action_type=action))
            assert decision.approved is True

    @pytest.mark.asyncio
    async def test_allows_all_sources(self, enforcer, make_request):
        for source in ("gateway", "device", "computer_use"):
            decision = await enforcer.enforce(make_request(source=source))
            assert decision.approved is True


# ---------------------------------------------------------------------------
# Policy-based enforcement
# ---------------------------------------------------------------------------


class TestPolicyEnforcement:
    """Test enforcement with the test policy."""

    @pytest.mark.asyncio
    async def test_allows_safe_shell_commands(self, policy_enforcer, make_request):
        req = make_request(
            action_type="shell",
            details={"command": "ls -la /workspace/default"},
        )
        decision = await policy_enforcer.enforce(req)
        assert decision.approved is True
        assert decision.matched_rule == "allow_safe_commands"

    @pytest.mark.asyncio
    async def test_denies_system_file_access(self, policy_enforcer, make_request):
        req = make_request(
            action_type="file_read",
            details={"path": "/etc/passwd"},
        )
        decision = await policy_enforcer.enforce(req)
        assert decision.denied is True
        assert decision.matched_rule == "block_system_directories"

    @pytest.mark.asyncio
    async def test_denies_destructive_commands(self, policy_enforcer, make_request):
        req = make_request(
            action_type="shell",
            details={"command": "rm -rf /"},
        )
        decision = await policy_enforcer.enforce(req)
        assert decision.denied is True
        assert decision.matched_rule == "block_dangerous_commands"

    @pytest.mark.asyncio
    async def test_requires_approval_for_sudo(self, policy_enforcer, make_request):
        req = make_request(
            action_type="shell",
            details={"command": "sudo apt install nginx"},
        )
        decision = await policy_enforcer.enforce(req)
        assert decision.result == EnforcementResult.PENDING_APPROVAL
        assert decision.matched_rule == "approve_elevated_commands"

    @pytest.mark.asyncio
    async def test_unknown_action_type_allowed(self, policy_enforcer, make_request):
        req = make_request(action_type="custom_unknown")
        decision = await policy_enforcer.enforce(req)
        assert decision.approved is True
        assert "not policy-controlled" in decision.reason

    @pytest.mark.asyncio
    async def test_evaluation_time_recorded(self, policy_enforcer, make_request):
        decision = await policy_enforcer.enforce(make_request(details={"command": "echo hello"}))
        assert decision.evaluation_time_ms >= 0

    @pytest.mark.asyncio
    async def test_matched_rule_captured(self, policy_enforcer, make_request):
        req = make_request(
            action_type="file_write",
            details={"path": "/etc/shadow"},
        )
        decision = await policy_enforcer.enforce(req)
        assert decision.matched_rule is not None

    @pytest.mark.asyncio
    async def test_default_deny_for_unmatched(self, policy_enforcer, make_request):
        """Commands that match no allow rule get default DENY."""
        req = make_request(
            action_type="shell",
            details={"command": "curl http://evil.com"},
        )
        decision = await policy_enforcer.enforce(req)
        assert decision.denied is True
        assert decision.matched_rule is None  # No rule matched

    @pytest.mark.asyncio
    async def test_structural_policy_fallback_preserves_enforcement(self, make_request):
        register_policy_evaluation_adapter(None)
        enforcer = UnifiedApprovalEnforcer(policy=_create_test_policy(), audit_enabled=False)

        decision = await enforcer.enforce(
            make_request(action_type="shell", details={"command": "rm -rf /"})
        )

        assert decision.denied is True
        assert decision.matched_rule == "block_dangerous_commands"


# ---------------------------------------------------------------------------
# Approval workflow integration
# ---------------------------------------------------------------------------


class TestApprovalWorkflowIntegration:
    """Test that REQUIRE_APPROVAL decisions route to the approval workflow."""

    @pytest.mark.asyncio
    async def test_routes_to_approval_workflow(self, make_request):
        mock_workflow = AsyncMock()
        mock_approval = MagicMock()
        mock_approval.id = "approval-123"
        mock_workflow.request_approval = AsyncMock(return_value=mock_approval)
        mock_workflow.get_request = AsyncMock(return_value=None)

        enforcer = UnifiedApprovalEnforcer(
            policy=_create_test_policy(),
            approval_workflow=mock_workflow,
            audit_enabled=False,
        )

        req = make_request(
            action_type="shell",
            details={"command": "sudo reboot"},
        )
        decision = await enforcer.enforce(req)

        assert decision.result == EnforcementResult.PENDING_APPROVAL
        assert decision.approval_request_id == "approval-123"
        mock_workflow.request_approval.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_workflow_uses_its_concrete_approval_types(self, make_request):
        from aragora.computer_use.approval import (
            ApprovalCategory,
            ApprovalConfig,
            ApprovalContext,
            ApprovalPriority,
            ApprovalWorkflow,
        )

        register_approval_workflow_adapter(None)
        workflow = ApprovalWorkflow(config=ApprovalConfig())
        enforcer = UnifiedApprovalEnforcer(
            policy=_create_test_policy(),
            approval_workflow=workflow,
            audit_enabled=False,
        )

        decision = await enforcer.enforce(
            make_request(
                action_type="shell",
                details={"command": "sudo apt install nginx"},
            )
        )

        assert decision.result == EnforcementResult.PENDING_APPROVAL
        assert decision.approval_request_id is not None
        approval = await workflow.get_request(decision.approval_request_id)
        assert approval is not None
        assert type(approval.context) is ApprovalContext
        assert approval.context.category is ApprovalCategory.DESTRUCTIVE_ACTION
        assert approval.priority is ApprovalPriority.HIGH

    @pytest.mark.asyncio
    async def test_no_workflow_keeps_pending(self, policy_enforcer, make_request):
        """When no workflow is configured, decision stays PENDING_APPROVAL."""
        req = make_request(
            action_type="shell",
            details={"command": "sudo systemctl restart"},
        )
        decision = await policy_enforcer.enforce(req)
        assert decision.result == EnforcementResult.PENDING_APPROVAL
        assert decision.approval_request_id is None

    @pytest.mark.asyncio
    async def test_force_approval_routes_and_waits(self, make_request):
        from aragora.computer_use.approval import ApprovalConfig, ApprovalWorkflow

        workflow = ApprovalWorkflow(
            config=ApprovalConfig(
                default_timeout_seconds=1.0,
                min_timeout_seconds=0.1,
            )
        )

        enforcer = UnifiedApprovalEnforcer(
            approval_workflow=workflow,
            audit_enabled=False,
        )

        req = make_request(
            action_type="browser",
            details={
                "force_approval": True,
                "force_reason": "Sensitive navigation",
            },
        )
        decision = await enforcer.enforce(req)

        assert decision.result == EnforcementResult.PENDING_APPROVAL
        assert decision.approval_request_id is not None
        assert "Sensitive navigation" in decision.reason

        await workflow.approve(decision.approval_request_id, "admin")
        approved = await enforcer.wait_for_approval(decision.approval_request_id, timeout=1.0)
        assert approved is True


# ---------------------------------------------------------------------------
# Pre-existing approval token verification
# ---------------------------------------------------------------------------


class TestApprovalTokenVerification:
    """Test pre-existing approval token handling."""

    @pytest.mark.asyncio
    async def test_valid_approval_token_allows(self, make_request):
        from aragora.computer_use.approval import (
            ApprovalCategory,
            ApprovalConfig,
            ApprovalContext,
            ApprovalWorkflow,
        )

        workflow = ApprovalWorkflow(config=ApprovalConfig())

        ctx = ApprovalContext(
            task_id="t1",
            action_type="shell",
            action_details={},
            category=ApprovalCategory.SYSTEM_MODIFICATION,
            reason="test",
        )
        approval = await workflow.request_approval(ctx)
        await workflow.approve(approval.id, "admin")

        enforcer = UnifiedApprovalEnforcer(approval_workflow=workflow, audit_enabled=False)
        req = make_request(approval_id=approval.id)
        decision = await enforcer.enforce(req)

        assert decision.approved is True
        assert approval.id in decision.reason

    @pytest.mark.asyncio
    async def test_invalid_approval_token_falls_through(self, make_request):
        mock_workflow = AsyncMock()
        mock_workflow.get_request = AsyncMock(return_value=None)

        enforcer = UnifiedApprovalEnforcer(approval_workflow=mock_workflow, audit_enabled=False)
        req = make_request(approval_id="fake-token-999")
        decision = await enforcer.enforce(req)

        # Falls through to policy (no policy = allowed)
        assert decision.approved is True
        assert "No policy configured" in decision.reason

    @pytest.mark.asyncio
    async def test_denied_approval_token_falls_through(self, make_request):
        from aragora.computer_use.approval import (
            ApprovalCategory,
            ApprovalConfig,
            ApprovalContext,
            ApprovalWorkflow,
        )

        workflow = ApprovalWorkflow(config=ApprovalConfig())
        ctx = ApprovalContext(
            task_id="t1",
            action_type="shell",
            action_details={},
            category=ApprovalCategory.SYSTEM_MODIFICATION,
            reason="test",
        )
        approval = await workflow.request_approval(ctx)
        await workflow.deny(approval.id, "admin")

        enforcer = UnifiedApprovalEnforcer(approval_workflow=workflow, audit_enabled=False)
        req = make_request(approval_id=approval.id)
        decision = await enforcer.enforce(req)

        # Denied approval means token is invalid, falls through
        assert "No policy configured" in decision.reason


# ---------------------------------------------------------------------------
# Bypass detection and prevention
# ---------------------------------------------------------------------------


class TestBypassPrevention:
    """Test bypass detection mechanisms.

    These tests verify that the enforcer detects attempts to circumvent
    the approval flow, including:
    - Performing sensitive actions without approval tokens
    - Using fake/expired approval tokens
    - Skipping the enforcement path entirely
    """

    @pytest.mark.asyncio
    async def test_detects_missing_approval_token(self, make_request):
        enforcer = UnifiedApprovalEnforcer(policy=_create_test_policy(), audit_enabled=False)

        # sudo requires approval per test policy
        req = make_request(
            action_type="shell",
            details={"command": "sudo rm /tmp/cache"},
        )
        decision = await enforcer.verify_not_bypassed(req)

        assert decision.result == EnforcementResult.BYPASSED_DETECTED
        assert "without approval token" in decision.reason

    @pytest.mark.asyncio
    async def test_detects_fake_approval_token(self, make_request):
        mock_workflow = AsyncMock()
        mock_workflow.get_request = AsyncMock(return_value=None)

        enforcer = UnifiedApprovalEnforcer(
            policy=_create_test_policy(),
            approval_workflow=mock_workflow,
            audit_enabled=False,
        )

        req = make_request(
            action_type="shell",
            details={"command": "sudo systemctl stop nginx"},
        )
        decision = await enforcer.verify_not_bypassed(req, claimed_approval_id="fake-token-999")

        assert decision.result == EnforcementResult.BYPASSED_DETECTED
        assert "Invalid or expired" in decision.reason

    @pytest.mark.asyncio
    async def test_detects_expired_approval_token(self, make_request):
        from aragora.computer_use.approval import (
            ApprovalCategory,
            ApprovalConfig,
            ApprovalContext,
            ApprovalWorkflow,
        )

        workflow = ApprovalWorkflow(
            config=ApprovalConfig(
                default_timeout_seconds=0.01,
                min_timeout_seconds=0.01,
            )
        )
        ctx = ApprovalContext(
            task_id="t1",
            action_type="shell",
            action_details={},
            category=ApprovalCategory.SYSTEM_MODIFICATION,
            reason="test",
        )
        approval = await workflow.request_approval(ctx, timeout_seconds=0.01)
        await workflow.approve(approval.id, "admin")

        # Wait for expiry
        await asyncio.sleep(0.05)

        enforcer = UnifiedApprovalEnforcer(
            policy=_create_test_policy(),
            approval_workflow=workflow,
            audit_enabled=False,
        )

        req = make_request(
            action_type="shell",
            details={"command": "sudo cat /etc/shadow"},
        )
        decision = await enforcer.verify_not_bypassed(req, claimed_approval_id=approval.id)

        assert decision.result == EnforcementResult.BYPASSED_DETECTED

    @pytest.mark.asyncio
    async def test_valid_approval_passes_bypass_check(self, make_request):
        from aragora.computer_use.approval import (
            ApprovalCategory,
            ApprovalConfig,
            ApprovalContext,
            ApprovalWorkflow,
        )

        workflow = ApprovalWorkflow(config=ApprovalConfig())
        ctx = ApprovalContext(
            task_id="t1",
            action_type="shell",
            action_details={},
            category=ApprovalCategory.SYSTEM_MODIFICATION,
            reason="test",
        )
        approval = await workflow.request_approval(ctx)
        await workflow.approve(approval.id, "admin")

        enforcer = UnifiedApprovalEnforcer(
            policy=_create_test_policy(),
            approval_workflow=workflow,
            audit_enabled=False,
        )

        req = make_request(
            action_type="shell",
            details={"command": "sudo apt update"},
        )
        decision = await enforcer.verify_not_bypassed(req, claimed_approval_id=approval.id)

        assert decision.result == EnforcementResult.ALLOWED
        assert approval.id in (decision.approval_request_id or "")

    @pytest.mark.asyncio
    async def test_non_sensitive_action_no_bypass(self, make_request):
        enforcer = UnifiedApprovalEnforcer(policy=_create_test_policy(), audit_enabled=False)

        # Custom action type is not policy-controlled → not sensitive
        req = make_request(action_type="custom_safe_action")
        decision = await enforcer.verify_not_bypassed(req)

        assert decision.result == EnforcementResult.ALLOWED

    @pytest.mark.asyncio
    async def test_bypass_attempts_logged(self, make_request):
        enforcer = UnifiedApprovalEnforcer(policy=_create_test_policy(), audit_enabled=False)

        req = make_request(
            action_type="shell",
            details={"command": "sudo rm /var/log/syslog"},
        )
        await enforcer.verify_not_bypassed(req)

        attempts = enforcer.get_bypass_attempts()
        assert len(attempts) == 1
        assert attempts[0].result == EnforcementResult.BYPASSED_DETECTED


# ---------------------------------------------------------------------------
# Audit event emission
# ---------------------------------------------------------------------------


class TestAuditEventEmission:
    """Test that enforcement decisions emit audit events."""

    @pytest.mark.asyncio
    async def test_emits_audit_for_allowed(self, make_request):
        enforcer = UnifiedApprovalEnforcer(audit_enabled=True)
        enforcer._emit_audit_event = AsyncMock()

        await enforcer.enforce(make_request())
        enforcer._emit_audit_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_emits_audit_for_denied(self, make_request):
        enforcer = UnifiedApprovalEnforcer(policy=_create_test_policy(), audit_enabled=True)
        enforcer._emit_audit_event = AsyncMock()

        req = make_request(action_type="file_read", details={"path": "/etc/shadow"})
        await enforcer.enforce(req)
        enforcer._emit_audit_event.assert_called_once()
        decision = enforcer._emit_audit_event.call_args[0][0]
        assert decision.result == EnforcementResult.DENIED

    @pytest.mark.asyncio
    async def test_emits_audit_for_bypass_detection(self, make_request):
        enforcer = UnifiedApprovalEnforcer(policy=_create_test_policy(), audit_enabled=True)
        enforcer._emit_audit_event = AsyncMock()

        req = make_request(
            action_type="shell",
            details={"command": "sudo whoami"},
        )
        await enforcer.verify_not_bypassed(req)
        enforcer._emit_audit_event.assert_called_once()
        decision = enforcer._emit_audit_event.call_args[0][0]
        assert decision.result == EnforcementResult.BYPASSED_DETECTED

    @pytest.mark.asyncio
    async def test_audit_disabled_no_emit(self, make_request):
        enforcer = UnifiedApprovalEnforcer(audit_enabled=False)
        enforcer._emit_audit_event = AsyncMock()

        await enforcer.enforce(make_request())
        enforcer._emit_audit_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_emits_audit_for_approval_required(self, make_request):
        enforcer = UnifiedApprovalEnforcer(policy=_create_test_policy(), audit_enabled=True)
        enforcer._emit_audit_event = AsyncMock()

        req = make_request(
            action_type="shell",
            details={"command": "sudo restart"},
        )
        await enforcer.enforce(req)
        enforcer._emit_audit_event.assert_called_once()
        decision = enforcer._emit_audit_event.call_args[0][0]
        assert decision.result == EnforcementResult.PENDING_APPROVAL


# ---------------------------------------------------------------------------
# Decision logging
# ---------------------------------------------------------------------------


class TestDecisionLogging:
    """Test in-memory decision log for audit review."""

    @pytest.mark.asyncio
    async def test_decisions_logged(self, enforcer, make_request):
        await enforcer.enforce(make_request(source="gateway"))
        await enforcer.enforce(make_request(source="device"))
        await enforcer.enforce(make_request(source="computer_use"))

        decisions = enforcer.get_recent_decisions()
        assert len(decisions) == 3

    @pytest.mark.asyncio
    async def test_filter_by_source(self, enforcer, make_request):
        await enforcer.enforce(make_request(source="gateway"))
        await enforcer.enforce(make_request(source="device"))
        await enforcer.enforce(make_request(source="computer_use"))

        gateway_decisions = enforcer.get_recent_decisions(source="gateway")
        assert len(gateway_decisions) == 1
        assert gateway_decisions[0].request.source == "gateway"

    @pytest.mark.asyncio
    async def test_log_size_bounded(self, make_request):
        enforcer = UnifiedApprovalEnforcer(audit_enabled=False)
        enforcer._max_log_size = 5

        for i in range(10):
            await enforcer.enforce(make_request(actor_id=f"user-{i}"))

        assert len(enforcer.get_recent_decisions(limit=100)) == 5


# ---------------------------------------------------------------------------
# Multi-source enforcement
# ---------------------------------------------------------------------------


class TestMultiSourceEnforcement:
    """Test that all three sources (gateway, device, computer_use) are handled."""

    @pytest.mark.asyncio
    async def test_gateway_source(self, policy_enforcer, make_request):
        req = make_request(
            source="gateway",
            action_type="file_read",
            details={"path": "/workspace/default/data.json"},
        )
        decision = await policy_enforcer.enforce(req)
        assert decision.request.source == "gateway"

    @pytest.mark.asyncio
    async def test_device_source(self, policy_enforcer, make_request):
        req = make_request(
            source="device",
            action_type="screenshot",
        )
        decision = await policy_enforcer.enforce(req)
        assert decision.request.source == "device"

    @pytest.mark.asyncio
    async def test_computer_use_source(self, policy_enforcer, make_request):
        req = make_request(
            source="computer_use",
            action_type="browser",
            details={"url": "https://example.com"},
        )
        decision = await policy_enforcer.enforce(req)
        assert decision.request.source == "computer_use"


# ---------------------------------------------------------------------------
# Module-level API
# ---------------------------------------------------------------------------


class TestModuleAPI:
    """Test module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_get_approval_enforcer_singleton(self):
        e1 = get_approval_enforcer()
        e2 = get_approval_enforcer()
        assert e1 is e2

    @pytest.mark.asyncio
    async def test_set_approval_enforcer(self, enforcer):
        set_approval_enforcer(enforcer)
        assert get_approval_enforcer() is enforcer
        # Reset to avoid affecting other tests
        set_approval_enforcer(None)

    @pytest.mark.asyncio
    async def test_enforce_action_convenience(self, make_request):
        set_approval_enforcer(UnifiedApprovalEnforcer(audit_enabled=False))
        decision = await enforce_action(make_request())
        assert decision.approved is True
        set_approval_enforcer(None)


# ---------------------------------------------------------------------------
# Concurrent enforcement
# ---------------------------------------------------------------------------


class TestConcurrentEnforcement:
    """Test concurrent enforcement requests."""

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, policy_enforcer, make_request):
        requests = [
            make_request(
                action_type="shell",
                details={"command": f"echo {i}"},
                actor_id=f"user-{i}",
            )
            for i in range(10)
        ]

        decisions = await asyncio.gather(*[policy_enforcer.enforce(req) for req in requests])

        assert len(decisions) == 10
        assert all(isinstance(d, EnforcementDecision) for d in decisions)

    @pytest.mark.asyncio
    async def test_concurrent_bypass_checks(self, make_request):
        enforcer = UnifiedApprovalEnforcer(policy=_create_test_policy(), audit_enabled=False)

        requests = [
            make_request(
                action_type="shell",
                details={"command": "sudo ping localhost"},
                actor_id=f"user-{i}",
            )
            for i in range(5)
        ]

        decisions = await asyncio.gather(*[enforcer.verify_not_bypassed(req) for req in requests])

        assert len(decisions) == 5
        assert all(d.result == EnforcementResult.BYPASSED_DETECTED for d in decisions)
