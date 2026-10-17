"""The verified organization reaches DecisionRouter from authentication, never from a payload."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.core.decision_cache import DecisionCache
from aragora.core.decision_models import DecisionConfig, DecisionRequest
from aragora.core.decision_router import DecisionRouter
from aragora.core.decision_types import DecisionType
from aragora.knowledge import pipeline as pipeline_module
from aragora.knowledge.embeddings import InMemoryEmbeddingService
from aragora.knowledge.fact_store import InMemoryFactStore
from aragora.rbac import RBACEnforcer
from aragora.server.handlers.decisions import decision as decision_module
from aragora.server.handlers.decisions.decision import DecisionHandler
from aragora.tenancy.record_scope import OrgScope, require_org_scope

FORGED = {"tenant_id": "victim", "workspace_id": "victim", "verified_org_id": "victim"}


def _request(org: str | None = None, content: str = "Should we expand?") -> DecisionRequest:
    request = DecisionRequest(
        content=content,
        decision_type=DecisionType.DEBATE,
        config=DecisionConfig(agents=[]),
    )
    if org:
        request.bind_verified_org(OrgScope(org_id=org, user_id="u-1", role="member"))
    return request


def test_payload_identity_never_becomes_the_verified_organization() -> None:
    body = {"content": "Q?", "verified_org_id": "victim", "_verified_org_id": "victim"}
    request = DecisionRequest.from_http({**body, "context": FORGED}, {})

    assert request.verified_org_id is None
    assert "victim" not in json.dumps(
        {k: v for k, v in request.to_dict().items() if k != "context"}
    )
    with pytest.raises(TypeError):
        DecisionRequest(content="Q?", _verified_org_id="victim")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        request.bind_verified_org("victim")  # type: ignore[arg-type]


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[DecisionRequest] = []

    async def route(self, request: DecisionRequest) -> Any:
        self.requests.append(request)
        return SimpleNamespace(
            success=True,
            decision_type=request.decision_type,
            answer="",
            confidence=0.0,
            consensus_reached=False,
            reasoning=None,
            evidence_used=[],
            duration_seconds=0.0,
            error=None,
            to_dict=dict,
        )


async def _allow(*_: Any, **__: Any) -> None:
    return None


def _http(token: str | None, body: dict[str, Any]) -> Any:
    raw = json.dumps(body).encode()
    headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return SimpleNamespace(headers=headers, rfile=io.BytesIO(raw), client_address=("127.0.0.1", 1))


async def test_decision_ingress_binds_the_authenticated_organization_not_the_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(decision_module, "_get_decision_router", lambda ctx=None: recorder)
    monkeypatch.setattr(decision_module, "_save_result", lambda *a, **k: True)
    monkeypatch.setattr(RBACEnforcer, "require", _allow)  # authorization, not identity
    token = create_access_token("u-1", "u1@example.com", "acme", role="owner")
    body = {"content": "Should we expand?", "context": FORGED}

    result = await DecisionHandler({}).handle_post("/api/v1/decisions", {}, _http(token, body))

    assert result.status_code == 200
    assert [r.verified_org_id for r in recorder.requests] == ["acme"]


async def test_retry_binds_the_retrying_callers_organization_not_the_stored_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    stored = {"status": "failed", "result": {"request": {"content": "Q?", "context": FORGED}}}
    monkeypatch.setattr(decision_module, "_get_decision_router", lambda ctx=None: recorder)
    monkeypatch.setattr(decision_module, "_get_result", lambda request_id, org_id: stored)
    monkeypatch.setattr(decision_module, "_save_result", lambda *a, **k: True)
    http = _http(create_access_token("u-1", "u1@example.com", "acme", role="owner"), {})
    scope, _ = require_org_scope(http)
    assert scope is not None

    result = await DecisionHandler({})._retry_decision("dec_1", http, scope)

    assert result.status_code == 200
    assert [r.verified_org_id for r in recorder.requests] == ["acme"]


# require_org_scope already denies these callers; kept as a regression guard for the
# precondition the binding relies on (no request is built, so none reaches the router).
@pytest.mark.parametrize(("token", "status"), [(None, 401), ("no-org", 403), ("forged", 401)])
async def test_ingress_without_a_verified_organization_is_denied_before_the_router(
    monkeypatch: pytest.MonkeyPatch, token: str | None, status: int
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(decision_module, "_get_decision_router", lambda ctx=None: recorder)
    if token == "no-org":
        token = create_access_token("u-1", "u1@example.com", None, role="owner")
    body = {"content": "Should we expand?", "context": FORGED}

    result = await DecisionHandler({}).handle_post("/api/v1/decisions", {}, _http(token, body))

    assert result.status_code == status
    assert recorder.requests == []


class _Arena:
    environments: list[Any] = []

    def __init__(self, environment: Any, **_: Any) -> None:
        _Arena.environments.append(environment)

    async def run(self) -> Any:
        return SimpleNamespace(final_answer="ok", confidence=0.9, consensus_reached=True)


class _Mound:
    async def query(self, **kwargs: Any) -> Any:
        items = [SimpleNamespace(content="acme roadmap", metadata={"org_id": "acme"})]
        return SimpleNamespace(items=items, total_count=1)

    async def close(self) -> None:
        return None


async def test_unverified_request_gets_no_knowledge_mound_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_pipeline(config: Any) -> Any:
        raise AssertionError("a pipeline was built without a verified organization")

    monkeypatch.setattr(pipeline_module, "KnowledgePipeline", _no_pipeline)
    _Arena.environments = []
    request = _request()
    request.context.tenant_id = request.context.workspace_id = "victim"

    result = await DecisionRouter(debate_engine=_Arena)._route_to_debate(request)

    assert result.success is not False
    assert _Arena.environments[0].context == ""


async def test_verified_request_reads_the_mound_as_its_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configs: list[Any] = []
    real = pipeline_module.KnowledgePipeline

    def _pipeline(config: Any) -> Any:
        configs.append(config)
        return real(
            config,
            fact_store=InMemoryFactStore(),
            embedding_service=InMemoryEmbeddingService(),
            knowledge_mound=_Mound(),
        )

    monkeypatch.setattr(pipeline_module, "KnowledgePipeline", _pipeline)
    _Arena.environments = []
    request = _request("acme")
    request.context.workspace_id = "research"

    await DecisionRouter(debate_engine=_Arena)._route_to_debate(request)

    assert [(c.org_id, c.workspace_id) for c in configs] == [("acme", "research")]
    assert "acme roadmap" in _Arena.environments[0].context


def test_cache_and_in_flight_keys_separate_verified_organizations() -> None:
    cache = DecisionCache()
    keys = {org: cache._compute_hash(_request(org)) for org in ("acme", "beta", None)}

    assert len(set(keys.values())) == 3
    assert cache._compute_hash(_request("acme")) == keys["acme"]
