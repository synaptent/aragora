"""Org isolation of the gauntlet routes (GauntletHandler, legacy server).

Two orgs and an anonymous caller exercise every gauntlet route against real
SQLite gauntlet and receipt stores holding results and receipts of org A,
org B and a pair with no owner:

* another org's run, result or receipt answers exactly like a missing one,
  and deleting it has no side effect;
* result, receipt and anchor lists only show the caller org's records; an
  unowned record is shown to nobody;
* anonymous callers get 401 and static-API-token-only callers 403
  ``org_required``;
* runs started through the API, the durable worker and the auto-persisted
  decision receipt carry the creator's org;
* the owner keeps full access.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.billing.auth.context import UserAuthContext
from aragora.gauntlet.storage import GauntletStorage
from aragora.server.handlers.gauntlet import GauntletHandler, get_gauntlet_runs
from aragora.storage.receipt_store import ReceiptStore
from aragora.tenancy.record_scope import OrgScope

ORG_A = "org-a"
ORG_B = "org-b"
SCOPE_A = OrgScope(org_id=ORG_A, user_id="user-a", role="admin")

GID_A = "gauntlet-20261004120000-aaaaaa"
GID_A2 = "gauntlet-20261004120100-aaaaa2"
GID_B = "gauntlet-20261004120000-bbbbbb"
GID_NULL = "gauntlet-20261004120000-000000"
GID_MISSING = "gauntlet-20261004120000-ffffff"
# An in-memory (not yet persisted) completed run owned by A.
GID_LIVE_A = "gauntlet-20261004120200-cccccc"

RUN_NOT_FOUND = {"error": "Gauntlet run not found", "code": "not_found"}
RECEIPT_NOT_FOUND = {"error": "Receipt not found", "code": "not_found"}

USER_A = UserAuthContext(
    authenticated=True,
    user_id="user-a",
    email="a@example.com",
    org_id=ORG_A,
    role="admin",
    token_type="access",
)
USER_B = UserAuthContext(
    authenticated=True,
    user_id="user-b",
    email="b@example.com",
    org_id=ORG_B,
    role="admin",
    token_type="access",
)
ANONYMOUS = UserAuthContext(authenticated=False)


def _finding(gid: str) -> dict[str, Any]:
    return {
        "id": f"f-{gid[-6:]}",
        "category": "security",
        "severity": 0.9,
        "severity_level": "HIGH",
        "title": f"sentinel finding {gid}",
        "description": f"sentinel text of {gid}",
    }


class _StoredResult:
    """The attributes ``GauntletStorage.save`` reads from a gauntlet result."""

    def __init__(self, gauntlet_id: str) -> None:
        self.gauntlet_id = gauntlet_id
        self.input_summary = f"isolation probe {gauntlet_id}"
        self.input_hash = f"hash-{gauntlet_id}"
        self.verdict = "pass"
        self.confidence = 0.9
        self.robustness_score = 0.8
        self.total_findings = 1
        self.high_findings = [_finding(gauntlet_id)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gauntlet_id": self.gauntlet_id,
            "input_summary": self.input_summary,
            "input_hash": self.input_hash,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "robustness_score": self.robustness_score,
            "total_findings": 1,
            "high_count": 1,
            "findings": [_finding(self.gauntlet_id)],
        }


def _receipt_payload(receipt_id: str, gauntlet_id: str) -> dict[str, Any]:
    return {
        "receipt_id": receipt_id,
        "gauntlet_id": gauntlet_id,
        "timestamp": "2026-10-04T12:00:00",
        "input_summary": f"isolation probe {gauntlet_id}",
        "input_hash": f"hash-{gauntlet_id}",
        "verdict": "PASS",
        "confidence": 0.9,
        "robustness_score": 0.8,
        "risk_summary": {"total": 1},
        "checksum": f"checksum-{receipt_id}",
    }


@pytest.fixture(autouse=True)
def _clean_runs():
    runs = get_gauntlet_runs()
    runs.clear()
    yield
    runs.clear()


@pytest.fixture
def gauntlet_storage(tmp_path, monkeypatch) -> GauntletStorage:
    storage = GauntletStorage(db_path=str(tmp_path / "gauntlet.db"))
    storage.save(_StoredResult(GID_A), org_id=ORG_A)
    storage.save(_StoredResult(GID_A2), org_id=ORG_A)
    storage.save(_StoredResult(GID_B), org_id=ORG_B)
    storage.save(_StoredResult(GID_NULL))
    monkeypatch.setattr("aragora.server.handlers.gauntlet._get_storage", lambda: storage)
    return storage


@pytest.fixture
def receipt_store(tmp_path, monkeypatch) -> ReceiptStore:
    store = ReceiptStore(db_path=tmp_path / "receipts.db", file_receipt_dirs=[])
    store.save(_receipt_payload("rcpt-ga", GID_A), org_id=ORG_A, created_by="user-a")
    store.save(_receipt_payload("rcpt-gb", GID_B), org_id=ORG_B, created_by="user-b")
    store.save(_receipt_payload("rcpt-gnull", GID_NULL))
    monkeypatch.setattr("aragora.storage.receipt_store.get_receipt_store", lambda: store)
    return store


@pytest.fixture
def gauntlet(gauntlet_storage, receipt_store) -> GauntletHandler:
    handler = GauntletHandler({})
    get_gauntlet_runs()[GID_LIVE_A] = {
        "gauntlet_id": GID_LIVE_A,
        "status": "completed",
        "input_type": "spec",
        "input_summary": "in-memory probe",
        "input_hash": "hash-live",
        "created_at": "2026-10-04T12:02:00",
        "completed_at": "2026-10-04T12:03:00",
        "org_id": ORG_A,
        "created_by": "user-a",
        "result": _StoredResult(GID_LIVE_A).to_dict(),
    }
    return handler


@pytest.fixture
def act_as(monkeypatch):
    """Make every following request come from ``user``."""

    def _act_as(user: UserAuthContext) -> None:
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: user,
        )

    return _act_as


def _request(method: str, body: dict[str, Any] | None, headers: dict[str, str] | None):
    request = MagicMock()
    request.command = method
    request.headers = headers or {}
    request.user_store = None
    request._auth_context = None
    request.body = json.dumps(body).encode() if body is not None else b""
    return request


async def _call(
    gauntlet: GauntletHandler,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
):
    return await gauntlet.handle(path, dict(query or {}), _request(method, body, headers))


def _json(result) -> Any:
    return json.loads(result.body)


# (method, path template, body) for every route acting on one gauntlet run.
PER_RUN_ROUTES = [
    ("GET", "/api/v1/gauntlet/{id}", None),
    ("GET", "/api/gauntlet/{id}", None),
    ("GET", "/api/v1/gauntlet/{id}/receipt", None),
    ("GET", "/api/v1/gauntlet/{id}/heatmap", None),
    ("GET", "/api/v1/gauntlet/{id}/export", None),
    ("GET", "/api/v1/gauntlet/{id}/compare/{id}", None),
    ("POST", "/api/v1/gauntlet/{id}/receipt/verify", {}),
    ("DELETE", "/api/v1/gauntlet/{id}", None),
]
RUN_ROUTE_IDS = [f"{m} {p}" for m, p, _b in PER_RUN_ROUTES]

COLLECTION_ROUTES = [
    ("GET", "/api/v1/gauntlet/results", None),
    ("GET", "/api/v1/gauntlet/receipts", None),
    ("GET", "/api/v1/receipts/recent-anchors", None),
    ("POST", "/api/v1/gauntlet/run", {"input_content": "probe"}),
]
ALL_SCOPED_ROUTES = (
    [(m, p.format(id=GID_A), b) for m, p, b in PER_RUN_ROUTES]
    + [("GET", "/api/v1/receipts/rcpt-ga/anchor-status", None)]
    + COLLECTION_ROUTES
)


class TestForeignRunIsIndistinguishableFromMissing:
    @pytest.mark.asyncio
    async def test_compare_with_a_foreign_run_is_404(self, gauntlet, act_as):
        act_as(USER_A)
        result = await _call(gauntlet, "GET", f"/api/v1/gauntlet/{GID_A}/compare/{GID_B}")
        assert result.status_code == 404
        assert _json(result) == RUN_NOT_FOUND


class TestForeignDeleteHasNoSideEffect:
    @pytest.mark.parametrize("target", [GID_A, GID_LIVE_A])
    @pytest.mark.asyncio
    async def test_other_org_delete_leaves_the_run(
        self, gauntlet, gauntlet_storage, act_as, target
    ):
        act_as(USER_B)
        result = await _call(gauntlet, "DELETE", f"/api/v1/gauntlet/{target}")

        assert result.status_code == 404
        assert gauntlet_storage.get(GID_A, ORG_A) is not None
        assert GID_LIVE_A in get_gauntlet_runs()

        act_as(USER_A)
        assert (await _call(gauntlet, "GET", f"/api/v1/gauntlet/{target}")).status_code == 200


class TestListsShowOnlyTheCallersOrg:
    @pytest.mark.parametrize(("user", "expected"), [(USER_A, {GID_A, GID_A2}), (USER_B, {GID_B})])
    @pytest.mark.asyncio
    async def test_results(self, gauntlet, act_as, user, expected):
        act_as(user)
        body = _json(await _call(gauntlet, "GET", "/api/v1/gauntlet/results"))
        assert {r["gauntlet_id"] for r in body["results"]} == expected
        assert body["total"] == len(expected)

    @pytest.mark.parametrize(("user", "expected"), [(USER_A, {"rcpt-ga"}), (USER_B, {"rcpt-gb"})])
    @pytest.mark.asyncio
    async def test_receipts(self, gauntlet, act_as, user, expected):
        act_as(user)
        body = _json(await _call(gauntlet, "GET", "/api/v1/gauntlet/receipts"))
        assert {r["receipt_id"] for r in body["receipts"]} == expected

    @pytest.mark.asyncio
    async def test_recent_anchors(self, gauntlet, act_as, receipt_store):
        anchor = gauntlet._get_receipt_anchor()
        for receipt_id in ("rcpt-ga", "rcpt-gb", "rcpt-gnull"):
            anchor._anchor_locally(receipt_store.get(receipt_id).checksum, {"probe": receipt_id})

        act_as(USER_A)
        body = _json(await _call(gauntlet, "GET", "/api/v1/receipts/recent-anchors"))
        assert [a["metadata"]["probe"] for a in body["anchors"]] == ["rcpt-ga"]
        assert body["total"] == 1

        act_as(USER_B)
        body = _json(await _call(gauntlet, "GET", "/api/v1/receipts/recent-anchors"))
        assert [a["metadata"]["probe"] for a in body["anchors"]] == ["rcpt-gb"]


class TestUnauthenticatedCallers:
    @pytest.mark.parametrize(("method", "path", "body"), ALL_SCOPED_ROUTES)
    @pytest.mark.asyncio
    async def test_anonymous_gets_401(self, gauntlet, act_as, method, path, body):
        act_as(ANONYMOUS)
        result = await _call(gauntlet, method, path, body=body)
        assert result.status_code == 401
        assert _json(result)["code"] == "auth_required"

    @pytest.mark.parametrize(("method", "path", "body"), ALL_SCOPED_ROUTES)
    @pytest.mark.asyncio
    async def test_static_token_only_gets_403_org_required(
        self, gauntlet, act_as, monkeypatch, method, path, body
    ):
        from aragora.server import auth as server_auth

        monkeypatch.setattr(server_auth.auth_config, "api_token", "static-token-123")
        act_as(ANONYMOUS)
        result = await _call(
            gauntlet, method, path, body=body, headers={"Authorization": "Bearer static-token-123"}
        )
        assert result.status_code == 403
        assert _json(result)["code"] == "org_required"

    @pytest.mark.asyncio
    async def test_anonymous_delete_has_no_side_effect(self, gauntlet, gauntlet_storage, act_as):
        act_as(ANONYMOUS)
        await _call(gauntlet, "DELETE", f"/api/v1/gauntlet/{GID_A}")
        assert gauntlet_storage.get(GID_A, ORG_A) is not None


_OWNER_READS = [
    pytest.param(method, path, body, own, id=f"{route_id}-{own[-6:]}")
    for route_id, (method, path, body) in zip(RUN_ROUTE_IDS, PER_RUN_ROUTES)
    if method == "GET"
    for own in (GID_A, GID_LIVE_A)
    # compare reads persisted results only
    if not ("/compare/" in path and own == GID_LIVE_A)
]


class TestOwnerKeepsAccess:
    @pytest.mark.parametrize(("method", "path", "body", "own"), _OWNER_READS)
    @pytest.mark.asyncio
    async def test_owner_succeeds_on_every_read_route(
        self, gauntlet, act_as, method, path, body, own
    ):
        act_as(USER_A)
        result = await _call(gauntlet, method, path.format(id=own), body=body)
        assert result.status_code == 200, result.body[:300]

    @pytest.mark.asyncio
    async def test_owner_deletes_their_result(self, gauntlet, gauntlet_storage, act_as):
        act_as(USER_A)
        result = await _call(gauntlet, "DELETE", f"/api/v1/gauntlet/{GID_A}")
        assert result.status_code == 200
        assert gauntlet_storage.get(GID_A, ORG_A) is None


def _orchestrator_result(gauntlet_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        gauntlet_id=gauntlet_id,
        input_summary="started through the API",
        verdict=SimpleNamespace(value="pass"),
        confidence=0.9,
        risk_score=0.1,
        robustness_score=0.9,
        coverage_score=0.8,
        total_findings=0,
        critical_findings=[],
        high_findings=[],
        medium_findings=[],
        low_findings=[],
        all_findings=[],
        duration_seconds=1.0,
    )


@pytest.fixture
def offline_run(monkeypatch):
    """Run gauntlets without agents, knowledge mound or webhooks."""

    def _install(gauntlet_id: str) -> None:
        orchestrator = MagicMock()
        orchestrator.run = AsyncMock(return_value=_orchestrator_result(gauntlet_id))
        monkeypatch.setattr("aragora.agents.base.create_agent", lambda **_: MagicMock(name="a"))
        monkeypatch.setattr("aragora.gauntlet.GauntletOrchestrator", lambda *a, **k: orchestrator)
        monkeypatch.setattr("aragora.knowledge.mound.get_knowledge_mound", lambda: None)
        monkeypatch.setattr(
            "aragora.integrations.receipt_webhooks.get_receipt_notifier", lambda: MagicMock()
        )

    return _install


class TestRunsCarryTheCreatorsOrg:
    @pytest.mark.parametrize("durable", [False, True])
    @pytest.mark.asyncio
    async def test_started_run_belongs_to_the_caller(
        self, gauntlet, gauntlet_storage, act_as, monkeypatch, durable
    ):
        from aragora.server.handlers.gauntlet import runner

        started: list[Any] = []

        def _track(coro, name):
            started.append(name)
            coro.close()

        enqueue = AsyncMock()
        monkeypatch.setattr(runner, "create_tracked_task", _track)
        monkeypatch.setattr(runner, "is_durable_queue_enabled", lambda: durable)
        monkeypatch.setattr("aragora.server.workers.gauntlet_worker.enqueue_gauntlet_job", enqueue)

        act_as(USER_A)
        started_run = await _call(
            gauntlet, "POST", "/api/v1/gauntlet/run", body={"input_content": "probe"}
        )
        assert started_run.status_code == 202
        gid = _json(started_run)["gauntlet_id"]

        run = get_gauntlet_runs()[gid]
        assert (run["org_id"], run["created_by"]) == (ORG_A, "user-a")
        assert gauntlet_storage.get_inflight(gid).org_id == ORG_A
        if durable:
            assert enqueue.call_args.kwargs["org_id"] == ORG_A
            assert enqueue.call_args.kwargs["user_id"] == "user-a"

        assert (await _call(gauntlet, "GET", f"/api/v1/gauntlet/{gid}")).status_code == 200
        act_as(USER_B)
        assert (await _call(gauntlet, "GET", f"/api/v1/gauntlet/{gid}")).status_code == 404

    @pytest.mark.asyncio
    async def test_completed_run_saves_result_and_receipt_for_the_org(
        self, gauntlet, gauntlet_storage, receipt_store, offline_run
    ):
        gid = "gauntlet-20261004130000-dddddd"
        offline_run(gid)
        get_gauntlet_runs()[gid] = {
            "gauntlet_id": gid,
            "status": "pending",
            "org_id": ORG_A,
            "created_by": "user-a",
            "result": None,
        }

        await gauntlet._run_gauntlet_async(
            gid, "probe", "spec", None, ["demo"], "default", scope=SCOPE_A
        )

        assert get_gauntlet_runs()[gid]["status"] == "completed"
        assert gauntlet_storage.get(gid, ORG_A) is not None
        assert gauntlet_storage.get(gid, ORG_B) is None
        receipt = receipt_store.get_by_gauntlet_for_org(gid, ORG_A)
        assert receipt is not None
        assert receipt.created_by == "user-a"


class TestDurableWorkerKeepsTheOrg:
    @pytest.mark.asyncio
    async def test_enqueued_job_carries_the_org(self, tmp_path):
        from aragora.server.workers.gauntlet_worker import enqueue_gauntlet_job
        from aragora.storage.job_queue_store import (
            SQLiteJobStore,
            reset_job_store,
            set_job_store,
        )

        reset_job_store()
        set_job_store(SQLiteJobStore(tmp_path / "jobs.db"))
        try:
            job = await enqueue_gauntlet_job(
                gauntlet_id=GID_MISSING,
                input_content="probe",
                input_type="spec",
                persona=None,
                agents=["demo"],
                profile="default",
                user_id="user-a",
                org_id=ORG_A,
            )
        finally:
            reset_job_store()
        assert job.payload["org_id"] == ORG_A

    @pytest.mark.parametrize("org_in_payload", [True, False])
    @pytest.mark.asyncio
    async def test_worker_saves_the_result_for_the_org(
        self, gauntlet_storage, offline_run, monkeypatch, org_in_payload
    ):
        from aragora.server.workers.gauntlet_worker import GauntletWorker
        from aragora.storage.job_queue_store import QueuedJob

        gid = "gauntlet-20261004140000-eeeeee"
        offline_run(gid)
        monkeypatch.setattr("aragora.gauntlet.storage.GauntletStorage", lambda: gauntlet_storage)
        monkeypatch.setattr("aragora.ranking.elo.EloSystem", MagicMock)
        gauntlet_storage.save_inflight(
            gauntlet_id=gid,
            status="pending",
            input_type="spec",
            input_summary="probe",
            input_hash="hash",
            persona=None,
            profile="default",
            agents=["demo"],
            org_id=ORG_A,
        )
        payload = {"gauntlet_id": gid, "input_content": "probe", "agents": ["demo"]}
        if org_in_payload:
            payload["org_id"] = ORG_A

        await GauntletWorker()._execute_gauntlet(
            QueuedJob(id=gid, job_type="gauntlet", payload=payload)
        )

        assert gauntlet_storage.get(gid, ORG_A) is not None
        assert gauntlet_storage.get(gid, ORG_B) is None
