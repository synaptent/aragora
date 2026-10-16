"""Job-queue health endpoints when the distributed-state guard refuses the store.

In production with a SQLite job store, ``SQLiteJobStore.__init__`` calls
``require_distributed_store``, which raises ``DistributedStateError``. The
authenticated ``/api/health/job-queue`` and ``/api/health/workers/all``
endpoints must still answer 200 with an unhealthy queue report that names only
the error type, instead of letting the error reach the dispatcher's 500 path.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from aragora.server.handlers.admin.health import HealthHandler, workers
from aragora.storage import job_queue_store, production_guards

_GUARD_ERROR = "Queue status error: DistributedStateError"

_ENDPOINTS = {
    "job-queue": (workers.job_queue_health_status, lambda body: body),
    "workers-all": (workers.combined_worker_queue_health, lambda body: body["job_queue"]),
}


def _on_fresh_thread(fn: Any) -> Any:
    """Run ``fn`` on a new thread, which has no event loop, and return its result."""
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - re-raised on the test thread
            outcome["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=60)
    assert not thread.is_alive()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


@pytest.fixture
def production_sqlite(monkeypatch, tmp_path):
    """Production with a SQLite job store and the guard at its default (enforcing)."""
    for key in (
        "ARAGORA_REQUIRE_DISTRIBUTED",
        "ARAGORA_REQUIRE_DISTRIBUTED_STATE",
        "ARAGORA_ALLOW_SQLITE_FALLBACK",
        "ARAGORA_JOB_STORE_BACKEND",
        "ARAGORA_JOB_BACKEND",
        "DATABASE_URL",
        "ARAGORA_POSTGRES_DSN",
        "SUPABASE_URL",
        "SUPABASE_POSTGRES_DSN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARAGORA_ENV", "production")
    monkeypatch.setenv("ARAGORA_DB_BACKEND", "sqlite")
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(production_guards, "_config", None)
    job_queue_store.reset_job_store()
    yield tmp_path
    job_queue_store.reset_job_store()


def _enforce_guard_in_this_test(monkeypatch) -> None:
    # require_distributed_store waives the guard whenever PYTEST_CURRENT_TEST is
    # set, and pytest sets it again at the start of every phase, so a fixture
    # cannot clear it for the call phase.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


def _assert_guard_reported(result: Any, queue: dict[str, Any], data_dir: Any) -> None:
    assert result.status_code == 200
    assert queue["status"] == "unhealthy"
    assert queue["connected"] is False
    assert queue["errors"] == [_GUARD_ERROR]
    text = result.body.decode("utf-8")
    for leaked in ("ARAGORA_REQUIRE_DISTRIBUTED", "job_queue_store", str(data_dir)):
        assert leaked not in text


@pytest.mark.parametrize("endpoint", sorted(_ENDPOINTS))
def test_guard_error_on_thread_without_event_loop_reports_unhealthy(
    endpoint, production_sqlite, monkeypatch
):
    # The deploy-secure recipe sets the fallback flag, so the store factory
    # builds SQLiteJobStore and the guard raises.
    monkeypatch.setenv("ARAGORA_ALLOW_SQLITE_FALLBACK", "true")
    _enforce_guard_in_this_test(monkeypatch)
    endpoint_fn, queue_of = _ENDPOINTS[endpoint]

    result = _on_fresh_thread(lambda: endpoint_fn(MagicMock()))

    body = json.loads(result.body)
    _assert_guard_reported(result, queue_of(body), production_sqlite)
    assert body["status"] == "unhealthy"


@pytest.mark.parametrize("path", ["/api/health/job-queue", "/api/v1/health/workers/all"])
def test_guard_error_through_handle_in_event_loop_reports_unhealthy(
    path, production_sqlite, monkeypatch
):
    # The threaded server runs handle() inside an event loop, where the store
    # factory falls back to SQLite even without the flag.
    _enforce_guard_in_this_test(monkeypatch)
    http = MagicMock(command="GET", headers={})

    result = _on_fresh_thread(lambda: asyncio.run(HealthHandler(ctx={}).handle(path, {}, http)))

    body = json.loads(result.body)
    queue = body["job_queue"] if path.endswith("/workers/all") else body
    _assert_guard_reported(result, queue, production_sqlite)


class _HealthyStore:
    async def get_stats(self) -> dict[str, int]:
        return {"pending": 0, "processing": 0, "completed": 3, "failed": 0, "total": 3}


@pytest.mark.parametrize("endpoint", sorted(_ENDPOINTS))
def test_healthy_store_still_reports_healthy(endpoint, monkeypatch):
    monkeypatch.setattr(job_queue_store, "_job_store", _HealthyStore())
    endpoint_fn, queue_of = _ENDPOINTS[endpoint]

    result = _on_fresh_thread(lambda: endpoint_fn(MagicMock()))

    queue = queue_of(json.loads(result.body))
    assert result.status_code == 200
    assert queue["status"] == "healthy"
    assert queue["connected"] is True
    assert queue["errors"] is None
    assert queue["stats"]["completed"] == 3
