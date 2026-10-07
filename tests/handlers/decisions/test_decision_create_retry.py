"""A10 decision create and retry with real JWTs (VAL-PLAN-006).

``DecisionHandler`` runs with real access tokens, the real ``DecisionRequest``
parsing and a real ``DecisionResultStore`` on disk; only the router, which
would run a debate, is replaced. An org owner can create a decision, and a
decision that failed, timed out or ended without success can be retried by
its owner with the original request. A caller without ``decisions:create``
is refused, and another org retrying the decision gets the same answer as
for a missing id.
"""

from __future__ import annotations

import asyncio
import io
import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from aragora.core.decision import DecisionRequest, DecisionResult, DecisionType
from aragora.server.handlers.decisions import decision as decision_module
from aragora.server.handlers.decisions.decision import DecisionHandler
from aragora.storage.decision_result_store import DecisionResultStore

pytestmark = pytest.mark.no_auto_auth

ORG_A = "org-a-decisions"
ORG_B = "org-b-decisions"
NOT_FOUND_BODY = {"error": "Decision not found", "code": "not_found"}

CREATE_BODY: dict[str, Any] = {
    "content": "Should vendors rotate their API keys every year?",
    "decision_type": "debate",
    "config": {"agents": ["grok", "openai-api"], "rounds": 1, "consensus": "majority"},
    "documents": ["doc-a-vendor-policy"],
    "response_channels": [
        {"platform": "webhook", "webhook_url": "https://hooks.example.test/decisions"},
        {"platform": "slack", "channel_id": "C-vendor-review", "thread_id": "171.42"},
    ],
    "context": {
        "user_id": "spoofed-user",
        "workspace_id": ORG_B,
        "tags": ["vendor-review"],
        "metadata": {"topic": "key rotation"},
    },
}

_client_ips = (f"10.30.{n // 250}.{n % 250 + 1}" for n in itertools.count())


@pytest.fixture(autouse=True)
def _isolated_auth(monkeypatch):
    """Real JWTs and the stock (unset) static API token."""
    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store
    from aragora.server import auth as server_auth

    for name in ("ARAGORA_ENV", "ARAGORA_ENVIRONMENT", "ARAGORA_SECRETS_STRICT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "decision-create-retry-secret-" + "s" * 32)
    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())
    monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)


def _bearer(user_id: str, org_id: str, role: str) -> str:
    from aragora.billing.auth.tokens import create_access_token

    return "Bearer " + create_access_token(user_id, f"{user_id}@example.test", org_id, role)


class _Request:
    """The parts of the HTTP request handler that DecisionHandler reads."""

    def __init__(self, authorization: str, body: dict[str, Any] | None = None):
        raw = json.dumps(body or {}).encode()
        self.headers = {
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
        }
        self.rfile = io.BytesIO(raw)
        self.client_address = (next(_client_ips), 50124)


class _Router:
    """Stands in for DecisionRouter: records each request and plays back outcomes."""

    def __init__(self, *outcomes: Any):
        self._outcomes = list(outcomes)
        self.requests: list[DecisionRequest] = []

    async def route(self, request: DecisionRequest) -> DecisionResult:
        self.requests.append(request)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return DecisionResult(
            request_id=request.request_id,
            decision_type=request.decision_type,
            answer=outcome,
            confidence=0.8 if outcome else 0.0,
            consensus_reached=bool(outcome),
            success=bool(outcome),
            error=None if outcome else "No consensus",
        )


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> DecisionResultStore:
    real = DecisionResultStore(db_path=tmp_path / "decision_results.db", ttl_seconds=3600)

    class _Factory:
        def get(self) -> DecisionResultStore:
            return real

    monkeypatch.setattr(decision_module, "_decision_result_store", _Factory())
    monkeypatch.setattr(decision_module, "_decision_results_fallback", {})
    return real


def _use_router(monkeypatch, router: _Router) -> None:
    monkeypatch.setattr(decision_module, "_get_decision_router", lambda ctx=None: router)


def _post(path: str, authorization: str, body: dict[str, Any] | None = None):
    request = _Request(authorization, body)
    result = asyncio.run(DecisionHandler(ctx={}).handle_post(path, {}, request))
    assert result is not None
    return result.status_code, json.loads(result.body.decode("utf-8"))


def _on_disk(tmp_path: Path, request_id: str) -> dict[str, Any] | None:
    return DecisionResultStore(db_path=tmp_path / "decision_results.db").get(request_id)


def _created_id(store: DecisionResultStore, org_id: str) -> str:
    [entry] = store.list_recent_for_org(org_id, 10)
    return entry["request_id"]


