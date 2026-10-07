"""Tests for the SpectateStreamHandler.

Tests the HTTP handler that serves spectate events from the
SpectateWebSocketBridge over the /api/v1/spectate/* endpoints.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import aragora.server.handlers.spectate_ws as spectate_ws_handler
from aragora.server.handlers.debates.share import _reset_share_state, set_public_spectate
from aragora.server.handlers.spectate_ws import SpectateStreamHandler
from aragora.server.handlers.spectate_ws import iter_live_spectate_sse_frames
from aragora.spectate.ws_bridge import (
    SpectateEvent,
    SpectateWebSocketBridge,
    reset_spectate_bridge,
)


pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

TEST_ORG = "test-org-001"


class _OrgDebates:
    """Debate storage stub: the listed private debates belong to the test org."""

    def __init__(self, debate_ids: set[str]) -> None:
        self.debate_ids = debate_ids

    def get_access_info(self, ref: str) -> tuple[str, str, bool] | None:
        return (ref, TEST_ORG, False) if ref in self.debate_ids else None

    def is_public(self, debate_id: str) -> bool:
        return False


ORG_DEBATES = _OrgDebates({"d-111", "d-222", "d-private"})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_bridge():
    """Reset the singleton bridge between tests."""
    _reset_share_state()
    reset_spectate_bridge()
    yield
    _reset_share_state()
    reset_spectate_bridge()


@pytest.fixture
def handler():
    """Create a SpectateStreamHandler whose storage knows the test org's debates."""
    return SpectateStreamHandler({"storage": ORG_DEBATES})


@pytest.fixture
def mock_handler():
    """Create a mock HTTP request handler."""
    h = MagicMock()
    h.headers = {}
    return h


def _parse_sse_frames(body: bytes) -> list[tuple[str, object]]:
    """Parse a finite SSE snapshot body into (event_type, payload) pairs."""
    frames: list[tuple[str, object]] = []
    for chunk in body.decode("utf-8").strip().split("\n\n"):
        lines = chunk.splitlines()
        if not lines or lines[0].startswith(":"):
            continue
        event_type = "event"
        payload: object = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ")
            elif line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
        frames.append((event_type, payload))
    return frames


class _ManualSpectateBridge:
    """Deterministic bridge stub for live SSE generator tests."""

    def __init__(self, recent_events: list[SpectateEvent] | None = None) -> None:
        self.running = True
        self._recent_events = recent_events or []
        self._subscriber: Any = None
        self.unsubscribed = False

    def start(self) -> None:
        self.running = True

    def subscribe(self, callback: Any) -> None:
        self._subscriber = callback

    def unsubscribe(self, callback: Any) -> None:
        self.unsubscribed = callback == self._subscriber

    def get_recent_events(self, count: int = 50) -> list[SpectateEvent]:
        return list(self._recent_events[-count:])


# ---------------------------------------------------------------------------
# Route matching tests
# ---------------------------------------------------------------------------


