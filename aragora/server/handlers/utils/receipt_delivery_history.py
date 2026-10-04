"""
Shared in-memory receipt delivery history for lightweight server bridges.

This keeps receipt send history available to both the legacy SME delivery
handler and the receipts handler without introducing a heavier persistence
dependency for the demo/live dashboard path.
"""

from __future__ import annotations

from typing import Any

#: Entry field naming the org that owns the delivered receipt; an entry without
#: it is visible to no org, and readers strip it from every response.
DELIVERY_ORG_KEY = "_org_id"

_receipt_delivery_history: list[dict[str, Any]] = []


def get_receipt_delivery_history_store() -> list[dict[str, Any]]:
    """Return the shared mutable in-memory delivery history store."""
    return _receipt_delivery_history
