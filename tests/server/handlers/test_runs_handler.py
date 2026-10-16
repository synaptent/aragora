"""Tests for backbone run ledger handlers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from aragora.pipeline.backbone_contracts import BackboneStage, RunLedger, RunStageEvent
from aragora.pipeline.execution_mode import ExecutionMode
from aragora.pipeline.plan_store import PlanStore
from aragora.server.handlers.runs import RunsHandler, handle_run_detail, handle_runs_list


_ORG = "org-a"
_OTHER_ORG = "org-b"
_NOT_FOUND = {"error": "Run not found", "code": "not_found"}


def _parse(result: Any) -> dict[str, Any]:
    """Normalize a HandlerResult into a simple dict."""
    if hasattr(result, "to_dict"):
        return result.to_dict()
    raise AssertionError("Expected HandlerResult-compatible response")


def _make_run(
    run_id: str,
    *,
    status: str,
    execution_id: str = "",
    receipt_id: str = "",
    safety_mode: str | None = None,
    stage_events: list[RunStageEvent] | None = None,
) -> RunLedger:
    """Build a test RunLedger."""
    run = RunLedger(
        run_id=run_id,
        entrypoint="prompt_engine.run",
        status=status,
        execution_id=execution_id,
        receipt_id=receipt_id,
        metadata={"safety_mode": safety_mode} if safety_mode else {},
    )
    for event in stage_events or []:
        run.add_event(event)
    return run


def _make_http_handler() -> Any:
    handler = MagicMock()
    handler.command = "GET"
    handler.headers = {}
    handler.user_store = None
    return handler


def _assert_stage_payload(
    actual: list[dict[str, Any]],
    expected: list[tuple[str, str]],
) -> None:
    assert [(stage["stage"], stage["status"]) for stage in actual] == expected
    for stage in actual:
        assert isinstance(stage.get("event_id"), str)
        assert "created_at" in stage
        assert stage.get("artifact_ref") == ""
        assert stage.get("details") == {}


@pytest.fixture(autouse=True)
def isolated_plan_store(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> PlanStore:
    store = PlanStore(db_path=str(tmp_path / "runs_handler.db"))
    monkeypatch.setattr("aragora.pipeline.plan_store.get_plan_store", lambda: store)
    return store


@pytest.fixture
def authorized_http_handler(monkeypatch: pytest.MonkeyPatch) -> Any:
    from aragora.server.handlers.utils import decorators as handler_decorators

    auth_ctx = MagicMock()
    auth_ctx.is_authenticated = True
    auth_ctx.user_id = "runs-reader"
    auth_ctx.org_id = _ORG
    auth_ctx.role = "admin"
    auth_ctx.error_reason = None

    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request",
        lambda handler, user_store=None: auth_ctx,
    )
    monkeypatch.setattr(
        handler_decorators,
        "has_permission",
        lambda role, permission: permission == "orchestration:read",
    )
    return _make_http_handler()


def test_handle_runs_list_returns_compact_backbone_payload(
    isolated_plan_store: PlanStore,
) -> None:
    run = _make_run(
        "run-001",
        status="plan_ready",
        execution_id="exec-001",
        receipt_id="receipt-001",
        safety_mode=ExecutionMode.INTERACTIVE.value,
        stage_events=[
            RunStageEvent.create(BackboneStage.INTAKE, status="received"),
            RunStageEvent.create(BackboneStage.PLAN, status="completed"),
        ],
    )
    isolated_plan_store.create_run(run, org_id=_ORG, created_by="runs-reader")

    result = handle_runs_list(
        {"status": "plan_ready", "limit": "10", "offset": "0"},
        org_id=_ORG,
    )
    parsed = _parse(result)

    assert parsed["status"] == 200
    assert len(parsed["body"]["runs"]) == 1
    payload = parsed["body"]["runs"][0]
    assert payload["run_id"] == "run-001"
    assert payload["status"] == "plan_ready"
    assert payload["execution_id"] == "exec-001"
    assert payload["receipt_id"] == "receipt-001"
    assert payload["safety_mode"] == ExecutionMode.INTERACTIVE.value
    _assert_stage_payload(
        payload["stages"],
        [
            (BackboneStage.INTAKE.value, "received"),
            (BackboneStage.PLAN.value, "completed"),
        ],
    )
    assert payload["stage_timeline"] == payload["stages"]


def test_handle_runs_list_excludes_other_org_and_unowned_runs(
    isolated_plan_store: PlanStore,
) -> None:
    isolated_plan_store.create_run(_make_run("run-mine", status="plan_ready"), org_id=_ORG)
    isolated_plan_store.create_run(_make_run("run-theirs", status="plan_ready"), org_id=_OTHER_ORG)
    isolated_plan_store.create_run(_make_run("run-unowned", status="plan_ready"))

    mine = _parse(handle_runs_list({}, org_id=_ORG))
    theirs = _parse(handle_runs_list({}, org_id=_OTHER_ORG))

    assert [run["run_id"] for run in mine["body"]["runs"]] == ["run-mine"]
    assert [run["run_id"] for run in theirs["body"]["runs"]] == ["run-theirs"]


def test_handle_runs_list_uses_org_scoped_lister() -> None:
    run = _make_run(
        "run-compat",
        status="receipt_ready",
        stage_events=[RunStageEvent.create(BackboneStage.RECEIPT, status="completed")],
    )

    class _ScopedStore:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None, int, int]] = []

        def list_runs_for_org(
            self,
            org_id: str,
            *,
            status: str | None = None,
            limit: int = 50,
            offset: int = 0,
        ) -> list[RunLedger]:
            self.calls.append((org_id, status, limit, offset))
            return [run]

    store = _ScopedStore()

    result = handle_runs_list(
        {"status": "receipt_ready", "limit": "5", "offset": "2"}, org_id=_ORG, store=store
    )
    parsed = _parse(result)

    assert parsed["status"] == 200
    assert store.calls == [(_ORG, "receipt_ready", 5, 2)]
    assert parsed["body"]["runs"][0]["run_id"] == "run-compat"
    _assert_stage_payload(
        parsed["body"]["runs"][0]["stages"],
        [(BackboneStage.RECEIPT.value, "completed")],
    )
    assert parsed["body"]["runs"][0]["stage_timeline"] == parsed["body"]["runs"][0]["stages"]


def test_handle_runs_list_store_without_org_reads_lists_nothing() -> None:
    class _UnscopedStore:
        def list_runs(self, **_: Any) -> list[RunLedger]:
            return [_make_run("run-any", status="plan_ready")]

    parsed = _parse(handle_runs_list({}, org_id=_ORG, store=_UnscopedStore()))

    assert parsed["status"] == 200
    assert parsed["body"]["runs"] == []


def test_handle_run_detail_uses_org_scoped_getter() -> None:
    run = _make_run(
        "run-detail",
        status="execution_started",
        execution_id="exec-detail",
        safety_mode=ExecutionMode.AUTONOMOUS.value,
        stage_events=[RunStageEvent.create(BackboneStage.EXECUTION, status="running")],
    )

    class _ScopedStore:
        def __init__(self) -> None:
            self.seen: list[tuple[str, str]] = []

        def get_run_for_org(self, run_id: str, org_id: str) -> RunLedger | None:
            self.seen.append((run_id, org_id))
            return run if run_id == "run-detail" else None

    store = _ScopedStore()
    result = handle_run_detail("run-detail", org_id=_ORG, store=store)
    parsed = _parse(result)

    assert parsed["status"] == 200
    assert store.seen == [("run-detail", _ORG)]
    payload = parsed["body"]["run"]
    assert payload["run_id"] == "run-detail"
    assert payload["status"] == "execution_started"
    assert payload["execution_id"] == "exec-detail"
    assert payload["receipt_id"] is None
    assert payload["safety_mode"] == ExecutionMode.AUTONOMOUS.value
    _assert_stage_payload(
        payload["stages"],
        [(BackboneStage.EXECUTION.value, "running")],
    )
    assert payload["stage_timeline"] == payload["stages"]


def test_handle_run_detail_returns_404_when_missing() -> None:
    class _MissingStore:
        def get_run_for_org(self, run_id: str, org_id: str) -> None:
            return None

    result = handle_run_detail("missing-run", org_id=_ORG, store=_MissingStore())
    parsed = _parse(result)

    assert parsed["status"] == 404
    assert parsed["body"] == _NOT_FOUND


def test_handle_run_detail_hides_other_org_and_unowned_runs(
    isolated_plan_store: PlanStore,
) -> None:
    isolated_plan_store.create_run(_make_run("run-theirs", status="plan_ready"), org_id=_OTHER_ORG)
    isolated_plan_store.create_run(_make_run("run-unowned", status="plan_ready"))

    missing = _parse(handle_run_detail("run-missing", org_id=_ORG))
    for run_id in ("run-theirs", "run-unowned"):
        parsed = _parse(handle_run_detail(run_id, org_id=_ORG))
        assert parsed["status"] == 404
        assert parsed["body"] == missing["body"] == _NOT_FOUND


def test_runs_handler_routes_list_requests(
    isolated_plan_store: PlanStore,
    authorized_http_handler: Any,
) -> None:
    run = _make_run(
        "run-handler-list",
        status="plan_ready",
        stage_events=[RunStageEvent.create(BackboneStage.PLAN, status="completed")],
    )
    isolated_plan_store.create_run(run, org_id=_ORG)
    isolated_plan_store.create_run(
        _make_run("run-handler-other", status="plan_ready"), org_id=_OTHER_ORG
    )

    result = RunsHandler({"plan_store": isolated_plan_store}).handle(
        "/api/runs",
        {},
        authorized_http_handler,
    )
    parsed = _parse(result)

    assert parsed["status"] == 200
    assert [r["run_id"] for r in parsed["body"]["runs"]] == ["run-handler-list"]


def test_runs_handler_routes_detail_requests(
    isolated_plan_store: PlanStore,
    authorized_http_handler: Any,
) -> None:
    run = _make_run(
        "run-handler-detail",
        status="execution_started",
        stage_events=[RunStageEvent.create(BackboneStage.EXECUTION, status="running")],
    )
    isolated_plan_store.create_run(run, org_id=_ORG)

    result = RunsHandler({"plan_store": isolated_plan_store}).handle(
        "/api/runs/run-handler-detail",
        {},
        authorized_http_handler,
    )
    parsed = _parse(result)

    assert parsed["status"] == 200
    assert parsed["body"]["run"]["run_id"] == "run-handler-detail"


def test_runs_handler_other_org_run_is_not_found(
    isolated_plan_store: PlanStore,
    authorized_http_handler: Any,
) -> None:
    isolated_plan_store.create_run(
        _make_run("run-handler-other", status="plan_ready"), org_id=_OTHER_ORG
    )
    handler = RunsHandler({"plan_store": isolated_plan_store})

    other = _parse(handler.handle("/api/runs/run-handler-other", {}, authorized_http_handler))
    missing = _parse(handler.handle("/api/runs/run-handler-missing", {}, authorized_http_handler))

    assert other["status"] == missing["status"] == 404
    assert other["body"] == missing["body"] == _NOT_FOUND


def test_runs_handler_requires_org(
    isolated_plan_store: PlanStore,
    authorized_http_handler: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_org = MagicMock()
    no_org.is_authenticated = True
    no_org.user_id = "runs-reader"
    no_org.org_id = None
    no_org.role = "admin"
    no_org.error_reason = None
    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request",
        lambda handler, user_store=None: no_org,
    )

    result = RunsHandler({"plan_store": isolated_plan_store}).handle(
        "/api/runs",
        {},
        authorized_http_handler,
    )
    parsed = _parse(result)

    assert parsed["status"] == 403
    assert parsed["body"]["code"] == "org_required"


def test_runs_handler_requires_auth(
    isolated_plan_store: PlanStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aragora.server.handlers.utils import decorators as handler_decorators

    unauthenticated = MagicMock()
    unauthenticated.is_authenticated = False
    unauthenticated.error_reason = "Authentication required"

    monkeypatch.setattr(handler_decorators, "_test_user_context_override", None)
    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request",
        lambda handler, user_store=None: unauthenticated,
    )

    result = RunsHandler({"plan_store": isolated_plan_store}).handle(
        "/api/runs",
        {},
        _make_http_handler(),
    )
    parsed = _parse(result)

    assert parsed["status"] == 401
    assert parsed["body"] == {"error": "Authentication required"}


def test_orchestration_read_is_granted_to_admins_and_owners() -> None:
    from aragora.server.handlers.utils.decorators import PERMISSION_MATRIX

    assert set(PERMISSION_MATRIX["orchestration:read"]) >= {"admin", "owner"}