def test_owner_create_succeeds(store, tmp_path, monkeypatch):
    router = _Router("Rotate keys yearly")
    _use_router(monkeypatch, router)

    status, body = _post("/api/v1/decisions", _bearer("user-a", ORG_A, "owner"), CREATE_BODY)

    assert status == 200, body
    assert (body["status"], body["answer"]) == ("completed", "Rotate keys yearly")
    [routed] = router.requests
    assert (routed.context.user_id, routed.context.workspace_id) == ("user-a", ORG_A)
    saved = _on_disk(tmp_path, body["request_id"])
    assert (saved["status"], saved["org_id"], saved["created_by"]) == ("completed", ORG_A, "user-a")


def test_caller_without_create_permission_is_refused(store, monkeypatch):
    router = _Router("unused")
    _use_router(monkeypatch, router)

    status, body = _post("/api/v1/decisions", _bearer("user-v", ORG_A, "viewer"), CREATE_BODY)

    assert status == 403, body
    assert router.requests == []
    assert store.count_for_org(ORG_A) == 0


@pytest.mark.parametrize(
    ("first_outcome", "create_status", "stored_status"),
    [
        (asyncio.TimeoutError(), 408, "timeout"),
        (RuntimeError("provider unavailable"), 500, "failed"),
        ("", 200, "failed"),
    ],
    ids=["timeout", "routing-error", "unsuccessful-result"],
)
def test_owner_retry_replays_the_stored_request(
    store, tmp_path, monkeypatch, first_outcome, create_status, stored_status
):
    owner = _bearer("user-a", ORG_A, "owner")
    router = _Router(first_outcome, "Rotate keys yearly")
    _use_router(monkeypatch, router)

    status, _ = _post("/api/v1/decisions", owner, CREATE_BODY)
    assert status == create_status
    original_id = _created_id(store, ORG_A)
    assert _on_disk(tmp_path, original_id)["status"] == stored_status

    status, body = _post(f"/api/v1/decisions/{original_id}/retry", owner)

    assert status == 200, body
    assert (body["status"], body["retried_from"]) == ("completed", original_id)
    first, retried = router.requests
    assert retried.content == first.content == CREATE_BODY["content"]
    assert retried.decision_type == first.decision_type == DecisionType.DEBATE
    assert retried.config.to_dict() == first.config.to_dict()
    assert (retried.config.agents, retried.config.rounds) == (["grok", "openai-api"], 1)
    assert retried.documents == ["doc-a-vendor-policy"]
    channels = [rc.to_dict() for rc in retried.response_channels]
    assert channels == [rc.to_dict() for rc in first.response_channels]
    assert [(c["platform"], c["webhook_url"], c["channel_id"]) for c in channels] == [
        ("webhook", "https://hooks.example.test/decisions", None),
        ("slack", None, "C-vendor-review"),
    ]
    assert retried.context.tags == ["vendor-review"]
    assert retried.context.metadata["topic"] == "key rotation"
    assert retried.context.metadata["retried_from"] == original_id
    assert (retried.context.user_id, retried.context.workspace_id) == ("user-a", ORG_A)
    saved = _on_disk(tmp_path, body["request_id"])
    assert (saved["status"], saved["org_id"]) == ("completed", ORG_A)
    assert saved["result"]["request"]["content"] == CREATE_BODY["content"]
    assert saved["result"]["request"]["response_channels"] == CREATE_BODY["response_channels"]
    assert "request_id" not in saved["result"]["request"]
    assert set(saved["result"]["request"]["context"]) == {"tags", "metadata"}


def test_retry_of_a_failed_retry_keeps_the_request(store, monkeypatch):
    owner = _bearer("user-a", ORG_A, "owner")
    router = _Router(RuntimeError("down"), RuntimeError("still down"), "Rotate keys yearly")
    _use_router(monkeypatch, router)

    _post("/api/v1/decisions", owner, CREATE_BODY)
    original_id = _created_id(store, ORG_A)
    status, _ = _post(f"/api/v1/decisions/{original_id}/retry", owner)
    assert status == 500
    retry_id = next(
        d["request_id"]
        for d in store.list_recent_for_org(ORG_A, 10)
        if d["request_id"] != original_id
    )

    status, body = _post(f"/api/v1/decisions/{retry_id}/retry", owner)

    assert status == 200, body
    assert router.requests[-1].content == CREATE_BODY["content"]
    assert router.requests[-1].documents == ["doc-a-vendor-policy"]


def test_other_org_retry_is_identical_to_missing(store, tmp_path, monkeypatch):
    router = _Router(RuntimeError("provider unavailable"))
    _use_router(monkeypatch, router)
    _post("/api/v1/decisions", _bearer("user-a", ORG_A, "owner"), CREATE_BODY)
    original_id = _created_id(store, ORG_A)
    before = _on_disk(tmp_path, original_id)
    other = _bearer("user-b", ORG_B, "owner")

    foreign = _post(f"/api/v1/decisions/{original_id}/retry", other)
    missing = _post("/api/v1/decisions/dec_missing0000/retry", other)

    assert foreign == missing == (404, NOT_FOUND_BODY)
    assert len(router.requests) == 1
    assert store.count_for_org(ORG_B) == 0
    assert _on_disk(tmp_path, original_id) == before
