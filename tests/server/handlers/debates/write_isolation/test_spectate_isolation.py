"""Spectate events stay inside the debate's org unless the debate is public."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.debates.share import _reset_share_state
from aragora.server.handlers.streaming import spectate_ws
from aragora.server.handlers.streaming.spectate_ws import (
    SpectateStreamHandler,
    iter_live_spectate_sse_frames,
)
from aragora.spectate.ws_bridge import SpectateEvent, get_spectate_bridge, reset_spectate_bridge
from tests.server.handlers.debates.write_isolation.support import (
    ANON,
    DA,
    DB,
    DN,
    DP,
    DX,
    NOT_FOUND,
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    USER_NO_ORG,
    Request,
    act_as,
    body_of,
    text_of,
)

ADMIN_B = SimpleNamespace(
    user_id="admin-b",
    org_id=ORG_B,
    role="admin",
    roles=["admin"],
    permissions=["debates:read", "admin"],
    is_authenticated=True,
    authenticated=True,
)
DR = "deb-running-a"
SEEDED = (DA, DB, DN, DP)
SURFACES = (
    ("/api/v1/spectate/recent", {}),
    ("/api/v1/spectate/stream", {}),
    ("/api/v1/spectate/stream", {"format": "sse"}),
)


def _event(debate_id: str | None, details: str = "", *, now: bool = False) -> SpectateEvent:
    timestamp = datetime.now(timezone.utc).isoformat() if now else "2026-04-03T11:00:00Z"
    return SpectateEvent(
        event_type="proposal",
        timestamp=timestamp,
        debate_id=debate_id,
        agent_name="claude",
        data={"details": details or f"{debate_id} opening"},
    )


@pytest.fixture(autouse=True)
def bridge():
    _reset_share_state()
    reset_spectate_bridge()
    bridge = get_spectate_bridge()
    yield bridge
    bridge.stop()
    _reset_share_state()
    reset_spectate_bridge()


@pytest.fixture
def seeded(bridge):
    for debate_id in SEEDED:
        bridge._event_buffer.append(_event(debate_id, now=True))
    return bridge


@pytest.fixture
def spectate(storage) -> SpectateStreamHandler:
    return SpectateStreamHandler({"storage": storage})


def _sse_frames(raw: str | bytes) -> list[tuple[str, Any]]:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    frames = []
    for chunk in text.strip().split("\n\n"):
        lines = chunk.splitlines()
        if not lines or lines[0].startswith(":"):
            continue
        event_type, payload = "event", None
        for line in lines:
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ")
            elif line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
        frames.append((event_type, payload))
    return frames


def _event_debate_ids(result: Any) -> list[str]:
    if result.content_type == "text/event-stream":
        return [
            payload["debate_id"]
            for event_type, payload in _sse_frames(text_of(result))
            if event_type not in {"connected", "snapshot_complete"}
        ]
    return [event["debate_id"] for event in body_of(result)["events"]]


def _get(monkeypatch, spectate, user, path, query):
    act_as(monkeypatch, user)
    return spectate.handle(path, dict(query), Request("GET", user))


@pytest.mark.parametrize(("path", "query"), SURFACES)
@pytest.mark.parametrize(
    ("user", "visible"),
    [
        (USER_A, [DA, DP]),
        (USER_B, [DB, DP]),
        (ADMIN_B, [DB, DP]),
        (USER_NO_ORG, [DP]),
        (ANON, [DP]),
    ],
)
def test_event_lists_show_only_own_org_and_public_debates(
    monkeypatch, spectate, seeded, path, query, user, visible
):
    result = _get(monkeypatch, spectate, user, path, query)

    assert result.status_code == 200
    assert _event_debate_ids(result) == visible


def test_running_debate_events_follow_the_registered_org(
    monkeypatch, spectate, bridge, state_manager
):
    state_manager.register_debate(DR, "running", ["claude"], metadata={"org_id": ORG_A})
    bridge._event_buffer.append(_event(DR))

    assert _event_debate_ids(_get(monkeypatch, spectate, USER_A, *SURFACES[0])) == [DR]
    assert _event_debate_ids(_get(monkeypatch, spectate, USER_B, *SURFACES[0])) == []


DENIALS = {
    404: NOT_FOUND,
    401: {"error": "Authentication required", "code": "auth_required"},
    403: {"code": "org_required"},
}
NAMED = [
    *[(user, DA, 404) for user in (USER_B, ADMIN_B)],
    *[(USER_A, debate_id, 404) for debate_id in (DN, DX)],
    (ANON, DA, 401),
    (USER_NO_ORG, DA, 403),
    (USER_A, DA, 200),
    *[(user, DP, 200) for user in (USER_A, USER_B, USER_NO_ORG, ANON)],
]


@pytest.mark.parametrize(("path", "query"), SURFACES)
@pytest.mark.parametrize(("user", "debate_id", "status"), NAMED)
def test_named_debate_is_served_only_when_visible(
    monkeypatch, spectate, seeded, path, query, user, debate_id, status
):
    result = _get(monkeypatch, spectate, user, path, {**query, "debate_id": debate_id})

    assert result.status_code == status
    if status == 200:
        assert _event_debate_ids(result) == [debate_id]
    else:
        assert DENIALS[status].items() <= body_of(result).items()
        assert "events" not in body_of(result)


@pytest.mark.parametrize(
    ("user", "live"),
    [(USER_A, {DA, DP}), (USER_B, {DB, DP}), (ADMIN_B, {DB, DP}), (ANON, {DP})],
)
def test_status_names_only_visible_live_debates(monkeypatch, spectate, seeded, user, live):
    seeded.start()

    body = body_of(_get(monkeypatch, spectate, user, "/api/v1/spectate/status", {}))

    assert set(body["live_debate_ids"]) == live
    assert {item["debate_id"] for item in body["live_debates"]} == live
    assert body["live_debate_count"] == len(live)
    assert body["recent_event_count"] == len(SEEDED)
    assert body["unattributed_recent_event_count"] == len(SEEDED) - len(live)


class _ManualBridge:
    def __init__(self, recent: list[SpectateEvent]) -> None:
        self.running = True
        self.recent = recent
        self.subscriber: Any = None

    def subscribe(self, callback: Any) -> None:
        self.subscriber = callback

    def unsubscribe(self, callback: Any) -> None:
        self.subscriber = None

    def get_recent_events(self, count: int = 50) -> list[SpectateEvent]:
        return list(self.recent[-count:])


@pytest.mark.parametrize(("org_id", "backlog", "live"), [(ORG_B, [DB, DP], DB), (None, [DP], DP)])
def test_live_stream_drops_other_org_backlog_and_live_events(storage, org_id, backlog, live):
    bridge = _ManualBridge([_event(debate_id) for debate_id in SEEDED])
    stream = iter_live_spectate_sse_frames(
        {"count": "10"}, heartbeat_interval=60, bridge=bridge, org_id=org_id, storage=storage
    )

    sent = [next(stream) for _ in range(len(backlog) + 2)]
    bridge.subscriber(_event(DA, "A private live critique"))
    bridge.subscriber(_event(live, "visible live critique"))
    sent.append(next(stream))
    stream.close()

    frames = _sse_frames(b"".join(sent))
    assert [frame[0] for frame in frames] == [
        "connected",
        *["spectate"] * len(backlog),
        "snapshot_complete",
        "spectate",
    ]
    assert [p["debate_id"] for t, p in frames if t == "spectate"] == [*backlog, live]
    assert b"A private live critique" not in b"".join(sent)


def _unified_handler(storage):
    from aragora.server.unified_server import UnifiedHandler

    handler = UnifiedHandler.__new__(UnifiedHandler)
    handler.path = "/api/v1/spectate/stream"
    handler.command = "GET"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {"Accept": "text/event-stream"}
    handler.wfile = MagicMock()
    handler.storage = storage
    handler._response_status = 0
    handler._rate_limit_result = None
    for name in (
        "send_response send_header end_headers _add_cors_headers _add_security_headers"
        " _add_trace_headers _send_json _try_modular_handler"
    ).split():
        setattr(handler, name, MagicMock())
    gates = "_check_rbac _check_admin_mfa _check_rate_limit _check_live_streaming_budget"
    for gate in gates.split():
        setattr(handler, gate, MagicMock(return_value=True))
    return handler


@pytest.mark.parametrize(
    ("user", "debate_id", "status"),
    [(USER_B, DA, 404), (ANON, DA, 401), (USER_NO_ORG, DA, 403)]
    + [(USER_A, DA, 200), (ANON, DP, 200), (USER_B, DP, 200)],
)
def test_live_server_answers_before_any_200_header(monkeypatch, storage, user, debate_id, status):
    act_as(monkeypatch, user)
    handler = _unified_handler(storage)

    with patch.object(
        spectate_ws, "iter_live_spectate_sse_frames", return_value=iter([b"event: connected\n\n"])
    ) as frames:
        handler._do_GET_internal("/api/v1/spectate/stream", {"debate_id": [debate_id]})

    handler._try_modular_handler.assert_not_called()
    if status == 200:
        frames.assert_called_once_with(
            {"debate_id": debate_id}, org_id=user.org_id, storage=storage
        )
        handler.send_response.assert_called_once_with(200)
        handler._send_json.assert_not_called()
        return
    frames.assert_not_called()
    handler.send_response.assert_not_called()
    handler.wfile.write.assert_not_called()
    sent, kwargs = handler._send_json.call_args
    assert kwargs["status"] == status
    assert DENIALS[status].items() <= sent[0].items()


def _emit(monkeypatch, spectate, user, body: dict[str, Any]):
    act_as(monkeypatch, user)
    return spectate.handle_post("/api/v1/spectate/emit", {}, Request("POST", user, body))


@pytest.mark.parametrize(
    ("user", "debate_id", "status"),
    [
        (USER_B, DA, 404),
        (USER_B, DP, 404),
        (USER_A, DN, 404),
        (USER_A, DX, 404),
        (USER_A, "", 404),
        (ANON, DA, 401),
        (USER_NO_ORG, DA, 403),
    ],
)
def test_emit_refuses_debates_outside_the_callers_org(
    monkeypatch, spectate, bridge, user, debate_id, status
):
    bridge.start()

    result = _emit(monkeypatch, spectate, user, {"debate_id": debate_id, "details": "injected"})

    assert result.status_code == status
    if status == 404:
        assert body_of(result) == NOT_FOUND
    assert bridge.get_recent_events(50) == []


def test_emit_for_own_debate_is_bound_to_that_debate(monkeypatch, spectate, bridge):
    bridge.start()
    smuggled = json.dumps({"debate_id": DB, "details": "aimed at B"})

    result = _emit(
        monkeypatch,
        spectate,
        USER_A,
        {"debate_id": DA, "events": [{"event_type": "critique", "details": smuggled}]},
    )

    assert result.status_code == 200
    assert body_of(result) == {"emitted": 1, "debate_id": DA}
    assert [event.debate_id for event in bridge.get_recent_events(50)] == [DA]


PIPE_A, PIPE_U, PIPE_X = "pipe-org-a", "pipe-unowned", "pipe-missing"


@pytest.fixture
def pipelines(tmp_path):
    from aragora.pipeline.graph_store import GraphStore
    from aragora.storage.pipeline_store import PipelineResultStore

    store = PipelineResultStore(str(tmp_path / "pipelines.db"))
    store.save(PIPE_A, {"stage_status": {}}, org_id=ORG_A, created_by="user-a")
    store.save(PIPE_U, {"stage_status": {}})
    graphs = GraphStore(db_path=str(tmp_path / "graphs.db"))
    with (
        patch("aragora.storage.pipeline_store.get_pipeline_store", return_value=store),
        patch("aragora.pipeline.graph_store.get_graph_store", return_value=graphs),
    ):
        yield store


def _pipeline_event(pipeline_id: str) -> SpectateEvent:
    return SpectateEvent(
        event_type="approval_granted",
        timestamp=datetime.now(timezone.utc).isoformat(),
        pipeline_id=pipeline_id,
        data={"agent_id": "agent-1", "notes": f"{pipeline_id} private notes"},
    )


def _event_scopes(result: Any) -> list[tuple[str | None, str | None]]:
    if result.content_type == "text/event-stream":
        frames = _sse_frames(text_of(result))
        events = [p for t, p in frames if t not in {"connected", "snapshot_complete"}]
    else:
        events = body_of(result)["events"]
    return [(event["debate_id"], event["pipeline_id"]) for event in events]


@pytest.mark.parametrize(("path", "query"), SURFACES)
@pytest.mark.parametrize(
    ("user", "visible"),
    [(USER_A, [PIPE_A]), (USER_B, []), (ADMIN_B, []), (USER_NO_ORG, []), (ANON, [])],
)
def test_pipeline_events_reach_only_the_pipelines_org(
    monkeypatch, spectate, bridge, pipelines, path, query, user, visible
):
    for pipeline_id in (PIPE_A, PIPE_U, PIPE_X):
        bridge._event_buffer.append(_pipeline_event(pipeline_id))
    bridge._event_buffer.append(_event(None, "unscoped notice", now=True))

    result = _get(monkeypatch, spectate, user, path, query)

    assert result.status_code == 200
    assert _event_scopes(result) == [*((None, p) for p in visible), (None, None)]


@pytest.mark.parametrize("pipeline_id", [PIPE_A, PIPE_X])
def test_naming_another_orgs_pipeline_reads_like_a_missing_one(
    monkeypatch, spectate, bridge, pipelines, pipeline_id
):
    bridge._event_buffer.append(_pipeline_event(PIPE_A))

    result = _get(monkeypatch, spectate, USER_B, SURFACES[0][0], {"pipeline_id": pipeline_id})

    assert (result.status_code, body_of(result)) == (200, {"events": [], "count": 0})


@pytest.mark.parametrize(("org_id", "visible"), [(ORG_A, 1), (ORG_B, 0), (None, 0)])
def test_live_stream_sends_pipeline_events_only_to_the_pipelines_org(
    storage, pipelines, org_id, visible
):
    bridge = _ManualBridge([_pipeline_event(PIPE_A)])
    stream = iter_live_spectate_sse_frames(
        {"count": "10"}, heartbeat_interval=60, bridge=bridge, org_id=org_id, storage=storage
    )

    sent = [next(stream) for _ in range(2 + visible)]
    bridge.subscriber(_pipeline_event(PIPE_A))
    bridge.subscriber(_event(None, "unscoped notice"))
    sent.extend(next(stream) for _ in range(1 + visible))
    stream.close()

    frames = [p for t, p in _sse_frames(b"".join(sent)) if t == "spectate"]
    assert [p["pipeline_id"] for p in frames] == [PIPE_A] * 2 * visible + [None]


def test_pipeline_run_events_are_tagged_with_their_pipeline(
    monkeypatch, spectate, bridge, pipelines
):
    from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

    bridge.start()
    IdeaToExecutionPipeline().from_ideas(["one idea"], auto_advance=False, pipeline_id=PIPE_A)

    owner = body_of(_get(monkeypatch, spectate, USER_A, *SURFACES[0]))
    other = body_of(_get(monkeypatch, spectate, USER_B, *SURFACES[0]))
    assert [e["event_type"] for e in owner["events"] if e["pipeline_id"] == PIPE_A] == [
        "pipeline.started"
    ]
    assert PIPE_A not in json.dumps(other)
