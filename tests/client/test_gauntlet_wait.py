"""Truthful polling against the existing Gauntlet status/receipt contract."""

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import inspect
import json
from threading import Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.client.errors import AragoraAPIError
from aragora.client import AragoraClient
from aragora.client.resources import gauntlet


RUN_ID = "gauntlet-wait-contract"
STATUS_PATH = f"/api/v1/gauntlet/{RUN_ID}"
RECEIPT_PATH = f"/api/gauntlet/{RUN_ID}/receipt"
RECEIPT = {"gauntlet_id": RUN_ID, "verdict": "APPROVED", "findings": []}


@pytest.fixture
def polling(monkeypatch):
    clock = SimpleNamespace(now=0.0, sleeps=[])

    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(
        gauntlet,
        "time",
        SimpleNamespace(monotonic=lambda: clock.now, time=lambda: clock.now, sleep=sleep),
    )
    client = MagicMock()
    client._post.return_value = {"gauntlet_id": RUN_ID, "status": "pending"}
    return gauntlet.GauntletAPI(client), client, clock


def state(status):
    # Actual _get_status server payload uses gauntlet_id, not GauntletRun.id.
    return {"gauntlet_id": RUN_ID, "status": status}


@pytest.mark.parametrize("verdict", ["APPROVED", "REJECTED", "NEEDS_REVIEW"])
def test_waits_for_status_before_requesting_legacy_receipt(polling, verdict):
    api, client, clock = polling
    client._get.side_effect = [
        state("pending"),
        state("running"),
        state("completed"),
        {**RECEIPT, "verdict": verdict},
    ]
    result = api.run_and_wait("content", timeout=30)
    assert result.verdict == verdict
    assert result.status is None
    assert [call.args[0] for call in client._get.call_args_list] == [
        STATUS_PATH,
        STATUS_PATH,
        STATUS_PATH,
        RECEIPT_PATH,
    ]
    assert clock.sleeps == [5, 5]
    client._post.assert_called_once()


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_run_is_not_indefinitely_pending_or_a_receipt(polling, status):
    api, client, clock = polling
    client._get.return_value = {**state(status), "error": "sensitive backend details"}
    with pytest.raises(AragoraAPIError, match=f"{RUN_ID}.*{status}") as caught:
        api.run_and_wait("content")
    assert "sensitive" not in str(caught.value)
    client._get.assert_called_once_with(STATUS_PATH)
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        None,
        {"gauntlet_id": RUN_ID},
        {"status": "pending"},
        {"gauntlet_id": "another-run", "status": "completed"},
        {"gauntlet_id": RUN_ID, "status": "mystery"},
        {"gauntlet_id": RUN_ID, "status": None},
        {"gauntlet_id": RUN_ID, "status": []},
    ],
)
def test_missing_unknown_or_mismatched_status_fails_closed(polling, payload):
    api, client, clock = polling
    client._get.return_value = payload
    with pytest.raises(AragoraAPIError, match=RUN_ID):
        api.run_and_wait("content")
    assert client._get.call_count == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "status,code", [(400, "GAUNTLET_406"), (400, "OTHER"), (404, "NOT_FOUND"), (503, "UNAVAILABLE")]
)
def test_http_failure_is_not_assumed_pending(polling, status, code):
    api, client, clock = polling
    error = AragoraAPIError("HTTP failure", code=code, status_code=status)
    client._get.side_effect = error
    with pytest.raises(AragoraAPIError) as caught:
        api.run_and_wait("content")
    assert caught.value is error
    assert clock.sleeps == []
    assert client._get.call_count == 1


@pytest.mark.parametrize("budget,sleeps,polls", [(0, [], 0), (1, [1], 1), (6, [5, 1], 2)])
def test_no_poll_after_deadline_and_no_oversleep(polling, budget, sleeps, polls):
    api, client, clock = polling
    client._get.return_value = state("running")
    with pytest.raises(TimeoutError, match=RUN_ID):
        api.run_and_wait("content", timeout=budget)
    assert clock.sleeps == sleeps
    assert clock.now == budget
    assert client._get.call_count == polls
    client._post.assert_called_once()


