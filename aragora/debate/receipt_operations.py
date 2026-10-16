"""Receipt operations the debate engine needs on the foundation receipt models.

The debate engine builds, signs and verifies receipts from
:mod:`aragora.models.receipts.gauntlet` without importing the ``aragora.gauntlet``
facade, which is what normally registers the operation adapters. Building a receipt
from a debate result classifies failed agent responses and infers providers, and
signing needs a backend, so :func:`register_debate_receipt_operations` registers those
from packages the debate engine may import: ``aragora.agents.receipt_hooks`` and
``aragora.storage.receipt_signing``.
"""

from __future__ import annotations

from typing import Any

from aragora.agents.receipt_hooks import register_receipt_agent_hooks
from aragora.models.receipts import operations


class _StorageReceiptSigning:
    # Importing aragora.storage.receipt_signing runs the whole storage package init,
    # so it waits for the first signing call.
    def __getattr__(self, name: str) -> Any:
        import aragora.storage.receipt_signing as receipt_signing

        return getattr(receipt_signing, name)


def register_debate_receipt_operations() -> None:
    """Register signing, provider detection and failure classification (idempotent).

    A signing adapter a facade already registered is kept.
    """
    if operations.SIGNING not in operations.registered_operations():
        operations.register_signing(_StorageReceiptSigning())
    register_receipt_agent_hooks()


__all__ = ["register_debate_receipt_operations"]
