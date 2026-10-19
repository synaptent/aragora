"""Tests for debate CRUD operations handler (crud.py).

Tests the CrudOperationsMixin covering:
- GET /api/v1/debates (list debates)
- GET /api/v1/debates/{slug} (get debate by slug)
- GET /api/v1/debates/{id}/messages (paginated messages)
- PATCH /api/v1/debates/{id} (update debate metadata)
- DELETE /api/v1/debates/{id} (delete debate)

Covers: success paths, error handling, edge cases, tenant isolation,
ABAC checks, pagination, status normalization, and storage errors.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.exceptions import DatabaseError, RecordNotFoundError, StorageError

# Reads, updates and deletes check the debate's stored org against the caller
# from extract_user_from_request: requests come from test-user-001 of test-org-001.
pytestmark = pytest.mark.usefixtures("org_scoped_request_user")


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


def _patch_active_debates(active_dict):
    """Context manager that patches _active_debates in both crud and handler modules."""
    return _MultiPatchActiveDebates(active_dict)


class _MultiPatchActiveDebates:
    """Patches _active_debates in both crud.py and handler.py modules."""

    def __init__(self, active_dict):
        self._active_dict = active_dict
        self._patches = []

    def __enter__(self):
        # Patch the crud module's _active_debates
        p1 = patch("aragora.server.handlers.debates.crud._active_debates", self._active_dict)
        p1.start()
        self._patches.append(p1)

        # Patch the handler module's _active_debates (loaded via import in crud.py)
        try:
            p2 = patch("aragora.server.handlers.debates.handler._active_debates", self._active_dict)
            p2.start()
            self._patches.append(p2)
        except (AttributeError, ImportError):
            pass

        # Also patch debate_utils._active_debates (source of the import)
        try:
            p3 = patch("aragora.server.debate_utils._active_debates", self._active_dict)
            p3.start()
            self._patches.append(p3)
        except (AttributeError, ImportError):
            pass

        return self._active_dict

    def __exit__(self, *args):
        for p in reversed(self._patches):
            p.stop()


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


class _MockDebateMetadata:
    """Mock DebateMetadata object with __dict__."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_handler(
    storage=None,
    ctx_extra: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    user=None,
):
    """Build a minimal handler instance with CrudOperationsMixin."""
    from aragora.server.handlers.base import BaseHandler
    from aragora.server.handlers.debates.crud import CrudOperationsMixin

    ctx: dict[str, Any] = {}
    if storage is not None:
        ctx["storage"] = storage
        if isinstance(storage, MagicMock) and storage.get_read_access.side_effect is None:
            # The stored row (id, org_id, is_public): a private test-org-001 debate.
            storage.get_read_access.side_effect = lambda ref: (ref, "test-org-001", False)
    if ctx_extra:
        ctx.update(ctx_extra)

    mock_user = user
    if mock_user is None:
        mock_user = MagicMock()
        mock_user.user_id = "test-user-001"
        mock_user.org_id = "test-org-001"
        mock_user.role = "admin"
        mock_user.plan = "pro"

    class _Handler(CrudOperationsMixin, BaseHandler):
        def __init__(self):
            self.ctx = ctx
            self._json_body = json_body
            self._mock_user = mock_user

        def get_storage(self):
            return ctx.get("storage")

        def read_json_body(self, handler, max_size=None):
            return self._json_body

        def get_current_user(self, handler):
            return self._mock_user

    return _Handler()


def _mock_http_handler(command="GET"):
    """Create a mock HTTP handler object."""
    h = MagicMock()
    h.command = command
    h.headers = {"Content-Length": "2"}
    h.rfile = MagicMock()
    h.rfile.read.return_value = b"{}"
    return h


# ---------------------------------------------------------------------------
# _list_debates tests
# ---------------------------------------------------------------------------


