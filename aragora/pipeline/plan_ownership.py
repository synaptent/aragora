"""Ownership columns and the one-time ownership backfill for ``plans.db``.

``plans``, ``plan_executions`` and ``backbone_runs`` carry ``org_id``,
``created_by`` and ``ownership_source``:

* ``created``: written when the record was created by an authenticated user.
* ``backfilled``: proven by the one-time migration below.
* ``unknown``: the migration could not prove an owner.
* NULL (with a NULL ``org_id``): created without an owner and not yet assigned.

A NULL ``org_id`` is invisible to every org, whatever the source says.

The backfill runs once, as version 1 of the ``plan_store`` schema module in
``_schema_versions``. A row is proven only by a server-recorded user id whose
user belongs to exactly one org in the user store:

* execution: ``metadata_json.scheduled_by``;
* backbone run: intake ``origin_metadata.scheduled_by`` and
  ``metadata_json.scheduled_by``;
* plan: the user ids of its linked executions and runs (``plan_id``, or the
  server-set ``metadata.backbone_run_id``). Plan metadata itself is
  request-controlled and never counts.

Every recorded user must resolve to the same single org; anything else is
``unknown``. ``created_by`` is backfilled for executions and runs (their
scheduler created them) but never for plans. Only the three ownership columns
of rows with no ownership yet are written. If the user store cannot be
consulted the backfill writes nothing, records no version and is retried on
the next schema setup.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from typing import Any

from aragora.storage.schema import SchemaManager, safe_add_column
from aragora.tenancy.membership import OrgMembershipResolver

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
    """Assign proven owners to unowned rows and mark the rest ``unknown``.

    Every decision is made before the first write, so a
    ``MembershipLookupError`` from ``resolve_org_ids`` leaves the database
    untouched. Returns backfilled/unknown counts per table.
    """
    users_of: dict[str, dict[str, list[str]]] = {table: {} for table in OWNED_TABLES}
    linked_users: dict[str, list[str]] = {}

    for row in _select(conn, "SELECT execution_id, plan_id, metadata_json FROM plan_executions"):
        users = _user_ids([_json_object(row["metadata_json"]).get("scheduled_by")])
        users_of["plan_executions"][row["execution_id"]] = users
        if row["plan_id"]:
            linked_users.setdefault(row["plan_id"], []).extend(users)

    run_users = users_of["backbone_runs"]
    for row in _select(
        conn, "SELECT run_id, plan_id, intake_bundle_json, metadata_json FROM backbone_runs"
    ):
        origin = _json_object(row["intake_bundle_json"]).get("origin_metadata")
        run_users[row["run_id"]] = _user_ids(
            [
                origin.get("scheduled_by") if isinstance(origin, dict) else None,
                _json_object(row["metadata_json"]).get("scheduled_by"),
            ]
        )
        if row["plan_id"]:
            linked_users.setdefault(row["plan_id"], []).extend(run_users[row["run_id"]])

    for row in _select(conn, "SELECT id, metadata_json FROM plans"):
        linked_run = _json_object(row["metadata_json"]).get("backbone_run_id")
        users_of["plans"][row["id"]] = _user_ids(
            [
                *linked_users.get(row["id"], []),
                *(run_users.get(linked_run, []) if isinstance(linked_run, str) else []),
            ]
        )

    cache: dict[str, frozenset[str]] = {}

    def proven_org(user_ids: list[str]) -> str | None:
        orgs: set[str] = set()
        for user_id in user_ids:
            if user_id not in cache:
                cache[user_id] = frozenset(resolve_org_ids(user_id))
            if len(cache[user_id]) != 1:
                return None
            orgs |= cache[user_id]
        return orgs.pop() if len(orgs) == 1 else None

    decisions: dict[str, list[tuple[str, str | None, str | None]]] = {}
    for table, key in OWNED_TABLES.items():
        query = f"SELECT {key} FROM {table} WHERE {UNASSIGNED_CLAUSE}"  # noqa: S608 -- table/key from OWNED_TABLES
        pending = [row[0] for row in conn.execute(query)]
        decisions[table] = []
        for record_id in pending:
            users = users_of[table].get(record_id, [])
            org_id = proven_org(users)
            # The scheduler of an execution or run created it; a plan's
            # creator is not recorded anywhere, only who later scheduled it.
            created_by = users[0] if org_id and table != "plans" else None
            decisions[table].append((record_id, org_id, created_by))

    counts: dict[str, dict[str, int]] = {}
    for table, rows in decisions.items():
        key = OWNED_TABLES[table]
        backfilled = unknown = 0
        for record_id, org_id, created_by in rows:
            source = OWNERSHIP_BACKFILLED if org_id else OWNERSHIP_UNKNOWN
            cursor = conn.execute(
                f"UPDATE {table} SET org_id = ?, created_by = ?, ownership_source = ? "  # noqa: S608 -- table/key from OWNED_TABLES
                f"WHERE {key} = ? AND {UNASSIGNED_CLAUSE}",
                (org_id, created_by, source, record_id),
            )
            if org_id:
                backfilled += cursor.rowcount
            else:
                unknown += cursor.rowcount
        counts[table] = {"backfilled": backfilled, "unknown": unknown}
        logger.info(
            "plans.db ownership backfill: table=%s backfilled=%d unknown=%d",
            table,
            backfilled,
            unknown,
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