def test_elapsed_status_request_cannot_start_late_receipt_request(polling):
    api, client, clock = polling

    def slow_status(_path):
        clock.now = 10
        return state("completed")

    client._get.side_effect = slow_status
    with pytest.raises(TimeoutError, match=RUN_ID):
        api.run_and_wait("content", timeout=10)
    assert client._get.call_count == 1
    assert clock.sleeps == []


def test_polling_uses_monotonic_not_wall_clock(polling, monkeypatch):
    api, client, _ = polling
    client._get.side_effect = [state("completed"), RECEIPT]
    monkeypatch.setattr(gauntlet.time, "time", MagicMock(side_effect=AssertionError("wall clock")))
    assert api.run_and_wait("content").verdict == "APPROVED"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**RECEIPT, "status": "failed"},
        {**RECEIPT, "status": "running"},
        {**RECEIPT, "gauntlet_id": "another-run"},
        {**RECEIPT, "verdict": ""},
    ],
)
def test_completed_status_cannot_legitimize_malformed_receipt(polling, payload):
    api, client, clock = polling
    client._get.side_effect = [state("completed"), payload]
    with pytest.raises(AragoraAPIError, match=RUN_ID):
        api.run_and_wait("content")
    assert client._get.call_count == 2
    assert clock.sleeps == []


@pytest.mark.parametrize("during_sleep", [False, True])
def test_interruption_propagates_without_resubmission(polling, monkeypatch, during_sleep):
    api, client, _ = polling
    interrupted = KeyboardInterrupt()
    if during_sleep:
        client._get.return_value = state("running")
        monkeypatch.setattr(gauntlet.time, "sleep", MagicMock(side_effect=interrupted))
    else:
        client._get.side_effect = interrupted
    with pytest.raises(KeyboardInterrupt) as caught:
        api.run_and_wait("content")
    assert caught.value is interrupted
    assert client._get.call_count == 1
    client._post.assert_called_once()


@pytest.mark.parametrize("status", ["pending", "running", "failed", "cancelled", "completed"])
def test_real_handler_shapes_through_loopback_client(polling, monkeypatch, status):
    """No convenient mocked 406 exception: exercise real handlers and urllib."""
    from aragora.server.handlers.gauntlet import receipts, results

    run = {**state(status), "result": {"verdict": "APPROVED"}, "input_summary": "fixture"}
    monkeypatch.setattr(receipts, "get_gauntlet_runs", lambda: {RUN_ID: run})
    monkeypatch.setattr(results, "get_gauntlet_runs", lambda: {RUN_ID: run})

    def status_response():
        return asyncio.run(inspect.unwrap(results.GauntletResultsMixin._get_status)(None, RUN_ID))

    def receipt_response():
        return asyncio.run(
            inspect.unwrap(receipts.GauntletReceiptsMixin._get_receipt)(None, RUN_ID, {})
        )

    if status != "completed":
        pending = receipt_response()
        assert pending.status_code == 400
        assert json.loads(pending.body)["code"] == "GAUNTLET_406"

    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            calls.append(("POST", self.path))
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.reply(200, json.dumps(state("pending")).encode())

        def do_GET(self):
            calls.append(("GET", self.path))
            if self.path == STATUS_PATH:
                response = status_response()
                if run["status"] in ("pending", "running"):
                    run["status"] = "completed"
            else:
                assert self.path == RECEIPT_PATH
                response = receipt_response()
            self.reply(response.status_code, response.body)

        def reply(self, code, body):
            if isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with AragoraClient(base_url=f"http://127.0.0.1:{server.server_port}", timeout=2) as client:
            if status in ("failed", "cancelled"):
                with pytest.raises(AragoraAPIError, match=status):
                    client.gauntlet.run_and_wait("fixture", timeout=20)
            else:
                assert client.gauntlet.run_and_wait("fixture", timeout=20).verdict == "APPROVED"
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()
    assert calls.count(("POST", "/api/gauntlet/run")) == 1
    assert calls.count(("GET", RECEIPT_PATH)) == (0 if status in ("failed", "cancelled") else 1)


def test_inflight_receipt_retains_transport_timeout_and_can_finish_after_budget(polling):
    api, client, clock = polling

    def respond(path):
        if path == STATUS_PATH:
            return state("completed")
        clock.now = 20
        return {**RECEIPT, "status": "COMPLETED"}

    client._get.side_effect = respond
    assert api.run_and_wait("content", timeout=10).verdict == "APPROVED"
    assert clock.sleeps == []