class TestListDebates:
    """Tests for GET /api/v1/debates (_list_debates)."""

    def test_list_debates_success(self):
        storage = MagicMock()
        storage.list_recent.return_value = [
            {"id": "d1", "task": "Test debate", "status": "active"},
            {"id": "d2", "task": "Another debate", "status": "concluded"},
        ]
        h = _make_handler(storage=storage)
        result = h._list_debates(limit=10)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 2
        assert len(body["debates"]) == 2

    def test_list_debates_empty(self):
        storage = MagicMock()
        storage.list_recent.return_value = []
        h = _make_handler(storage=storage)
        result = h._list_debates(limit=10)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 0
        assert body["debates"] == []

    def test_list_debates_with_org_filter(self):
        storage = MagicMock()
        storage.list_recent.return_value = [{"id": "d1", "task": "Org debate", "status": "active"}]
        h = _make_handler(storage=storage)
        result = h._list_debates(limit=5, org_id="org-123")
        assert _status(result) == 200
        storage.list_recent.assert_called_once_with(limit=5, org_id="org-123", offset=0)

    def test_list_debates_no_storage(self):
        h = _make_handler(storage=None)
        result = h._list_debates(limit=10)
        assert _status(result) == 503

    def test_list_debates_normalizes_status(self):
        storage = MagicMock()
        storage.list_recent.return_value = [
            {"id": "d1", "task": "Test", "status": "active"},
        ]
        h = _make_handler(storage=storage)
        result = h._list_debates(limit=10)
        body = _body(result)
        # "active" -> "running" via normalize_status
        assert body["debates"][0]["status"] == "running"

    def test_list_debates_with_debate_metadata_objects(self):
        storage = MagicMock()
        meta = _MockDebateMetadata(id="d1", task="Task", status="concluded")
        storage.list_recent.return_value = [meta]
        h = _make_handler(storage=storage)
        result = h._list_debates(limit=10)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 1
        # "concluded" -> "completed" via normalize_status
        assert body["debates"][0]["status"] == "completed"

    def test_list_debates_respects_limit(self):
        storage = MagicMock()
        storage.list_recent.return_value = []
        h = _make_handler(storage=storage)
        h._list_debates(limit=25)
        storage.list_recent.assert_called_once_with(limit=25, org_id=None, offset=0)

    def test_list_debates_no_org_id_default(self):
        storage = MagicMock()
        storage.list_recent.return_value = []
        h = _make_handler(storage=storage)
        h._list_debates(limit=10)
        storage.list_recent.assert_called_once_with(limit=10, org_id=None, offset=0)


# ---------------------------------------------------------------------------
# _get_debate_by_slug tests
# ---------------------------------------------------------------------------


