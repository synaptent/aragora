"""Dry-run follow-up discovery for receipt falsification checks."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def _receipt_get(receipt: Any, key: str, default: Any = None) -> Any:
    if isinstance(receipt, dict):
        return receipt.get(key, default)
    return getattr(receipt, key, default)


def _parse_check_by(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def find_due_falsification_followups(
    receipts: list[Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Return due falsification checks without filing or mutating anything."""
    today = (now or datetime.now(timezone.utc)).date()
    due: list[dict[str, str]] = []
    for receipt in receipts:
        falsification = _receipt_get(receipt, "falsification")
        if not isinstance(falsification, dict):
            continue
        check_by = _parse_check_by(falsification.get("check_by"))
        if check_by is None or check_by > today:
            continue
        observation = falsification.get("observation")
        if not isinstance(observation, str) or not observation.strip():
            continue
        item = {
            "receipt_id": str(_receipt_get(receipt, "receipt_id", "")),
            "observation": observation.strip(),
            "owner": str(falsification.get("owner") or ""),
            "source": str(falsification.get("source") or ""),
            "check_by": check_by.isoformat(),
            "reason": "falsification check_by is due",
        }
        due.append(item)
    return due
