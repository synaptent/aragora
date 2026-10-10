"""Live-dispatch tests for the /api/v1/index route family.

KnowledgeHandler lists /api/v1/index, /api/v1/index/embed-batch and
/api/v1/index/search in ROUTES, so the route index sends them to it. These
tests build the route index from the full HANDLER_REGISTRY with the real
``_init_handlers`` and send requests through the real ``_try_modular_handler``,
so first-match ownership and the dispatcher's own 500 fallbacks are exercised.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
from collections.abc import Callable, Iterator, Sequence
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.core.embeddings.service import UnifiedEmbeddingService
from aragora.ml.embeddings import LocalEmbeddingService
from aragora.server.handler_registry import HandlerRegistryMixin, get_route_index
from aragora.server.handlers.base import error_response
from aragora.server.handlers.knowledge import ml as ml_handler_module
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
    _ml_handler: Any  # set by _init_handlers


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


class _FakeLocalService:
    """Stands in for aragora.ml's LocalEmbeddingService without loading a model."""

    model_name = "fake-minilm"
    dimension = 4

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [byte / 255 for byte in digest[: self.dimension]]

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return [self.embed(text) for text in texts]


def _refuse_provider_service(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("embed-batch must not build a provider embedding service")


@pytest.fixture
def install_local_service(monkeypatch) -> Iterator[Callable[[Any], Any]]:
    """Put one service behind aragora.ml.get_embedding_service, the seam both embed routes use."""
    ml_handler_module._clear_ml_components()
    ml_handler_module._ml_limiter.clear()
    monkeypatch.setattr(
        "aragora.core.embeddings.service.get_embedding_service", _refuse_provider_service
    )

    def install(service: Any) -> Any:
        monkeypatch.setattr("aragora.ml.get_embedding_service", lambda *a, **k: service)
        return service

    yield install
    ml_handler_module._clear_ml_components()


@pytest.fixture
def local_service(install_local_service) -> _FakeLocalService:
    return install_local_service(_FakeLocalService())


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


def _ml_embed(registry_cls: type[_RegistryMixin], body: dict[str, Any]) -> tuple[int, Any]:
    # The registry passes MLHandler.handle_post the query dict rather than the JSON
    # body, so /api/v1/ml/embed is called here with the parsed body, as its own tests do.
    http = MagicMock()
    http.client_address = ("127.0.0.1", 12345)
    result = registry_cls._ml_handler.handle_post("/api/v1/ml/embed", body, http)
    return result.status_code, json.loads(result.body)


@pytest.mark.parametrize("path", INDEX_PATHS)
def test_index_routes_resolve_to_knowledge_handler(registry_cls, path: str) -> None:
    match = get_route_index().get_handler(path)
    assert match is not None
    attr_name, handler = match
    assert attr_name == "_knowledge_handler"
    assert isinstance(handler, KnowledgeHandler)


@pytest.mark.parametrize("send_active_model", [False, True])
def test_embed_batch_and_ml_embed_return_the_same_vectors(
    registry_cls, local_service, send_active_model: bool
) -> None:
    texts = ["alpha", "beta", "gamma"]
    payload: dict[str, Any] = {"texts": texts, "batch_size": 2}
    if send_active_model:
        payload["model"] = local_service.model_name
    status, batch = _dispatch(registry_cls, "POST", "/api/v1/index/embed-batch", payload)
    assert status == 200, batch
    status, single = _ml_embed(registry_cls, {"texts": texts})
    assert status == 200, single

    assert batch["embeddings"] == single["embeddings"]
    assert batch["dimension"] == single["dimension"] == local_service.dimension
    assert batch["count"] == 3
    assert batch["batch_count"] == 2
    assert local_service.batches[:2] == [["alpha", "beta"], ["gamma"]]
    assert batch["model"] == local_service.model_name
    assert "provider" not in batch


def test_embed_batch_never_builds_the_provider_embedding_service(
    registry_cls, local_service, monkeypatch
) -> None:
    monkeypatch.setattr(UnifiedEmbeddingService, "__init__", _refuse_provider_service)
    status, body = _dispatch(
        registry_cls, "POST", "/api/v1/index/embed-batch", {"texts": ["alpha"]}
    )
    assert status == 200, body
    assert body["embeddings"] == [local_service.embed("alpha")]


def _raise_os_error(*args: Any, **kwargs: Any) -> Any:
    raise OSError("model download failed")


@pytest.mark.parametrize(
    "sentence_transformer",
    [None, _raise_os_error],
    ids=["dependency-missing", "model-cannot-load"],
)
def test_both_embed_routes_answer_503_when_the_local_model_cannot_load(
    registry_cls, install_local_service, monkeypatch, sentence_transformer: Any
) -> None:
    monkeypatch.setattr("aragora.ml.embeddings.SentenceTransformer", sentence_transformer)
    install_local_service(LocalEmbeddingService())
    batch_status, batch = _dispatch(
        registry_cls, "POST", "/api/v1/index/embed-batch", {"texts": ["alpha"]}
    )
    embed_status, single = _ml_embed(registry_cls, {"texts": ["alpha"]})
    assert batch_status == embed_status == 503, (batch, single)
    assert batch == single
    assert "embeddings" not in batch


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
        {"texts": ["a"], "batch_size": 101},
        {"texts": ["a"], "batch_size": "4"},
        {"texts": ["a"], "batch_size": 4.0},
        {"texts": ["a"] * 1001},
        {"texts": ["a"], "model": "some-other-model"},
    ],
)
def test_embed_batch_rejects_invalid_payload(registry_cls, local_service, payload) -> None:
    status, body = _dispatch(registry_cls, "POST", "/api/v1/index/embed-batch", payload)
    assert status == 400, body


