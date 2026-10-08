from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import aiohttp
import aiohttp.web
import pytest

from aragora.server.handlers.debates.share import _reset_share_state, set_public_spectate
from aragora.server.handlers.streaming import spectate_ws
from aragora.server.stream.servers import AiohttpUnifiedServer
from aragora.spectate.ws_bridge import SpectateEvent, get_spectate_bridge, reset_spectate_bridge


@dataclass
class _FakeWSMsg:
    type: aiohttp.WSMsgType
    data: str = ""


class _StubWSIter:
    def __init__(self, messages: list[_FakeWSMsg]):
        self._messages = iter(messages)

    def __aiter__(self):
        return self

    async def __anext__(self) -> _FakeWSMsg:
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration


class _StubWebSocket:
    def __init__(self, messages: list[_FakeWSMsg] | None = None):
        self._messages = list(messages or [])
        self.sent_json: list[dict[str, Any]] = []
        self.closed = False

    async def prepare(self, request: Any) -> "_StubWebSocket":
        return self

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent_json.append(data)

    async def close(self, *args: Any, **kwargs: Any) -> None:
        self.closed = True

    def __aiter__(self):
        return _StubWSIter(self._messages)


@dataclass
class _MockRequest:
    headers: dict[str, str]
    match_info: dict[str, str]
    query: dict[str, str]
    remote: str = "127.0.0.1"


@pytest.fixture(autouse=True)
def _reset_bridge():
    reset_spectate_bridge()
    yield
    reset_spectate_bridge()


@pytest.fixture
def public_debate(monkeypatch):
    """``debate-123`` is shared publicly, so any caller may spectate it."""
    monkeypatch.setattr(spectate_ws, "_resolve_debates_storage", lambda storage: None)
    _reset_share_state()
    set_public_spectate("debate-123", True)
    yield "debate-123"
    _reset_share_state()


@pytest.fixture
def pipeline_org(monkeypatch):
    """The caller signs in for the org that owns ``pipe-7``."""
    user = SimpleNamespace(user_id="u-1", org_id="org-a", role="member", is_authenticated=True)
    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request", lambda request, user_store=None: user
    )
    monkeypatch.setattr(spectate_ws, "_resolve_debates_storage", lambda storage: None)
    monkeypatch.setattr(
        spectate_ws, "pipeline_owned", lambda pipeline_id, scope: pipeline_id == "pipe-7"
    )
    return user


def _make_request(
    *,
    debate_id: str | None = None,
    pipeline_id: str | None = None,
) -> _MockRequest:
    match_info = {"debate_id": debate_id} if debate_id else {}
    query = {"pipeline_id": pipeline_id} if pipeline_id else {}
    return _MockRequest(
        headers={"Origin": "https://aragora.ai"},
        match_info=match_info,
        query=query,
    )


class TestSpectateWebSocket:
    @pytest.mark.asyncio
    async def test_replays_metadata_and_backlog_for_debate_scope(self, monkeypatch, public_debate):
        ws_stub = _StubWebSocket(messages=[_FakeWSMsg(type=aiohttp.WSMsgType.CLOSE)])
        monkeypatch.setattr(aiohttp.web, "WebSocketResponse", lambda **_: ws_stub)

        server = AiohttpUnifiedServer(port=0, host="127.0.0.1")
        server.set_debate_state(
            "debate-123",
            {
                "loop_id": "debate-123",
                "task": "Should we ship the live debate view?",
                "agents": ["claude", "gpt4"],
                "status": "running",
                "current_round": 2,
                "messages": [],
            },
        )

        bridge = get_spectate_bridge()
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp="2026-03-27T20:00:00+00:00",
                debate_id="debate-123",
                agent_name="claude",
                round_number=2,
                data={"details": "Ship the backend transport first"},
            )
        )

        await server._handle_spectate_websocket(_make_request(debate_id="debate-123"))

        assert ws_stub.sent_json[0]["type"] == "metadata"
        assert ws_stub.sent_json[0]["debate_id"] == "debate-123"
        assert ws_stub.sent_json[0]["task"] == "Should we ship the live debate view?"
        assert ws_stub.sent_json[0]["agents"] == ["claude", "gpt4"]

        assert ws_stub.sent_json[1]["type"] == "proposal"
        assert ws_stub.sent_json[1]["agent"] == "claude"
        assert ws_stub.sent_json[1]["details"] == "Ship the backend transport first"
        assert ws_stub.sent_json[1]["round"] == 2

    @pytest.mark.asyncio
    async def test_supports_pipeline_scope_via_query_string(self, monkeypatch, pipeline_org):
        ws_stub = _StubWebSocket(messages=[_FakeWSMsg(type=aiohttp.WSMsgType.CLOSE)])
        monkeypatch.setattr(aiohttp.web, "WebSocketResponse", lambda **_: ws_stub)

        server = AiohttpUnifiedServer(port=0, host="127.0.0.1")
        bridge = get_spectate_bridge()
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="assignment_started",
                timestamp="2026-03-27T20:00:00+00:00",
                pipeline_id="pipe-7",
                data={"details": "planner -> implementer"},
            )
        )

        await server._handle_spectate_websocket(_make_request(pipeline_id="pipe-7"))

        assert ws_stub.sent_json[0]["type"] == "metadata"
        assert ws_stub.sent_json[0]["pipeline_id"] == "pipe-7"
        assert ws_stub.sent_json[1]["type"] == "assignment_started"
        assert ws_stub.sent_json[1]["pipeline_id"] == "pipe-7"

    @pytest.mark.asyncio
    async def test_pipeline_events_are_not_sent_to_anonymous_callers(self, monkeypatch):
        ws_stub = _StubWebSocket(messages=[_FakeWSMsg(type=aiohttp.WSMsgType.CLOSE)])
        monkeypatch.setattr(aiohttp.web, "WebSocketResponse", lambda **_: ws_stub)
        monkeypatch.setattr(spectate_ws, "_resolve_debates_storage", lambda storage: None)

        server = AiohttpUnifiedServer(port=0, host="127.0.0.1")
        get_spectate_bridge()._event_buffer.append(
            SpectateEvent(
                event_type="assignment_started",
                timestamp="2026-03-27T20:00:00+00:00",
                pipeline_id="pipe-7",
                data={"details": "planner -> implementer"},
            )
        )

        await server._handle_spectate_websocket(_make_request(pipeline_id="pipe-7"))

        assert [message["type"] for message in ws_stub.sent_json] == ["metadata"]

    @pytest.mark.asyncio
    async def test_requires_single_scope_parameter(self):
        server = AiohttpUnifiedServer(port=0, host="127.0.0.1")

        missing_scope = await server._handle_spectate_websocket(_make_request())
        assert missing_scope.status == 400

        conflicting_scope = await server._handle_spectate_websocket(
            _MockRequest(
                headers={"Origin": "https://aragora.ai"},
                match_info={"debate_id": "debate-123"},
                query={"pipeline_id": "pipe-7"},
            )
        )
        assert conflicting_scope.status == 400
