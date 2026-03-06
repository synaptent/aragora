"""Tests for shared inbox handler functions.

Covers all 8 handler functions in inbox_handlers.py:
- handle_create_shared_inbox
- handle_list_shared_inboxes
- handle_get_shared_inbox
- handle_get_inbox_messages
- handle_assign_message
- handle_update_message_status
- handle_add_message_tag
- handle_add_message_to_inbox

Tests exercise success paths, error paths, in-memory fallback, store interactions,
activity logging, filtering, pagination, and edge cases.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.shared_inbox.inbox_handlers import (
    handle_add_message_tag,
    handle_add_message_to_inbox,
    handle_assign_message,
    handle_create_shared_inbox,
    handle_get_inbox_messages,
    handle_get_shared_inbox,
    handle_list_shared_inboxes,
    handle_update_message_status,
)
from aragora.server.handlers.shared_inbox.models import (
    MessageStatus,
    SharedInbox,
    SharedInboxMessage,
)
from aragora.server.handlers.shared_inbox.storage import (
    _inbox_messages,
    _shared_inboxes,
    _storage_lock,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: dict) -> dict:
    """Extract the body dict from a handler result."""
    return result


def _make_inbox(
    inbox_id: str = "inbox_test123",
    workspace_id: str = "ws_1",
    name: str = "Test Inbox",
    team_members: list[str] | None = None,
    admins: list[str] | None = None,
) -> SharedInbox:
    now = datetime.now(timezone.utc)
    return SharedInbox(
        id=inbox_id,
        workspace_id=workspace_id,
        name=name,
        team_members=team_members or [],
        admins=admins or [],
        created_at=now,
        updated_at=now,
    )


def _make_message(
    message_id: str = "msg_test123",
    inbox_id: str = "inbox_test123",
    status: MessageStatus = MessageStatus.OPEN,
    assigned_to: str | None = None,
    tags: list[str] | None = None,
    received_at: datetime | None = None,
    priority: str | None = None,
    thread_id: str | None = None,
) -> SharedInboxMessage:
    return SharedInboxMessage(
        id=message_id,
        inbox_id=inbox_id,
        email_id=f"email_{message_id}",
        subject=f"Subject for {message_id}",
        from_address="sender@example.com",
        to_addresses=["inbox@company.com"],
        snippet="Preview text",
        received_at=received_at or datetime.now(timezone.utc),
        status=status,
        assigned_to=assigned_to,
        tags=tags or [],
        priority=priority,
        thread_id=thread_id,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_in_memory_storage():
    """Clear shared in-memory dicts before/after each test."""
    with _storage_lock:
        _shared_inboxes.clear()
        _inbox_messages.clear()
    yield
    with _storage_lock:
        _shared_inboxes.clear()
        _inbox_messages.clear()


@pytest.fixture
def mock_store():
    """Return a MagicMock with common store methods."""
    store = MagicMock()
    store.get_inbox_messages = MagicMock(return_value=None)
    store.list_inbox_messages = MagicMock(return_value=None)
    store.update_message = MagicMock()
    store.update_message_status = MagicMock()
    store.create_shared_inbox = MagicMock()
    store.get_shared_inbox = MagicMock(return_value=None)
    store.list_shared_inboxes = MagicMock(return_value=None)
    store.save_message = MagicMock()
    return store


@pytest.fixture
def patch_store_none():
    """Patch _get_store to return None (no persistent store)."""
    with patch(
        "aragora.server.handlers.shared_inbox.inbox_handlers._get_store",
        return_value=None,
    ):
        yield


@pytest.fixture
def patch_store(mock_store):
    """Patch _get_store to return mock_store."""
    with patch(
        "aragora.server.handlers.shared_inbox.inbox_handlers._get_store",
        return_value=mock_store,
    ):
        yield mock_store


@pytest.fixture
def patch_log_activity():
    """Patch _log_activity to a MagicMock."""
    mock_log = MagicMock()
    with patch(
        "aragora.server.handlers.shared_inbox.inbox_handlers._log_activity",
        mock_log,
    ):
        yield mock_log


# ===========================================================================
# handle_create_shared_inbox
# ===========================================================================


class TestCreateSharedInbox:
    """Tests for handle_create_shared_inbox."""

    @pytest.mark.asyncio
    async def test_create_basic_inbox(self, patch_store_none):
        result = await handle_create_shared_inbox(
            workspace_id="ws_1",
            name="Support",
        )
        assert result["success"] is True
        inbox = result["inbox"]
        assert inbox["workspace_id"] == "ws_1"
        assert inbox["name"] == "Support"
        assert inbox["id"].startswith("inbox_")

    @pytest.mark.asyncio
    async def test_create_inbox_with_all_fields(self, patch_store_none):
        result = await handle_create_shared_inbox(
            workspace_id="ws_2",
            name="Sales",
            description="Sales emails",
            email_address="sales@co.com",
            connector_type="gmail",
            team_members=["u1", "u2"],
            admins=["a1"],
            settings={"auto_assign": True},
            created_by="admin1",
        )
        assert result["success"] is True
        inbox = result["inbox"]
        assert inbox["description"] == "Sales emails"
        assert inbox["email_address"] == "sales@co.com"
        assert inbox["connector_type"] == "gmail"
        assert inbox["team_members"] == ["u1", "u2"]
        assert inbox["admins"] == ["a1"]
        assert inbox["settings"] == {"auto_assign": True}
        assert inbox["created_by"] == "admin1"

    @pytest.mark.asyncio
    async def test_create_inbox_stored_in_memory(self, patch_store_none):
        result = await handle_create_shared_inbox(
            workspace_id="ws_1",
            name="Test",
        )
        inbox_id = result["inbox"]["id"]
        with _storage_lock:
            assert inbox_id in _shared_inboxes
            assert inbox_id in _inbox_messages
            assert _inbox_messages[inbox_id] == {}

    @pytest.mark.asyncio
    async def test_create_inbox_persists_to_store(self, patch_store):
        store = patch_store
        result = await handle_create_shared_inbox(
            workspace_id="ws_1",
            name="Persisted",
        )
        assert result["success"] is True
        store.create_shared_inbox.assert_called_once()
        call_kwargs = store.create_shared_inbox.call_args
        assert call_kwargs[1]["workspace_id"] == "ws_1"
        assert call_kwargs[1]["name"] == "Persisted"

    @pytest.mark.asyncio
    async def test_create_inbox_store_type_error_fallback(self, mock_store):
        """When first store call raises TypeError, tries simplified call."""
        call_count = {"n": 0}
        original_side_effect = None

        def side_effect_fn(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TypeError("unexpected kwarg")
            # Second call succeeds

        mock_store.create_shared_inbox.side_effect = side_effect_fn
        with patch(
            "aragora.server.handlers.shared_inbox.inbox_handlers._get_store",
            return_value=mock_store,
        ):
            result = await handle_create_shared_inbox(
                workspace_id="ws_1",
                name="Fallback",
                connector_type="outlook",
            )
        assert result["success"] is True
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_create_inbox_store_os_error_handled(self, mock_store):
        """Store OSError is caught gracefully."""
        mock_store.create_shared_inbox.side_effect = OSError("disk full")
        with patch(
            "aragora.server.handlers.shared_inbox.inbox_handlers._get_store",
            return_value=mock_store,
        ):
            result = await handle_create_shared_inbox(
                workspace_id="ws_1",
                name="Still works",
            )
        # Still succeeds because in-memory storage works
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_inbox_defaults(self, patch_store_none):
        result = await handle_create_shared_inbox(
            workspace_id="ws_1",
            name="Defaults",
        )
        inbox = result["inbox"]
        assert inbox["team_members"] == []
        assert inbox["admins"] == []
        assert inbox["settings"] == {}
        assert inbox["description"] is None
        assert inbox["email_address"] is None

    @pytest.mark.asyncio
    async def test_create_inbox_timestamps_set(self, patch_store_none):
        result = await handle_create_shared_inbox(
            workspace_id="ws_1",
            name="Timestamped",
        )
        inbox = result["inbox"]
        # Both timestamps should be set and parseable
        assert inbox["created_at"] is not None
        assert inbox["updated_at"] is not None
        dt = datetime.fromisoformat(inbox["created_at"])
        assert dt.year >= 2026


# ===========================================================================
# handle_list_shared_inboxes
# ===========================================================================


class TestListSharedInboxes:
    """Tests for handle_list_shared_inboxes."""

    @pytest.mark.asyncio
    async def test_list_empty(self, patch_store_none):
        result = await handle_list_shared_inboxes(workspace_id="ws_1")
        assert result["success"] is True
        assert result["inboxes"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_list_returns_matching_workspace(self, patch_store_none):
        inbox1 = _make_inbox(inbox_id="i1", workspace_id="ws_1", name="Inbox 1")
        inbox2 = _make_inbox(inbox_id="i2", workspace_id="ws_2", name="Inbox 2")
        with _storage_lock:
            _shared_inboxes["i1"] = inbox1
            _shared_inboxes["i2"] = inbox2

        result = await handle_list_shared_inboxes(workspace_id="ws_1")
        assert result["success"] is True
        assert result["total"] == 1
        assert result["inboxes"][0]["id"] == "i1"

    @pytest.mark.asyncio
    async def test_list_filters_by_user_team_member(self, patch_store_none):
        inbox = _make_inbox(
            inbox_id="i1",
            workspace_id="ws_1",
            team_members=["user_a"],
        )
        with _storage_lock:
            _shared_inboxes["i1"] = inbox

        result = await handle_list_shared_inboxes(workspace_id="ws_1", user_id="user_a")
        assert result["total"] == 1

        result = await handle_list_shared_inboxes(workspace_id="ws_1", user_id="user_b")
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_list_filters_by_user_admin(self, patch_store_none):
        inbox = _make_inbox(
            inbox_id="i1",
            workspace_id="ws_1",
            admins=["admin_a"],
        )
        with _storage_lock:
            _shared_inboxes["i1"] = inbox

        result = await handle_list_shared_inboxes(workspace_id="ws_1", user_id="admin_a")
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_list_no_user_filter_returns_all(self, patch_store_none):
        """When user_id is None, return all inboxes in workspace."""
        inbox1 = _make_inbox(inbox_id="i1", workspace_id="ws_1", team_members=["u1"])
        inbox2 = _make_inbox(inbox_id="i2", workspace_id="ws_1", team_members=["u2"])
        with _storage_lock:
            _shared_inboxes["i1"] = inbox1
            _shared_inboxes["i2"] = inbox2

        result = await handle_list_shared_inboxes(workspace_id="ws_1")
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_list_uses_store_when_available(self, patch_store):
        store = patch_store
        store.list_shared_inboxes.return_value = [{"id": "si1", "name": "Store Inbox"}]
        result = await handle_list_shared_inboxes(workspace_id="ws_1")
        assert result["success"] is True
        assert result["total"] == 1
        assert result["inboxes"][0]["id"] == "si1"

    @pytest.mark.asyncio
    async def test_list_store_error_returns_failure(self, patch_store):
        store = patch_store
        store.list_shared_inboxes.side_effect = OSError("store down")
        inbox = _make_inbox(inbox_id="i1", workspace_id="ws_1")
        with _storage_lock:
            _shared_inboxes["i1"] = inbox

        result = await handle_list_shared_inboxes(workspace_id="ws_1")
        assert result["success"] is False
        assert "storage" in result["error"].lower() or "failed" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_list_store_empty_falls_back_to_memory(self, patch_store):
        store = patch_store
        store.list_shared_inboxes.return_value = []
        # Empty list from store is falsy, so falls through to in-memory
        inbox = _make_inbox(inbox_id="i1", workspace_id="ws_1")
        with _storage_lock:
            _shared_inboxes["i1"] = inbox

        result = await handle_list_shared_inboxes(workspace_id="ws_1")
        assert result["success"] is True
        # Falls through because `if stored_inboxes:` is falsy for []
        assert result["total"] == 1


# ===========================================================================
# handle_get_shared_inbox
# ===========================================================================


class TestGetSharedInbox:
    """Tests for handle_get_shared_inbox."""

    @pytest.mark.asyncio
    async def test_get_inbox_not_found(self, patch_store_none):
        result = await handle_get_shared_inbox(inbox_id="nonexistent")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_inbox_from_memory(self, patch_store_none):
        inbox = _make_inbox(inbox_id="i1", name="MyInbox")
        with _storage_lock:
            _shared_inboxes["i1"] = inbox
            _inbox_messages["i1"] = {}

        result = await handle_get_shared_inbox(inbox_id="i1")
        assert result["success"] is True
        assert result["inbox"]["name"] == "MyInbox"

    @pytest.mark.asyncio
    async def test_get_inbox_updates_counts(self, patch_store_none):
        inbox = _make_inbox(inbox_id="i1")
        msg_open = _make_message(message_id="m1", inbox_id="i1", status=MessageStatus.OPEN)
        msg_assigned = _make_message(message_id="m2", inbox_id="i1", status=MessageStatus.ASSIGNED)
        msg_resolved = _make_message(message_id="m3", inbox_id="i1", status=MessageStatus.RESOLVED)
        with _storage_lock:
            _shared_inboxes["i1"] = inbox
            _inbox_messages["i1"] = {"m1": msg_open, "m2": msg_assigned, "m3": msg_resolved}

        result = await handle_get_shared_inbox(inbox_id="i1")
        assert result["success"] is True
        assert result["inbox"]["message_count"] == 3
        assert result["inbox"]["unread_count"] == 1  # Only OPEN counts as unread

    @pytest.mark.asyncio
    async def test_get_inbox_from_store(self, patch_store):
        store = patch_store
        store.get_shared_inbox.return_value = {"id": "i1", "name": "Store Inbox"}
        result = await handle_get_shared_inbox(inbox_id="i1")
        assert result["success"] is True
        assert result["inbox"]["name"] == "Store Inbox"

    @pytest.mark.asyncio
    async def test_get_inbox_store_error_falls_back(self, patch_store):
        store = patch_store
        store.get_shared_inbox.side_effect = RuntimeError("boom")
        inbox = _make_inbox(inbox_id="i1", name="Cached")
        with _storage_lock:
            _shared_inboxes["i1"] = inbox
            _inbox_messages["i1"] = {}

        result = await handle_get_shared_inbox(inbox_id="i1")
        assert result["success"] is True
        assert result["inbox"]["name"] == "Cached"

    @pytest.mark.asyncio
    async def test_get_inbox_store_returns_none_falls_back(self, patch_store):
        store = patch_store
        store.get_shared_inbox.return_value = None
        inbox = _make_inbox(inbox_id="i1", name="Fallback")
        with _storage_lock:
            _shared_inboxes["i1"] = inbox
            _inbox_messages["i1"] = {}

        result = await handle_get_shared_inbox(inbox_id="i1")
        assert result["success"] is True
        assert result["inbox"]["name"] == "Fallback"


# ===========================================================================
# handle_get_inbox_messages
# ===========================================================================


class TestGetInboxMessages:
    """Tests for handle_get_inbox_messages."""

    @pytest.mark.asyncio
    async def test_get_messages_inbox_not_found(self, patch_store_none):
        result = await handle_get_inbox_messages(inbox_id="nonexistent")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_messages_empty_inbox(self, patch_store_none):
        with _storage_lock:
            _inbox_messages["i1"] = {}

        result = await handle_get_inbox_messages(inbox_id="i1")
        assert result["success"] is True
        assert result["messages"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_get_messages_returns_all(self, patch_store_none):
        m1 = _make_message(message_id="m1", inbox_id="i1")
        m2 = _make_message(message_id="m2", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": m1, "m2": m2}

        result = await handle_get_inbox_messages(inbox_id="i1")
        assert result["success"] is True
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_get_messages_filter_by_status(self, patch_store_none):
        m1 = _make_message(message_id="m1", inbox_id="i1", status=MessageStatus.OPEN)
        m2 = _make_message(message_id="m2", inbox_id="i1", status=MessageStatus.RESOLVED)
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": m1, "m2": m2}

        result = await handle_get_inbox_messages(inbox_id="i1", status="open")
        assert result["total"] == 1
        assert result["messages"][0]["id"] == "m1"

    @pytest.mark.asyncio
    async def test_get_messages_filter_by_assigned_to(self, patch_store_none):
        m1 = _make_message(message_id="m1", inbox_id="i1", assigned_to="alice")
        m2 = _make_message(message_id="m2", inbox_id="i1", assigned_to="bob")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": m1, "m2": m2}

        result = await handle_get_inbox_messages(inbox_id="i1", assigned_to="alice")
        assert result["total"] == 1
        assert result["messages"][0]["id"] == "m1"

    @pytest.mark.asyncio
    async def test_get_messages_filter_by_tag(self, patch_store_none):
        m1 = _make_message(message_id="m1", inbox_id="i1", tags=["urgent"])
        m2 = _make_message(message_id="m2", inbox_id="i1", tags=["billing"])
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": m1, "m2": m2}

        result = await handle_get_inbox_messages(inbox_id="i1", tag="urgent")
        assert result["total"] == 1
        assert result["messages"][0]["id"] == "m1"

    @pytest.mark.asyncio
    async def test_get_messages_pagination_limit(self, patch_store_none):
        msgs = {}
        for i in range(5):
            m = _make_message(message_id=f"m{i}", inbox_id="i1")
            msgs[f"m{i}"] = m
        with _storage_lock:
            _inbox_messages["i1"] = msgs

        result = await handle_get_inbox_messages(inbox_id="i1", limit=2)
        assert result["total"] == 5
        assert len(result["messages"]) == 2
        assert result["limit"] == 2
        assert result["offset"] == 0

    @pytest.mark.asyncio
    async def test_get_messages_pagination_offset(self, patch_store_none):
        msgs = {}
        for i in range(5):
            m = _make_message(message_id=f"m{i}", inbox_id="i1")
            msgs[f"m{i}"] = m
        with _storage_lock:
            _inbox_messages["i1"] = msgs

        result = await handle_get_inbox_messages(inbox_id="i1", limit=2, offset=3)
        assert result["total"] == 5
        assert len(result["messages"]) == 2
        assert result["offset"] == 3

    @pytest.mark.asyncio
    async def test_get_messages_sorted_by_received_at_desc(self, patch_store_none):
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        t3 = datetime(2026, 1, 3, tzinfo=timezone.utc)
        m1 = _make_message(message_id="m1", inbox_id="i1", received_at=t1)
        m2 = _make_message(message_id="m2", inbox_id="i1", received_at=t3)
        m3 = _make_message(message_id="m3", inbox_id="i1", received_at=t2)
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": m1, "m2": m2, "m3": m3}

        result = await handle_get_inbox_messages(inbox_id="i1")
        ids = [m["id"] for m in result["messages"]]
        assert ids == ["m2", "m3", "m1"]  # newest first

    @pytest.mark.asyncio
    async def test_get_messages_from_store(self, patch_store):
        store = patch_store
        store.get_inbox_messages.return_value = [
            {"id": "m1", "subject": "Hi", "tags": []},
        ]
        result = await handle_get_inbox_messages(inbox_id="i1")
        assert result["success"] is True
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_get_messages_store_tag_filter(self, patch_store):
        store = patch_store
        store.get_inbox_messages.return_value = [
            {"id": "m1", "tags": ["urgent"]},
            {"id": "m2", "tags": ["billing"]},
        ]
        result = await handle_get_inbox_messages(inbox_id="i1", tag="urgent")
        assert result["total"] == 1
        assert result["messages"][0]["id"] == "m1"

    @pytest.mark.asyncio
    async def test_get_messages_store_error_returns_failure(self, patch_store):
        store = patch_store
        store.get_inbox_messages.side_effect = RuntimeError("db down")
        m1 = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": m1}

        result = await handle_get_inbox_messages(inbox_id="i1")
        assert result["success"] is False
        assert "storage" in result["error"].lower() or "failed" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_messages_store_uses_list_inbox_messages_fallback(self, mock_store):
        """When store has list_inbox_messages but not get_inbox_messages."""
        del mock_store.get_inbox_messages
        mock_store.list_inbox_messages.return_value = [
            {"id": "m1", "tags": []},
        ]
        with patch(
            "aragora.server.handlers.shared_inbox.inbox_handlers._get_store",
            return_value=mock_store,
        ):
            result = await handle_get_inbox_messages(inbox_id="i1")
        assert result["success"] is True
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_get_messages_combined_filters(self, patch_store_none):
        m1 = _make_message(
            message_id="m1",
            inbox_id="i1",
            status=MessageStatus.OPEN,
            assigned_to="alice",
            tags=["urgent"],
        )
        m2 = _make_message(
            message_id="m2",
            inbox_id="i1",
            status=MessageStatus.OPEN,
            assigned_to="bob",
            tags=["urgent"],
        )
        m3 = _make_message(
            message_id="m3",
            inbox_id="i1",
            status=MessageStatus.RESOLVED,
            assigned_to="alice",
            tags=["urgent"],
        )
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": m1, "m2": m2, "m3": m3}

        result = await handle_get_inbox_messages(
            inbox_id="i1", status="open", assigned_to="alice", tag="urgent"
        )
        assert result["total"] == 1
        assert result["messages"][0]["id"] == "m1"

    @pytest.mark.asyncio
    async def test_get_messages_store_returns_empty_with_cache(self, patch_store):
        """Store returns empty but cache has messages -> falls to in-memory."""
        store = patch_store
        store.get_inbox_messages.return_value = []
        m1 = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": m1}

        result = await handle_get_inbox_messages(inbox_id="i1")
        assert result["success"] is True
        # Store returned [] but cache has messages, so messages_data is set to None
        # then falls through to in-memory path
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_get_messages_store_pagination_total_count(self, patch_store):
        """When store results hit limit, a second query estimates total."""
        store = patch_store
        page_data = [{"id": f"m{i}", "tags": []} for i in range(3)]
        all_data = [{"id": f"m{i}", "tags": []} for i in range(10)]

        call_count = {"n": 0}

        def side_effect(**kwargs):
            call_count["n"] += 1
            if kwargs.get("limit", 50) == 10000:
                return all_data
            return page_data

        store.get_inbox_messages.side_effect = side_effect
        result = await handle_get_inbox_messages(inbox_id="i1", limit=3)
        assert result["success"] is True
        assert result["total"] == 10


# ===========================================================================
# handle_assign_message
# ===========================================================================


class TestAssignMessage:
    """Tests for handle_assign_message."""

    @pytest.mark.asyncio
    async def test_assign_message_not_found(self, patch_store_none):
        result = await handle_assign_message(
            inbox_id="i1", message_id="m_missing", assigned_to="alice"
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_assign_message_basic(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_assign_message(inbox_id="i1", message_id="m1", assigned_to="alice")
        assert result["success"] is True
        assert result["message"]["assigned_to"] == "alice"

    @pytest.mark.asyncio
    async def test_assign_updates_status_to_assigned(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1", status=MessageStatus.OPEN)
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_assign_message(inbox_id="i1", message_id="m1", assigned_to="alice")
        assert result["message"]["status"] == "assigned"

    @pytest.mark.asyncio
    async def test_assign_does_not_change_non_open_status(
        self, patch_store_none, patch_log_activity
    ):
        msg = _make_message(message_id="m1", inbox_id="i1", status=MessageStatus.IN_PROGRESS)
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_assign_message(inbox_id="i1", message_id="m1", assigned_to="bob")
        assert result["message"]["status"] == "in_progress"
        assert result["message"]["assigned_to"] == "bob"

    @pytest.mark.asyncio
    async def test_assign_sets_assigned_at(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_assign_message(inbox_id="i1", message_id="m1", assigned_to="alice")
        assert result["message"]["assigned_at"] is not None

    @pytest.mark.asyncio
    async def test_assign_logs_activity(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_assign_message(
            inbox_id="i1",
            message_id="m1",
            assigned_to="alice",
            assigned_by="admin",
            org_id="org_1",
        )
        patch_log_activity.assert_called_once()
        call_kwargs = patch_log_activity.call_args
        assert call_kwargs[1]["action"] == "assigned"
        assert call_kwargs[1]["actor_id"] == "admin"

    @pytest.mark.asyncio
    async def test_assign_logs_reassigned_action(self, patch_store_none, patch_log_activity):
        msg = _make_message(
            message_id="m1",
            inbox_id="i1",
            status=MessageStatus.ASSIGNED,
            assigned_to="bob",
        )
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_assign_message(
            inbox_id="i1",
            message_id="m1",
            assigned_to="alice",
            org_id="org_1",
        )
        call_kwargs = patch_log_activity.call_args
        assert call_kwargs[1]["action"] == "reassigned"
        assert call_kwargs[1]["metadata"]["previous_assignee"] == "bob"

    @pytest.mark.asyncio
    async def test_assign_no_activity_without_org_id(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_assign_message(inbox_id="i1", message_id="m1", assigned_to="alice")
        patch_log_activity.assert_not_called()

    @pytest.mark.asyncio
    async def test_assign_persists_to_store_update_message_status(
        self, patch_store, patch_log_activity
    ):
        store = patch_store
        msg = _make_message(message_id="m1", inbox_id="i1", status=MessageStatus.OPEN)
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_assign_message(inbox_id="i1", message_id="m1", assigned_to="alice")
        assert result["success"] is True
        store.update_message_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_assign_persists_to_store_update_message_fallback(
        self, mock_store, patch_log_activity
    ):
        """When store lacks update_message_status, uses update_message."""
        del mock_store.update_message_status
        msg = _make_message(message_id="m1", inbox_id="i1", status=MessageStatus.OPEN)
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        with patch(
            "aragora.server.handlers.shared_inbox.inbox_handlers._get_store",
            return_value=mock_store,
        ):
            result = await handle_assign_message(
                inbox_id="i1", message_id="m1", assigned_to="alice"
            )
        assert result["success"] is True
        mock_store.update_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_assign_store_error_handled(self, mock_store, patch_log_activity):
        mock_store.update_message_status.side_effect = OSError("fail")
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        with patch(
            "aragora.server.handlers.shared_inbox.inbox_handlers._get_store",
            return_value=mock_store,
        ):
            result = await handle_assign_message(
                inbox_id="i1", message_id="m1", assigned_to="alice"
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_assign_default_actor_is_system(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_assign_message(
            inbox_id="i1", message_id="m1", assigned_to="alice", org_id="org_1"
        )
        call_kwargs = patch_log_activity.call_args
        assert call_kwargs[1]["actor_id"] == "system"


# ===========================================================================
# handle_update_message_status
# ===========================================================================


class TestUpdateMessageStatus:
    """Tests for handle_update_message_status."""

    @pytest.mark.asyncio
    async def test_update_status_not_found(self, patch_store_none):
        result = await handle_update_message_status(
            inbox_id="i1", message_id="m_missing", status="resolved"
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_status_basic(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1", status=MessageStatus.OPEN)
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_update_message_status(
            inbox_id="i1", message_id="m1", status="in_progress"
        )
        assert result["success"] is True
        assert result["message"]["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_status_resolved_sets_metadata(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_update_message_status(
            inbox_id="i1",
            message_id="m1",
            status="resolved",
            updated_by="admin1",
        )
        assert result["success"] is True
        assert result["message"]["resolved_at"] is not None
        assert result["message"]["resolved_by"] == "admin1"

    @pytest.mark.asyncio
    async def test_update_status_invalid_value(self, patch_store_none):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_update_message_status(
            inbox_id="i1", message_id="m1", status="invalid_status"
        )
        assert result["success"] is False
        assert "invalid status" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_status_logs_activity(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1", status=MessageStatus.OPEN)
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_update_message_status(
            inbox_id="i1",
            message_id="m1",
            status="assigned",
            updated_by="admin",
            org_id="org_1",
        )
        patch_log_activity.assert_called_once()
        kw = patch_log_activity.call_args[1]
        assert kw["action"] == "status_changed"
        assert kw["metadata"]["from_status"] == "open"
        assert kw["metadata"]["to_status"] == "assigned"

    @pytest.mark.asyncio
    async def test_update_status_no_activity_without_org(
        self, patch_store_none, patch_log_activity
    ):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_update_message_status(inbox_id="i1", message_id="m1", status="closed")
        patch_log_activity.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_status_persists_to_store(self, patch_store, patch_log_activity):
        store = patch_store
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_update_message_status(
            inbox_id="i1", message_id="m1", status="resolved", updated_by="admin"
        )
        assert result["success"] is True
        store.update_message_status.assert_called_once_with("m1", "resolved")

    @pytest.mark.asyncio
    async def test_update_status_store_update_message_fallback(
        self, mock_store, patch_log_activity
    ):
        del mock_store.update_message_status
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        with patch(
            "aragora.server.handlers.shared_inbox.inbox_handlers._get_store",
            return_value=mock_store,
        ):
            result = await handle_update_message_status(
                inbox_id="i1", message_id="m1", status="resolved", updated_by="u1"
            )
        assert result["success"] is True
        mock_store.update_message.assert_called_once()
        updates = mock_store.update_message.call_args[0][1]
        assert updates["status"] == "resolved"
        assert "resolved_at" in updates
        assert updates["resolved_by"] == "u1"

    @pytest.mark.asyncio
    async def test_update_status_store_error_handled(self, mock_store, patch_log_activity):
        mock_store.update_message_status.side_effect = ValueError("bad")
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        with patch(
            "aragora.server.handlers.shared_inbox.inbox_handlers._get_store",
            return_value=mock_store,
        ):
            result = await handle_update_message_status(
                inbox_id="i1", message_id="m1", status="closed"
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_status_all_valid_statuses(self, patch_store_none, patch_log_activity):
        """Verify all MessageStatus values are accepted."""
        for status in MessageStatus:
            msg = _make_message(message_id="m1", inbox_id="i1", status=MessageStatus.OPEN)
            with _storage_lock:
                _inbox_messages["i1"] = {"m1": msg}

            result = await handle_update_message_status(
                inbox_id="i1", message_id="m1", status=status.value
            )
            assert result["success"] is True, f"Failed for status {status.value}"

    @pytest.mark.asyncio
    async def test_update_status_default_actor_is_system(
        self, patch_store_none, patch_log_activity
    ):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_update_message_status(
            inbox_id="i1", message_id="m1", status="closed", org_id="org_1"
        )
        kw = patch_log_activity.call_args[1]
        assert kw["actor_id"] == "system"


# ===========================================================================
# handle_add_message_tag
# ===========================================================================


class TestAddMessageTag:
    """Tests for handle_add_message_tag."""

    @pytest.mark.asyncio
    async def test_add_tag_message_not_found(self, patch_store_none):
        result = await handle_add_message_tag(inbox_id="i1", message_id="m_missing", tag="urgent")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_add_tag_basic(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_add_message_tag(inbox_id="i1", message_id="m1", tag="urgent")
        assert result["success"] is True
        assert "urgent" in result["message"]["tags"]

    @pytest.mark.asyncio
    async def test_add_tag_idempotent(self, patch_store_none, patch_log_activity):
        """Adding the same tag twice should not duplicate it."""
        msg = _make_message(message_id="m1", inbox_id="i1", tags=["urgent"])
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        result = await handle_add_message_tag(inbox_id="i1", message_id="m1", tag="urgent")
        assert result["success"] is True
        assert result["message"]["tags"].count("urgent") == 1

    @pytest.mark.asyncio
    async def test_add_tag_multiple_tags(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_add_message_tag(inbox_id="i1", message_id="m1", tag="urgent")
        result = await handle_add_message_tag(inbox_id="i1", message_id="m1", tag="billing")
        assert "urgent" in result["message"]["tags"]
        assert "billing" in result["message"]["tags"]

    @pytest.mark.asyncio
    async def test_add_tag_logs_activity_on_new_tag(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_add_message_tag(
            inbox_id="i1",
            message_id="m1",
            tag="urgent",
            added_by="admin",
            org_id="org_1",
        )
        patch_log_activity.assert_called_once()
        kw = patch_log_activity.call_args[1]
        assert kw["action"] == "tag_added"
        assert kw["metadata"]["tag"] == "urgent"

    @pytest.mark.asyncio
    async def test_add_tag_no_activity_on_duplicate(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1", tags=["urgent"])
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_add_message_tag(inbox_id="i1", message_id="m1", tag="urgent", org_id="org_1")
        patch_log_activity.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_tag_no_activity_without_org(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_add_message_tag(inbox_id="i1", message_id="m1", tag="urgent")
        patch_log_activity.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_tag_default_actor_system(self, patch_store_none, patch_log_activity):
        msg = _make_message(message_id="m1", inbox_id="i1")
        with _storage_lock:
            _inbox_messages["i1"] = {"m1": msg}

        await handle_add_message_tag(inbox_id="i1", message_id="m1", tag="t1", org_id="org_1")
        kw = patch_log_activity.call_args[1]
        assert kw["actor_id"] == "system"


# ===========================================================================
# handle_add_message_to_inbox
# ===========================================================================


class TestAddMessageToInbox:
    """Tests for handle_add_message_to_inbox."""

    @pytest.mark.asyncio
    async def test_add_message_basic(self, patch_store_none):
        result = await handle_add_message_to_inbox(
            inbox_id="i1",
            email_id="email_001",
            subject="Test Subject",
            from_address="sender@test.com",
            to_addresses=["inbox@company.com"],
            snippet="Hello world",
        )
        assert result["success"] is True
        msg = result["message"]
        assert msg["subject"] == "Test Subject"
        assert msg["from_address"] == "sender@test.com"
        assert msg["to_addresses"] == ["inbox@company.com"]
        assert msg["snippet"] == "Hello world"
        assert msg["status"] == "open"
        assert msg["id"].startswith("msg_")

    @pytest.mark.asyncio
    async def test_add_message_with_optional_fields(self, patch_store_none):
        ts = datetime(2026, 2, 1, tzinfo=timezone.utc)
        result = await handle_add_message_to_inbox(
            inbox_id="i1",
            email_id="email_002",
            subject="Important",
            from_address="ceo@company.com",
            to_addresses=["inbox@company.com"],
            snippet="Urgent matter",
            received_at=ts,
            thread_id="thread_abc",
            priority="high",
        )
        assert result["success"] is True
        msg = result["message"]
        assert msg["thread_id"] == "thread_abc"
        assert msg["priority"] == "high"
        assert "2026-02-01" in msg["received_at"]

    @pytest.mark.asyncio
    async def test_add_message_stored_in_memory(self, patch_store_none):
        # Pre-create inbox entry
        with _storage_lock:
            _inbox_messages["i1"] = {}

        result = await handle_add_message_to_inbox(
            inbox_id="i1",
            email_id="e1",
            subject="S",
            from_address="a@b.com",
            to_addresses=["x@y.com"],
            snippet="snip",
        )
        msg_id = result["message"]["id"]
        with _storage_lock:
            assert msg_id in _inbox_messages["i1"]

    @pytest.mark.asyncio
    async def test_add_message_creates_inbox_entry_if_missing(self, patch_store_none):
        """If inbox_id not in _inbox_messages, it gets created."""
        result = await handle_add_message_to_inbox(
            inbox_id="new_inbox",
            email_id="e1",
            subject="S",
            from_address="a@b.com",
            to_addresses=["x@y.com"],
            snippet="snip",
        )
        assert result["success"] is True
        with _storage_lock:
            assert "new_inbox" in _inbox_messages

    @pytest.mark.asyncio
    async def test_add_message_persists_to_store(self, patch_store):
        store = patch_store
        store.get_shared_inbox.return_value = {"workspace_id": "ws_1"}
        result = await handle_add_message_to_inbox(
            inbox_id="i1",
            email_id="e1",
            subject="S",
            from_address="a@b.com",
            to_addresses=["x@y.com"],
            snippet="snip",
        )
        assert result["success"] is True
        store.save_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_message_store_error_handled(self, mock_store):
        mock_store.save_message.side_effect = OSError("fail")
        mock_store.get_shared_inbox.return_value = {"workspace_id": "ws_1"}
        with patch(
            "aragora.server.handlers.shared_inbox.inbox_handlers._get_store",
            return_value=mock_store,
        ):
            result = await handle_add_message_to_inbox(
                inbox_id="i1",
                email_id="e1",
                subject="S",
                from_address="a@b.com",
                to_addresses=["x@y.com"],
                snippet="snip",
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_add_message_default_received_at(self, patch_store_none):
        result = await handle_add_message_to_inbox(
            inbox_id="i1",
            email_id="e1",
            subject="S",
            from_address="a@b.com",
            to_addresses=["x@y.com"],
            snippet="snip",
        )
        assert result["success"] is True
        # received_at should be auto-set
        assert result["message"]["received_at"] is not None

    @pytest.mark.asyncio
    async def test_add_message_workspace_from_store(self, patch_store):
        """workspace_id is fetched from store when not provided."""
        store = patch_store
        store.get_shared_inbox.return_value = {"workspace_id": "ws_from_store"}
        await handle_add_message_to_inbox(
            inbox_id="i1",
            email_id="e1",
            subject="S",
            from_address="a@b.com",
            to_addresses=["x@y.com"],
            snippet="snip",
        )
        call_kwargs = store.save_message.call_args[1]
        assert call_kwargs["workspace_id"] == "ws_from_store"

    @pytest.mark.asyncio
    async def test_add_message_workspace_default_when_store_returns_none(self, patch_store):
        store = patch_store
        store.get_shared_inbox.return_value = None
        await handle_add_message_to_inbox(
            inbox_id="i1",
            email_id="e1",
            subject="S",
            from_address="a@b.com",
            to_addresses=["x@y.com"],
            snippet="snip",
        )
        call_kwargs = store.save_message.call_args[1]
        assert call_kwargs["workspace_id"] == "default"

    @pytest.mark.asyncio
    async def test_add_message_workspace_explicit(self, patch_store):
        store = patch_store
        await handle_add_message_to_inbox(
            inbox_id="i1",
            email_id="e1",
            subject="S",
            from_address="a@b.com",
            to_addresses=["x@y.com"],
            snippet="snip",
            workspace_id="explicit_ws",
        )
        call_kwargs = store.save_message.call_args[1]
        assert call_kwargs["workspace_id"] == "explicit_ws"

    @pytest.mark.asyncio
    async def test_add_multiple_messages(self, patch_store_none):
        with _storage_lock:
            _inbox_messages["i1"] = {}

        for i in range(5):
            result = await handle_add_message_to_inbox(
                inbox_id="i1",
                email_id=f"e{i}",
                subject=f"S{i}",
                from_address="a@b.com",
                to_addresses=["x@y.com"],
                snippet=f"snip{i}",
            )
            assert result["success"] is True

        with _storage_lock:
            assert len(_inbox_messages["i1"]) == 5


# ===========================================================================
# Integration / Cross-Handler Tests
# ===========================================================================


class TestCrossHandlerIntegration:
    """Tests that exercise multiple handlers together."""

    @pytest.mark.asyncio
    async def test_create_then_list(self, patch_store_none):
        await handle_create_shared_inbox(workspace_id="ws_1", name="Inbox A")
        await handle_create_shared_inbox(workspace_id="ws_1", name="Inbox B")
        await handle_create_shared_inbox(workspace_id="ws_2", name="Inbox C")

        result = await handle_list_shared_inboxes(workspace_id="ws_1")
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_create_then_get(self, patch_store_none):
        create_result = await handle_create_shared_inbox(workspace_id="ws_1", name="My Inbox")
        inbox_id = create_result["inbox"]["id"]

        get_result = await handle_get_shared_inbox(inbox_id=inbox_id)
        assert get_result["success"] is True
        assert get_result["inbox"]["name"] == "My Inbox"

    @pytest.mark.asyncio
    async def test_add_message_then_get_messages(self, patch_store_none):
        create_result = await handle_create_shared_inbox(workspace_id="ws_1", name="Test")
        inbox_id = create_result["inbox"]["id"]

        await handle_add_message_to_inbox(
            inbox_id=inbox_id,
            email_id="e1",
            subject="Hello",
            from_address="a@b.com",
            to_addresses=["x@y.com"],
            snippet="preview",
        )

        msgs_result = await handle_get_inbox_messages(inbox_id=inbox_id)
        assert msgs_result["total"] == 1
        assert msgs_result["messages"][0]["subject"] == "Hello"

    @pytest.mark.asyncio
    async def test_add_message_assign_then_filter(self, patch_store_none, patch_log_activity):
        with _storage_lock:
            _inbox_messages["i1"] = {}

        add_result = await handle_add_message_to_inbox(
            inbox_id="i1",
            email_id="e1",
            subject="Test",
            from_address="a@b.com",
            to_addresses=["x@y.com"],
            snippet="snip",
        )
        msg_id = add_result["message"]["id"]

        await handle_assign_message(inbox_id="i1", message_id=msg_id, assigned_to="alice")

        result = await handle_get_inbox_messages(inbox_id="i1", assigned_to="alice")
        assert result["total"] == 1

        result = await handle_get_inbox_messages(inbox_id="i1", assigned_to="bob")
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_add_message_tag_then_filter(self, patch_store_none, patch_log_activity):
        with _storage_lock:
            _inbox_messages["i1"] = {}

        add_result = await handle_add_message_to_inbox(
            inbox_id="i1",
            email_id="e1",
            subject="Test",
            from_address="a@b.com",
            to_addresses=["x@y.com"],
            snippet="snip",
        )
        msg_id = add_result["message"]["id"]

        await handle_add_message_tag(inbox_id="i1", message_id=msg_id, tag="vip")

        result = await handle_get_inbox_messages(inbox_id="i1", tag="vip")
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, patch_store_none, patch_log_activity):
        """Create inbox -> add message -> assign -> update status -> resolve."""
        create_result = await handle_create_shared_inbox(workspace_id="ws_1", name="Lifecycle")
        inbox_id = create_result["inbox"]["id"]

        add_result = await handle_add_message_to_inbox(
            inbox_id=inbox_id,
            email_id="e1",
            subject="Lifecycle Test",
            from_address="customer@example.com",
            to_addresses=["support@company.com"],
            snippet="I need help",
        )
        msg_id = add_result["message"]["id"]
        assert add_result["message"]["status"] == "open"

        assign_result = await handle_assign_message(
            inbox_id=inbox_id, message_id=msg_id, assigned_to="agent1"
        )
        assert assign_result["message"]["status"] == "assigned"

        progress_result = await handle_update_message_status(
            inbox_id=inbox_id, message_id=msg_id, status="in_progress"
        )
        assert progress_result["message"]["status"] == "in_progress"

        resolve_result = await handle_update_message_status(
            inbox_id=inbox_id,
            message_id=msg_id,
            status="resolved",
            updated_by="agent1",
        )
        assert resolve_result["message"]["status"] == "resolved"
        assert resolve_result["message"]["resolved_by"] == "agent1"
        assert resolve_result["message"]["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_get_inbox_counts_after_operations(self, patch_store_none, patch_log_activity):
        """Inbox counts should reflect current message states."""
        create_result = await handle_create_shared_inbox(workspace_id="ws_1", name="Counts")
        inbox_id = create_result["inbox"]["id"]

        # Add 3 messages
        msg_ids = []
        for i in range(3):
            r = await handle_add_message_to_inbox(
                inbox_id=inbox_id,
                email_id=f"e{i}",
                subject=f"Msg {i}",
                from_address="a@b.com",
                to_addresses=["x@y.com"],
                snippet="snip",
            )
            msg_ids.append(r["message"]["id"])

        # Assign first, resolve second
        await handle_assign_message(inbox_id=inbox_id, message_id=msg_ids[0], assigned_to="alice")
        await handle_update_message_status(
            inbox_id=inbox_id, message_id=msg_ids[1], status="resolved"
        )

        get_result = await handle_get_shared_inbox(inbox_id=inbox_id)
        assert get_result["inbox"]["message_count"] == 3
        # Only m2 (index 2) is still OPEN
        assert get_result["inbox"]["unread_count"] == 1
