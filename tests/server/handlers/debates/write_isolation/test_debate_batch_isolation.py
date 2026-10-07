"""Debate batches belong to the org that submitted them (inventory D19).

``GET /api/v1/debates/batch`` lists only the caller's batches, and
``/batch/{id}/status`` reads the batch id and answers another org's batch like
a missing one. Also covers the ``/api/v1/batch`` placeholder routes.
"""

from __future__ import annotations

import pytest

from tests.server.handlers.debates.write_isolation.support import (
    ANON,
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    USER_NO_ORG,
    body_of,
    text_of,
)

BATCH_NOT_FOUND = {"error": "Batch not found", "code": "not_found"}
BATCH_A, BATCH_B, BATCH_NULL = "batch_aaaaaaaaaaaa", "batch_bbbbbbbbbbbb", "batch_nnnnnnnnnnnn"


@pytest.fixture
def queue(monkeypatch):
    from aragora.server import debate_queue
    from aragora.server.debate_queue import BatchItem, BatchRequest, DebateQueue

    queue = DebateQueue()
    for name, org in ((BATCH_A, ORG_A), (BATCH_B, ORG_B), (BATCH_NULL, None)):
        batch = BatchRequest(items=[BatchItem(question=f"{name}?", org_id=org)], org_id=org)
        batch.batch_id = name
        queue._batches[name] = batch
    monkeypatch.setattr(debate_queue, "get_debate_queue_sync", lambda: queue)
    return queue


def test_list_shows_only_the_callers_batches(send, queue):
    listed_a = body_of(send(USER_A, "GET", "/api/v1/debates/batch"))
    listed_b = body_of(send(USER_B, "GET", "/api/v1/debates/batch"))

    assert [b["batch_id"] for b in listed_a["batches"]] == [BATCH_A]
    assert [b["batch_id"] for b in listed_b["batches"]] == [BATCH_B]


def test_status_reads_the_batch_id_and_hides_other_orgs(send, queue):
    owner = send(USER_A, "GET", f"/api/v1/debates/batch/{BATCH_A}/status")

    assert owner.status_code == 200, text_of(owner)
    assert body_of(owner)["batch_id"] == BATCH_A
    for batch_id in (BATCH_A, BATCH_NULL, "batch_cccccccccccc"):
        refused = send(USER_B, "GET", f"/api/v1/debates/batch/{batch_id}/status")
        assert (refused.status_code, body_of(refused)) == (404, BATCH_NOT_FOUND), batch_id


def test_anonymous_and_org_less_callers_are_refused(send, queue):
    for path in ("/api/v1/debates/batch", f"/api/v1/debates/batch/{BATCH_A}/status"):
        assert send(ANON, "GET", path).status_code == 401, path
        no_org = send(USER_NO_ORG, "GET", path)
        assert (no_org.status_code, body_of(no_org)["code"]) == (403, "org_required"), path


def test_submitted_batch_records_the_callers_org(send, monkeypatch):
    from aragora.server import debate_queue

    submitted = []

    class _Queue:
        debate_executor = object()

        async def submit_batch(self, batch):
            submitted.append(batch)
            return batch.batch_id

    async def _get_queue():
        return _Queue()

    monkeypatch.setattr(debate_queue, "get_debate_queue", _get_queue)
    result = send(USER_A, "POST", "/api/v1/debates/batch", {"items": [{"question": "Q?"}]})

    assert result.status_code == 200, text_of(result)
    assert [(b.org_id, b.items[0].org_id) for b in submitted] == [(ORG_A, ORG_A)]


@pytest.mark.no_auto_auth
def test_unimplemented_batch_routes_answer_instead_of_500(server):
    from tests.server.rbac_dispatch import dispatch, jwt

    token = jwt("owner-no-org", None, "owner")
    for method, path in (
        ("GET", "/api/v1/batch"),
        ("POST", "/api/v1/batch"),
        ("GET", "/api/v1/batch/queue/status"),
    ):
        status, payload = dispatch(server, method, path, token)
        assert status == 501, (method, path, payload)
