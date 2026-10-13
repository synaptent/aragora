"""Export facade over :mod:`aragora.models.receipts.legacy`.

The legacy decision-receipt family (``DecisionReceipt``,
``SignedDecisionReceipt``, ``ReceiptFinding``, ``ReceiptDissent``,
``ReceiptVerification``, ``DecisionReceiptGenerator`` and helpers) lives in the
foundation layer. This path resolves to that same module object, so
``mock.patch("aragora.export.decision_receipt._load_weasyprint")`` and every
other patch through this path reach the implementation. Importing it registers
the signing adapter the legacy receipts use.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from aragora.models.receipts import legacy as _legacy

if not TYPE_CHECKING:
    sys.modules[__name__] = _legacy

from aragora.models.receipts import operations as _operations


class _DeferredReceiptSigning:
    # Importing aragora.storage.receipt_signing runs the whole storage package init,
    # so it waits for the first signing call instead of loading with this facade.
    def __getattr__(self, name: str) -> Any:
        import aragora.storage.receipt_signing as receipt_signing

        return getattr(receipt_signing, name)


_operations.register_signing(_DeferredReceiptSigning())

if TYPE_CHECKING:
    from aragora.models.receipts.legacy import DecisionReceipt as DecisionReceipt
    from aragora.models.receipts.legacy import (
        DecisionReceiptGenerator as DecisionReceiptGenerator,
    )
    from aragora.models.receipts.legacy import ReceiptDissent as ReceiptDissent
    from aragora.models.receipts.legacy import ReceiptFinding as ReceiptFinding
    from aragora.models.receipts.legacy import ReceiptVerification as ReceiptVerification
    from aragora.models.receipts.legacy import SignedDecisionReceipt as SignedDecisionReceipt
    from aragora.models.receipts.legacy import _load_weasyprint as _load_weasyprint
    from aragora.models.receipts.legacy import (
        generate_decision_receipt as generate_decision_receipt,
    )
    from aragora.models.receipts.legacy import link_receipt_to_trail as link_receipt_to_trail
