"""
Shared helpers for storing and retrieving decision results.

Centralizes DecisionResultStore usage with an in-memory fallback so
multiple handlers/workers can reuse consistent behavior.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_decision_result_store = None
_decision_results_fallback: dict[str, dict[str, Any]] = {}


def _get_result_store():
    """Get the decision result store for persistence."""
    global _decision_result_store
    if _decision_result_store is None:
        try:
            from aragora.storage.decision_result_store import get_decision_result_store

            _decision_result_store = get_decision_result_store()
        except (ImportError, OSError, RuntimeError, ValueError) as e:
            logger.warning("DecisionResultStore not available, using in-memory: %s", e)
    return _decision_result_store


def save_decision_result(request_id: str, data: dict[str, Any]) -> None:
    """Save a decision result to persistent store with fallback."""
    store = _get_result_store()
    if store:
        try:
            store.save(request_id, data)
            return
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to persist result, using fallback: %s", e)
    _decision_results_fallback[request_id] = data


def without_stored_request(record: dict[str, Any]) -> dict[str, Any]:
    """``record`` as API responses show it, without ``result["request"]``.

    The decision handler keeps the caller's request there so that a retry can
    replay it. It can hold delivery targets such as webhook URLs and email
    addresses, so only the retry path may read it. ``record`` is not changed.
    """
    result = record.get("result")
    if not isinstance(result, dict) or "request" not in result:
        return record
    return {**record, "result": {k: v for k, v in result.items() if k != "request"}}


def get_decision_result(request_id: str) -> dict[str, Any] | None:
    """Get a decision result from persistent store with fallback, for a response."""
    store = _get_result_store()
    if store:
        try:
            result = store.get(request_id)
            if result:
                return without_stored_request(result)
        except (OSError, RuntimeError, KeyError) as e:
            logger.warning("Failed to retrieve from store: %s", e)
    fallback = _decision_results_fallback.get(request_id)
    return None if fallback is None else without_stored_request(fallback)


def get_decision_result_for_org(request_id: str, org_id: str) -> dict[str, Any] | None:
    """Like :func:`get_decision_result`, but only when ``org_id`` owns the result.

    A missing result, another org's and one with no recorded owner all give None.
    """
    if not org_id:
        return None
    store = _get_result_store()
    if store:
        try:
            result = store.get_for_org(request_id, org_id)
            if result:
                return without_stored_request(result)
        except (OSError, RuntimeError, KeyError) as e:
            logger.warning("Failed to retrieve from store: %s", e)
    fallback = _decision_results_fallback.get(request_id)
    if fallback is None or fallback.get("org_id") != org_id:
        return None
    return without_stored_request(fallback)


def get_decision_status_for_org(request_id: str, org_id: str) -> dict[str, Any] | None:
    """Polling status of a result ``org_id`` owns; None when missing, foreign or ownerless."""
    result = get_decision_result_for_org(request_id, org_id)
    if result is None:
        return None
    return {
        "request_id": request_id,
        "status": result.get("status", "unknown"),
        "completed_at": result.get("completed_at"),
    }


def get_decision_status(request_id: str) -> dict[str, Any]:
    """Get decision status for polling with fallback."""
    store = _get_result_store()
    if store:
        try:
            return store.get_status(request_id)
        except (OSError, RuntimeError, KeyError) as e:
            logger.warning("Failed to get status from store: %s", e)

    if request_id in _decision_results_fallback:
        result = _decision_results_fallback[request_id]
        return {
            "request_id": request_id,
            "status": result.get("status", "unknown"),
            "completed_at": result.get("completed_at"),
        }
    return {
        "request_id": request_id,
        "status": "not_found",
    }


__all__ = [
    "save_decision_result",
    "get_decision_result",
    "get_decision_result_for_org",
    "get_decision_status",
    "get_decision_status_for_org",
    "without_stored_request",
]
