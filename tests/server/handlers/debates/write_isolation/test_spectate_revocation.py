"""Unsharing a debate ends what open spectate streams of other viewers receive.

A live stream (SSE or WebSocket) opened by another org or anonymously while A's
debate was public gets none of the debate's events once A unshares it, and a
stream opened for that debate is closed. That includes events buffered before
the unshare (snapshot or queue) and sent after it, with nothing published
later. A's own streams carry on.
"""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from typing import Any

import aiohttp
import aiohttp.web
import pytest

from aragora.server.handlers.debates import share as share_module
from aragora.server.handlers.debates.share import (
    DebateShareHandler,
    _reset_share_state,
    public_spectate_sse_generator,
    push_public_spectator_event,
)
from aragora.server.handlers.streaming import spectate_ws
from aragora.server.handlers.streaming.spectate_ws import iter_live_spectate_sse_frames
from aragora.spectate.ws_bridge import SpectateEvent
from tests.server.handlers.debates.write_isolation.support import (
    ANON,
    DA,
    DB,
    DP,
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    USER_NO_ORG,
    Request,
    act_as,
    route,
    text_of,
)


PIPE = "pipe-write-isolation"


def _event(debate_id: str, details: str, pipeline_id: str | None = None) -> SpectateEvent:
    return SpectateEvent(
        event_type="proposal",
        timestamp="2026-10-08T12:00:00+00:00",
        debate_id=debate_id,
        pipeline_id=pipeline_id,
        agent_name="claude",
        data={"details": details},
    )


class LiveBridge:
    """A spectate bridge whose live events the test publishes by hand."""

    running = True

    def __init__(self, backlog: list[SpectateEvent] | None = None) -> None:
        self.subscribers: list[Any] = []
        self.backlog = list(backlog or [])

    def subscribe(self, callback: Any) -> None:
        self.subscribers.append(callback)

    def unsubscribe(self, callback: Any) -> None:
        self.subscribers.remove(callback)

    def get_recent_events(self, count: int = 50) -> list[SpectateEvent]:
        return self.backlog[-count:]

    def publish(self, debate_id: str, details: str, pipeline_id: str | None = None) -> None:
        event = _event(debate_id, details, pipeline_id)
        for callback in list(self.subscribers):
            callback(event)


@pytest.fixture(autouse=True)
def _clean_share_state():
    _reset_share_state()
    yield
    _reset_share_state()


@pytest.fixture
def share(monkeypatch, storage):
    """``share(method)``: A shares (POST) or unshares (DELETE) its debate ``DA``."""
    handler = DebateShareHandler(ctx={"storage": storage})

    def _share(method: str) -> None:
        act_as(monkeypatch, USER_A)
        path = f"/api/v1/debates/{DA}/share"
        result = route(handler, method, path, Request(method, USER_A))
        assert result.status_code == 200, text_of(result)

    return _share


def _frames(chunks: list[bytes]) -> list[tuple[str, dict[str, Any]]]:
    frames = []
    for chunk in b"".join(chunks).decode().split("\n\n"):
        lines = chunk.strip().splitlines()
        if not lines or lines[0].startswith(":"):
            continue
        event = lines[0].removeprefix("event: ")
        frames.append((event, json.loads(lines[1].removeprefix("data: "))))
    return frames


