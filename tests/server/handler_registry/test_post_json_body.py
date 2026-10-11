"""POST handlers whose ``handle_post`` takes the request body receive the parsed JSON body.

The server dispatches every POST as ``_try_modular_handler(path, {})``, so the
registry's second ``handle_post`` argument is an empty query dict. Handlers that
read their fields from that argument declare ``HANDLE_POST_JSON_BODY`` and the
registry passes them the parsed JSON object instead. Requests go through the
real HANDLER_REGISTRY dispatch with a JWT access token.
"""

from __future__ import annotations

import io
import json
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.server.handler_registry import HandlerRegistryMixin
from aragora.server.handlers.knowledge.ml import _ml_limiter
from aragora.server.handlers.utils.responses import json_response

pytestmark = pytest.mark.no_auto_auth

# (registry attribute, POST path) for every dispatched handler that reads its body
# from handle_post's second argument.
BODY_READERS: list[tuple[str, str]] = [
    ("_ml_handler", "/api/v1/ml/embed"),
    ("_smart_upload_handler", "/api/v1/upload/smart"),
    ("_evolution_ab_testing_handler", "/api/v1/evolution/ab-tests"),
    ("_breakpoints_handler", "/api/v1/breakpoints/bp-1/resolve"),
    ("_tournament_handler", "/api/v1/tournaments"),
    ("_gmail_ingest_handler", "/api/v1/gmail/search"),
    ("_universal_graph_handler", "/api/v1/pipeline/graphs"),
    ("_orchestration_handler", "/api/v1/orchestration/deliberate"),
]


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


@pytest.fixture(autouse=True, params=[False, True], ids=["auth-disabled", "auth-enabled"])
def _auth_enabled(request, monkeypatch) -> bool:
    from aragora.server.auth import auth_config

    monkeypatch.setattr(auth_config, "enabled", request.param)
    _ml_limiter.clear()
    return request.param


def _dispatch(
    registry_cls: type[_RegistryMixin],
    path: str,
    raw: bytes,
    role: str = "member",
) -> tuple[int, dict[str, Any]]:
    instance: Any = registry_cls()
    token = create_access_token(
        user_id=f"jwt-{role}", email=f"{role}@example.com", org_id="org-1", role=role
    )
    instance.command = "POST"
    instance.path = path
    instance.headers = {
        "Content-Length": str(len(raw)),
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
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
        patch("aragora.billing.auth.blacklist.is_token_revoked_persistent", return_value=False),
    ):
        handled = instance._try_modular_handler(path, {})
    assert handled is True, f"POST {path} was not handled"
    status = instance.send_response.call_args[0][0]
    return status, json.loads(instance.wfile.getvalue() or b"{}")


class _FakeEmbeddingService:
    model_name = "fake-mini"
    dimension = 3

    def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.mark.parametrize(
    ("body", "count"),
    [({"text": "hello"}, 1), ({"texts": ["a", "b"]}, 2)],
    ids=["text", "texts"],
)
def test_json_post_ml_embed_answers_200_through_the_registry(registry_cls, body, count):
    with patch(
        "aragora.server.handlers.knowledge.ml.get_local_embedding_service",
        return_value=_FakeEmbeddingService(),
    ):
        status, payload = _dispatch(
            registry_cls, "/api/v1/ml/embed", json.dumps(body).encode("utf-8")
        )

    assert status == 200, payload
    assert payload["count"] == count
    assert payload["dimension"] == 3


def test_json_post_ml_embed_without_a_model_answers_the_coded_503(registry_cls):
    with patch(
        "aragora.server.handlers.knowledge.ml.get_local_embedding_service", return_value=None
    ):
        status, payload = _dispatch(registry_cls, "/api/v1/ml/embed", b'{"text": "hello"}')

    assert status == 503
    assert payload == {
        "error": {"message": "ML embeddings not available", "code": "service_unavailable"}
    }


@pytest.mark.parametrize(("attr", "path"), BODY_READERS, ids=[p for _, p in BODY_READERS])
def test_body_reading_post_handlers_receive_the_parsed_json_body(
    registry_cls, monkeypatch, attr, path
):
    received: list[tuple[str, Any]] = []

    def spy(request_path, data, *args, **kwargs):
        received.append((request_path, data))
        return json_response({"ok": True})

    # The registry wraps each instance's handle methods for tracing, so the spy
    # replaces the instance attribute.
    monkeypatch.setattr(getattr(registry_cls, attr), "handle_post", spy)
    body = {"field": "value", "items": [1, 2]}

    status, payload = _dispatch(registry_cls, path, json.dumps(body).encode("utf-8"))

    assert (status, payload) == (200, {"ok": True})
    # Some handlers receive the unversioned path, so only the body is compared.
    assert [data for _, data in received] == [body]


@pytest.mark.parametrize("raw", [b"{not json", b"[1, 2]"], ids=["malformed", "array"])
def test_body_reading_post_handler_rejects_a_body_that_is_not_a_json_object(registry_cls, raw):
    status, payload = _dispatch(registry_cls, "/api/v1/ml/embed", raw)

    assert status == 400
    assert payload == {
        "error": {"message": "Request body must be a JSON object", "code": "invalid_json_body"}
    }


def test_post_handlers_without_the_declaration_keep_the_query_dict(registry_cls, monkeypatch):
    knowledge_handler = registry_cls._knowledge_handler
    assert getattr(knowledge_handler, "HANDLE_POST_JSON_BODY", False) is False
    received: list[Any] = []

    def spy(request_path, query_params, *args, **kwargs):
        received.append(query_params)
        return json_response({"ok": True})

    monkeypatch.setattr(knowledge_handler, "handle_post", spy, raising=False)

    status, _ = _dispatch(registry_cls, "/api/v1/knowledge/query", b'{"question": "q"}')

    assert status == 200
    assert received == [{}]