@pytest.mark.parametrize("producer", ["handler", "worker"])
def test_producer_identity_survives_execution_storage_and_receipts(monkeypatch, tmp_path, producer):
    from aragora.agents import base
    import aragora.gauntlet as package
    from aragora.gauntlet import storage
    from aragora.ranking import elo
    from aragora.server.handlers.gauntlet import receipts, results, runner
    from aragora.server.workers.gauntlet_worker import GauntletWorker
    from aragora.storage.job_queue_store import QueuedJob

    config_type = package.OrchestratorConfig

    def offline_config(**kwargs):
        return config_type(
            **kwargs,
            **{
                f"enable_{phase}": False
                for phase in ("redteam", "probing", "deep_audit", "verification", "risk_assessment")
            },
        )

    # Real result construction and SQLite; no inference, ELO, or receipt publication.
    monkeypatch.setattr(package, "OrchestratorConfig", offline_config)
    monkeypatch.setattr(base, "create_agent", lambda **_: SimpleNamespace(name="offline"))
    monkeypatch.setattr(elo, "EloSystem", MagicMock())
    store_type = storage.GauntletStorage
    db = str(tmp_path / "results.db")
    store = store_type(db, backend="sqlite")
    store.save_inflight(RUN_ID, "pending", "spec", "fixture", "hash", None, "default", ["demo"])
    monkeypatch.setattr(storage, "GauntletStorage", lambda: store)
    runs = {RUN_ID: {**state("pending"), "input_summary": "fixture"}}
    for module in (runner, receipts, results):
        monkeypatch.setattr(module, "get_gauntlet_runs", lambda: runs)
        monkeypatch.setattr(module, "_get_storage_proxy", lambda: store)
    monkeypatch.setattr(runner, "get_gauntlet_broadcast_fn", lambda: None)
    if producer == "handler":
        owner = SimpleNamespace(_auto_persist_receipt=AsyncMock())
        asyncio.run(
            runner.GauntletRunnerMixin._run_gauntlet_async(
                owner, RUN_ID, "fixture", "spec", None, ["demo"], "default"
            )
        )
        assert runs[RUN_ID]["result_obj"].gauntlet_id == RUN_ID
        assert owner._auto_persist_receipt.call_args.args[0].gauntlet_id == RUN_ID
    else:
        worker = object.__new__(GauntletWorker)
        worker.broadcast_fn = None
        job = QueuedJob(
            id="queue-job",
            job_type="gauntlet",
            payload={"gauntlet_id": RUN_ID, "input_content": "fixture", "agents": ["demo"]},
        )
        assert asyncio.run(worker._execute_gauntlet(job))["gauntlet_id"] == RUN_ID
        runs.clear()
    assert store.get(RUN_ID)["gauntlet_id"] == RUN_ID
    assert store.get_inflight(RUN_ID) is None
    client = MagicMock()
    client._post.return_value = state("pending")

    def read(path):
        response = asyncio.run(
            inspect.unwrap(receipts.GauntletReceiptsMixin._get_receipt)(
                None, RUN_ID, {"signed": "false"}
            )
            if path == RECEIPT_PATH
            else inspect.unwrap(results.GauntletResultsMixin._get_status)(None, RUN_ID)
        )
        assert response.status_code == 200
        return json.loads(response.body)

    client._get.side_effect = read
    for _ in range(2):
        receipt = gauntlet.GauntletAPI(client).run_and_wait("fixture", timeout=10)
        assert receipt.gauntlet_id == RUN_ID
        assert receipt.verdict == "NEEDS_REVIEW"  # No fabricated successful evidence.
        runs.clear()
        store.close()
        store = store_type(db, backend="sqlite")  # Restart-style durable lookup.
    store.close()
    assert client._post.call_count == 2  # One per explicit client invocation.


def test_standalone_execution_still_generates_distinct_ids():
    from aragora.gauntlet import GauntletOrchestrator, OrchestratorConfig

    config = OrchestratorConfig(enable_risk_assessment=False, enable_verification=False)
    first = asyncio.run(GauntletOrchestrator([]).run(config))
    second = asyncio.run(GauntletOrchestrator([]).run(config))
    assert first.gauntlet_id.startswith("gauntlet-")
    assert second.gauntlet_id.startswith("gauntlet-")
    assert first.gauntlet_id != second.gauntlet_id
