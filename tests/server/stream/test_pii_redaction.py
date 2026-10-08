from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp
import aiohttp.web
import pytest

from aragora.server.handlers.debates.share import _reset_share_state, set_public_spectate
from aragora.server.handlers.debates.spectate import (
    get_active_collectors,
    push_spectator_event,
)
from aragora.server.handlers.streaming import spectate_ws
from aragora.server.stream.servers import AiohttpUnifiedServer
from aragora.spectate.ws_bridge import SpectateEvent, get_spectate_bridge, reset_spectate_bridge

PII_TEXT = "Contact patient@example.com or 555-123-4567 with SSN 123-45-6789."


def _assert_pii_redacted(value: str) -> None:
    assert "patient@example.com" not in value
    assert "555-123-4567" not in value
    assert "123-45-6789" not in value
    assert "[EMAIL_REDACTED]" in value
    assert "[PHONE_REDACTED]" in value
    assert "[SSN_REDACTED]" in value


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
def _reset_spectate_state():
    reset_spectate_bridge()
    get_active_collectors().clear()
    _reset_share_state()
    yield
    _reset_share_state()
    get_active_collectors().clear()
    reset_spectate_bridge()


def _make_request(*, debate_id: str | None = None) -> _MockRequest:
    match_info = {"debate_id": debate_id} if debate_id else {}
    return _MockRequest(
        headers={"Origin": "https://aragora.ai"},
        match_info=match_info,
        query={},
    )


class TestPIIRedaction:
    def test_bridge_redacts_pii_in_buffered_raw_events(self):
        bridge = get_spectate_bridge()

        bridge._forward_event(
            "proposal",
            agent="claude",
            details=PII_TEXT,
            round_number=1,
        )

        event = bridge.get_recent_events(1)[0]
        _assert_pii_redacted(event.data["details"])
        _assert_pii_redacted(event.to_dict()["data"]["details"])

    def test_push_spectator_event_redacts_pii_before_queueing(self):
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        get_active_collectors()["debate-123"] = {queue}

        pushed = push_spectator_event(
            "debate-123",
            "proposal",
            agent="claude",
            details=PII_TEXT,
            round_number=1,
        )

        assert pushed == 1
        event = queue.get_nowait()
        _assert_pii_redacted(event["details"])

    @pytest.mark.asyncio
    async def test_websocket_redacts_pii_in_metadata_and_backlog_payload(self, monkeypatch):
        ws_stub = _StubWebSocket(messages=[_FakeWSMsg(type=aiohttp.WSMsgType.CLOSE)])
        monkeypatch.setattr(aiohttp.web, "WebSocketResponse", lambda **_: ws_stub)
        # Anonymous spectators only see publicly shared debates.
        monkeypatch.setattr(spectate_ws, "_resolve_debates_storage", lambda storage: None)
        set_public_spectate("debate-123", True)

        server = AiohttpUnifiedServer(port=0, host="127.0.0.1")
        server.set_debate_state(
            "debate-123",
            {
                "loop_id": "debate-123",
                "task": f"Review proposal: {PII_TEXT}",
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
                timestamp="2026-03-31T20:00:00+00:00",
                debate_id="debate-123",
                agent_name="claude",
                round_number=2,
                data={
                    "details": PII_TEXT,
                    "task": f"Backlog task: {PII_TEXT}",
                },
            )
        )

        await server._handle_spectate_websocket(_make_request(debate_id="debate-123"))

        _assert_pii_redacted(ws_stub.sent_json[0]["task"])
        _assert_pii_redacted(ws_stub.sent_json[1]["details"])
        _assert_pii_redacted(ws_stub.sent_json[1]["task"])
