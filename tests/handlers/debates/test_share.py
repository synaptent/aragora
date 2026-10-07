"""Comprehensive tests for the debate share / public spectator handler.

Covers:
- DebateShareHandler instantiation and configuration
- can_handle routing (accept/reject paths)
- GET /api/v1/debates/{id}/spectate/public (public spectate endpoint)
- POST /api/v1/debates/{id}/share (enable sharing, auth required)
- DELETE /api/v1/debates/{id}/share (revoke sharing, auth required)
- State helpers: set_public_spectate, is_publicly_shared, get_shared_debates,
  get_public_collectors, _reset_share_state
- push_public_spectator_event delivery and edge cases
- public_spectate_sse_generator async SSE stream
- _sse_frame formatting
- Security: path traversal, injection, concurrent spectator limits
- Method not allowed / unknown routes
- Edge cases: empty IDs, special characters, unicode, host headers
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.debates.share import (
    DebateShareHandler,
    _MAX_PUBLIC_SPECTATORS,
    _reset_share_state,
    _sse_frame,
    get_public_collectors,
    get_shared_debates,
    is_publicly_shared,
    public_spectate_sse_generator,
    push_public_spectator_event,
    set_public_spectate,
)

# Share writes are org-scoped; requests act as test-user-001 of test-org-001.
pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

TEST_ORG = "test-org-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict[str, Any]:
    """Extract JSON body from a HandlerResult."""
    if result is None:
        return {}
    raw = result.body
    if isinstance(raw, bytes):
        return json.loads(raw.decode())
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _status(result) -> int:
    """Extract status code from a HandlerResult."""
    if result is None:
        return 0
    return result.status_code


def _make_http_handler(
    body: dict[str, Any] | None = None,
    host: str = "example.com",
) -> MagicMock:
    """Create a mock HTTP handler object."""
    h = MagicMock()
    h.command = "GET"
    h.client_address = ("10.0.0.1", 12345)
    if body:
        body_bytes = json.dumps(body).encode()
        h.rfile.read.return_value = body_bytes
        h.headers = {"Content-Length": str(len(body_bytes)), "Host": host}
    else:
        h.rfile.read.return_value = b"{}"
        h.headers = {"Content-Length": "2", "Host": host}
    return h


def _org_storage(org_id: str = TEST_ORG) -> MagicMock:
    """Debate storage in which every debate id is a private debate of ``org_id``."""
    storage = MagicMock()
    storage.get_access_info.side_effect = lambda ref: (ref, org_id, False)
    return storage


@pytest.fixture(autouse=True)
def debates_db(monkeypatch):
    """The default debate store: every debate belongs to the caller's org."""
    storage = _org_storage()
    monkeypatch.setattr("aragora.server.storage.get_debates_db", lambda: storage)
    return storage


# ---------------------------------------------------------------------------
# Fixture: reset share state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_state():
    """Reset all share state before and after each test."""
    _reset_share_state()
    yield
    _reset_share_state()


# ===========================================================================
# Handler instantiation
# ===========================================================================


class TestHandlerInstantiation:
    """Tests for DebateShareHandler creation."""

    def test_default_ctx(self):
        h = DebateShareHandler()
        assert h.ctx == {}

    def test_custom_ctx(self):
        ctx = {"storage": MagicMock()}
        h = DebateShareHandler(ctx=ctx)
        assert h.ctx is ctx

    def test_none_ctx_defaults_to_empty(self):
        h = DebateShareHandler(ctx=None)
        assert h.ctx == {}

    def test_routes_defined(self):
        assert len(DebateShareHandler.ROUTES) == 2
        assert "/api/v1/debates/*/share" in DebateShareHandler.ROUTES
        assert "/api/v1/debates/*/spectate/public" in DebateShareHandler.ROUTES


# ===========================================================================
# can_handle routing
# ===========================================================================


