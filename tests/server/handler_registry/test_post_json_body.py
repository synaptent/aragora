"""POST handlers whose ``handle_post`` takes the request body receive the parsed JSON body.

The server dispatches every POST as ``_try_modular_handler(path, {})``, so the
registry's second ``handle_post`` argument is an empty query dict. Handlers that
read their fields from that argument declare ``HANDLE_POST_JSON_BODY`` and the
registry passes them the parsed JSON object instead. Requests go through the
real HANDLER_REGISTRY dispatch with a JWT access token.
"""

from __future__ import annotations

import inspect
import io
import json
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.server.handler_registry import HANDLER_REGISTRY, HandlerRegistryMixin
from aragora.server.handlers.knowledge.ml import _ml_limiter
from aragora.server.handlers.utils.responses import json_response

pytestmark = pytest.mark.no_auto_auth

# (registry attribute, POST path) for every dispatched handler that reads its body
# from handle_post's second argument. With NOT_BODY_READERS it covers every registered
# handler whose handle_post names that argument body or data.
BODY_READERS: list[tuple[str, str]] = [
    ("_ml_handler", "/api/v1/ml/embed"),
    ("_evolution_ab_testing_handler", "/api/v1/evolution/ab-tests"),
]
# Registered handlers whose handle_post takes a body argument but are not opted in.
NOT_BODY_READERS: dict[str, str] = {
    # test_debate_intervention_posts_reach_the_debates_handler traces this.
    "_debate_intervention_handler": "the route index sends its POST paths to DebatesHandler",
    "_decomposition_handler": "never reads the body argument",
    "_slack_handler": "reads the raw body from rfile itself",
    "_chat_handler": "reads the raw body from rfile itself",
    "_smart_upload_handler": "its options would set user, workspace and tenant attribution",
    "_tournament_handler": "tournament creation has no participant cap",
    "_orchestration_handler": "async deliberation would run on a per-request event loop",
    "_breakpoints_handler": "resolve would take reviewer_id from the body as the human id",
    "_gmail_ingest_handler": "sync and search fields have no type or bound checks",
    "_universal_graph_handler": "graph create would upsert a caller-chosen graph id",
}
# Not opted in, so handle_post keeps receiving the (empty) query dict.
QUERY_DICT_POSTS: list[tuple[str, str]] = [
    ("_knowledge_handler", "/api/v1/knowledge/query"),
    ("_smart_upload_handler", "/api/v1/upload/smart"),
    ("_tournament_handler", "/api/v1/tournaments"),
    ("_orchestration_handler", "/api/v1/orchestration/deliberate"),
    ("_breakpoints_handler", "/api/v1/breakpoints/bp-1/resolve"),
    ("_gmail_ingest_handler", "/api/v1/gmail/search"),
    ("_universal_graph_handler", "/api/v1/pipeline/graphs"),
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
    content_length: str | None = None,
    rfile: Any = None,
    attrs: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    instance: Any = registry_cls()
    for name, value in (attrs or {}).items():
        setattr(instance, name, value)
    token = create_access_token(
        user_id=f"jwt-{role}", email=f"{role}@example.com", org_id="org-1", role=role
    )
    instance.command = "POST"
    instance.path = path
    instance.headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if content_length != "":
        instance.headers["Content-Length"] = (
            str(len(raw)) if content_length is None else content_length
        )
    instance.headers.update(headers or {})
    instance.rfile = io.BytesIO(raw) if rfile is None else rfile
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

    def search(self, query: str, documents: list[str], top_k: int, threshold: float) -> list:
        return []


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


def test_zero_length_post_is_bodyless_and_not_read_from_the_socket(registry_cls):
    # A keep-alive socket with nothing more to send blocks on read().
    blocking_rfile = MagicMock()
    blocking_rfile.read.side_effect = AssertionError("rfile.read on a bodyless POST")

    with patch(
        "aragora.server.handlers.knowledge.ml.get_local_embedding_service",
        return_value=_FakeEmbeddingService(),
    ):
        status, payload = _dispatch(
            registry_cls, "/api/v1/ml/embed", b"", content_length="0", rfile=blocking_rfile
        )

    blocking_rfile.read.assert_not_called()
    assert status == 400
    assert "text or texts is required" in json.dumps(payload)


_LENGTH_REQUIRED = (
    411,
    "Content-Length is required and Transfer-Encoding is not supported",
    "length_required",
)
_INVALID_LENGTH = (400, "Content-Length must be a non-negative integer", "invalid_content_length")


@pytest.mark.parametrize(
    ("content_length", "headers", "expected"),
    [
        ("", {}, _LENGTH_REQUIRED),
        ("", {"Transfer-Encoding": "chunked"}, _LENGTH_REQUIRED),
        ("17", {"Transfer-Encoding": "chunked"}, _LENGTH_REQUIRED),
        ("17", {"Transfer-Encoding": "gzip"}, _LENGTH_REQUIRED),
        ("abc", {}, _INVALID_LENGTH),
        ("-1", {}, _INVALID_LENGTH),
        ("\u00b2", {}, _INVALID_LENGTH),
    ],
    ids=["absent", "chunked", "chunked-with-length", "other-coding", "text", "negative", "u00b2"],
)
def test_post_without_a_usable_length_is_refused_unread(
    registry_cls, monkeypatch, content_length, headers, expected
):
    blocking_rfile = MagicMock()
    blocking_rfile.read.side_effect = AssertionError("rfile.read without a usable length")
    handle_post = MagicMock(side_effect=AssertionError("handle_post without a usable length"))
    monkeypatch.setattr(registry_cls._ml_handler, "handle_post", handle_post)

    status, payload = _dispatch(
        registry_cls,
        "/api/v1/ml/embed",
        b'{"text": "hello"}',
        content_length=content_length,
        rfile=blocking_rfile,
        headers=headers,
    )

    blocking_rfile.read.assert_not_called()
    handle_post.assert_not_called()
    assert (status, payload) == (
        expected[0],
        {"error": {"message": expected[1], "code": expected[2]}},
    )


# Without Content-Length too: the 411 rule applies only to opted-in handlers.
@pytest.mark.parametrize("content_length", [None, ""], ids=["with-length", "no-length"])
@pytest.mark.parametrize(("attr", "path"), QUERY_DICT_POSTS, ids=[p for _, p in QUERY_DICT_POSTS])
def test_post_handlers_without_the_declaration_keep_the_query_dict(
    registry_cls, monkeypatch, attr, path, content_length
):
    handler = getattr(registry_cls, attr)
    assert getattr(handler, "HANDLE_POST_JSON_BODY", False) is False
    received: list[Any] = []

    def spy(request_path, query_params, *args, **kwargs):
        received.append(query_params)
        return json_response({"ok": True})

    monkeypatch.setattr(handler, "handle_post", spy, raising=False)

    status, _ = _dispatch(registry_cls, path, b'{"question": "q"}', content_length=content_length)

    assert status == 200
    assert received == [{}]


def test_every_handler_taking_a_post_body_is_opted_in_or_excluded(registry_cls):
    takes_body, opted_in = set(), set()
    for attr, _ in HANDLER_REGISTRY:
        handler = getattr(registry_cls, attr, None)
        method = getattr(type(handler), "handle_post", None)
        if method and list(inspect.signature(method).parameters)[2:3] in (["body"], ["data"]):
            takes_body.add(attr)
            if getattr(handler, "HANDLE_POST_JSON_BODY", False):
                opted_in.add(attr)

    assert opted_in == {attr for attr, _ in BODY_READERS}
    assert takes_body == opted_in | set(NOT_BODY_READERS)


@pytest.mark.parametrize("path", ["/api/v1/debates/d-1/intervene", "/api/debates/d-1/intervene"])
def test_debate_intervention_posts_reach_the_debates_handler(registry_cls, monkeypatch, path):
    called: list[str] = []

    def spy(attr: str) -> Any:
        def handle_post(*args: Any, **kwargs: Any) -> Any:
            called.append(attr)
            return json_response({"ok": True})

        return handle_post

    for attr in ("_debates_handler", "_debate_intervention_handler"):
        monkeypatch.setattr(getattr(registry_cls, attr), "handle_post", spy(attr))

    status, _ = _dispatch(registry_cls, path, b'{"type": "redirect"}')

    assert (status, called) == (200, ["_debates_handler"])


def _post_ml(registry_cls, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    with patch(
        "aragora.server.handlers.knowledge.ml.get_local_embedding_service",
        return_value=_FakeEmbeddingService(),
    ):
        return _dispatch(registry_cls, path, json.dumps(body).encode("utf-8"))


_PER_TEXT_CAP_ERROR = {
    "error": {"message": "Each text may be at most 2000 bytes of UTF-8", "code": "input_too_large"}
}


@pytest.mark.parametrize(
    "body",
    [{"text": "x" * 2001}, {"texts": ["a", "x" * 2001]}, {"texts": ["\u00e9" * 1001]}],
    ids=["text", "texts", "multibyte"],
)
def test_ml_embed_rejects_a_text_over_the_per_text_byte_cap(registry_cls, body):
    assert _post_ml(registry_cls, "/api/v1/ml/embed", body) == (400, _PER_TEXT_CAP_ERROR)


@pytest.mark.parametrize(
    "body",
    [{"query": "x" * 2001, "documents": ["a"]}, {"query": "q", "documents": ["a", "x" * 2001]}],
    ids=["query", "document"],
)
def test_ml_search_rejects_a_text_over_the_per_text_byte_cap(registry_cls, body):
    assert _post_ml(registry_cls, "/api/v1/ml/search", body) == (400, _PER_TEXT_CAP_ERROR)


def test_ml_search_rejects_texts_over_the_total_byte_cap(registry_cls):
    body = {"query": "q", "documents": ["x" * 2000] * 100}

    assert _post_ml(registry_cls, "/api/v1/ml/search", body) == (
        400,
        {
            "error": {
                "message": "Texts may total at most 200000 bytes of UTF-8",
                "code": "input_too_large",
            }
        },
    )


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/ml/embed", {"texts": ["x" * 2000] * 100}),
        ("/api/v1/ml/search", {"query": "q", "documents": ["x" * 2000] * 99 + ["x" * 1999]}),
    ],
    ids=["embed", "search"],
)
def test_ml_embed_and_search_accept_texts_at_the_byte_caps(registry_cls, path, body):
    status, payload = _post_ml(registry_cls, path, body)

    assert status == 200, payload


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/ml/embed", {"texts": ["a", 5]}),
        ("/api/v1/ml/embed", {"texts": "not a list"}),
        ("/api/v1/ml/search", {"query": "q", "documents": ["a", {"text": "b"}]}),
    ],
    ids=["embed-item", "embed-string", "search-item"],
)
def test_ml_embed_and_search_reject_texts_that_are_not_strings(registry_cls, path, body):
    assert _post_ml(registry_cls, path, body) == (
        400,
        {"error": {"message": "Texts to embed must be strings", "code": "invalid_input"}},
    )


