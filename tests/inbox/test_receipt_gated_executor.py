"""Tests for the receipt-gated executor.

Validates that Gmail actions are only executed when a matching receipt
exists in APPROVED state, and that receipt state transitions happen
correctly on success and are skipped on failure.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from aragora.gauntlet.receipt_store import (
    ReceiptState,
    ReceiptStore,
    reset_receipt_store,
)
from aragora.inbox.receipt_gated_executor import (
    ReceiptGateError,
    ReceiptGatedExecutor,
)
from aragora.inbox.trust_wedge import AllowedAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store() -> ReceiptStore:
    """Fresh ReceiptStore for each test (not the singleton)."""
    return ReceiptStore()


@pytest.fixture()
def gmail() -> AsyncMock:
    """Mock Gmail connector with async methods."""
    mock = AsyncMock()
    mock.archive_message = AsyncMock()
    mock.star_message = AsyncMock()
    mock.add_label = AsyncMock()
    return mock


@pytest.fixture()
def executor(gmail: AsyncMock, store: ReceiptStore) -> ReceiptGatedExecutor:
    return ReceiptGatedExecutor(gmail_connector=gmail, receipt_store=store)


def _persist_approved(store: ReceiptStore, receipt_id: str = "r-1") -> None:
    """Helper: persist a receipt and transition to APPROVED."""
    store.persist(
        receipt_id=receipt_id,
        receipt_data={"action": "archive", "message_id": "msg-1"},
    )
    store.transition(receipt_id, ReceiptState.APPROVED)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_archive_succeeds_with_approved_receipt(
    executor: ReceiptGatedExecutor,
    store: ReceiptStore,
    gmail: AsyncMock,
) -> None:
    """ARCHIVE action succeeds when receipt is APPROVED."""
    _persist_approved(store, "r-1")

    result = await executor.execute(
        receipt_id="r-1",
        action=AllowedAction.ARCHIVE.value,
        message_id="msg-1",
    )

    gmail.archive_message.assert_awaited_once_with("msg-1")
    assert result.state == ReceiptState.EXECUTED


@pytest.mark.asyncio
async def test_execute_star_succeeds(
    executor: ReceiptGatedExecutor,
    store: ReceiptStore,
    gmail: AsyncMock,
) -> None:
    """STAR action calls star_message and transitions receipt."""
    _persist_approved(store, "r-2")

    result = await executor.execute(
        receipt_id="r-2",
        action=AllowedAction.STAR.value,
        message_id="msg-2",
    )

    gmail.star_message.assert_awaited_once_with("msg-2")
    assert result.state == ReceiptState.EXECUTED


@pytest.mark.asyncio
async def test_execute_label_succeeds(
    executor: ReceiptGatedExecutor,
    store: ReceiptStore,
    gmail: AsyncMock,
) -> None:
    """LABEL action calls add_label with the provided label_id."""
    _persist_approved(store, "r-3")

    result = await executor.execute(
        receipt_id="r-3",
        action=AllowedAction.LABEL.value,
        message_id="msg-3",
        label_id="Label_42",
    )

    gmail.add_label.assert_awaited_once_with("msg-3", "Label_42")
    assert result.state == ReceiptState.EXECUTED


@pytest.mark.asyncio
async def test_execute_ignore_succeeds_without_gmail_call(
    executor: ReceiptGatedExecutor,
    store: ReceiptStore,
    gmail: AsyncMock,
) -> None:
    """IGNORE validates receipt but makes no Gmail call."""
    _persist_approved(store, "r-4")

    result = await executor.execute(
        receipt_id="r-4",
        action=AllowedAction.IGNORE.value,
        message_id="msg-4",
    )

    # No Gmail methods should have been called
    gmail.archive_message.assert_not_awaited()
    gmail.star_message.assert_not_awaited()
    gmail.add_label.assert_not_awaited()

    # Receipt still transitions to EXECUTED
    assert result.state == ReceiptState.EXECUTED


# ---------------------------------------------------------------------------
# Missing receipt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_fails_when_receipt_missing(
    executor: ReceiptGatedExecutor,
    gmail: AsyncMock,
) -> None:
    """Raises ReceiptGateError when no receipt exists for the given ID."""
    with pytest.raises(ReceiptGateError, match="No receipt found"):
        await executor.execute(
            receipt_id="nonexistent",
            action=AllowedAction.ARCHIVE.value,
            message_id="msg-1",
        )

    gmail.archive_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# Wrong receipt state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_fails_when_receipt_in_created_state(
    executor: ReceiptGatedExecutor,
    store: ReceiptStore,
    gmail: AsyncMock,
) -> None:
    """Raises ReceiptGateError when receipt is still in CREATED state."""
    store.persist(
        receipt_id="r-created",
        receipt_data={"action": "archive"},
    )

    with pytest.raises(ReceiptGateError, match="CREATED.*expected APPROVED"):
        await executor.execute(
            receipt_id="r-created",
            action=AllowedAction.ARCHIVE.value,
            message_id="msg-1",
        )

    gmail.archive_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_fails_when_receipt_already_executed(
    executor: ReceiptGatedExecutor,
    store: ReceiptStore,
    gmail: AsyncMock,
) -> None:
    """Raises ReceiptGateError when receipt is already in EXECUTED state."""
    _persist_approved(store, "r-exec")
    store.transition("r-exec", ReceiptState.EXECUTED)

    with pytest.raises(ReceiptGateError, match="EXECUTED.*expected APPROVED"):
        await executor.execute(
            receipt_id="r-exec",
            action=AllowedAction.ARCHIVE.value,
            message_id="msg-1",
        )

    gmail.archive_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_fails_when_receipt_expired(
    executor: ReceiptGatedExecutor,
    store: ReceiptStore,
    gmail: AsyncMock,
) -> None:
    """Raises ReceiptGateError when receipt is in EXPIRED state."""
    store.persist(
        receipt_id="r-exp",
        receipt_data={"action": "archive"},
    )
    store.transition("r-exp", ReceiptState.EXPIRED)

    with pytest.raises(ReceiptGateError, match="EXPIRED.*expected APPROVED"):
        await executor.execute(
            receipt_id="r-exp",
            action=AllowedAction.ARCHIVE.value,
            message_id="msg-1",
        )

    gmail.archive_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# Receipt state NOT transitioned on Gmail failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receipt_not_transitioned_on_gmail_failure(
    executor: ReceiptGatedExecutor,
    store: ReceiptStore,
    gmail: AsyncMock,
) -> None:
    """Receipt stays APPROVED when the Gmail operation raises."""
    _persist_approved(store, "r-fail")
    gmail.archive_message.side_effect = ConnectionError("Gmail API down")

    with pytest.raises(ConnectionError, match="Gmail API down"):
        await executor.execute(
            receipt_id="r-fail",
            action=AllowedAction.ARCHIVE.value,
            message_id="msg-fail",
        )

    # Receipt must remain APPROVED -- not transitioned
    stored = store.get("r-fail")
    assert stored is not None
    assert stored.state == ReceiptState.APPROVED


# ---------------------------------------------------------------------------
# LABEL without label_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_label_action_requires_label_id(
    executor: ReceiptGatedExecutor,
    store: ReceiptStore,
    gmail: AsyncMock,
) -> None:
    """LABEL action raises ReceiptGateError when label_id is missing."""
    _persist_approved(store, "r-label-no-id")

    with pytest.raises(ReceiptGateError, match="label_id"):
        await executor.execute(
            receipt_id="r-label-no-id",
            action=AllowedAction.LABEL.value,
            message_id="msg-l",
        )

    # Receipt stays APPROVED since execution didn't happen
    stored = store.get("r-label-no-id")
    assert stored is not None
    assert stored.state == ReceiptState.APPROVED


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_action_raises(
    executor: ReceiptGatedExecutor,
    store: ReceiptStore,
    gmail: AsyncMock,
) -> None:
    """Unknown action value raises ReceiptGateError."""
    _persist_approved(store, "r-unk")

    with pytest.raises(ReceiptGateError, match="Unknown action"):
        await executor.execute(
            receipt_id="r-unk",
            action="delete",
            message_id="msg-unk",
        )
