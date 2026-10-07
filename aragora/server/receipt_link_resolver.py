"""Server-side lookups that let the receipt store prove receipt ownership.

The receipt ownership backfill (``aragora.storage.receipt_ownership``) needs the
owning org of the debate or plan a receipt was generated from. Storage cannot
import the pipeline or server layers, so the server builds this resolver from
its live debate storage and plan store and registers it at startup.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from aragora.storage.receipt_ownership import (
    ReceiptLinkLookupError,
    register_receipt_link_resolver,
)

logger = logging.getLogger(__name__)

_LOOKUP_ERRORS = (sqlite3.Error, OSError, RuntimeError)


class ServerReceiptLinkResolver:
    """Resolves debate orgs from debate storage and plan orgs from the plan store."""

    def __init__(
        self,
        debate_storage: Any | None,
        plan_store_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._debate_storage = debate_storage
        self._plan_store_factory = plan_store_factory or _default_plan_store

    def debate_org_id(self, debate_id: str) -> str | None:
        get_org_id = getattr(self._debate_storage, "get_org_id", None)
        if not callable(get_org_id):
            raise ReceiptLinkLookupError("debate storage is not available")
        try:
            return get_org_id(debate_id)
        except _LOOKUP_ERRORS as exc:
            raise ReceiptLinkLookupError(f"debate lookup failed: {type(exc).__name__}") from exc

    def plan_org_id(self, plan_id: str) -> str | None:
        try:
            store = self._plan_store_factory()
            # Legacy plans have no org until the plan backfill runs, which would
            # read as "no owner" and mark their receipts unknown for good.
            pending = getattr(store, "ownership_backfill_pending", False) is True
            plan = None if pending else store.get(plan_id)
        except _LOOKUP_ERRORS as exc:
            raise ReceiptLinkLookupError(f"plan lookup failed: {type(exc).__name__}") from exc
        if pending:
            raise ReceiptLinkLookupError("the plan ownership backfill has not run yet")
        return getattr(plan, "org_id", None) if plan is not None else None


def _default_plan_store() -> Any:
    from aragora.pipeline.plan_store import get_plan_store

    return get_plan_store()


def install_receipt_link_resolver(debate_storage: Any | None) -> bool:
    """Register the resolver and run the receipt ownership backfill if it is due.

    Returns True when the backfill ran. Failures are logged and leave the
    backfill pending; they never block startup.
    """
    register_receipt_link_resolver(ServerReceiptLinkResolver(debate_storage))
    try:
        from aragora.storage.receipt_store import get_receipt_store

        return get_receipt_store().migrate_ownership()
    except (ImportError, sqlite3.Error, OSError, RuntimeError, ValueError) as exc:
        logger.warning("[init] Receipt ownership backfill did not run: %s", exc)
        return False


def run_deferred_ownership_backfills() -> None:
    """Retry the plan, then the receipt, ownership backfill if either is still due.

    Called once the authoritative user store is registered. Failures are
    logged and leave the backfills pending.
    """
    try:
        from aragora.pipeline.plan_store import get_plan_store
        from aragora.storage.receipt_store import get_receipt_store

        get_plan_store().migrate_ownership()
        get_receipt_store().migrate_ownership()
    except Exception as exc:  # noqa: BLE001 - runs inside server start(); never block startup
        logger.warning("[init] Deferred ownership backfills did not run: %s", exc)


__all__ = [
    "ServerReceiptLinkResolver",
    "install_receipt_link_resolver",
    "run_deferred_ownership_backfills",
]