class TestCanHandle:
    """Tests for can_handle route matching."""

    def test_share_route(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/abc-123/share") is True

    def test_spectate_public_route(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/abc-123/spectate/public") is True

    def test_unrelated_route(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/abc-123/status") is False

    def test_short_path(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates") is False

    def test_root_path(self):
        h = DebateShareHandler()
        assert h.can_handle("/") is False

    def test_empty_path(self):
        h = DebateShareHandler()
        assert h.can_handle("") is False

    def test_wrong_version(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v2/debates/abc/share") is False

    def test_wrong_prefix(self):
        h = DebateShareHandler()
        assert h.can_handle("/web/v1/debates/abc/share") is False

    def test_extra_segments(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/abc/share/extra") is False

    def test_missing_debates_segment(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/topics/abc/share") is False

    def test_spectate_without_public(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/abc/spectate") is False

    def test_spectate_wrong_suffix(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/abc/spectate/private") is False

    def test_numeric_debate_id(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/12345/share") is True

    def test_uuid_debate_id(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/550e8400-e29b-41d4-a716-446655440000/share") is True

    def test_unicode_debate_id(self):
        h = DebateShareHandler()
        assert h.can_handle("/api/v1/debates/debate-\u00e9/share") is True


# ===========================================================================
# _extract_debate_id
# ===========================================================================


class TestExtractDebateId:
    """Tests for _extract_debate_id private method."""

    def test_extracts_from_share_path(self):
        h = DebateShareHandler()
        assert h._extract_debate_id("/api/v1/debates/my-id/share") == "my-id"

    def test_extracts_from_spectate_path(self):
        h = DebateShareHandler()
        assert h._extract_debate_id("/api/v1/debates/my-id/spectate/public") == "my-id"

    def test_returns_none_for_short_path(self):
        h = DebateShareHandler()
        assert h._extract_debate_id("/api/v1/debates") is None

    def test_returns_none_for_very_short_path(self):
        h = DebateShareHandler()
        assert h._extract_debate_id("/api") is None

    def test_extracts_empty_string_segment(self):
        h = DebateShareHandler()
        # Path with empty id segment: "/api/v1/debates//share"
        result = h._extract_debate_id("/api/v1/debates//share")
        assert result == ""


# ===========================================================================
# GET /api/v1/debates/{id}/spectate/public
# ===========================================================================


class TestPublicSpectate:
    """Tests for the public spectate GET endpoint."""

    def test_returns_403_when_debate_not_shared(self):
        h = DebateShareHandler()
        result = h.handle("/api/v1/debates/test-1/spectate/public", {}, _make_http_handler())
        assert _status(result) == 403
        body = _body(result)
        assert body["code"] == "not_shared"
        assert "not publicly shared" in body["error"]

    def test_returns_200_when_debate_is_shared(self):
        set_public_spectate("test-2", True)
        h = DebateShareHandler()
        result = h.handle("/api/v1/debates/test-2/spectate/public", {}, _make_http_handler())
        assert _status(result) == 200
        body = _body(result)
        assert body["debate_id"] == "test-2"
        assert body["public"] is True
        assert body["spectate_available"] is True

    def test_returns_active_viewer_count(self):
        debate_id = "viewer-count-test"
        set_public_spectate(debate_id, True)
        # Add 3 mock collectors
        collectors = get_public_collectors()
        collectors[debate_id] = {asyncio.Queue() for _ in range(3)}

        h = DebateShareHandler()
        result = h.handle(f"/api/v1/debates/{debate_id}/spectate/public", {}, _make_http_handler())
        assert _status(result) == 200
        body = _body(result)
        assert body["active_viewers"] == 3
        assert body["max_viewers"] == _MAX_PUBLIC_SPECTATORS

    def test_returns_sse_url(self):
        debate_id = "sse-url-test"
        set_public_spectate(debate_id, True)
        h = DebateShareHandler()
        result = h.handle(f"/api/v1/debates/{debate_id}/spectate/public", {}, _make_http_handler())
        body = _body(result)
        assert body["sse_url"] == f"/api/v1/debates/{debate_id}/spectate/public"

    def test_returns_429_when_at_capacity(self):
        debate_id = "full-debate"
        set_public_spectate(debate_id, True)
        collectors = get_public_collectors()
        collectors[debate_id] = {asyncio.Queue() for _ in range(_MAX_PUBLIC_SPECTATORS)}

        h = DebateShareHandler()
        result = h.handle(f"/api/v1/debates/{debate_id}/spectate/public", {}, _make_http_handler())
        assert _status(result) == 429
        body = _body(result)
        assert body["code"] == "spectator_limit"
        assert body["max_spectators"] == _MAX_PUBLIC_SPECTATORS

    def test_returns_429_body_has_error_message(self):
        debate_id = "cap-msg"
        set_public_spectate(debate_id, True)
        collectors = get_public_collectors()
        collectors[debate_id] = {asyncio.Queue() for _ in range(_MAX_PUBLIC_SPECTATORS)}

        h = DebateShareHandler()
        result = h.handle(f"/api/v1/debates/{debate_id}/spectate/public", {}, _make_http_handler())
        body = _body(result)
        assert "Maximum spectators" in body["error"]

    def test_at_limit_minus_one_still_allowed(self):
        debate_id = "almost-full"
        set_public_spectate(debate_id, True)
        collectors = get_public_collectors()
        collectors[debate_id] = {asyncio.Queue() for _ in range(_MAX_PUBLIC_SPECTATORS - 1)}

        h = DebateShareHandler()
        result = h.handle(f"/api/v1/debates/{debate_id}/spectate/public", {}, _make_http_handler())
        assert _status(result) == 200
        body = _body(result)
        assert body["active_viewers"] == _MAX_PUBLIC_SPECTATORS - 1

    def test_zero_active_viewers_when_no_collectors(self):
        debate_id = "no-viewers"
        set_public_spectate(debate_id, True)
        h = DebateShareHandler()
        result = h.handle(f"/api/v1/debates/{debate_id}/spectate/public", {}, _make_http_handler())
        body = _body(result)
        assert body["active_viewers"] == 0

    def test_handle_returns_none_for_share_path(self):
        """handle() only dispatches to spectate/public, not to /share."""
        h = DebateShareHandler()
        result = h.handle("/api/v1/debates/test/share", {}, _make_http_handler())
        assert result is None

    def test_handle_returns_none_for_unknown_path(self):
        h = DebateShareHandler()
        result = h.handle("/api/v1/debates/test/unknown", {}, _make_http_handler())
        assert result is None


# ===========================================================================
# POST /api/v1/debates/{id}/share
# ===========================================================================


class TestSharePost:
    """Tests for the POST share endpoint."""

    def test_creates_share_url(self):
        h = DebateShareHandler()
        result = h.handle_post("/api/v1/debates/my-debate/share", {}, _make_http_handler())
        assert _status(result) == 200
        body = _body(result)
        assert body["debate_id"] == "my-debate"
        assert body["public_spectate"] is True
        assert body["share_url"] == "/debate/my-debate"
        assert body["full_url"] == "https://example.com/debate/my-debate"

    def test_share_sets_public_state(self):
        h = DebateShareHandler()
        h.handle_post("/api/v1/debates/my-debate/share", {}, _make_http_handler())
        assert is_publicly_shared("my-debate") is True

    def test_share_persists_public_state_to_storage(self):
        storage = _org_storage()
        h = DebateShareHandler(ctx={"storage": storage})

        result = h.handle_post("/api/v1/debates/stored/share", {}, _make_http_handler())

        assert _status(result) == 200
        storage.set_public.assert_called_once_with("stored", True, org_id=TEST_ORG)

    def test_full_url_uses_host_header(self):
        h = DebateShareHandler()
        handler = _make_http_handler(host="debates.example.org")
        result = h.handle_post("/api/v1/debates/test-1/share", {}, handler)
        body = _body(result)
        assert body["full_url"] == "https://debates.example.org/debate/test-1"

    def test_full_url_uses_default_host_when_header_missing(self):
        h = DebateShareHandler()
        handler = _make_http_handler()
        # Remove Host header
        handler.headers = {"Content-Length": "2"}
        result = h.handle_post("/api/v1/debates/test-1/share", {}, handler)
        body = _body(result)
        # Should fall back to _DEFAULT_HOST
        assert "https://" in body["full_url"]

    def test_share_url_contains_debate_id(self):
        h = DebateShareHandler()
        result = h.handle_post("/api/v1/debates/specific-id/share", {}, _make_http_handler())
        body = _body(result)
        assert "specific-id" in body["share_url"]

    def test_idempotent_share(self):
        """Sharing the same debate twice should succeed both times."""
        h = DebateShareHandler()
        handler = _make_http_handler()
        result1 = h.handle_post("/api/v1/debates/idem/share", {}, handler)
        result2 = h.handle_post("/api/v1/debates/idem/share", {}, handler)
        assert _status(result1) == 200
        assert _status(result2) == 200
        assert is_publicly_shared("idem") is True

    def test_share_different_debates(self):
        h = DebateShareHandler()
        handler = _make_http_handler()
        h.handle_post("/api/v1/debates/d1/share", {}, handler)
        h.handle_post("/api/v1/debates/d2/share", {}, handler)
        assert is_publicly_shared("d1") is True
        assert is_publicly_shared("d2") is True

    def test_returns_none_for_spectate_path(self):
        """handle_post should return None for non-share paths."""
        h = DebateShareHandler()
        result = h.handle_post("/api/v1/debates/test/spectate/public", {}, _make_http_handler())
        assert result is None

    def test_returns_none_for_wrong_length_path(self):
        h = DebateShareHandler()
        result = h.handle_post("/api/v1/debates/share", {}, _make_http_handler())
        assert result is None

    def test_other_org_debate_is_not_shared(self):
        storage = _org_storage("org-other")
        h = DebateShareHandler(ctx={"storage": storage})

        result = h.handle_post("/api/v1/debates/theirs/share", {}, _make_http_handler())

        assert _status(result) == 404
        assert _body(result) == {"error": "Debate not found", "code": "not_found"}
        assert is_publicly_shared("theirs") is False
        storage.set_public.assert_not_called()

    @pytest.mark.no_auto_auth
    def test_anonymous_share_is_refused(self, monkeypatch, debates_db):
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: MagicMock(is_authenticated=False, org_id=None),
        )
        h = DebateShareHandler()

        result = h.handle_post("/api/v1/debates/mine/share", {}, _make_http_handler())

        assert _status(result) == 401
        assert is_publicly_shared("mine") is False
        debates_db.set_public.assert_not_called()

    def test_full_url_https_scheme(self):
        h = DebateShareHandler()
        result = h.handle_post("/api/v1/debates/test/share", {}, _make_http_handler())
        body = _body(result)
        assert body["full_url"].startswith("https://")


# ===========================================================================
# DELETE /api/v1/debates/{id}/share
# ===========================================================================


class TestShareDelete:
    """Tests for the DELETE share endpoint."""

    def test_revoke_clears_public_state(self):
        set_public_spectate("my-debate", True)
        h = DebateShareHandler()
        result = h.handle_delete("/api/v1/debates/my-debate/share", {}, _make_http_handler())
        assert _status(result) == 200
        body = _body(result)
        assert body["public_spectate"] is False
        assert body["debate_id"] == "my-debate"
        assert is_publicly_shared("my-debate") is False

    def test_revoke_persists_private_state_to_storage(self):
        storage = _org_storage()
        h = DebateShareHandler(ctx={"storage": storage})

        result = h.handle_delete("/api/v1/debates/stored/share", {}, _make_http_handler())

        assert _status(result) == 200
        storage.set_public.assert_called_once_with("stored", False, org_id=TEST_ORG)

    def test_other_org_cannot_revoke(self):
        set_public_spectate("theirs", True)
        storage = _org_storage("org-other")
        h = DebateShareHandler(ctx={"storage": storage})

        result = h.handle_delete("/api/v1/debates/theirs/share", {}, _make_http_handler())

        assert _status(result) == 404
        assert is_publicly_shared("theirs") is True
        storage.set_public.assert_not_called()

    def test_revoke_nonexistent_share_succeeds(self):
        """Revoking a debate that was never shared should still succeed."""
        h = DebateShareHandler()
        result = h.handle_delete("/api/v1/debates/never-shared/share", {}, _make_http_handler())
        assert _status(result) == 200
        body = _body(result)
        assert body["public_spectate"] is False

    def test_revoke_then_spectate_returns_403(self):
        set_public_spectate("revoke-test", True)
        h = DebateShareHandler()
        h.handle_delete("/api/v1/debates/revoke-test/share", {}, _make_http_handler())
        result = h.handle("/api/v1/debates/revoke-test/spectate/public", {}, _make_http_handler())
        assert _status(result) == 403

    def test_returns_none_for_wrong_path(self):
        h = DebateShareHandler()
        result = h.handle_delete("/api/v1/debates/test/spectate/public", {}, _make_http_handler())
        assert result is None

    def test_returns_none_for_wrong_length_path(self):
        h = DebateShareHandler()
        result = h.handle_delete("/api/v1/debates", {}, _make_http_handler())
        assert result is None

    def test_share_then_revoke_then_reshare(self):
        h = DebateShareHandler()
        handler = _make_http_handler()
        h.handle_post("/api/v1/debates/cycle/share", {}, handler)
        assert is_publicly_shared("cycle") is True
        h.handle_delete("/api/v1/debates/cycle/share", {}, handler)
        assert is_publicly_shared("cycle") is False
        h.handle_post("/api/v1/debates/cycle/share", {}, handler)
        assert is_publicly_shared("cycle") is True


# ===========================================================================
# State helpers
# ===========================================================================


class TestStateHelpers:
    """Tests for module-level state management functions."""

    def test_is_publicly_shared_false_by_default(self):
        assert is_publicly_shared("nonexistent") is False

    def test_set_and_check(self):
        set_public_spectate("d1", True)
        assert is_publicly_shared("d1") is True

    def test_revoke(self):
        set_public_spectate("d1", True)
        set_public_spectate("d1", False)
        assert is_publicly_shared("d1") is False

    def test_get_shared_debates_returns_registry(self):
        set_public_spectate("d1", True)
        set_public_spectate("d2", True)
        shared = get_shared_debates()
        assert "d1" in shared
        assert "d2" in shared
        assert shared["d1"] is True

    def test_get_shared_debates_excludes_revoked(self):
        set_public_spectate("d1", True)
        set_public_spectate("d1", False)
        shared = get_shared_debates()
        assert "d1" not in shared

    def test_get_public_collectors_empty_initially(self):
        collectors = get_public_collectors()
        assert isinstance(collectors, dict)
        assert len(collectors) == 0

    def test_reset_clears_everything(self):
        set_public_spectate("d1", True)
        collectors = get_public_collectors()
        collectors["d1"] = {asyncio.Queue()}
        _reset_share_state()
        assert is_publicly_shared("d1") is False
        assert len(get_public_collectors()) == 0

    def test_revoke_cleans_up_collectors(self):
        set_public_spectate("d1", True)
        collectors = get_public_collectors()
        collectors["d1"] = {asyncio.Queue()}
        set_public_spectate("d1", False)
        assert "d1" not in get_public_collectors()

    def test_revoke_sends_share_revoked_event(self):
        set_public_spectate("d1", True)
        q = asyncio.Queue()
        collectors = get_public_collectors()
        collectors["d1"] = {q}
        set_public_spectate("d1", False)
        event = q.get_nowait()
        assert event["type"] == "share_revoked"
        assert "timestamp" in event

    def test_revoke_with_full_queue_does_not_crash(self):
        set_public_spectate("d1", True)
        q = asyncio.Queue(maxsize=1)
        q.put_nowait({"type": "filler"})
        collectors = get_public_collectors()
        collectors["d1"] = {q}
        # Should not raise even though queue is full
        set_public_spectate("d1", False)

    def test_revoke_notifies_multiple_collectors(self):
        set_public_spectate("d1", True)
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        collectors = get_public_collectors()
        collectors["d1"] = {q1, q2}
        set_public_spectate("d1", False)
        assert q1.get_nowait()["type"] == "share_revoked"
        assert q2.get_nowait()["type"] == "share_revoked"


# ===========================================================================
# push_public_spectator_event
# ===========================================================================


class TestPushEvents:
    """Tests for push_public_spectator_event."""

    def test_returns_0_when_not_shared(self):
        count = push_public_spectator_event("no-debate", "test_event")
        assert count == 0

    def test_returns_0_when_shared_but_no_collectors(self):
        set_public_spectate("d1", True)
        count = push_public_spectator_event("d1", "test_event")
        assert count == 0

    def test_delivers_to_single_collector(self):
        debate_id = "push-1"
        set_public_spectate(debate_id, True)
        q = asyncio.Queue()
        get_public_collectors()[debate_id] = {q}

        count = push_public_spectator_event(debate_id, "round_start", agent="claude")
        assert count == 1
        event = q.get_nowait()
        assert event["type"] == "round_start"
        assert event["agent"] == "claude"

    def test_delivers_to_multiple_collectors(self):
        debate_id = "push-multi"
        set_public_spectate(debate_id, True)
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        q3 = asyncio.Queue()
        get_public_collectors()[debate_id] = {q1, q2, q3}

        count = push_public_spectator_event(debate_id, "vote")
        assert count == 3

    def test_event_fields(self):
        debate_id = "push-fields"
        set_public_spectate(debate_id, True)
        q = asyncio.Queue()
        get_public_collectors()[debate_id] = {q}

        push_public_spectator_event(
            debate_id,
            "consensus",
            agent="gpt-4",
            details="Agreement reached",
            metric=0.95,
            round_number=3,
        )
        event = q.get_nowait()
        assert event["type"] == "consensus"
        assert event["agent"] == "gpt-4"
        assert event["details"] == "Agreement reached"
        assert event["metric"] == 0.95
        assert event["round"] == 3
        assert "timestamp" in event

    def test_empty_agent_becomes_none(self):
        debate_id = "push-none"
        set_public_spectate(debate_id, True)
        q = asyncio.Queue()
        get_public_collectors()[debate_id] = {q}

        push_public_spectator_event(debate_id, "test")
        event = q.get_nowait()
        assert event["agent"] is None
        assert event["details"] is None
        assert event["metric"] is None
        assert event["round"] is None

    def test_full_queue_evicts_oldest(self):
        debate_id = "push-full"
        set_public_spectate(debate_id, True)
        q = asyncio.Queue(maxsize=1)
        q.put_nowait({"type": "old_event"})
        get_public_collectors()[debate_id] = {q}

        count = push_public_spectator_event(debate_id, "new_event")
        assert count == 1
        event = q.get_nowait()
        assert event["type"] == "new_event"

    def test_dead_queues_removed(self):
        """Queues that are both full and can't be drained should be discarded."""
        debate_id = "push-dead"
        set_public_spectate(debate_id, True)

        # Create a real queue and a dead queue
        good_q = asyncio.Queue()
        # Simulate dead queue: we manually create a full queue with maxsize=0
        # Actually, use maxsize=1 and fill it, then we'll patch get_nowait to fail
        dead_q = asyncio.Queue(maxsize=1)
        dead_q.put_nowait({"type": "stuck"})

        # Monkey-patch the dead queue so get_nowait also raises
        original_get = dead_q.get_nowait

        def broken_get():
            raise asyncio.QueueEmpty()

        dead_q.get_nowait = broken_get

        # Also patch put_nowait to raise after get succeeds
        original_put = dead_q.put_nowait

        def broken_put(item):
            raise asyncio.QueueFull()

        dead_q.put_nowait = broken_put

        get_public_collectors()[debate_id] = {good_q, dead_q}

        count = push_public_spectator_event(debate_id, "test")
        assert count == 1  # only good_q received it
        assert dead_q not in get_public_collectors()[debate_id]

    def test_timestamp_is_recent(self):
        debate_id = "push-ts"
        set_public_spectate(debate_id, True)
        q = asyncio.Queue()
        get_public_collectors()[debate_id] = {q}

        before = time.time()
        push_public_spectator_event(debate_id, "test")
        after = time.time()

        event = q.get_nowait()
        assert before <= event["timestamp"] <= after


# ===========================================================================
# _sse_frame formatting
# ===========================================================================


class TestSseFrame:
    """Tests for the _sse_frame helper function."""

    def test_basic_format(self):
        frame = _sse_frame("test_event", {"key": "value"})
        assert frame.startswith("event: test_event\n")
        assert "data: " in frame
        assert frame.endswith("\n\n")

    def test_data_is_valid_json(self):
        frame = _sse_frame("evt", {"a": 1, "b": "two"})
        lines = frame.strip().split("\n")
        data_line = [l for l in lines if l.startswith("data: ")][0]
        parsed = json.loads(data_line[6:])
        assert parsed["a"] == 1
        assert parsed["b"] == "two"

    def test_handles_non_serializable(self):
        """_sse_frame uses default=str for json.dumps."""
        from datetime import datetime

        data = {"time": datetime(2026, 1, 1)}
        frame = _sse_frame("test", data)
        assert "2026" in frame

    def test_event_type_in_output(self):
        frame = _sse_frame("custom_type", {})
        assert "event: custom_type\n" in frame


# ===========================================================================
# public_spectate_sse_generator (async)
# ===========================================================================


class TestPublicSpectateSSEGenerator:
    """Tests for the SSE async generator."""

    @pytest.mark.asyncio
    async def test_yields_error_when_not_shared(self):
        frames = []
        async for frame in public_spectate_sse_generator("not-shared"):
            frames.append(frame)
        assert len(frames) == 1
        assert "error" in frames[0]
        assert "not publicly shared" in frames[0].lower()

    @pytest.mark.asyncio
    async def test_yields_error_at_capacity(self):
        debate_id = "sse-full"
        set_public_spectate(debate_id, True)
        collectors = get_public_collectors()
        collectors[debate_id] = {asyncio.Queue() for _ in range(_MAX_PUBLIC_SPECTATORS)}

        frames = []
        async for frame in public_spectate_sse_generator(debate_id):
            frames.append(frame)
        assert len(frames) == 1
        assert "Maximum spectators" in frames[0]

    @pytest.mark.asyncio
    async def test_yields_connected_event_first(self):
        debate_id = "sse-connect"
        set_public_spectate(debate_id, True)

        frames = []

        async def collect():
            async for frame in public_spectate_sse_generator(debate_id):
                frames.append(frame)
                if len(frames) >= 1:
                    break

        task = asyncio.create_task(collect())
        # Give the generator time to start
        await asyncio.sleep(0.05)

        # The generator should have yielded a connected event
        # But it's blocked waiting for queue items after that.
        # We need to push a share_revoked event to unblock it.
        collectors = get_public_collectors()
        for q in collectors.get(debate_id, set()):
            q.put_nowait({"type": "share_revoked"})

        await asyncio.wait_for(task, timeout=2.0)
        assert len(frames) >= 1
        assert "connected" in frames[0]

    @pytest.mark.asyncio
    async def test_share_revoked_stops_generator(self):
        debate_id = "sse-revoke"
        set_public_spectate(debate_id, True)

        frames = []

        async def collect():
            async for frame in public_spectate_sse_generator(debate_id):
                frames.append(frame)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.05)

        # Push revoked event
        collectors = get_public_collectors()
        for q in collectors.get(debate_id, set()):
            q.put_nowait({"type": "share_revoked"})

        await asyncio.wait_for(task, timeout=2.0)
        # Should have connected + share_revoked frames
        assert any("share_revoked" in f for f in frames)

    @pytest.mark.asyncio
    async def test_forwards_regular_events(self):
        debate_id = "sse-forward"
        set_public_spectate(debate_id, True)

        frames = []

        async def collect():
            async for frame in public_spectate_sse_generator(debate_id):
                frames.append(frame)
                # Break after we get the forwarded event + connected + revoked
                if any("share_revoked" in f for f in frames):
                    break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.05)

        collectors = get_public_collectors()
        for q in collectors.get(debate_id, set()):
            q.put_nowait({"type": "round_start", "round": 1})
            q.put_nowait({"type": "share_revoked"})

        await asyncio.wait_for(task, timeout=2.0)
        assert any("round_start" in f for f in frames)

    @pytest.mark.asyncio
    async def test_heartbeat_on_timeout(self):
        debate_id = "sse-heartbeat"
        set_public_spectate(debate_id, True)

        frames = []

        async def collect():
            async for frame in public_spectate_sse_generator(debate_id, heartbeat_interval=0.1):
                frames.append(frame)
                if len(frames) >= 3:
                    break

        task = asyncio.create_task(collect())
        # Let it run for a bit to get heartbeats
        await asyncio.sleep(0.35)

        # Stop the generator by pushing revoke
        collectors = get_public_collectors()
        for q in collectors.get(debate_id, set()):
            q.put_nowait({"type": "share_revoked"})

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.CancelledError:
            pass

        # Should have at least connected + heartbeat(s)
        heartbeats = [f for f in frames if "heartbeat" in f]
        assert len(heartbeats) >= 1

    @pytest.mark.asyncio
    async def test_cleanup_on_disconnect(self):
        debate_id = "sse-cleanup"
        set_public_spectate(debate_id, True)

        generator = public_spectate_sse_generator(debate_id)
        frame = await asyncio.wait_for(generator.__anext__(), timeout=2.0)
        assert "connected" in frame
        await generator.aclose()

        # After disconnect, the queue should be removed
        collectors = get_public_collectors()
        # The debate may still be in collectors but the queue should be gone
        if debate_id in collectors:
            assert len(collectors[debate_id]) == 0

    @pytest.mark.asyncio
    async def test_creates_collector_entry(self):
        debate_id = "sse-creates"
        set_public_spectate(debate_id, True)
        assert debate_id not in get_public_collectors()

        generator = public_spectate_sse_generator(debate_id)
        frame = await asyncio.wait_for(generator.__anext__(), timeout=2.0)
        assert "connected" in frame
        await generator.aclose()
        # Queue was registered then cleaned up
        # But the entry may remain as empty set - that's fine

    @pytest.mark.asyncio
    async def test_custom_max_queue_size(self):
        debate_id = "sse-qsize"
        set_public_spectate(debate_id, True)

        generator = public_spectate_sse_generator(debate_id, max_queue_size=10)
        frame = await asyncio.wait_for(generator.__anext__(), timeout=2.0)
        assert "connected" in frame
        await generator.aclose()
        # Just verifying it doesn't crash with custom queue size


# ===========================================================================
# Security tests
# ===========================================================================


class TestSecurity:
    """Security-related tests."""

    def test_path_traversal_in_debate_id(self):
        h = DebateShareHandler()
        # Path traversal attempt
        result = h.handle(
            "/api/v1/debates/../../../etc/passwd/spectate/public", {}, _make_http_handler()
        )
        # The handler will try to extract the ID which is ".." - this is fine
        # since it's not a filesystem operation. The key is it doesn't crash.
        # The path has wrong number of segments so can_handle returns False
        assert result is None or _status(result) in (400, 403, 404)

    def test_sql_injection_in_debate_id_spectate(self):
        """SQL injection in debate ID should not crash the handler."""
        h = DebateShareHandler()
        result = h.handle("/api/v1/debates/' OR 1=1 --/spectate/public", {}, _make_http_handler())
        # The debate isn't shared, so it returns 403
        assert _status(result) == 403
        body = _body(result)
        assert body["code"] == "not_shared"

    def test_sql_injection_in_debate_id_share(self):
        h = DebateShareHandler()
        result = h.handle_post("/api/v1/debates/' OR 1=1 --/share", {}, _make_http_handler())
        assert _status(result) == 200
        body = _body(result)
        assert body["debate_id"] == "' OR 1=1 --"

    def test_xss_in_debate_id(self):
        """XSS in debate ID: the path with slashes in the ID changes
        segment count, so can_handle rejects it. This is safe behavior."""
        h = DebateShareHandler()
        # <script>alert(1)</script> contains no slashes so it's a valid segment
        xss_id = "<script>alert(1)<.script>"
        set_public_spectate(xss_id, True)
        result = h.handle(f"/api/v1/debates/{xss_id}/spectate/public", {}, _make_http_handler())
        assert _status(result) == 200
        body = _body(result)
        # The ID is passed through but JSON encoding escapes HTML
        assert body["debate_id"] == xss_id

    def test_very_long_debate_id(self):
        h = DebateShareHandler()
        long_id = "a" * 10000
        result = h.handle(f"/api/v1/debates/{long_id}/spectate/public", {}, _make_http_handler())
        # Should return 403 (not shared) without crashing
        assert _status(result) == 403

    def test_null_byte_in_debate_id(self):
        h = DebateShareHandler()
        result = h.handle("/api/v1/debates/test\x00id/spectate/public", {}, _make_http_handler())
        assert _status(result) == 403

    def test_unicode_debate_id_spectate(self):
        h = DebateShareHandler()
        uid = "debat-\u00e9-\u4e2d\u6587"
        set_public_spectate(uid, True)
        result = h.handle(f"/api/v1/debates/{uid}/spectate/public", {}, _make_http_handler())
        assert _status(result) == 200
        body = _body(result)
        assert body["debate_id"] == uid


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge case and miscellaneous tests."""

    def test_handler_with_no_headers_attribute(self):
        """Handler without headers attribute should use default host."""
        h = DebateShareHandler()
        handler = MagicMock(spec=[])  # No attributes
        # Manually patch require_auth_or_error on h
        from aragora.billing.auth.context import UserAuthContext

        mock_user_ctx = MagicMock(spec=UserAuthContext)
        mock_user_ctx.authenticated = True
        h.require_auth_or_error = lambda self_handler: (mock_user_ctx, None)
        result = h.handle_post("/api/v1/debates/test/share", {}, handler)
        assert _status(result) == 200

    def test_empty_string_debate_id_via_spectate(self):
        """Path with empty debate ID segment returns 400 (missing debate ID).

        The empty string from the split is falsy, so _extract_debate_id returns
        the empty string, and the handler treats it as missing (falsy check).
        """
        h = DebateShareHandler()
        # "/api/v1/debates//spectate/public" -> parts[4] is ""
        result = h.handle("/api/v1/debates//spectate/public", {}, _make_http_handler())
        assert result is not None
        assert _status(result) == 400

    def test_multiple_handlers_share_state(self):
        """State is module-level, so multiple handler instances share it."""
        h1 = DebateShareHandler()
        h2 = DebateShareHandler()
        h1.handle_post("/api/v1/debates/shared-state/share", {}, _make_http_handler())
        result = h2.handle("/api/v1/debates/shared-state/spectate/public", {}, _make_http_handler())
        assert _status(result) == 200

    def test_max_public_spectators_constant(self):
        assert _MAX_PUBLIC_SPECTATORS == 10

    def test_spectate_after_share_and_delete(self):
        h = DebateShareHandler()
        handler = _make_http_handler()
        h.handle_post("/api/v1/debates/lifecycle/share", {}, handler)
        assert is_publicly_shared("lifecycle") is True

        h.handle_delete("/api/v1/debates/lifecycle/share", {}, handler)
        assert is_publicly_shared("lifecycle") is False

        result = h.handle("/api/v1/debates/lifecycle/spectate/public", {}, handler)
        assert _status(result) == 403

    def test_push_with_all_optional_params(self):
        debate_id = "push-all"
        set_public_spectate(debate_id, True)
        q = asyncio.Queue()
        get_public_collectors()[debate_id] = {q}

        count = push_public_spectator_event(
            debate_id,
            "detailed_event",
            agent="gemini",
            details="Detailed info here",
            metric=0.75,
            round_number=2,
        )
        assert count == 1
        event = q.get_nowait()
        assert event["type"] == "detailed_event"
        assert event["agent"] == "gemini"
        assert event["details"] == "Detailed info here"
        assert event["metric"] == 0.75
        assert event["round"] == 2

    def test_push_to_empty_collector_set(self):
        debate_id = "push-empty-set"
        set_public_spectate(debate_id, True)
        get_public_collectors()[debate_id] = set()

        count = push_public_spectator_event(debate_id, "test")
        assert count == 0

    def test_spectate_response_includes_all_fields(self):
        debate_id = "fields-test"
        set_public_spectate(debate_id, True)
        h = DebateShareHandler()
        result = h.handle(f"/api/v1/debates/{debate_id}/spectate/public", {}, _make_http_handler())
        body = _body(result)
        expected_keys = {
            "debate_id",
            "spectate_available",
            "public",
            "active_viewers",
            "max_viewers",
            "sse_url",
        }
        assert expected_keys.issubset(set(body.keys()))

    def test_share_response_includes_all_fields(self):
        h = DebateShareHandler()
        result = h.handle_post("/api/v1/debates/field-check/share", {}, _make_http_handler())
        body = _body(result)
        expected_keys = {"debate_id", "public_spectate", "share_url", "full_url"}
        assert expected_keys.issubset(set(body.keys()))

    def test_delete_response_includes_all_fields(self):
        h = DebateShareHandler()
        result = h.handle_delete("/api/v1/debates/field-check/share", {}, _make_http_handler())
        body = _body(result)
        expected_keys = {"debate_id", "public_spectate"}
        assert expected_keys.issubset(set(body.keys()))

    def test_special_chars_in_host_header(self):
        h = DebateShareHandler()
        handler = _make_http_handler(host="host:8080/path?q=1")
        result = h.handle_post("/api/v1/debates/test/share", {}, handler)
        body = _body(result)
        assert "host:8080/path?q=1" in body["full_url"]


# ===========================================================================
# __all__ exports
# ===========================================================================


class TestModuleExports:
    """Tests that module exports the expected symbols."""

    def test_all_exports(self):
        from aragora.server.handlers.debates import share

        expected = [
            "DebateShareHandler",
            "get_public_collectors",
            "get_shared_debates",
            "is_publicly_shared",
            "public_spectate_sse_generator",
            "push_public_spectator_event",
            "set_public_spectate",
        ]
        for name in expected:
            assert name in share.__all__, f"{name} missing from __all__"
            assert hasattr(share, name), f"{name} not defined in module"

    def test_max_public_spectators_accessible(self):
        from aragora.server.handlers.debates.share import _MAX_PUBLIC_SPECTATORS

        assert isinstance(_MAX_PUBLIC_SPECTATORS, int)
        assert _MAX_PUBLIC_SPECTATORS > 0
