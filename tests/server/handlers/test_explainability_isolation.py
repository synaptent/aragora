"""Explainability routes on a debate are scoped to the caller's org.

``/api/v1/debates/{id}/evidence`` (and the other per-debate explainability
routes) are served by ``ExplainabilityHandler``. Seeds a real ``DebateStorage``
as the server storage with a private debate of org A (``DA``), one of org B
(``DB``), one with no recorded org (``DN``) and a public debate of org A
(``DP``).
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.decisions import explainability as explain_mod
from aragora.server.handlers.decisions import explainability_store as store_mod
from aragora.server.handlers.decisions.explainability import ExplainabilityHandler
from aragora.storage.debate_storage import DebateStorage

ORG_A = "org-a"
ORG_B = "org-b"
DA, DB, DN, DP = "deb-alpha-a", "deb-bravo-b", "deb-null-org", "deb-public-a"
DX = "deb-missing-x"
DA_TASK = "Explainability topic alpha for org A only"

ENDPOINTS = ["explanation", "evidence", "votes/pivots", "counterfactuals", "explainability/export"]
NOT_FOUND = {"error": "Debate not found", "code": "not_found"}


def _debate(debate_id: str, task: str) -> dict[str, Any]:
    return {
        "id": debate_id,
        "task": task,
        "agents": ["claude", "gpt"],
        "messages": [
            {"role": "proposer", "agent": "claude", "content": f"{task} opening", "round": 1}
        ],
        "critiques": [],
        "votes": [],
        "final_answer": f"{task} answer",
        "consensus_reached": True,
        "confidence": 0.8,
        "status": "completed",
    }


@pytest.fixture
def storage(tmp_path) -> DebateStorage:
    store = DebateStorage(str(tmp_path / "debates.db"))
    store.save_dict(_debate(DA, DA_TASK), org_id=ORG_A)
    store.save_dict(_debate(DB, "Explainability topic bravo for org B"), org_id=ORG_B)
    store.save_dict(_debate(DN, "Explainability topic with no recorded org"))
    store.save_dict(_debate(DP, "Explainability topic shared publicly by A"), org_id=ORG_A)
    assert store.set_public(DP, True)
    return store


@pytest.fixture(autouse=True)
def _fresh_caches_and_batch_store():
    explain_mod._decision_cache.clear()
    store_mod._batch_store = store_mod.MemoryBatchJobStore()
    yield
    explain_mod._decision_cache.clear()
    store_mod._batch_store = None


def _user(org_id: str | None, user_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id, org_id=org_id, role="member", is_authenticated=True, authenticated=True
    )


ANON = SimpleNamespace(user_id=None, org_id=None, role=None, is_authenticated=False)
USER_A = _user(ORG_A, "user-a")
USER_B = _user(ORG_B, "user-b")
USER_NO_ORG = _user(None, "user-no-org")


@pytest.fixture
def handler(storage) -> ExplainabilityHandler:
    return ExplainabilityHandler({"storage": storage, "elo_system": None})


@pytest.fixture
def call(monkeypatch, handler):
    """``call(user, path, body=None)`` runs ``ExplainabilityHandler.handle`` as ``user``."""
    from aragora.server.handlers.utils.rate_limit import clear_all_limiters

    def _call(user: Any, path: str, body: dict[str, Any] | None = None):
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda request, user_store=None: user,
        )
        clear_all_limiters()
        raw = json.dumps(body).encode() if body is not None else b""
        request = MagicMock()
        request.command = "POST" if body is not None else "GET"
        request.headers = {"Host": "localhost", "Content-Length": str(len(raw))}
        request.rfile = io.BytesIO(raw)
        request.client_address = ("10.0.0.8", 4000)
        return asyncio.run(handler.handle(path, {}, request))

    return _call


def _body(result) -> Any:
    raw = result.body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _text(result) -> str:
    raw = result.body
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)


def _slug(storage: DebateStorage, debate_id: str) -> str:
    with storage.connection() as conn:
        return conn.execute("SELECT slug FROM debates WHERE id = ?", (debate_id,)).fetchone()[0]


def _paths(debate_id: str) -> list[str]:
    paths = [f"/api/v1/debates/{debate_id}/{endpoint}" for endpoint in ENDPOINTS]
    return [*paths, f"/api/v1/explain/{debate_id}"]


class TestPerDebateRoutes:
    def test_other_org_gets_the_missing_debate_404(self, call):
        for on_da, on_dx in zip(_paths(DA), _paths(DX), strict=True):
            for path in (on_da, on_dx):
                result = call(USER_B, path)
                assert (result.status_code, _body(result)) == (404, NOT_FOUND), path

    def test_owner_reads_explanations(self, call):
        for path in _paths(DA):
            result = call(USER_A, path)
            assert result.status_code == 200, (path, _text(result))
        evidence = call(USER_A, f"/api/v1/debates/{DA}/evidence")
        assert _body(evidence)["debate_id"] == DA

    def test_anonymous_gets_401_and_no_org_gets_403(self, call):
        for path in _paths(DA):
            anonymous = call(ANON, path)
            no_org = call(USER_NO_ORG, path)
            assert anonymous.status_code == 401, path
            assert DA_TASK not in _text(anonymous)
            assert (no_org.status_code, _body(no_org)["code"]) == (403, "org_required"), path

    def test_null_org_debate_is_invisible(self, call):
        for user in (USER_A, USER_B):
            for path in _paths(DN):
                result = call(user, path)
                assert (result.status_code, _body(result)) == (404, NOT_FOUND), path

    def test_public_debate_is_readable_outside_its_org(self, call):
        result = call(USER_B, f"/api/v1/debates/{DP}/evidence")

        assert result.status_code == 200
        assert _body(result)["debate_id"] == DP

    def test_cached_explanation_is_not_served_to_another_org(self, call):
        assert call(USER_A, f"/api/v1/debates/{DA}/explanation").status_code == 200
        assert explain_mod._get_cached_decision(DA) is not None

        result = call(USER_B, f"/api/v1/debates/{DA}/explanation")

        assert (result.status_code, _body(result)) == (404, NOT_FOUND)

    def test_server_storage_is_used_instead_of_the_default_store(self, call, tmp_path):
        """A same-id debate of org B in the default store neither grants nor feeds reads."""
        other = DebateStorage(str(tmp_path / "aragora_debates.db"))
        other.save_dict(_debate(DA, "Same id stored by org B elsewhere"), org_id=ORG_B)

        with patch("aragora.server.storage.get_debates_db", return_value=other):
            as_b = call(USER_B, f"/api/v1/debates/{DA}/explanation")
            as_a = call(USER_A, f"/api/v1/debates/{DA}/explanation")

        assert (as_b.status_code, _body(as_b)) == (404, NOT_FOUND)
        assert as_a.status_code == 200
        assert "Same id stored by org B" not in _text(as_a)


class TestSlugRefs:
    """Explanations are built and cached for the debate id the access check resolved."""

    def test_owner_reads_by_slug_like_by_id(self, call, storage):
        slug = _slug(storage, DA)
        for by_id, by_slug in zip(_paths(DA), _paths(slug), strict=True):
            id_result, slug_result = call(USER_A, by_id), call(USER_A, by_slug)
            assert id_result.status_code == 200, by_id
            assert (slug_result.status_code, _text(slug_result)) == (200, _text(id_result))
        assert set(explain_mod._decision_cache._cache) == {DA}

    def test_hidden_slugs_get_the_missing_debate_404(self, call, storage):
        for user, debate_id in ((USER_B, DA), (USER_A, DN), (USER_B, DN)):
            for path in _paths(_slug(storage, debate_id)):
                result = call(user, path)
                assert (result.status_code, _body(result)) == (404, NOT_FOUND), path
        slug_path = f"/api/v1/debates/{_slug(storage, DA)}/explanation"
        assert call(ANON, slug_path).status_code == 401
        assert _body(call(USER_NO_ORG, slug_path))["code"] == "org_required"

    def test_a_slug_never_shadows_another_orgs_id(self, call, storage):
        with storage.connection() as conn:
            conn.execute("UPDATE debates SET slug = ? WHERE id = ?", (DB, DA))

        as_a = call(USER_A, f"/api/v1/debates/{DB}/evidence")
        as_b = call(USER_B, f"/api/v1/debates/{DB}/evidence")

        assert (as_a.status_code, _body(as_a)) == (404, NOT_FOUND)
        assert (as_b.status_code, _body(as_b)["debate_id"]) == (200, DB)


class TestBatchAndCompare:
    @pytest.fixture
    def run_batches_inline(self, monkeypatch, handler):
        """Process batch jobs to completion before the create call returns."""

        def _start(job):
            worker = threading.Thread(target=asyncio.run, args=(handler._process_batch(job),))
            worker.start()
            worker.join(timeout=30)

        monkeypatch.setattr(handler, "_start_batch_processing", _start)

    def test_batch_reports_other_org_debates_as_missing(self, call, run_batches_inline):
        created = call(USER_B, "/api/v1/explainability/batch", {"debate_ids": [DA, DB, DN, DX]})
        assert created.status_code == 202
        batch_id = _body(created)["batch_id"]

        results = call(USER_B, f"/api/v1/explainability/batch/{batch_id}/results")

        assert results.status_code == 200
        by_id = {r["debate_id"]: r for r in _body(results)["results"]}
        assert by_id[DB]["status"] == "success"
        missing_error = by_id[DX]["error"].replace(DX, "ID")
        for hidden in (DA, DN, DX):
            assert by_id[hidden]["status"] == "not_found"
            assert by_id[hidden]["error"].replace(hidden, "ID") == missing_error
        assert DA_TASK not in _text(results)

    def test_batch_belongs_to_the_creating_org(self, call, run_batches_inline):
        body = {"debate_ids": [DA], "options": {"_owner_org_id": ORG_B}}
        batch_id = _body(call(USER_A, "/api/v1/explainability/batch", body))["batch_id"]

        for suffix in ("status", "results"):
            own = call(USER_A, f"/api/v1/explainability/batch/{batch_id}/{suffix}")
            other = call(USER_B, f"/api/v1/explainability/batch/{batch_id}/{suffix}")
            missing = call(USER_B, f"/api/v1/explainability/batch/batch-missing00/{suffix}")
            assert own.status_code == 200, suffix
            assert other.status_code == 404, suffix
            assert _body(other)["error"].replace(batch_id, "ID") == _body(missing)["error"].replace(
                "batch-missing00", "ID"
            )

    def test_batch_and_compare_build_slugs_by_the_resolved_id(
        self, call, storage, run_batches_inline
    ):
        slug = _slug(storage, DA)
        batch_id = _body(call(USER_A, "/api/v1/explainability/batch", {"debate_ids": [slug]}))[
            "batch_id"
        ]
        results = call(USER_A, f"/api/v1/explainability/batch/{batch_id}/results")
        compared = call(USER_A, "/api/v1/explainability/compare", {"debate_ids": [slug, DP]})

        assert [r["status"] for r in _body(results)["results"]] == ["success"]
        assert compared.status_code == 200
        assert set(explain_mod._decision_cache._cache) == {DA, DP}

    def test_batch_routes_require_an_org(self, call):
        for user, status in ((ANON, 401), (USER_NO_ORG, 403)):
            created = call(user, "/api/v1/explainability/batch", {"debate_ids": [DA]})
            status_route = call(user, "/api/v1/explainability/batch/batch-any/status")
            assert created.status_code == status
            assert status_route.status_code == status

    def test_compare_counts_other_org_debates_as_missing(self, call):
        as_b = call(USER_B, "/api/v1/explainability/compare", {"debate_ids": [DA, DB, DN]})
        as_a = call(USER_A, "/api/v1/explainability/compare", {"debate_ids": [DA, DP]})
        public = call(USER_B, "/api/v1/explainability/compare", {"debate_ids": [DB, DP]})

        assert as_b.status_code == 404
        assert DA_TASK not in _text(as_b)
        assert as_a.status_code == 200
        assert _body(as_a)["debates_compared"] == [DA, DP]
        assert public.status_code == 200
        assert (
            call(ANON, "/api/v1/explainability/compare", {"debate_ids": [DA, DP]}).status_code
            == 401
        )
