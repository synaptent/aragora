"""
Shared in-memory receipt delivery history for lightweight server bridges.

This keeps receipt send history available to both the legacy SME delivery
handler and the receipts handler without introducing a heavier persistence
dependency for the demo/live dashboard path.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

#: Entry field naming the org that owns the delivered receipt; an entry without
#: it is visible to no org, and readers strip it from every response.
DELIVERY_ORG_KEY = "_org_id"

_MAX_ENTRIES = 1000

_receipt_delivery_history: list[dict[str, Any]] = []


def get_receipt_delivery_history_store() -> list[dict[str, Any]]:
    """Return the shared mutable in-memory delivery history store."""
    return _receipt_delivery_history


def record_receipt_delivery(
    *,
    receipt_id: str,
    channel_type: str,
    channel_id: str,
    workspace_id: str | None,
    status: str,
    org_id: str | None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Append one delivery to the history and return the entry.

    ``org_id`` is the org that owns the receipt; only that org's members see
    the entry.
    """
    delivery_result = result or {}
    delivered_at = datetime.now(timezone.utc).isoformat()
    destination_name = (
        delivery_result.get("channel_name")
        or delivery_result.get("channel")
        or delivery_result.get("email_sent_to")
        or channel_id
    )
    message_id = delivery_result.get("message_id") or delivery_result.get("message_ts")
    entry = {
        "id": f"delivery-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{secrets.token_hex(4)}",
        "receiptId": receipt_id,
        "receipt_id": receipt_id,
        "channel": channel_type,
        "channel_type": channel_type,
        "destination": channel_id,
        "channel_id": channel_id,
        "destinationName": destination_name,
        "destination_name": destination_name,
        "deliveredAt": delivered_at,
        "delivered_at": delivered_at,
        "status": status,
        "workspaceId": workspace_id,
        "workspace_id": workspace_id,
        "messageId": message_id,
        "message_id": message_id,
        "errorMessage": error,
        "error_message": error,
        DELIVERY_ORG_KEY: org_id,
    }
    history = get_receipt_delivery_history_store()
    history.append(entry)
    if len(history) > _MAX_ENTRIES:
        del history[:-_MAX_ENTRIES]
    return entry
