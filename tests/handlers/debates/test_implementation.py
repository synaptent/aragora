"""Tests for debate implementation handler (decision integrity).

Tests the ImplementationOperationsMixin covering:
- POST /api/v1/debates/{id}/decision-integrity
- _parse_request configuration parsing
- _build_integrity_package
- _persist_artifacts (receipt + plan)
- _obsidian_writeback
- _handle_workflow_mode
- _handle_approval_execution
- _execute_direct / _execute_hybrid / _execute_fabric / _execute_computer_use
- _append_review
- _check_approval_permission
- _check_execution_enabled
- _build_changes_list
- _route_and_respond
- _check_execution_budget helper
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.autonomous.loop_enhancement import ApprovalStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict[str, Any]:
    """Extract JSON body from a HandlerResult."""
    if result is None:
        return {}
    raw = result.body
    if isinstance(raw, bytes):
        return json.loads(raw.decode())
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _status(result) -> int:
    """Extract status code from a HandlerResult."""
    if result is None:
        return 0
    return result.status_code


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


@dataclass
class _MockTask:
    id: str = "task-1"
    description: str = "Implement feature"
    files: list[str] = field(default_factory=lambda: ["main.py"])
    complexity: str = "low"


@dataclass
class _MockPlan:
    tasks: list[_MockTask] = field(default_factory=lambda: [_MockTask()])


@dataclass
class _MockReceipt:
    receipt_id: str = "rcpt-001"

    def to_dict(self):
        return {"receipt_id": self.receipt_id}


@dataclass
class _MockPackage:
    receipt: _MockReceipt | None = field(default_factory=_MockReceipt)
    plan: _MockPlan | None = field(default_factory=_MockPlan)

    def to_dict(self):
        d: dict[str, Any] = {}
        if self.receipt:
            d["receipt"] = self.receipt.to_dict()
        if self.plan:
            d["plan"] = {"tasks": [{"id": t.id} for t in self.plan.tasks]}
        return d


@dataclass
class _MockApprovalRequest:
    id: str = "appr-001"
    title: str = "Implement debate d1"
    description: str = "Execute plan"
    changes: list[dict[str, Any]] = field(default_factory=list)
    risk_level: str = "medium"
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    requested_by: str = "test-user-001"
    timeout_seconds: int | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _MockOutcome:
    success: bool = True
    tasks_total: int = 1
    tasks_completed: int = 1
    duration_seconds: float = 2.5

    def to_dict(self):
        return {
            "success": self.success,
            "tasks_total": self.tasks_total,
            "tasks_completed": self.tasks_completed,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class _MockTaskResult:
    def to_dict(self):
        return {"status": "completed"}


@dataclass
class _MockProgress:
    def to_dict(self):
        return {"total": 1, "completed": 1}


class _MockPermissionDecision:
    def __init__(self, allowed: bool):
        self.allowed = allowed


# ---------------------------------------------------------------------------
# Test handler class that includes the mixin
# ---------------------------------------------------------------------------


def _make_handler(
    storage=None,
    ctx_extra: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
):
    """Build a minimal handler with the ImplementationOperationsMixin."""
    from aragora.server.handlers.debates.implementation import (
        ImplementationOperationsMixin,
    )
    from aragora.server.handlers.base import BaseHandler

    ctx: dict[str, Any] = {}
    if storage is not None:
        ctx["storage"] = storage
    if ctx_extra:
        ctx.update(ctx_extra)

    class _Handler(ImplementationOperationsMixin, BaseHandler):
        def __init__(self):
            self.ctx = ctx
            self._json_body = json_body

        def get_storage(self):
            return ctx.get("storage")

        def read_json_body(self, handler, max_size=None):
            return self._json_body or {}

        def get_current_user(self, handler):
            user = MagicMock()
            user.user_id = "test-user-001"
            user.org_id = "test-org-001"
            return user

    return _Handler()


def _mock_http_handler(command="POST"):
    """Create a mock HTTP handler object."""
    h = MagicMock()
    h.command = command
    h.headers = {"Content-Length": "2"}
    h.rfile = MagicMock()
    h.rfile.read.return_value = b"{}"
    return h


# ---------------------------------------------------------------------------
# _parse_request tests
# ---------------------------------------------------------------------------


class TestParseRequest:
    """Tests for _parse_request configuration parsing."""

    def _parse(self, payload=None, ctx=None):
        from aragora.server.handlers.debates.implementation import _parse_request

        return _parse_request(payload or {}, ctx or {})

    def test_defaults(self):
        rc = self._parse()
        assert rc.include_receipt is True
        assert rc.include_plan is True
        assert rc.include_context is False
        assert rc.plan_strategy == "single_task"
        assert rc.execution_mode == "plan_only"
        assert rc.execution_engine == ""
        assert rc.parallel_execution is False
        assert rc.notify_origin is False
        assert rc.risk_level == "medium"
        assert rc.approval_mode == "risk_based"
        assert rc.max_auto_risk == "low"
        assert rc.workflow_mode is False
        assert rc.execute_workflow is False

    def test_include_flags(self):
        rc = self._parse({"include_receipt": False, "include_plan": False, "include_context": True})
        assert rc.include_receipt is False
        assert rc.include_plan is False
        assert rc.include_context is True

    def test_hybrid_execution_mode_normalizes(self):
        rc = self._parse({"execution_mode": "hybrid"})
        assert rc.execution_engine == "hybrid"
        assert rc.execution_mode == "execute"

    def test_fabric_execution_mode_normalizes(self):
        rc = self._parse({"execution_mode": "fabric"})
        assert rc.execution_engine == "fabric"
        assert rc.execution_mode == "execute"

    def test_computer_use_execution_mode_normalizes(self):
        rc = self._parse({"execution_mode": "computer_use"})
        assert rc.execution_engine == "computer_use"
        assert rc.execution_mode == "execute"

    def test_workflow_mode(self):
        rc = self._parse({"execution_mode": "workflow"})
        assert rc.workflow_mode is True
        assert rc.execute_workflow is False

    def test_workflow_execute_mode(self):
        rc = self._parse({"execution_mode": "workflow_execute"})
        assert rc.workflow_mode is True
        assert rc.execute_workflow is True

    def test_execute_workflow_mode(self):
        rc = self._parse({"execution_mode": "execute_workflow"})
        assert rc.workflow_mode is True
        assert rc.execute_workflow is True

    def test_workflow_forces_include_plan(self):
        rc = self._parse({"execution_mode": "workflow", "include_plan": False})
        assert rc.include_plan is True

    def test_effective_engine_workflow(self):
        rc = self._parse({"execution_mode": "workflow"})
        assert rc.effective_engine == "workflow"

    def test_effective_engine_execute(self):
        rc = self._parse({"execution_mode": "execute"})
        assert rc.effective_engine == "hybrid"

    def test_effective_engine_request_approval(self):
        rc = self._parse({"execution_mode": "request_approval"})
        assert rc.effective_engine == "hybrid"

    def test_effective_engine_plan_only_no_engine(self):
        rc = self._parse({"execution_mode": "plan_only"})
        assert rc.effective_engine == ""

    def test_explicit_execution_engine(self):
        rc = self._parse({"execution_engine": "fabric"})
        assert rc.effective_engine == "fabric"

    def test_repo_root_from_ctx(self):
        rc = self._parse({}, {"repo_root": "/tmp/myrepo"})
        assert rc.repo_path == Path("/tmp/myrepo")

    def test_repo_root_absent(self):
        rc = self._parse({})
        assert rc.repo_path is None

    def test_parallel_execution(self):
        rc = self._parse({"parallel_execution": True})
        assert rc.parallel_execution is True

    def test_notify_origin(self):
        rc = self._parse({"notify_origin": True})
        assert rc.notify_origin is True

    def test_risk_level(self):
        rc = self._parse({"risk_level": "high"})
        assert rc.risk_level == "high"

    def test_approval_timeout(self):
        rc = self._parse({"approval_timeout_seconds": 300})
        assert rc.approval_timeout == 300

    def test_budget_limit_usd(self):
        rc = self._parse({"budget_limit_usd": 5.0})
        assert rc.budget_limit_usd == 5.0

    def test_openclaw_actions(self):
        rc = self._parse({"openclaw_actions": ["run"]})
        assert rc.openclaw_actions == ["run"]

    def test_computer_use_actions(self):
        rc = self._parse({"computer_use_actions": ["click"]})
        assert rc.computer_use_actions == ["click"]

    def test_implementation_profile_dict(self):
        rc = self._parse({"implementation_profile": {"key": "val"}})
        assert rc.implementation_profile == {"key": "val"}

    def test_implementation_profile_non_dict_ignored(self):
        rc = self._parse({"implementation_profile": "not-a-dict"})
        assert rc.implementation_profile is None

    def test_channel_targets_alias(self):
        rc = self._parse({"chat_targets": ["slack"]})
        assert rc.channel_targets == ["slack"]

    def test_channel_targets_preferred(self):
        rc = self._parse({"channel_targets": ["teams"], "chat_targets": ["slack"]})
        assert rc.channel_targets == ["teams"]

    def test_thread_id_alias(self):
        rc = self._parse({"origin_thread_id": "t-1"})
        assert rc.thread_id == "t-1"

    def test_complexity_router_alias(self):
        rc = self._parse({"agent_by_complexity": {"low": "gpt-4"}})
        assert rc.complexity_router == {"low": "gpt-4"}

    def test_task_type_router_alias(self):
        rc = self._parse({"agent_by_task_type": {"code": "claude"}})
        assert rc.task_type_router == {"code": "claude"}

    def test_capability_router_alias(self):
        rc = self._parse({"agent_by_capability": {"vision": "gpt-4v"}})
        assert rc.capability_router == {"vision": "gpt-4v"}

    def test_fabric_fields(self):
        rc = self._parse(
            {
                "fabric_models": ["claude", "gpt-4"],
                "fabric_pool_id": "pool-1",
                "fabric_min_agents": 2,
                "fabric_max_agents": 5,
                "fabric_timeout_seconds": 60,
            }
        )
        assert rc.fabric_models == ["claude", "gpt-4"]
        assert rc.fabric_pool_id == "pool-1"
        assert rc.fabric_min_agents == 2
        assert rc.fabric_max_agents == 5
        assert rc.fabric_timeout_seconds == 60

    def test_implementers_and_critic(self):
        rc = self._parse({"implementers": ["claude"], "critic": "gpt-4", "reviser": "gemini"})
        assert rc.implementers == ["claude"]
        assert rc.critic == "gpt-4"
        assert rc.reviser == "gemini"

    def test_strategy_and_max_revisions(self):
        rc = self._parse({"strategy": "parallel", "max_revisions": 3})
        assert rc.strategy == "parallel"
        assert rc.max_revisions == 3

    def test_max_parallel(self):
        rc = self._parse({"max_parallel": 4})
        assert rc.max_parallel == 4

    def test_openclaw_session(self):
        rc = self._parse({"openclaw_session": {"token": "abc"}})
        assert rc.openclaw_session == {"token": "abc"}

    def test_thread_id_by_platform(self):
        rc = self._parse({"thread_id_by_platform": {"slack": "t-1"}})
        assert rc.thread_id_by_platform == {"slack": "t-1"}


# ---------------------------------------------------------------------------
# _check_execution_budget tests
# ---------------------------------------------------------------------------


class TestCheckExecutionBudget:
    """Tests for the module-level _check_execution_budget helper."""

    def _check(self, debate_id="d1", ctx=None):
        from aragora.server.handlers.debates.implementation import _check_execution_budget

        return _check_execution_budget(debate_id, ctx or {})

    def test_no_tracker_allows(self):
        ok, msg = self._check()
        assert ok is True
        assert msg == ""

    def test_allowed_budget(self):
        tracker = MagicMock()
        tracker.check_debate_budget.return_value = {"allowed": True}
        ok, msg = self._check(ctx={"cost_tracker": tracker})
        assert ok is True

    def test_exceeded_budget(self):
        tracker = MagicMock()
        tracker.check_debate_budget.return_value = {"allowed": False, "message": "Over limit"}
        ok, msg = self._check(ctx={"cost_tracker": tracker})
        assert ok is False
        assert msg == "Over limit"

    def test_exception_allows(self):
        tracker = MagicMock()
        tracker.check_debate_budget.side_effect = ValueError("bad")
        ok, msg = self._check(ctx={"cost_tracker": tracker})
        assert ok is True


# ---------------------------------------------------------------------------
# _serialize_approval tests
# ---------------------------------------------------------------------------


class TestSerializeApproval:
    def test_serializes_fields(self):
        from aragora.server.handlers.debates.implementation import _serialize_approval

        ar = _MockApprovalRequest()
        d = _serialize_approval(ar)
        assert d["id"] == "appr-001"
        assert d["title"] == "Implement debate d1"
        assert d["status"] == "pending"
        assert d["approved_by"] is None
        assert d["approved_at"] is None
        assert isinstance(d["requested_at"], str)

    def test_approved_at_present(self):
        from aragora.server.handlers.debates.implementation import _serialize_approval

        now = datetime.now(timezone.utc)
        ar = _MockApprovalRequest(
            status=ApprovalStatus.APPROVED,
            approved_by="admin",
            approved_at=now,
        )
        d = _serialize_approval(ar)
        assert d["approved_by"] == "admin"
        assert d["approved_at"] == now.isoformat()


# ---------------------------------------------------------------------------
# _persist_receipt tests
# ---------------------------------------------------------------------------


class TestPersistReceipt:
    @patch("aragora.server.handlers.debates.implementation.get_receipt_store")
    def test_success(self, mock_get):
        from aragora.server.handlers.debates.implementation import _persist_receipt

        store = MagicMock()
        store.save.return_value = "rcpt-saved"

        # patch the import inside the function
        with patch("aragora.storage.receipt_store.get_receipt_store", return_value=store):
            result = _persist_receipt(_MockReceipt(), "d1")

        assert result == "rcpt-saved"

    def test_import_error_returns_none(self):
        from aragora.server.handlers.debates.implementation import _persist_receipt

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            side_effect=ImportError("no module"),
        ):
            result = _persist_receipt(_MockReceipt(), "d1")
        assert result is None


# ---------------------------------------------------------------------------
# _persist_plan tests
# ---------------------------------------------------------------------------


class TestPersistPlan:
    def test_success(self):
        from aragora.server.handlers.debates.implementation import _persist_plan

        mock_factory = MagicMock()
        mock_decision_plan = MagicMock()
        mock_decision_plan.id = "plan-123"
        mock_decision_plan.metadata = {}
        mock_factory.from_implement_plan.return_value = mock_decision_plan
        with patch(
            "aragora.server.handlers.debates.implementation.DecisionPlanFactory",
            mock_factory,
            create=True,
        ):
            with (
                patch("aragora.pipeline.executor.store_plan") as mock_store,
                patch(
                    "aragora.server.decision_integrity_utils.ensure_decision_plan_backbone_run",
                    return_value="run-123",
                ),
                patch(
                    "aragora.server.decision_integrity_utils.sync_decision_plan_backbone_receipt",
                    return_value=True,
                ),
            ):
                with patch(
                    "aragora.pipeline.decision_plan.DecisionPlanFactory",
                    mock_factory,
                ):
                    _persist_plan(_MockPlan(), "d1")
                    mock_store.assert_called_once_with(mock_decision_plan)

    def test_import_error_silenced(self):
        from aragora.server.handlers.debates.implementation import _persist_plan

        with patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory",
            side_effect=ImportError("nope"),
        ):
            # Should not raise
            _persist_plan(_MockPlan(), "d1")


# ---------------------------------------------------------------------------
# _build_changes_list tests
# ---------------------------------------------------------------------------


class TestBuildChangesList:
    def test_none_plan(self):
        h = _make_handler()
        assert h._build_changes_list(None) == []

    def test_with_tasks(self):
        h = _make_handler()
        plan = _MockPlan(
            tasks=[
                _MockTask(id="t1", description="Do X", files=["a.py"], complexity="low"),
                _MockTask(id="t2", description="Do Y", files=["b.py"], complexity="high"),
            ]
        )
        changes = h._build_changes_list(plan)
        assert len(changes) == 2
        assert changes[0]["id"] == "t1"
        assert changes[1]["files"] == ["b.py"]


# ---------------------------------------------------------------------------
# _route_and_respond tests
# ---------------------------------------------------------------------------


class TestRouteAndRespond:
    def test_without_notify(self):
        h = _make_handler()
        result = h._route_and_respond({"key": "val"}, "d1", False)
        assert _status(result) == 200
        assert _body(result)["key"] == "val"

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.route_result")
    def test_with_notify(self, mock_route, mock_run_async):
        mock_run_async.return_value = None
        h = _make_handler()
        result = h._route_and_respond({"key": "val"}, "d1", True)
        assert _status(result) == 200
        mock_run_async.assert_called_once()

    @patch("aragora.server.handlers.debates.implementation.run_async", side_effect=ConnectionError)
    @patch("aragora.server.handlers.debates.implementation.route_result")
    def test_notify_error_still_returns_200(self, mock_route, mock_run_async):
        h = _make_handler()
        result = h._route_and_respond({"key": "val"}, "d1", True)
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# _check_execution_enabled tests
# ---------------------------------------------------------------------------


class TestCheckExecutionEnabled:
    def test_disabled_by_default(self):
        h = _make_handler()
        result = h._check_execution_enabled("d1")
        assert result is not None
        assert _status(result) == 403
        assert "disabled" in _body(result).get("error", "").lower()

    def test_enabled(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "1")
        h = _make_handler()
        result = h._check_execution_enabled("d1")
        assert result is None

    def test_budget_exceeded(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "1")
        tracker = MagicMock()
        tracker.check_debate_budget.return_value = {"allowed": False, "message": "No budget"}
        h = _make_handler(ctx_extra={"cost_tracker": tracker})
        result = h._check_execution_enabled("d1")
        assert result is not None
        assert _status(result) == 402


# ---------------------------------------------------------------------------
# _check_approval_permission tests
# ---------------------------------------------------------------------------


class TestCheckApprovalPermission:
    @patch("aragora.server.handlers.debates.implementation.get_permission_checker")
    def test_allowed(self, mock_checker_factory):
        checker = MagicMock()
        checker.check_permission.return_value = _MockPermissionDecision(True)
        mock_checker_factory.return_value = checker
        h = _make_handler()
        result = h._check_approval_permission(_mock_http_handler())
        assert result is None

    @patch("aragora.server.handlers.debates.implementation.get_permission_checker")
    def test_denied(self, mock_checker_factory):
        checker = MagicMock()
        checker.check_permission.return_value = _MockPermissionDecision(False)
        mock_checker_factory.return_value = checker
        h = _make_handler()
        result = h._check_approval_permission(_mock_http_handler())
        assert result is not None
        assert _status(result) == 403

    @patch(
        "aragora.server.handlers.debates.implementation.get_permission_checker",
        side_effect=ImportError,
    )
    def test_import_error_allows(self, _):
        h = _make_handler()
        result = h._check_approval_permission(_mock_http_handler())
        assert result is None


# ---------------------------------------------------------------------------
# _obsidian_writeback tests
# ---------------------------------------------------------------------------


class TestObsidianWriteback:
    def test_disabled_by_default(self):
        h = _make_handler()
        # Should not raise
        h._obsidian_writeback(_MockPackage(), None)

    def test_enabled_import_error(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_OBSIDIAN_WRITEBACK", "1")
        h = _make_handler()
        with patch(
            "aragora.connectors.knowledge.obsidian.ObsidianConfig",
            side_effect=ImportError("no module"),
        ):
            # Should not raise
            h._obsidian_writeback(_MockPackage(), "rcpt-1")

    @patch("aragora.server.handlers.debates.implementation.run_async")
    def test_enabled_with_config(self, mock_run_async, monkeypatch):
        monkeypatch.setenv("ARAGORA_OBSIDIAN_WRITEBACK", "1")
        mock_config = MagicMock()
        mock_connector = MagicMock()
        mock_run_async.return_value = None

        with patch("aragora.connectors.knowledge.obsidian.ObsidianConfig") as MockCfg:
            MockCfg.from_env.return_value = mock_config
            with patch(
                "aragora.connectors.knowledge.obsidian.ObsidianConnector",
                return_value=mock_connector,
            ):
                h = _make_handler()
                h._obsidian_writeback(_MockPackage(), "rcpt-1")
                # run_async called for the write
                assert mock_run_async.called

    @patch("aragora.server.handlers.debates.implementation.run_async")
    def test_enabled_no_config(self, mock_run_async, monkeypatch):
        monkeypatch.setenv("ARAGORA_OBSIDIAN_WRITEBACK", "1")
        with patch("aragora.connectors.knowledge.obsidian.ObsidianConfig") as MockCfg:
            MockCfg.from_env.return_value = None
            with patch("aragora.connectors.knowledge.obsidian.ObsidianConnector"):
                h = _make_handler()
                h._obsidian_writeback(_MockPackage(), None)
                # Should not call run_async for write since config is None
                mock_run_async.assert_not_called()


# ---------------------------------------------------------------------------
# _persist_artifacts tests
# ---------------------------------------------------------------------------


class TestPersistArtifacts:
    def _make_rc(self, **overrides):
        from aragora.server.handlers.debates.implementation import _parse_request

        return _parse_request(overrides, {})

    @patch("aragora.server.handlers.debates.implementation._persist_receipt", return_value="rcpt-1")
    @patch("aragora.server.handlers.debates.implementation._persist_plan")
    def test_receipt_and_plan_persisted(self, mock_plan, mock_receipt):
        h = _make_handler()
        rc = self._make_rc()
        payload: dict[str, Any] = {}
        receipt_id, cu_plan = h._persist_artifacts(_MockPackage(), "d1", rc, payload)
        assert receipt_id == "rcpt-1"
        assert cu_plan is None
        assert payload["receipt_id"] == "rcpt-1"
        mock_plan.assert_called_once()

    @patch("aragora.server.handlers.debates.implementation._persist_receipt", return_value=None)
    def test_receipt_persist_failure(self, mock_receipt):
        h = _make_handler()
        rc = self._make_rc()
        payload: dict[str, Any] = {}
        pkg = _MockPackage(plan=None)
        receipt_id, _ = h._persist_artifacts(pkg, "d1", rc, payload)
        assert receipt_id is None
        assert "receipt_id" not in payload

    def test_no_receipt(self):
        h = _make_handler()
        rc = self._make_rc()
        payload: dict[str, Any] = {}
        pkg = _MockPackage(receipt=None, plan=None)
        receipt_id, _ = h._persist_artifacts(pkg, "d1", rc, payload)
        assert receipt_id is None

    @patch("aragora.server.handlers.debates.implementation._persist_receipt", return_value=None)
    def test_computer_use_plan(self, _):
        h = _make_handler()
        rc = self._make_rc(execution_mode="computer_use")

        mock_dp = MagicMock()
        mock_dp.id = "plan-cu-1"
        with patch("aragora.pipeline.decision_plan.DecisionPlanFactory") as MockFactory:
            MockFactory.from_implement_plan.return_value = mock_dp
            with (
                patch("aragora.pipeline.executor.store_plan") as mock_store,
                patch(
                    "aragora.server.handlers.debates.implementation.ensure_decision_plan_backbone_run",
                    return_value="run-cu-1",
                ),
                patch(
                    "aragora.server.handlers.debates.implementation.sync_decision_plan_backbone_receipt",
                    return_value=True,
                ),
            ):
                payload: dict[str, Any] = {}
                receipt_id, cu_plan = h._persist_artifacts(_MockPackage(), "d1", rc, payload)
                assert payload["plan_id"] == "plan-cu-1"
                assert payload["run_id"] == "run-cu-1"
                assert cu_plan is mock_dp
                mock_store.assert_called_once_with(mock_dp)

    @patch("aragora.server.handlers.debates.implementation._persist_receipt", return_value=None)
    def test_workflow_mode_skips_plan(self, _):
        h = _make_handler()
        rc = self._make_rc(execution_mode="workflow")
        payload: dict[str, Any] = {}
        # Even with a plan, workflow_mode should skip _persist_plan
        with patch("aragora.server.handlers.debates.implementation._persist_plan") as mock_pp:
            h._persist_artifacts(_MockPackage(), "d1", rc, payload)
            mock_pp.assert_not_called()


# ---------------------------------------------------------------------------
# _append_review tests
# ---------------------------------------------------------------------------


class TestAppendReview:
    def test_review_off(self):
        h = _make_handler()
        executor = MagicMock()
        payload: dict[str, Any] = {"status": "completed"}
        # review_mode "off" should not be called from _execute_hybrid,
        # but calling _append_review directly with any mode
        h._append_review(executor, payload, "auto")
        assert "review" in payload

    def test_review_strict_not_approved(self):
        h = _make_handler()
        executor = MagicMock()
        executor.get_review_diff.return_value = "diff text"
        with patch("aragora.server.handlers.debates.implementation.run_async") as mock_ra:
            mock_ra.return_value = {"approved": False, "comments": "Bad code"}
            payload: dict[str, Any] = {"status": "completed"}
            h._append_review(executor, payload, "strict")
            assert payload["status"] == "review_failed"
            assert payload["review_passed"] is False

    def test_review_strict_approved(self):
        h = _make_handler()
        executor = MagicMock()
        executor.get_review_diff.return_value = "diff text"
        with patch("aragora.server.handlers.debates.implementation.run_async") as mock_ra:
            mock_ra.return_value = {"approved": True}
            payload: dict[str, Any] = {"status": "completed"}
            h._append_review(executor, payload, "strict")
            assert payload["status"] == "completed"
            assert payload["review_passed"] is True

    def test_review_error(self):
        h = _make_handler()
        executor = MagicMock()
        executor.get_review_diff.side_effect = RuntimeError("oops")
        payload: dict[str, Any] = {"status": "completed"}
        h._append_review(executor, payload, "auto")
        assert payload["review"]["error"] == "oops"
        assert payload["review_passed"] is None


# ---------------------------------------------------------------------------
# _build_integrity_package tests
# ---------------------------------------------------------------------------


class TestBuildIntegrityPackage:
    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.build_decision_integrity_package")
    def test_basic(self, mock_build, mock_run_async):
        pkg = _MockPackage()
        mock_run_async.return_value = pkg
        h = _make_handler()
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({}, {})
        result_pkg, payload = h._build_integrity_package(MagicMock(), "d1", rc)
        assert result_pkg is pkg
        assert "receipt" in payload

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.build_decision_integrity_package")
    def test_execute_mode_adds_fields(self, mock_build, mock_run_async):
        pkg = _MockPackage()
        mock_run_async.return_value = pkg
        h = _make_handler()
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"execution_mode": "execute"}, {})
        _, payload = h._build_integrity_package(MagicMock(), "d1", rc)
        assert payload["execution_mode"] == "execute"
        assert payload["execution_engine"] == "hybrid"

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.build_decision_integrity_package")
    def test_plan_only_no_engine(self, mock_build, mock_run_async):
        pkg = _MockPackage()
        mock_run_async.return_value = pkg
        h = _make_handler()
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({}, {})
        _, payload = h._build_integrity_package(MagicMock(), "d1", rc)
        # plan_only with no engine should NOT add execution_mode to payload
        assert "execution_mode" not in payload

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.build_decision_integrity_package")
    def test_include_context_loads_evidence(self, mock_build, mock_run_async):
        pkg = _MockPackage()
        mock_run_async.return_value = pkg
        h = _make_handler(ctx_extra={"continuum_memory": MagicMock()})
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"include_context": True}, {})
        with patch("aragora.evidence.store.EvidenceStore") as MockES:
            MockES.return_value = MagicMock()
            h._build_integrity_package(MagicMock(), "d1", rc)
            MockES.assert_called_once()


# ---------------------------------------------------------------------------
# Main endpoint: _create_decision_integrity tests
# ---------------------------------------------------------------------------


class TestCreateDecisionIntegrity:
    """Tests for the full POST /api/v1/debates/{id}/decision-integrity flow."""

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.build_decision_integrity_package")
    @patch("aragora.server.handlers.debates.implementation._persist_receipt", return_value="rcpt-1")
    @patch("aragora.server.handlers.debates.implementation._persist_plan")
    def test_plan_only_success(self, mock_pp, mock_pr, mock_build, mock_ra):
        storage = MagicMock()
        storage.get_debate.return_value = {"task": "Test", "status": "concluded"}
        pkg = _MockPackage()
        mock_ra.return_value = pkg

        h = _make_handler(storage=storage)
        handler = _mock_http_handler()
        result = h._create_decision_integrity(handler, "debate-001")

        assert _status(result) == 200
        body = _body(result)
        assert body.get("receipt_id") == "rcpt-1"

    def test_no_storage(self):
        h = _make_handler(storage=None)
        handler = _mock_http_handler()
        result = h._create_decision_integrity(handler, "debate-001")
        assert _status(result) == 503

    def test_debate_not_found(self):
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()
        result = h._create_decision_integrity(handler, "debate-001")
        assert _status(result) == 404

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.build_decision_integrity_package")
    @patch("aragora.server.handlers.debates.implementation._persist_receipt", return_value=None)
    @patch("aragora.server.handlers.debates.implementation._persist_plan")
    def test_receipt_persist_failure_still_200(self, mock_pp, mock_pr, mock_build, mock_ra):
        storage = MagicMock()
        storage.get_debate.return_value = {"task": "T", "status": "concluded"}
        mock_ra.return_value = _MockPackage()
        h = _make_handler(storage=storage)
        result = h._create_decision_integrity(_mock_http_handler(), "d1")
        assert _status(result) == 200
        assert "receipt_id" not in _body(result)


# ---------------------------------------------------------------------------
# Workflow mode tests
# ---------------------------------------------------------------------------


class TestHandleWorkflowMode:
    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.risk_register.RiskLevel")
    @patch("aragora.pipeline.decision_plan.ApprovalMode")
    def test_workflow_no_approval_needed(self, MockAM, MockRL, mock_store, MockFactory, mock_ra):
        from aragora.server.handlers.debates.implementation import _parse_request

        mock_plan = MagicMock()
        mock_plan.id = "plan-1"
        mock_plan.status = "approved"
        mock_plan.approval_mode = "risk_based"
        mock_plan.requires_human_approval = False
        mock_plan.to_dict.return_value = {"id": "plan-1"}
        MockFactory.from_debate_result.return_value = mock_plan

        mock_ra.return_value = mock_plan  # for coerce_debate_result

        storage = MagicMock()
        storage.get_debate.return_value = {"task": "T"}
        h = _make_handler(storage=storage)

        rc = _parse_request({"execution_mode": "workflow"}, {})
        handler = _mock_http_handler()

        with patch(
            "aragora.server.handlers.debates.implementation.coerce_debate_result",
            return_value=MagicMock(),
        ):
            with (
                patch(
                    "aragora.server.handlers.debates.implementation.ensure_decision_plan_backbone_run",
                    return_value="run-1",
                ),
                patch(
                    "aragora.server.handlers.debates.implementation.sync_decision_plan_backbone_receipt",
                    return_value=True,
                ),
            ):
                result = h._handle_workflow_mode(
                    handler, {"task": "T"}, "d1", _MockPackage(), rc, {}
                )

        assert _status(result) == 200
        body = _body(result)
        assert "plan_id" in body
        assert body["plan_id"] == "plan-1"

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.executor.PlanExecutor")
    def test_workflow_execute_approved(self, MockPE, mock_store, MockFactory, mock_ra, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "1")
        from aragora.server.handlers.debates.implementation import _parse_request

        mock_plan = MagicMock()
        mock_plan.id = "plan-1"
        mock_plan.status = "approved"
        mock_plan.approval_mode = "risk_based"
        mock_plan.requires_human_approval = False
        mock_plan.is_approved = True
        mock_plan.to_dict.return_value = {"id": "plan-1"}
        MockFactory.from_debate_result.return_value = mock_plan

        outcome = _MockOutcome()
        mock_executor_inst = MagicMock()
        MockPE.return_value = mock_executor_inst

        launch = {
            "run_id": "run-1",
            "execution_id": "exec-1",
            "correlation_id": "corr-1",
        }

        def side_effect(coro):
            if hasattr(coro, "close"):
                coro.close()
            return launch, outcome

        mock_ra.side_effect = side_effect

        rc = _parse_request({"execution_mode": "execute_workflow"}, {})
        h = _make_handler(storage=MagicMock())

        with patch(
            "aragora.server.handlers.debates.implementation.coerce_debate_result",
            return_value=MagicMock(),
        ):
            with (
                patch("aragora.pipeline.risk_register.RiskLevel", MagicMock()),
                patch("aragora.pipeline.decision_plan.ApprovalMode", MagicMock()),
                patch(
                    "aragora.server.handlers.debates.implementation.ensure_decision_plan_backbone_run",
                    return_value="run-1",
                ),
                patch(
                    "aragora.server.handlers.debates.implementation.sync_decision_plan_backbone_receipt",
                    return_value=True,
                ),
            ):
                result = h._handle_workflow_mode(
                    _mock_http_handler(), {}, "d1", _MockPackage(), rc, {}
                )

        assert _status(result) == 200
        body = _body(result)
        assert "workflow_execution" in body
        assert body["workflow_execution"]["status"] == "completed"

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch("aragora.pipeline.executor.store_plan")
    def test_workflow_execute_pending_approval(self, mock_store, MockFactory, mock_ra, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "1")
        from aragora.server.handlers.debates.implementation import _parse_request

        mock_plan = MagicMock()
        mock_plan.id = "plan-1"
        mock_plan.status = "awaiting_approval"
        mock_plan.approval_mode = "always"
        mock_plan.requires_human_approval = True
        mock_plan.is_approved = False
        mock_plan.highest_risk_level.value = "high"
        mock_plan.to_dict.return_value = {"id": "plan-1"}
        mock_plan.implement_plan = _MockPlan()
        MockFactory.from_debate_result.return_value = mock_plan

        approval_req = _MockApprovalRequest(status=ApprovalStatus.PENDING)

        def approval_side_effect(coro):
            if hasattr(coro, "close"):
                coro.close()
            return approval_req

        mock_ra.side_effect = approval_side_effect

        rc = _parse_request({"execution_mode": "execute_workflow"}, {})
        h = _make_handler(storage=MagicMock())

        with patch(
            "aragora.server.handlers.debates.implementation.coerce_debate_result",
            return_value=MagicMock(),
        ):
            with patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow"
            ) as mock_gaf:
                mock_flow = MagicMock()
                mock_flow.request_approval = AsyncMock(return_value=approval_req)
                mock_gaf.return_value = mock_flow
                with (
                    patch("aragora.pipeline.risk_register.RiskLevel", MagicMock()),
                    patch("aragora.pipeline.decision_plan.ApprovalMode", MagicMock()),
                    patch(
                        "aragora.server.handlers.debates.implementation.ensure_decision_plan_backbone_run",
                        return_value="run-1",
                    ),
                    patch(
                        "aragora.server.handlers.debates.implementation.sync_decision_plan_backbone_receipt",
                        return_value=True,
                    ),
                    patch(
                        "aragora.server.handlers.debates.implementation.get_permission_checker"
                    ) as mock_pc,
                ):
                    checker = MagicMock()
                    checker.check_permission.return_value = _MockPermissionDecision(True)
                    mock_pc.return_value = checker
                    result = h._handle_workflow_mode(
                        _mock_http_handler(), {}, "d1", _MockPackage(), rc, {}
                    )

        assert _status(result) == 200
        body = _body(result)
        assert "workflow_execution" in body
        assert body["workflow_execution"]["status"] == "pending_approval"


# ---------------------------------------------------------------------------
# _handle_approval_execution tests
# ---------------------------------------------------------------------------


class TestHandleApprovalExecution:
    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.get_approval_flow")
    @patch("aragora.server.handlers.debates.implementation.get_permission_checker")
    def test_request_approval_mode(self, mock_pc, mock_gaf, mock_ra):
        from aragora.server.handlers.debates.implementation import _parse_request

        checker = MagicMock()
        checker.check_permission.return_value = _MockPermissionDecision(True)
        mock_pc.return_value = checker

        approval_req = _MockApprovalRequest(status=ApprovalStatus.PENDING)
        mock_ra.return_value = approval_req

        mock_flow = MagicMock()
        mock_gaf.return_value = mock_flow

        rc = _parse_request({"execution_mode": "request_approval"}, {})
        h = _make_handler(storage=MagicMock())
        result = h._handle_approval_execution(
            _mock_http_handler(), "d1", _MockPackage(), rc, {}, None
        )
        assert _status(result) == 200
        body = _body(result)
        assert "approval" in body

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.get_approval_flow")
    @patch("aragora.server.handlers.debates.implementation.get_permission_checker")
    def test_permission_denied(self, mock_pc, mock_gaf, mock_ra):
        from aragora.server.handlers.debates.implementation import _parse_request

        checker = MagicMock()
        checker.check_permission.return_value = _MockPermissionDecision(False)
        mock_pc.return_value = checker

        rc = _parse_request({"execution_mode": "request_approval"}, {})
        h = _make_handler(storage=MagicMock())
        result = h._handle_approval_execution(
            _mock_http_handler(), "d1", _MockPackage(), rc, {}, None
        )
        assert _status(result) == 403


# ---------------------------------------------------------------------------
# _execute_direct tests
# ---------------------------------------------------------------------------


class TestExecuteDirect:
    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.HybridExecutor")
    @patch("aragora.server.handlers.debates.implementation.ExecutionNotifier")
    def test_hybrid_engine(self, MockNotifier, MockHE, mock_ra, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "1")
        from aragora.server.handlers.debates.implementation import _parse_request

        mock_results = [_MockTaskResult()]
        mock_ra.return_value = mock_results

        notifier_inst = MagicMock()
        notifier_inst.progress = _MockProgress()
        MockNotifier.return_value = notifier_inst

        approval = _MockApprovalRequest(status=ApprovalStatus.APPROVED)
        rc = _parse_request({"execution_mode": "execute"}, {})
        h = _make_handler(storage=MagicMock())
        payload: dict[str, Any] = {}
        result = h._execute_direct("d1", _MockPackage(), rc, payload, approval, "user-1", None)

        # None means success (no error)
        assert result is None
        assert "execution" in payload
        assert payload["execution"]["status"] == "completed"

    def test_execution_disabled(self):
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"execution_mode": "execute"}, {})
        h = _make_handler(storage=MagicMock())
        approval = _MockApprovalRequest(status=ApprovalStatus.APPROVED)
        result = h._execute_direct("d1", _MockPackage(), rc, {}, approval, "user", None)
        assert result is not None
        assert _status(result) == 403

    def test_pending_approval(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "1")
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"execution_mode": "execute"}, {})
        h = _make_handler(storage=MagicMock())
        approval = _MockApprovalRequest(status=ApprovalStatus.PENDING)
        payload: dict[str, Any] = {}
        result = h._execute_direct("d1", _MockPackage(), rc, payload, approval, "user", None)
        assert result is None  # no error, just pending
        assert payload["execution"]["status"] == "pending_approval"

    def test_no_plan(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "1")
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"execution_mode": "execute"}, {})
        h = _make_handler(storage=MagicMock())
        approval = _MockApprovalRequest(status=ApprovalStatus.APPROVED)
        pkg = _MockPackage(plan=None)
        result = h._execute_direct("d1", pkg, rc, {}, approval, "user", None)
        assert _status(result) == 400

    def test_invalid_engine_defaults_to_hybrid(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "1")
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"execution_mode": "execute", "execution_engine": "unknown"}, {})

        approval = _MockApprovalRequest(status=ApprovalStatus.APPROVED)
        h = _make_handler(storage=MagicMock())
        payload: dict[str, Any] = {}
        with patch.object(h, "_execute_hybrid") as mock_eh:
            h._execute_direct("d1", _MockPackage(), rc, payload, approval, "user", None)
            mock_eh.assert_called_once()


# ---------------------------------------------------------------------------
# _execute_hybrid tests
# ---------------------------------------------------------------------------


class TestExecuteHybrid:
    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.HybridExecutor")
    @patch("aragora.server.handlers.debates.implementation.ExecutionNotifier")
    def test_sequential(self, MockNotifier, MockHE, mock_ra):
        from aragora.server.handlers.debates.implementation import _parse_request

        results = [_MockTaskResult()]
        mock_ra.return_value = results

        notifier_inst = MagicMock()
        notifier_inst.progress = _MockProgress()
        MockNotifier.return_value = notifier_inst

        executor = MagicMock()
        MockHE.return_value = executor

        rc = _parse_request({}, {})
        h = _make_handler()
        payload: dict[str, Any] = {}
        h._execute_hybrid("d1", _MockPackage(), rc, payload)
        assert payload["execution"]["status"] == "completed"
        assert len(payload["execution"]["results"]) == 1

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.HybridExecutor")
    @patch("aragora.server.handlers.debates.implementation.ExecutionNotifier")
    def test_parallel(self, MockNotifier, MockHE, mock_ra):
        from aragora.server.handlers.debates.implementation import _parse_request

        results = [_MockTaskResult(), _MockTaskResult()]
        mock_ra.return_value = results

        notifier_inst = MagicMock()
        notifier_inst.progress = _MockProgress()
        MockNotifier.return_value = notifier_inst

        rc = _parse_request({"parallel_execution": True}, {})
        h = _make_handler()
        payload: dict[str, Any] = {}
        h._execute_hybrid("d1", _MockPackage(), rc, payload)
        assert payload["execution"]["status"] == "completed"

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.HybridExecutor")
    @patch("aragora.server.handlers.debates.implementation.ExecutionNotifier")
    def test_with_review(self, MockNotifier, MockHE, mock_ra, monkeypatch):
        monkeypatch.setenv("ARAGORA_IMPLEMENTATION_REVIEW_MODE", "auto")
        from aragora.server.handlers.debates.implementation import _parse_request

        results = [_MockTaskResult()]

        call_count = [0]

        def _mock_run_async(coro):
            call_count[0] += 1
            if call_count[0] <= 1:
                return results
            return {"approved": True}

        mock_ra.side_effect = _mock_run_async

        notifier_inst = MagicMock()
        notifier_inst.progress = _MockProgress()
        MockNotifier.return_value = notifier_inst

        executor = MagicMock()
        executor.get_review_diff.return_value = "diff"
        MockHE.return_value = executor

        rc = _parse_request({}, {})
        h = _make_handler()
        payload: dict[str, Any] = {}
        h._execute_hybrid("d1", _MockPackage(), rc, payload)
        assert "review" in payload["execution"]

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.HybridExecutor")
    @patch("aragora.server.handlers.debates.implementation.ExecutionNotifier")
    def test_notify_origin(self, MockNotifier, MockHE, mock_ra):
        from aragora.server.handlers.debates.implementation import _parse_request

        results = [_MockTaskResult()]
        mock_ra.return_value = results

        notifier_inst = MagicMock()
        notifier_inst.progress = _MockProgress()
        MockNotifier.return_value = notifier_inst

        rc = _parse_request({"notify_origin": True}, {})
        h = _make_handler()
        payload: dict[str, Any] = {}
        h._execute_hybrid("d1", _MockPackage(), rc, payload)
        # run_async called for: execute_plan + send_completion_summary
        assert mock_ra.call_count >= 2


# ---------------------------------------------------------------------------
# _execute_fabric tests
# ---------------------------------------------------------------------------


class TestExecuteFabric:
    @patch("aragora.server.handlers.debates.implementation.run_async")
    def test_success(self, mock_ra):
        from aragora.server.handlers.debates.implementation import _parse_request

        results = [_MockTaskResult()]
        mock_ra.return_value = results

        rc = _parse_request({}, {})
        h = _make_handler()
        payload: dict[str, Any] = {}

        with patch("aragora.fabric.AgentFabric"):
            with patch("aragora.implement.fabric_integration.FabricImplementationRunner"):
                with patch("aragora.implement.fabric_integration.FabricImplementationConfig"):
                    h._execute_fabric("d1", _MockPackage(), rc, payload)

        assert payload["execution"]["status"] == "completed"
        assert payload["execution"]["mode"] == "fabric"

    @patch(
        "aragora.server.handlers.debates.implementation.run_async",
        side_effect=ImportError("no fabric"),
    )
    def test_import_error(self, mock_ra):
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({}, {})
        h = _make_handler()
        payload: dict[str, Any] = {}
        h._execute_fabric("d1", _MockPackage(), rc, payload)
        assert payload["execution"]["status"] == "failed"
        assert payload["execution"]["mode"] == "fabric"


# ---------------------------------------------------------------------------
# _execute_computer_use tests
# ---------------------------------------------------------------------------


class TestExecuteComputerUse:
    def test_no_plan(self):
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"execution_mode": "computer_use"}, {})
        h = _make_handler()
        payload: dict[str, Any] = {}
        approval = _MockApprovalRequest()
        h._execute_computer_use(rc, payload, approval, "user", None)
        assert payload["execution"]["status"] == "failed"
        assert "No execution plan" in payload["execution"]["error"]

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.pipeline.executor.PlanExecutor")
    @patch("aragora.pipeline.executor.store_plan")
    def test_success(self, mock_store, MockPE, mock_ra):
        from aragora.server.handlers.debates.implementation import _parse_request

        outcome = _MockOutcome()

        def _mock_run_async(coro):
            if hasattr(coro, "close"):
                coro.close()
            return (
                {
                    "run_id": "run-1",
                    "execution_id": "exec-1",
                    "correlation_id": "corr-1",
                },
                outcome,
            )

        mock_ra.side_effect = _mock_run_async

        mock_executor = MagicMock()
        MockPE.return_value = mock_executor

        cu_plan = MagicMock()
        cu_plan.approve = MagicMock()

        rc = _parse_request({"execution_mode": "computer_use"}, {})
        h = _make_handler()
        payload: dict[str, Any] = {}
        approval = _MockApprovalRequest(status=ApprovalStatus.APPROVED, approved_by="admin")
        with patch(
            "aragora.server.handlers.debates.implementation.sync_decision_plan_backbone_receipt",
            return_value=True,
        ):
            h._execute_computer_use(rc, payload, approval, "user", cu_plan)
        assert payload["execution"]["status"] == "completed"
        assert payload["execution"]["mode"] == "computer_use"
        cu_plan.approve.assert_called_once()

    def test_import_error(self):
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"execution_mode": "computer_use"}, {})
        h = _make_handler()
        payload: dict[str, Any] = {}
        cu_plan = MagicMock()
        cu_plan.approve.side_effect = ImportError("no module")
        approval = _MockApprovalRequest()

        with patch("aragora.pipeline.executor.PlanExecutor", side_effect=ImportError):
            h._execute_computer_use(rc, payload, approval, "user", cu_plan)
        assert payload["execution"]["status"] == "failed"


# ---------------------------------------------------------------------------
# get_receipt_store compatibility shim tests
# ---------------------------------------------------------------------------


class TestGetReceiptStore:
    def test_none_raises(self):
        from aragora.server.handlers.debates.implementation import get_receipt_store

        with patch("aragora.server.handlers.debates.implementation._receipt_store_get", None):
            with pytest.raises(RuntimeError, match="unavailable"):
                get_receipt_store()

    def test_delegates(self):
        from aragora.server.handlers.debates.implementation import get_receipt_store

        mock_getter = MagicMock(return_value="store-obj")
        with patch(
            "aragora.server.handlers.debates.implementation._receipt_store_get", mock_getter
        ):
            assert get_receipt_store() == "store-obj"


# ---------------------------------------------------------------------------
# Full integration through handle() dispatch
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("org_scoped_request_user")
class TestHandleDispatch:
    """Test that the handler.handle() method correctly dispatches decision-integrity."""

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.build_decision_integrity_package")
    @patch("aragora.server.handlers.debates.implementation._persist_receipt", return_value="r1")
    @patch("aragora.server.handlers.debates.implementation._persist_plan")
    def test_dispatch_via_handle(self, mock_pp, mock_pr, mock_build, mock_ra):
        from aragora.server.handlers.debates.handler import DebatesHandler

        storage = MagicMock()
        storage.get_debate.return_value = {"task": "T", "status": "concluded"}
        storage.is_public.return_value = False
        storage.get_access_info.return_value = ("debate-001", "test-org-001", False)

        pkg = _MockPackage()
        mock_ra.return_value = pkg

        handler_obj = DebatesHandler(server_context={"storage": storage})
        http_handler = _mock_http_handler(command="POST")

        with patch.object(handler_obj, "read_json_body", return_value={}):
            with patch("aragora.server.auth.auth_config") as mock_auth:
                mock_auth.enabled = False
                result = handler_obj.handle(
                    "/api/v1/debates/debate-001/decision-integrity", {}, http_handler
                )

        assert _status(result) == 200

    def test_dispatch_method_not_allowed(self):
        from aragora.server.handlers.debates.handler import DebatesHandler

        storage = MagicMock()
        storage.get_access_info.return_value = ("debate-001", "test-org-001", False)
        handler_obj = DebatesHandler(server_context={"storage": storage})
        http_handler = _mock_http_handler(command="GET")

        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = False
            result = handler_obj.handle(
                "/api/v1/debates/debate-001/decision-integrity", {}, http_handler
            )

        assert _status(result) == 405


# ---------------------------------------------------------------------------
# Edge cases and error paths
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_parse_request_execution_mode_case_insensitive(self):
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"execution_mode": "EXECUTE"}, {})
        assert rc.execution_mode == "execute"

    def test_parse_request_execution_engine_case_insensitive(self):
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"execution_engine": "FABRIC"}, {})
        assert rc.execution_engine == "fabric"

    def test_build_changes_list_empty_tasks(self):
        h = _make_handler()
        plan = _MockPlan(tasks=[])
        assert h._build_changes_list(plan) == []

    @patch("aragora.server.handlers.debates.implementation.run_async")
    @patch("aragora.server.handlers.debates.implementation.build_decision_integrity_package")
    @patch("aragora.server.handlers.debates.implementation._persist_receipt", return_value=None)
    @patch("aragora.server.handlers.debates.implementation._persist_plan")
    def test_empty_payload(self, mock_pp, mock_pr, mock_build, mock_ra):
        """Empty JSON body should use defaults."""
        storage = MagicMock()
        storage.get_debate.return_value = {"task": "T"}
        pkg = _MockPackage(receipt=None, plan=None)
        mock_ra.return_value = pkg

        h = _make_handler(storage=storage, json_body={})
        result = h._create_decision_integrity(_mock_http_handler(), "d1")
        assert _status(result) == 200

    def test_persist_artifacts_computer_use_type_error(self):
        h = _make_handler()
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({"execution_mode": "computer_use"}, {})
        payload: dict[str, Any] = {}

        with patch("aragora.pipeline.decision_plan.DecisionPlanFactory") as MockFactory:
            MockFactory.from_implement_plan.side_effect = TypeError("bad plan")
            with patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ):
                _, cu_plan = h._persist_artifacts(_MockPackage(), "d1", rc, payload)
        assert cu_plan is None
        assert "plan_id" not in payload

    def test_route_and_respond_notify_timeout_error(self):
        h = _make_handler()
        with patch(
            "aragora.server.handlers.debates.implementation.run_async",
            side_effect=TimeoutError("timeout"),
        ):
            result = h._route_and_respond({"key": "val"}, "d1", True)
        assert _status(result) == 200

    def test_route_and_respond_notify_value_error(self):
        h = _make_handler()
        with patch(
            "aragora.server.handlers.debates.implementation.run_async",
            side_effect=ValueError("bad"),
        ):
            result = h._route_and_respond({"key": "val"}, "d1", True)
        assert _status(result) == 200

    def test_check_execution_budget_default_message(self):
        from aragora.server.handlers.debates.implementation import _check_execution_budget

        tracker = MagicMock()
        tracker.check_debate_budget.return_value = {"allowed": False}
        ok, msg = _check_execution_budget("d1", {"cost_tracker": tracker})
        assert ok is False
        assert msg == "Budget exceeded"

    @patch("aragora.server.handlers.debates.implementation._persist_receipt", return_value=None)
    @patch("aragora.server.handlers.debates.implementation._persist_plan")
    def test_persist_artifacts_no_plan(self, mock_pp, mock_pr):
        h = _make_handler()
        from aragora.server.handlers.debates.implementation import _parse_request

        rc = _parse_request({}, {})
        payload: dict[str, Any] = {}
        pkg = _MockPackage(plan=None)
        _, cu = h._persist_artifacts(pkg, "d1", rc, payload)
        assert cu is None
        mock_pp.assert_not_called()

    def test_append_review_max_chars_from_env(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_IMPLEMENTATION_REVIEW_MAX_CHARS", "500")
        monkeypatch.setenv("ARAGORA_IMPLEMENTATION_REVIEW_TIMEOUT", "60")
        h = _make_handler()
        executor = MagicMock()
        executor.get_review_diff.return_value = "diff"
        with patch("aragora.server.handlers.debates.implementation.run_async") as mock_ra:
            mock_ra.return_value = {"approved": True}
            payload: dict[str, Any] = {}
            h._append_review(executor, payload, "auto")
            executor.get_review_diff.assert_called_once_with(max_chars=500)

    def test_serialize_approval_rejection(self):
        from aragora.server.handlers.debates.implementation import _serialize_approval

        ar = _MockApprovalRequest(
            status=ApprovalStatus.REJECTED,
            rejection_reason="Too risky",
        )
        d = _serialize_approval(ar)
        assert d["status"] == "rejected"
        assert d["rejection_reason"] == "Too risky"
