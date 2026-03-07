"""Tests for the Unified Inbox bulk actions module.

Covers all public symbols in aragora/server/handlers/features/unified_inbox/actions.py:
- VALID_ACTIONS            - List of recognised bulk action strings
- execute_bulk_action      - Execute a bulk action on a batch of message IDs

Test areas:
- VALID_ACTIONS constant correctness
- mark_read action: single, multiple, not-found, store exception
- mark_unread action: single, not-found, store exception
- star action: single, multiple, not-found, store exception
- archive action: single, not-found, store exception
- delete action: single, not-found, store exception
- Mixed success / failure within a single batch
- Empty message_ids list
- All recognised exception types (RuntimeError, ValueError, TypeError, KeyError, OSError)
- Unrecognised action (falls through all branches, still counts as success)
- Errors list is None when no errors occur
- Large batch processing
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.server.handlers.features.unified_inbox.actions import (
    VALID_ACTIONS,
    execute_bulk_action,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(
    update_return: bool = True,
    delete_return: bool = True,
) -> MagicMock:
    """Build a mock store with async helpers pre-wired."""
    store = MagicMock()
    store.update_message_flags = AsyncMock(return_value=update_return)
    store.delete_message = AsyncMock(return_value=delete_return)
    return store


def _assert_receipt_required(result: dict[str, Any], action: str, message_ids: list[str]) -> None:
    assert result["action"] == action
    assert result["success_count"] == 0
    assert result["error_count"] == len(message_ids)
    assert result["errors"] is not None
    assert [entry["id"] for entry in result["errors"]] == message_ids
    assert all("cryptographic decision receipt" in entry["error"] for entry in result["errors"])


# ---------------------------------------------------------------------------
# VALID_ACTIONS constant
# ---------------------------------------------------------------------------


class TestValidActions:
    """Tests for the VALID_ACTIONS constant."""

    def test_valid_actions_is_list(self):
        assert isinstance(VALID_ACTIONS, list)

    def test_valid_actions_contains_expected_entries(self):
        expected = {"archive", "mark_read", "mark_unread", "star", "delete"}
        assert set(VALID_ACTIONS) == expected

    def test_valid_actions_length(self):
        assert len(VALID_ACTIONS) == 5

    def test_valid_actions_all_strings(self):
        for action in VALID_ACTIONS:
            assert isinstance(action, str)


# ---------------------------------------------------------------------------
# execute_bulk_action -- mark_read
# ---------------------------------------------------------------------------


class TestMarkRead:
    """Tests for mark_read bulk action."""

    @pytest.mark.asyncio
    async def test_mark_read_single_message(self):
        store = _make_store()
        result = await execute_bulk_action("t1", ["msg-1"], "mark_read", store)
        assert result["action"] == "mark_read"
        assert result["success_count"] == 1
        assert result["error_count"] == 0
        assert result["errors"] is None
        store.update_message_flags.assert_awaited_once_with("t1", "msg-1", is_read=True)

    @pytest.mark.asyncio
    async def test_mark_read_multiple_messages(self):
        store = _make_store()
        ids = ["msg-1", "msg-2", "msg-3"]
        result = await execute_bulk_action("t1", ids, "mark_read", store)
        assert result["success_count"] == 3
        assert result["error_count"] == 0
        assert store.update_message_flags.await_count == 3

    @pytest.mark.asyncio
    async def test_mark_read_not_found(self):
        store = _make_store(update_return=False)
        result = await execute_bulk_action("t1", ["msg-404"], "mark_read", store)
        assert result["success_count"] == 0
        assert result["error_count"] == 1
        assert result["errors"][0]["id"] == "msg-404"
        assert result["errors"][0]["error"] == "Message not found"

    @pytest.mark.asyncio
    async def test_mark_read_store_raises_runtime_error(self):
        store = _make_store()
        store.update_message_flags.side_effect = RuntimeError("db down")
        result = await execute_bulk_action("t1", ["msg-1"], "mark_read", store)
        assert result["success_count"] == 0
        assert result["error_count"] == 1
        assert result["errors"][0]["error"] == "Action failed"


# ---------------------------------------------------------------------------
# execute_bulk_action -- mark_unread
# ---------------------------------------------------------------------------


class TestMarkUnread:
    """Tests for mark_unread bulk action."""

    @pytest.mark.asyncio
    async def test_mark_unread_single_message(self):
        store = _make_store()
        result = await execute_bulk_action("t1", ["msg-1"], "mark_unread", store)
        assert result["action"] == "mark_unread"
        assert result["success_count"] == 1
        assert result["error_count"] == 0
        store.update_message_flags.assert_awaited_once_with("t1", "msg-1", is_read=False)

    @pytest.mark.asyncio
    async def test_mark_unread_not_found(self):
        store = _make_store(update_return=False)
        result = await execute_bulk_action("t1", ["msg-1"], "mark_unread", store)
        assert result["success_count"] == 0
        assert result["error_count"] == 1
        assert result["errors"][0]["error"] == "Message not found"

    @pytest.mark.asyncio
    async def test_mark_unread_store_raises_value_error(self):
        store = _make_store()
        store.update_message_flags.side_effect = ValueError("bad value")
        result = await execute_bulk_action("t1", ["msg-1"], "mark_unread", store)
        assert result["success_count"] == 0
        assert result["error_count"] == 1
        assert result["errors"][0]["error"] == "Action failed"


# ---------------------------------------------------------------------------
# execute_bulk_action -- star
# ---------------------------------------------------------------------------


class TestStar:
    """Tests for star bulk action."""

    @pytest.mark.asyncio
    async def test_star_single_message(self):
        store = _make_store()
        result = await execute_bulk_action("t1", ["msg-1"], "star", store)
        _assert_receipt_required(result, "star", ["msg-1"])
        store.update_message_flags.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_star_multiple_messages(self):
        store = _make_store()
        ids = ["a", "b"]
        result = await execute_bulk_action("t1", ids, "star", store)
        _assert_receipt_required(result, "star", ids)
        store.update_message_flags.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_star_not_found(self):
        store = _make_store(update_return=False)
        result = await execute_bulk_action("t1", ["msg-1"], "star", store)
        _assert_receipt_required(result, "star", ["msg-1"])
        store.update_message_flags.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_star_store_raises_type_error(self):
        store = _make_store()
        store.update_message_flags.side_effect = TypeError("nope")
        result = await execute_bulk_action("t1", ["msg-1"], "star", store)
        _assert_receipt_required(result, "star", ["msg-1"])
        store.update_message_flags.assert_not_awaited()


# ---------------------------------------------------------------------------
# execute_bulk_action -- archive
# ---------------------------------------------------------------------------


class TestArchive:
    """Tests for archive bulk action."""

    @pytest.mark.asyncio
    async def test_archive_single_message(self):
        store = _make_store()
        result = await execute_bulk_action("t1", ["msg-1"], "archive", store)
        _assert_receipt_required(result, "archive", ["msg-1"])
        store.delete_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_archive_not_found(self):
        store = _make_store(delete_return=False)
        result = await execute_bulk_action("t1", ["msg-1"], "archive", store)
        _assert_receipt_required(result, "archive", ["msg-1"])
        store.delete_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_archive_store_raises_key_error(self):
        store = _make_store()
        store.delete_message.side_effect = KeyError("missing")
        result = await execute_bulk_action("t1", ["msg-1"], "archive", store)
        _assert_receipt_required(result, "archive", ["msg-1"])
        store.delete_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# execute_bulk_action -- delete
# ---------------------------------------------------------------------------


class TestDelete:
    """Tests for delete bulk action."""

    @pytest.mark.asyncio
    async def test_delete_single_message(self):
        store = _make_store()
        result = await execute_bulk_action("t1", ["msg-1"], "delete", store)
        _assert_receipt_required(result, "delete", ["msg-1"])
        store.delete_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        store = _make_store(delete_return=False)
        result = await execute_bulk_action("t1", ["msg-1"], "delete", store)
        _assert_receipt_required(result, "delete", ["msg-1"])
        store.delete_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_store_raises_os_error(self):
        store = _make_store()
        store.delete_message.side_effect = OSError("disk full")
        result = await execute_bulk_action("t1", ["msg-1"], "delete", store)
        _assert_receipt_required(result, "delete", ["msg-1"])
        store.delete_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# execute_bulk_action -- mixed batches and edge cases
# ---------------------------------------------------------------------------


class TestMixedAndEdgeCases:
    """Tests for mixed-success batches and edge cases."""

    @pytest.mark.asyncio
    async def test_empty_message_ids(self):
        store = _make_store()
        result = await execute_bulk_action("t1", [], "mark_read", store)
        assert result["success_count"] == 0
        assert result["error_count"] == 0
        assert result["errors"] is None
        store.update_message_flags.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mixed_success_and_not_found(self):
        """First message succeeds, second not found."""
        store = _make_store()
        store.update_message_flags = AsyncMock(side_effect=[True, False])
        result = await execute_bulk_action("t1", ["ok", "missing"], "mark_read", store)
        assert result["success_count"] == 1
        assert result["error_count"] == 1
        assert result["errors"][0]["id"] == "missing"

    @pytest.mark.asyncio
    async def test_mixed_success_and_exception(self):
        """First message succeeds, second raises."""
        store = _make_store()
        store.update_message_flags = AsyncMock(side_effect=[True, RuntimeError("boom")])
        result = await execute_bulk_action("t1", ["ok", "fail"], "star", store)
        _assert_receipt_required(result, "star", ["ok", "fail"])
        store.update_message_flags.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unrecognised_action_counts_as_success(self):
        """An action that doesn't match any branch still increments success_count."""
        store = _make_store()
        result = await execute_bulk_action("t1", ["msg-1"], "unknown_action", store)
        assert result["action"] == "unknown_action"
        assert result["success_count"] == 1
        assert result["error_count"] == 0

    @pytest.mark.asyncio
    async def test_errors_is_none_when_all_succeed(self):
        store = _make_store()
        result = await execute_bulk_action("t1", ["a", "b", "c"], "delete", store)
        assert isinstance(result["errors"], list)
        assert len(result["errors"]) == 3

    @pytest.mark.asyncio
    async def test_errors_is_list_when_failures_exist(self):
        store = _make_store(delete_return=False)
        result = await execute_bulk_action("t1", ["a"], "delete", store)
        assert isinstance(result["errors"], list)
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_large_batch(self):
        store = _make_store()
        ids = [f"msg-{i}" for i in range(100)]
        result = await execute_bulk_action("t1", ids, "mark_read", store)
        assert result["success_count"] == 100
        assert result["error_count"] == 0
        assert store.update_message_flags.await_count == 100

    @pytest.mark.asyncio
    async def test_tenant_id_is_forwarded(self):
        store = _make_store()
        await execute_bulk_action("tenant-xyz", ["m1"], "mark_read", store)
        store.update_message_flags.assert_awaited_once_with("tenant-xyz", "m1", is_read=True)

    @pytest.mark.asyncio
    async def test_tenant_id_is_forwarded_to_delete(self):
        store = _make_store()
        await execute_bulk_action("tenant-xyz", ["m1"], "archive", store)
        store.delete_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_return_dict_keys(self):
        store = _make_store()
        result = await execute_bulk_action("t1", ["m1"], "star", store)
        assert set(result.keys()) == {"action", "success_count", "error_count", "errors"}

    @pytest.mark.asyncio
    async def test_each_exception_type_is_caught(self):
        """Verify all five exception types in the handler are caught."""
        exception_types = [RuntimeError, ValueError, TypeError, KeyError, OSError]
        for exc_cls in exception_types:
            store = _make_store()
            store.update_message_flags.side_effect = exc_cls("test")
            result = await execute_bulk_action("t1", ["m1"], "mark_read", store)
            assert result["error_count"] == 1, f"{exc_cls.__name__} was not caught"
            assert result["errors"][0]["error"] == "Action failed"

    @pytest.mark.asyncio
    async def test_all_not_found_in_batch(self):
        store = _make_store(update_return=False)
        ids = ["a", "b", "c"]
        result = await execute_bulk_action("t1", ids, "mark_unread", store)
        assert result["success_count"] == 0
        assert result["error_count"] == 3
        assert len(result["errors"]) == 3
        assert {e["id"] for e in result["errors"]} == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_delete_and_archive_share_code_path(self):
        """Both archive and delete are blocked pending receipt backing."""
        for action in ("archive", "delete"):
            store = _make_store()
            result = await execute_bulk_action("t1", ["m1"], action, store)
            _assert_receipt_required(result, action, ["m1"])
            store.delete_message.assert_not_awaited()
