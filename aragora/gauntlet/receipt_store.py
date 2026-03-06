"""Durable receipt store with state machine for the inbox trust wedge.

Provides:
- ``ReceiptState`` enum: CREATED -> APPROVED -> EXECUTED | EXPIRED
- ``ReceiptStore``: thread-safe in-memory + optional file persistence
  for signed ``DecisionReceipt`` objects.
- ``get_receipt_store()`` singleton accessor.

The execution safety gate retrieves and *validates* a previously-persisted
receipt by ID instead of building one inline, closing the attestation
inversion gap.
"""

from __future__ import annotations

import enum
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger(__name__)


class ReceiptState(str, enum.Enum):
    """State machine for decision receipts.

    Transitions:
        CREATED  -> APPROVED  (approval gate passes or auto-approved)
        APPROVED -> EXECUTED  (execution confirmed successful)
        CREATED  -> EXPIRED   (receipt not approved within TTL)
        APPROVED -> EXPIRED   (receipt not executed within TTL)
    """

    CREATED = "CREATED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


_VALID_TRANSITIONS: dict[ReceiptState, set[ReceiptState]] = {
    ReceiptState.CREATED: {ReceiptState.APPROVED, ReceiptState.EXPIRED},
    ReceiptState.APPROVED: {ReceiptState.EXECUTED, ReceiptState.EXPIRED},
    ReceiptState.EXECUTED: set(),
    ReceiptState.EXPIRED: set(),
}


@dataclass
class StoredReceipt:
    """A receipt with its current lifecycle state and full signed payload."""

    receipt_id: str
    state: ReceiptState
    receipt_data: dict[str, Any]
    # Signature fields lifted for fast validation
    signature: str | None = None
    signature_key_id: str | None = None
    signed_at: str | None = None
    signature_algorithm: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "state": self.state.value,
            "receipt_data": self.receipt_data,
            "signature": self.signature,
            "signature_key_id": self.signature_key_id,
            "signed_at": self.signed_at,
            "signature_algorithm": self.signature_algorithm,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredReceipt:
        return cls(
            receipt_id=data["receipt_id"],
            state=ReceiptState(data.get("state", "CREATED")),
            receipt_data=data.get("receipt_data", {}),
            signature=data.get("signature"),
            signature_key_id=data.get("signature_key_id"),
            signed_at=data.get("signed_at"),
            signature_algorithm=data.get("signature_algorithm"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class ReceiptStateError(Exception):
    """Raised on invalid state transition."""


class ReceiptStore:
    """Thread-safe receipt store with state machine tracking.

    Stores signed receipts so the execution safety gate can retrieve
    and verify them instead of building fresh receipts inline.
    """

    def __init__(self) -> None:
        self._receipts: dict[str, StoredReceipt] = {}
        self._lock = threading.Lock()

    # -- write operations ------------------------------------------------

    def persist(
        self,
        receipt_id: str,
        receipt_data: dict[str, Any],
        *,
        signature: str | None = None,
        signature_key_id: str | None = None,
        signed_at: str | None = None,
        signature_algorithm: str | None = None,
        state: ReceiptState = ReceiptState.CREATED,
    ) -> StoredReceipt:
        """Persist a signed receipt.  Replaces any existing receipt with
        the same ``receipt_id``."""
        now = datetime.now(timezone.utc).isoformat()
        stored = StoredReceipt(
            receipt_id=receipt_id,
            state=state,
            receipt_data=receipt_data,
            signature=signature,
            signature_key_id=signature_key_id,
            signed_at=signed_at,
            signature_algorithm=signature_algorithm,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._receipts[receipt_id] = stored
        _logger.info("Receipt persisted: %s (state=%s)", receipt_id, state.value)
        return stored

    def transition(self, receipt_id: str, new_state: ReceiptState) -> StoredReceipt:
        """Transition a receipt to a new state.

        Raises:
            KeyError: receipt not found.
            ReceiptStateError: invalid transition.
        """
        with self._lock:
            stored = self._receipts.get(receipt_id)
            if stored is None:
                raise KeyError(f"Receipt {receipt_id!r} not found in store")
            if new_state not in _VALID_TRANSITIONS.get(stored.state, set()):
                raise ReceiptStateError(
                    f"Cannot transition receipt {receipt_id!r} from "
                    f"{stored.state.value} to {new_state.value}"
                )
            stored.state = new_state
            stored.updated_at = datetime.now(timezone.utc).isoformat()
        _logger.info("Receipt state transition: %s -> %s", receipt_id, new_state.value)
        return stored

    # -- read operations -------------------------------------------------

    def get(self, receipt_id: str) -> StoredReceipt | None:
        """Retrieve a stored receipt by ID."""
        with self._lock:
            return self._receipts.get(receipt_id)

    def verify_receipt(self, receipt_id: str) -> bool:
        """Retrieve a stored receipt and verify its signature.

        Returns False if receipt is missing or signature is invalid.
        """
        stored = self.get(receipt_id)
        if stored is None or not stored.signature:
            return False

        try:
            from aragora.gauntlet.signing import (
                SignatureMetadata,
                SignedReceipt,
                get_default_signer,
            )

            signer = get_default_signer()

            # Strip signature fields from receipt data to match signing input
            data_for_verify = dict(stored.receipt_data)
            for key in ("signature", "signature_algorithm", "signature_key_id", "signed_at"):
                data_for_verify.pop(key, None)

            signed = SignedReceipt(
                receipt_data=data_for_verify,
                signature=stored.signature,
                signature_metadata=SignatureMetadata(
                    algorithm=stored.signature_algorithm or "",
                    timestamp=stored.signed_at or "",
                    key_id=stored.signature_key_id or "",
                ),
            )
            return signer.verify(signed)
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
            _logger.warning("Receipt verification failed for %s: %s", receipt_id, exc)
            return False

    def list_receipts(self, *, state: ReceiptState | None = None) -> list[StoredReceipt]:
        """List stored receipts, optionally filtered by state."""
        with self._lock:
            if state is None:
                return list(self._receipts.values())
            return [r for r in self._receipts.values() if r.state == state]


# -- module singleton ---------------------------------------------------

_receipt_store_singleton: ReceiptStore | None = None
_store_lock = threading.Lock()


def get_receipt_store() -> ReceiptStore:
    """Get or create the module-level ReceiptStore singleton."""
    global _receipt_store_singleton
    if _receipt_store_singleton is None:
        with _store_lock:
            if _receipt_store_singleton is None:
                _receipt_store_singleton = ReceiptStore()
    return _receipt_store_singleton


def reset_receipt_store() -> None:
    """Reset the singleton (for testing)."""
    global _receipt_store_singleton
    _receipt_store_singleton = None


__all__ = [
    "ReceiptState",
    "ReceiptStateError",
    "ReceiptStore",
    "StoredReceipt",
    "get_receipt_store",
    "reset_receipt_store",
]
