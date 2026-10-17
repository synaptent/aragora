"""Receipt lifecycle store (compatibility path).

The store lives in :mod:`aragora.storage.receipt_lifecycle_store`. This path resolves to
that same module object, so patching or resetting ``_receipt_store_singleton`` through
either path changes the one shared store.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.storage import receipt_lifecycle_store as _store

if not TYPE_CHECKING:
    sys.modules[__name__] = _store

if TYPE_CHECKING:
    from aragora.storage.receipt_lifecycle_store import ReceiptState as ReceiptState
    from aragora.storage.receipt_lifecycle_store import ReceiptStateError as ReceiptStateError
    from aragora.storage.receipt_lifecycle_store import ReceiptStore as ReceiptStore
    from aragora.storage.receipt_lifecycle_store import StoredReceipt as StoredReceipt
    from aragora.storage.receipt_lifecycle_store import get_receipt_store as get_receipt_store
    from aragora.storage.receipt_lifecycle_store import (
        reset_receipt_store as reset_receipt_store,
    )
