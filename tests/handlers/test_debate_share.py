"""Tests for the debate share / public spectator handler.

Covers:
- Public spectate returns 403 when debate is not shared
- Public spectate returns 200 when debate is shared
- Share generates URL with debate ID
- Revoke stops public access
- Concurrent spectator limit enforcement
- SSE generator behavior
- State management helpers
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from aragora.server.handlers.base import HandlerResult
from aragora.server.handlers.debates.share import (
    DebateShareHandler,
    _MAX_PUBLIC_SPECTATORS,
    _reset_share_state,
    get_public_collectors,
    get_shared_debates,
    is_publicly_shared,
    public_spectate_sse_generator,
    push_public_spectator_event,
    set_public_spectate,
)


def _parse(result: HandlerResult) -> dict:
    return json.loads(result.body.decode("utf-8"))


def _make_handler(authenticated: bool = True) -> MagicMock:
    handler = MagicMock()
    handler.client_address = ("10.0.0.1", 12345)
    handler.headers = {"Content-Length": "0", "Host": "example.com"}
    handler.rfile = MagicMock()
    handler.rfile.read.return_value = b""
    return handler


# Share writes are org-scoped; requests act as test-user-001 of test-org-001.
pytestmark = pytest.mark.usefixtures("org_scoped_request_user")


@pytest.fixture(autouse=True)
def caller_org_owns_debates(monkeypatch):
    """Every debate in the default debate store belongs to the caller's org."""
    storage = MagicMock()
    storage.get_access_info.side_effect = lambda ref: (ref, "test-org-001", False)
    monkeypatch.setattr("aragora.server.storage.get_debates_db", lambda: storage)
    return storage


@pytest.fixture(autouse=True)
def reset_state():
    _reset_share_state()
    yield
    _reset_share_state()


# ============================================================================
# State helpers
# ============================================================================


class TestStateHelpers:
    def test_set_and_check_public_spectate(self):
        assert is_publicly_shared("d1") is False
        set_public_spectate("d1", True)
        assert is_publicly_shared("d1") is True

    def test_revoke_public_spectate(self):
        set_public_spectate("d1", True)
        set_public_spectate("d1", False)
        assert is_publicly_shared("d1") is False

    def test_get_shared_debates(self):
        set_public_spectate("d1", True)
        set_public_spectate("d2", True)
        shared = get_shared_debates()
        assert "d1" in shared
        assert "d2" in shared


# ============================================================================
# GET /api/v1/debates/{id}/spectate/public
# ============================================================================


class TestPublicSpectate:
    def test_returns_403_when_not_shared(self):
        h = DebateShareHandler()
        handler = _make_handler()
        result = h.handle("/api/v1/debates/test-debate-1/spectate/public", {}, handler)
        assert result is not None
        assert result.status_code == 403
        data = _parse(result)
        assert data["code"] == "not_shared"

    def test_returns_200_when_shared(self):
        set_public_spectate("test-debate-2", True)
        h = DebateShareHandler()
        handler = _make_handler()
        result = h.handle("/api/v1/debates/test-debate-2/spectate/public", {}, handler)
        assert result is not None
        assert result.status_code == 200
        data = _parse(result)
        assert data["debate_id"] == "test-debate-2"
        assert data["public"] is True
        assert data["spectate_available"] is True

    def test_returns_429_when_at_capacity(self):
        debate_id = "crowded-debate"
        set_public_spectate(debate_id, True)
        # Fill up collectors
        collectors = get_public_collectors()
        collectors[debate_id] = set()
        for _ in range(_MAX_PUBLIC_SPECTATORS):
            collectors[debate_id].add(asyncio.Queue())

        h = DebateShareHandler()
        handler = _make_handler()
        result = h.handle(f"/api/v1/debates/{debate_id}/spectate/public", {}, handler)
        assert result is not None
        assert result.status_code == 429
        data = _parse(result)
        assert data["code"] == "spectator_limit"


# ============================================================================
# POST /api/v1/debates/{id}/share
# ============================================================================


class TestShareEndpoint:
    def test_share_creates_url(self):
        h = DebateShareHandler()
        handler = _make_handler()
        result = h.handle_post("/api/v1/debates/my-debate/share", {}, handler)
        assert result is not None
        assert result.status_code == 200
        data = _parse(result)
        assert data["debate_id"] == "my-debate"
        assert data["public_spectate"] is True
        assert data["share_url"] == "/debate/my-debate"
        assert data["full_url"] == "https://example.com/debate/my-debate"

    def test_share_sets_public_state(self):
        h = DebateShareHandler()
        handler = _make_handler()
        h.handle_post("/api/v1/debates/my-debate/share", {}, handler)
        assert is_publicly_shared("my-debate") is True


# ============================================================================
# DELETE /api/v1/debates/{id}/share
# ============================================================================


class TestRevokeShare:
    def test_revoke_clears_public_state(self):
        set_public_spectate("my-debate", True)
        assert is_publicly_shared("my-debate") is True

        h = DebateShareHandler()
        handler = _make_handler()
        result = h.handle_delete("/api/v1/debates/my-debate/share", {}, handler)
        assert result is not None
        assert result.status_code == 200
        data = _parse(result)
        assert data["public_spectate"] is False
        assert is_publicly_shared("my-debate") is False


# ============================================================================
# Push events
# ============================================================================


class TestPushEvents:
    def test_push_returns_0_when_not_shared(self):
        count = push_public_spectator_event("no-debate", "test")
        assert count == 0

    def test_push_delivers_to_collectors(self):
        debate_id = "push-test"
        set_public_spectate(debate_id, True)
        q: asyncio.Queue = asyncio.Queue()
        collectors = get_public_collectors()
        collectors[debate_id] = {q}

        count = push_public_spectator_event(debate_id, "round_start", agent="claude")
        assert count == 1
        event = q.get_nowait()
        assert event["type"] == "round_start"
        assert event["agent"] == "claude"


# ============================================================================
# can_handle routing
# ============================================================================


class TestRouting:
    def test_can_handle_share(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/abc/share") is True

    def test_can_handle_public_spectate(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/abc/spectate/public") is True

    def test_cannot_handle_unrelated(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/abc/status") is False

    def test_cannot_handle_short_path(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates") is False
