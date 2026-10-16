"""Ownership columns and the one-time ownership backfill for ``plans.db``.

``plans``, ``plan_executions`` and ``backbone_runs`` carry ``org_id``,
``created_by`` and ``ownership_source``:

* ``created``: written when the record was created by an authenticated user.
* ``backfilled``: assigned by earlier builds of the one-time migration below;
  it no longer assigns any.
* ``unknown``: the migration could not prove an owner.
* NULL (with a NULL ``org_id``): created without an owner and not yet assigned.

A NULL ``org_id`` is invisible to every org, whatever the source says.

The backfill runs once, as version 1 of the ``plan_store`` schema module in
``_schema_versions``. A row could only be proven by an org the server recorded
on it when it was written, matching the single current org of its recorded
scheduler. Rows written before ownership existed record none: plan metadata
(including its ``org_id``) is request-controlled, and executions and runs
record only the scheduler's user id. A scheduler's current org alone proves
nothing, since the scheduler may have changed orgs, so the backfill marks every
row with no ownership yet ``unknown`` and writes no other column.

The recorded schedulers are looked up first: execution
``metadata_json.scheduled_by``, and run intake
``origin_metadata.scheduled_by`` and ``metadata_json.scheduled_by``. If the
user store cannot be consulted, or places none of them in any org (an empty
store, or not the one those users signed in to), the backfill writes nothing,
records no version and is retried on the next schema setup.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from typing import Any

from aragora.storage.schema import SchemaManager, safe_add_column
from aragora.tenancy.membership import MembershipLookupError, OrgMembershipResolver

logger = logging.getLogger(__name__)

OWNERSHIP_CREATED = "created"
OWNERSHIP_BACKFILLED = "backfilled"
OWNERSHIP_UNKNOWN = "unknown"

OWNED_TABLES: dict[str, str] = {
    "plans": "id",
    "plan_executions": "execution_id",
    "backbone_runs": "run_id",
}
OWNERSHIP_COLUMNS = ("org_id", "created_by", "ownership_source")

SCHEMA_MODULE = "plan_store"
SCHEMA_VERSION = 1

UNASSIGNED_CLAUSE = "org_id IS NULL AND ownership_source IS NULL"


def ensure_ownership_columns(conn: sqlite3.Connection) -> None:
    """Add the ownership columns and an ``org_id`` index to every owned table."""
    for table in OWNED_TABLES:
        for column in OWNERSHIP_COLUMNS:
            safe_add_column(conn, table, column, "TEXT")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_org_id ON {table}(org_id)")
    conn.commit()


def migrate_plan_store_schema(
    conn: sqlite3.Connection, resolve_org_ids: OrgMembershipResolver
) -> bool:
    """Run pending ``plan_store`` migrations; True when one was applied."""
    manager = SchemaManager(conn, SCHEMA_MODULE, current_version=SCHEMA_VERSION)
    manager.register_migration(
        0,
        1,
        function=lambda c: backfill_ownership(c, resolve_org_ids),
        description="backfill plan, execution and backbone run ownership",
    )
    return manager.ensure_schema()


def backfill_ownership(
    conn: sqlite3.Connection, resolve_org_ids: OrgMembershipResolver
) -> dict[str, dict[str, int]]:
    """Mark every unowned row ``unknown``.

    The recorded schedulers are looked up before the first write, so a
    ``MembershipLookupError`` from ``resolve_org_ids``, or one raised because
    no recorded user resolves to any org, leaves the database untouched.
    Returns backfilled/unknown counts per table.
    """
    recorded: list[Any] = []
    for row in _select(conn, "SELECT metadata_json FROM plan_executions"):
        recorded.append(_json_object(row["metadata_json"]).get("scheduled_by"))
    for row in _select(conn, "SELECT intake_bundle_json, metadata_json FROM backbone_runs"):
        origin = _json_object(row["intake_bundle_json"]).get("origin_metadata")
        recorded.append(origin.get("scheduled_by") if isinstance(origin, dict) else None)
        recorded.append(_json_object(row["metadata_json"]).get("scheduled_by"))

    # The backfill is recorded once, so it is only finalized against a user
    # store that knows at least one of the recorded schedulers.
    user_ids = sorted(_user_ids(recorded))
    memberships = [frozenset(resolve_org_ids(user_id)) for user_id in user_ids]
    if user_ids and not any(memberships):
        raise MembershipLookupError("the user store places none of the recorded users in an org")

    counts: dict[str, dict[str, int]] = {}
    for table in OWNED_TABLES:
        cursor = conn.execute(
            f"UPDATE {table} SET ownership_source = ? WHERE {UNASSIGNED_CLAUSE}",  # noqa: S608 -- table from OWNED_TABLES
            (OWNERSHIP_UNKNOWN,),
        )
        counts[table] = {"backfilled": 0, "unknown": cursor.rowcount}
        logger.info(
            "plans.db ownership backfill: table=%s backfilled=0 unknown=%d",
            table,
            cursor.rowcount,
        )
    return counts


def _select(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    cursor = conn.execute(sql)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _user_ids(values: Iterable[Any]) -> list[str]:
    """Distinct non-blank string user ids, in order."""
    seen: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip() and value.strip() not in seen:
            seen.append(value.strip())
    return seen


__all__ = [
    "OWNED_TABLES",
    "OWNERSHIP_BACKFILLED",
    "OWNERSHIP_COLUMNS",
    "OWNERSHIP_CREATED",
    "OWNERSHIP_UNKNOWN",
    "SCHEMA_MODULE",
    "SCHEMA_VERSION",
    "UNASSIGNED_CLAUSE",
    "backfill_ownership",
    "ensure_ownership_columns",
    "migrate_plan_store_schema",
]