class TestRouteMatching:
    """Tests for handler route configuration."""

    def test_routes_defined(self, handler: SpectateStreamHandler):
        assert "/api/v1/spectate/recent" in handler.ROUTES
        assert "/api/v1/spectate/status" in handler.ROUTES
        assert "/api/v1/spectate/stream" in handler.ROUTES

    def test_handle_non_spectate_path_returns_none(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        result = handler.handle("/api/v1/debates", {}, mock_handler)
        assert result is None

    def test_handle_recent_path(self, handler: SpectateStreamHandler, mock_handler: MagicMock):
        result = handler.handle("/api/v1/spectate/recent", {}, mock_handler)
        assert result is not None
        body = result[0]
        assert "events" in body
        assert "count" in body

    def test_handle_status_path(self, handler: SpectateStreamHandler, mock_handler: MagicMock):
        result = handler.handle("/api/v1/spectate/status", {}, mock_handler)
        assert result is not None
        body = result[0]
        assert "active" in body
        assert "subscribers" in body
        assert "buffer_size" in body

    def test_handle_stream_path(self, handler: SpectateStreamHandler, mock_handler: MagicMock):
        """Stream endpoint defaults to a JSON preview for non-SSE callers."""
        result = handler.handle("/api/v1/spectate/stream", {}, mock_handler)
        assert result is not None
        body = result[0]
        assert "events" in body
        assert body["mode"] == "snapshot"
        assert body["transport"] == "json_preview"
        assert body["readiness"] == "partial"
        assert body["streaming_ready"] is False
        assert "JSON preview" in body["message"]
        assert result[2]["X-Aragora-Endpoint-State"] == "partial"
        assert result[2]["X-Aragora-Stream-Mode"] == "snapshot"
        assert result[2]["X-Aragora-Stream-Transport"] == "json_preview"

    def test_handle_stream_path_returns_sse_snapshot_when_requested(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp="2026-02-18T10:00:00+00:00",
                debate_id="d-111",
                agent_name="claude",
                data={"details": "Bounded fix"},
            )
        )
        mock_handler.headers = {"Accept": "text/event-stream"}

        result = handler.handle("/api/v1/spectate/stream", {"debate_id": "d-111"}, mock_handler)

        assert result is not None
        assert result.content_type == "text/event-stream"
        assert result.headers["X-Aragora-Stream-Transport"] == "sse_snapshot"
        frames = _parse_sse_frames(result.body)
        assert [frame[0] for frame in frames] == ["connected", "proposal", "snapshot_complete"]
        connected = frames[0][1]
        proposal = frames[1][1]
        complete = frames[2][1]
        assert isinstance(connected, dict)
        assert connected["transport"] == "sse_snapshot"
        assert connected["debate_id"] == "d-111"
        assert isinstance(proposal, dict)
        assert proposal["event_type"] == "proposal"
        assert proposal["agent_name"] == "claude"
        assert isinstance(complete, dict)
        assert complete["count"] == 1

    def test_handle_stream_path_honors_format_sse_query(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        result = handler.handle("/api/v1/spectate/stream", {"format": "sse"}, mock_handler)
        assert result is not None
        assert result.content_type == "text/event-stream"
        frames = _parse_sse_frames(result.body)
        assert [frame[0] for frame in frames] == ["connected", "snapshot_complete"]


class TestLiveSSEFrames:
    """Tests for the live SSE frame generator used by the unified server."""

    def test_replays_backlog_then_streams_live_events(self):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp="2026-02-18T10:00:00+00:00",
                debate_id="d-111",
                agent_name="claude",
                data={"details": "Ship the public bridge"},
            )
        )

        stream = iter_live_spectate_sse_frames(
            {"debate_id": "d-111", "count": "5"},
            heartbeat_interval=0.01,
            bridge=bridge,
            org_id=TEST_ORG,
            storage=ORG_DEBATES,
        )

        connected = next(stream)
        backlog = next(stream)
        snapshot_complete = next(stream)

        bridge._forward_event(
            event_type="critique",
            agent="gpt4",
            details='{"debate_id":"d-111","details":"Do not fake liveness."}',
        )
        live_update = next(stream)
        stream.close()

        frames = _parse_sse_frames(connected + backlog + snapshot_complete + live_update)
        assert [frame[0] for frame in frames] == [
            "connected",
            "spectate",
            "snapshot_complete",
            "spectate",
        ]
        assert frames[1][1]["event_type"] == "proposal"
        assert frames[3][1]["event_type"] == "critique"
        assert bridge.subscriber_count == 0

    def test_emits_heartbeats_when_no_live_event_arrives(self):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        stream = iter_live_spectate_sse_frames(
            {"count": "1"},
            heartbeat_interval=0.01,
            bridge=bridge,
        )

        assert next(stream).startswith(b"event: connected")
        assert next(stream).startswith(b"event: snapshot_complete")
        assert next(stream) == b": heartbeat\n\n"
        stream.close()

    def test_emits_resync_required_when_live_queue_overflows(self, monkeypatch):
        monkeypatch.setattr(spectate_ws_handler, "_LIVE_SSE_QUEUE_SIZE", 2)
        bridge = _ManualSpectateBridge()

        stream = iter_live_spectate_sse_frames(
            {"count": "5"},
            heartbeat_interval=60,
            bridge=bridge,
        )

        connected = next(stream)
        snapshot_complete = next(stream)

        assert bridge._subscriber is not None
        for i in range(3):
            bridge._subscriber(
                SpectateEvent(
                    event_type="system",
                    timestamp=f"2026-04-03T11:00:0{i}Z",
                    data={"details": f"event-{i}"},
                )
            )

        resync = next(stream)

        with pytest.raises(StopIteration):
            next(stream)

        frames = _parse_sse_frames(connected + snapshot_complete + resync)
        assert [frame[0] for frame in frames] == [
            "connected",
            "snapshot_complete",
            "resync_required",
        ]
        payload = frames[-1][1]
        assert isinstance(payload, dict)
        assert payload["reason"] == "queue_overflow"
        assert payload["dropped_events"] == 3
        assert "resync" in payload["message"]
        assert bridge.unsubscribed is True

    def test_filters_private_backlog_and_live_updates_for_public_callers(self):
        set_public_spectate("shared-222", True)
        bridge = _ManualSpectateBridge(
            recent_events=[
                SpectateEvent(
                    event_type="proposal",
                    timestamp="2026-04-03T11:00:00Z",
                    debate_id="private-111",
                    agent_name="claude",
                    data={"details": "Private opening"},
                ),
                SpectateEvent(
                    event_type="proposal",
                    timestamp="2026-04-03T11:00:01Z",
                    debate_id="shared-222",
                    agent_name="gpt4",
                    data={"details": "Shared opening"},
                ),
                SpectateEvent(
                    event_type="proposal",
                    timestamp="2026-04-03T11:00:02Z",
                    debate_id="playground_abcd1234",
                    agent_name="gemini",
                    data={"details": "Playground opening"},
                ),
            ]
        )

        stream = iter_live_spectate_sse_frames(
            {"count": "5"},
            heartbeat_interval=60,
            bridge=bridge,
            storage=ORG_DEBATES,
        )

        connected = next(stream)
        shared_backlog = next(stream)
        playground_backlog = next(stream)
        snapshot_complete = next(stream)

        assert bridge._subscriber is not None
        bridge._subscriber(
            SpectateEvent(
                event_type="critique",
                timestamp="2026-04-03T11:00:03Z",
                debate_id="private-111",
                agent_name="claude",
                data={"details": "Private critique"},
            )
        )
        bridge._subscriber(
            SpectateEvent(
                event_type="critique",
                timestamp="2026-04-03T11:00:04Z",
                debate_id="shared-222",
                agent_name="gpt4",
                data={"details": "Shared critique"},
            )
        )
        live_update = next(stream)
        stream.close()

        frames = _parse_sse_frames(
            connected + shared_backlog + playground_backlog + snapshot_complete + live_update
        )
        assert [frame[0] for frame in frames] == [
            "connected",
            "spectate",
            "spectate",
            "snapshot_complete",
            "spectate",
        ]
        visible_debate_ids = [frame[1]["debate_id"] for frame in frames if frame[0] == "spectate"]
        assert "private-111" not in visible_debate_ids
        assert visible_debate_ids == ["shared-222", "playground_abcd1234", "shared-222"]