def _details(frames: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [p["data"]["details"] for event, p in frames if event == "spectate"]


def _open_sse(bridge: LiveBridge, storage: Any, org_id: str | None, query: dict[str, str]):
    stream = iter_live_spectate_sse_frames(
        query, heartbeat_interval=0.05, bridge=bridge, org_id=org_id, storage=storage
    )
    opening = [next(stream), next(stream)]
    assert [event for event, _ in _frames(opening)] == ["connected", "snapshot_complete"]
    return stream


def _next_frame(stream: Any) -> tuple[str, dict[str, Any]]:
    """The next frame that is not a heartbeat."""
    while True:
        chunk = next(stream)
        if not chunk.startswith(b":"):
            return _frames([chunk])[0]


class TestLiveSse:
    @pytest.mark.parametrize("org_id", [ORG_B, None])
    def test_stream_for_the_debate_is_closed_on_unshare(self, share, storage, org_id):
        share("POST")
        bridge = LiveBridge()
        stream = _open_sse(bridge, storage, org_id, {"debate_id": DA})
        bridge.publish(DA, "sent while public")
        assert _details([_next_frame(stream)]) == ["sent while public"]

        share("DELETE")
        bridge.publish(DA, "sent after unshare")
        rest = list(stream)

        assert [event for event, _ in _frames(rest)] == ["share_revoked"]
        assert b"sent after unshare" not in b"".join(rest)
        assert bridge.subscribers == []

    @pytest.mark.parametrize("org_id", [ORG_B, None])
    def test_idle_stream_for_the_debate_is_closed_at_the_next_heartbeat(
        self, share, storage, org_id
    ):
        share("POST")
        bridge = LiveBridge()
        stream = _open_sse(bridge, storage, org_id, {"debate_id": DA})

        share("DELETE")

        assert [event for event, _ in _frames(list(stream))] == ["share_revoked"]

    @pytest.mark.parametrize("org_id", [ORG_B, None])
    def test_stream_of_all_public_events_drops_the_unshared_debate(self, share, storage, org_id):
        share("POST")
        bridge = LiveBridge()
        stream = _open_sse(bridge, storage, org_id, {})
        bridge.publish(DA, "sent while public")
        assert _details([_next_frame(stream)]) == ["sent while public"]

        share("DELETE")
        bridge.publish(DA, "sent after unshare")
        bridge.publish(DP, "still public")
        later = _next_frame(stream)
        stream.close()

        assert _details([later]) == ["still public"]

    @pytest.mark.parametrize("query", [{"debate_id": DA}, {}])
    def test_owner_stream_carries_on(self, share, storage, query):
        share("POST")
        bridge = LiveBridge()
        stream = _open_sse(bridge, storage, ORG_A, query)

        share("DELETE")
        bridge.publish(DA, "owner still sees this")
        frame = _next_frame(stream)
        stream.close()

        assert _details([frame]) == ["owner still sees this"]


def _start_sse(bridge: LiveBridge, storage: Any, org_id: str | None, query: dict[str, str]):
    """A live stream whose ``connected`` frame and first snapshot event have been read."""
    stream = iter_live_spectate_sse_frames(
        query, heartbeat_interval=0.05, bridge=bridge, org_id=org_id, storage=storage
    )
    opening = _frames([next(stream), next(stream)])
    assert [event for event, _ in opening] == ["connected", "spectate"]
    assert _details(opening) == ["backlog 1"]
    return stream


HEARTBEAT = b": heartbeat\n\n"


class TestBufferedLiveSse:
    """Events buffered before the unshare; nothing is published after it."""

    @pytest.mark.parametrize("org_id", [ORG_B, None])
    def test_event_queued_before_unshare_is_not_sent(self, share, storage, org_id):
        share("POST")
        bridge = LiveBridge()
        stream = _open_sse(bridge, storage, org_id, {"debate_id": DA})
        bridge.publish(DA, "queued while public")

        share("DELETE")
        rest = list(stream)

        assert [event for event, _ in _frames(rest)] == ["share_revoked"]
        assert b"queued while public" not in b"".join(rest)
        assert bridge.subscribers == []

    @pytest.mark.parametrize("org_id", [ORG_B, None])
    def test_snapshot_rest_is_not_sent_after_unshare(self, share, storage, org_id):
        share("POST")
        bridge = LiveBridge(backlog=[_event(DA, "backlog 1"), _event(DA, "backlog 2")])
        stream = _start_sse(bridge, storage, org_id, {"debate_id": DA})

        share("DELETE")
        rest = list(stream)

        assert [event for event, _ in _frames(rest)] == ["share_revoked"]
        assert b"backlog 2" not in b"".join(rest)
        assert bridge.subscribers == []

    @pytest.mark.parametrize("org_id", [ORG_B, None])
    @pytest.mark.parametrize("query", [{}, {"pipeline_id": PIPE}])
    def test_stream_of_public_events_drops_events_queued_before_unshare(
        self, share, storage, org_id, query
    ):
        share("POST")
        bridge = LiveBridge()
        stream = _open_sse(bridge, storage, org_id, query)
        bridge.publish(DA, "queued while public", pipeline_id=PIPE)
        bridge.publish(DP, "still public", pipeline_id=PIPE)

        share("DELETE")
        later = _next_frame(stream)
        alive = next(stream)
        stream.close()

        assert _details([later]) == ["still public"]
        assert alive == HEARTBEAT

    @pytest.mark.parametrize("org_id", [ORG_B, None])
    def test_stream_of_public_events_drops_the_snapshot_rest_after_unshare(
        self, share, storage, org_id
    ):
        share("POST")
        backlog = [_event(DA, "backlog 1"), _event(DA, "backlog 2"), _event(DP, "public backlog")]
        stream = _start_sse(LiveBridge(backlog=backlog), storage, org_id, {})

        share("DELETE")
        rest = [_next_frame(stream), _next_frame(stream)]
        stream.close()

        assert [event for event, _ in rest] == ["spectate", "snapshot_complete"]
        assert _details(rest) == ["public backlog"]

    @pytest.mark.parametrize("query", [{"debate_id": DA}, {}])
    def test_owner_gets_events_buffered_before_unshare(self, share, storage, query):
        share("POST")
        bridge = LiveBridge(backlog=[_event(DA, "backlog 1"), _event(DA, "backlog 2")])
        stream = _start_sse(bridge, storage, ORG_A, query)
        bridge.publish(DA, "queued while public")

        share("DELETE")
        rest = [_next_frame(stream) for _ in range(3)]
        alive = next(stream)
        stream.close()

        assert [event for event, _ in rest] == ["spectate", "snapshot_complete", "spectate"]
        assert _details(rest) == ["backlog 2", "queued while public"]
        assert alive == HEARTBEAT

    @pytest.mark.parametrize("org_id", [ORG_B, None])
    def test_event_queued_before_unshare_is_sent_once_shared_again(self, share, storage, org_id):
        share("POST")
        bridge = LiveBridge()
        stream = _open_sse(bridge, storage, org_id, {"debate_id": DA})
        bridge.publish(DA, "queued while public")

        share("DELETE")
        share("POST")
        frame = _next_frame(stream)
        alive = next(stream)
        stream.close()

        assert _details([frame]) == ["queued while public"]
        assert alive == HEARTBEAT

    def test_closed_stream_stays_closed_once_shared_again(self, share, storage):
        share("POST")
        bridge = LiveBridge()
        stream = _open_sse(bridge, storage, ORG_B, {"debate_id": DA})
        share("DELETE")
        assert [event for event, _ in _frames(list(stream))] == ["share_revoked"]

        share("POST")
        bridge.publish(DA, "shared again")

        assert next(stream, None) is None
        assert bridge.subscribers == []


def test_visibility_decided_before_unshare_is_not_kept_after_it(monkeypatch, share, storage):
    """A stream's visibility is used from two threads (the publisher's and the
    stream's). A decision that read the share flag before the unshare must not
    leave its answer cached after the other thread has seen the unshare."""
    share("POST")
    visibility = spectate_ws.SpectateVisibility(ORG_B, storage=storage)
    read_flag, finish = threading.Event(), threading.Event()
    real_is_publicly_shared = share_module.is_publicly_shared

    def slow_first_read(debate_id: str) -> bool:
        answer = real_is_publicly_shared(debate_id)
        if not read_flag.is_set():
            read_flag.set()
            finish.wait(5)
        return answer

    monkeypatch.setattr(share_module, "is_publicly_shared", slow_first_read)
    publisher = threading.Thread(target=visibility.can_view, args=(DA,))
    publisher.start()
    assert read_flag.wait(5)
    share("DELETE")
    consumer = threading.Thread(target=visibility.can_view, args=(DA,))
    consumer.start()
    consumer.join(0.5)
    finish.set()
    publisher.join(5)
    consumer.join(5)

    assert visibility.can_view(DA) is False
    assert visibility.lost_access(DA)


class _Socket:
    """A WebSocket whose incoming messages end when the server closes it."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._incoming: asyncio.Queue[Any] = asyncio.Queue()

    async def prepare(self, request: Any) -> _Socket:
        return self

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    async def close(self, *args: Any, **kwargs: Any) -> None:
        self.closed = True
        self._incoming.put_nowait(SimpleNamespace(type=aiohttp.WSMsgType.CLOSED, data=""))

    def __aiter__(self) -> _Socket:
        return self

    async def __anext__(self) -> Any:
        message = await self._incoming.get()
        if message.type == aiohttp.WSMsgType.CLOSED:
            raise StopAsyncIteration
        return message

    def details(self) -> list[str]:
        return [m.get("details") for m in self.sent if m.get("type") == "proposal"]


class _SlowSocket(_Socket):
    """A socket whose first debate event stays in flight until ``release()``,
    so the events published meanwhile wait in the server's queue."""

    def __init__(self) -> None:
        super().__init__()
        self.in_flight = asyncio.Event()
        self._released = asyncio.Event()

    async def send_json(self, data: dict[str, Any]) -> None:
        await super().send_json(data)
        if data.get("type") == "proposal" and not self.in_flight.is_set():
            self.in_flight.set()
            await self._released.wait()

    def release(self) -> None:
        self._released.set()


WS_HEARTBEAT = 0.05


@pytest.fixture
def ws_server(monkeypatch, storage):
    """``open_socket(user, debate_id)`` runs the aiohttp spectate socket as ``user``
    (``debate_id=None`` with ``query={"pipeline_id": ...}`` for a pipeline socket)."""
    from aragora.server.stream.servers import AiohttpUnifiedServer

    bridge = LiveBridge()
    monkeypatch.setattr("aragora.spectate.ws_bridge.get_spectate_bridge", lambda: bridge)
    monkeypatch.setattr(spectate_ws, "_resolve_debates_storage", lambda _storage: storage)
    monkeypatch.setattr(spectate_ws, "LIVE_SPECTATE_HEARTBEAT_SECONDS", WS_HEARTBEAT)
    server = AiohttpUnifiedServer(port=0, host="127.0.0.1")

    async def open_socket(
        user: Any,
        debate_id: str | None,
        *,
        socket: _Socket | None = None,
        query: dict[str, str] | None = None,
    ) -> tuple[Any, Any]:
        socket = socket or _Socket()
        monkeypatch.setattr(aiohttp.web, "WebSocketResponse", lambda **_: socket)
        act_as(monkeypatch, user)
        request = SimpleNamespace(
            headers={"Origin": "https://aragora.ai"},
            match_info={"debate_id": debate_id} if debate_id else {},
            query=query or {},
            remote="10.0.0.9",
        )
        subscribed = len(bridge.subscribers)
        task = asyncio.create_task(server._handle_spectate_websocket(request))
        for _ in range(500):
            if task.done() or len(bridge.subscribers) > subscribed:
                break
            await asyncio.sleep(0.01)
        return socket, task

    async def _settle() -> None:
        for _ in range(5):
            await asyncio.sleep(0.01)

    return SimpleNamespace(bridge=bridge, open=open_socket, settle=_settle)


class TestSpectateWebSocket:
    @pytest.mark.parametrize("viewer", [USER_B, ANON])
    async def test_socket_is_closed_on_unshare(self, share, ws_server, viewer):
        share("POST")
        socket, task = await ws_server.open(viewer, DA)
        assert not task.done(), getattr(task.result(), "status", None)
        ws_server.bridge.publish(DA, "sent while public")
        await ws_server.settle()
        assert socket.details() == ["sent while public"]

        share("DELETE")
        ws_server.bridge.publish(DA, "sent after unshare")
        await asyncio.wait_for(task, timeout=5)

        assert socket.details() == ["sent while public"]
        assert socket.sent[-1] == {"type": "share_revoked", "debate_id": DA}
        assert socket.closed
        assert ws_server.bridge.subscribers == []

    @pytest.mark.parametrize("viewer", [USER_B, ANON])
    async def test_idle_socket_is_closed_at_the_next_heartbeat(self, share, ws_server, viewer):
        share("POST")
        socket, task = await ws_server.open(viewer, DA)
        assert not task.done(), getattr(task.result(), "status", None)

        share("DELETE")
        await asyncio.wait_for(task, timeout=5)

        assert socket.sent[-1] == {"type": "share_revoked", "debate_id": DA}
        assert socket.closed
        assert ws_server.bridge.subscribers == []

    async def test_owner_socket_carries_on(self, share, ws_server):
        share("POST")
        socket, task = await ws_server.open(USER_A, DA)

        share("DELETE")
        await asyncio.sleep(WS_HEARTBEAT * 6)
        assert not task.done() and not socket.closed
        ws_server.bridge.publish(DA, "owner still sees this")
        await ws_server.settle()
        await socket.close()
        await asyncio.wait_for(task, timeout=5)

        assert socket.details() == ["owner still sees this"]
        assert not any(m.get("type") == "share_revoked" for m in socket.sent)

    @pytest.mark.parametrize(
        ("viewer", "debate_id", "status", "code"),
        [
            (ANON, DA, 401, "auth_required"),
            (USER_NO_ORG, DA, 403, "org_required"),
            (USER_B, DA, 404, "not_found"),
            (USER_A, DB, 404, "not_found"),
        ],
    )
    async def test_private_debate_socket_is_refused(
        self, ws_server, viewer, debate_id, status, code
    ):
        socket, task = await ws_server.open(viewer, debate_id)
        response = await asyncio.wait_for(task, timeout=5)

        assert response.status == status
        assert json.loads(response.text)["code"] == code
        assert socket.sent == []
        assert ws_server.bridge.subscribers == []

    @pytest.mark.parametrize("viewer", [USER_A, USER_B, ANON])
    async def test_public_debate_socket_is_served_to_anyone(self, ws_server, viewer):
        socket, task = await ws_server.open(viewer, DP)
        ws_server.bridge.publish(DP, "public opening")
        await ws_server.settle()
        await socket.close()
        await asyncio.wait_for(task, timeout=5)

        assert socket.sent[0]["type"] == "metadata"
        assert socket.details() == ["public opening"]


class TestBufferedSpectateWebSocket:
    """Events queued while one send is in flight; nothing is published after the unshare."""

    @staticmethod
    async def _queue_behind_slow_send(ws_server: Any, socket: _SlowSocket, *later: Any) -> None:
        ws_server.bridge.publish(DA, "sent while public", pipeline_id=PIPE)
        await asyncio.wait_for(socket.in_flight.wait(), timeout=5)
        for debate_id, details in later:
            ws_server.bridge.publish(debate_id, details, pipeline_id=PIPE)
        await ws_server.settle()

    @pytest.mark.parametrize("viewer", [USER_B, ANON])
    async def test_event_queued_before_unshare_is_not_sent(self, share, ws_server, viewer):
        share("POST")
        socket = _SlowSocket()
        _, task = await ws_server.open(viewer, DA, socket=socket)
        assert not task.done(), getattr(task.result(), "status", None)
        await self._queue_behind_slow_send(ws_server, socket, (DA, "queued while public"))

        share("DELETE")
        socket.release()
        await asyncio.wait_for(task, timeout=5)

        assert socket.details() == ["sent while public"]
        assert socket.sent[-1] == {"type": "share_revoked", "debate_id": DA}
        assert socket.closed
        assert ws_server.bridge.subscribers == []

    async def test_owner_socket_gets_event_queued_before_unshare(self, share, ws_server):
        share("POST")
        socket = _SlowSocket()
        _, task = await ws_server.open(USER_A, DA, socket=socket)
        await self._queue_behind_slow_send(ws_server, socket, (DA, "queued while public"))

        share("DELETE")
        socket.release()
        await asyncio.sleep(WS_HEARTBEAT * 6)
        assert not task.done() and not socket.closed
        await socket.close()
        await asyncio.wait_for(task, timeout=5)

        assert socket.details() == ["sent while public", "queued while public"]
        assert not any(m.get("type") == "share_revoked" for m in socket.sent)

    async def test_pipeline_socket_drops_event_queued_before_unshare(self, share, ws_server):
        share("POST")
        socket = _SlowSocket()
        _, task = await ws_server.open(ANON, None, socket=socket, query={"pipeline_id": PIPE})
        assert not task.done(), getattr(task.result(), "status", None)
        await self._queue_behind_slow_send(
            ws_server, socket, (DA, "queued while public"), (DP, "still public")
        )

        share("DELETE")
        socket.release()
        await asyncio.sleep(WS_HEARTBEAT * 6)
        assert not task.done() and not socket.closed
        await socket.close()
        await asyncio.wait_for(task, timeout=5)

        assert socket.details() == ["sent while public", "still public"]
        assert not any(m.get("type") == "share_revoked" for m in socket.sent)


async def _first_frames(stream: Any, limit: int = 5) -> list[str]:
    frames = []
    async for frame in stream:
        frames.append(frame)
        if len(frames) >= limit:
            break
    return frames


class TestPublicShareSse:
    """``public_spectate_sse_generator`` (not mounted on a route) sends nothing it
    queued before the unshare, also when the queue was too full to take the
    ``share_revoked`` notice."""

    @pytest.mark.parametrize("max_queue_size", [256, 1])
    async def test_event_queued_before_unshare_is_not_sent(self, share, max_queue_size):
        share("POST")
        stream = public_spectate_sse_generator(
            DA, heartbeat_interval=0.05, max_queue_size=max_queue_size
        )
        assert "event: connected" in await stream.__anext__()
        assert push_public_spectator_event(DA, "proposal", details="queued while public") == 1

        share("DELETE")
        rest = await asyncio.wait_for(_first_frames(stream), timeout=5)

        assert rest == [share_module._sse_frame("share_revoked", {"debate_id": DA})]

    async def test_event_queued_before_unshare_is_sent_once_shared_again(self, share):
        share("POST")
        stream = public_spectate_sse_generator(DA, heartbeat_interval=0.05)
        assert "event: connected" in await stream.__anext__()
        push_public_spectator_event(DA, "proposal", details="queued while public")

        share("DELETE")
        share("POST")
        rest = await asyncio.wait_for(_first_frames(stream), timeout=5)

        assert [frame.split("\n", 1)[0] for frame in rest] == [
            "event: proposal",
            "event: share_revoked",
        ]
        assert "queued while public" in rest[0]
