"""Receipt-gated executor for inbox trust wedge actions.

Wraps Gmail actions behind receipt validation: every action requires a
persisted ``StoredReceipt`` in ``APPROVED`` state before execution is
permitted.  After a successful Gmail operation the receipt transitions to
``EXECUTED``.  If the receipt is missing, invalid, expired, or not in
the correct state, a ``ReceiptGateError`` is raised and no Gmail
mutation occurs.

Usage::

    from aragora.inbox.receipt_gated_executor import ReceiptGatedExecutor

    executor = ReceiptGatedExecutor(gmail_connector=gmail)
    await executor.execute(receipt_id="abc-123", action="archive", message_id="msg-1")
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.gauntlet.receipt_store import (
    ReceiptState,
    ReceiptStore,
    StoredReceipt,
    get_receipt_store,
)
from aragora.inbox.trust_wedge import AllowedAction

logger = logging.getLogger(__name__)


class ReceiptGateError(Exception):
    """Raised when receipt validation fails before execution."""


class ReceiptGatedExecutor:
    """Executes Gmail actions only after validating a persisted receipt.

    Parameters
    ----------
    gmail_connector:
        An object supporting ``archive_message``, ``star_message``, and
        ``add_label`` async methods.
    receipt_store:
        The ``ReceiptStore`` to validate against.  Defaults to the
        module-level singleton via ``get_receipt_store()``.
    """

    def __init__(
        self,
        gmail_connector: Any,
        receipt_store: ReceiptStore | None = None,
    ) -> None:
        self._gmail = gmail_connector
        self._store = receipt_store or get_receipt_store()

    async def execute(
        self,
        receipt_id: str,
        action: str,
        message_id: str,
        *,
        label_id: str | None = None,
    ) -> StoredReceipt:
        """Validate receipt and execute the corresponding Gmail action.

        Parameters
        ----------
        receipt_id:
            The ID of the persisted receipt to validate.
        action:
            An ``AllowedAction`` value (archive, star, label, ignore).
        message_id:
            The Gmail message ID to act on.
        label_id:
            Required when *action* is ``label``.

        Returns
        -------
        StoredReceipt
            The receipt after transitioning to ``EXECUTED``.

        Raises
        ------
        ReceiptGateError
            If the receipt is missing, not in ``APPROVED`` state, or has
            an invalid signature.
        """
        # 1. Validate receipt exists and is in APPROVED state
        stored = self._store.get(receipt_id)
        if stored is None:
            raise ReceiptGateError(f"No receipt found for ID {receipt_id!r}")

        if stored.state != ReceiptState.APPROVED:
            raise ReceiptGateError(
                f"Receipt {receipt_id!r} is in state {stored.state.value}, expected APPROVED"
            )

        # 2. Verify signature if present
        if stored.signature and not self._store.verify_receipt(receipt_id):
            raise ReceiptGateError(f"Receipt {receipt_id!r} has an invalid signature")

        # 3. Execute the Gmail action
        await self._execute_gmail_action(action, message_id, label_id=label_id)

        # 4. Transition to EXECUTED
        updated = self._store.transition(receipt_id, ReceiptState.EXECUTED)
        logger.info(
            "Receipt-gated execution complete: receipt=%s action=%s message=%s",
            receipt_id,
            action,
            message_id,
        )
        return updated

    async def _execute_gmail_action(
        self,
        action: str,
        message_id: str,
        *,
        label_id: str | None = None,
    ) -> None:
        """Dispatch to the appropriate Gmail connector method.

        Raises on any connector error -- the caller is responsible for
        NOT transitioning the receipt state on failure.
        """
        if action == AllowedAction.ARCHIVE.value:
            await self._gmail.archive_message(message_id)
        elif action == AllowedAction.STAR.value:
            await self._gmail.star_message(message_id)
        elif action == AllowedAction.LABEL.value:
            if label_id is None:
                raise ReceiptGateError("LABEL action requires a label_id")
            await self._gmail.add_label(message_id, label_id)
        elif action == AllowedAction.IGNORE.value:
            # IGNORE is a no-op on the Gmail side, but the receipt
            # still transitions to EXECUTED to close the lifecycle.
            logger.debug("IGNORE action; no Gmail operation for message %s", message_id)
        else:
            raise ReceiptGateError(f"Unknown action: {action!r}")


__all__ = [
    "ReceiptGateError",
    "ReceiptGatedExecutor",
]
