"""Live-dispatch tests for the /api/v1/index route family.

KnowledgeHandler lists /api/v1/index, /api/v1/index/embed-batch and
/api/v1/index/search in ROUTES, so the route index sends them to it. These
tests build the route index from the full HANDLER_REGISTRY with the real
``_init_handlers`` and send requests through the real ``_try_modular_handler``,
so first-match ownership and the dispatcher's own 500 fallbacks are exercised.
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.core.embeddings.service import UnifiedEmbeddingService
from aragora.core.embeddings.types import EmbeddingConfig
from aragora.server.handler_registry import HandlerRegistryMixin, get_route_index
from aragora.server.handlers.base import error_response
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


class _ReadOnlyUser:
    user_id = "reader"
    permissions = {"knowledge.read"}
    roles = {"viewer"}


class _NoPermissionUser:
    user_id = "nobody"
    permissions: set[str] = set()
    roles: set[str] = set()


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


def _dispatch(
    registry_cls: type[_RegistryMixin],
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    instance: Any = registry_cls()
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    instance.command = method
    instance.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
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


def test_embed_batch_reports_backend_failure_as_503(registry_cls) -> None:
    broken = MagicMock()
    broken.embed_batch_raw.side_effect = RuntimeError("backend down")
    with patch("aragora.core.embeddings.service.get_embedding_service", return_value=broken):
        status, body = _dispatch(
            registry_cls, "POST", "/api/v1/index/embed-batch", {"texts": ["alpha"]}
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
    assert body["code"] == "not_implemented"
    assert "not implemented" in body["error"].lower()


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


def test_search_needs_only_read_permission(registry_cls) -> None:
    with patch.object(
        KnowledgeHandler, "require_auth_or_error", return_value=(_ReadOnlyUser(), None)
    ):
        status, body = _dispatch(
            registry_cls, "POST", "/api/v1/index/search", {"query": "q", "index_name": "docs"}
        )
    assert status == 501, body


@pytest.mark.parametrize("path", ["/api/v1/index", "/api/v1/index/embed-batch"])
def test_writes_still_need_write_permission(registry_cls, hash_service, path: str) -> None:
    with (
        patch.object(
            KnowledgeHandler, "require_auth_or_error", return_value=(_ReadOnlyUser(), None)
        ),
        patch("aragora.core.embeddings.service.get_embedding_service", return_value=hash_service),
    ):
        status, body = _dispatch(registry_cls, "POST", path, {"name": "docs", "texts": ["a"]})
    assert status == 403, body


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/v1/index"), ("POST", "/api/v1/index/search")]
)
def test_reads_still_need_read_permission(registry_cls, method: str, path: str) -> None:
    with patch.object(
        KnowledgeHandler, "require_auth_or_error", return_value=(_NoPermissionUser(), None)
    ):
        status, body = _dispatch(registry_cls, method, path, {"query": "q"})
    assert status == 403, body


def test_list_requires_authentication(registry_cls) -> None:
    with patch.object(
        KnowledgeHandler,
        "require_auth_or_error",
        return_value=(None, error_response("Authentication required", 401)),
    ):
        status, body = _dispatch(registry_cls, "GET", "/api/v1/index")
    assert status == 401, body