def _post_ml_component(registry_cls, path: str, body: dict[str, Any]) -> tuple[Any, MagicMock]:
    component = MagicMock()
    with patch("aragora.server.handlers.knowledge.ml._get_ml_component", return_value=component):
        return _dispatch(registry_cls, path, json.dumps(body).encode("utf-8")), component


def _rejected(message: str, code: str = "input_too_large") -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"message": message, "code": code}}


_LONG = "x" * 20001
_AT_TOTAL = ["x" * 20000] * 10
_TEXT_CAP = _rejected("Each text may be at most 20000 bytes of UTF-8")
_TOTAL_CAP = _rejected("Texts may total at most 200000 bytes of UTF-8")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"text": _LONG}, _TEXT_CAP),
        ({"text": "t", "context": _LONG}, _TEXT_CAP),
        ({"text": 5}, _rejected("Texts to score must be strings", "invalid_input")),
    ],
    ids=["text", "context", "not-a-string"],
)
def test_ml_score_caps_its_texts(registry_cls, body, expected):
    response, scorer = _post_ml_component(registry_cls, "/api/v1/ml/score", body)

    assert response == expected
    assert scorer.method_calls == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"texts": ["t", _LONG]}, _TEXT_CAP),
        ({"texts": ["t"], "contexts": [_LONG]}, _TEXT_CAP),
        ({"texts": _AT_TOTAL, "contexts": ["c"]}, _TOTAL_CAP),
        ({"texts": ["t"], "contexts": [""] * 101}, _rejected("At most 100 contexts per batch")),
        (
            {"texts": ["t"], "contexts": "c"},
            _rejected("Texts to score must be strings", "invalid_input"),
        ),
    ],
    ids=["text", "context", "total", "context-count", "contexts-not-a-list"],
)
def test_ml_score_batch_caps_its_texts(registry_cls, body, expected):
    response, scorer = _post_ml_component(registry_cls, "/api/v1/ml/score-batch", body)

    assert response == expected
    assert scorer.method_calls == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"responses": [["a", _LONG]]}, _TEXT_CAP),
        ({"responses": [["a", "t"]], "context": _LONG}, _TEXT_CAP),
        ({"responses": [["a", t] for t in _AT_TOTAL]}, _TOTAL_CAP),
        ({"responses": [["a", "t"]] * 101}, _rejected("At most 100 responses")),
        *(
            (
                {"responses": responses},
                _rejected(
                    "Each response must be an [agent, text] pair of strings", "invalid_input"
                ),
            )
            for responses in ([["a"]], ["ab"], [["a", 5]], "ab")
        ),
    ],
    ids=["text", "context", "total", "count", "short-pair", "string-pair", "number", "not-a-list"],
)
def test_ml_consensus_caps_its_responses(registry_cls, body, expected):
    response, predictor = _post_ml_component(registry_cls, "/api/v1/ml/consensus", body)

    assert response == expected
    assert predictor.method_calls == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"task": _LONG, "available_agents": ["a"]}, _TEXT_CAP),
        ({"task": "t", "available_agents": ["a", _LONG]}, _TEXT_CAP),
        ({"task": "t", "available_agents": _AT_TOTAL}, _TOTAL_CAP),
        ({"task": "t", "available_agents": ["a"] * 101}, _rejected("At most 100 available_agents")),
        (
            {"task": "t", "available_agents": "claude"},
            _rejected("The task and available_agents must be strings", "invalid_input"),
        ),
    ],
    ids=["task", "agent", "total", "count", "agents-not-a-list"],
)
def test_ml_route_caps_its_task_and_agents(registry_cls, body, expected):
    response, router = _post_ml_component(registry_cls, "/api/v1/ml/route", body)

    assert response == expected
    assert router.method_calls == []