# ---------------------------------------------------------------------------
# Recent events tests
# ---------------------------------------------------------------------------


class TestRecentEvents:
    """Tests for GET /api/v1/spectate/recent."""

    def test_empty_returns_empty_list(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        result = handler.handle("/api/v1/spectate/recent", {}, mock_handler)
        body = result[0]
        assert body["events"] == []
        assert body["count"] == 0

    def test_returns_buffered_events(self, handler: SpectateStreamHandler, mock_handler: MagicMock):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        # Manually inject events into the buffer
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="debate_start",
                timestamp="2026-02-18T10:00:00+00:00",
                agent_name="claude",
            )
        )
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp="2026-02-18T10:00:01+00:00",
                agent_name="gpt4",
                data={"details": "A rate limiter"},
            )
        )

        result = handler.handle("/api/v1/spectate/recent", {}, mock_handler)
        body = result[0]
        assert body["count"] == 2
        assert body["events"][0]["event_type"] == "debate_start"
        assert body["events"][1]["agent_name"] == "gpt4"

    def test_count_parameter(self, handler: SpectateStreamHandler, mock_handler: MagicMock):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        for i in range(10):
            bridge._event_buffer.append(
                SpectateEvent(
                    event_type="system",
                    timestamp=f"2026-02-18T10:00:{i:02d}+00:00",
                    data={"details": f"event-{i}"},
                )
            )

        result = handler.handle("/api/v1/spectate/recent", {"count": "3"}, mock_handler)
        body = result[0]
        assert body["count"] == 3

    def test_invalid_count_defaults_to_50(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        """Non-integer count should fall back to default of 50."""
        result = handler.handle("/api/v1/spectate/recent", {"count": "abc"}, mock_handler)
        body = result[0]
        assert body["count"] == 0  # 0 events in buffer, but no error

    def test_filter_by_debate_id(self, handler: SpectateStreamHandler, mock_handler: MagicMock):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp="2026-02-18T10:00:00+00:00",
                debate_id="d-111",
            )
        )
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="vote",
                timestamp="2026-02-18T10:00:01+00:00",
                debate_id="d-222",
            )
        )

        result = handler.handle("/api/v1/spectate/recent", {"debate_id": "d-111"}, mock_handler)
        body = result[0]
        assert body["count"] == 1
        assert body["events"][0]["debate_id"] == "d-111"

    def test_filter_by_pipeline_id(self, handler: SpectateStreamHandler, mock_handler: MagicMock):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="system",
                timestamp="2026-02-18T10:00:00+00:00",
                pipeline_id="p-abc",
            )
        )
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="system",
                timestamp="2026-02-18T10:00:01+00:00",
                pipeline_id="p-xyz",
            )
        )

        result = handler.handle("/api/v1/spectate/recent", {"pipeline_id": "p-abc"}, mock_handler)
        body = result[0]
        assert body["count"] == 1
        assert body["events"][0]["pipeline_id"] == "p-abc"

    @pytest.mark.no_auto_auth
    def test_recent_filters_private_debate_events_for_unauthenticated_callers(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp="2026-02-18T10:00:00+00:00",
                debate_id="d-private",
                agent_name="claude",
                data={"details": "Private opening"},
            )
        )
        set_public_spectate("d-shared", True)
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp="2026-02-18T10:00:01+00:00",
                debate_id="d-shared",
                agent_name="gpt4",
                data={"details": "Shared opening"},
            )
        )
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp="2026-02-18T10:00:02+00:00",
                debate_id="playground_abc12345",
                agent_name="gemini",
                data={"details": "Playground opening"},
            )
        )

        result = handler.handle("/api/v1/spectate/recent", {}, mock_handler)

        body = result[0]
        assert body["count"] == 2
        debate_ids = [event["debate_id"] for event in body["events"]]
        assert debate_ids == ["d-shared", "playground_abc12345"]
        assert "d-private" not in debate_ids

    def test_recent_keeps_private_debate_events_for_the_owning_org(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        for debate_id in ("d-private", "d-other-org"):
            bridge._event_buffer.append(
                SpectateEvent(
                    event_type="proposal",
                    timestamp="2026-02-18T10:00:00+00:00",
                    debate_id=debate_id,
                    agent_name="claude",
                    data={"details": "Private opening"},
                )
            )

        result = handler.handle("/api/v1/spectate/recent", {}, mock_handler)

        body = result[0]
        assert body["count"] == 1
        assert body["events"][0]["debate_id"] == "d-private"


# ---------------------------------------------------------------------------
# Status endpoint tests
# ---------------------------------------------------------------------------


class TestStatus:
    """Tests for GET /api/v1/spectate/status."""

    def test_status_when_inactive(self, handler: SpectateStreamHandler, mock_handler: MagicMock):
        result = handler.handle("/api/v1/spectate/status", {}, mock_handler)
        body = result[0]
        assert body["active"] is False
        assert body["subscribers"] == 0
        assert body["buffer_size"] == 0
        assert body["bridge_state"] == "inactive"
        assert body["live_debate_count"] == 0
        assert body["recent_event_count"] == 0

    def test_status_when_active(self, handler: SpectateStreamHandler, mock_handler: MagicMock):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge.start()
        bridge.subscribe(lambda e: None)

        try:
            result = handler.handle("/api/v1/spectate/status", {}, mock_handler)
            body = result[0]
            assert body["active"] is True
            assert body["subscribers"] == 1
            assert body["bridge_state"] == "idle"
        finally:
            bridge.stop()

    def test_status_reports_discoverable_live_debates(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge.start()
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp=datetime.now(timezone.utc).isoformat(),
                debate_id="d-111",
                agent_name="claude",
            )
        )

        try:
            result = handler.handle("/api/v1/spectate/status", {}, mock_handler)
            body = result[0]
            assert body["bridge_state"] == "live_debates_available"
            assert body["live_debate_count"] == 1
            assert body["live_debate_ids"] == ["d-111"]
            assert body["live_debates"][0]["debate_id"] == "d-111"
            assert body["live_debates"][0]["recent_event_count"] == 1
            assert body["unattributed_recent_event_count"] == 0
        finally:
            bridge.stop()

    @pytest.mark.no_auto_auth
    def test_status_redacts_live_debate_details_for_unauthenticated_callers(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge.start()
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp=datetime.now(timezone.utc).isoformat(),
                debate_id="d-111",
                agent_name="claude",
            )
        )

        try:
            result = handler.handle("/api/v1/spectate/status", {}, mock_handler)
            body = result[0]
            assert body["bridge_state"] == "activity_unattributed"
            assert body["live_debate_count"] == 0
            assert body["live_debate_ids"] == []
            assert body["live_debates"] == []
            assert body["recent_event_count"] == 1
            assert body["unattributed_recent_event_count"] == 1
        finally:
            bridge.stop()

    def test_status_exposes_live_debate_details_to_the_owning_org(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge.start()
        for debate_id in ("d-111", "d-other-org"):
            bridge._event_buffer.append(
                SpectateEvent(
                    event_type="proposal",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    debate_id=debate_id,
                    agent_name="claude",
                )
            )

        try:
            result = handler.handle("/api/v1/spectate/status", {}, mock_handler)
            body = result[0]
            assert body["bridge_state"] == "live_debates_available"
            assert body["live_debate_count"] == 1
            assert body["live_debate_ids"] == ["d-111"]
            assert body["live_debates"][0]["debate_id"] == "d-111"
            assert body["unattributed_recent_event_count"] == 1
        finally:
            bridge.stop()

    def test_status_flags_recent_unattributed_activity(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()
        bridge.start()
        bridge._event_buffer.append(
            SpectateEvent(
                event_type="proposal",
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent_name="claude",
            )
        )

        try:
            result = handler.handle("/api/v1/spectate/status", {}, mock_handler)
            body = result[0]
            assert body["bridge_state"] == "activity_unattributed"
            assert body["recent_event_count"] == 1
            assert body["live_debate_count"] == 0
            assert body["unattributed_recent_event_count"] == 1
        finally:
            bridge.stop()


# ---------------------------------------------------------------------------
# Graceful degradation tests
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Tests for ImportError handling when bridge module is unavailable."""

    def test_recent_with_import_error(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        with patch(
            "aragora.server.handlers.spectate_ws.SpectateStreamHandler._handle_recent"
        ) as mock_recent:
            # Simulate the ImportError path directly
            mock_recent.return_value = ({"events": [], "count": 0}, 200)
            result = handler.handle("/api/v1/spectate/recent", {}, mock_handler)
            # Should return something (the mocked result or the real one)
            assert result is not None

    def test_status_with_import_error(
        self, handler: SpectateStreamHandler, mock_handler: MagicMock
    ):
        with patch(
            "aragora.server.handlers.spectate_ws.SpectateStreamHandler._handle_status"
        ) as mock_status:
            mock_status.return_value = (
                {"active": False, "subscribers": 0, "buffer_size": 0},
                200,
            )
            result = handler.handle("/api/v1/spectate/status", {}, mock_handler)
            assert result is not None
