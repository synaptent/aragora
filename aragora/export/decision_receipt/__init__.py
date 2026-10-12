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
from typing import TYPE_CHECKING

from aragora.models.receipts import legacy as _legacy

if not TYPE_CHECKING:
    sys.modules[__name__] = _legacy

import aragora.storage.receipt_signing as _receipt_signing
from aragora.models.receipts import operations as _operations

_operations.register_signing(_receipt_signing)

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