@pytest.mark.parametrize(
    ("path", "body", "method"),
    [
        ("/api/v1/ml/score", {"text": "x" * 20000, "context": "x" * 20000}, "score"),
        (
            "/api/v1/ml/score-batch",
            {"texts": _AT_TOTAL[:9], "contexts": [None] * 8 + _AT_TOTAL[:1]},
            "score_batch",
        ),
        ("/api/v1/ml/consensus", {"responses": [["a", "x" * 19999]] * 10}, "predict"),
        ("/api/v1/ml/route", {"task": "t", "available_agents": ["a"] * 100}, "route"),
    ],
    ids=["score", "score-batch", "consensus", "route"],
)
def test_ml_scoring_routes_accept_input_at_the_caps(registry_cls, path, body, method):
    (status, payload), component = _post_ml_component(registry_cls, path, body)

    assert status == 200, payload
    getattr(component, method).assert_called_once()


_ML_BODIES: dict[str, dict[str, Any]] = {
    "score-batch": {"texts": ["a", "b"]},
    "consensus": {"responses": [["a", "t"]]},
    "route": {"task": "t", "available_agents": ["a"]},
    "search": {"query": "q", "documents": ["d"]},
}
_INT = "must be an integer"


@pytest.mark.parametrize(
    ("route", "fields", "message"),
    [
        ("score-batch", {"contexts": ["c"]}, "contexts must match texts in length"),
        ("score-batch", {"contexts": []}, "contexts must match texts in length"),
        ("consensus", {"total_rounds": 0}, f"total_rounds {_INT} of at least 1"),
        ("consensus", {"total_rounds": True}, f"total_rounds {_INT} of at least 1"),
        ("consensus", {"current_round": "1"}, f"current_round {_INT} from 1 to 3"),
        ("consensus", {"current_round": 3, "total_rounds": 2}, f"current_round {_INT} from 1 to 2"),
        ("route", {"team_size": 0}, f"team_size {_INT} of at least 1"),
        ("route", {"team_size": 2.0}, f"team_size {_INT} of at least 1"),
        ("route", {"constraints": "x"}, "constraints must be an object"),
        ("search", {"top_k": -1}, f"top_k {_INT} of at least 1"),
        ("search", {"top_k": None}, f"top_k {_INT} of at least 1"),
        ("search", {"threshold": 1.5}, "threshold must be a number from -1 to 1"),
        ("search", {"threshold": False}, "threshold must be a number from -1 to 1"),
    ],
)
def test_ml_routes_reject_malformed_fields_before_the_model(registry_cls, route, fields, message):
    body = {**_ML_BODIES[route], **fields}
    response, component = _post_ml_component(registry_cls, f"/api/v1/ml/{route}", body)

    assert response == _rejected(message, "invalid_input")
    assert component.method_calls == []


@pytest.mark.parametrize(
    "attrs",
    [
        {"body": b'{"text": "hello"}'},
        {"request": MagicMock(body='{"text": "hello"}')},
    ],
    ids=["handler.body", "handler.request.body"],
)
def test_a_pre_buffered_body_is_read_without_a_length_header(registry_cls, attrs):
    blocking_rfile = MagicMock()
    blocking_rfile.read.side_effect = AssertionError("rfile.read with a pre-buffered body")

    with patch(
        "aragora.server.handlers.knowledge.ml.get_local_embedding_service",
        return_value=_FakeEmbeddingService(),
    ):
        status, payload = _dispatch(
            registry_cls,
            "/api/v1/ml/embed",
            b"",
            content_length="",
            rfile=blocking_rfile,
            attrs=attrs,
        )

    blocking_rfile.read.assert_not_called()
    assert status == 200, payload
    assert payload["count"] == 1