class TestGetDebateBySlug:
    """Tests for GET /api/v1/debates/{slug} (_get_debate_by_slug)."""

    def test_get_debate_found_in_storage(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Design a rate limiter",
            "status": "concluded",
            "org_id": "test-org-001",
        }
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "d1"

    def test_get_debate_not_found(self):
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()
        with _patch_active_debates({}):
            result = h._get_debate_by_slug(handler, "nonexistent")
        assert _status(result) == 404

    def test_get_debate_no_storage(self):
        h = _make_handler(storage=None)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 503

    def test_get_debate_normalizes_status(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "org_id": "test-org-001",
        }
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        body = _body(result)
        assert body["status"] == "running"

    def test_get_debate_cross_tenant_denied(self):
        """User from org-A cannot access debate owned by org-B."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Secret debate",
            "status": "active",
            "org_id": "other-org-999",
        }
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_get_debate_cross_tenant_allowed_same_org(self):
        """User from same org can access debate."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Same org debate",
            "status": "active",
            "org_id": "test-org-001",
        }
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 200

    def test_get_debate_no_org_id_accessible(self):
        """Debate without org_id is accessible."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Public debate",
            "status": "concluded",
            "visibility": "public",
        }
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 200

    def test_get_debate_private_not_owner_denied(self):
        """Private debate without org, not owned by requesting user, is denied."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Private debate",
            "status": "active",
            "visibility": "private",
            "user_id": "other-user-999",
            "participants": [],
        }
        user = MagicMock()
        user.user_id = "test-user-001"
        user.org_id = "test-org-001"
        user.role = "user"  # Not admin
        h = _make_handler(storage=storage, user=user)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 404

    def test_get_debate_private_participant_allowed(self):
        """User who is a participant of a private debate can access it."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Private debate",
            "status": "active",
            "visibility": "private",
            "user_id": "other-user-999",
            "participants": ["test-user-001"],
        }
        user = MagicMock()
        user.user_id = "test-user-001"
        user.org_id = "test-org-001"
        user.role = "user"
        h = _make_handler(storage=storage, user=user)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 200

    def test_get_debate_private_admin_allowed(self):
        """Admin user can access any private debate."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Private debate",
            "status": "active",
            "visibility": "private",
            "user_id": "other-user-999",
            "participants": [],
        }
        user = MagicMock()
        user.user_id = "test-user-001"
        user.org_id = "test-org-001"
        user.role = "admin"
        h = _make_handler(storage=storage, user=user)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 200

    def test_get_debate_owner_allowed(self):
        """Owner of debate can access it."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "My debate",
            "status": "active",
            "visibility": "private",
            "user_id": "test-user-001",
            "participants": [],
        }
        user = MagicMock()
        user.user_id = "test-user-001"
        user.org_id = "test-org-001"
        user.role = "user"
        h = _make_handler(storage=storage, user=user)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 200

    def test_get_debate_in_progress_found(self):
        """Debate not in storage but in active_debates is returned."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        active = {
            "d-active": {
                "task": "Active debate",
                "status": "starting",
                "agents": "claude,gpt-4",
                "rounds": 3,
            }
        }
        with _patch_active_debates(active):
            result = h._get_debate_by_slug(handler, "d-active")
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "d-active"
        assert body["in_progress"] is True
        assert body["agents"] == ["claude", "gpt-4"]
        assert body["rounds"] == 3

    def test_get_debate_in_progress_agents_as_list(self):
        """Active debate with agents already as a list."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        active = {"d-active": {"task": "Active", "agents": ["claude", "gpt-4"]}}
        with _patch_active_debates(active):
            result = h._get_debate_by_slug(handler, "d-active")
        body = _body(result)
        assert body["agents"] == ["claude", "gpt-4"]

    def test_get_debate_in_progress_includes_mode_and_settlement(self):
        """In-progress payload should include mode/settlement when present on active state."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        active = {
            "d-active": {
                "task": "Active",
                "agents": ["claude", "gpt-4"],
                "mode": "epistemic_hygiene",
                "settlement": {
                    "claim": "Should we deploy?",
                    "resolver_type": "human",
                    "review_horizon_days": 14,
                },
            }
        }
        with _patch_active_debates(active):
            result = h._get_debate_by_slug(handler, "d-active")
        body = _body(result)
        assert body["mode"] == "epistemic_hygiene"
        assert body["settlement"]["claim"] == "Should we deploy?"
        assert body["settlement"]["resolver_type"] == "human"

    def test_get_debate_in_progress_uses_result_fallback_for_mode_and_settlement(self):
        """Fallback to active.result metadata when top-level fields are absent."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        active = {
            "d-active": {
                "task": "Active",
                "agents": ["claude"],
                "result": {
                    "mode": "epistemic_hygiene",
                    "settlement": {
                        "claim": "Should we switch regions?",
                        "resolver_type": "deterministic",
                    },
                },
            }
        }
        with _patch_active_debates(active):
            result = h._get_debate_by_slug(handler, "d-active")
        body = _body(result)
        assert body["mode"] == "epistemic_hygiene"
        assert body["settlement"]["claim"] == "Should we switch regions?"
        assert body["settlement"]["resolver_type"] == "deterministic"

    def test_get_debate_in_progress_reads_mode_and_settlement_from_metadata(self):
        """Proxy-backed active entries may store mode/settlement inside metadata."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        active = {
            "d-active": {
                "task": "Active",
                "agents": ["claude"],
                "metadata": {
                    "mode": "epistemic_hygiene",
                    "settlement": {
                        "claim": "Should we freeze deploys?",
                        "resolver_type": "human",
                    },
                },
            }
        }
        with _patch_active_debates(active):
            result = h._get_debate_by_slug(handler, "d-active")
        body = _body(result)
        assert body["mode"] == "epistemic_hygiene"
        assert body["settlement"]["claim"] == "Should we freeze deploys?"
        assert body["settlement"]["resolver_type"] == "human"

    def test_get_debate_in_progress_uses_question_field(self):
        """Active debate with legacy 'question' field instead of 'task'."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        active = {"d-legacy": {"question": "Legacy question", "agents": []}}
        with _patch_active_debates(active):
            result = h._get_debate_by_slug(handler, "d-legacy")
        body = _body(result)
        assert body["task"] == "Legacy question"

    def test_get_debate_in_progress_normalizes_status(self):
        """Active debate status is normalized."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        active = {"d-active": {"task": "T", "status": "starting", "agents": []}}
        with _patch_active_debates(active):
            result = h._get_debate_by_slug(handler, "d-active")
        body = _body(result)
        assert body["status"] == "created"  # "starting" -> "created"

    def test_get_debate_no_user_context(self):
        """When no user context, debate is returned without access checks."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
        }
        h = _make_handler(storage=storage, user=None)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 200

    def test_get_debate_tenant_id_field(self):
        """Cross-tenant check works with tenant_id field."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "tenant_id": "other-tenant",
        }
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 404

    def test_get_debate_workspace_id_field(self):
        """Cross-tenant check works with workspace_id field."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "workspace_id": "other-workspace",
        }
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 404

    def test_get_debate_in_progress_default_rounds(self):
        """Active debate without rounds uses DEFAULT_ROUNDS."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        from aragora.config import DEFAULT_ROUNDS

        active = {"d1": {"task": "T", "agents": []}}
        with _patch_active_debates(active):
            result = h._get_debate_by_slug(handler, "d1")
        body = _body(result)
        assert body["rounds"] == DEFAULT_ROUNDS

    def test_get_debate_superadmin_bypass_idor(self):
        """Superadmin can access any private debate."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Private debate",
            "status": "active",
            "visibility": "private",
            "user_id": "other-user",
            "participants": [],
        }
        user = MagicMock()
        user.user_id = "test-user-001"
        user.org_id = "test-org-001"
        user.role = "superadmin"
        h = _make_handler(storage=storage, user=user)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# _get_debate_messages tests
# ---------------------------------------------------------------------------


class TestGetDebateMessages:
    """Tests for GET /api/v1/debates/{id}/messages (_get_debate_messages)."""

    def test_get_messages_success(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "messages": [
                {"role": "assistant", "content": "Hello", "agent": "claude", "round": 1},
                {"role": "assistant", "content": "World", "agent": "gpt-4", "round": 1},
            ],
        }
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1", limit=50, offset=0)
        assert _status(result) == 200
        body = _body(result)
        assert body["debate_id"] == "d1"
        assert body["total"] == 2
        assert len(body["messages"]) == 2
        assert body["offset"] == 0
        assert body["limit"] == 50
        assert body["has_more"] is False

    def test_get_messages_pagination(self):
        storage = MagicMock()
        messages = [{"role": "assistant", "content": f"Message {i}", "round": 1} for i in range(10)]
        storage.get_debate.return_value = {"id": "d1", "messages": messages}
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1", limit=3, offset=2)
        body = _body(result)
        assert body["total"] == 10
        assert len(body["messages"]) == 3
        assert body["offset"] == 2
        assert body["limit"] == 3
        assert body["has_more"] is True
        # Check indices are correct
        assert body["messages"][0]["index"] == 2
        assert body["messages"][1]["index"] == 3
        assert body["messages"][2]["index"] == 4

    def test_get_messages_pagination_last_page(self):
        storage = MagicMock()
        messages = [{"role": "assistant", "content": f"M{i}", "round": 1} for i in range(5)]
        storage.get_debate.return_value = {"id": "d1", "messages": messages}
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1", limit=3, offset=3)
        body = _body(result)
        assert len(body["messages"]) == 2
        assert body["has_more"] is False

    def test_get_messages_debate_not_found(self):
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("nonexistent")
        assert _status(result) == 404

    def test_get_messages_no_storage(self):
        h = _make_handler(storage=None)
        result = h._get_debate_messages("d1")
        assert _status(result) == 503

    def test_get_messages_empty_messages(self):
        storage = MagicMock()
        storage.get_debate.return_value = {"id": "d1", "messages": []}
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1")
        body = _body(result)
        assert body["total"] == 0
        assert body["messages"] == []
        assert body["has_more"] is False

    def test_get_messages_no_messages_key(self):
        storage = MagicMock()
        storage.get_debate.return_value = {"id": "d1"}
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1")
        body = _body(result)
        assert body["total"] == 0
        assert body["messages"] == []

    def test_get_messages_limit_clamped_min(self):
        """Limit below 1 is clamped to 1."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "messages": [{"role": "assistant", "content": "Hi", "round": 1}],
        }
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1", limit=0, offset=0)
        body = _body(result)
        assert body["limit"] == 1

    def test_get_messages_limit_clamped_max(self):
        """Limit above 200 is clamped to 200."""
        storage = MagicMock()
        storage.get_debate.return_value = {"id": "d1", "messages": []}
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1", limit=500, offset=0)
        body = _body(result)
        assert body["limit"] == 200

    def test_get_messages_negative_offset_clamped(self):
        """Negative offset is clamped to 0."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "messages": [{"role": "assistant", "content": "Hi", "round": 1}],
        }
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1", limit=10, offset=-5)
        body = _body(result)
        assert body["offset"] == 0

    def test_get_messages_includes_optional_fields(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "messages": [
                {
                    "role": "assistant",
                    "content": "Hello",
                    "agent": "claude",
                    "round": 1,
                    "timestamp": "2026-01-01T00:00:00Z",
                    "metadata": {"confidence": 0.95},
                },
            ],
        }
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1")
        body = _body(result)
        msg = body["messages"][0]
        assert msg["timestamp"] == "2026-01-01T00:00:00Z"
        assert msg["metadata"]["confidence"] == 0.95

    def test_get_messages_name_fallback_for_agent(self):
        """Falls back to 'name' if 'agent' not present in message."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "messages": [
                {"role": "assistant", "content": "Hi", "name": "gemini", "round": 1},
            ],
        }
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1")
        body = _body(result)
        assert body["messages"][0]["agent"] == "gemini"

    def test_get_messages_record_not_found_error(self):
        storage = MagicMock()
        storage.get_debate.side_effect = RecordNotFoundError("debates", "d1")
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1")
        assert _status(result) == 404

    def test_get_messages_storage_error(self):
        storage = MagicMock()
        storage.get_debate.side_effect = StorageError("DB down")
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1")
        assert _status(result) == 500

    def test_get_messages_database_error(self):
        storage = MagicMock()
        storage.get_debate.side_effect = DatabaseError("Connection failed")
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1")
        assert _status(result) == 500

    def test_get_messages_default_values(self):
        """Messages without optional fields use defaults."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "messages": [{}],
        }
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1")
        body = _body(result)
        msg = body["messages"][0]
        assert msg["role"] == "unknown"
        assert msg["content"] == ""
        assert msg["agent"] is None
        assert msg["round"] == 0

    def test_get_messages_offset_beyond_total(self):
        """Offset beyond total messages returns empty list."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "messages": [{"role": "a", "content": "Hi", "round": 1}],
        }
        h = _make_handler(storage=storage)
        result = h._get_debate_messages("d1", limit=10, offset=100)
        body = _body(result)
        assert body["messages"] == []
        assert body["total"] == 1
        assert body["has_more"] is False


