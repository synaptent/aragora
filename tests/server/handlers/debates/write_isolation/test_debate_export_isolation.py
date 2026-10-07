"""Batch export jobs belong to the org that started them (inventory D11).

A job exports only its org's debates (public ones of that org included); any
other id is reported as not found. Another org's job answers like a missing one.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from aragora.server.handlers.debates.export import _run_in_background as REAL_RUN_IN_BACKGROUND
from tests.server.handlers.debates.write_isolation.support import (
    ANON,
    DA,
    DA_TASK,
    DB,
    DB_TASK,
    DN,
    DP,
    DX,
    ORG_A,
    USER_A,
    USER_B,
    USER_NO_ORG,
    body_of,
    text_of,
)

JOB_NOT_FOUND = {"error": "Export job not found", "code": "not_found"}


@pytest.fixture(autouse=True)
def _clean_export_jobs(monkeypatch):
    from aragora.server.handlers.debates import export

    export._batch_export_jobs.clear()
    export._batch_export_events.clear()
    monkeypatch.setattr(export, "_run_in_background", lambda coro: asyncio.run(coro))
    yield
    export._batch_export_jobs.clear()
    export._batch_export_events.clear()


def _start(send, user, ids):
    result = send(
        user, "POST", "/api/v1/debates/export/batch", {"debate_ids": ids, "format": "json"}
    )
    assert result.status_code == 200, text_of(result)
    return body_of(result)["job_id"]


def test_mixed_ids_export_only_the_callers_org(send):
    job_id = _start(send, USER_A, [DA, DB, DN, DP, DX])

    result = send(USER_A, "GET", f"/api/v1/debates/export/batch/{job_id}/results")

    assert result.status_code == 200, text_of(result)
    by_id = {row["debate_id"]: row for row in body_of(result)["results"]}
    assert by_id[DA]["status"] == "completed" and DA_TASK in by_id[DA]["content"]
    assert by_id[DP]["status"] == "completed"
    refused = [by_id[d] for d in (DB, DN, DX)]
    assert {(r["status"], r["content"], r["error"]) for r in refused} == {
        ("failed", None, "Debate not found")
    }
    assert DB_TASK not in text_of(result)


@pytest.mark.parametrize("route", ["status", "results", "stream"])
def test_other_org_gets_the_missing_job_404(send, route):
    job_id = _start(send, USER_A, [DA])

    other = send(USER_B, "GET", f"/api/v1/debates/export/batch/{job_id}/{route}")
    missing = send(USER_B, "GET", f"/api/v1/debates/export/batch/export_000000000000/{route}")

    assert (other.status_code, body_of(other)) == (404, JOB_NOT_FOUND)
    assert (missing.status_code, body_of(missing)) == (404, JOB_NOT_FOUND)
    if route != "stream":
        owner = send(USER_A, "GET", f"/api/v1/debates/export/batch/{job_id}/{route}")
        assert owner.status_code == 200, text_of(owner)


def test_job_list_shows_only_the_callers_jobs(send):
    job_id = _start(send, USER_A, [DA])

    listed_a = body_of(send(USER_A, "GET", "/api/v1/debates/export/batch"))
    listed_b = body_of(send(USER_B, "GET", "/api/v1/debates/export/batch"))

    assert [job["job_id"] for job in listed_a["jobs"]] == [job_id]
    assert (listed_b["jobs"], listed_b["count"]) == ([], 0)


def test_anonymous_and_org_less_callers_are_refused(send):
    from aragora.server.handlers.debates import export

    job_id = _start(send, USER_A, [DA])
    paths = [
        ("POST", "/api/v1/debates/export/batch"),
        ("GET", "/api/v1/debates/export/batch"),
        *(("GET", f"/api/v1/debates/export/batch/{job_id}/{r}") for r in ("status", "results")),
        ("GET", f"/api/v1/debates/export/batch/{job_id}/stream"),
    ]
    for method, path in paths:
        body = {"debate_ids": [DA], "format": "json"}
        assert send(ANON, method, path, body).status_code == 401, path
        no_org = send(USER_NO_ORG, method, path, body)
        assert (no_org.status_code, body_of(no_org)["code"]) == (403, "org_required"), path
    assert list(export._batch_export_jobs) == [job_id]


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("token", [None, "static-test-token"])
def test_anonymous_start_is_refused_without_the_rbac_test_bypass(send, monkeypatch, token):
    from aragora.server.auth import auth_config
    from aragora.server.handlers.debates import export

    monkeypatch.setattr(auth_config, "api_token", token)
    monkeypatch.setattr(auth_config, "enabled", token is not None)

    result = send(
        ANON, "POST", "/api/v1/debates/export/batch", {"debate_ids": [DA], "format": "json"}
    )

    assert result.status_code == 401, text_of(result)
    assert export._batch_export_jobs == {}


def test_start_answers_without_a_running_event_loop(debates, monkeypatch):
    """The legacy server calls handlers on threads with no running loop."""
    from aragora.server.handlers.debates import export

    started = []
    monkeypatch.setattr(export, "_run_in_background", started.append)
    result = debates._start_batch_export(None, [DA], "json", org_id=ORG_A)

    assert result.status_code == 200
    assert len(started) == 1
    started[0].close()


def test_background_runner_runs_the_job_without_a_loop():
    done = threading.Event()

    async def job() -> None:
        done.set()

    REAL_RUN_IN_BACKGROUND(job())

    assert done.wait(timeout=5)
