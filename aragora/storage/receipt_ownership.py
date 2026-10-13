"""Ownership columns and the one-time ownership backfill for decision receipts.

The ``receipts`` table carries ``org_id``, ``created_by`` and ``ownership_source``:

* ``created``: written when the receipt was saved for an org (a debate or a
  plan run for an authenticated member of that org).
* ``backfilled``: proven by the one-time migration below.
* ``unknown``: the migration could not prove an owner.
* NULL (with a NULL ``org_id``): saved without an owner and not yet assigned.

A NULL ``org_id`` is invisible to every org, whatever the source says.

The backfill runs once, as version 1 of the ``receipt_store`` module in
``_schema_versions``, on SQLite and PostgreSQL alike. A receipt is proven by
the records it was generated from: the debate named by its ``debate_id`` column,
its ``debate_id`` member or ``config_used.debate_id``, and the plan named by its
``plan_id`` member or ``config_used.plan_id``. Each linked record that exists
with an owner contributes that owner's org, and the receipt is backfilled only
when exactly one org results. Missing or unowned linked records prove nothing.
``created_by`` is never backfilled.

The receipt store cannot see debates or plans itself, so the server registers
a :class:`ReceiptLinkResolver`. Until one is registered, or while a linked
record cannot be looked up, the backfill writes nothing, records no version and
is retried by the next ``ReceiptStore.migrate_ownership()`` call (store
construction and server startup both make one).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from typing import Any, Protocol

logger = logging.getLogger(__name__)

OWNERSHIP_CREATED = "created"
OWNERSHIP_BACKFILLED = "backfilled"
OWNERSHIP_UNKNOWN = "unknown"

OWNERSHIP_COLUMNS = ("org_id", "created_by", "ownership_source")

SCHEMA_MODULE = "receipt_store"
SCHEMA_VERSION = 1

UNASSIGNED_CLAUSE = "org_id IS NULL AND ownership_source IS NULL"


class ReceiptLinkLookupError(RuntimeError):
    """A linked debate or plan could not be looked up, so ownership is undetermined."""


class ReceiptLinkResolver(Protocol):
    """Looks up the owning org of the records a receipt was generated from.

    Each method returns the org id of an existing, owned record, or None when
    the record does not exist or has no owner. It raises
    :class:`ReceiptLinkLookupError` when the lookup itself failed.
    """

    def debate_org_id(self, debate_id: str) -> str | None: ...

    def plan_org_id(self, plan_id: str) -> str | None: ...


_registered_resolver: ReceiptLinkResolver | None = None


def register_receipt_link_resolver(resolver: ReceiptLinkResolver | None) -> None:
    """Make ``resolver`` the one the ownership backfill uses (None clears it)."""
    global _registered_resolver
    _registered_resolver = resolver


def get_receipt_link_resolver() -> ReceiptLinkResolver | None:
    """Return the registered resolver, if any."""
    return _registered_resolver


def ownership_values(org_id: Any, created_by: Any) -> tuple[str | None, str | None, str | None]:
    """Ownership column values for a receipt saved for ``org_id`` (all None without one)."""
    org = _clean(org_id)
    if org is None:
        return None, None, None
    return org, _clean(created_by), OWNERSHIP_CREATED


def receipt_links(debate_id: Any, data: Any) -> tuple[list[str], list[str]]:
    """Return the ``(debate_ids, plan_ids)`` a stored receipt was generated from."""
    payload = _json_object(data)
    config = payload.get("config_used")
    config = config if isinstance(config, dict) else {}
    debate_ids = _distinct([debate_id, payload.get("debate_id"), config.get("debate_id")])
    plan_ids = _distinct([payload.get("plan_id"), config.get("plan_id")])
    return debate_ids, plan_ids


def backfill_receipt_ownership(backend: Any, resolver: ReceiptLinkResolver) -> dict[str, int]:
    """Assign proven owners to unassigned receipts and mark the rest ``unknown``.

    ``backend`` is the store's ``DatabaseBackend``. Every decision is made
    before the first write, so a :class:`ReceiptLinkLookupError` leaves the
    table untouched. Returns the backfilled and unknown counts.
    """
    rows = backend.fetch_all(
        f"SELECT receipt_id, debate_id, data_json FROM receipts WHERE {UNASSIGNED_CLAUSE}"  # noqa: S608 -- constant clause
    )
    debate_orgs: dict[str, str | None] = {}
    plan_orgs: dict[str, str | None] = {}

    def lookup(cache: dict[str, str | None], fetch: Callable[[str], Any], key: str) -> str | None:
        if key not in cache:
            cache[key] = _clean(fetch(key))
        return cache[key]

    updates: list[tuple[str | None, str, str]] = []
    for receipt_id, debate_id, data in rows:
        debate_ids, plan_ids = receipt_links(debate_id, data)
        orgs = {lookup(debate_orgs, resolver.debate_org_id, d) for d in debate_ids}
        orgs |= {lookup(plan_orgs, resolver.plan_org_id, p) for p in plan_ids}
        orgs.discard(None)
        org_id = orgs.pop() if len(orgs) == 1 else None
        source = OWNERSHIP_BACKFILLED if org_id else OWNERSHIP_UNKNOWN
        updates.append((org_id, source, receipt_id))

    if updates:
        backend.executemany(
            "UPDATE receipts SET org_id = ?, ownership_source = ? "
            f"WHERE receipt_id = ? AND {UNASSIGNED_CLAUSE}",  # noqa: S608 -- constant clause
            updates,
        )
    backfilled = sum(1 for org_id, _source, _id in updates if org_id)
    counts = {"backfilled": backfilled, "unknown": len(updates) - backfilled}
    logger.info(
        "receipts ownership backfill: backfilled=%d unknown=%d",
        counts["backfilled"],
        counts["unknown"],
    )
    return counts


def migrate_receipt_ownership(
    backend: Any, backend_type: str, resolver: ReceiptLinkResolver
) -> bool:
    """Run the ownership backfill unless already recorded; True when it ran."""
    backend.execute_write(
        """
        CREATE TABLE IF NOT EXISTS _schema_versions (
            module TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    row = backend.fetch_one(
        "SELECT version FROM _schema_versions WHERE module = ?", (SCHEMA_MODULE,)
    )
    if row is not None and row[0] is not None and int(row[0]) >= SCHEMA_VERSION:
        return False

    backfill_receipt_ownership(backend, resolver)
    if backend_type == "postgresql":
        backend.execute_write(
            "INSERT INTO _schema_versions (module, version) VALUES (?, ?) "
            "ON CONFLICT (module) DO UPDATE SET version = EXCLUDED.version",
            (SCHEMA_MODULE, SCHEMA_VERSION),
        )
    else:
        backend.execute_write(
            "INSERT OR REPLACE INTO _schema_versions (module, version, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (SCHEMA_MODULE, SCHEMA_VERSION),
        )
    return True


def _clean(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _distinct(values: Iterable[Any]) -> list[str]:
    seen: list[str] = []
    for value in values:
        cleaned = _clean(value)
        if cleaned is not None and cleaned not in seen:
            seen.append(cleaned)
    return seen


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = [
    "OWNERSHIP_BACKFILLED",
    "OWNERSHIP_COLUMNS",
    "OWNERSHIP_CREATED",
    "OWNERSHIP_UNKNOWN",
    "SCHEMA_MODULE",
    "SCHEMA_VERSION",
    "UNASSIGNED_CLAUSE",
    "ReceiptLinkLookupError",
    "ReceiptLinkResolver",
    "backfill_receipt_ownership",
    "get_receipt_link_resolver",
    "migrate_receipt_ownership",
    "ownership_values",
    "receipt_links",
    "register_receipt_link_resolver",
]