# ---------------------------------------------------------------------------
# _patch_debate tests
# ---------------------------------------------------------------------------


class TestPatchDebate:
    """Tests for PATCH /api/v1/debates/{id} (_patch_debate)."""

    def test_update_title(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Original",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"title": "New Title"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._patch_debate(handler, "d1")

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["debate_id"] == "d1"
        assert "title" in body["updated_fields"]
        assert body["debate"]["title"] == "New Title"

    def test_update_tags(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"tags": ["ai", "safety"]})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True
        assert body["debate"]["tags"] == ["ai", "safety"]

    def test_update_status_internal(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"status": "concluded"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True
        # Status is normalized for response: "concluded" -> "completed"
        assert body["debate"]["status"] == "completed"

    def test_update_status_sdk_value_with_schema_bypass(self):
        """SDK status values (e.g., 'running') are accepted when schema allows them."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "concluded",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"status": "running"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            # Bypass schema validation to test the code-level SDK status handling
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True

    def test_update_invalid_status_rejected_by_schema(self):
        """Invalid status is rejected by schema validation."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"status": "invalid_status"})
        handler = _mock_http_handler("PATCH")
        result = h._patch_debate(handler, "d1")
        assert _status(result) == 400

    def test_update_invalid_status_via_code_check(self):
        """Invalid status not in SDK or internal set is rejected by the code."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"status": "bogus"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                result = h._patch_debate(handler, "d1")

        assert _status(result) == 400
        assert "invalid status" in _body(result).get("error", "").lower()

    def test_update_metadata(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"metadata": {"key": "value"}})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True
        assert "metadata" in body["updated_fields"]

    def test_update_no_json_body(self):
        storage = MagicMock()
        h = _make_handler(storage=storage, json_body=None)
        handler = _mock_http_handler("PATCH")
        result = h._patch_debate(handler, "d1")
        assert _status(result) == 400
        error_msg = _body(result).get("error", "").lower()
        assert "invalid" in error_msg or "missing" in error_msg

    def test_update_empty_body(self):
        storage = MagicMock()
        h = _make_handler(storage=storage, json_body={})
        handler = _mock_http_handler("PATCH")
        result = h._patch_debate(handler, "d1")
        assert _status(result) == 400

    def test_update_debate_not_found(self):
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage, json_body={"title": "New"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.validate_against_schema") as mock_validate:
            mock_validate.return_value = MagicMock(is_valid=True)
            result = h._patch_debate(handler, "nonexistent")

        assert _status(result) == 404

    def test_update_no_storage(self):
        h = _make_handler(storage=None, json_body={"title": "New"})
        handler = _mock_http_handler("PATCH")
        result = h._patch_debate(handler, "d1")
        assert _status(result) == 503

    def test_update_abac_denied(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "other-user",
        }
        h = _make_handler(storage=storage, json_body={"title": "Hacked"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=False, reason="Not owner")
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                result = h._patch_debate(handler, "d1")

        assert _status(result) == 403

    def test_update_only_allowed_fields(self):
        """Fields not in allowed set are filtered out."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"unknown_field": "value"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                result = h._patch_debate(handler, "d1")

        assert _status(result) == 400
        assert "no valid fields" in _body(result).get("error", "").lower()

    def test_update_saves_to_storage(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        storage.save_debate = MagicMock()
        h = _make_handler(storage=storage, json_body={"title": "Updated"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._patch_debate(handler, "d1")

        assert _status(result) == 200
        storage.save_debate.assert_called_once()

    def test_update_record_not_found_error(self):
        storage = MagicMock()
        storage.get_debate.side_effect = RecordNotFoundError("debates", "d1")
        h = _make_handler(storage=storage, json_body={"title": "X"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.validate_against_schema") as mock_validate:
            mock_validate.return_value = MagicMock(is_valid=True)
            result = h._patch_debate(handler, "d1")

        assert _status(result) == 404

    def test_update_storage_error(self):
        storage = MagicMock()
        storage.get_debate.side_effect = StorageError("DB failed")
        h = _make_handler(storage=storage, json_body={"title": "X"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.validate_against_schema") as mock_validate:
            mock_validate.return_value = MagicMock(is_valid=True)
            result = h._patch_debate(handler, "d1")

        assert _status(result) == 500

    def test_update_database_error(self):
        storage = MagicMock()
        storage.get_debate.side_effect = DatabaseError("Connection reset")
        h = _make_handler(storage=storage, json_body={"title": "X"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.validate_against_schema") as mock_validate:
            mock_validate.return_value = MagicMock(is_valid=True)
            result = h._patch_debate(handler, "d1")

        assert _status(result) == 500

    def test_update_value_error(self):
        storage = MagicMock()
        storage.get_debate.side_effect = ValueError("Bad data")
        h = _make_handler(storage=storage, json_body={"title": "X"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.validate_against_schema") as mock_validate:
            mock_validate.return_value = MagicMock(is_valid=True)
            result = h._patch_debate(handler, "d1")

        assert _status(result) == 400

    def test_update_schema_validation_failure(self):
        storage = MagicMock()
        h = _make_handler(storage=storage, json_body={"title": "X"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.validate_against_schema") as mock_validate:
            mock_validate.return_value = MagicMock(is_valid=False, error="Title too long")
            result = h._patch_debate(handler, "d1")

        assert _status(result) == 400
        assert "Title too long" in _body(result).get("error", "")

    def test_update_multiple_fields(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(
            storage=storage,
            json_body={"title": "New", "tags": ["a"], "status": "paused"},
        )
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True
        assert set(body["updated_fields"]) == {"title", "tags", "status"}

    def test_update_no_user_context(self):
        """When no user context, ABAC check is skipped."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
        }
        h = _make_handler(storage=storage, json_body={"title": "Updated"}, user=None)
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.validate_against_schema") as mock_validate:
            mock_validate.return_value = MagicMock(is_valid=True)
            result = h._patch_debate(handler, "d1")

        assert _status(result) == 200

    def test_update_storage_without_save_debate(self):
        """Storage without save_debate method doesn't crash."""
        storage = MagicMock(spec=["get_debate", "get_read_access"])
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        # Remove save_debate from spec
        del storage.save_debate
        h = _make_handler(storage=storage, json_body={"title": "Updated"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._patch_debate(handler, "d1")

        assert _status(result) == 200

    def test_update_status_paused(self):
        """'paused' is a valid internal status."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"status": "paused"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True
        assert body["debate"]["status"] == "paused"

    def test_update_status_archived(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"status": "archived"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True
        # "archived" -> "completed" via normalize_status for response
        assert body["debate"]["status"] == "completed"

    def test_update_sdk_status_completed_via_bypass(self):
        """SDK status 'completed' is denormalized to 'concluded' when schema is bypassed."""
        storage = MagicMock()
        debate_data = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        storage.get_debate.return_value = debate_data
        h = _make_handler(storage=storage, json_body={"status": "completed"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True
        # Stored as "concluded", returned as "completed" via normalize
        assert body["debate"]["status"] == "completed"

    def test_update_sdk_status_pending_via_bypass(self):
        """SDK status 'pending' is converted to 'active' when schema is bypassed."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "concluded",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"status": "pending"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True

    def test_update_sdk_status_cancelled_via_bypass(self):
        """SDK status 'cancelled' is accepted when schema is bypassed."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"status": "cancelled"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True

    def test_update_sdk_status_failed_via_bypass(self):
        """SDK status 'failed' is accepted when schema is bypassed."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"status": "failed"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["success"] is True

    def test_update_response_title_fallback(self):
        """Response title falls back to task field if no title."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Original Task",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"tags": ["test"]})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._patch_debate(handler, "d1")

        body = _body(result)
        assert body["debate"]["title"] == "Original Task"

    def test_update_schema_rejects_sdk_status_directly(self):
        """SDK status values are rejected by the real schema validation."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        # Use "running" which is an SDK status not in schema allowed_values
        h = _make_handler(storage=storage, json_body={"status": "running"})
        handler = _mock_http_handler("PATCH")
        # Let real schema validation run
        result = h._patch_debate(handler, "d1")
        assert _status(result) == 400


# ---------------------------------------------------------------------------
# _delete_debate tests
# ---------------------------------------------------------------------------


class TestDeleteDebate:
    """Tests for DELETE /api/v1/debates/{id} (_delete_debate)."""

    def test_delete_success(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "concluded",
            "user_id": "test-user-001",
        }
        storage.delete_debate.return_value = True
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._delete_debate(handler, "d1")

        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["id"] == "d1"

    def test_delete_debate_not_found(self):
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")
        result = h._delete_debate(handler, "nonexistent")
        assert _status(result) == 404

    def test_delete_no_storage(self):
        h = _make_handler(storage=None)
        handler = _mock_http_handler("DELETE")
        result = h._delete_debate(handler, "d1")
        assert _status(result) == 503

    def test_delete_abac_denied(self):
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "concluded",
            "user_id": "other-user",
        }
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=False, reason="Not authorized")
            result = h._delete_debate(handler, "d1")

        assert _status(result) == 403

    def test_delete_cascade_critiques(self):
        """Delete passes cascade_critiques=True to storage."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "user_id": "test-user-001",
        }
        storage.delete_debate.return_value = True
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            h._delete_debate(handler, "d1")

        storage.delete_debate.assert_called_once_with("d1", cascade_critiques=True)

    def test_delete_not_found_from_storage_delete(self):
        """When storage.delete_debate returns False (not found), return 404."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "user_id": "test-user-001",
        }
        storage.delete_debate.return_value = False
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._delete_debate(handler, "d1")

        assert _status(result) == 404

    def test_delete_record_not_found_error(self):
        storage = MagicMock()
        storage.get_debate.side_effect = RecordNotFoundError("debates", "d1")
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")
        result = h._delete_debate(handler, "d1")
        assert _status(result) == 404

    def test_delete_storage_error(self):
        storage = MagicMock()
        storage.get_debate.side_effect = StorageError("DB crashed")
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")
        result = h._delete_debate(handler, "d1")
        assert _status(result) == 500

    def test_delete_database_error(self):
        storage = MagicMock()
        storage.get_debate.side_effect = DatabaseError("Connection lost")
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")
        result = h._delete_debate(handler, "d1")
        assert _status(result) == 500

    def test_delete_cancels_active_debate(self):
        """If debate is in _active_debates with a running task, cancel it."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "user_id": "test-user-001",
        }
        storage.delete_debate.return_value = True

        mock_task = MagicMock()
        mock_task.done.return_value = False
        active_entry = MagicMock()
        active_entry.task = mock_task
        active_debates = {"d1": active_entry}

        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")

        with patch("aragora.server.handlers.debates.crud._active_debates", active_debates):
            with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
                mock_access.return_value = MagicMock(allowed=True)
                result = h._delete_debate(handler, "d1")

        assert _status(result) == 200
        mock_task.cancel.assert_called_once()
        assert "d1" not in active_debates

    def test_delete_active_debate_already_done(self):
        """If active debate task is already done, don't cancel."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "user_id": "test-user-001",
        }
        storage.delete_debate.return_value = True

        mock_task = MagicMock()
        mock_task.done.return_value = True
        active_entry = MagicMock()
        active_entry.task = mock_task
        active_debates = {"d1": active_entry}

        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")

        with patch("aragora.server.handlers.debates.crud._active_debates", active_debates):
            with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
                mock_access.return_value = MagicMock(allowed=True)
                result = h._delete_debate(handler, "d1")

        assert _status(result) == 200
        mock_task.cancel.assert_not_called()

    def test_delete_no_user_context(self):
        """When no user context, ABAC check is skipped."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
        }
        storage.delete_debate.return_value = True
        h = _make_handler(storage=storage, user=None)
        handler = _mock_http_handler("DELETE")
        result = h._delete_debate(handler, "d1")
        assert _status(result) == 200

    def test_delete_uses_owner_id_field(self):
        """ABAC check works with owner_id field."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "owner_id": "test-user-001",
        }
        storage.delete_debate.return_value = True
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            result = h._delete_debate(handler, "d1")

        assert _status(result) == 200
        # Verify owner_id was passed to ABAC
        call_kwargs = mock_access.call_args
        assert call_kwargs.kwargs.get("resource_owner_id") == "test-user-001"

    def test_delete_active_debate_no_task_attribute(self):
        """Active debate entry without task attribute is handled."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "user_id": "test-user-001",
        }
        storage.delete_debate.return_value = True

        # Entry with no 'task' attribute (bare dict-like)
        active_entry = {"status": "running"}
        active_debates = {"d1": active_entry}

        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")

        with patch("aragora.server.handlers.debates.crud._active_debates", active_debates):
            with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
                mock_access.return_value = MagicMock(allowed=True)
                result = h._delete_debate(handler, "d1")

        assert _status(result) == 200
        assert "d1" not in active_debates

    def test_delete_uses_stored_org_for_abac(self):
        """ABAC check gets the stored org column, not the artifact's workspace_id."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "user_id": "test-user-001",
            "workspace_id": "ws-001",
        }
        storage.delete_debate.return_value = True
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            h._delete_debate(handler, "d1")

        call_kwargs = mock_access.call_args
        assert call_kwargs.kwargs.get("resource_workspace_id") == "test-org-001"


# ---------------------------------------------------------------------------
# Edge cases and cross-cutting concerns
# ---------------------------------------------------------------------------


class TestCrudEdgeCases:
    """Edge cases for CRUD operations."""

    def test_list_debates_debate_dict_like_objects(self):
        """Handles debate objects that support dict() conversion."""
        storage = MagicMock()

        class DictLike:
            def __init__(self):
                self._data = {"id": "d1", "status": "active"}

            def __iter__(self):
                return iter(self._data.items())

            def keys(self):
                return self._data.keys()

            def __getitem__(self, key):
                return self._data[key]

        storage.list_recent.return_value = [DictLike()]
        h = _make_handler(storage=storage)
        result = h._list_debates(limit=10)
        assert _status(result) == 200

    def test_get_debate_handler_module_fallback(self):
        """When handler module has _active_debates, it's used for lookup."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        active = {"d1": {"task": "T", "agents": []}}
        with _patch_active_debates(active):
            result = h._get_debate_by_slug(handler, "d1")
        assert _status(result) == 200

    def test_list_debates_concluded_status_normalized(self):
        """Concluded status is normalized to completed in list."""
        storage = MagicMock()
        storage.list_recent.return_value = [{"id": "d1", "status": "concluded", "task": "T"}]
        h = _make_handler(storage=storage)
        result = h._list_debates(limit=10)
        body = _body(result)
        assert body["debates"][0]["status"] == "completed"

    def test_list_debates_archived_status_normalized(self):
        """Archived status is normalized to completed in list."""
        storage = MagicMock()
        storage.list_recent.return_value = [{"id": "d1", "status": "archived", "task": "T"}]
        h = _make_handler(storage=storage)
        result = h._list_debates(limit=10)
        body = _body(result)
        assert body["debates"][0]["status"] == "completed"

    def test_get_debate_in_progress_empty_agents_string(self):
        """Active debate with empty agents string produces empty list after split."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        active = {"d1": {"task": "T", "agents": "", "status": "starting"}}
        with _patch_active_debates(active):
            result = h._get_debate_by_slug(handler, "d1")
        body = _body(result)
        # "".split(",") produces [""]
        assert body["agents"] == [""]

    def test_patch_debate_abac_uses_correct_action(self):
        """Verify ABAC check uses WRITE action for patch."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"title": "X"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                h._patch_debate(handler, "d1")

        from aragora.server.middleware.abac import Action

        call_kwargs = mock_access.call_args
        assert call_kwargs.kwargs.get("action") == Action.WRITE

    def test_delete_debate_abac_uses_correct_action(self):
        """Verify ABAC check uses DELETE action for delete."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "user_id": "test-user-001",
        }
        storage.delete_debate.return_value = True
        h = _make_handler(storage=storage)
        handler = _mock_http_handler("DELETE")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            h._delete_debate(handler, "d1")

        from aragora.server.middleware.abac import Action

        call_kwargs = mock_access.call_args
        assert call_kwargs.kwargs.get("action") == Action.DELETE

    def test_patch_debate_abac_uses_debate_resource_type(self):
        """Verify ABAC check uses DEBATE resource type."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "test-user-001",
        }
        h = _make_handler(storage=storage, json_body={"title": "X"})
        handler = _mock_http_handler("PATCH")

        with patch("aragora.server.handlers.debates.crud.check_resource_access") as mock_access:
            mock_access.return_value = MagicMock(allowed=True)
            with patch(
                "aragora.server.handlers.debates.crud.validate_against_schema"
            ) as mock_validate:
                mock_validate.return_value = MagicMock(is_valid=True)
                h._patch_debate(handler, "d1")

        from aragora.server.middleware.abac import ResourceType

        call_kwargs = mock_access.call_args
        assert call_kwargs.kwargs.get("resource_type") == ResourceType.DEBATE

    def test_get_debate_no_visibility_field(self):
        """Debate without visibility field defaults to private behavior."""
        storage = MagicMock()
        storage.get_debate.return_value = {
            "id": "d1",
            "task": "Test",
            "status": "active",
            "user_id": "other-user",
            # No visibility field - defaults to "private"
            "participants": [],
        }
        user = MagicMock()
        user.user_id = "test-user-001"
        user.org_id = "test-org-001"
        user.role = "user"
        h = _make_handler(storage=storage, user=user)
        handler = _mock_http_handler()
        result = h._get_debate_by_slug(handler, "d1")
        # visibility defaults to "private", so IDOR check applies
        assert _status(result) == 404

    def test_list_debates_single_debate(self):
        """List with a single debate returns correct count."""
        storage = MagicMock()
        storage.list_recent.return_value = [{"id": "d1", "status": "active"}]
        h = _make_handler(storage=storage)
        result = h._list_debates(limit=1)
        body = _body(result)
        assert body["count"] == 1