@pytest.fixture
def counted_service_getter(install_local_service, monkeypatch) -> MagicMock:
    getter = MagicMock(return_value=_FakeLocalService())
    monkeypatch.setattr("aragora.ml.get_embedding_service", getter)
    return getter


@pytest.mark.parametrize(
    ("text", "status"),
    [
        pytest.param("x" * 2000, 200, id="ascii-at-cap"),
        pytest.param("x" * 2001, 400, id="ascii-over"),
        # Two-byte "é": 1,000 characters are 2,000 bytes; 1,001 characters are 2,001.
        pytest.param("\u00e9" * 1000, 200, id="two-byte-at-cap"),
        pytest.param("\u00e9" * 1000 + "x", 400, id="two-byte-over"),
        # Three-byte CJK: 667 characters are 2,001 bytes, far under 2,000 characters.
        pytest.param("\u4e2d" * 666 + "xx", 200, id="cjk-at-cap"),
        pytest.param("\u4e2d" * 667, 400, id="cjk-over"),
    ],
)
def test_embed_batch_caps_each_text_at_2000_utf8_bytes(
    registry_cls, counted_service_getter, text: str, status: int
) -> None:
    assert len(text.encode("utf-8")) == (2000 if status == 200 else 2001)
    payload = {"texts": ["short", text]}
    got, body = _dispatch(registry_cls, "POST", "/api/v1/index/embed-batch", payload)
    assert got == status, body
    if status == 200:
        assert body["count"] == 2
    else:
        assert body["error"] == "Each text may be at most 2000 bytes of UTF-8"
        counted_service_getter.assert_not_called()


def test_embed_batch_rejects_a_lone_surrogate_before_the_service(
    registry_cls, counted_service_getter
) -> None:
    # JSON "\ud800" decodes to a lone surrogate, which no tokenizer can encode.
    payload = {"texts": ["short", "a\ud800b"]}
    status, body = _dispatch(registry_cls, "POST", "/api/v1/index/embed-batch", payload)
    assert status == 400, body
    assert body["error"] == "Each text must be valid Unicode text (no lone surrogates)"
    counted_service_getter.assert_not_called()


@pytest.mark.parametrize(("count", "status"), [(100, 200), (101, 400)])
def test_embed_batch_caps_the_request_at_100_texts(
    registry_cls, counted_service_getter, count: int, status: int
) -> None:
    payload = {"texts": [f"text {i}" for i in range(count)]}
    got, body = _dispatch(registry_cls, "POST", "/api/v1/index/embed-batch", payload)
    assert got == status, body
    if status == 200:
        assert body["count"] == 100
    else:
        assert body["error"] == "At most 100 texts per request"
        counted_service_getter.assert_not_called()


def test_embed_batch_requires_a_json_content_type(registry_cls, local_service) -> None:
    status, body = _dispatch(
        registry_cls,
        "POST",
        "/api/v1/index/embed-batch",
        {"texts": ["alpha"]},
        headers={"Content-Type": "text/plain"},
    )
    assert status == 415, body


@pytest.mark.parametrize("failure", [RuntimeError("encode failed"), OSError("device lost")])
def test_embed_batch_reports_an_encode_failure_as_503(
    registry_cls, local_service, monkeypatch, failure: Exception
) -> None:
    # 5xx messages from error_response are rewritten in production; this one must not be.
    monkeypatch.setenv("ARAGORA_ENV", "production")
    monkeypatch.setattr(local_service, "embed_batch", MagicMock(side_effect=failure))
    status, body = _dispatch(
        registry_cls, "POST", "/api/v1/index/embed-batch", {"texts": ["alpha"]}
    )
    assert status == 503, body
    assert body == {
        "error": {"message": "Embedding service unavailable", "code": "service_unavailable"}
    }


def test_embed_batch_short_model_reply_answers_503(
    registry_cls, local_service, monkeypatch
) -> None:
    monkeypatch.setattr(local_service, "embed_batch", lambda texts: [[1.0, 0.0, 0.0, 0.0]])
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
    registry_cls, local_service, role: str, request_name: str, expected: int
) -> None:
    """A real access token per role, the real RBAC v2 checker and the real dispatcher."""
    method, path, payload = _INDEX_ROLE_REQUESTS[request_name]
    token = create_access_token(user_id=f"jwt-{role}", email=f"{role}@example.com", role=role)
    # Keep token validation off whatever revocation database the host environment points at.
    with patch("aragora.billing.auth.blacklist.is_token_revoked_persistent", return_value=False):
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
        assert body["model"] == local_service.model_name
