"""Live-dispatch tests for the /api/v1/index route family.

KnowledgeHandler lists /api/v1/index, /api/v1/index/embed-batch and
/api/v1/index/search in ROUTES, so the route index sends them to it. These
tests build the route index from the full HANDLER_REGISTRY with the real
``_init_handlers`` and send requests through the real ``_try_modular_handler``,
so first-match ownership and the dispatcher's own 500 fallbacks are exercised.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import io
import json
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.core.embeddings.backends import EmbeddingBackend, HashBackend
from aragora.core.embeddings.cache import EmbeddingCache
from aragora.core.embeddings.service import UnifiedEmbeddingService, get_embedding_service
from aragora.core.embeddings.types import EmbeddingConfig
from aragora.server.handler_registry import HandlerRegistryMixin, get_route_index
from aragora.server.handlers.base import error_response
from aragora.server.handlers.knowledge_base import handler as handler_module
from aragora.server.handlers.knowledge_base.handler import (
    KnowledgeHandler,
    _knowledge_limiter,
)

INDEX_PATHS = ["/api/v1/index", "/api/v1/index/embed-batch", "/api/v1/index/search"]


class _RegistryMixin(HandlerRegistryMixin):
    _handlers_initialized = False
    _init_lock = threading.Lock()

    storage = None
    stream_emitter = None
    control_plane_stream = None
    nomic_loop_stream = None
    elo_system = None
    nomic_state_file = None
    debate_embeddings = None
    critique_store = None
    document_store = None
    persona_manager = None
    position_ledger = None
    user_store = None
    continuum_memory = None
    cross_debate_memory = None
    knowledge_mound = None


@pytest.fixture(scope="module")
def registry_cls() -> type[_RegistryMixin]:
    _RegistryMixin._init_handlers()
    assert _RegistryMixin._handlers_initialized is True
    return _RegistryMixin


@pytest.fixture(autouse=True)
def _clear_knowledge_limiter():
    _knowledge_limiter.clear()
    yield
    _knowledge_limiter.clear()


@pytest.fixture
def hash_service() -> UnifiedEmbeddingService:
    return UnifiedEmbeddingService(config=EmbeddingConfig(provider="hash", cache_enabled=False))


@pytest.fixture
def shared_embedding_cache(monkeypatch) -> EmbeddingCache:
    """A fresh process-wide embedding cache and singleton, restored after the test."""
    cache = EmbeddingCache()
    monkeypatch.setattr("aragora.core.embeddings.cache._global_cache", cache)
    monkeypatch.setattr("aragora.core.embeddings.service._global_service", None)
    return cache


class _FailingTextsBackend(EmbeddingBackend):
    """Keeps the base embed_batch, which swaps every failed text for a zero vector."""

    def __init__(self, failing: set[str]) -> None:
        super().__init__(EmbeddingConfig(dimension=8), use_circuit_breaker=False)
        self.failing = failing

    @property
    def provider_name(self) -> str:
        return "failing"

    @property
    def model_name(self) -> str:
        return "failing-model"

    async def embed(self, text: str) -> list[float]:
        if text in self.failing:
            raise ConnectionError(f"provider outage for {text!r}")
        return [1.0] * self.dimension


def _dispatch(
    registry_cls: type[_RegistryMixin],
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    instance: Any = registry_cls()
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    instance.command = method
    instance.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
    instance.headers.update(headers or {})
    instance.rfile = io.BytesIO(raw)
    instance.wfile = io.BytesIO()
    instance.send_response = MagicMock()
    instance.send_header = MagicMock()
    instance.end_headers = MagicMock()
    instance._add_cors_headers = MagicMock()
    instance._add_security_headers = MagicMock()
    instance._add_trace_headers = MagicMock()
    instance._auth_context = None
    instance.client_address = ("127.0.0.1", 12345)
    with (
        patch("aragora.server.handler_registry.HANDLERS_AVAILABLE", True),
        patch(
            "aragora.server.middleware.rate_limit.should_apply_default_rate_limit",
            return_value=False,
        ),
    ):
        handled = instance._try_modular_handler(path, {})
    assert handled is True, f"{method} {path} was not handled"
    status = instance.send_response.call_args[0][0]
    return status, json.loads(instance.wfile.getvalue() or b"{}")


@pytest.mark.parametrize("path", INDEX_PATHS)
def test_index_routes_resolve_to_knowledge_handler(registry_cls, path: str) -> None:
    match = get_route_index().get_handler(path)
    assert match is not None
    attr_name, handler = match
    assert attr_name == "_knowledge_handler"
    assert isinstance(handler, KnowledgeHandler)


@pytest.mark.parametrize("send_active_model", [False, True])
def test_embed_batch_returns_service_embeddings(
    registry_cls, hash_service, send_active_model: bool
) -> None:
    texts = ["alpha", "beta", "gamma"]
    payload: dict[str, Any] = {"texts": texts, "batch_size": 2}
    if send_active_model:
        payload["model"] = hash_service.model
    with patch("aragora.core.embeddings.service.get_embedding_service", return_value=hash_service):
        status, body = _dispatch(registry_cls, "POST", "/api/v1/index/embed-batch", payload)
    assert status == 200, body
    expected = asyncio.run(hash_service.embed_batch_raw(texts))
    assert body["embeddings"] == expected
    assert body["count"] == 3
    assert body["dimension"] == len(expected[0]) > 0
    assert body["batch_count"] == 2
    assert body["provider"] == "hash"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"texts": []},
        {"texts": "alpha"},
        {"texts": ["ok", 7]},
        {"texts": ["ok", ""]},
        {"texts": ["a"], "batch_size": 0},
        {"texts": ["a"], "batch_size": True},
        {"texts": ["a"] * 1001},
        {"texts": ["a"], "model": "some-other-model"},
    ],
)
def test_embed_batch_rejects_invalid_payload(registry_cls, hash_service, payload) -> None:
    with patch("aragora.core.embeddings.service.get_embedding_service", return_value=hash_service):
        status, body = _dispatch(registry_cls, "POST", "/api/v1/index/embed-batch", payload)
    assert status == 400, body


@pytest.mark.parametrize(("length", "status"), [(8192, 200), (8193, 400)])
def test_embed_batch_caps_each_text_at_8192_characters(
    registry_cls, hash_service, length: int, status: int
) -> None:
    payload = {"texts": ["short", "x" * length]}
    with patch(
        "aragora.core.embeddings.service.get_embedding_service", return_value=hash_service
    ) as get_service:
        got, body = _dispatch(registry_cls, "POST", "/api/v1/index/embed-batch", payload)
    assert got == status, body
    if status == 400:
        assert "8192 characters" in body["error"]
        get_service.assert_not_called()


@pytest.mark.parametrize(("count", "status"), [(100, 200), (101, 400)])
def test_embed_batch_caps_the_request_at_100_texts(
    registry_cls, hash_service, count: int, status: int
) -> None:
    payload = {"texts": [f"text {i}" for i in range(count)]}
    with patch(
        "aragora.core.embeddings.service.get_embedding_service", return_value=hash_service
    ) as get_service:
        got, body = _dispatch(registry_cls, "POST", "/api/v1/index/embed-batch", payload)
    assert got == status, body
    if status == 200:
        assert body["count"] == 100
    else:
        assert body["error"] == "At most 100 texts per request"
        get_service.assert_not_called()


@pytest.mark.parametrize(("count", "status"), [(125, 200), (126, 400)])
def test_embed_batch_caps_the_request_at_one_million_characters(
    registry_cls, hash_service, monkeypatch, count: int, status: int
) -> None:
    # 100 texts of at most 8,192 characters cannot reach the total, so lift the
    # count cap to reach the total-characters check behind it.
    monkeypatch.setattr(handler_module, "_MAX_EMBED_BATCH_TEXTS", 1000)
    # 125 x 8000 is exactly 1,000,000 characters; every text is under the per-text cap.
    payload = {"texts": [f"{i:08d}" + "y" * 7992 for i in range(count)]}
    with patch(
        "aragora.core.embeddings.service.get_embedding_service", return_value=hash_service
    ) as get_service:
        got, body = _dispatch(registry_cls, "POST", "/api/v1/index/embed-batch", payload)
    assert got == status, body
    if status == 400:
        assert "1000000 characters" in body["error"]
        get_service.assert_not_called()


def test_embed_batch_requires_a_json_content_type(registry_cls, hash_service) -> None:
    with patch("aragora.core.embeddings.service.get_embedding_service", return_value=hash_service):
        status, body = _dispatch(
            registry_cls,
            "POST",
            "/api/v1/index/embed-batch",
            {"texts": ["alpha"]},
            headers={"Content-Type": "text/plain"},
        )
    assert status == 415, body


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("backend down"), asyncio.TimeoutError(), concurrent.futures.TimeoutError()],
)
def test_embed_batch_reports_backend_failure_as_503(
    registry_cls, monkeypatch, failure: Exception
) -> None:
    # 5xx messages from error_response are rewritten in production; this one must not be.
    monkeypatch.setenv("ARAGORA_ENV", "production")
    broken = MagicMock()
    broken.embed_batch_raw.side_effect = failure
    with patch("aragora.core.embeddings.service.get_embedding_service", return_value=broken):
        status, body = _dispatch(
            registry_cls, "POST", "/api/v1/index/embed-batch", {"texts": ["alpha"]}
        )
    assert status == 503, body
    assert body == {
        "error": {"message": "Embedding service unavailable", "code": "service_unavailable"}
    }


@pytest.mark.parametrize("failing", [{"alpha", "beta"}, {"beta"}])
def test_embed_batch_answers_503_when_the_base_backend_swallows_failures(
    registry_cls, shared_embedding_cache, monkeypatch, failing: set[str]
) -> None:
    monkeypatch.setattr(
        UnifiedEmbeddingService, "_create_backend", lambda self: _FailingTextsBackend(failing)
    )
    status, body = _dispatch(
        registry_cls, "POST", "/api/v1/index/embed-batch", {"texts": ["alpha", "beta"]}
    )
    assert status == 503, body
    assert len(shared_embedding_cache) == 0


def test_embed_batch_neither_reads_nor_writes_the_shared_embedding_cache(
    registry_cls, shared_embedding_cache, monkeypatch
) -> None:
    monkeypatch.setattr(
        UnifiedEmbeddingService, "_create_backend", lambda self: HashBackend(self.config)
    )
    shared = get_embedding_service()
    stale = [9.0] * shared.dimension
    shared_embedding_cache.set("alpha", stale)
    before = shared_embedding_cache.stats()

    status, body = _dispatch(
        registry_cls, "POST", "/api/v1/index/embed-batch", {"texts": ["alpha", "beta"]}
    )

    assert status == 200, body
    assert body["embeddings"] == asyncio.run(shared._backend.embed_batch(["alpha", "beta"]))
    assert body["embeddings"][0] != stale
    assert shared_embedding_cache.stats() == before
    assert get_embedding_service() is shared


def test_embed_batch_stops_at_the_overall_time_budget(registry_cls, monkeypatch) -> None:
    monkeypatch.setattr(handler_module, "_EMBED_BATCH_BUDGET_SECONDS", 0.2, raising=False)
    calls: list[list[str]] = []

    class _SlowService:
        model = "slow-model"
        provider = "slow"

        async def embed_batch_raw(self, batch: list[str]) -> list[list[float]]:
            calls.append(batch)
            await asyncio.sleep(0.05)
            return [[1.0] for _ in batch]

    texts = [f"t{i}" for i in range(40)]
    with patch(
        "aragora.core.embeddings.service.get_embedding_service", return_value=_SlowService()
    ):
        status, body = _dispatch(
            registry_cls, "POST", "/api/v1/index/embed-batch", {"texts": texts, "batch_size": 1}
        )
    assert status == 503, body
    assert len(calls) < len(texts)


def test_embed_batch_short_backend_reply_answers_503(registry_cls, hash_service) -> None:
    backend = hash_service._backend
    real_embed_batch = backend.embed_batch

    async def _short_reply(texts: list[str]) -> list[list[float]]:
        return (await real_embed_batch(texts))[:-1]

    with (
        patch.object(backend, "embed_batch", _short_reply),
        patch("aragora.core.embeddings.service.get_embedding_service", return_value=hash_service),
    ):
        status, body = _dispatch(
            registry_cls, "POST", "/api/v1/index/embed-batch", {"texts": ["alpha", "beta"]}
        )
    assert status == 503, body


def test_list_indexes_returns_empty_list(registry_cls) -> None:
    status, body = _dispatch(registry_cls, "GET", "/api/v1/index")
    assert status == 200, body
    assert body == {"indexes": [], "count": 0}


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/index", {"name": "docs", "metric": "cosine"}),
        ("/api/v1/index/search", {"query": "safety", "index_name": "docs", "top_k": 3}),
    ],
)
def test_create_and_search_answer_501_not_implemented(
    registry_cls, monkeypatch, path: str, payload: dict[str, Any]
) -> None:
    # 5xx messages from error_response are rewritten in production; this one must not be.
    monkeypatch.setenv("ARAGORA_ENV", "production")
    status, body = _dispatch(registry_cls, "POST", path, payload)
    assert status == 501, body
    assert set(body) == {"error"}, body
    assert body["error"]["code"] == "not_implemented"
    message = body["error"]["message"]
    assert "not implemented" in message.lower()

    # Same nested envelope that error_response(..., code=...) builds outside production.
    monkeypatch.delenv("ARAGORA_ENV")
    envelope = error_response(message, 501, code="not_implemented")
    assert body == json.loads(envelope.body)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/index"),
        ("POST", "/api/v1/index"),
        ("DELETE", "/api/v1/index"),
        ("GET", "/api/v1/index/embed-batch"),
        ("GET", "/api/v1/index/search"),
        ("PUT", "/api/v1/index/search"),
    ],
)
def test_no_index_request_ends_in_handler_no_result(registry_cls, method: str, path: str) -> None:
    status, body = _dispatch(registry_cls, method, path, {"name": "docs"})
    assert status != 500, body
    assert body.get("code") != "handler_no_result"


@pytest.mark.parametrize(
    ("method", "path"), [("DELETE", "/api/v1/index"), ("GET", "/api/v1/index/search")]
)
def test_unsupported_methods_answer_405(registry_cls, method: str, path: str) -> None:
    status, body = _dispatch(registry_cls, method, path, {"name": "docs"})
    assert status == 405, body


def test_list_requires_authentication(registry_cls) -> None:
    with patch.object(
        KnowledgeHandler,
        "require_auth_or_error",
        return_value=(None, error_response("Authentication required", 401)),
    ):
        status, body = _dispatch(registry_cls, "GET", "/api/v1/index")
    assert status == 401, body


_INDEX_ROLE_REQUESTS: dict[str, tuple[str, str, dict[str, Any] | None]] = {
    "list": ("GET", "/api/v1/index", None),
    "create": ("POST", "/api/v1/index", {"name": "docs"}),
    "search": ("POST", "/api/v1/index/search", {"query": "q"}),
    "embed": ("POST", "/api/v1/index/embed-batch", {"texts": ["a"]}),
}
# RBAC v2: owner, admin and member hold knowledge.read; only owner holds
# knowledge.write; viewer holds neither. Search is a read, create and embed are writes.
_INDEX_ROLE_MATRIX: dict[str, dict[str, int]] = {
    "owner": {"list": 200, "create": 501, "search": 501, "embed": 200},
    "admin": {"list": 200, "create": 403, "search": 501, "embed": 403},
    "member": {"list": 200, "create": 403, "search": 501, "embed": 403},
    "viewer": {"list": 403, "create": 403, "search": 403, "embed": 403},
}


@pytest.mark.no_auto_auth
@pytest.mark.parametrize(
    ("role", "request_name", "expected"),
    [
        (role, request_name, status)
        for role, cells in _INDEX_ROLE_MATRIX.items()
        for request_name, status in cells.items()
    ],
)
def test_real_jwt_roles_follow_rbac_v2(
    registry_cls, hash_service, role: str, request_name: str, expected: int
) -> None:
    """A real access token per role, the real RBAC v2 checker and the real dispatcher."""
    method, path, payload = _INDEX_ROLE_REQUESTS[request_name]
    token = create_access_token(user_id=f"jwt-{role}", email=f"{role}@example.com", role=role)
    # Keep token validation off whatever revocation database the host environment points at.
    with (
        patch("aragora.billing.auth.blacklist.is_token_revoked_persistent", return_value=False),
        patch("aragora.core.embeddings.service.get_embedding_service", return_value=hash_service),
    ):
        status, body = _dispatch(
            registry_cls, method, path, payload, headers={"Authorization": f"Bearer {token}"}
        )
    assert status == expected, body
    if expected == 403:
        assert body == {"error": "Permission denied"}
    elif expected == 501:
        assert body["error"]["code"] == "not_implemented"
    elif request_name == "list":
        assert body == {"indexes": [], "count": 0}
    else:
        assert body["count"] == 1
        assert body["provider"] == "hash"
