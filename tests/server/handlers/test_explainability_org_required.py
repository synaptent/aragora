"""Explainability routes (D18) through the real server dispatch path.

Route index, auth gates, RBAC route rules and the handler's own permission
decorator, with real JWTs. A caller with no org (the static API token, or a
signed-in user without one) gets 403 ``org_required`` whatever its role;
anonymous callers get 401; an org member keeps access.
"""

from __future__ import annotations

from typing import Any

import pytest

from aragora.server.handlers.decisions import explainability as explain_mod
from aragora.server.handlers.decisions import explainability_store as store_mod
from aragora.server.handlers.decisions.explainability import ExplainabilityHandler
from aragora.storage.debate_storage import DebateStorage
from tests.server.rbac_dispatch import (
    ORG_REQUIRED_BODY,
    STATIC_TOKEN,
    build_server,
    dispatch,
    handler_for,
    isolate_auth,
    jwt,
)

ORG_A = "org-a"
DA, DP = "deb-explain-a", "deb-explain-public-a"
DA_TASK = "Explainability precedence topic for org A only"

ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", f"/api/v1/explain/{DA}", None),
    ("GET", f"/api/v1/debates/{DA}/evidence", None),
    ("POST", "/api/v1/explainability/batch", {"debate_ids": [DA]}),
    ("GET", "/api/v1/explainability/batch/batch-any/status", None),
    ("GET", "/api/v1/explainability/batch/batch-any/results", None),
    ("POST", "/api/v1/explainability/compare", {"debate_ids": [DA, DP]}),
]
ROUTE_IDS = [f"{method} {path}" for method, path, _body in ROUTES]


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


@pytest.fixture(autouse=True)
def _fresh_caches_and_limits():
    from aragora.server.handlers.utils.rate_limit import clear_all_limiters

    clear_all_limiters()
    explain_mod._decision_cache.clear()
    store_mod._batch_store = store_mod.MemoryBatchJobStore()
    yield
    clear_all_limiters()
    explain_mod._decision_cache.clear()
    store_mod._batch_store = None


@pytest.fixture
def storage(tmp_path) -> DebateStorage:
    store = DebateStorage(str(tmp_path / "debates.db"))
    store.save_dict(_debate(DA, DA_TASK), org_id=ORG_A)
    store.save_dict(_debate(DP, "Explainability topic shared publicly by A"), org_id=ORG_A)
    assert store.set_public(DP, True)
    return store


@pytest.fixture
def server(monkeypatch, storage, request):
    """The server over ``storage``; parametrize indirectly with the API token (or None)."""
    isolate_auth(monkeypatch, api_token=getattr(request, "param", STATIC_TOKEN))
    built = build_server()
    explainability = handler_for(built, f"/api/v1/explain/{DA}")
    assert isinstance(explainability, ExplainabilityHandler)
    explainability.ctx["storage"] = storage
    return built


def _send(server, route, authorization: str | None) -> tuple[int, dict[str, Any]]:
    method, path, body = route
    return dispatch(server, method, path, authorization, body=body)


@pytest.mark.no_auto_auth
class TestTokenMode:
    """``ARAGORA_API_TOKEN`` is set."""

    @pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
    def test_static_token_gets_403_org_required(self, server, route):
        assert _send(server, route, f"Bearer {STATIC_TOKEN}") == (403, ORG_REQUIRED_BODY)

    @pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
    @pytest.mark.parametrize("role", ["member", "viewer"])
    def test_jwt_user_without_org_gets_403_org_required(self, server, route, role):
        assert _send(server, route, jwt("user-solo", None, role)) == (403, ORG_REQUIRED_BODY)

    @pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
    def test_anonymous_gets_401(self, server, route):
        status, payload = _send(server, route, None)

        assert status == 401
        assert DA_TASK not in str(payload)

    @pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
    def test_org_member_keeps_the_route_rule_answer(self, server, route):
        """These routes have no RBAC route rule, so with the token set every org
        caller gets the default-deny; a missing org must not replace it."""
        status, payload = _send(server, route, jwt("user-a", ORG_A, "member"))

        assert (status, payload["code"]) == (403, "permission_denied")
        assert DA_TASK not in str(payload)


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("server", [None], indirect=True)
class TestStockMode:
    """No API token configured."""

    @pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
    @pytest.mark.parametrize("role", ["member", "viewer"])
    def test_jwt_user_without_org_gets_403_org_required(self, server, route, role):
        assert _send(server, route, jwt("user-solo", None, role)) == (403, ORG_REQUIRED_BODY)

    @pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
    def test_unknown_bearer_gets_401(self, server, route):
        assert _send(server, route, f"Bearer {STATIC_TOKEN}")[0] == 401

    def test_org_member_reads_and_compares_its_debates(self, server):
        token_a = jwt("user-a", ORG_A, "member")

        explain_status, explanation = _send(server, ROUTES[0], token_a)
        compare_status, compared = _send(server, ROUTES[5], token_a)

        assert explain_status == 200, explanation
        assert explanation["debate_id"] == DA
        assert compare_status == 200, compared
        assert compared["debates_compared"] == [DA, DP]
